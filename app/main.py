from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.actions import ActionIntentService, ActionStore
from app import repository
from app.audit import get_events
from app.config import ActionSettings
from app.connectors import ConnectorBundle, EnterpriseToolService, create_connector_bundle
from app.errors import ResolutionError
from app.models import ActionIntent, DemoStatus, RequestDocumentInput, ResolutionRecommendation
from app.reasoner import Reasoner, RuleBasedReasoner, create_reasoner
from app.service import resolve_exception

APP_VERSION = "0.4.0"
DEMO_DIR = Path(__file__).resolve().parent / "demo"
DETERMINISTIC_DEMO_CASES = frozenset({"EX-002"})

DEMO_CASES = (
    {
        "exception_id": "EX-001", "label": "Missing commercial invoice",
        "title": "Critical delivery at risk",
        "question": "What is blocking the shipment, and what evidence supports the next action?",
        "impact": "Delivery at risk", "strategy": "Configured reasoner",
        "report_summary": "Awaiting a corrected commercial invoice",
    },
    {
        "exception_id": "EX-002", "label": "Deterministic weather delay",
        "title": "Port closure delays sailing",
        "question": "Can a known operational status be handled without an LLM?",
        "impact": "Delivery at risk", "strategy": "Deterministic baseline",
        "report_summary": "Port closed by severe storm; next sailing unconfirmed",
    },
    {
        "exception_id": "EX-003", "label": "Ambiguous carrier update",
        "title": "Conflicting shipment status",
        "question": "What can be concluded when source records disagree?",
        "impact": "Manual investigation likely", "strategy": "Configured reasoner",
        "report_summary": "Carrier and tracking updates conflict; reliable timestamps are missing",
    },
    {
        "exception_id": "EX-004", "label": "Missing shipment evidence",
        "title": "Required evidence unavailable",
        "question": "Will the workflow stop instead of guessing?",
        "impact": "Fail-closed demonstration", "strategy": "No reasoning if evidence is missing",
        "report_summary": "Unavailable — analysis must stop",
    },
)


def demo_cases() -> list[dict]:
    cases = []
    for definition in DEMO_CASES:
        exception = repository.get_exception(definition["exception_id"])
        order = repository.get_order(exception["order_id"])
        shipment = repository.get_shipment(exception["shipment_id"])
        cases.append({
            **definition,
            "order_request": f'{order["order_id"]} · {order["requested_delivery_date"]}',
            "carrier_status": (
                f'{shipment["status"]} · ETA {shipment["current_eta"]}'
                if shipment else "Unavailable — analysis must stop"
            ),
            "carrier_report": definition["report_summary"],
        })
    return cases


def create_app(
    reasoner: Reasoner | None = None,
    tool_service: EnterpriseToolService | None = None,
    action_store: ActionStore | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        selected = reasoner if reasoner is not None else create_reasoner()
        bundle = (
            ConnectorBundle(tool_service, mode="injected")
            if tool_service is not None else create_connector_bundle()
        )
        store = action_store or ActionStore(ActionSettings.from_env().database_path)
        application.state.reasoner = selected
        application.state.connector_bundle = bundle
        application.state.tools = bundle.tools
        application.state.actions = ActionIntentService(store, bundle.tools)
        try:
            yield
        finally:
            if reasoner is None:
                client = getattr(selected, "client", None)
                if client is not None:
                    client.close()
            bundle.close()

    application = FastAPI(
        title="Supply Chain Exception Resolution Agent",
        version=APP_VERSION,
        description="Evidence-referenced recommendations with resilient enterprise connectors",
        lifespan=lifespan,
    )

    @application.get("/health")
    def health():
        return {"status": "ok"}

    @application.get("/demo", include_in_schema=False)
    def demo():
        return FileResponse(DEMO_DIR / "index.html", media_type="text/html")

    @application.get("/demo/status", response_model=DemoStatus)
    def demo_status(request: Request):
        return DemoStatus(
            version=APP_VERSION,
            reasoner_provider=request.app.state.reasoner.provider,
            connector_mode=request.app.state.connector_bundle.mode,
        )

    @application.get("/demo/cases")
    def list_demo_cases():
        return {"cases": demo_cases()}

    @application.post("/exceptions/{exception_id}/resolve", response_model=ResolutionRecommendation)
    def resolve(exception_id: str, request: Request, response: Response):
        try:
            selected_reasoner = (
                RuleBasedReasoner()
                if exception_id in DETERMINISTIC_DEMO_CASES
                else request.app.state.reasoner
            )
            result = resolve_exception(exception_id, selected_reasoner, request.app.state.tools)
        except ResolutionError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message, "run_id": exc.run_id},
                headers={"X-Run-ID": exc.run_id or ""},
            ) from None
        response.headers["X-Run-ID"] = result.run_id
        return result

    @application.get("/exceptions/{exception_id}/audit")
    def audit(exception_id: str, run_id: str | None = None):
        return {"events": get_events(exception_id, run_id)}

    @application.post("/actions/request-document", response_model=ActionIntent, status_code=202)
    def request_document(
        payload: RequestDocumentInput, request: Request, response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        try:
            action, replayed, run_id = request.app.state.actions.request_document(payload, idempotency_key)
        except ResolutionError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message, "run_id": exc.run_id},
                headers={"X-Run-ID": exc.run_id or ""},
            ) from None
        response.headers["Idempotency-Replayed"] = str(replayed).lower()
        response.headers["X-Run-ID"] = run_id
        return action

    @application.get("/actions/{action_id}", response_model=ActionIntent)
    def get_action(action_id: str, request: Request):
        try:
            return request.app.state.actions.store.get(action_id)
        except ResolutionError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message, "run_id": exc.run_id},
            ) from None

    application.mount("/demo/assets", StaticFiles(directory=DEMO_DIR), name="demo-assets")
    return application


app = create_app()

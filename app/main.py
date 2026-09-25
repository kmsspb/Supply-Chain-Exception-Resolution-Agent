from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request, Response

from app.actions import ActionIntentService, ActionStore
from app.audit import get_events
from app.config import ActionSettings
from app.connectors import ConnectorBundle, EnterpriseToolService, create_connector_bundle
from app.errors import ResolutionError
from app.models import ActionIntent, RequestDocumentInput, ResolutionRecommendation
from app.reasoner import Reasoner, create_reasoner
from app.service import resolve_exception


def create_app(
    reasoner: Reasoner | None = None,
    tool_service: EnterpriseToolService | None = None,
    action_store: ActionStore | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        selected = reasoner if reasoner is not None else create_reasoner()
        bundle = ConnectorBundle(tool_service) if tool_service is not None else create_connector_bundle()
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
        version="0.4.0",
        description="Evidence-referenced recommendations with resilient enterprise connectors",
        lifespan=lifespan,
    )

    @application.get("/health")
    def health():
        return {"status": "ok"}

    @application.post("/exceptions/{exception_id}/resolve", response_model=ResolutionRecommendation)
    def resolve(exception_id: str, request: Request, response: Response):
        try:
            result = resolve_exception(exception_id, request.app.state.reasoner, request.app.state.tools)
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

    return application


app = create_app()

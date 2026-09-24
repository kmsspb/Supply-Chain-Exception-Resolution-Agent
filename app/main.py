from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response

from app.audit import get_events
from app.errors import ResolutionError
from app.models import ResolutionRecommendation
from app.reasoner import Reasoner, create_reasoner
from app.service import resolve_exception


def create_app(reasoner: Reasoner | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        selected = reasoner if reasoner is not None else create_reasoner()
        application.state.reasoner = selected
        try:
            yield
        finally:
            if reasoner is None:
                client = getattr(selected, "client", None)
                if client is not None:
                    client.close()

    application = FastAPI(
        title="Supply Chain Exception Resolution Agent",
        version="0.3.0",
        description="Evidence-referenced recommendations with deterministic or Azure reasoning",
        lifespan=lifespan,
    )

    @application.get("/health")
    def health():
        return {"status": "ok"}

    @application.post("/exceptions/{exception_id}/resolve", response_model=ResolutionRecommendation)
    def resolve(exception_id: str, request: Request, response: Response):
        try:
            result = resolve_exception(exception_id, request.app.state.reasoner)
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

    return application


app = create_app()

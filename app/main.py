from fastapi import FastAPI, HTTPException

from app.audit import get_events
from app.service import resolve_exception

app = FastAPI(
    title="Supply Chain Exception Resolution Agent",
    version="0.1.0",
    description="Hybrid deterministic + agentic automation portfolio demonstrator",
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/exceptions/{exception_id}/resolve")
def resolve(exception_id: str):
    try:
        return resolve_exception(exception_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/exceptions/{exception_id}/audit")
def audit(exception_id: str):
    return {"events": get_events(exception_id)}

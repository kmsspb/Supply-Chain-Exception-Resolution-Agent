import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.audit import RunTrace
from app.connectors.service import EnterpriseToolService
from app.errors import ActionNotFound, IdempotencyConflict, InvalidIdempotencyKey
from app.models import ActionIntent, RequestDocumentInput
from app.service import collect_context

ACTION_TYPE = "request_document"


def validate_idempotency_key(value: str | None) -> str:
    if value is None or not 8 <= len(value) <= 128 or any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise InvalidIdempotencyKey()
    return value


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_request_hash(request: RequestDocumentInput) -> str:
    payload = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _hash_text(payload)


class ActionStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS action_intents (
                    action_id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    exception_id TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    shipment_id TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    idempotency_key_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status = 'recorded'),
                    created_at TEXT NOT NULL,
                    UNIQUE(action_type, idempotency_key_hash)
                )
            """)

    @staticmethod
    def _model(row: sqlite3.Row) -> ActionIntent:
        return ActionIntent.model_validate({key: row[key] for key in (
            "action_id", "action_type", "exception_id", "order_id", "shipment_id",
            "document_type", "reason", "status", "created_at",
        )})

    def find_by_key(self, key_hash: str) -> tuple[ActionIntent, str] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM action_intents WHERE action_type = ? AND idempotency_key_hash = ?",
                (ACTION_TYPE, key_hash),
            ).fetchone()
        return (self._model(row), row["request_hash"]) if row else None

    def get(self, action_id: str) -> ActionIntent:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM action_intents WHERE action_id = ?", (action_id,)).fetchone()
        if row is None:
            raise ActionNotFound()
        return self._model(row)

    def insert_or_get(
        self, request: RequestDocumentInput, order_id: str, shipment_id: str,
        request_hash: str, key_hash: str,
    ) -> tuple[ActionIntent, bool]:
        action = ActionIntent(
            action_id=str(uuid4()), action_type=ACTION_TYPE,
            exception_id=request.exception_id, order_id=order_id, shipment_id=shipment_id,
            document_type=request.document_type, reason=request.reason,
            status="recorded", created_at=datetime.now(timezone.utc).isoformat(),
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM action_intents WHERE action_type = ? AND idempotency_key_hash = ?",
                (ACTION_TYPE, key_hash),
            ).fetchone()
            if row:
                if row["request_hash"] != request_hash:
                    raise IdempotencyConflict()
                return self._model(row), True
            connection.execute("""
                INSERT INTO action_intents (
                    action_id, action_type, exception_id, order_id, shipment_id, document_type,
                    reason, request_hash, idempotency_key_hash, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                action.action_id, action.action_type, action.exception_id, action.order_id,
                action.shipment_id, action.document_type.value, action.reason, request_hash,
                key_hash, action.status, action.created_at,
            ))
        return action, False


class ActionIntentService:
    def __init__(self, store: ActionStore, tools: EnterpriseToolService):
        self.store = store
        self.tools = tools

    def request_document(self, request: RequestDocumentInput, key: str | None) -> tuple[ActionIntent, bool, str]:
        trace = RunTrace(request.exception_id, "action_intent")
        try:
            validated_key = validate_idempotency_key(key)
            key_hash = _hash_text(validated_key)
            request_hash = canonical_request_hash(request)
            existing = self.store.find_by_key(key_hash)
            if existing:
                action, stored_hash = existing
                if stored_hash != request_hash:
                    trace.log("action_intent_conflict", idempotency_key_hash=key_hash)
                    raise IdempotencyConflict()
                trace.log("action_intent_replayed", idempotency_key_hash=key_hash, action_id=action.action_id)
                return action, True, trace.run_id

            context = collect_context(request.exception_id, trace, self.tools)
            try:
                action, replayed = self.store.insert_or_get(
                    request, context.order["order_id"], context.shipment["shipment_id"], request_hash, key_hash,
                )
            except IdempotencyConflict:
                trace.log("action_intent_conflict", idempotency_key_hash=key_hash)
                raise
            trace.log(
                "action_intent_replayed" if replayed else "action_intent_recorded",
                idempotency_key_hash=key_hash, action_id=action.action_id,
            )
            return action, replayed, trace.run_id
        except Exception as exc:
            if hasattr(exc, "run_id"):
                exc.run_id = trace.run_id
            raise

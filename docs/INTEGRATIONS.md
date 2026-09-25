# Enterprise integration pattern — v0.4

## Shared connector contract

`EnterpriseToolService` exposes three typed reads used by REST orchestration, action validation,
and MCP: `get_erp_order`, `get_logistics_status`, and `get_shipment_note`. `CONNECTOR_MODE=fixture`
is the local default. HTTP mode uses these contracts:

| Upstream | Request |
| --- | --- |
| ERP | `GET {ERP_BASE_URL}/orders/{url-encoded-order-id}` |
| Logistics status | `GET {LOGISTICS_BASE_URL}/shipments/{url-encoded-shipment-id}` |
| Logistics note | `GET {LOGISTICS_BASE_URL}/shipments/{url-encoded-shipment-id}/note` |

Set `CONNECTOR_MODE=http`, `ERP_BASE_URL`, and `LOGISTICS_BASE_URL`. HTTPS is required except for
`localhost`, `127.0.0.1`, and `::1`. v0.4 deliberately sends no credentials; production Entra ID
belongs to v0.5. A single pooled HTTP client is closed during application shutdown.

Strict response schemas match the fixture records in `data/erp_orders.json`, `data/shipments.json`,
and `data/notes.json`. Unknown records map to the existing 422 missing-evidence response. Malformed
JSON, extra/missing fields, invalid values, or mismatched identifiers map to 502. Exhausted connection
and timeout failures map to 503 and 504. Response bodies and credentials are never traced.

## Retries and circuits

Read-only GETs use connect/read/write/pool timeouts of 2/5/5/2 seconds and three total attempts.
Transport errors, timeouts, and HTTP 408, 429, 500, 502, 503, and 504 are retried. Other 4xx statuses,
schema failures, and relationship failures are not retried. Backoff is exponential full jitter from
100 ms to one second; valid `Retry-After` values take precedence and are capped at five seconds.

ERP and logistics have separate thread-safe process-local breakers. Five consecutive failed logical
calls open the relevant breaker for 30 seconds. Only one half-open probe is allowed; success closes
the circuit and failure reopens it. Individual retry attempts do not increment the breaker. A 404
shows that the upstream responded and does not count as a failure. Restarting resets breaker state.

## MCP experiment

The official Python MCP SDK v2 server exposes only the three reads:

```powershell
python -m app.mcp_server
python -m app.mcp_server --transport http --host 127.0.0.1 --port 8001
python -m app.mcp_smoke --transport in-process
python -m app.mcp_smoke --transport stdio
```

The Streamable HTTP endpoint is `/mcp`; non-loopback binds are rejected. Tool annotations set
`readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, and `openWorldHint=true`.
These are client hints, not access control. A future remote design needs OAuth, strict tool allowlists,
and approvals for sensitive calls. See the [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
and [OpenAI MCP guidance](https://developers.openai.com/api/docs/guides/tools-connectors-mcp).

## Idempotent action intent

`POST /actions/request-document` requires `Idempotency-Key` with 8–128 visible ASCII characters.
The request supports `commercial_invoice`, `certificate_of_origin`, `packing_list`, and `other`.
A first accepted request returns 202 with `Idempotency-Replayed: false`; the same key and canonical
payload returns the identical record with 202 and `true`, including after restart. A changed payload
under that key returns 409. `GET /actions/{action_id}` retrieves the durable record. The current
API exposes no update operation; this does not make local SQLite tamper-proof audit storage.

SQLite defaults to `.runtime/actions.sqlite3` and can be changed with `ACTION_DB_PATH`. It uses WAL,
a busy timeout, atomic transactions, and a unique action-type/key-hash constraint. Only the SHA-256
key hash is persisted and traced. Connector validation occurs before a new insertion, so failures
leave no row and callers can retry. This is exactly-once intent recording on one SQLite database;
it does not claim exactly-once delivery. No email, supplier call, ERP write, approval, or completion
transition is implemented.

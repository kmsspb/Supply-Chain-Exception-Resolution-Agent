# Architecture — v0.4

The application also serves a dependency-free guided business interface at `/demo`. It calls the
same REST contracts described below and includes a presentation-oriented architecture view. Its
status endpoint exposes only the application version and safe provider/connector/action mode labels.

## Implemented request flow

```text
POST /exceptions/{id}/resolve
  -> create UUID run trace
  -> load local exception
  -> EnterpriseToolService reads ERP order, shipment, and carrier note sequentially
  -> validate required record shape/relationships and build canonical evidence
  -> selected Reasoner.resolve(ReasoningContext)
       RuleBasedReasoner | AzureOpenAIReasoner
  -> local recommendation and citation validation
  -> return recommendation + run ID + provider + evidence
  -> terminal success/failure trace
```

FastAPI creates the selected provider and connector bundle during application lifespan startup. Configuration is
loaded from environment variables and an optional repository-root .env; environment values win.
The default baseline needs no Azure configuration. SDK clients owned by the application are
closed at shutdown. Tests can inject a reasoner, tool service, and action store using the application factory.

## Contracts and responsibility

- **Connectors:** typed `ERPConnector` and `LogisticsConnector` protocols have fixture and HTTP
  implementations. `EnterpriseToolService` is the single contract used by the orchestrator, MCP,
  and action validation. HTTP responses use strict Pydantic records and relationship checks.
- **Context:** the service collects all records before reasoning. It validates required string
  fields and ID relationships; this is not a complete enterprise domain schema.
- **Evidence:** stable IDs such as `erp:SO-1001`, `logistics:SHP-9001`, and `note:NOTE-7001`.
  Facts contain canonical JSON source records. References identify records within the saved
  context snapshot, not immutable versions in an external system.
- **Reasoner:** an injectable protocol with a provider name, descriptive metadata, and a context
  input/result contract. The original deterministic classification/confidence behaviour remains.
- **Azure:** OpenAI Python SDK Responses parsing, an Azure v1 base URL, deployment name, versioned
  instructions, and a required strict structured output schema. No tool-calling loop or managed agent.
- **Validation:** provider transport schema is separate from domain constraints. Validate finite
  confidence in [0,1], nonblank category/summary/action, nonempty cause/action citations, and
  membership in the supplied catalogue. Public facts are hydrated from that catalogue.
- **Action intent:** `request_document` is an immutable SQLite record with status `recorded` and
  REST idempotency. It is neither approval nor delivery. No message sending or ERP mutation occurs.

Reference integrity does not establish semantic entailment. Even a valid response can misinterpret
facts or recommend an unsuitable action. Evaluation uses human review to assess unsupported
claims separately from citation validity. Carrier notes are treated as untrusted evidence in
the prompt; this is not a claim of complete prompt-injection resistance.

## Failures

Unknown exceptions map to 404; missing support to 422; corrupt local data to 500; invalid output,
refusal, or incomplete output to 502; unavailable providers to 503; timeout to 504. Unexpected
failures return a sanitized 500. Handled analysis failures include a run ID in body and header
and a terminal trace event. Configuration errors prevent Azure-mode startup.

Azure has a configurable SDK timeout and output limit, with zero automatic SDK retries. There is
no fallback to baseline. HTTP reads make three total attempts for transport/timeouts and selected
status codes, honor bounded `Retry-After`, and use exponential full jitter. ERP and logistics have
independent thread-safe process-local breakers: five failed logical calls open a breaker for 30
seconds, then one half-open probe is admitted. A 404 maps to missing evidence and does not count.
Raw upstream error text is neither returned nor saved in traces.

## MCP and action-intent paths

The standalone MCP SDK v2 server exposes the same three read tools with Pydantic output. It supports
stdio and loopback-only Streamable HTTP at `/mcp`. Tool annotations describe read-only, non-destructive,
idempotent, open-world calls; authorization must not rely on these hints. The Azure model is not an
MCP client in this version.

`POST /actions/request-document` first checks the idempotency journal. A matching prior request is
returned without revalidating connectors. A new key triggers linked exception/order/shipment
collection, then an atomic SQLite transaction inserts one row under a unique action-type/key-hash
constraint. WAL and a busy timeout support local concurrency. The raw key is never stored. A key reused
with another canonical payload returns 409. Failed validation inserts nothing.

## Traces and comparisons

Each run has a UUID and monotonically increasing sequence numbers. A lock protects appends and
reads in the in-memory store; reads return defensive copies. Events include connector outcomes,
context snapshots, prompt version/hash, provider metadata, model timings/usage when available,
validation results, and the final validated recommendation or safe failure code.

The audit endpoint retains `{"events": [...]}` and accepts an optional run-ID filter.
Trace history is process-local, lost on restart, separate across workers, unauthenticated,
unbounded, and not immutable. No production audit guarantees are claimed.

The comparison CLI creates each of six context snapshots once and passes it to both providers.
It records separate run IDs, reviewer expectations, recommendations/errors, elapsed times, model
metadata, and run traces in JSON. Comparison runs use preloaded fixture contexts, so they have
no connector-call events: no connector calls occurred during those runs. This six-case compatibility
workflow stays unscored; v0.3 evaluation is a separate CLI using the same execution helper.

## Evaluation workflow

`app.evaluate run` validates a versioned 30-case dataset before constructing providers. It builds
source contexts without ground-truth annotations, runs the unchanged reasoners, and snapshots
results, metadata, traces, dataset/context/output hashes, and annotations for reproducible scoring.

Deterministic metrics measure category matches, latency, token usage and supported cost estimates.
The scorer imports explicit human judgements for action meaning, unsupported claims, and manual
escalation. The approval flag is not an escalation prediction. All metrics expose denominators,
review/usage coverage, and unavailable values. Provider failures stay in all-attempt denominators.

`app.evaluate score` reuses saved results and makes no model calls. Reviews are bound to exact
case/provider/run/output hashes. Pricing is an explicit, dated deployment profile snapshotted
into the report; missing or unsupported pricing produces unknown costs, not zero. Results are
JSON/Markdown artifacts in a new directory, not a new database or serving endpoint.

The new evaluation dataset, review validation, metrics, pricing and reporting code lives under
`app/evaluation`. Production reasoning and policy do not depend on it. See [EVALUATION.md](EVALUATION.md)
for formulas and review responsibilities. Hashes detect mismatches; they do not authenticate reviewers
or provide immutable audit guarantees.

## Future boundaries

v0.5 provides Entra identity, remote MCP OAuth, enforced write approvals, external dispatch and
immutable audit. v0.6 covers delivery infrastructure. These stages must preserve the separation
between reasoning and authorized deterministic execution.

# Architecture — v0.2

## Implemented request flow

```text
POST /exceptions/{id}/resolve
  -> create UUID run trace
  -> load local exception
  -> read ERP order, shipment, and carrier note sequentially
  -> validate required record shape/relationships and build canonical evidence
  -> selected Reasoner.resolve(ReasoningContext)
       RuleBasedReasoner | AzureOpenAIReasoner
  -> local recommendation and citation validation
  -> return recommendation + run ID + provider + evidence
  -> terminal success/failure trace
```

FastAPI creates the selected provider during application lifespan startup. Configuration is
loaded from environment variables and an optional repository-root .env; environment values win.
The default baseline needs no Azure configuration. SDK clients owned by the application are
closed at shutdown. Tests can inject a reasoner using the application factory.

## Contracts and responsibility

- **Repository/tools:** fixed local JSON sources behind narrow read-only functions. Missing records
  and corrupt data have distinct typed errors. There is no HTTP ERP integration or detector.
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
- **Approval:** flags and suggested actions are advisory. No authorization decision, workflow
  transition, approval persistence, message sending, or ERP mutation is implemented.

Reference integrity does not establish semantic entailment. Even a valid response can misinterpret
facts or recommend an unsuitable action. The comparison fixtures expose this limitation; formal
unsupported-claim evaluation belongs to v0.3. Carrier notes are treated as untrusted evidence in
the prompt; this is not a claim of complete prompt-injection resistance.

## Failures

Unknown exceptions map to 404; missing support to 422; corrupt local data to 500; invalid output,
refusal, or incomplete output to 502; unavailable providers to 503; timeout to 504. Unexpected
failures return a sanitized 500. Handled analysis failures include a run ID in body and header
and a terminal trace event. Configuration errors prevent Azure-mode startup.

Azure has a configurable SDK timeout and output limit, with zero automatic SDK retries. There is
no fallback to baseline. General connector resilience/circuit breakers remain v0.4 work.
Raw upstream error text is neither returned nor saved in traces.

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
no connector-call events: no connector calls occurred during those runs. No semantic grading or
cost estimates are performed in v0.2.

## Future boundaries

v0.3 adds a larger evaluation dataset and metrics. v0.4 introduces enterprise tool access,
MCP exploration and action resilience. v0.5 provides identity, enforced write approvals and
immutable audit. v0.6 covers delivery infrastructure. These stages must preserve the separation
between reasoning and authorized deterministic execution.

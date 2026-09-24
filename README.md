# Supply Chain Exception Resolution Agent

A portfolio demonstrator for hybrid enterprise automation: deterministic context collection,
replaceable reasoning, evidence references, and traceable recommendations.

**v0.3 is recommendation-only.** It offers the original deterministic baseline and a direct
Azure OpenAI model integration. Neither provider changes ERP records, sends messages, approves
actions, or resolves stored exception status. The approval flag is advisory.

## Scenario

For fictional Nordic Marine Components, an order is due on 2026-09-25, the carrier reports
2026-09-28, and a note describes an incomplete customs invoice. Local synthetic JSON records
stand in for ERP, logistics, and communication systems.

The baseline uses the original keyword rule and fixed confidence values. The Azure provider
receives the same context and must return structured recommendations with references to
application-owned evidence. Citation validation proves references exist, **not** that all
claims are semantically supported. Compare the actual outputs before claiming model improvement.

## Quick start

Requires Python 3.11+. Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

On macOS/Linux, activate with `source .venv/bin/activate`.
The default `rule_based` provider runs without Azure credentials.

- Swagger: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health

```powershell
curl.exe -X POST http://127.0.0.1:8000/exceptions/EX-001/resolve
```

PowerShell-native example:

```powershell
$result = Invoke-RestMethod -Method Post http://127.0.0.1:8000/exceptions/EX-001/resolve
$result | ConvertTo-Json -Depth 10
Invoke-RestMethod "http://127.0.0.1:8000/exceptions/EX-001/audit?run_id=$($result.run_id)"
```

## Enable Azure reasoning

Copy `.env.example` to `.env`, then set:

```dotenv
REASONER_PROVIDER=azure_openai
AZURE_OPENAI_BASE_URL=https://YOUR-RESOURCE.openai.azure.com/openai/v1/
AZURE_OPENAI_API_KEY=your-local-key
AZURE_OPENAI_DEPLOYMENT=your-deployment-name
AZURE_OPENAI_TIMEOUT_SECONDS=30
AZURE_OPENAI_MAX_OUTPUT_TOKENS=4096
```

Use an existing deployment that supports the Responses API and structured outputs. The
deployment name is passed as `model`; this is not a Foundry project/agent endpoint.
No Azure resources are provisioned by this application. Follow Microsoft's
[structured-output setup](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs).

Environment variables take precedence over the optional repository-root `.env`.
Restart the application after changing provider configuration. Azure configuration is checked
at startup only when Azure is selected. The baseline ignores incomplete Azure settings.

The SDK has zero automatic retries and an explicit request timeout. The configured timeout is
an SDK request/I/O timeout, not a distributed workflow deadline. Provider errors never cause a
baseline fallback. Secrets stay out of source control; do not place real keys in `.env.example`.

## API contract

| Endpoint | Behaviour |
| --- | --- |
| `GET /health` | Process health; does not probe Azure |
| `POST /exceptions/{exception_id}/resolve` | Collect context and return a recommendation |
| `GET /exceptions/{exception_id}/audit?run_id=...` | Retrieve events for an exception, optionally one run |

All original recommendation fields remain. Responses add `run_id`, `provider`,
`cause_evidence_ids`, and `action_evidence_ids`; each evidence item adds `evidence_id`.
The `X-Run-ID` response header matches the body, including handled analysis errors.
Evidence facts are canonical JSON representations of retrieved records, constructed by the
application rather than copied from model-generated prose.

Handled errors use:
`{"detail": {"code": "...", "message": "...", "run_id": "..."}}`.

| HTTP status | Meaning |
| --- | --- |
| 404 | Exception does not exist |
| 422 | Required supporting record is unavailable |
| 500 | Corrupt local data or unexpected internal failure |
| 502 | Invalid output/citations, model refusal, or incomplete model response |
| 503 | Provider unavailable, including authentication and throttling failures |
| 504 | Provider timeout |

Recommendations do not mutate business state. Calling resolve again creates a new analysis run.
There is no approval endpoint, exception intake endpoint, or action executor.

## Compare providers

Six fixtures cover missing documents, completed documents/negation, weather delay, insufficient
information, conflicting sources, and instructions embedded in a carrier note.

```powershell
python -m app.compare --provider rule_based --output comparison-results/baseline.json
python -m app.compare --provider azure_openai --output comparison-results/azure.json
python -m app.compare --provider both --output comparison-results/both.json
```

The CLI provider selection overrides `REASONER_PROVIDER`. In `both` mode, each fixture is
loaded once and the identical context snapshot is supplied to both providers. Reports include
expected outcomes, recommendations, evidence citations, run traces, elapsed time, and available
model/token metadata. Failures remain explicit errors, with no substituted recommendation.
Exit codes: 0 = all runs completed; 1 = one or more provider errors; 2 = fixture/report I/O error.
Exit code 0 does not imply the recommendations match expected outcomes.

Expected actions describe reviewer expectations, not an automatic semantic grader. Known baseline
errors on negation and contradictory notes are preserved so comparisons remain honest. A completed
baseline-only report does not validate Azure model quality. The original six-case comparison
remains available; use the v0.3 evaluation workflow below for scoring and cost estimates.

## Evaluate 30 cases

The versioned dataset contains five examples in each existing scenario family, including the
six original seeds and 24 new cases. Both reasoners and the Azure prompt remain fixed.

```powershell
python -m app.evaluate run --provider rule_based --output-dir evaluation-results/baseline
python -m app.evaluate run --provider both --output-dir evaluation-results/both
```

Each new output directory receives `results.json`, `summary.md`, and `review-template.json`.
Classification, latency, token counts, and available cost estimates are automatic. Action
correctness, unsupported claims, and escalation meaning use structured human review. Pending
reviews are shown as unavailable, with coverage; they are not silently scored as correct.

Copy the blank template to `reviews.json`, record actual human judgements with reviewer identity,
timestamp, rationale, and evidence, then rescore without making model calls:

```powershell
python -m app.evaluate score --results evaluation-results/baseline/results.json --reviews reviews.json --output-dir evaluation-results/baseline-reviewed
```

Both commands accept `--pricing <file>` for sourced, dated deployment rates. Start with
`data/pricing.example.json`, which contains no real prices. Missing usage or prices produce
unavailable costs; unknown failed requests are not free. Existing output artifacts are not overwritten.

See [the evaluation guide](docs/EVALUATION.md) for metric definitions, review format, pricing,
dataset provenance, report hashes, and interpretation limits.

## Tracing and boundaries

Every run has a UUID and increasing event sequence numbers. Traces record run start, connector
calls, the supplied synthetic context, prompt version/hash, deployment, returned model/response
IDs, available token usage, validation outcomes, timings, and terminal success/failure.
Only validated recommendations are stored as recommendation events. Raw SDK error bodies,
credentials, request headers, and hidden model reasoning are excluded.

The prompt lives in `app/prompts/resolution_v1.txt`. Its hash identifies the exact text, while
context snapshots identify the evidence supplied. Connector events describe calls made by the
orchestrator; the model does not invoke tools.

**Traces are process-local, unauthenticated, and not immutable.** Restarting loses them; workers
have separate stores; memory usage grows with runs. This is a synthetic-data local demo, not a
production governance store. JSON comparison reports are local exports of those runs.

## Tests

```powershell
python -m pytest tests -q
```

Offline tests use mocked HTTP transport with the real OpenAI SDK. They cover parsing, the Azure
schema subset, local validation, provider failures, safe errors, configuration, API compatibility,
trace correlation/concurrency, comparison compatibility, and evaluation calculations/review validation.
They require no Azure credentials. Live verification is separate: configure Azure, resolve
`EX-001`, then run the 30-case evaluation and review its outputs. Mocked tests do not measure model quality.

## Roadmap

- **v0.2:** Direct Azure reasoning, structured output, evidence reference validation, prompt/connector tracing, small baseline comparisons.
- **v0.3:** 30 evaluation cases; classification, human-reviewed action/claim/escalation scoring, latency, token/cost estimates with coverage.
- **v0.4:** Enterprise tool exposure, MCP exploration, retries/timeouts/circuit breakers, action idempotency.
- **v0.5:** Entra ID, agent identity and least privilege, read/write separation, enforced approval policies, immutable audit.
- **v0.6:** CI/CD, containers, deployment configuration/secrets management, deployment architecture.

See [architecture](docs/ARCHITECTURE.md) and [interview narrative](docs/INTERVIEW_STORY.md).

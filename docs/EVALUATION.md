# Evaluation — v0.3

The evaluation harness measures the unchanged v0.2 reasoners. It does not improve or tune them,
introduce an LLM judge, change the API contract, or authorize actions. Semantic scoring uses
explicit human review, with unreviewed judgements left unavailable.

## Dataset

`data/evaluation_v1.json` contains 30 self-contained synthetic cases: five each for missing
customs documents, completed documents, weather delays, insufficient information, conflicting
sources, and embedded instructions. Six original examples are tagged `seed`; 24 additional cases
are tagged `new`. The new cases vary wording, concrete paperwork defects, weather events,
dates/identifiers, and evidence consistency. These are small, authored examples, not a statistically
representative production benchmark or an independently held-out test set.

Each case includes source records, an expected category, acceptable action criteria, prohibited
actions and claims, expected manual escalation, supporting references, and the annotation rationale.
The entire dataset is validated before provider setup. Ground truth never enters the reasoning
context. Each context snapshot is shared by both providers for a fair comparison.

Dataset version and canonical SHA-256 hash are saved with results. Changing a dataset should
increment its version; the hash also distinguishes edits made without a version increment.

## Run an evaluation

Activate the existing virtual environment, then:

```powershell
python -m app.evaluate run --provider rule_based --output-dir evaluation-results/baseline
python -m app.evaluate run --provider both --output-dir evaluation-results/both
```

Provider selection defaults to `rule_based`. Azure uses the existing environment/.env settings.
The `both` option requires Azure configuration for real Azure results; if configuration is missing,
the Azure outcomes remain explicit errors. There is one attempt per case/provider and no fallback.
Use `--dataset <path>` to supply a dataset following the same 30-case, six-family schema.

Each command produces:

- `results.json`: dataset/context snapshots, annotations, recommendations or errors, original
  traces and timings, model/prompt/rule metadata, hashes, derived metrics, and pricing/review provenance.
- `summary.md`: readable scores, coverage, latency/usage/cost summaries, and per-case outcomes.
- `review-template.json`: blank review entries for successful outputs only.

Use a new output directory for each run or rescore. Existing artifacts are not overwritten, and
overwrite checks happen before paid model calls. Exit codes are 0 for no provider errors, 1 when
provider errors are recorded, and 2 for invalid input or report I/O failure. These are execution
statuses, not quality gates; a poor model result or a pending human review does not change exit 0.

## Structured human review

Copy the template to a separate `reviews.json`. For each output you actually review:

1. Read its source context, expected action criteria, prohibited actions/claims, and rationale in
   `results.json`. Classify the recommendation on its meaning rather than literal phrase matching.
2. Enter the reviewer's identity, a timezone-aware `reviewed_at` timestamp, and a rationale.
3. Set `action_correct` to true/false, or leave it null if unreviewed. A correct action meets the
   acceptable criteria and does not propose a prohibited action.
4. Set `escalation_recommended` according to whether the output calls for manual investigation
   or reconciliation of uncertainty. Routine follow-up to request paperwork or confirm an ETA
   is not itself an investigative escalation. The advisory approval flag is not this metric.
5. Extract factual assertions from `category`, `summary`, and `recommended_action`. Quote each
   assertion exactly from its field and mark it `supported`, `unsupported`, or `uncertain`, with
   an explanation and relevant evidence IDs. Supported claims require at least one source reference.
   A proposal to request a document is not a claim that it has already been requested; assess
   factual premises inside proposed actions as claims.
6. Set `claims_complete=true` only after assessing all factual assertions. The category assertion
   must be included. Completeness beyond these structural checks is the reviewer's responsibility.

Each claim object has `field`, `assertion`, `verdict`, `explanation`, and `evidence_ids`. Evidence
references come from the source catalogue, whether or not the model cited them. Use `uncertain`
when support cannot be decided; uncertain claims are not automatically counted as supported.
Duplicate assertion entries are rejected to avoid double-counting identical field/text pairs.

Do not label assistant-generated, model-generated, or unit-test judgements as human review.
The tool records declared reviewer provenance; it does not authenticate the reviewer's identity.

```powershell
python -m app.evaluate score --results evaluation-results/baseline/results.json --reviews reviews.json --output-dir evaluation-results/baseline-reviewed
```

Scoring makes no provider calls. Review files bind to the evaluation hash; entries bind to case,
provider, run ID, and output hash. Duplicates, unknown evidence, nonmatching quoted assertions,
stale outputs, and missing judgement provenance are rejected. You can submit only a subset of
reviews. Pending entries remain unknown. Partially entered claim reviews are retained as provenance
but excluded from claim-rate calculations until declared complete.

Imported reviews and their hash are saved inside the scored `results.json`. Each output directory
also gets a fresh blank template; it never silently overwrites the separate human-authored review file.
Hashes detect accidental changes and mismatches; they are not signatures or immutable audit records.

## Metric definitions

All metrics are available overall, per provider, per family within each provider, and for the
24 new cases per provider. Counts and denominators accompany rates. An undefined ratio is JSON
`null` and displays as "not available."

| Metric | Calculation |
| --- | --- |
| Classification | Trim/case-normalize labels and compare exactly with the expected category. All-attempt accuracy counts provider errors as incorrect; successful-output accuracy excludes errors. Confusion counts include `__provider_error__`. |
| Action accuracy | Correct action reviews / submitted action reviews. Coverage is reviewed / successful outputs. |
| Unsupported claims | Unsupported / (supported + unsupported) assertions, using only completed claim reviews. Report uncertain counts/rate, verdict coverage, reviewed-output coverage, and outputs with unsupported assertions separately. |
| Escalation | Human-assessed recommendation for manual investigation versus expected escalation. Accuracy, precision, recall, and TP/FP/TN/FN counts use reviewed outputs. Undefined precision/recall remain null. |
| Citation integrity | Both citation lists are nonempty, references exist in the returned canonical catalogue, and facts match source records. This is independent of semantic support. |
| Latency | Count, mean, median, and nearest-rank p95 for analysis and provider-stage durations; success and error samples remain separate. Missing durations are excluded with counts shown. |

Analysis timing starts after fixture loading and excludes the application's HTTP layer. Provider
timing covers the reasoner invocation stage, including fast configuration-failure outcomes; it is
not a pure network-latency measurement. A single pass over 30 cases has limited statistical power.

## Tokens and estimated cost

Available token counts are aggregated without inventing missing usage: input, cached input,
output, reasoning, and total, each with its own known subtotal and run coverage. Reasoning tokens
are a subset of output tokens and are never added again to total tokens or cost. Inconsistent
counts are excluded from known subtotals; partial but noncontradictory counts remain visible.
Usage captured on failed responses is included. Failed requests without usage are not treated as free.
The deterministic baseline uses zero model tokens and incurs zero model token charges.

Copy `data/pricing.example.json` and populate rates from your actual pricing source. The example
contains no real rates. A profile names provider/deployment, currency, effective date, source, and
decimal-string rates per million `input`, `cached_input`, and `output` tokens. The file keys are
`input_per_million`, `cached_input_per_million`, and `output_per_million`.

```powershell
python -m app.evaluate run --provider both --pricing pricing.local.json --output-dir evaluation-results/priced
python -m app.evaluate score --results evaluation-results/priced/results.json --reviews reviews.json --pricing pricing.updated.json --output-dir evaluation-results/repriced
```

For supported usage, cost is:

```text
((input_tokens - cached_input_tokens) * input_rate
 + cached_input_tokens * cached_input_rate
 + output_tokens * output_rate) / 1,000,000
```

Calculations use decimal arithmetic. Missing rates needed for nonzero token counts, missing cache
breakdown, inconsistent usage, cache-write charges, or other unsupported nonzero breakdowns produce
an unavailable cost with a reason. The harness does not guess prices or discount rules.

Known subtotals are grouped by currency with cost coverage. A complete total appears only when
all runs have known costs and currencies can be combined. Baseline-only cost is zero with no
billing currency. Pricing profiles are snapshotted into results. Rescoring without `--pricing`
reuses that snapshot; an explicit pricing file replaces it. No live tariff lookup is performed.
These are estimated model token charges, excluding infrastructure, tax, commitments, and other
billing items. A deployment name is not evidence of a specific model version or tariff.

## Validation and remaining boundaries

Offline tests verify dataset integrity, scoring with hand-calculated examples, review imports,
cost arithmetic, incomplete coverage, identical provider inputs, report hashes, and CLI behaviour.
Unit-test judgements are explicitly synthetic; generated baseline reports remain pending review.
Live Azure runs require deployment configuration and are reported separately from mocked tests.

Evaluation remains outside the production request path. v0.4 adds typed read connectors, MCP access,
and a local action-intent journal without changing the fixed reasoners or dataset. Identity, enforced
approval, external delivery, immutable audit, and deployment infrastructure remain v0.5–v0.6 work.

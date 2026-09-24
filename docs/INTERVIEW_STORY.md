# Interview story

## 30-second explanation

I built a supply-chain exception recommendation service to explore how existing RPA workflows
can use model reasoning for ambiguous cases. The orchestrator collects synthetic ERP, logistics,
and carrier-note evidence. Either a deterministic baseline or an Azure OpenAI deployment analyses
the same context. Structured output and evidence-reference checks validate the result, and a run
trace explains which evidence and provider were used.

The current version proposes actions only. Approval flags are advisory; authenticated approvals
and deterministic execution are later roadmap stages. I can compare the providers on six cases,
including negation, conflicting evidence and instructions embedded in notes.

## What the implementation demonstrates

- Separation of API, orchestration, read tools, reasoning and output validation.
- A local baseline that needs no cloud credentials.
- A direct Azure provider with structured output and explicit failure handling.
- Canonical evidence references and traceable runs.
- Repeatable comparisons that retain model failures and known baseline limitations.

Mocked provider tests validate integration behaviour, not model quality. A live Azure comparison
must be run before reporting model-quality results. Valid citations alone do not prove every
claim is supported.

## Next engineering steps

Formal evaluation comes in v0.3, enterprise tools and resilience in v0.4, identity and enforced
write approval in v0.5, and deployment infrastructure in v0.6. UiPath could eventually submit
qualified exceptions and execute explicitly authorized actions through a deterministic contract.

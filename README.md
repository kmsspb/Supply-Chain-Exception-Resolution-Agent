# Supply Chain Exception Resolution Agent

A portfolio demonstrator for **hybrid intelligent automation**: deterministic workflow + AI reasoning + enterprise tools + human approval + auditability.

## Why this project exists

Mature automation estates already handle deterministic work well. AI agents are most valuable where a process contains ambiguity, unstructured information, exception reasoning, or a need to choose among several next actions.

This project demonstrates how to **add agentic capability without replacing reliable automation unnecessarily**.

The fictional scenario is a logistics exception:
- an ERP sales/order record says a shipment should already be progressing;
- logistics data reports a delay or inconsistent ETA;
- a supplier/carrier note contains unstructured context;
- an agent gathers evidence and proposes the most likely cause and next action;
- high-impact actions require a human approval;
- all tool calls, evidence and decisions are logged.

## What this should prove in an interview

1. You understand **RPA vs agentic AI vs hybrid automation**.
2. You can design **tool-based agents** around enterprise systems.
3. You understand **REST/JSON/Python integration patterns**.
4. You design for **human-in-the-loop, auditability, monitoring and failure handling**.
5. You can explain how the pattern could integrate with an existing RPA estate such as UiPath.
6. You know that an LLM should not be allowed to mutate enterprise systems without controls.

## MVP architecture

```text
Exception event
     |
     v
Deterministic intake / validation
     |
     v
Exception Resolution Orchestrator
     |
     +------> ERP Tool (mock REST/data)
     +------> Logistics Tool (mock REST/data)
     +------> Communication Tool (mock unstructured note)
     |
     v
Agent reasoning / recommendation
     |
     +------ low-risk -> recommended next step
     |
     +------ high-risk -> Human approval
                            |
                            v
                    Deterministic action
                            |
                            v
                       Audit event
```

The initial version deliberately uses a **rule-based reasoning stub** instead of an external LLM. This keeps the project runnable without secrets and lets us first prove the workflow, tool contracts, guardrails and audit model. A real Azure/OpenAI agent will be added later behind the same interface.

## Scenario

Order `SO-1001` is expected at the customer on 2026-09-25.

The ERP record looks normal, but the carrier reports an ETA of 2026-09-28. A supplier/carrier note says the shipment was held because customs documentation was incomplete.

The system should:
1. validate the exception;
2. collect evidence from ERP, shipment tracking and notes;
3. classify the exception;
4. produce an evidence-backed recommendation;
5. decide whether human approval is required;
6. log what happened.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
```

Windows:

```powershell
.venv\Scripts\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install:

```bash
pip install -r requirements.txt
```

Run:

```bash
uvicorn app.main:app --reload
```

Open:

- Swagger: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health

Resolve the sample exception:

```bash
curl -X POST http://127.0.0.1:8000/exceptions/EX-001/resolve
```

## Development roadmap

### Phase 1 — deterministic skeleton
- [x] Exception model
- [x] Mock ERP/logistics/notes data
- [x] Tool interfaces
- [x] Rule-based reasoning stub
- [x] Human-approval decision
- [x] Audit trail
- [x] REST API

### Phase 2 — real LLM/tool calling
- [ ] Add `AgentReasoner` interface
- [ ] Azure OpenAI / Azure AI Foundry implementation
- [ ] Structured JSON output
- [ ] Tool/function calling
- [ ] Prompt versioning
- [ ] Grounded evidence citations in agent output

### Phase 3 — enterprise-grade controls
- [ ] Entra ID concept
- [ ] secrets via Key Vault
- [ ] confidence / risk thresholds
- [ ] PII/data-access controls
- [ ] evaluation dataset
- [ ] tracing and metrics
- [ ] retry/idempotency patterns
- [ ] approval persistence

### Phase 4 — RPA integration
- [ ] Define UiPath-facing REST contract
- [ ] RPA invokes agent only for qualified exceptions
- [ ] Agent returns recommendation + required action
- [ ] UiPath executes approved deterministic action
- [ ] common audit correlation ID

## Design principle

> **Keep deterministic work deterministic. Use the agent for ambiguity and reasoning. Require a human where the consequence of a wrong action is material.**

That principle is the core of this portfolio project.

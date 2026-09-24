# Architecture

## Architectural objective

Demonstrate a safe hybrid pattern in which an AI agent **reasons over evidence** but does not receive unrestricted access to enterprise systems.

### Components

1. **Exception intake**
   - deterministic validation
   - correlation ID / exception ID
   - no LLM involved

2. **Tool layer**
   - narrow read-only functions
   - ERP order lookup
   - logistics status lookup
   - communication/note lookup
   - later: controlled write tools

3. **Reasoning layer**
   - MVP: deterministic reasoner
   - later: Azure OpenAI / Azure AI Foundry agent
   - structured output only
   - evidence-grounded recommendation

4. **Risk / approval layer**
   - confidence threshold
   - action risk classification
   - human approval for material actions

5. **Execution layer**
   - deterministic system mutation
   - potentially delegated to UiPath / Power Automate
   - idempotent action contract

6. **Audit / observability**
   - tool calls
   - evidence references
   - model/prompt version
   - recommendation
   - approval
   - executed action
   - timestamps / correlation ID

## Why this pattern

The purpose is not to replace RPA. Existing deterministic automation remains valuable for stable tasks.

Agentic AI is introduced for:
- ambiguous exception classification;
- unstructured information;
- choosing among possible next steps;
- reasoning across multiple evidence sources.

High-consequence actions remain controlled by deterministic execution and human approval.

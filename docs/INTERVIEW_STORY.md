# Interview story

## 30-second explanation

I built this project to explore how an established enterprise RPA landscape can evolve toward agentic automation without replacing reliable deterministic workflows.

The example is a supply-chain exception. Deterministic logic detects the exception. An agent collects evidence from mock ERP, logistics and unstructured communication sources, reasons about the likely root cause and proposes an action. A human approval boundary protects material actions, and every step is auditable.

The initial version deliberately separates orchestration, tools and reasoning so I can replace the deterministic reasoner with Azure AI Foundry or another agent framework without redesigning the workflow.

## Key point

The project is about architecture and operational discipline, not a chatbot demo.

## Questions to be ready for

- Why should this step use an LLM instead of rules?
- What happens when confidence is low?
- What can the agent read?
- What can the agent write?
- Where is the human approval?
- How would UiPath participate?
- How do you evaluate whether the agent is improving?
- How do you protect secrets and identities?
- How would you trace an incorrect recommendation?

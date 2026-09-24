from app.models import EvidenceItem, ResolutionRecommendation, RiskLevel


class RuleBasedReasoner:
    """
    MVP stand-in for an LLM/agent.

    The interface is intentionally simple so that a future Azure/OpenAI
    implementation can replace this class without changing the orchestration flow.
    """

    def resolve(self, exception: dict, order: dict, shipment: dict, note: dict) -> ResolutionRecommendation:
        evidence = [
            EvidenceItem(
                source="ERP",
                fact=f"Requested delivery date is {order['requested_delivery_date']}",
                raw_reference=order["order_id"],
            ),
            EvidenceItem(
                source="Logistics",
                fact=f"Carrier ETA is {shipment['current_eta']} and status is {shipment['status']}",
                raw_reference=shipment["shipment_id"],
            ),
            EvidenceItem(
                source="Carrier note",
                fact=note["text"],
                raw_reference=note["note_id"],
            ),
        ]

        note_text = note["text"].lower()

        if "customs" in note_text and ("document" in note_text or "documentation" in note_text):
            category = "customs_documentation"
            summary = "Shipment delay is most likely caused by incomplete customs documentation."
            action = (
                "Request the missing customs document from the responsible party, "
                "then recheck the carrier ETA before updating the customer."
            )
            confidence = 0.93
            risk = RiskLevel.MEDIUM
            approval_required = True
        else:
            category = "unknown_logistics_exception"
            summary = "The available evidence is insufficient to determine a reliable root cause."
            action = "Escalate to a logistics specialist for manual investigation."
            confidence = 0.45
            risk = RiskLevel.HIGH
            approval_required = True

        return ResolutionRecommendation(
            exception_id=exception["exception_id"],
            category=category,
            summary=summary,
            recommended_action=action,
            confidence=confidence,
            risk_level=risk,
            human_approval_required=approval_required,
            evidence=evidence,
        )

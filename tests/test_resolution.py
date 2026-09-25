from app.service import resolve_exception


def test_customs_exception_resolution():
    result = resolve_exception("EX-001")
    assert result.category == "customs_documentation"
    assert result.human_approval_required is True
    assert result.confidence >= 0.9
    assert result.action_proposal.action_type == "request_document"
    assert result.action_proposal.document_type == "commercial_invoice"
    assert result.action_proposal.execution_mode == "record_only"
    assert result.action_proposal.supported is True
    assert len(result.evidence) == 3

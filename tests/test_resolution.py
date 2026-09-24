from app.service import resolve_exception


def test_customs_exception_resolution():
    result = resolve_exception("EX-001")
    assert result.category == "customs_documentation"
    assert result.human_approval_required is True
    assert result.confidence >= 0.9
    assert len(result.evidence) == 3

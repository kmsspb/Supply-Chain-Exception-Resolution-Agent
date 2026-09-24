import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.config import ROOT
from app.context import build_context
from app.errors import ResolutionError

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Family = Literal[
    "missing_customs_documents", "completed_documents", "weather_delays",
    "insufficient_information", "contradictory_sources", "embedded_instructions",
]
Category = Literal["customs_documentation", "customs_cleared", "weather_delay", "unknown_logistics_exception"]
FAMILIES = (
    "missing_customs_documents", "completed_documents", "weather_delays",
    "insufficient_information", "contradictory_sources", "embedded_instructions",
)
DATASET_PATH = ROOT / "data" / "evaluation_v1.json"


def canonical_hash(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Expectations(StrictModel):
    category: Category
    acceptable_action_criteria: list[Text] = Field(min_length=1)
    prohibited_actions: list[Text] = Field(min_length=1)
    prohibited_claims: list[Text] = Field(min_length=1)
    manual_escalation: bool = Field(strict=True)
    supporting_evidence_ids: list[Text] = Field(min_length=1)
    rationale: Text


class EvaluationCase(StrictModel):
    case_id: Text
    description: Text
    family: Family
    origin: Literal["seed", "new"]
    exception: dict
    order: dict
    shipment: dict
    note: dict
    expected: Expectations

    def context(self):
        return build_context(self.exception, self.order, self.shipment, self.note)

    @model_validator(mode="after")
    def validate_sources(self):
        try:
            context = self.context()
        except ResolutionError:
            raise ValueError("Invalid source records or relationships") from None
        if self.exception["exception_id"] != self.case_id:
            raise ValueError("Case and exception IDs differ")
        ids = {e.evidence_id for e in context.evidence}
        if not set(self.expected.supporting_evidence_ids) <= ids:
            raise ValueError("Expected evidence references do not exist")
        return self


class EvaluationDataset(StrictModel):
    name: Text
    version: Text
    cases: list[EvaluationCase] = Field(min_length=30, max_length=30)

    @model_validator(mode="after")
    def validate_balance(self):
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("Duplicate case ID")
        if Counter(case.family for case in self.cases) != Counter({family: 5 for family in FAMILIES}):
            raise ValueError("Expected five cases in each scenario family")
        for family in FAMILIES:
            if sum(case.origin == "seed" for case in self.cases if case.family == family) != 1:
                raise ValueError("Expected one seed and four new cases per family")
        return self


def load_dataset(path: Path = DATASET_PATH) -> EvaluationDataset:
    return EvaluationDataset.model_validate(read_json(path))

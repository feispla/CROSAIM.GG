import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts" / "crosaim" / "v1"


def load_schema(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def test_all_shared_schemas_are_valid_draft_2020_12_documents():
    for name in ("content_compliance.schema.json", "sync_event.schema.json", "application_sync.schema.json"):
        schema = load_schema(name)
        Draft202012Validator.check_schema(schema)


def test_content_compliance_requires_strict_structured_result():
    schema = load_schema("content_compliance.schema.json")
    valid = {
        "violates": False,
        "violation_categories": [],
        "violation_reason": "",
        "confidence": 0.98,
        "review_required": False,
        "policy_version": "1.0.0",
        "evidence": [],
    }
    Draft202012Validator(schema).validate(valid)
    with pytest.raises(Exception):
        Draft202012Validator(schema).validate({**valid, "unexpected": True})


def test_existing_application_submitted_example_matches_sync_event_contract():
    schema = load_schema("sync_event.schema.json")
    fixture = json.loads((ROOT / "examples" / "application_submitted.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(fixture)

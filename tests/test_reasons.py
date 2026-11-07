"""Quarantine reasons are plain English and never echo the raw value."""

import pytest

from schema_fixer.checker import QUARANTINE_SUFFIX, row_model, validate_row
from schema_fixer.mapping import Mapping
from schema_fixer.models import TargetSchema

SCHEMA = TargetSchema.model_validate(
    {
        "name": "reasons",
        "fields": {
            "email": {"type": "string", "format": "email", "required": True},
            "plan": {"type": "string", "enum": ["free", "pro"]},
            "joined": {"type": "date"},
            "quantity": {"type": "integer"},
            "phone": {"type": "string", "format": "phone"},
        },
    }
)


def entry(target, transform=None):
    return {
        "target": target,
        "sources": [target],
        "transform": transform or {"name": "rename"},
        "confidence": 1,
        "reason": "test",
    }


def reasons(record, fields=None):
    mapping = Mapping.model_validate(
        {
            "fields": fields or [entry(name) for name in SCHEMA.fields],
            "drop": [],
            "unmapped_required": [],
            "unmapped_optional": [],
        }
    )
    _, issues = validate_row(mapping, record, row_model(SCHEMA), 1)
    assert all(i.message.endswith(QUARANTINE_SUFFIX) for i in issues)
    return {i.field: i.message.removesuffix(QUARANTINE_SUFFIX) for i in issues}


GOOD = {
    "email": "ada@example.com",
    "plan": "pro",
    "joined": "2026-11-06",
    "quantity": "2",
    "phone": "+639171234567",
}


@pytest.mark.parametrize(
    "field, raw, expected",
    [
        ("email", "zz-secret", "not a valid email address"),
        ("email", "   ", "required value is blank"),
        ("plan", "zz-secret", "not an allowed value (allowed: free, pro)"),
        ("joined", "2026-02-30", "not a real date in YYYY-MM-DD form"),
        ("quantity", "zz-secret", "not a whole number"),
        ("quantity", "2.5", "not a whole number"),
        ("phone", "123", "not a valid phone number (+ and 7-15 digits)"),
    ],
)
def test_row_reasons_are_plain_english(field, raw, expected):
    found = reasons({**GOOD, field: raw})
    assert found == {field: expected}
    assert raw.strip() == "" or raw not in found[field]


def test_transform_failures_name_the_transform_safely():
    fields = [
        entry(name) for name in SCHEMA.fields if name not in {"joined", "quantity"}
    ]
    fields.append(entry("joined", {"name": "parse_date", "format": "%m/%d/%y"}))
    fields.append(entry("quantity", {"name": "cast", "type": "integer"}))
    found = reasons({**GOOD, "joined": "zz-secret", "quantity": "zz-many"}, fields)
    assert found == {
        "joined": "date does not match format %m/%d/%y",
        "quantity": "could not convert to integer",
    }

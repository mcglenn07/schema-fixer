import pandas as pd
import pytest

from schema_fixer.profiler import mask_sample, profile_table


def test_profiles_use_all_rows_but_only_three_samples():
    report = profile_table(
        pd.DataFrame(
            {
                "quantity": ["1", "2", "3", "not-numeric", None, "  "],
                "empty": [None] * 6,
            }
        )
    )
    quantity, empty = report.columns
    assert report.row_count == 6
    assert quantity.inferred_type == "mixed"
    assert quantity.null_percent == 33.33
    assert quantity.samples == ["1", "2", "3"]
    assert empty.inferred_type == "unknown"
    assert empty.null_percent == 100.0
    assert empty.samples == []


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["1", "2"], "integer"),
        (["1", "2.5", "3e2"], "number"),
        ([True, "false"], "boolean"),
        (["2026-11-06", "2024-02-29"], "date"),
        (["2026-02-29"], "string"),
        ([True, 1], "mixed"),
        (["plain", "words"], "string"),
    ],
)
def test_inferred_types(values, expected):
    report = profile_table(pd.DataFrame({"value": values}, dtype=object))
    assert report.columns[0].inferred_type == expected


@pytest.mark.parametrize(
    ("value", "column", "expected"),
    [
        ("Ada <ada@example.com>", "note", "Ada <[EMAIL]>"),
        ("broken-email", "Email Address", "[EMAIL]"),
        ("Call +63 917 123 4567", "note", "Call [PHONE]"),
        ("Call (202) 555-0123", "note", "Call [PHONE]"),
        ("09171234567", "other", "[PHONE]"),
        (639171234567, "mobile_number", "[PHONE]"),
        ("2026-11-06", "signup_date", "2026-11-06"),
        ("06-11-2026", "created_date", "06-11-2026"),
        ("2026.11.06", "created_date", "2026.11.06"),
        ("31-02-2026", "created_date", "31-02-2026"),
    ],
)
def test_masking(value, column, expected):
    assert mask_sample(value, column) == expected


def test_masking_happens_before_truncation_and_covers_every_sample():
    values = ["x " * 70 + "ada@example.com", "ben@example.com", "cara@example.com"]
    report = profile_table(pd.DataFrame({"contact": values}))
    serialized = report.model_dump_json()
    assert "@" not in serialized
    assert len(report.columns[0].samples) == 3
    assert max(map(len, report.columns[0].samples)) <= 120


def test_empty_table_profiles_have_zero_null_percent():
    report = profile_table(pd.DataFrame(columns=["email"]))
    assert report.columns[0].null_percent == 0.0
    assert report.columns[0].inferred_type == "unknown"

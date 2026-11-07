import pandas as pd
from pandas.testing import assert_frame_equal

from schema_fixer.detector import detect
from schema_fixer.io import load_schema
from schema_fixer.models import TargetSchema


def findings_for(report, code):
    return [finding for finding in report.findings if finding.code == code]


def test_valid_customers_list_absent_optional_fields_only(root):
    frame = pd.DataFrame({"email": ["ada@example.com"], "full_name": ["Ada Reyes"]})
    report = detect(frame, load_schema(root / "schemas/customer.yaml"))
    assert [(f.code, f.field) for f in report.findings] == [
        ("missing_optional", "plan"),
        ("missing_optional", "signup_date"),
    ]


def test_complete_customers_have_no_findings(root):
    frame = pd.DataFrame(
        {
            "email": ["ada@example.com"],
            "full_name": ["Ada Reyes"],
            "plan": ["pro"],
            "signup_date": ["2026-11-06"],
        }
    )
    assert detect(frame, load_schema(root / "schemas/customer.yaml")).findings == []


def test_rename_hint_does_not_hide_missing_optional(root):
    frame = pd.DataFrame(
        {
            "email": ["ada@example.com"],
            "full_name": ["Ada"],
            "Signup Date": ["2026-11-06"],
        }
    )
    report = detect(frame, load_schema(root / "schemas/customer.yaml"))
    assert {f.field for f in findings_for(report, "missing_optional")} == {
        "plan",
        "signup_date",
    }
    hint = findings_for(report, "likely_rename")[0]
    assert (hint.field, hint.source) == ("signup_date", "Signup Date")


def test_collects_all_value_errors_and_does_not_modify_input(root):
    frame = pd.DataFrame(
        {
            "email": ["ada@example.com", "bad", "ben@example.com", "late-bad"],
            "full_name": ["Ada", " ", "Ben", "Cara"],
            "plan": ["pro", "enterprise", "free", "team"],
            "signup_date": ["2026-11-06", "2026-02-30", None, "11/06/26"],
            "debug": ["x"] * 4,
        },
        index=[10, 20, 30, 40],
    )
    original = frame.copy(deep=True)
    report = detect(frame, load_schema(root / "schemas/customer.yaml"))
    assert_frame_equal(frame, original)
    assert findings_for(report, "null_required")[0].rows == [2]
    assert findings_for(report, "enum_drift")[0].rows == [2, 4]
    formats = {
        finding.field: finding.rows
        for finding in findings_for(report, "format_mismatch")
    }
    assert formats == {"email": [2, 4], "signup_date": [2, 4]}
    assert findings_for(report, "extra_column")[0].source == "debug"
    assert "ada@example.com" not in report.model_dump_json()
    assert "late-bad" not in report.model_dump_json()


def test_rename_hints_are_tentative_and_leave_missing_and_extra_findings(root):
    frame = pd.DataFrame({"Email Address": ["bad"], "full_name": ["Ada"]})
    report = detect(frame, load_schema(root / "schemas/customer.yaml"))
    hint = findings_for(report, "likely_rename")[0]
    assert (hint.source, hint.field, hint.tentative) == ("Email Address", "email", True)
    assert findings_for(report, "missing_required")[0].field == "email"
    assert findings_for(report, "extra_column")[0].source == "Email Address"
    assert findings_for(report, "format_mismatch")[0].tentative


def test_ambiguous_candidates_are_not_reported_as_likely(root):
    frame = pd.DataFrame(
        {
            "billing_email": ["ada@example.com"],
            "shipping_email": ["ben@example.com"],
            "full_name": ["Ada"],
        }
    )
    report = detect(frame, load_schema(root / "schemas/customer.yaml"))
    assert not findings_for(report, "likely_rename")


def test_one_source_cannot_be_suggested_for_two_targets():
    schema = TargetSchema.model_validate(
        {
            "name": "x",
            "fields": {
                "billing_email": {"type": "string", "required": True},
                "shipping_email": {"type": "string", "required": True},
            },
        }
    )
    report = detect(pd.DataFrame({"email": ["ada@example.com"]}), schema)
    assert not findings_for(report, "likely_rename")


def test_numeric_type_failures_do_not_treat_booleans_as_numbers():
    schema = TargetSchema.model_validate(
        {
            "name": "x",
            "fields": {
                "quantity": {"type": "integer"},
                "total": {"type": "number"},
            },
        }
    )
    frame = pd.DataFrame(
        {
            "quantity": ["1", "2.5", True, "many", None],
            "total": ["1", "2.5", False, "1e9999", None],
        },
        dtype=object,
    )
    failures = {f.field: f.rows for f in detect(frame, schema).findings}
    assert failures == {"quantity": [2, 3, 4], "total": [3, 4]}


def test_numeric_json_is_not_silently_accepted_as_a_string():
    schema = TargetSchema.model_validate(
        {"name": "x", "fields": {"id": {"type": "string"}}}
    )
    report = detect(pd.DataFrame({"id": [123]}, dtype=object), schema)
    assert findings_for(report, "type_mismatch")[0].rows == [1]


def test_empty_json_still_reports_missing_columns(root):
    report = detect(pd.DataFrame(), load_schema(root / "schemas/customer.yaml"))
    assert {(f.code, f.field) for f in report.findings} == {
        ("missing_required", "email"),
        ("missing_required", "full_name"),
        ("missing_optional", "plan"),
        ("missing_optional", "signup_date"),
    }


def test_required_null_is_reported_once_and_optional_null_is_allowed(root):
    frame = pd.DataFrame(
        {"email": [None], "full_name": ["Ada"], "plan": [None], "signup_date": [None]}
    )
    report = detect(frame, load_schema(root / "schemas/customer.yaml"))
    assert [(f.code, f.field) for f in report.findings] == [("null_required", "email")]

"""Behavioral checks for draft generation and all local guardrails, without APIs."""

import copy
import json
from types import SimpleNamespace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError
from typer.testing import CliRunner

from schema_fixer.checker import check_mapping, row_model
from schema_fixer.cli import app
from schema_fixer.config import Settings, load_settings
from schema_fixer.io import load_schema, read_table
from schema_fixer.mapping import Mapping
from schema_fixer.models import TargetSchema
from schema_fixer.profiler import profile_table
from schema_fixer.providers import ProviderError
from schema_fixer.providers.baseline import BaselineProposer
from schema_fixer.providers.openai import OpenAIProposer, build_payload
from schema_fixer.transforms import cast_value, transform_field


def entry(target, sources=None, name="rename", **parameters):
    return {
        "target": target,
        "sources": [target] if sources is None else sources,
        "transform": dict(name=name, **parameters),
        "confidence": 0.9,
        "reason": "Test proposal, subject to local checking.",
    }


def mapping(*fields, required=(), optional=(), dropped=()):
    return Mapping.model_validate(
        {
            "fields": list(fields),
            "unmapped_required": list(required),
            "unmapped_optional": list(optional),
            "drop": [
                {
                    "sources": [source],
                    "transform": {"name": "drop"},
                    "confidence": 0.0,
                    "reason": "Unused source.",
                }
                for source in dropped
            ],
        }
    )


def simple_schema(**fields):
    return TargetSchema.model_validate({"name": "test", "fields": fields})


def codes(result):
    return {issue.code for issue in result.issues}


def test_baseline_real_renames_pass_without_mutating_input(root):
    frame = read_table(root / "eval/cases/09_order_header_renames/incoming.csv")
    original = frame.copy(deep=True)
    schema = load_schema(root / "schemas/order.yaml")
    proposal = BaselineProposer().propose(schema, profile_table(frame).columns)
    assert {f.target: f.sources for f in proposal.fields}["order_id"] == ["Order ID"]
    assert all(f.transform.name == "rename" for f in proposal.fields)
    result = check_mapping(proposal, frame, schema)
    assert result.passed and result.valid_rows == 3
    assert_frame_equal(frame, original)


def test_baseline_abstains_on_ambiguous_headers_and_preserves_exact_matches():
    schema = simple_schema(
        email={"type": "string", "required": True}, name={"type": "string"}
    )
    frame = pd.DataFrame(
        {"billing_email": ["a"], "shipping_email": ["b"], "name": ["Ada"]}
    )
    proposal = BaselineProposer().propose(schema, profile_table(frame).columns)
    assert [f.target for f in proposal.fields] == ["name"]
    assert proposal.unmapped_required == ["email"]
    assert {s for drop in proposal.drop for s in drop.sources} == {
        "billing_email",
        "shipping_email",
    }
    assert "unmapped_required" in codes(check_mapping(proposal, frame, schema))


def test_baseline_does_not_read_values_to_invent_semantic_transforms(root):
    schema = load_schema(root / "schemas/customer.yaml")
    frame = read_table(root / "eval/cases/01_customer_spec_example/incoming.csv")
    proposal = BaselineProposer().propose(schema, profile_table(frame).columns)
    assert proposal.unmapped_required == ["full_name"]
    assert set(proposal.unmapped_optional) == {"plan", "signup_date"}
    result = check_mapping(proposal, frame, schema)
    assert not result.passed and result.rows_checked == 0


def test_all_transforms_and_two_parts_from_same_column_are_checked():
    schema = simple_schema(
        full_name={"type": "string", "required": True},
        email={"type": "string", "format": "email", "required": True},
        username={"type": "string"},
        name={"type": "string"},
        day={"type": "date"},
        quantity={"type": "integer"},
        plan={"type": "string", "enum": ["pro"]},
        status={"type": "string", "enum": ["open"]},
    )
    frame = pd.DataFrame(
        [
            {
                "First": "Ada",
                "Last": "Reyes",
                "Contact": "Ada | ada@example.com",
                "user": "ada",
                "joined": "11/06/26",
                "qty": "2",
                "subscription": "Pro Monthly",
                "debug": "x",
            }
        ]
    )
    proposal = mapping(
        entry("full_name", ["First", "Last"], "combine", separator=" "),
        entry("email", ["Contact"], "split", separator=" | ", index=1),
        entry("name", ["Contact"], "split", separator=" | ", index=0),
        entry("username", ["user"]),
        entry("day", ["joined"], "parse_date", format="%m/%d/%y"),
        entry("quantity", ["qty"], "cast", type="integer"),
        entry(
            "plan",
            ["subscription"],
            "map_values",
            values=[{"source": "Pro Monthly", "target": "pro"}],
        ),
        entry("status", [], "constant", value="open"),
        dropped=["debug"],
    )
    result = check_mapping(proposal, frame, schema)
    assert result.passed and result.valid_rows == 1
    assert codes(result) == {"constant_review"}


@pytest.mark.parametrize(
    "bad_transform",
    [
        {"name": "python", "code": "print('bad')"},
        {"name": "rename", "code": "unapproved"},
        {"name": "split", "separator": "", "index": 0},
        {"name": "split", "separator": "|", "index": -1},
        {"name": "cast", "type": "exec"},
        {
            "name": "map_values",
            "values": [{"source": "a", "target": "b"}, {"source": "a", "target": "c"}],
        },
    ],
)
def test_invalid_contract_is_flagged_before_transform_execution(bad_transform):
    payload = mapping(entry("x")).model_dump()
    payload["fields"][0]["transform"] = bad_transform
    result = check_mapping(
        payload, pd.DataFrame({"x": ["a"]}), simple_schema(x={"type": "string"})
    )
    assert not result.passed and result.rows_checked == 0
    assert codes(result) == {"invalid_mapping"}


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("nan"), float("inf"), "0.5"])
def test_confidence_must_be_a_finite_number_in_range(confidence):
    payload = entry("x")
    payload["confidence"] = confidence
    with pytest.raises(ValidationError):
        mapping(payload)


@pytest.mark.parametrize(
    ("proposal", "expected"),
    [
        (lambda: mapping(entry("x", ["missing"]), dropped=["x"]), "missing_source"),
        (lambda: mapping(entry("wrong", ["x"]), optional=["x"]), "unknown_target"),
        (lambda: mapping(entry("x"), entry("x")), "duplicate_target"),
        (lambda: mapping(entry("x"), dropped=["x"]), "conflicting_drop"),
        (lambda: mapping(optional=["x"]), "unaccounted_source"),
        (lambda: mapping(dropped=["x"]), "unaccounted_target"),
        (lambda: mapping(entry("x"), dropped=["missing"]), "missing_drop_source"),
        (
            lambda: mapping(entry("x", name="parse_date", format="%m/%d")),
            "incomplete_date_format",
        ),
    ],
)
def test_structural_failures(proposal, expected):
    result = check_mapping(
        proposal(), pd.DataFrame({"x": ["hello"]}), simple_schema(x={"type": "string"})
    )
    assert expected in codes(result)
    assert not result.passed and result.rows_checked == 0


def test_source_reuse_requires_different_indices_of_same_split():
    schema = simple_schema(a={"type": "string"}, b={"type": "string"})
    frame = pd.DataFrame({"x": ["a|b"]})
    proposal = mapping(entry("a", ["x"]), entry("b", ["x"]))
    assert "source_reused" in codes(check_mapping(proposal, frame, schema))


def test_required_field_cannot_hide_in_optional_group():
    result = check_mapping(
        mapping(optional=["x"]),
        pd.DataFrame(),
        simple_schema(x={"type": "string", "required": True}),
    )
    assert "wrong_missing_group" in codes(result)


def test_optional_omission_does_not_block_valid_sample():
    result = check_mapping(
        mapping(entry("x"), optional=["y"]),
        pd.DataFrame({"x": ["a"]}),
        simple_schema(x={"type": "string", "required": True}, y={"type": "string"}),
    )
    assert result.passed and codes(result) == {"unmapped_optional"}


def test_empty_file_cannot_claim_sample_check_passed():
    result = check_mapping(
        mapping(entry("x")),
        pd.DataFrame(columns=["x"]),
        simple_schema(x={"type": "string"}),
    )
    assert not result.passed and codes(result) == {"no_sample"}


def test_sample_is_bounded_and_dirty_rows_warn_without_leaking_values():
    schema = simple_schema(
        email={"type": "string", "format": "email", "required": True}
    )
    frame = pd.DataFrame({"email": ["ada@example.com", "private-invalid-address"]})
    first = check_mapping(mapping(entry("email")), frame, schema, sample_size=1)
    assert first.passed and first.rows_checked == 1
    full = check_mapping(mapping(entry("email")), frame, schema)
    assert full.passed and full.valid_rows == 1
    assert full.quarantine_rows == [2]
    assert all(
        i.severity == "warning" and "would be quarantined" in i.message
        for i in full.issues
    )
    assert [(i.field, i.row) for i in full.issues] == [("email", 2)]
    assert "private-invalid-address" not in full.model_dump_json()
    assert "ada@example.com" not in full.model_dump_json()


def test_bad_date_unknown_enum_and_split_failure_all_report_correct_rows():
    schema = simple_schema(
        day={"type": "date"},
        plan={"type": "string", "enum": ["pro"]},
        email={"type": "string"},
    )
    frame = pd.DataFrame(
        {"day": ["31/02/2026"], "plan": ["Enterprise"], "contact": ["no-delimiter"]}
    )
    proposal = mapping(
        entry("day", name="parse_date", format="%d/%m/%Y"),
        entry(
            "plan",
            name="map_values",
            values=[{"source": "Pro Monthly", "target": "pro"}],
        ),
        entry("email", ["contact"], "split", separator=" | ", index=1),
    )
    result = check_mapping(proposal, frame, schema)
    assert not result.passed
    assert {(i.code, i.field, i.row) for i in result.issues if i.row is not None} == {
        ("transform_failed", "day", 1),
        ("transform_failed", "email", 1),
        ("row_invalid", "plan", 1),
    }
    assert {i.field for i in result.issues if i.code == "all_rows_failed_field"} == {
        "day",
        "email",
        "plan",
    }
    assert result.quarantine_rows == [1]


@pytest.mark.parametrize(
    ("value", "target"),
    [
        (True, "integer"),
        (True, "number"),
        (2.5, "integer"),
        ("2.5", "integer"),
        ("yes", "boolean"),
        ("1e999", "number"),
    ],
)
def test_casts_reject_lossy_or_unsupported_values(value, target):
    with pytest.raises((ValueError, TypeError)):
        cast_value(value, target)


def test_missing_combine_part_does_not_invent_a_partial_required_name():
    result = check_mapping(
        mapping(entry("name", ["First", "Last"], "combine", separator=" ")),
        pd.DataFrame({"First": ["Ada"], "Last": [None]}),
        simple_schema(name={"type": "string", "required": True}),
    )
    assert not result.passed and result.issues[0].field == "name"


def test_row_model_rejects_booleans_as_numbers_and_accepts_arbitrary_schema_headers():
    validator = row_model(
        simple_schema(
            _id={"type": "string", "required": True}, quantity={"type": "integer"}
        )
    )
    with pytest.raises(ValidationError):
        validator.model_validate({"quantity": 1})
    with pytest.raises(ValidationError):
        validator.model_validate({"_id": "001", "quantity": True})
    assert validator.model_validate({"_id": "001", "quantity": "2"}).model_dump(
        by_alias=True
    ) == {"_id": "001", "quantity": 2}


def fake_client(response):
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        return response

    return SimpleNamespace(responses=SimpleNamespace(parse=parse)), calls


def test_openai_payload_and_call_use_only_schema_and_masked_profiles():
    schema = simple_schema(email={"type": "string", "format": "email"})
    frame = pd.DataFrame(
        {
            "email": ["ada@example.com", "ben@example.com"],
            "note": ["call +63 917 123 4567", "private four"],
        }
    )
    columns = profile_table(frame).columns
    proposal = mapping(entry("email"), dropped=["note"])
    response = SimpleNamespace(status="completed", output=[], output_parsed=proposal)
    client, calls = fake_client(response)
    result = OpenAIProposer(
        Settings(api_key="secret-not-to-be-sent-in-payload"), client=client
    ).propose(schema, columns)
    assert result == proposal and len(calls) == 1
    request = calls[0]
    assert request["text_format"] is Mapping and request["store"] is False
    payload = json.loads(request["input"][0]["content"])
    assert set(payload) == {"target_schema", "column_profiles"}
    assert all(
        set(c) == {"name", "inferred_type", "null_percent", "samples"}
        for c in payload["column_profiles"]
    )
    serialized = json.dumps(payload)
    assert "ada@example.com" not in serialized and "917" not in serialized
    assert "secret-not-to-be-sent-in-payload" not in serialized
    assert "row_count" not in serialized


def test_provider_remasks_profiles_before_sending():
    columns = profile_table(pd.DataFrame({"contact": ["placeholder"]})).columns
    columns[0].samples = ["ada@example.com"]
    payload = build_payload(simple_schema(contact={"type": "string"}), columns)
    assert "ada@example.com" not in payload and "[EMAIL]" in payload


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(status="incomplete", output=[], output_parsed=None),
        SimpleNamespace(status="completed", output=[], output_parsed=None),
        SimpleNamespace(
            status="completed",
            output=[
                SimpleNamespace(
                    type="message", content=[SimpleNamespace(type="refusal")]
                )
            ],
            output_parsed=None,
        ),
    ],
)
def test_openai_unusable_responses_are_rejected(response):
    client, calls = fake_client(response)
    with pytest.raises(ProviderError):
        OpenAIProposer(Settings(), client=client).propose(
            simple_schema(x={"type": "string"}), []
        )
    assert len(calls) == 1


def test_no_key_is_a_friendly_error_and_never_opens_a_client():
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        OpenAIProposer(Settings())


def test_configuration_precedence_and_secret_repr(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in ("PROVIDER", "OPENAI_MODEL", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert load_settings().provider == "openai"
    (tmp_path / ".env").write_text(
        "PROVIDER=baseline\nOPENAI_MODEL=example-model\nOPENAI_API_KEY=example-secret\n"
    )
    assert load_settings().provider == "baseline"
    monkeypatch.setenv("PROVIDER", "openai")
    assert load_settings().provider == "openai"
    assert load_settings("baseline").provider == "baseline"
    assert "example-secret" not in repr(load_settings())
    with pytest.raises(ProviderError):
        load_settings("ollama")


def test_propose_cli_success_flagging_json_and_no_output_files(
    root, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    good = [
        "propose",
        str(root / "eval/cases/09_order_header_renames/incoming.csv"),
        "--schema",
        str(root / "schemas/order.yaml"),
        "--provider",
        "baseline",
    ]
    result = runner.invoke(app, good)
    assert result.exit_code == 0, result.output
    assert "PASSED" in result.output and "draft" in result.output
    structured = runner.invoke(app, [*good, "--json"])
    assert json.loads(structured.output)["checks"]["passed"] is True
    bad = [
        "propose",
        str(root / "eval/cases/01_customer_spec_example/incoming.csv"),
        "--schema",
        str(root / "schemas/customer.yaml"),
        "--provider",
        "baseline",
        "--json",
    ]
    flagged = runner.invoke(app, bad)
    assert flagged.exit_code == 1
    assert json.loads(flagged.output)["checks"]["passed"] is False
    assert list(tmp_path.iterdir()) == []
    assert runner.invoke(app, [*good, "--sample-size", "0"]).exit_code == 2


def test_real_sdk_serializes_strict_schema_and_parses_mock_response():
    import httpx2
    from openai import OpenAI

    proposal = mapping(entry("x"))
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": "gpt-6-luna",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_test",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": proposal.model_dump_json(),
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
            },
        )

    with OpenAI(
        api_key="test-only",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handle)),
    ) as client:
        result = OpenAIProposer(Settings(), client=client).propose(
            simple_schema(x={"type": "string"}), []
        )
    assert result == proposal and len(requests) == 1
    format_schema = requests[0]["text"]["format"]
    assert format_schema["type"] == "json_schema" and format_schema["strict"] is True

    def verify(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            assert "oneOf" not in node
            for value in node.values():
                verify(value)
        elif isinstance(node, list):
            for value in node:
                verify(value)

    verify(format_schema["schema"])


def test_sample_check_revalidates_even_a_mutated_mapping_instance():
    proposal = mapping(entry("x"))
    broken = copy.deepcopy(proposal)
    broken.fields[0].confidence = 9.0
    result = check_mapping(
        broken, pd.DataFrame({"x": ["a"]}), simple_schema(x={"type": "string"})
    )
    assert codes(result) == {"invalid_mapping"}


def test_escaped_year_directive_cannot_introduce_a_default_year():
    proposal = mapping(entry("day", name="parse_date", format="%%Y-%m-%d"))
    result = check_mapping(
        proposal,
        pd.DataFrame({"day": ["%Y-11-06"]}),
        simple_schema(day={"type": "date"}),
    )
    assert "incomplete_date_format" in codes(result)
    assert result.rows_checked == 0


def test_baseline_ignores_irrelevant_openai_configuration(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_MODEL", "")
    assert load_settings("baseline").provider == "baseline"


@pytest.mark.parametrize(
    ("status", "message"),
    [(401, "authentication"), (429, "quota"), (500, "request failed")],
)
def test_sdk_api_errors_are_sanitized_without_retries(status, message):
    import httpx2
    from openai import OpenAI

    requests = []

    def handle(request):
        requests.append(request)
        return httpx2.Response(
            status,
            json={"error": {"message": "sensitive-server-text", "type": "test_error"}},
        )

    with (
        OpenAI(
            api_key="test-only",
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(handle)),
        ) as client,
        pytest.raises(ProviderError, match=message) as captured,
    ):
        OpenAIProposer(Settings(), client=client).propose(
            simple_schema(x={"type": "string"}), []
        )
    assert "sensitive-server-text" not in str(captured.value)
    assert len(requests) == 1


def test_production_client_has_bounded_request_settings_and_closes(monkeypatch):
    import schema_fixer.providers.openai as module

    constructed = []
    closed = []
    client, calls = fake_client(
        SimpleNamespace(
            status="completed", output=[], output_parsed=mapping(entry("x"))
        )
    )
    client.close = lambda: closed.append(True)

    def construct(**kwargs):
        constructed.append(kwargs)
        return client

    monkeypatch.setattr(module, "OpenAI", construct)
    OpenAIProposer(Settings(api_key="test-only")).propose(
        simple_schema(x={"type": "string"}), []
    )
    assert constructed[0]["max_retries"] == 0
    assert constructed[0]["timeout"] == 45.0
    assert constructed[0]["base_url"] == "https://api.openai.com/v1"
    assert calls[0]["max_output_tokens"] == 4096
    assert calls[0]["reasoning"] == {"effort": "low"}
    assert closed == [True]


def test_openai_cli_checks_the_spec_example_without_sending_original_rows(
    root, monkeypatch, tmp_path
):
    import schema_fixer.proposals as service

    proposal = mapping(
        entry("email", ["Email Address"]),
        entry("full_name", ["First", "Last"], "combine", separator=" "),
        entry(
            "plan",
            ["Subscription"],
            "map_values",
            values=[
                {"source": "Pro Monthly", "target": "pro"},
                {"source": "Free", "target": "free"},
            ],
        ),
        entry("signup_date", ["Joined"], "parse_date", format="%m/%d/%y"),
    )
    received = []

    def propose(schema, columns):
        received.append((schema, columns))
        return proposal

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        service, "create_proposer", lambda settings: SimpleNamespace(propose=propose)
    )
    result = CliRunner().invoke(
        app,
        [
            "propose",
            str(root / "eval/cases/01_customer_spec_example/incoming.csv"),
            "--schema",
            str(root / "schemas/customer.yaml"),
            "--provider",
            "openai",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["checks"]["passed"] is True
    assert report["checks"]["valid_rows"] == 2
    assert report["checks"]["quarantine_rows"] == [3]
    assert report["checks"]["issues"][0]["severity"] == "warning"
    assert "would be quarantined" in report["checks"]["issues"][0]["message"]
    assert [(i["field"], i["row"]) for i in report["checks"]["issues"]] == [
        ("email", 3)
    ]
    sent = [column.model_dump_json() for column in received[0][1]]
    assert "ada@example.com" not in str(sent)
    assert "not-an-email" not in result.output
    assert list(tmp_path.iterdir()) == []


def test_case18_dirty_rows_warn_on_different_fields_without_flagging(root):
    frame = read_table(root / "eval/cases/18_ticket_nulls_and_formats/incoming.json")
    schema = load_schema(root / "schemas/support_ticket.yaml")
    proposal = mapping(*(entry(name) for name in schema.fields))
    result = check_mapping(proposal, frame, schema)
    assert result.passed and result.valid_rows == 1
    assert result.quarantine_rows == [2, 3]
    assert {(i.field, i.row) for i in result.issues} == {
        ("requester_email", 2),
        ("subject", 2),
        ("priority", 3),
        ("phone", 3),
    }
    assert all(
        i.severity == "warning" and "would be quarantined" in i.message
        for i in result.issues
    )


def test_all_rows_failing_different_fields_is_not_a_systematic_field_failure():
    schema = simple_schema(
        email={"type": "string", "format": "email"}, day={"type": "date"}
    )
    frame = pd.DataFrame(
        {"email": ["bad", "ada@example.com"], "day": ["2026-11-06", "bad"]}
    )
    result = check_mapping(mapping(entry("email"), entry("day")), frame, schema)
    assert result.passed and result.valid_rows == 0
    assert result.quarantine_rows == [1, 2]
    assert all(i.severity == "warning" for i in result.issues)


def test_systematic_guard_combines_transform_and_validation_failures_per_field():
    schema = simple_schema(
        email={"type": "string", "format": "email", "required": True}
    )
    frame = pd.DataFrame({"contact": ["missing separator", "Ada|invalid-email"]})
    result = check_mapping(
        mapping(entry("email", ["contact"], "split", separator="|", index=1)),
        frame,
        schema,
    )
    assert not result.passed and result.valid_rows == 0
    assert result.quarantine_rows == [1, 2]
    assert {(i.code, i.row) for i in result.issues if i.severity == "warning"} == {
        ("transform_failed", 1),
        ("row_invalid", 2),
    }
    errors = [i for i in result.issues if i.severity == "error"]
    assert [(i.code, i.field, i.row) for i in errors] == [
        ("all_rows_failed_field", "email", None)
    ]


def test_systematic_guard_uses_checked_rows_not_the_whole_file():
    schema = simple_schema(email={"type": "string", "format": "email"})
    frame = pd.DataFrame({"email": ["bad-one", "bad-two", "ada@example.com"]})
    proposal = mapping(entry("email"))
    short = check_mapping(proposal, frame, schema, sample_size=2)
    full = check_mapping(proposal, frame, schema, sample_size=3)
    assert not short.passed and "all_rows_failed_field" in codes(short)
    assert full.passed and full.valid_rows == 1
    assert full.quarantine_rows == [1, 2]


def test_isolated_parse_failure_warns_but_wrong_format_on_every_row_flags():
    schema = simple_schema(day={"type": "date"})
    proposal = mapping(entry("day", name="parse_date", format="%d/%m/%Y"))
    dirty = check_mapping(
        proposal,
        pd.DataFrame({"day": ["06/11/2026", "31/02/2026", "20/09/2026"]}),
        schema,
    )
    assert dirty.passed and dirty.valid_rows == 2 and dirty.quarantine_rows == [2]
    assert [(i.code, i.severity) for i in dirty.issues] == [
        ("transform_failed", "warning")
    ]
    wrong = check_mapping(
        proposal, pd.DataFrame({"day": ["2026-11-06", "2026-10-15"]}), schema
    )
    assert not wrong.passed and wrong.quarantine_rows == [1, 2]
    assert [(i.code, i.field) for i in wrong.issues if i.severity == "error"] == [
        ("all_rows_failed_field", "day")
    ]


@pytest.mark.parametrize(
    ("case", "schema_name", "source", "target", "fmt", "samples"),
    [
        (
            "01_customer_spec_example/incoming.csv",
            "customer",
            "Joined",
            "signup_date",
            "%m/%d/%y",
            ["11/06/26", "10/15/26", "09/20/26"],
        ),
        (
            "20_ticket_mixed_drift/incoming.json",
            "support_ticket",
            "created_date",
            "created_date",
            "%d-%m-%Y",
            ["06-11-2026", "15-10-2026", "20-09-2026"],
        ),
    ],
)
def test_date_evidence_reaches_provider_and_returned_format_parses_every_sample(
    root, case, schema_name, source, target, fmt, samples
):
    schema = load_schema(root / f"schemas/{schema_name}.yaml")
    frame = read_table(root / "eval/cases" / case)
    proposal = mapping(entry(target, [source], "parse_date", format=fmt))
    client, calls = fake_client(
        SimpleNamespace(status="completed", output=[], output_parsed=proposal)
    )
    parsed = OpenAIProposer(Settings(), client=client).propose(
        schema, profile_table(frame).columns
    )
    payload = json.loads(calls[0]["input"][0]["content"])
    sent = next(c for c in payload["column_profiles"] if c["name"] == source)
    assert sent["samples"] == samples
    assert [
        transform_field(parsed.fields[0], {source: sample}) for sample in samples
    ] == ["2026-11-06", "2026-10-15", "2026-09-20"]


def test_case18_cli_passes_with_quarantine_warnings_and_writes_no_files(
    root, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "propose",
            str(root / "eval/cases/18_ticket_nulls_and_formats/incoming.json"),
            "--schema",
            str(root / "schemas/support_ticket.yaml"),
            "--provider",
            "baseline",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Checks: PASSED" in result.output
    assert "Would quarantine: 2" in result.output
    assert "would be quarantined" in result.output
    assert "FLAGGED" not in result.output
    assert list(tmp_path.iterdir()) == []

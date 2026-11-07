"""Offline scoring, accounting, privacy and exactly-once attempt regressions."""

import copy
import json
import shutil
from types import SimpleNamespace

import pytest
import yaml

from schema_fixer import eval_runner
from schema_fixer.config import Settings
from schema_fixer.evaluation import (
    aggregate,
    comparison_table,
    estimate_cost,
    expected_quarantine,
    load_cases,
    provider_reference,
    read_yaml,
    reference_mapping,
    score_mapping,
)
from schema_fixer.io import InputError
from schema_fixer.mapping import Mapping
from schema_fixer.providers import ProviderError
from schema_fixer.providers.openai import OpenAIProposer


@pytest.fixture
def cases(root):
    return load_cases(root)


def usage():
    return {
        "input_tokens": 1000,
        "input_tokens_details": {
            "cached_tokens": 100,
            "cache_write_tokens": 200,
            "cache_write_tokens_details": {"ttl_30m_tokens": 150, "ttl_12h_tokens": 50},
        },
        "output_tokens": 500,
        "output_tokens_details": {"reasoning_tokens": 300},
        "total_tokens": 1500,
    }


@pytest.mark.parametrize("index", range(20))
def test_all_provider_stage_references_score_perfectly(cases, index):
    case = cases[index]
    before = copy.deepcopy(case.reference)
    score = score_mapping(case, provider_reference(case))
    assert score["case_passed"], score["failures"]
    assert score["output_match"]
    assert score["field_correct"] == score["field_total"]
    assert score["quarantine_correct"]
    assert case.reference == before


def test_case19_rewards_abstention_and_rejects_guessed_constant(cases):
    case = cases[18]
    score = score_mapping(case, provider_reference(case))
    assert score["case_passed"] and score["missing_correct"] == 1
    assert score["predicted_quarantine"] == {
        1: ["status"],
        2: ["status"],
        3: ["status"],
    }
    assert score["checks"]["passed"] is False  # eval success is not approval
    guessed = score_mapping(case, reference_mapping(case.reference))
    assert not guessed["case_passed"]
    assert not guessed["output_match"]  # a guessed constant changes the output
    assert guessed["high_confidence_wrong"] == 1
    assert any(f["field"] == "status" for f in guessed["failures"])


@pytest.mark.parametrize("index", [8, 9])
def test_rename_and_cast_to_schema_type_are_equivalent(cases, index):
    case = cases[index]
    payload = provider_reference(case).model_dump()
    for field in payload["fields"]:
        if field["target"] in {"quantity", "total"}:
            field["transform"] = (
                {"name": "rename"}
                if index == 9
                else {"name": "cast", "type": case.schema.fields[field["target"]].type}
            )
    assert score_mapping(case, Mapping.model_validate(payload))["case_passed"]
    payload["fields"][0]["transform"] = {"name": "cast", "type": "boolean"}
    assert not score_mapping(case, Mapping.model_validate(payload))["case_passed"]


def test_entry_order_and_reasons_do_not_matter_but_source_order_and_parameters_do(
    cases,
):
    case = cases[0]
    payload = provider_reference(case).model_dump()
    payload["fields"].reverse()
    for field in payload["fields"]:
        field["confidence"] = 0.1
        field["reason"] = "A different explanation"
        if field["transform"]["name"] == "map_values":
            field["transform"]["values"].reverse()
    assert score_mapping(case, Mapping.model_validate(payload))["case_passed"]
    name = next(f for f in payload["fields"] if f["target"] == "full_name")
    name["sources"].reverse()
    wrong = score_mapping(case, Mapping.model_validate(payload))
    assert wrong["field_correct"] == 3 and wrong["high_confidence_wrong"] == 0
    assert any(f["field"] == "full_name" for f in wrong["failures"])


def test_duplicate_targets_and_bad_drop_are_failures(cases):
    case = cases[0]
    payload = provider_reference(case).model_dump()
    payload["fields"].append(copy.deepcopy(payload["fields"][0]))
    score = score_mapping(case, Mapping.model_validate(payload))
    assert score["high_confidence_wrong"] == 2
    assert not score["case_passed"] and not score["quarantine_correct"]
    assert not score["output_match"]
    assert score["predicted_quarantine"] is None
    case = cases[7]
    payload = provider_reference(case).model_dump()
    payload["drop"] = []
    assert any(
        f["field"] == "(drop)"
        for f in score_mapping(case, Mapping.model_validate(payload))["failures"]
    )


def test_missing_recall_and_quarantine_count_correct_blocked_drafts(cases):
    for index in (6, 12):
        score = score_mapping(cases[index], provider_reference(cases[index]))
        assert score["missing_correct"] == score["missing_total"] == 1
        assert score["checks"]["rows_checked"] == 0
        assert score["case_passed"] and len(score["predicted_quarantine"]) == 3


def test_quarantine_compares_fields_as_well_as_row_positions(cases):
    case = copy.deepcopy(cases[0])
    case.reference["quarantine_reasons"][3] = ["plan: deliberately wrong reason target"]
    assert expected_quarantine(case) == {3: ["plan"]}
    score = score_mapping(case, provider_reference(case))
    assert score["field_correct"] == 4 and not score["quarantine_correct"]
    assert score["predicted_quarantine"] == {3: ["email"]}


def test_redundant_iso_parser_is_an_output_match_but_a_strict_mismatch(cases):
    case = cases[1]
    payload = provider_reference(case).model_dump()
    entry = next(e for e in payload["fields"] if e["target"] == "signup_date")
    entry["transform"] = {"name": "parse_date", "format": "%Y-%m-%d"}
    score = score_mapping(case, Mapping.model_validate(payload))
    assert score["field_correct"] == 3 and not score["case_passed"]
    assert score["output_match"]
    assert score["fixture_equivalent_mismatches"] == 1
    assert "Counts toward output match" in score["failures"][0]["reason"]
    entry["transform"]["format"] = "%d/%m/%Y"
    score = score_mapping(case, Mapping.model_validate(payload))
    assert score["fixture_equivalent_mismatches"] == 0
    assert not score["output_match"]


def test_identity_value_map_is_an_output_match(cases):
    case = cases[2]  # 03: tier already holds free/pro
    payload = provider_reference(case).model_dump()
    entry = next(e for e in payload["fields"] if e["target"] == "plan")
    entry["transform"] = {
        "name": "map_values",
        "values": [
            {"source": "free", "target": "free"},
            {"source": "pro", "target": "pro"},
        ],
    }
    score = score_mapping(case, Mapping.model_validate(payload))
    assert score["output_match"] and not score["case_passed"]


def test_dropping_a_column_over_one_bad_value_is_not_an_output_match(cases):
    case = cases[5]  # 06: Enterprise is unknown, FREE and Pro Monthly are fine
    payload = provider_reference(case).model_dump()
    payload["fields"] = [f for f in payload["fields"] if f["target"] != "plan"]
    payload["unmapped_optional"] = ["plan"]
    payload["drop"] = [
        {
            "sources": ["plan"],
            "transform": {"name": "drop"},
            "confidence": 0.5,
            "reason": "Unknown label",
        }
    ]
    score = score_mapping(case, Mapping.model_validate(payload))
    assert not score["output_match"] and not score["quarantine_correct"]


def test_comparison_table_leads_with_output_match(cases):
    records = [
        {
            "provider": "baseline",
            "case": case.id,
            "score": score_mapping(case, provider_reference(case)),
        }
        for case in cases[:2]
    ]
    assert aggregate(records)["output_match"] == 2
    header = comparison_table(records).splitlines()[0]
    assert header.startswith("| Provider | Output match | Strict pass |")


def test_errors_stay_in_denominators_and_zero_confidence_denominator_is_na(cases):
    good = {
        "score": score_mapping(cases[0], provider_reference(cases[0])),
        "provider": "openai",
        "latency_seconds": 1.0,
        "cost_usd": 0.002,
        "error": None,
    }
    bad = {
        "score": score_mapping(cases[0], None),
        "provider": "openai",
        "latency_seconds": 5.0,
        "cost_usd": None,
        "error": "failed",
    }
    result = aggregate([good, bad])
    assert result["field_correct"] == 4 and result["field_total"] == 8
    assert result["errors"] == 1 and result["p50_seconds"] == 3.0
    assert result["cost_unknown_cases"] == 1 and result["cost_known_usd"] == 0.002
    assert "unknown" in comparison_table([good, bad])
    assert "N/A (0 denominator)" in comparison_table([bad])


def test_cost_accounts_for_cache_reads_writes_and_reasoning_once(root):
    pricing = read_yaml(root / "eval/pricing.yaml")
    assert estimate_cost(usage(), "gpt-6-luna", "default", pricing) == pytest.approx(
        0.00035225
    )
    unknown = usage()
    del unknown["input_tokens_details"]["cached_tokens"]
    assert estimate_cost(unknown, "gpt-6-luna", "default", pricing) is None
    assert estimate_cost(None, "gpt-6-luna", "default", pricing) is None
    assert estimate_cost(usage(), "unpriced", "default", pricing) is None
    assert estimate_cost(usage(), "gpt-6-luna", "priority", pricing) is None
    invalid = usage()
    invalid["input_tokens"] = 100
    assert estimate_cost(invalid, "gpt-6-luna", "default", pricing) is None


def test_provider_records_usage_even_for_refusal_and_resets_between_calls(cases):
    calls = []
    responses = [
        SimpleNamespace(
            status="completed",
            model="gpt-6-luna",
            service_tier="default",
            usage=SimpleNamespace(model_dump=lambda **kwargs: usage()),
            output=[
                SimpleNamespace(
                    type="message", content=[SimpleNamespace(type="refusal")]
                )
            ],
            output_parsed=None,
        ),
        SimpleNamespace(
            status="completed", output=[], output_parsed=provider_reference(cases[0])
        ),
    ]

    def parse(**kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    proposer = OpenAIProposer(
        Settings(), client=SimpleNamespace(responses=SimpleNamespace(parse=parse))
    )
    with pytest.raises(ProviderError):
        proposer.propose(cases[0].schema, [])
    assert proposer.last_usage == usage() and proposer.last_service_tier == "default"
    proposer.propose(cases[0].schema, [])
    assert proposer.last_usage is None
    assert len(calls) == 2 and calls[0]["service_tier"] == "default"


def fake_run(monkeypatch, cases, *, fail_first=False):
    calls = []
    monkeypatch.setattr(
        eval_runner,
        "load_settings",
        lambda provider: Settings(provider=provider, api_key="private-fake-key"),
    )

    def factory(settings):
        index = sum(provider == settings.provider for provider in calls)
        case = cases[index]

        def propose(schema, columns):
            calls.append(settings.provider)
            assert schema == case.schema
            assert all(type(c).__name__ == "ColumnProfile" for c in columns)
            payload = json.dumps([c.model_dump() for c in columns])
            assert "ada@example.com" not in payload
            assert "review_status" not in payload and "expected_mapping" not in payload
            if fail_first and index == 0:
                raise ProviderError("private-fake-key raw provider error")
            return provider_reference(case)

        return SimpleNamespace(
            propose=propose,
            last_usage=usage(),
            last_response_model="gpt-6-luna",
            last_service_tier="default",
        )

    return factory, calls


def test_runner_calls_each_provider_once_and_replay_never_calls_any(
    root, cases, tmp_path, monkeypatch
):
    factory, calls = fake_run(monkeypatch, cases)
    run = tmp_path / "run"
    report = tmp_path / "results.md"
    records = eval_runner.run_evaluation(
        root, ["baseline", "openai"], run, report, factory=factory
    )
    assert calls.count("baseline") == calls.count("openai") == 20
    assert len(list(run.glob("*.json"))) == 41
    assert all(r["score"]["case_passed"] for r in records)
    assert "private-fake-key" not in "".join(p.read_text() for p in run.glob("*.json"))
    with pytest.raises(InputError, match="already exists"):
        eval_runner.run_evaluation(root, ["openai"], run, report, factory=factory)
    assert len(calls) == 40

    def forbidden(*args, **kwargs):
        pytest.fail("Report-only must not load credentials or create a provider")

    monkeypatch.setattr(eval_runner, "load_settings", forbidden)
    monkeypatch.setattr(eval_runner, "create_proposer", forbidden)
    original = report.read_text()
    eval_runner.replay_report(root, run, report)
    assert report.read_text() == original
    (run / f"openai-{cases[0].id}.json").unlink()
    partial = eval_runner.replay_report(root, run, report)
    assert sum(bool(r.get("error")) for r in partial) == 1


def test_runner_retains_failed_attempt_without_retry_or_secret_error(
    root, cases, tmp_path, monkeypatch
):
    factory, calls = fake_run(monkeypatch, cases, fail_first=True)
    records = eval_runner.run_evaluation(
        root, ["openai"], tmp_path / "run", tmp_path / "report.md", factory=factory
    )
    assert len(calls) == 20 and records[0]["error"]
    assert records[0]["score"]["field_correct"] == 0
    assert "private-fake-key" not in (tmp_path / "report.md").read_text()


def test_approval_gate_checks_all_cases_before_any_provider(root, tmp_path):
    project = tmp_path / "project"
    shutil.copytree(root / "eval/cases", project / "eval/cases")
    path = next((project / "eval/cases").glob("*/case.yaml"))
    meta = yaml.safe_load(path.read_text())
    meta["review_status"] = "pending"
    path.write_text(yaml.safe_dump(meta))
    with pytest.raises(InputError, match="approved by Glenn"):
        eval_runner.run_evaluation(
            project,
            ["openai"],
            project / "run",
            project / "results.md",
            factory=lambda *_: pytest.fail("Provider must not be created"),
        )
    assert not (project / "run").exists()


def test_report_only_rejects_dataset_mismatch(root, cases, tmp_path, monkeypatch):
    factory, _ = fake_run(monkeypatch, cases)
    run = tmp_path / "run"
    report = tmp_path / "results.md"
    eval_runner.run_evaluation(root, ["baseline"], run, report, factory=factory)
    manifest = json.loads((run / "manifest.json").read_text())
    manifest["dataset_sha256"] = "changed"
    (run / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(InputError, match="dataset changed"):
        eval_runner.replay_report(root, run, report)


def test_cli_defaults_to_baseline_and_report_only_requires_saved_run(
    root, tmp_path, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        eval_runner,
        "run_evaluation",
        lambda root, providers, *args: calls.append(providers) or [],
    )
    assert eval_runner.main(root, ["--output", str(tmp_path / "report.md")]) == 0
    assert calls == [["baseline"]]
    assert eval_runner.main(root, ["--report-only"]) == 2

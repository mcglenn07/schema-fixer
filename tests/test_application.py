"""Approval gates, persisted bindings, typed outputs and full-file quarantine."""

import csv
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from typer.testing import CliRunner

from schema_fixer import cli
from schema_fixer.application import apply_file
from schema_fixer.approval import edit_yaml, fingerprint, load_approved
from schema_fixer.io import InputError

runner = CliRunner()


def source(tmp_path, fields=None, rows=None, suffix=".json"):
    fields = fields or {
        "email": {"type": "string", "format": "email", "required": True}
    }
    rows = rows if rows is not None else [{"email": "ada@example.com"}]
    schema = tmp_path / "schema.yaml"
    schema.write_text(
        yaml.safe_dump({"name": "test", "fields": fields}, sort_keys=False)
    )
    data = tmp_path / f"input{suffix}"
    if suffix == ".json":
        data.write_text(json.dumps(rows))
    else:
        with data.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return data, schema


def approve(data, schema, destination, *, input="accept\n", extra=()):
    return runner.invoke(
        cli.app,
        [
            "approve",
            str(data),
            "--schema",
            str(schema),
            "--provider",
            "baseline",
            "--output",
            str(destination),
            *extra,
        ],
        input=input,
    )


def approved(tmp_path, fields=None, rows=None, suffix=".json"):
    data, schema = source(tmp_path, fields, rows, suffix)
    mapping = tmp_path / "mappings" / "source.yaml"
    result = approve(data, schema, mapping)
    assert result.exit_code == 0, result.output
    return data, schema, mapping


def quarantine(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


@pytest.mark.parametrize("suffix", [".csv", ".json"])
def test_schema_typed_json_output_without_casts(tmp_path, suffix):
    fields = {
        "id": {"type": "string"},
        "quantity": {"type": "integer"},
        "total": {"type": "number"},
        "joined date": {"type": "date"},
        "active": {"type": "boolean"},
        "optional": {"type": "integer"},
    }
    rows = [
        {
            "id": "0003",
            "quantity": "3",
            "total": "19.99",
            "joined date": "2026-11-06",
            "active": "true",
            "optional": "",
        }
    ]
    data, _, mapping = approved(tmp_path, fields, rows, suffix)
    saved, _, _ = load_approved(mapping)
    assert all(e.transform.name == "rename" for e in saved.mapping.fields)
    path = tmp_path / "out" / "clean.json"
    report = apply_file(data, mapping, path)
    row = json.loads(path.read_text())[0]
    assert row == {
        "id": "0003",
        "quantity": 3,
        "total": 19.99,
        "joined date": "2026-11-06",
        "active": True,
        "optional": None,
    }
    assert type(row["quantity"]) is int and type(row["total"]) is float
    assert report.checks.rows_checked == report.checks.valid_rows == 1
    assert quarantine(path.parent / "quarantine.csv") == []


def test_csv_serializes_validated_numbers_and_preserves_string_ids(tmp_path):
    fields = {
        "id": {"type": "string"},
        "quantity": {"type": "integer"},
        "total": {"type": "number"},
    }
    data, _, mapping = approved(
        tmp_path, fields, [{"id": "0003", "quantity": "003", "total": "19.990"}], ".csv"
    )
    path = tmp_path / "out" / "clean.csv"
    apply_file(data, mapping, path)
    assert quarantine(path) == [{"id": "0003", "quantity": "3", "total": "19.99"}]


def test_case18_real_cli_approval_apply_and_safe_reports(root, tmp_path):
    data = root / "eval/cases/18_ticket_nulls_and_formats/incoming.json"
    schema = root / "schemas/support_ticket.yaml"
    mapping = tmp_path / "mappings" / "ticket.yaml"
    result = approve(data, schema, mapping)
    assert result.exit_code == 0, result.output
    assert "Check" in result.output and "result" in result.output
    assert "WARNING" in result.output
    saved, _, bound_path = load_approved(mapping)
    assert saved.status == "approved" and bound_path == schema
    assert not Path(saved.schema_path).is_absolute()
    output = tmp_path / "out" / "clean.json"
    result = runner.invoke(
        cli.app,
        [
            "apply",
            str(data),
            "--mapping",
            str(mapping),
            "--output",
            str(output),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["checks"]["rows_checked"] == 3
    assert report["checks"]["quarantine_rows"] == [2, 3]
    assert "invalid-email" not in result.output
    assert "would be quarantined" not in result.output
    assert "was quarantined" in result.output
    originals = json.loads(data.read_text())
    assert json.loads(output.read_text()) == originals[:1]
    bad = quarantine(output.parent / "quarantine.csv")
    assert [r["data_row"] for r in bad] == ["2", "3"]
    assert [json.loads(r["original_row"]) for r in bad] == originals[1:]
    # Plain-English reasons, one per field, with no raw values or codes.
    assert bad[0]["reason"] == (
        "requester_email: not a valid email address; subject: required value is blank"
    )
    assert bad[1]["reason"] == (
        "priority: required value is blank; "
        "phone: not a valid phone number (+ and 7-15 digits)"
    )
    assert "invalid-email" not in bad[0]["reason"]
    assert all("row_invalid" not in row["reason"] for row in bad)


def test_apply_never_creates_provider_or_loads_key_and_can_reuse_mapping(
    tmp_path, monkeypatch
):
    data, _, mapping = approved(tmp_path)
    import schema_fixer.providers.openai as provider
    from schema_fixer import proposals

    def forbidden(*args, **kwargs):
        pytest.fail("Apply must not consult a provider or load API settings")

    monkeypatch.setattr(proposals, "create_proposer", forbidden)
    monkeypatch.setattr(proposals, "load_settings", forbidden)
    monkeypatch.setattr(provider, "OpenAI", forbidden)
    monkeypatch.setenv("OPENAI_API_KEY", "private-test-key-never-used")
    first = tmp_path / "first" / "clean.json"
    second = tmp_path / "second" / "clean.json"
    for path in (first, second):
        result = runner.invoke(
            cli.app,
            ["apply", str(data), "--mapping", str(mapping), "--output", str(path)],
        )
        assert result.exit_code == 0, result.output
        assert "private-test-key" not in result.output
    assert first.read_bytes() == second.read_bytes()
    assert (first.parent / "quarantine.csv").read_bytes() == (
        second.parent / "quarantine.csv"
    ).read_bytes()


@pytest.mark.parametrize("change", ["type", "required", "format", "name"])
def test_changed_schema_refuses_apply_before_writing(tmp_path, change):
    data, schema, mapping = approved(tmp_path)
    payload = yaml.safe_load(schema.read_text())
    if change == "name":
        payload["name"] = "different"
    else:
        payload["fields"]["email"] = (
            {"type": "integer"}
            if change == "type"
            else {"type": "string", "required": False}
            if change == "required"
            else {"type": "string", "format": "phone"}
        )
    schema.write_text(yaml.safe_dump(payload))
    output = tmp_path / "out" / "clean.json"
    result = runner.invoke(
        cli.app,
        ["apply", str(data), "--mapping", str(mapping), "--output", str(output)],
    )
    assert result.exit_code == 2 and "schema changed" in result.output
    assert not output.parent.exists()


def test_schema_comments_and_column_order_do_not_break_binding(tmp_path):
    fields = {
        "email": {"type": "string", "format": "email"},
        "name": {"type": "string"},
    }
    data, schema, mapping = approved(
        tmp_path, fields, [{"email": "ada@example.com", "name": "Ada"}]
    )
    schema.write_text("# formatting only\n" + schema.read_text())
    data.write_text('[{"name": "Ada", "email": "ada@example.com"}]')
    output = tmp_path / "out" / "clean.json"
    assert apply_file(data, mapping, output).checks.passed


@pytest.mark.parametrize(
    "row", [{"other": "ada@example.com"}, {"email": "ada@example.com", "extra": "x"}]
)
def test_source_column_mismatch_refuses_apply(tmp_path, row):
    data, _, mapping = approved(tmp_path)
    data.write_text(json.dumps([row]))
    with pytest.raises(InputError, match="Source columns differ"):
        apply_file(data, mapping, tmp_path / "out" / "clean.json")
    assert not (tmp_path / "out").exists()


def test_missing_dropped_source_is_also_a_binding_mismatch(tmp_path):
    data, _, mapping = approved(
        tmp_path, rows=[{"email": "ada@example.com", "unused": "x"}]
    )
    data.write_text('[{"email":"ada@example.com"}]')
    with pytest.raises(InputError, match="Source columns differ"):
        apply_file(data, mapping)


def test_modified_approval_or_raw_draft_cannot_be_applied(tmp_path):
    data, _, mapping = approved(tmp_path)
    payload = yaml.safe_load(mapping.read_text())
    payload["mapping"]["fields"][0]["reason"] = "Edited after approval"
    mapping.write_text(yaml.safe_dump(payload))
    with pytest.raises(InputError, match="modified approved mapping"):
        apply_file(data, mapping)
    mapping.write_text(yaml.safe_dump(payload["mapping"]))
    with pytest.raises(InputError, match="modified approved mapping"):
        apply_file(data, mapping)


def test_apply_reruns_structure_even_on_self_consistent_approval(tmp_path):
    data, _, mapping = approved(tmp_path)
    payload = yaml.safe_load(mapping.read_text())
    payload["mapping"]["fields"][0]["sources"] = ["missing"]
    payload.pop("approval_sha256")
    payload["approval_sha256"] = fingerprint(payload)
    mapping.write_text(yaml.safe_dump(payload))
    result = runner.invoke(
        cli.app,
        [
            "apply",
            str(data),
            "--mapping",
            str(mapping),
            "--output",
            str(tmp_path / "out" / "clean.json"),
        ],
    )
    assert result.exit_code == 1 and "missing_source" in result.output
    assert not (tmp_path / "out").exists()


def test_full_file_validation_catches_rows_beyond_sample_limit(tmp_path):
    rows = [{"email": "ada@example.com"}] * 110 + [{"email": "private-bad-value"}]
    data, _, mapping = approved(tmp_path, rows=rows)
    output = tmp_path / "out" / "clean.json"
    report = apply_file(data, mapping, output)
    assert report.checks.rows_checked == 111 and report.checks.valid_rows == 110
    assert report.checks.quarantine_rows == [111]
    assert len(json.loads(output.read_text())) == 110
    assert quarantine(output.parent / "quarantine.csv")[0]["data_row"] == "111"
    assert "private-bad-value" not in report.model_dump_json()


def test_full_file_guard_uses_all_rows_and_refuses_systematic_failure(tmp_path):
    data, _, mapping = approved(tmp_path)
    data.write_text(
        json.dumps([{"email": "bad"}] * 100 + [{"email": "ada@example.com"}])
    )
    report = apply_file(data, mapping, tmp_path / "out" / "clean.json")
    assert report.checks.valid_rows == 1 and len(report.checks.quarantine_rows) == 100
    data.write_text('[{"email":"private-bad-one"},{"email":"private-bad-two"}]')
    result = runner.invoke(
        cli.app,
        [
            "apply",
            str(data),
            "--mapping",
            str(mapping),
            "--output",
            str(tmp_path / "blocked" / "clean.json"),
            "--json",
        ],
    )
    assert result.exit_code == 1 and "all_rows_failed_field" in result.output
    assert "private-bad" not in result.output
    assert not (tmp_path / "blocked").exists()


@pytest.mark.parametrize("kind", ["structure", "parameters", "syntax"])
def test_bad_edit_cannot_save_or_fall_back_to_pre_edit_mapping(
    tmp_path, monkeypatch, kind
):
    data, schema = source(tmp_path)
    destination = tmp_path / "mapping.yaml"

    def bad_edit(text):
        payload = yaml.safe_load(text)
        if kind == "structure":
            payload["fields"][0]["sources"] = ["missing"]
        elif kind == "parameters":
            payload["fields"][0]["transform"] = {
                "name": "execute",
                "code": "private-invalid-value",
            }
        else:
            return 'fields: ["private-invalid-value"'
        return yaml.safe_dump(payload)

    monkeypatch.setattr(cli, "edit_yaml", bad_edit)
    result = approve(data, schema, destination, input="edit\naccept\ncancel\n")
    assert result.exit_code == 1 and "Cannot accept" in result.output
    assert "private-invalid-value" not in result.output
    assert not destination.exists()


def test_valid_edit_is_rechecked_displayed_and_saved(tmp_path, monkeypatch):
    data, schema = source(
        tmp_path,
        {"date": {"type": "date"}},
        [{"date": "11/06/26"}, {"date": "10/15/26"}],
    )
    destination = tmp_path / "mapping.yaml"

    def fix_date(text):
        payload = yaml.safe_load(text)
        payload["fields"][0]["transform"] = {"name": "parse_date", "format": "%m/%d/%y"}
        payload["fields"][0]["reason"] = "10/15/26 establishes month-first dates."
        return yaml.safe_dump(payload)

    monkeypatch.setattr(cli, "edit_yaml", fix_date)
    result = approve(data, schema, destination, input="accept\nedit\naccept\n")
    assert result.exit_code == 0, result.output
    assert "Cannot accept" in result.output and "PASSED" in result.output
    saved, _, _ = load_approved(destination)
    assert saved.mapping.fields[0].transform.format == "%m/%d/%y"
    path = tmp_path / "out" / "clean.json"
    apply_file(data, destination, path)
    assert json.loads(path.read_text()) == [
        {"date": "2026-11-06"},
        {"date": "2026-10-15"},
    ]


@pytest.mark.parametrize("input", ["\n", "cancel\n", ""])
def test_cancel_default_and_eof_never_save(tmp_path, input):
    data, schema = source(tmp_path)
    path = tmp_path / "mapping.yaml"
    result = approve(data, schema, path, input=input)
    assert result.exit_code != 0
    assert not path.exists()


@pytest.mark.parametrize("changed", ["data", "schema"])
def test_inputs_changed_in_editor_require_new_review(tmp_path, monkeypatch, changed):
    data, schema = source(tmp_path)
    path = tmp_path / "mapping.yaml"

    def edit(text):
        if changed == "data":
            data.write_text('[{"email":"ben@example.com"}]')
        else:
            payload = yaml.safe_load(schema.read_text())
            payload["name"] = "changed"
            schema.write_text(yaml.safe_dump(payload))
        return text

    monkeypatch.setattr(cli, "edit_yaml", edit)
    result = approve(data, schema, path, input="edit\naccept\n")
    assert result.exit_code == 2 and "changed during review" in result.output
    assert not path.exists()


def test_offline_draft_review_does_not_invoke_provider(tmp_path, monkeypatch):
    data, schema, original = approved(tmp_path)
    draft = tmp_path / "draft.yaml"
    draft.write_text(original.read_text())

    def forbidden(*args, **kwargs):
        pytest.fail("Draft review must not invoke a provider")

    monkeypatch.setattr(cli, "propose_file", forbidden)
    path = tmp_path / "new.yaml"
    args = [
        "approve",
        str(data),
        "--schema",
        str(schema),
        "--draft",
        str(draft),
        "--output",
        str(path),
    ]
    assert runner.invoke(cli.app, args, input="accept\n").exit_code == 0
    assert load_approved(path)[0].mapping == load_approved(original)[0].mapping
    result = runner.invoke(cli.app, [*args, "--provider", "baseline"])
    assert result.exit_code == 2 and "either --draft or --provider" in result.output


def test_output_collisions_do_not_overwrite_or_leave_partial_files(tmp_path):
    data, schema, mapping = approved(tmp_path)
    before = mapping.read_bytes()
    result = approve(data, schema, mapping)
    assert result.exit_code == 2 and mapping.read_bytes() == before
    output = tmp_path / "out" / "clean.json"
    output.parent.mkdir()
    bad = output.parent / "quarantine.csv"
    bad.write_text("keep existing quarantine")
    with pytest.raises(InputError, match="already exists"):
        apply_file(data, mapping, output)
    assert bad.read_text() == "keep existing quarantine" and not output.exists()
    with pytest.raises(InputError, match="distinct"):
        apply_file(data, mapping, data)
    with pytest.raises(InputError, match="distinct"):
        apply_file(data, mapping, bad)


def test_failed_publication_cleans_only_new_files(tmp_path, monkeypatch):
    data, _, mapping = approved(tmp_path)
    import schema_fixer.output as output_module

    link = output_module.os.link
    calls = []

    def fail_second(src, dst):
        calls.append(dst)
        if len(calls) == 2:
            raise OSError("private OS details")
        link(src, dst)

    monkeypatch.setattr(output_module.os, "link", fail_second)
    path = tmp_path / "out" / "clean.json"
    with pytest.raises(InputError, match="Cannot write output files"):
        apply_file(data, mapping, path)
    assert list(path.parent.iterdir()) == []


def test_quarantine_original_headers_cannot_overwrite_metadata(tmp_path):
    fields = {
        "data_row": {"type": "string"},
        "reason": {"type": "string"},
        "email": {"type": "string", "format": "email"},
    }
    rows = [
        {"data_row": "original-1", "reason": "ok", "email": "ada@example.com"},
        {
            "data_row": "original-2",
            "reason": "private-source-reason",
            "email": "private-bad-email",
        },
    ]
    data, _, mapping = approved(tmp_path, fields, rows)
    path = tmp_path / "out" / "clean.json"
    report = apply_file(data, mapping, path)
    bad = quarantine(path.parent / "quarantine.csv")[0]
    assert bad["data_row"] == "2" and "email: not a valid email" in bad["reason"]
    assert json.loads(bad["original_row"]) == rows[1]
    assert "private-" not in report.model_dump_json()


def test_editor_uses_argv_and_cleans_temporary_yaml(tmp_path, monkeypatch):
    from schema_fixer import approval

    monkeypatch.setenv("VISUAL", '"/path with spaces/editor" --wait')
    seen = []

    def run(argv, **kwargs):
        assert argv[:2] == ["/path with spaces/editor", "--wait"]
        path = Path(argv[2])
        assert path.read_text() == "before"
        path.write_text("after")
        seen.append(path)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(approval.subprocess, "run", run)
    assert edit_yaml("before") == "after"
    assert not seen[0].exists()


def test_mapping_and_schema_can_move_together(tmp_path, monkeypatch):
    original = tmp_path / "original"
    original.mkdir()
    data, _, mapping = approved(original)
    moved = tmp_path / "moved"
    shutil.copytree(original, moved)
    shutil.rmtree(original)
    monkeypatch.chdir(tmp_path)
    report = apply_file(
        moved / data.name,
        moved / "mappings" / mapping.name,
        moved / "out" / "clean.json",
    )
    assert report.checks.passed


def test_all_dirty_rows_on_different_fields_write_empty_clean_file(tmp_path):
    fields = {"email": {"type": "string", "format": "email"}, "date": {"type": "date"}}
    rows = [
        {"email": "bad", "date": "2026-11-06"},
        {"email": "ada@example.com", "date": "bad"},
    ]
    data, _, mapping = approved(tmp_path, fields, rows)
    path = tmp_path / "out" / "clean.json"
    report = apply_file(data, mapping, path)
    assert report.checks.passed and report.checks.quarantine_rows == [1, 2]
    assert json.loads(path.read_text()) == []
    assert len(quarantine(path.parent / "quarantine.csv")) == 2


def test_empty_input_cannot_be_applied(tmp_path):
    data, _, mapping = approved(tmp_path, suffix=".csv")
    data.write_text("email\n")
    result = runner.invoke(
        cli.app,
        [
            "apply",
            str(data),
            "--mapping",
            str(mapping),
            "--output",
            str(tmp_path / "out" / "clean.csv"),
        ],
    )
    assert result.exit_code == 1 and "no_sample" in result.output
    assert not (tmp_path / "out").exists()


def test_default_mapping_and_output_locations(tmp_path, monkeypatch):
    data, schema = source(tmp_path, suffix=".csv")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        cli.app,
        ["approve", str(data), "--schema", str(schema), "--provider", "baseline"],
        input="accept\n",
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        cli.app, ["apply", str(data), "--mapping", "mappings/input.yaml"]
    )
    assert result.exit_code == 0, result.output
    assert Path("outputs/input/clean.csv").exists()
    assert Path("outputs/input/quarantine.csv").exists()


def test_case01_offline_draft_approval_and_saved_apply(root, tmp_path):
    data = root / "eval/cases/01_customer_spec_example/incoming.csv"
    mapping = tmp_path / "case01.yaml"
    result = runner.invoke(
        cli.app,
        [
            "approve",
            str(data),
            "--schema",
            str(root / "schemas/customer.yaml"),
            "--draft",
            str(root / "examples/case01-draft.yaml"),
            "--output",
            str(mapping),
        ],
        input="accept\n",
    )
    assert result.exit_code == 0, result.output
    path = tmp_path / "out" / "clean.csv"
    report = apply_file(data, mapping, path)
    assert quarantine(path) == [
        {
            "email": "ada@example.com",
            "full_name": "Ada Reyes",
            "plan": "pro",
            "signup_date": "2026-11-06",
        },
        {
            "email": "ben@example.com",
            "full_name": "Ben Cruz",
            "plan": "free",
            "signup_date": "2026-10-15",
        },
    ]
    bad = quarantine(path.parent / "quarantine.csv")
    assert len(bad) == 1 and bad[0]["data_row"] == "3"
    assert bad[0]["reason"] == "email: not a valid email address"
    assert json.loads(bad[0]["original_row"])["Email Address"] == "not-an-email"
    assert "not-an-email" not in report.model_dump_json()

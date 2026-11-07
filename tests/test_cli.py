import json

from typer.testing import CliRunner

from schema_fixer.cli import app

runner = CliRunner()


def test_m3_commands_are_exposed_without_later_milestones():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "inspect" in result.output
    assert "propose" in result.output
    assert "approve" in result.output
    assert "apply" in result.output
    assert "eval" not in result.output


def test_real_example_text_and_json_and_exit_status(root):
    path = root / "eval/cases/01_customer_spec_example/incoming.csv"
    original = path.read_bytes()
    args = ["inspect", str(path), "--schema", str(root / "schemas/customer.yaml")]
    text = runner.invoke(app, args)
    assert text.exit_code == 0, text.output
    assert "Inspection only" in text.output
    assert "[EMAIL]" in text.output
    assert "ada@example.com" not in text.output
    result = runner.invoke(app, [*args, "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["profile"]["row_count"] == 3
    assert payload["findings"]
    optional = {
        f["field"] for f in payload["findings"] if f["code"] == "missing_optional"
    }
    assert optional == {"plan", "signup_date"}
    assert "missing_optional" in text.output
    assert runner.invoke(app, [*args, "--fail-on-mismatch"]).exit_code == 1
    assert path.read_bytes() == original


def test_valid_input_has_success_status(root, tmp_path):
    path = tmp_path / "valid.csv"
    path.write_text("email,full_name\nada@example.com,Ada Reyes\n")
    result = runner.invoke(
        app,
        [
            "inspect",
            str(path),
            "--schema",
            str(root / "schemas/customer.yaml"),
            "--fail-on-mismatch",
        ],
    )
    assert result.exit_code == 0
    assert "missing_optional" in result.output
    assert "No blocking mismatches" in result.output


def test_complete_input_reports_no_mismatches(root, tmp_path):
    path = tmp_path / "complete.csv"
    path.write_text(
        "email,full_name,plan,signup_date\nada@example.com,Ada Reyes,pro,2026-11-06\n"
    )
    result = runner.invoke(
        app,
        [
            "inspect",
            str(path),
            "--schema",
            str(root / "schemas/customer.yaml"),
            "--fail-on-mismatch",
        ],
    )
    assert result.exit_code == 0
    assert "No mismatches detected" in result.output


def test_bad_input_is_a_friendly_error(root, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('[{"private":"ada@example.com"')
    result = runner.invoke(
        app, ["inspect", str(path), "--schema", str(root / "schemas/customer.yaml")]
    )
    assert result.exit_code == 2
    assert "Error:" in result.output
    assert "Traceback" not in result.output
    assert "ada@example.com" not in result.output


def test_missing_file_is_a_friendly_error(root):
    result = runner.invoke(
        app,
        ["inspect", "nonexistent.csv", "--schema", str(root / "schemas/customer.yaml")],
    )
    assert result.exit_code == 2
    assert "Cannot read" in result.output

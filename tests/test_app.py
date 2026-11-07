"""Exercise the actual app wiring and callbacks without starting a socket."""

import csv
import json
import runpy
import shutil
from pathlib import Path

import pytest

from schema_fixer import demo as workflow_module
from schema_fixer.approval import ChecksFailed, load_approved
from schema_fixer.demo import DemoSession, DemoWorkflow, cleanup_session
from schema_fixer.io import InputError


@pytest.fixture
def ui(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("PROVIDER", "openai")
    from schema_fixer import demo_ui

    return demo_ui


@pytest.fixture
def session():
    value = DemoSession()
    yield value
    cleanup_session(value)


@pytest.fixture
def callbacks(root, ui):
    return ui.DemoCallbacks(DemoWorkflow(root))


def prepare(callbacks, session, index=2):
    file, schema = callbacks.workflow.sample(index)
    stages = list(callbacks.inspect(file, schema, "baseline", session))
    return file, schema, stages


def test_app_entry_builds_real_controls_without_provider_or_server(
    root, ui, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("Constructing the page must not propose or launch.")

    monkeypatch.setattr(workflow_module, "propose_file", forbidden)
    monkeypatch.setattr(ui, "launch_demo", forbidden)
    namespace = runpy.run_path(str(root / "app.py"))
    app = namespace["demo"]
    assert not app.analytics_enabled
    components = app.config["components"]
    providers = next(
        c["props"] for c in components if c["props"].get("label") == "Provider"
    )
    assert providers["value"] == "baseline"
    assert providers["choices"] == [("baseline", "baseline")]
    approve = next(
        c["props"] for c in components if c["props"].get("value") == "Approve & apply"
    )
    assert approve["interactive"] is False
    downloads = [c for c in components if c["type"] == "downloadbutton"]
    assert len(downloads) == 2
    assert all(
        not c["props"]["interactive"] and c["props"].get("value") is None
        for c in downloads
    )
    assert sum(c["type"] == "state" for c in components) == 1
    assert (
        sum(getattr(f.fn, "__name__", None) == "reset" for f in app.fns.values()) == 3
    )
    assert any(getattr(f.fn, "__name__", None) == "approve" for f in app.fns.values())
    assert any(getattr(f.fn, "__name__", None) == "inspect" for f in app.fns.values())


def test_main_launches_built_app_only(root, ui, monkeypatch):
    launched = []
    monkeypatch.setattr(ui, "launch_demo", launched.append)
    namespace = runpy.run_path(str(root / "app.py"), run_name="__main__")
    assert launched == [namespace["demo"]]


def test_launch_is_loopback_no_share_or_telemetry(ui):
    class FakeApp:
        def launch(self, **kwargs):
            return kwargs

    options = ui.launch_demo(FakeApp())
    assert options["server_name"] == "127.0.0.1"
    assert options["share"] is False
    assert options["show_error"] is False
    assert options["enable_monitoring"] is False
    assert options["max_file_size"] == 10 * 1024 * 1024


def test_optional_openai_only_when_configured(ui, monkeypatch, tmp_path):
    assert workflow_module.available_providers() == ["baseline"]
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
    assert workflow_module.available_providers() == ["baseline", "openai"]
    page = ui.build_demo()
    props = next(
        c["props"]
        for c in page.config["components"]
        if c["props"].get("label") == "Provider"
    )
    assert props["value"] == "baseline"
    assert "test-not-a-real-key" not in json.dumps(page.config, default=str)
    monkeypatch.delenv("OPENAI_API_KEY")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=test-local-only\n")
    assert workflow_module.available_providers() == ["baseline", "openai"]
    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert workflow_module.available_providers() == ["baseline"]


@pytest.mark.parametrize(
    "index, clean_count, bad_rows", [(0, 3, []), (1, 3, []), (2, 1, [2, 3])]
)
def test_samples_inspect_review_approve_and_download(
    callbacks, session, monkeypatch, index, clean_count, bad_rows
):
    file, schema, stages = prepare(callbacks, session, index)
    assert len(stages) == 3  # Cleared, inspected, then proposed.
    assert stages[0][5]["interactive"] is False
    assert "Inspected 3 rows" in stages[1][1]
    assert stages[1][3] == []
    assert stages[-1][3]  # Mapping table with confidence/reason/check result.
    assert all(len(row) == 6 for row in stages[-1][3])
    assert stages[-1][5]["interactive"] is True
    review = session.review
    assert not (review.directory / "approved.yaml").exists()
    assert not (review.directory / "clean.csv").exists()

    def no_proposal(*args, **kwargs):
        pytest.fail("Approval and application must not call a provider.")

    monkeypatch.setattr(workflow_module, "propose_file", no_proposal)
    result = callbacks.approve(file, schema, "baseline", session)
    assert "**Applied.**" in result[1]
    assert result[5]["interactive"] is False
    assert session.review is None
    clean = Path(result[6]["value"])
    quarantine = Path(result[7]["value"])
    assert clean.name == "clean.csv" and quarantine.name == "quarantine.csv"
    rows = list(csv.DictReader(clean.read_text().splitlines()))
    assert len(rows) == clean_count
    dirty = list(csv.DictReader(quarantine.read_text().splitlines()))
    assert [int(row["data_row"]) for row in dirty] == bad_rows
    if dirty:
        assert all("quarantined" not in row["reason"] for row in dirty)
        assert "invalid-email" in dirty[0]["original_row"]
        assert "invalid-email" not in str(stages) + str(result)
        assert "requester_email" in dirty[0]["reason"]
        assert "priority" in dirty[1]["reason"]
    if index == 1:
        assert rows[0]["quantity"] == "2"
        assert rows[0]["total"] == "39.5"
        assert rows[0]["order_date"] == "2026-11-06"
    approved, _, _ = load_approved(review.directory / "approved.yaml")
    assert approved.status == "approved"
    assert (
        "Could not continue" in callbacks.approve(file, schema, "baseline", session)[1]
    )


def test_flagged_draft_cannot_be_approved(root, callbacks, session):
    file = str(root / "eval/cases/01_customer_spec_example/incoming.csv")
    result = list(callbacks.inspect(file, "Customers", "baseline", session))[-1]
    assert "Flagged" in result[1]
    assert result[5]["interactive"] is False
    directory = session.review.directory
    refused = callbacks.approve(file, "Customers", "baseline", session)
    assert "Blocked" in refused[1]
    assert not (directory / "approved.yaml").exists()
    assert refused[6]["value"] is None


@pytest.mark.parametrize("change", ["file", "schema", "provider", "contents"])
def test_changed_inputs_cannot_apply_stale_review(callbacks, session, tmp_path, change):
    original, schema = callbacks.workflow.sample(2)
    path = tmp_path / "incoming.json"
    shutil.copyfile(original, path)
    file, provider = str(path), "baseline"
    list(callbacks.inspect(file, schema, provider, session))
    directory = session.review.directory
    if change == "file":
        file = original
    elif change == "schema":
        schema = "Customers"
    elif change == "provider":
        provider = "openai"
    else:
        path.write_text(path.read_text().replace("Cannot log in", "Changed subject"))
    result = callbacks.approve(file, schema, provider, session)
    assert "Inputs changed" in result[1]
    assert not (directory / "approved.yaml").exists()
    assert result[6]["value"] is None


def test_schema_change_cannot_apply_stale_review(root, ui, session, tmp_path):
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    callbacks = ui.DemoCallbacks(DemoWorkflow(tmp_path))
    file = str(root / "examples/demo/customers.csv")
    list(callbacks.inspect(file, "Customers", "baseline", session))
    path = tmp_path / "schemas/customer.yaml"
    path.write_text(path.read_text().replace("name: customer", "name: changed"))
    result = callbacks.approve(file, "Customers", "baseline", session)
    assert "Inputs changed" in result[1]


def test_reset_revokes_review_and_downloads(callbacks, session):
    prepare(callbacks, session)
    result = callbacks.reset(session)
    assert session.review is None
    assert result[2:5] == ([], [], [])
    assert not result[5]["interactive"]
    assert result[6]["value"] is None and result[7]["value"] is None


def test_sessions_have_distinct_files_and_cleanup(callbacks):
    first, second = DemoSession(), DemoSession()
    try:
        prepare(callbacks, first)
        prepare(callbacks, second)
        first_dir, second_dir = first.directory, second.directory
        assert first_dir != second_dir
        assert first.review.directory != second.review.directory
        cleanup_session(first)
        assert not first_dir.exists()
        assert second_dir.exists()
        assert second.review is not None
    finally:
        cleanup_session(first)
        cleanup_session(second)


@pytest.mark.parametrize(
    "file_contents", ["[{broken", '[{"email": "secret-invalid"}, {"email": []}]']
)
def test_malformed_inputs_clear_old_draft_without_echo(
    callbacks, session, tmp_path, file_contents
):
    prepare(callbacks, session)
    bad = tmp_path / "bad.json"
    bad.write_text(file_contents)
    result = list(callbacks.inspect(str(bad), "Customers", "baseline", session))[-1]
    assert "Could not continue" in result[1]
    assert file_contents not in str(result)
    assert session.review is None
    assert result[3] == [] and result[6]["value"] is None


def test_empty_and_unavailable_inputs(callbacks, session):
    for file, schema, provider in [
        (None, "Customers", "baseline"),
        (callbacks.workflow.sample(0)[0], "../customer", "baseline"),
        (callbacks.workflow.sample(0)[0], "Customers", "openai"),
    ]:
        result = list(callbacks.inspect(file, schema, provider, session))[-1]
        assert "Could not continue" in result[1]
        assert session.review is None


def test_provider_error_keeps_inspection_but_revokes_approval(
    callbacks, session, monkeypatch
):
    def failure(*args, **kwargs):
        raise workflow_module.ProviderError("Provider unavailable.")

    monkeypatch.setattr(workflow_module, "propose_file", failure)
    _, _, stages = prepare(callbacks, session)
    assert "Provider unavailable" in stages[-1][1]
    assert stages[-1][2]
    assert stages[-1][3] == []
    assert stages[-1][5]["interactive"] is False
    assert session.review is None


def test_apply_validates_beyond_twenty_row_sample(callbacks, session, tmp_path):
    sample, schema = callbacks.workflow.sample(2)
    good = json.loads(Path(sample).read_text())[0]
    records = [good.copy() for _ in range(24)]
    records[-1]["requester_email"] = "invalid-last-row"
    file = tmp_path / "full.json"
    file.write_text(json.dumps(records))
    stages = list(callbacks.inspect(str(file), schema, "baseline", session))
    assert "20 sample rows" in stages[-1][1]
    result = callbacks.approve(str(file), schema, "baseline", session)
    assert "24 rows checked · 23 clean · 1 quarantined" in result[1]
    dirty = list(csv.DictReader(Path(result[7]["value"]).read_text().splitlines()))
    assert dirty[0]["data_row"] == "24"
    assert "invalid-last-row" not in str(result)


def test_modified_snapshot_or_mapping_is_rechecked(callbacks, session):
    file, schema, _ = prepare(callbacks, session)
    session.review.proposal.mapping.fields[0].sources = ["nonexistent"]
    result = callbacks.approve(file, schema, "baseline", session)
    assert "Blocked" in result[1]
    assert result[6]["value"] is None


def test_apply_refusal_returns_checks_and_no_downloads(callbacks, session, monkeypatch):
    file, schema, _ = prepare(callbacks, session)
    checks = session.review.proposal.checks.model_copy(update={"passed": False})

    def refuse(*args, **kwargs):
        raise ChecksFailed(checks)

    monkeypatch.setattr(workflow_module, "apply_file", refuse)
    result = callbacks.approve(file, schema, "baseline", session)
    assert "Blocked" in result[1]
    assert result[6]["value"] is None and result[7]["value"] is None


def test_upload_limit(callbacks, session, tmp_path, monkeypatch):
    file = tmp_path / "big.csv"
    file.write_text("email,full_name\na@example.com,Alice\n")
    monkeypatch.setattr(workflow_module, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(InputError, match="10 MiB"):
        callbacks.workflow.inspect(str(file), "Customers", "baseline", session)


def test_split_names_sample_is_flagged_by_baseline(callbacks, session):
    # The fourth sample shows where header matching stops: First + Last.
    _, filename, schema = workflow_module.SAMPLES[3]
    assert filename == "customers-split.csv" and schema == "Customers"
    _, _, stages = prepare(callbacks, session, 3)
    assert "Flagged" in stages[-1][1]
    assert "Header matching cannot join columns" in stages[-1][1]
    assert stages[-1][5]["interactive"] is False
    full_name = next(row for row in stages[-1][3] if row[0] == "full_name")
    assert full_name[1] == "(unmapped)" and full_name[3] == "FLAGGED"


def test_check_result_column_comes_before_long_text(ui):
    from schema_fixer.display import MAPPING_HEADERS

    assert MAPPING_HEADERS == [
        "Target",
        "Sources",
        "Transform",
        "Check result",
        "Confidence",
        "Reason",
    ]

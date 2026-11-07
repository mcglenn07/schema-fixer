from pathlib import Path

import pytest
import yaml

from schema_fixer.detector import detect
from schema_fixer.io import load_schema, read_table

CASES = sorted((Path(__file__).resolve().parents[1] / "eval/cases").glob("*/case.yaml"))
ALLOWED_TRANSFORMS = {
    "rename",
    "combine",
    "split",
    "parse_date",
    "map_values",
    "cast",
    "constant",
    "drop",
}


def test_corpus_has_twenty_cases_three_schemas_and_required_breakages():
    metadata = [yaml.safe_load(path.read_text()) for path in CASES]
    assert len(metadata) == 20
    assert len({item["id"] for item in metadata}) == 20
    assert len({item["schema"] for item in metadata}) == 3
    assert {
        "renames",
        "synonyms",
        "split_fields",
        "combined_fields",
        "date_formats",
        "enum_drift",
        "missing_required",
        "extra_columns",
        "header_typos",
    } <= {tag for item in metadata for tag in item["breakages"]}
    assert {Path(item["input"]).suffix for item in metadata} == {".csv", ".json"}


@pytest.mark.parametrize("case_path", CASES, ids=lambda p: p.parent.name)
def test_reference_is_complete_and_inspection_finds_seeded_mismatches(case_path):
    case = yaml.safe_load(case_path.read_text())
    expected = yaml.safe_load((case_path.parent / "expected_mapping.yaml").read_text())
    assert case["review_status"] in {"pending", "approved"}
    schema = load_schema(case_path.parent / case["schema"])
    frame = read_table(case_path.parent / case["input"])
    targets = set(expected["fields"])
    missing = set(expected["unmapped_required"])
    optional = set(expected["unmapped_optional"])
    assert not (targets & missing or targets & optional or missing & optional)
    assert targets | missing | optional == set(schema.fields)
    assert all(schema.fields[name].required for name in missing)
    assert all(not schema.fields[name].required for name in optional)
    used = set()
    for entry in [*expected["fields"].values(), *expected["drop"]]:
        assert entry["transform"]["name"] in ALLOWED_TRANSFORMS
        assert set(entry["sources"]) <= set(frame.columns)
        assert entry["reason"]
        name = entry["transform"]["name"]
        parameters = entry["transform"]
        if name == "constant":
            assert entry["sources"] == [] and "value" in parameters
        elif name == "combine":
            assert len(entry["sources"]) >= 2 and isinstance(
                parameters["separator"], str
            )
        else:
            assert len(entry["sources"]) == 1
        if name == "split":
            assert parameters["index"] >= 0 and parameters["separator"]
        if name == "parse_date":
            assert parameters["format"]
        if name == "map_values":
            assert parameters["values"]
        if name == "cast":
            assert parameters["type"] in {"integer", "number", "string", "boolean"}
        used.update(entry["sources"])
    assert used == set(frame.columns)
    dropped = {s for item in expected["drop"] for s in item["sources"]}
    mapped = {s for item in expected["fields"].values() for s in item["sources"]}
    assert dropped.isdisjoint(mapped)
    rows = expected["expected_quarantine_rows"]
    assert rows == sorted(set(rows))
    assert all(1 <= row <= len(frame) for row in rows)
    assert set(rows) == set(expected["quarantine_reasons"])
    report = detect(frame, schema)
    assert report.findings
    actual = {(f.code, f.field, f.source) for f in report.findings}
    for finding in case["required_findings"]:
        assert (finding["code"], finding["field"], finding["source"]) in actual

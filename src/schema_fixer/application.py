"""Deterministic full-file application. No provider or configuration imports."""

import csv
import json
from io import StringIO
from pathlib import Path

from schema_fixer.approval import ChecksFailed, load_approved
from schema_fixer.checker import (
    QUARANTINE_SUFFIX,
    CheckResult,
    check_mapping,
    row_model,
    validate_row,
)
from schema_fixer.io import InputError, read_table
from schema_fixer.models import StrictModel
from schema_fixer.output import write_new_files
from schema_fixer.profiler import is_null


class ApplyReport(StrictModel):
    clean_file: str
    quarantine_file: str
    checks: CheckResult


def csv_text(rows: list[dict], fields: list[str]) -> str:
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def applied_message(message: str) -> str:
    return message.replace("this row would be quarantined", "this row was quarantined")


def apply_file(
    data_path: Path, mapping_path: Path, output: Path | None = None
) -> ApplyReport:
    approved, schema, schema_path = load_approved(mapping_path)
    frame = read_table(data_path)
    if set(frame.columns) != set(approved.source_columns):
        raise InputError(
            "Source columns differ from approval. Review and approve a new mapping."
        )
    checks = check_mapping(approved.mapping, frame, schema, sample_size=None)
    if not checks.passed:
        raise ChecksFailed(checks)
    clean_path = (
        output or Path("outputs") / data_path.stem / f"clean{data_path.suffix.lower()}"
    )
    quarantine_path = clean_path.parent / "quarantine.csv"
    if clean_path.suffix.lower() not in {".csv", ".json"}:
        raise InputError("Clean output must have a .csv or .json extension.")
    protected = {data_path.resolve(), mapping_path.resolve(), schema_path.resolve()}
    if clean_path.resolve() == quarantine_path.resolve() or any(
        path.resolve() in protected for path in (clean_path, quarantine_path)
    ):
        raise InputError(
            "Output paths must be distinct from each other and all inputs."
        )
    valid, quarantine = [], []
    validator = row_model(schema)
    for position, record in enumerate(frame.to_dict(orient="records"), start=1):
        typed, issues = validate_row(approved.mapping, record, validator, position)
        if issues:
            # Missing JSON keys arrive as NaN; preserve actual strings (including
            # whitespace) and native values rather than masked profile samples.
            original = {
                key: None if not isinstance(value, str) and is_null(value) else value
                for key, value in record.items()
            }
            quarantine.append(
                {
                    "data_row": position,
                    "reason": "; ".join(
                        f"{issue.field}: {issue.message.removesuffix(QUARANTINE_SUFFIX)}"
                        for issue in issues
                    ),
                    "original_row": json.dumps(
                        original, ensure_ascii=False, allow_nan=False
                    ),
                }
            )
        else:
            valid.append(typed)
    clean_text = (
        json.dumps(valid, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if clean_path.suffix.lower() == ".json"
        else csv_text(valid, list(schema.fields))
    )
    write_new_files(
        {
            clean_path: clean_text,
            quarantine_path: csv_text(
                quarantine, ["data_row", "reason", "original_row"]
            ),
        }
    )
    # Only successful apply output uses past tense. Propose/approve predictions
    # and refused apply checks still describe what would happen.
    checks = checks.model_copy(
        update={
            "issues": [
                issue.model_copy(update={"message": applied_message(issue.message)})
                for issue in checks.issues
            ]
        }
    )
    return ApplyReport(
        clean_file=str(clean_path), quarantine_file=str(quarantine_path), checks=checks
    )

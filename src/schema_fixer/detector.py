"""Collect structural and per-value mismatches. Never change the source table."""

import re
from pathlib import Path

import pandas as pd
from email_validator import EmailNotValidError, validate_email

from schema_fixer.header_matching import rename_hints
from schema_fixer.io import load_schema, read_table
from schema_fixer.models import FieldSpec, Finding, InspectionReport, TargetSchema
from schema_fixer.profiler import (
    is_iso_date,
    is_null,
    profile_table,
    sample_values,
    value_type,
)


def _type_matches(value: object, spec: FieldSpec) -> bool:
    if spec.type == "string":
        return isinstance(value, str)
    if spec.type == "date":
        # Calendar/representation errors are format mismatches, not two errors.
        return isinstance(value, str)
    inferred = value_type(value)
    return inferred == spec.type or (spec.type == "number" and inferred == "integer")


def _format_matches(value: object, spec: FieldSpec) -> bool:
    if spec.type == "date":
        return is_iso_date(value)
    if spec.format == "email":
        try:
            validate_email(str(value), check_deliverability=False)
            return True
        except EmailNotValidError:
            return False
    if spec.format == "phone":
        return bool(re.fullmatch(r"\+[1-9]\d{6,14}", str(value)))
    return True


def _value_findings(
    values: list,
    field: str,
    source: str,
    spec: FieldSpec,
    tentative: bool,
) -> list[Finding]:
    failures = {
        code: []
        for code in ("null_required", "type_mismatch", "enum_drift", "format_mismatch")
    }
    for row, value in enumerate(values, start=1):
        if is_null(value):
            if spec.required:
                failures["null_required"].append(row)
            continue
        if not _type_matches(value, spec):
            failures["type_mismatch"].append(row)
        if spec.enum is not None and value not in spec.enum:
            failures["enum_drift"].append(row)
        if not _format_matches(value, spec):
            failures["format_mismatch"].append(row)
    messages = {
        "null_required": "Required values are blank or null.",
        "type_mismatch": f"Values do not match type {spec.type}.",
        "enum_drift": "Values are outside the allowed enum.",
        "format_mismatch": "Expected "
        + (
            "a real date in YYYY-MM-DD form."
            if spec.type == "date"
            else "an international phone number (+ and 7-15 digits)."
            if spec.format == "phone"
            else "an email address with valid syntax."
        ),
    }
    return [
        Finding(
            code=code,
            field=field,
            source=source,
            message=messages[code],
            count=len(rows),
            rows=rows,
            samples=sample_values((values[row - 1] for row in rows), source),
            tentative=tentative,
        )
        for code, rows in failures.items()
        if rows
    ]


def detect(frame: pd.DataFrame, schema: TargetSchema) -> InspectionReport:
    sources = list(frame.columns)
    absent = [name for name in schema.fields if name not in sources]
    extra = [name for name in sources if name not in schema.fields]
    findings = [
        Finding(
            code="missing_required", field=name, message="Required column is absent."
        )
        if schema.fields[name].required
        else Finding(
            code="missing_optional",
            field=name,
            message="Optional column is absent. Values stay empty unless mapped.",
        )
        for name in absent
    ]
    findings.extend(
        Finding(
            code="extra_column",
            source=name,
            message="Column is not in the target schema.",
        )
        for name in extra
    )
    hints = rename_hints(extra, absent)
    for field, (source, similarity) in hints.items():
        findings.append(
            Finding(
                code="likely_rename",
                field=field,
                source=source,
                message="Header similarity only; requires review.",
                similarity=similarity,
                tentative=True,
            )
        )
    for field, spec in schema.fields.items():
        source = field if field in sources else hints.get(field, (None, None))[0]
        if source is not None:
            findings.extend(
                _value_findings(
                    frame[source].tolist(), field, source, spec, source != field
                )
            )
    return InspectionReport(
        schema_name=schema.name, profile=profile_table(frame), findings=findings
    )


def inspect_file(data_path: Path | str, schema_path: Path | str) -> InspectionReport:
    return detect(read_table(data_path), load_schema(schema_path))

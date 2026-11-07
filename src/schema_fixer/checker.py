"""Shared structural checks and typed row validation for review and full apply."""

import re
from collections import Counter, defaultdict
from datetime import date
from typing import Annotated, Literal

import pandas as pd
from pydantic import (
    AfterValidator,
    BeforeValidator,
    ConfigDict,
    Field,
    FiniteFloat,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    computed_field,
    create_model,
)

from schema_fixer.detector import _format_matches
from schema_fixer.mapping import Mapping
from schema_fixer.models import FieldSpec, StrictModel, TargetSchema
from schema_fixer.profiler import is_iso_date, is_null
from schema_fixer.transforms import cast_value, transform_field


class CheckIssue(StrictModel):
    code: str
    message: str
    field: str | None = None
    source: str | None = None
    row: int | None = None
    severity: Literal["error", "warning"] = "error"


class CheckResult(StrictModel):
    passed: bool
    rows_checked: int
    valid_rows: int
    issues: list[CheckIssue]

    @computed_field
    @property
    def quarantine_rows(self) -> list[int]:
        """Unique invalid positions among the rows checked."""
        return sorted(
            {
                issue.row
                for issue in self.issues
                if issue.row is not None
                and issue.code in {"transform_failed", "row_invalid"}
            }
        )


QUARANTINE_SUFFIX = "; this row would be quarantined."
FORMAT_REASONS = {
    "email": "not a valid email address",
    "phone": "not a valid phone number (+ and 7-15 digits)",
}
# Plain-English reasons for Pydantic type errors. Never include the raw value.
TYPE_REASONS = {
    "string_type": "expected text",
    "int_type": "not a whole number",
    "float_type": "not a number",
    "finite_number": "not a finite number",
    "bool_type": "not true or false",
    "date_type": "not a date",
}


def _row_reason(error: dict, output: dict) -> str:
    field = str(error["loc"][0]) if error["loc"] else None
    if error["type"] == "value_error":
        return str(error["msg"]).removeprefix("Value error, ")
    if error["type"] == "missing" or is_null(output.get(field)):
        return "required value is blank"
    return TYPE_REASONS.get(error["type"], "value does not fit the target type")


def _transform_reason(transform) -> str:
    if transform.name == "cast":
        return f"could not convert to {transform.type}"
    if transform.name == "parse_date":
        return f"date does not match format {transform.format}"
    if transform.name == "split":
        return "could not split with the mapped separator"
    return f"could not apply {transform.name}"


def _row_type(spec: FieldSpec):
    scalar = {
        "string": StrictStr,
        "integer": StrictInt,
        "number": FiniteFloat,
        "boolean": StrictBool,
        "date": date,
    }[spec.type]

    def prepare(value):
        if is_null(value):
            return None
        if spec.type == "date":
            if not is_iso_date(value):
                raise ValueError("not a real date in YYYY-MM-DD form")
            return date.fromisoformat(value)
        # CSV has no native numeric/boolean scalars. Accept its lexical forms
        # without accepting bool as int or truncating non-integral numbers.
        if isinstance(value, str) and spec.type in {"integer", "number", "boolean"}:
            return cast_value(value, spec.type)
        return value

    def constraints(value):
        if value is None:
            return value
        if spec.enum is not None and value not in spec.enum:
            raise ValueError(f"not an allowed value (allowed: {', '.join(spec.enum)})")
        if spec.format is not None and not _format_matches(value, spec):
            raise ValueError(FORMAT_REASONS[spec.format])
        return value

    return Annotated[
        scalar if spec.required else scalar | None,
        BeforeValidator(prepare),
        AfterValidator(constraints),
    ]


def row_model(schema: TargetSchema):
    # Aliases support any schema header, including spaces or leading underscores,
    # without letting user headers become Pydantic's internal attribute names.
    fields = {
        f"column_{i}": (
            _row_type(spec),
            Field(... if spec.required else None, alias=name),
        )
        for i, (name, spec) in enumerate(schema.fields.items())
    }
    return create_model(
        "TargetRow",
        __config__=ConfigDict(
            strict=True,
            extra="forbid",
            validate_by_alias=True,
            validate_by_name=False,
            loc_by_alias=True,
        ),
        **fields,
    )


def _structure(
    mapping: Mapping, sources: list[str], schema: TargetSchema
) -> list[CheckIssue]:
    issues = []

    def issue(code, message, field=None, severity="error", source=None):
        issues.append(
            CheckIssue(
                code=code,
                message=message,
                field=field,
                source=source,
                severity=severity,
            )
        )

    targets = [entry.target for entry in mapping.fields]
    accounted = targets + mapping.unmapped_required + mapping.unmapped_optional
    for target, count in Counter(accounted).items():
        if target not in schema.fields:
            issue("unknown_target", "Target does not exist in the schema.", target)
        if count > 1:
            issue(
                "duplicate_target",
                "Target is mapped or declared missing more than once.",
                target,
            )
    for target in schema.fields:
        if target not in accounted:
            issue(
                "unaccounted_target",
                "Target must be mapped or declared missing.",
                target,
            )
    for target in mapping.unmapped_required:
        if target in schema.fields and not schema.fields[target].required:
            issue(
                "wrong_missing_group",
                "An optional target was listed as required.",
                target,
            )
        issue("unmapped_required", "Required target has no proposed source.", target)
    for target in mapping.unmapped_optional:
        if target in schema.fields and schema.fields[target].required:
            issue(
                "wrong_missing_group",
                "A required target was listed as optional.",
                target,
            )
        else:
            issue(
                "unmapped_optional",
                "Optional target will remain empty.",
                target,
                "warning",
            )
    use = defaultdict(list)
    for entry in mapping.fields:
        for source in entry.sources:
            use[source].append(entry)
            if source not in sources:
                issue(
                    "missing_source",
                    "Referenced source column does not exist.",
                    entry.target,
                    source=source,
                )
        transform = entry.transform
        if transform.name == "parse_date":
            directives = set(re.findall(r"%(?:%|[a-zA-Z])", transform.format))
            if not (
                ("%Y" in directives or "%y" in directives)
                and (
                    "%j" in directives
                    or (
                        "%d" in directives
                        and any(t in directives for t in ("%m", "%b", "%B"))
                    )
                )
            ):
                issue(
                    "incomplete_date_format",
                    "Date parsing requires year, month and day.",
                    entry.target,
                )
        if transform.name == "constant":
            issue(
                "constant_review",
                "A constant requires an explicit source contract and human review.",
                entry.target,
                "warning",
            )
    for source, entries in use.items():
        if len(entries) > 1:
            # Splitting distinct pieces from a shared input is explicitly allowed.
            parts = {
                (e.transform.separator, e.transform.index)
                for e in entries
                if e.transform.name == "split"
            }
            separators = {part[0] for part in parts}
            if len(parts) != len(entries) or len(separators) != 1:
                issue(
                    "source_reused",
                    "Reuse is permitted only for distinct parts of one split.",
                    source=source,
                )
    dropped = [source for entry in mapping.drop for source in entry.sources]
    for source, count in Counter(dropped).items():
        if source not in sources:
            issue(
                "missing_drop_source",
                "A dropped source column does not exist.",
                source=source,
            )
        if count > 1 or source in use:
            issue(
                "conflicting_drop",
                "A source is dropped twice or both mapped and dropped.",
                source=source,
            )
    for source in sources:
        if source not in use and source not in dropped:
            issue(
                "unaccounted_source",
                "Every source must be mapped or explicitly dropped.",
                source=source,
            )
    return issues


def validate_row(mapping: Mapping, record: dict, validator, position: int):
    """Return schema-typed output or safe issues, never raw values in errors."""
    output, issues, failed = {}, [], set()
    for entry in mapping.fields:
        try:
            output[entry.target] = transform_field(entry, record)
        except (ValueError, TypeError, IndexError, KeyError, OverflowError):
            failed.add(entry.target)
            issues.append(
                CheckIssue(
                    code="transform_failed",
                    field=entry.target,
                    row=position,
                    severity="warning",
                    message=_transform_reason(entry.transform) + QUARANTINE_SUFFIX,
                )
            )
    validated = None
    try:
        validated = validator.model_validate(output).model_dump(
            mode="json", by_alias=True
        )
    except ValidationError as exc:
        for error in exc.errors(
            include_input=False, include_context=False, include_url=False
        ):
            field = str(error["loc"][0]) if error["loc"] else None
            if field not in failed:
                issues.append(
                    CheckIssue(
                        code="row_invalid",
                        field=field,
                        row=position,
                        severity="warning",
                        message=_row_reason(error, output) + QUARANTINE_SUFFIX,
                    )
                )
    return (None if issues else validated), issues


def check_mapping(
    proposal: Mapping | dict,
    frame: pd.DataFrame,
    schema: TargetSchema,
    *,
    sample_size: int | None = 20,
) -> CheckResult:
    # None is the internal full-file mode used by apply, not a CLI sample option.
    if sample_size is not None and not 1 <= sample_size <= 100:
        raise ValueError("Sample size must be between 1 and 100.")
    try:
        payload = proposal.model_dump() if isinstance(proposal, Mapping) else proposal
        mapping = Mapping.model_validate(payload)
    except (ValidationError, ValueError, TypeError):
        return CheckResult(
            passed=False,
            rows_checked=0,
            valid_rows=0,
            issues=[
                CheckIssue(
                    code="invalid_mapping",
                    message="Mapping violates the allowed transform contract or parameter types.",
                )
            ],
        )
    issues = _structure(mapping, list(frame.columns), schema)
    if any(issue.severity == "error" for issue in issues):
        return CheckResult(passed=False, rows_checked=0, valid_rows=0, issues=issues)
    if frame.empty:
        issues.append(
            CheckIssue(
                code="no_sample", message="No data rows are available to validate."
            )
        )
        return CheckResult(passed=False, rows_checked=0, valid_rows=0, issues=issues)
    validator = row_model(schema)
    records = (frame if sample_size is None else frame.head(sample_size)).to_dict(
        orient="records"
    )
    valid_rows = 0
    field_failures = Counter()
    for position, record in enumerate(records, start=1):
        _, row_issues = validate_row(mapping, record, validator, position)
        issues.extend(row_issues)
        if not row_issues:
            valid_rows += 1
        # Count each target at most once per row, including both transform and
        # validation failures. Different dirty fields on different rows do not
        # imply a systematically wrong mapping.
        field_failures.update(
            {issue.field for issue in row_issues if issue.field is not None}
        )
    for field in schema.fields:
        if field_failures[field] == len(records):
            issues.append(
                CheckIssue(
                    code="all_rows_failed_field",
                    field=field,
                    message=f"All {len(records)} checked rows failed this target field; review its mapping or transform.",
                )
            )
    return CheckResult(
        passed=not any(issue.severity == "error" for issue in issues),
        rows_checked=len(records),
        valid_rows=valid_rows,
        issues=issues,
    )

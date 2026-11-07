"""Shared mapping review tables and safe check messages."""

import json

from rich.console import Console
from rich.table import Table

from schema_fixer.checker import CheckResult
from schema_fixer.mapping import Mapping


def print_checks(checks: CheckResult, console: Console, *, sample: bool = True):
    label = "PASSED" if checks.passed else "FLAGGED"
    scope = "Sample rows" if sample else "Rows"
    console.print(
        f"Checks: {label} | {scope}: {checks.rows_checked} | Valid: {checks.valid_rows}"
        f" | Would quarantine: {len(checks.quarantine_rows)}"
    )
    for issue in checks.issues:
        location = f" [{issue.field}]" if issue.field else ""
        location += f" source {issue.source!r}" if issue.source else ""
        location += f" data row {issue.row}" if issue.row else ""
        console.print(f"{issue.severity}: {issue.code}{location}: {issue.message}")


MAPPING_HEADERS = [
    "Target",
    "Sources",
    "Transform",
    "Check result",
    "Confidence",
    "Reason",
]


def mapping_rows(mapping: Mapping, checks: CheckResult) -> list[list[str]]:
    """The same review content for the terminal and local demo."""
    rows = []

    def result(target=None, sources=()):
        issues = [
            i
            for i in checks.issues
            if (i.field == target and target is not None)
            or i.source in sources
            or (i.field is None and i.source is None)
        ]
        if any(i.severity == "error" for i in issues):
            return "FLAGGED"
        if issues:
            rows = sorted({i.row for i in issues if i.row is not None})
            return "WARNING" + (f" rows {', '.join(map(str, rows))}" if rows else "")
        return "PASSED" if checks.rows_checked else "NOT CHECKED"

    for entry in mapping.fields:
        params = entry.transform.model_dump()
        name = params.pop("name")
        transform = name + (
            " " + json.dumps(params, ensure_ascii=False) if params else ""
        )
        rows.append(
            [
                entry.target,
                " + ".join(entry.sources) or "(none)",
                transform,
                result(entry.target, entry.sources),
                f"{entry.confidence:.0%}",
                entry.reason,
            ]
        )
    for entry in mapping.drop:
        rows.append(
            [
                "(drop)",
                ", ".join(entry.sources),
                "drop",
                result(sources=entry.sources),
                f"{entry.confidence:.0%}",
                entry.reason,
            ]
        )
    for name in mapping.unmapped_required:
        rows.append(
            [
                name,
                "(unmapped)",
                "",
                result(name),
                "",
                "Required target has no proposed source.",
            ]
        )
    for name in mapping.unmapped_optional:
        rows.append(
            [
                name,
                "(unmapped)",
                "",
                result(name),
                "",
                "Optional target will remain empty.",
            ]
        )
    return rows


def print_mapping(mapping: Mapping, checks: CheckResult, console: Console):
    table = Table(*MAPPING_HEADERS)
    for column in table.columns:
        column.overflow = "fold"
    for row in mapping_rows(mapping, checks):
        table.add_row(*row)
    console.print(table)

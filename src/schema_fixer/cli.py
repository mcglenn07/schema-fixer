"""Inspect, propose, review and apply schema-bound mappings."""

from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.table import Table

from schema_fixer.application import apply_file
from schema_fixer.approval import (
    ChecksFailed,
    edit_yaml,
    parse_draft,
    read_draft,
    save_approved,
)
from schema_fixer.checker import check_mapping
from schema_fixer.detector import inspect_file
from schema_fixer.display import print_checks, print_mapping
from schema_fixer.io import InputError, load_schema, read_table
from schema_fixer.models import INFO_CODES
from schema_fixer.proposals import propose_file
from schema_fixer.providers import ProviderError

app = typer.Typer(
    no_args_is_help=True, help="Inspect, propose, approve and apply schema mappings."
)


@app.callback()
def main():
    """Schema Fixer. Review mappings before deterministic application."""


@app.command("inspect")
def inspect_command(
    data: Annotated[
        Path, typer.Argument(help="UTF-8 CSV or JSON array of flat objects.")
    ],
    schema: Annotated[Path, typer.Option("--schema", help="Target YAML schema.")],
    json_output: Annotated[
        bool, typer.Option("--json", help="Print structured JSON.")
    ] = False,
    fail_on_mismatch: Annotated[
        bool,
        typer.Option(
            "--fail-on-mismatch",
            help="Exit 1 when mismatches exist. Absent optional fields do not count.",
        ),
    ] = False,
):
    try:
        report = inspect_file(data, schema)
    except InputError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    blocking = [f for f in report.findings if f.code not in INFO_CODES]
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
    else:
        console = Console(markup=False, highlight=False)
        console.print(
            f"Schema: {report.schema_name} | Rows: {report.profile.row_count}"
        )
        profiles = Table("Column", "Inferred type", "Null %", "Masked samples")
        for column in report.profile.columns:
            profiles.add_row(
                column.name,
                column.inferred_type,
                f"{column.null_percent:g}",
                " | ".join(column.samples),
            )
        console.print(profiles)
        if report.findings:
            table = Table("Issue", "Target", "Source", "Details")
            for finding in report.findings:
                detail = finding.message
                if finding.count:
                    rows = ", ".join(map(str, finding.rows[:10]))
                    detail += f" Count: {finding.count}; data rows: {rows}"
                    if len(finding.rows) > 10:
                        detail += ", ... (all positions in --json)"
                if finding.similarity is not None:
                    detail += f" Similarity: {finding.similarity:.0%}."
                if finding.tentative:
                    detail += " Tentative."
                table.add_row(
                    finding.code, finding.field or "", finding.source or "", detail
                )
            console.print(table)
        if not report.findings:
            console.print("No mismatches detected.")
        elif not blocking:
            console.print("No blocking mismatches. Only optional fields are absent.")
        console.print("Inspection only. No data changed and no mapping applied.")
    if fail_on_mismatch and blocking:
        raise typer.Exit(1)


@app.command("propose")
def propose_command(
    data: Annotated[
        Path, typer.Argument(help="UTF-8 CSV or JSON array of flat objects.")
    ],
    schema: Annotated[Path, typer.Option("--schema", help="Target YAML schema.")],
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider", help="baseline or openai; defaults to PROVIDER, then openai."
        ),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print draft and checks as JSON.")
    ] = False,
    sample_size: Annotated[
        int,
        typer.Option(
            "--sample-size",
            min=1,
            max=100,
            help="Number of leading rows checked locally.",
        ),
    ] = 20,
):
    try:
        report = propose_file(data, schema, provider=provider, sample_size=sample_size)
    except (InputError, ProviderError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
    else:
        console = Console(markup=False, highlight=False)
        console.print(f"Provider: {report.provider} | Status: draft")
        print_mapping(report.mapping, report.checks, console)
        print_checks(report.checks, console)
        console.print(
            "Draft only. Sample checks are not approval or a full-file guarantee. No files written."
        )
    if not report.checks.passed:
        raise typer.Exit(1)


@app.command("approve")
def approve_command(
    data: Annotated[Path, typer.Argument(help="CSV or flat JSON input to review.")],
    schema: Annotated[Path, typer.Option("--schema", help="Target YAML schema.")],
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="baseline or openai; omit with --draft."),
    ] = None,
    draft: Annotated[
        Path | None,
        typer.Option("--draft", help="Review a saved draft without a provider."),
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="New approved mapping YAML path.")
    ] = None,
    sample_size: Annotated[int, typer.Option("--sample-size", min=1, max=100)] = 20,
):
    console = Console(markup=False, highlight=False)
    try:
        if draft is not None and provider is not None:
            raise InputError("Use either --draft or --provider, not both.")
        destination = output or Path("mappings") / f"{data.stem}.yaml"
        if destination.suffix.lower() not in {".yaml", ".yml"}:
            raise InputError("Approved mapping output must be .yaml or .yml.")
        if destination.exists() or destination.is_symlink():
            raise InputError(
                "Mapping destination already exists. Choose a new --output path."
            )
        frame, target = read_table(data), load_schema(schema)
        if draft is not None:
            proposal = read_draft(draft)
        else:
            proposal = propose_file(
                data, schema, provider=provider, sample_size=sample_size
            ).mapping
        working_text = yaml.safe_dump(
            proposal.model_dump(mode="json"), sort_keys=False, allow_unicode=True
        )
        while True:
            try:
                proposal = parse_draft(working_text)
                checks = check_mapping(proposal, frame, target, sample_size=sample_size)
                print_mapping(proposal, checks, console)
                print_checks(checks, console)
            except InputError as exc:
                proposal, checks = None, None
                console.print(str(exc))
            action = (
                typer.prompt("Action [accept/edit/cancel]", default="cancel")
                .strip()
                .lower()
            )
            if action == "cancel":
                console.print("Cancelled. No approved mapping saved.")
                raise typer.Exit(1)
            if action == "edit":
                working_text = edit_yaml(working_text)
            elif action == "accept":
                if proposal is None or checks is None or not checks.passed:
                    console.print("Cannot accept: fix the draft with edit, or cancel.")
                    continue
                save_approved(
                    proposal,
                    data,
                    schema,
                    destination,
                    reviewed_frame=frame,
                    reviewed_schema=target,
                    sample_size=sample_size,
                )
                console.print(f"Approved mapping saved: {destination}")
                console.print(
                    "Approval saved only. Run apply to write clean and quarantine files."
                )
                return
            elif action != "edit":
                console.print("Choose accept, edit, or cancel.")
    except ChecksFailed as exc:
        print_checks(exc.checks, console)
        raise typer.Exit(1) from exc
    except (InputError, ProviderError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc


@app.command("apply")
def apply_command(
    data: Annotated[
        Path, typer.Argument(help="CSV or flat JSON input to apply in full.")
    ],
    mapping: Annotated[
        Path, typer.Option("--mapping", help="Saved approved mapping YAML.")
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", help="New clean .csv or .json; quarantine.csv is its sibling."
        ),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print safe checks, counts and paths.")
    ] = False,
):
    console = Console(markup=False, highlight=False)
    try:
        report = apply_file(data, mapping, output)
    except ChecksFailed as exc:
        if json_output:
            typer.echo(exc.checks.model_dump_json(indent=2))
        else:
            print_checks(exc.checks, console, sample=False)
        raise typer.Exit(1) from exc
    except InputError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
    else:
        console.print(
            f"Applied | Rows: {report.checks.rows_checked} | Clean: {report.checks.valid_rows} | Quarantined: {len(report.checks.quarantine_rows)}"
        )
        console.print(f"Clean file: {report.clean_file}")
        console.print(f"Quarantine file: {report.quarantine_file}")


if __name__ == "__main__":
    app()

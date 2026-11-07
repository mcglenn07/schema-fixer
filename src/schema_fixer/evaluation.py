"""Deterministic scoring of approved references, separate from provider execution."""

import copy
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from statistics import median

import pandas as pd
import yaml

from schema_fixer.checker import check_mapping, row_model, validate_row
from schema_fixer.io import InputError, UniqueSafeLoader, load_schema, read_table
from schema_fixer.mapping import Mapping
from schema_fixer.models import TargetSchema

CASE19 = "19_ticket_resolved_export"


def read_yaml(path: Path):
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueSafeLoader)
    except (OSError, UnicodeError, yaml.YAMLError, ValueError, TypeError) as exc:
        raise InputError(f"Cannot read eval YAML: {path.name}.") from exc


@dataclass
class EvalCase:
    id: str
    schema: TargetSchema
    frame: pd.DataFrame
    reference: dict
    paths: tuple[Path, ...]


def reference_mapping(reference: dict) -> Mapping:
    """Adapt reference dictionaries without rewriting them or reading reasons."""
    fields = []
    for target, entry in reference["fields"].items():
        transform = copy.deepcopy(entry["transform"])
        if transform["name"] == "map_values":
            transform["values"] = [
                {"source": key, "target": value}
                for key, value in transform["values"].items()
            ]
        fields.append(
            {
                "target": target,
                "sources": entry["sources"],
                "transform": transform,
                "confidence": 1.0,
                "reason": "Reference adapter; not a provider confidence.",
            }
        )
    return Mapping.model_validate(
        {
            "fields": fields,
            "drop": [{**entry, "confidence": 1.0} for entry in reference["drop"]],
            "unmapped_required": reference["unmapped_required"],
            "unmapped_optional": reference["unmapped_optional"],
        }
    )


def load_cases(root: Path) -> list[EvalCase]:
    paths = sorted((root / "eval/cases").glob("*/case.yaml"))
    if len(paths) != 20:
        raise InputError("The evaluation requires exactly 20 cases.")
    metadata = [read_yaml(path) for path in paths]
    if any(
        not isinstance(meta, dict) or meta.get("review_status") != "approved"
        for meta in metadata
    ):
        raise InputError(
            "Every eval case must be approved by Glenn before any provider runs."
        )
    if len({meta["id"] for meta in metadata}) != 20:
        raise InputError("Eval case IDs must be unique.")
    cases = []
    for path, meta in zip(paths, metadata, strict=True):
        if meta["id"] != path.parent.name:
            raise InputError("Eval ID must match its directory.")
        schema_path = (path.parent / meta["schema"]).resolve()
        input_path = (path.parent / meta["input"]).resolve()
        reference_path = path.parent / "expected_mapping.yaml"
        schema, frame = load_schema(schema_path), read_table(input_path)
        reference = read_yaml(reference_path)
        mapping = reference_mapping(reference)
        targets = (
            [f.target for f in mapping.fields]
            + mapping.unmapped_required
            + mapping.unmapped_optional
        )
        if Counter(targets) != Counter(schema.fields.keys()):
            raise InputError("Reference must account for every target exactly once.")
        rows = reference["expected_quarantine_rows"]
        if rows != sorted(set(rows)) or any(
            type(r) is not int or not 1 <= r <= len(frame) for r in rows
        ):
            raise InputError("Reference quarantine positions are invalid.")
        if set(rows) != set(reference["quarantine_reasons"]):
            raise InputError("Reference quarantine positions and reasons disagree.")
        cases.append(
            EvalCase(
                meta["id"],
                schema,
                frame,
                reference,
                (path, schema_path, input_path, reference_path),
            )
        )
    return cases


def dataset_hash(cases: list[EvalCase], root: Path) -> str:
    files = {path.resolve() for case in cases for path in case.paths}
    payload = {
        str(path.relative_to(root.resolve())): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(files)
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def provider_reference(case: EvalCase) -> Mapping:
    expected = reference_mapping(case.reference)
    if case.id == CASE19:
        expected.fields = [f for f in expected.fields if f.target != "status"]
        expected.unmapped_required = [*expected.unmapped_required, "status"]
    return expected


def decision(mapping: Mapping, target: str, schema: TargetSchema) -> dict:
    entries = [f for f in mapping.fields if f.target == target]
    groups = [
        name
        for name in ("unmapped_required", "unmapped_optional")
        for value in getattr(mapping, name)
        if value == target
    ]
    if len(entries) + len(groups) != 1:
        return {"invalid_accounting": len(entries) + len(groups)}
    if groups:
        return {"state": groups[0]}
    entry = entries[0]
    transform = entry.transform.model_dump(mode="json")
    if transform["name"] == "cast" and transform["type"] == schema.fields[target].type:
        transform = {"name": "rename"}
    if transform["name"] == "map_values":
        transform["values"] = sorted(
            transform["values"], key=lambda pair: pair["source"]
        )
    return {"sources": entry.sources, "transform": transform}


def canonical(value) -> str:
    # JSON preserves boolean/number distinctions that Python dict equality loses.
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def same_fixture_values(
    case: EvalCase, expected: Mapping, actual: Mapping | None, target: str
) -> bool:
    """Diagnostic only: equal supplied-row effects never override scoring rules."""
    wanted = [e for e in expected.fields if e.target == target]
    got = [e for e in actual.fields if e.target == target] if actual else []
    if len(wanted) != 1 or len(got) != 1 or wanted[0].sources != got[0].sources:
        return False
    validator = row_model(
        TargetSchema(
            name="field comparison", fields={target: case.schema.fields[target]}
        )
    )
    left = Mapping(fields=wanted, drop=[], unmapped_required=[], unmapped_optional=[])
    right = Mapping(fields=got, drop=[], unmapped_required=[], unmapped_optional=[])
    for row, record in enumerate(case.frame.to_dict(orient="records"), start=1):
        a, issues_a = validate_row(left, record, validator, row)
        b, issues_b = validate_row(right, record, validator, row)
        if canonical(a) != canonical(b) or bool(issues_a) != bool(issues_b):
            return False
    return True


def expected_quarantine(case: EvalCase) -> dict[int, list[str]]:
    if case.id == CASE19:
        return {position: ["status"] for position in range(1, len(case.frame) + 1)}
    return {
        row: sorted({reason.split(":", 1)[0] for reason in reasons})
        for row, reasons in case.reference["quarantine_reasons"].items()
    }


def predict_quarantine(
    case: EvalCase, mapping: Mapping, checks
) -> dict[int, list[str]] | None:
    # Eval-only prediction, never approval or application. Missing required
    # targets are intentionally validated as absent to score abstention cases.
    if any(
        i.severity == "error"
        and i.code not in {"unmapped_required", "all_rows_failed_field"}
        for i in checks.issues
    ):
        return None
    validator = row_model(case.schema)
    result = {}
    for row, record in enumerate(case.frame.to_dict(orient="records"), start=1):
        _, issues = validate_row(mapping, record, validator, row)
        if issues:
            result[row] = sorted({i.field for i in issues if i.field is not None})
    return result


def score_mapping(case: EvalCase, mapping: Mapping | None) -> dict:
    expected = provider_reference(case)
    failures = []
    correct = high_total = high_wrong = missing_correct = equivalent_mismatches = 0
    expected_missing = set(expected.unmapped_required + expected.unmapped_optional)

    def failure(field, want, got, reason):
        failures.append(
            {
                "case": case.id,
                "field": field,
                "expected": want,
                "got": got,
                "reason": reason,
            }
        )

    decisions = {}
    same_effect = {}
    for target in case.schema.fields:
        want = decision(expected, target, case.schema)
        got = (
            decision(mapping, target, case.schema)
            if mapping
            else {"error": "no usable proposal"}
        )
        matches = canonical(want) == canonical(got)
        decisions[target] = matches
        same_effect[target] = matches
        correct += matches
        missing_correct += matches and target in expected_missing
        if not matches:
            equivalent = same_fixture_values(case, expected, mapping, target)
            equivalent_mismatches += equivalent
            same_effect[target] = equivalent
            failure(
                target,
                want,
                got,
                "Different transform with the same validated values and row validity on every fixture row. Counts toward output match; still a strict mismatch."
                if equivalent
                else "Source, transform, parameters or missing-field decision differs.",
            )
    checks = None
    actual_quarantine = None
    structural = []
    if mapping is not None:
        for entry in mapping.fields:
            if entry.confidence >= 0.8:
                high_total += 1
                high_wrong += not decisions.get(entry.target, False)
            if entry.target not in case.schema.fields:
                failure(entry.target, "no such target", "mapped", "Unexpected target.")
        actual_drop = sorted(s for entry in mapping.drop for s in entry.sources)
        wanted_drop = sorted(s for entry in expected.drop for s in entry.sources)
        if actual_drop != wanted_drop:
            failure(
                "(drop)", wanted_drop, actual_drop, "Unused source accounting differs."
            )
        checks = check_mapping(mapping, case.frame, case.schema, sample_size=None)
        structural = sorted(
            {
                i.code
                for i in checks.issues
                if i.severity == "error"
                and i.code not in {"unmapped_required", "all_rows_failed_field"}
            }
        )
        if structural:
            failure(
                "(structure)",
                "valid source/target accounting",
                structural,
                "Local mapping checks rejected the structure.",
            )
        actual_quarantine = predict_quarantine(case, mapping, checks)
    wanted_quarantine = expected_quarantine(case)
    quarantine_correct = actual_quarantine == wanted_quarantine
    if not quarantine_correct:
        failure(
            "(quarantine)",
            wanted_quarantine,
            actual_quarantine if actual_quarantine is not None else "not evaluable",
            "Predicted row positions or failing target fields differ.",
        )
    # Execution-based score: the draft yields the reference's output on the
    # supplied rows. Measured on fixture rows only, not a general equivalence.
    output_match = (
        mapping is not None
        and not structural
        and all(same_effect.values())
        and quarantine_correct
    )
    return {
        "output_match": output_match,
        "field_correct": int(correct),
        "field_total": len(case.schema.fields),
        "fixture_equivalent_mismatches": equivalent_mismatches,
        "missing_correct": int(missing_correct),
        "missing_total": len(expected_missing),
        "high_confidence_wrong": int(high_wrong),
        "high_confidence_total": high_total,
        "quarantine_correct": quarantine_correct,
        "case_passed": not failures,
        "predicted_quarantine": actual_quarantine,
        "checks": checks.model_dump(mode="json") if checks else None,
        "failures": failures,
    }


def estimate_cost(
    usage: dict | None, model: str | None, tier: str | None, pricing: dict
) -> float | None:
    if (
        usage is None
        or model is None
        or not (model == pricing["model"] or model.startswith(pricing["model"] + "-"))
    ):
        return None
    if tier != pricing["service_tier"]:
        return None
    details = usage.get("input_tokens_details") or {}
    counts = [
        usage.get("input_tokens"),
        usage.get("output_tokens"),
        details.get("cached_tokens"),
        details.get("cache_write_tokens"),
    ]
    if any(type(n) is not int or n < 0 for n in counts):
        return None
    inputs, outputs, cached, written = counts
    if inputs > pricing["maximum_input_tokens"] or cached + written > inputs:
        return None
    ttl = details.get("cache_write_tokens_details")
    # This client does not override the documented default 30m cache lifetime.
    write12 = ttl.get("ttl_12h_tokens", 0) if ttl else 0
    write30 = ttl.get("ttl_30m_tokens", written - write12) if ttl else written
    if (
        any(type(n) is not int or n < 0 for n in (write12, write30))
        or write12 + write30 != written
    ):
        return None
    amounts = {
        "input": inputs - cached - written,
        "cached_input": cached,
        "cache_write_30m": write30,
        "cache_write_12h": write12,
        "output": outputs,
    }
    total = sum(
        Decimal(str(pricing["per_million_tokens"][key])) * count
        for key, count in amounts.items()
    ) / Decimal(1_000_000)
    return float(total)


def aggregate(records: list[dict]) -> dict:
    keys = (
        "field_correct",
        "field_total",
        "missing_correct",
        "missing_total",
        "high_confidence_wrong",
        "high_confidence_total",
    )
    result = {key: sum(r["score"][key] for r in records) for key in keys}
    result.update(
        {
            "cases": len(records),
            "case_passed": sum(r["score"]["case_passed"] for r in records),
            "output_match": sum(r["score"]["output_match"] for r in records),
            "quarantine_correct": sum(
                r["score"]["quarantine_correct"] for r in records
            ),
            "errors": sum(r.get("error") is not None for r in records),
            "p50_seconds": median(
                [
                    r["latency_seconds"]
                    for r in records
                    if r.get("latency_seconds") is not None
                ]
            )
            if any(r.get("latency_seconds") is not None for r in records)
            else None,
            "cost_known_usd": sum(
                r["cost_usd"] for r in records if r.get("cost_usd") is not None
            ),
            "cost_unknown_cases": sum(r.get("cost_usd") is None for r in records),
        }
    )
    return result


def fraction(numerator, denominator) -> str:
    return (
        f"{numerator}/{denominator} ({numerator / denominator:.1%})"
        if denominator
        else "N/A (0 denominator)"
    )


def comparison_table(records: list[dict]) -> str:
    lines = [
        "| Provider | Output match | Strict pass | Field accuracy | Missing recall | Confident wrong | Quarantine exact | API errors | Cost/file USD | Total USD | p50 seconds |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for provider in dict.fromkeys(r["provider"] for r in records):
        items = [r for r in records if r["provider"] == provider]
        a = aggregate(items)
        total = (
            f"${a['cost_known_usd']:.6f}"
            if not a["cost_unknown_cases"]
            else f"unknown ({a['cost_unknown_cases']} cases; known ${a['cost_known_usd']:.6f})"
        )
        per_file = (
            f"${a['cost_known_usd'] / a['cases']:.6f}"
            if not a["cost_unknown_cases"]
            else "unknown"
        )
        latency = (
            f"{a['p50_seconds']:.6f}" if a["p50_seconds"] is not None else "unknown"
        )
        lines.append(
            f"| {provider} | {a['output_match']}/{a['cases']} | {a['case_passed']}/{a['cases']} | {fraction(a['field_correct'], a['field_total'])} | {fraction(a['missing_correct'], a['missing_total'])} | {fraction(a['high_confidence_wrong'], a['high_confidence_total'])} | {a['quarantine_correct']}/{a['cases']} | {a['errors']} | {per_file} | {total} | {latency} |"
        )
    return "\n".join(lines)


def markdown_cell(value) -> str:
    text = value if isinstance(value, str) else canonical(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "&#124;")
        .replace("`", "&#96;")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def render_results(manifest: dict, records: list[dict]) -> str:
    lines = [
        "# Schema Fixer evaluation",
        "",
        f"Run: `{manifest['run_id']}`. Started UTC: {manifest['started_at']}.",
        f"Model: `{manifest['model']}`; reasoning: low; standard processing; zero retries. Dataset SHA256: `{manifest['dataset_sha256']}`.",
        f"Run code SHA256: `{manifest['code_sha256']}`. Report code SHA256: `{manifest.get('report_code_sha256', manifest['code_sha256'])}`.",
        "",
        comparison_table(records),
        "",
        "## Scoring and measurement",
        "",
        "- Output match (headline) is execution-based scoring, the same idea as execution accuracy in text-to-SQL benchmarks. A case matches when the draft passes local structure checks, every target yields the same validated values and row validity as the reference on every supplied row, and the predicted quarantine rows and fields are identical. It is measured on the supplied rows only: two transforms that agree here can still differ on unseen data. Example: `parse_date` with `%Y-%m-%d` accepts `2026-1-6`, which a plain rename rejects.",
        "- Strict pass compares the transform itself. Field accuracy counts every schema target, including explicit missing declarations. Source order and transform parameters matter; entry order, confidence and explanation wording do not. Rename equals cast to the schema's own type. Other transformations, including redundant ISO parsers and identity value maps, count as strict mismatches; the failures table marks the ones with the same output.",
        "- Missing recall uses reference missing fields. Confident wrong counts wrong target entries among emitted entries with confidence >= 0.8; abstentions have no confidence entry. Zero denominators are N/A.",
        "- Case 19 uses the provider-stage answer: leave status unmapped. Its predicted invalid rows all lack status. The resolved constant in the fixture is a human-supplied post-approval contract, never provider input.",
        "- Quarantine exact requires identical row positions AND failing target-field sets. Missing-required drafts are dry-validated for this prediction, including cases 07/13/19. Other structural failures are unevaluable and fail this metric. Nothing is approved or applied by evaluation.",
        "- Strict pass requires target decisions, drop accounting, valid structure and quarantine predictions to match. Correct abstention can pass the eval while the CLI still blocks application until a human supplies missing required data.",
        "- Latency is median wall time of provider calls, including failures, excluding profiling, scoring and disk writes. Baseline cost is zero. Provider errors are retained as failed decisions, not removed from denominators.",
        f"- Cost is an estimate using returned token usage and [{manifest['pricing']['as_of']} official pricing]({manifest['pricing']['source']}). Cached input and cache writes use separate rates; output tokens include reasoning. Missing accounting is unknown, not free. These are estimates, not invoice reconciliation.",
        "- One run on 20 synthetic cases is not a production accuracy, reliability or speed guarantee. Only schema and masked profiles reach providers; case descriptions, reference answers and full rows do not.",
        "",
        "## Failures",
        "",
        "| Provider | Case | Field | Expected | Got | Reason |",
        "|---|---|---|---|---|---|",
    ]
    failures = 0
    for record in records:
        for item in record["score"]["failures"]:
            failures += 1
            lines.append(
                "| "
                + " | ".join(
                    markdown_cell(v)
                    for v in [
                        record["provider"],
                        item["case"],
                        item["field"],
                        item["expected"],
                        item["got"],
                        item["reason"],
                    ]
                )
                + " |"
            )
        if record.get("error"):
            failures += 1
            lines.append(
                f"| {record['provider']} | {record['case']} | (provider) | usable proposal | request failed | {markdown_cell(record['error'])} |"
            )
    if not failures:
        lines.append("| all | all | none | match | match | No failures. |")
    lines.extend(
        [
            "",
            "## Per-case measurements",
            "",
            "| Provider | Case | Output | Strict | Local checks | Latency seconds | Input tokens | Cached | Cache writes | Output tokens | Cost USD |",
            "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for r in records:
        usage = r.get("usage") or {}
        details = usage.get("input_tokens_details") or {}
        cost = f"${r['cost_usd']:.8f}" if r.get("cost_usd") is not None else "unknown"
        duration = (
            f"{r['latency_seconds']:.6f}"
            if r.get("latency_seconds") is not None
            else "unknown"
        )
        checks = r["score"]["checks"]
        values = [
            r["provider"],
            r["case"],
            "MATCH" if r["score"]["output_match"] else "DIFF",
            "PASS" if r["score"]["case_passed"] else "FAIL",
            "PASSED" if checks and checks["passed"] else "FLAGGED/no proposal",
            duration,
            usage.get("input_tokens", "N/A"),
            details.get("cached_tokens", "N/A"),
            details.get("cache_write_tokens", "N/A"),
            usage.get("output_tokens", "N/A"),
            cost,
        ]
        lines.append("| " + " | ".join(str(v) for v in values) + " |")
    return "\n".join(lines) + "\n"

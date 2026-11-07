"""One-shot eval execution with durable attempts and offline report replay."""

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter

from schema_fixer.config import load_settings
from schema_fixer.evaluation import (
    dataset_hash,
    estimate_cost,
    load_cases,
    read_yaml,
    render_results,
    score_mapping,
)
from schema_fixer.io import InputError
from schema_fixer.mapping import Mapping
from schema_fixer.profiler import profile_table
from schema_fixer.proposals import create_proposer
from schema_fixer.providers import ProviderError


def code_hash(root: Path) -> str:
    paths = sorted((root / "src").rglob("*.py")) + [
        root / "eval/run_eval.py",
        root / "uv.lock",
    ]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def save_json(path: Path, data: dict):
    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_report(path: Path, manifest: dict, records: list[dict]):
    if path.suffix != ".md":
        raise InputError("Eval report output must be Markdown (.md).")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_results(manifest, records), encoding="utf-8")


def run_evaluation(
    root: Path, providers: list[str], run_dir: Path, output: Path, *, factory=None
) -> list[dict]:
    cases = load_cases(root)
    if (
        not providers
        or len(providers) != len(set(providers))
        or set(providers) - {"baseline", "openai"}
    ):
        raise InputError("Select baseline and/or openai exactly once.")
    if output.suffix != ".md":
        raise InputError("Eval report output must be Markdown (.md).")
    settings = {provider: load_settings(provider) for provider in providers}
    pricing = read_yaml(root / "eval/pricing.yaml")
    if "openai" in settings:
        if not settings["openai"].api_key:
            raise InputError("OpenAI evaluation requires OPENAI_API_KEY.")
        if settings["openai"].model != pricing["model"]:
            raise InputError(
                "Update the verified pricing snapshot for the configured model before evaluating."
            )
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise InputError(
            "Run directory already exists. Use --report-only; calls are never retried."
        ) from exc
    manifest = {
        "version": 1,
        "run_id": run_dir.name,
        "started_at": datetime.now(UTC).isoformat(),
        "providers": providers,
        "case_ids": [case.id for case in cases],
        "model": settings["openai"].model
        if "openai" in settings
        else "baseline (no model)",
        "dataset_sha256": dataset_hash(cases, root),
        "code_sha256": code_hash(root),
        "pricing": pricing,
        "reasoning_effort": "low",
        "max_retries": 0,
        "max_output_tokens": 4096,
        "service_tier": "default",
    }
    save_json(run_dir / "manifest.json", manifest)
    records = []
    for provider in providers:
        for case in cases:
            path = run_dir / f"{provider}-{case.id}.json"
            record = {
                "provider": provider,
                "case": case.id,
                "state": "started",
                "started_at": datetime.now(UTC).isoformat(),
            }
            # An exclusive marker exists before any API attempt. A crash never
            # causes an automatic retry; report-only can inspect partial runs.
            with path.open("x", encoding="utf-8") as stream:
                json.dump(record, stream)
            proposer = (factory or create_proposer)(settings[provider])
            columns = profile_table(case.frame).columns
            proposal, error = None, None
            started = perf_counter()
            try:
                proposal = proposer.propose(case.schema, columns)
            except ProviderError:
                error = "Provider returned no usable proposal. No retry was attempted."
            latency = perf_counter() - started
            usage = getattr(proposer, "last_usage", None)
            model = getattr(proposer, "last_response_model", None)
            tier = getattr(proposer, "last_service_tier", None)
            record.update(
                {
                    "state": "complete",
                    "error": error,
                    "latency_seconds": latency,
                    "mapping": proposal.model_dump(mode="json") if proposal else None,
                    "usage": usage,
                    "response_model": model,
                    "service_tier": tier,
                    "cost_usd": 0.0
                    if provider == "baseline"
                    else estimate_cost(usage, model, tier, pricing),
                    "score": score_mapping(case, proposal),
                }
            )
            save_json(path, record)
            records.append(record)
            print(
                f"{provider} {case.id}: {'error' if error else 'recorded'} ({latency:.3f}s)",
                flush=True,
            )
    write_report(output, manifest, records)
    return records


def replay_report(root: Path, run_dir: Path, output: Path) -> list[dict]:
    cases = load_cases(root)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest["dataset_sha256"] != dataset_hash(cases, root):
        raise InputError(
            "Eval dataset changed since this run. Refusing to mix old calls with new references."
        )
    if manifest["case_ids"] != [case.id for case in cases]:
        raise InputError("Saved run cases differ from the approved dataset.")
    records = []
    for provider in manifest["providers"]:
        for case in cases:
            path = run_dir / f"{provider}-{case.id}.json"
            record = (
                json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            )
            if record.get("state") != "complete":
                record = {
                    "provider": provider,
                    "case": case.id,
                    "mapping": None,
                    "usage": None,
                    "latency_seconds": None,
                    "cost_usd": None,
                    "error": "Incomplete or unstarted attempt; report-only never calls providers.",
                }
            mapping = (
                Mapping.model_validate(record["mapping"]) if record["mapping"] else None
            )
            record["score"] = score_mapping(case, mapping)
            records.append(record)
    manifest["report_code_sha256"] = code_hash(root)
    write_report(output, manifest, records)
    return records


def main(root: Path, argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Score approved eval cases; baseline only unless OpenAI is explicitly selected."
    )
    parser.add_argument("--providers", nargs="+", choices=["baseline", "openai"])
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--output", type=Path, default=root / "eval/results.md")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.report_only:
            if args.run_dir is None or args.providers is not None:
                raise InputError(
                    "--report-only requires --run-dir and cannot select providers."
                )
            records = replay_report(root, args.run_dir, args.output)
        else:
            run_dir = args.run_dir or root / "eval/runs" / datetime.now(UTC).strftime(
                "%Y%m%dT%H%M%S%fZ"
            )
            records = run_evaluation(
                root, args.providers or ["baseline"], run_dir, args.output
            )
        print(f"Results written: {args.output}")
        return int(any(r.get("error") for r in records))
    except (InputError, ProviderError, OSError, ValueError, KeyError, TypeError) as exc:
        # Do not stringify arbitrary parsing/provider exceptions containing data.
        message = (
            str(exc)
            if isinstance(exc, InputError)
            else "Cannot run evaluation. Check local input, configuration and output permissions."
        )
        print(f"Error: {message}")
        return 2

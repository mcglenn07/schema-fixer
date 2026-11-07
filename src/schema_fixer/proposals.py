"""Coordinate proposing and sample checking without approval or persistent output."""

from pathlib import Path
from typing import Literal

from schema_fixer.checker import CheckResult, check_mapping
from schema_fixer.config import Settings, load_settings
from schema_fixer.io import load_schema, read_table
from schema_fixer.mapping import Mapping
from schema_fixer.models import StrictModel
from schema_fixer.profiler import profile_table
from schema_fixer.providers import Proposer
from schema_fixer.providers.baseline import BaselineProposer


class ProposalReport(StrictModel):
    provider: Literal["baseline", "openai"]
    model: str | None
    status: Literal["draft"] = "draft"
    mapping: Mapping
    checks: CheckResult


def create_proposer(settings: Settings) -> Proposer:
    if settings.provider == "baseline":
        return BaselineProposer()
    from schema_fixer.providers.openai import OpenAIProposer

    return OpenAIProposer(settings)


def propose_file(
    data_path: Path | str,
    schema_path: Path | str,
    *,
    provider: str | None = None,
    sample_size: int = 20,
) -> ProposalReport:
    settings = load_settings(provider)
    frame, schema = read_table(data_path), load_schema(schema_path)
    columns = profile_table(frame).columns
    proposal = create_proposer(settings).propose(schema, columns)
    checks = check_mapping(proposal, frame, schema, sample_size=sample_size)
    return ProposalReport(
        provider=settings.provider,
        model=settings.model if settings.provider == "openai" else None,
        mapping=proposal,
        checks=checks,
    )

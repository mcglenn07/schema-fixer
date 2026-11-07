"""Session orchestration for the local demo; validation stays in shared functions."""

import atexit
import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp
from uuid import uuid4

import pandas as pd
import yaml

from schema_fixer.application import ApplyReport, apply_file
from schema_fixer.approval import ChecksFailed, save_approved, schema_hash
from schema_fixer.config import load_settings
from schema_fixer.detector import inspect_file
from schema_fixer.io import InputError, load_schema, read_table
from schema_fixer.models import InspectionReport, TargetSchema
from schema_fixer.proposals import ProposalReport, propose_file
from schema_fixer.providers import ProviderError

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = {
    "Customers": "customer.yaml",
    "Orders": "order.yaml",
    "Support tickets": "support_ticket.yaml",
}
SAMPLES = [
    ("Customer headers & extras", "customers.csv", "Customers"),
    ("Order headers & numbers", "orders.csv", "Orders"),
    ("Tickets with bad rows", "tickets.json", "Support tickets"),
    ("Split names & US dates", "customers-split.csv", "Customers"),
]
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def available_providers() -> list[str]:
    """Read availability only. Do not construct a client or expose a key."""
    try:
        key = load_settings("openai").api_key
    except ProviderError:
        key = None
    return ["baseline", "openai"] if key and key.strip() else ["baseline"]


@dataclass
class Review:
    directory: Path
    source: Path
    source_sha256: str
    schema_name: str
    provider: str
    frame: pd.DataFrame
    schema: TargetSchema
    inspection: InspectionReport
    proposal: ProposalReport | None = None

    @property
    def data_path(self) -> Path:
        return self.directory / f"incoming{self.source.suffix.lower()}"

    @property
    def schema_path(self) -> Path:
        return self.directory / "schema.yaml"


@dataclass
class DemoSession:
    directory: Path | None = None
    review: Review | None = None


def cleanup_session(session: DemoSession) -> None:
    if session.directory is not None:
        shutil.rmtree(session.directory, ignore_errors=True)
    session.directory = None
    session.review = None


def invalidate(session: DemoSession) -> None:
    # Retain already issued downloads until session expiry, but never reuse a draft.
    session.review = None


class DemoWorkflow:
    def __init__(self, root: Path = ROOT):
        self.root = root

    def schema_path(self, name: str) -> Path:
        if name not in SCHEMAS:
            raise InputError("Choose one of the available target schemas.")
        return self.root / "schemas" / SCHEMAS[name]

    def sample(self, index: int) -> tuple[str, str]:
        _, filename, schema = SAMPLES[index]
        return str(self.root / "examples" / "demo" / filename), schema

    def inspect(
        self, file: str | None, schema_name: str, provider: str, session: DemoSession
    ) -> Review:
        invalidate(session)
        if not file:
            raise InputError("Upload a CSV or JSON file, or load a sample first.")
        if provider not in available_providers():
            raise InputError("That provider is not available. Choose baseline.")
        source = Path(file)
        if source.suffix.lower() not in {".csv", ".json"}:
            raise InputError("Upload a .csv or flat .json file.")
        if source.stat().st_size > MAX_UPLOAD_BYTES:
            raise InputError("The local demo accepts files up to 10 MiB.")
        contents = source.read_bytes()
        if len(contents) > MAX_UPLOAD_BYTES:
            raise InputError("The local demo accepts files up to 10 MiB.")
        target = load_schema(self.schema_path(schema_name))
        if session.directory is None:
            session.directory = Path(mkdtemp(prefix="schema-fixer-demo-"))
            atexit.register(shutil.rmtree, session.directory, ignore_errors=True)
        directory = session.directory / uuid4().hex
        directory.mkdir(mode=0o700)
        data_path = directory / f"incoming{source.suffix.lower()}"
        data_path.write_bytes(contents)
        target_path = directory / "schema.yaml"
        target_path.write_text(
            yaml.safe_dump(target.model_dump(mode="json"), sort_keys=False)
        )
        inspection = inspect_file(data_path, target_path)
        review = Review(
            directory,
            source.resolve(),
            hashlib.sha256(contents).hexdigest(),
            schema_name,
            provider,
            read_table(data_path),
            target,
            inspection,
        )
        session.review = review
        return review

    def propose(self, session: DemoSession) -> ProposalReport:
        review = session.review
        if review is None:
            raise InputError("Inspect the file before requesting a mapping.")
        proposal = propose_file(
            review.data_path, review.schema_path, provider=review.provider
        )
        review.proposal = proposal
        return proposal

    def approve(
        self, file: str | None, schema_name: str, provider: str, session: DemoSession
    ) -> ApplyReport:
        review = session.review
        if review is None or review.proposal is None:
            raise InputError("Inspect and review a proposed mapping before approving.")
        # Consume the review even if a check fails. A repeated click cannot apply it twice.
        invalidate(session)
        if (
            not file
            or Path(file).resolve() != review.source
            or schema_name != review.schema_name
            or provider != review.provider
            or hashlib.sha256(Path(file).read_bytes()).hexdigest()
            != review.source_sha256
            or schema_hash(load_schema(self.schema_path(schema_name)))
            != schema_hash(review.schema)
        ):
            raise InputError("Inputs changed after review. Inspect and propose again.")
        if not review.proposal.checks.passed:
            raise ChecksFailed(review.proposal.checks)
        mapping_path = review.directory / "approved.yaml"
        save_approved(
            review.proposal.mapping,
            review.data_path,
            review.schema_path,
            mapping_path,
            reviewed_frame=review.frame,
            reviewed_schema=review.schema,
        )
        return apply_file(
            review.data_path, mapping_path, review.directory / "clean.csv"
        )

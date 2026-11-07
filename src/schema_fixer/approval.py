"""Persist checked human decisions, bound to a schema and source columns."""

import hashlib
import json
import os
import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import pandas as pd
import yaml
from pydantic import Field, ValidationError, model_validator

from schema_fixer.checker import CheckResult, check_mapping
from schema_fixer.io import InputError, UniqueSafeLoader, load_schema, read_table
from schema_fixer.mapping import Contract, Mapping
from schema_fixer.models import TargetSchema
from schema_fixer.output import write_new_files


def fingerprint(value: dict) -> str:
    canonical = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def schema_hash(schema: TargetSchema) -> str:
    return fingerprint(schema.model_dump(mode="json"))


class ApprovedMapping(Contract):
    version: Literal[1] = 1
    status: Literal["approved"] = "approved"
    approved_at: str = Field(min_length=1)
    schema_path: str = Field(min_length=1)
    schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_columns: list[str] = Field(min_length=1)
    mapping: Mapping
    approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def consistent(self):
        if len(set(self.source_columns)) != len(self.source_columns):
            raise ValueError("Source columns must be unique")
        if (
            fingerprint(self.model_dump(mode="json", exclude={"approval_sha256"}))
            != self.approval_sha256
        ):
            raise ValueError("Approval was modified; approve it again")
        return self


class ChecksFailed(InputError):
    def __init__(self, checks: CheckResult):
        super().__init__("Mapping checks failed. Review the mapping before continuing.")
        self.checks = checks


def parse_draft(text: str) -> Mapping:
    try:
        payload = yaml.load(text, Loader=UniqueSafeLoader)
        # A propose report or saved approval can be reviewed again, but its
        # previous checks/status never grant approval to the imported mapping.
        if isinstance(payload, dict) and "mapping" in payload:
            payload = payload["mapping"]
        return Mapping.model_validate(payload)
    except (yaml.YAMLError, ValidationError, ValueError, TypeError) as exc:
        raise InputError(
            "Invalid mapping YAML or transform contract. Fix the draft and recheck."
        ) from exc


def read_draft(path: Path) -> Mapping:
    try:
        return parse_draft(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise InputError("Cannot read the mapping draft as UTF-8.") from exc


def edit_yaml(text: str) -> str:
    """Use the user's editor with argv, never an interpolated shell command."""
    try:
        editor = shlex.split(
            os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
        )
        with TemporaryDirectory(prefix="schema-fixer-edit-") as directory:
            path = Path(directory) / "mapping.yaml"
            path.write_text(text, encoding="utf-8")
            if (
                not editor
                or subprocess.run([*editor, str(path)], check=False).returncode
            ):
                raise InputError("Editor failed. Set VISUAL or EDITOR and try again.")
            return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        raise InputError("Cannot edit mapping. Check VISUAL or EDITOR.") from exc


def save_approved(
    mapping: Mapping,
    data_path: Path,
    schema_path: Path,
    destination: Path,
    *,
    reviewed_frame: pd.DataFrame,
    reviewed_schema: TargetSchema,
    sample_size: int = 20,
) -> ApprovedMapping:
    """Called only after explicit CLI acceptance; recheck the reviewed inputs."""
    frame, schema = read_table(data_path), load_schema(schema_path)
    if not frame.equals(reviewed_frame) or schema_hash(schema) != schema_hash(
        reviewed_schema
    ):
        raise InputError("Input or schema changed during review. Restart approval.")
    checks = check_mapping(mapping, frame, schema, sample_size=sample_size)
    if not checks.passed:
        raise ChecksFailed(checks)
    payload = {
        "version": 1,
        "status": "approved",
        "approved_at": datetime.now(UTC).isoformat(),
        "schema_path": os.path.relpath(
            schema_path.resolve(), destination.resolve().parent
        ),
        "schema_sha256": schema_hash(schema),
        "source_columns": list(frame.columns),
        "mapping": mapping.model_dump(mode="json"),
    }
    approved = ApprovedMapping.model_validate(
        {**payload, "approval_sha256": fingerprint(payload)}
    )
    write_new_files(
        {
            destination: yaml.safe_dump(
                approved.model_dump(mode="json"), sort_keys=False, allow_unicode=True
            )
        }
    )
    return approved


def load_approved(path: Path) -> tuple[ApprovedMapping, TargetSchema, Path]:
    try:
        payload = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueSafeLoader)
        approved = ApprovedMapping.model_validate(payload)
    except (
        OSError,
        UnicodeError,
        yaml.YAMLError,
        ValidationError,
        ValueError,
        TypeError,
    ) as exc:
        raise InputError(
            "Invalid or modified approved mapping. Review and approve it again."
        ) from exc
    schema_path = (path.resolve().parent / approved.schema_path).resolve()
    schema = load_schema(schema_path)
    if schema_hash(schema) != approved.schema_sha256:
        raise InputError(
            "Target schema changed since approval. Review and approve the mapping again."
        )
    return approved, schema, schema_path

"""Providers accept schemas and masked profiles, never full input tables."""

from typing import Protocol

from schema_fixer.mapping import Mapping
from schema_fixer.models import ColumnProfile, TargetSchema


class ProviderError(ValueError):
    """A provider did not return a usable proposal."""


class Proposer(Protocol):
    def propose(
        self, schema: TargetSchema, columns: list[ColumnProfile]
    ) -> Mapping: ...

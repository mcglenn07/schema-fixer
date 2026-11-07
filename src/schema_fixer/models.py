"""Small, serializable contracts for M1 inspection."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DataType = Literal["string", "integer", "number", "boolean", "date"]
IssueCode = Literal[
    "missing_required",
    "missing_optional",
    "extra_column",
    "likely_rename",
    "type_mismatch",
    "enum_drift",
    "format_mismatch",
    "null_required",
]
# Listed so nothing is silently unmapped, but never a failure on its own.
INFO_CODES: frozenset[str] = frozenset({"missing_optional"})


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FieldSpec(StrictModel):
    type: DataType
    required: bool = False
    enum: list[str] | None = None
    format: Literal["email", "phone"] | None = None

    @model_validator(mode="after")
    def constraints_match_type(self) -> Self:
        if (self.enum is not None or self.format is not None) and self.type != "string":
            raise ValueError("enum and format constraints require type: string")
        if self.enum is not None and (
            not self.enum or len(self.enum) != len(set(self.enum))
        ):
            raise ValueError("enum must contain distinct values and cannot be empty")
        return self


class TargetSchema(StrictModel):
    name: str = Field(min_length=1)
    fields: dict[str, FieldSpec] = Field(min_length=1)

    @field_validator("fields")
    @classmethod
    def valid_names(cls, fields: dict[str, FieldSpec]) -> dict[str, FieldSpec]:
        if any(not name.strip() or name != name.strip() for name in fields):
            raise ValueError("field names must be nonblank with no surrounding spaces")
        return fields


class ColumnProfile(StrictModel):
    name: str
    inferred_type: str
    null_percent: float
    samples: list[str] = Field(max_length=3)


class FileProfile(StrictModel):
    row_count: int
    columns: list[ColumnProfile]


class Finding(StrictModel):
    code: IssueCode
    field: str | None = None
    source: str | None = None
    message: str
    count: int = 0
    rows: list[int] = Field(default_factory=list)
    samples: list[str] = Field(default_factory=list, max_length=3)
    similarity: float | None = None
    tentative: bool = False


class InspectionReport(StrictModel):
    schema_name: str
    profile: FileProfile
    findings: list[Finding]

"""The fixed mapping vocabulary, also used as the structured-output schema."""

from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from schema_fixer.models import StrictModel

Scalar = str | int | float | bool | None
Confidence = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class Contract(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Rename(Contract):
    name: Literal["rename"]


class Combine(Contract):
    name: Literal["combine"]
    separator: str


class Split(Contract):
    name: Literal["split"]
    separator: str = Field(min_length=1)
    index: int = Field(ge=0)


class ParseDate(Contract):
    name: Literal["parse_date"]
    format: str = Field(min_length=1)


class ValuePair(Contract):
    source: str
    target: Scalar


class MapValues(Contract):
    name: Literal["map_values"]
    # A list of pairs represents a dictionary without open-ended JSON object keys.
    values: list[ValuePair] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_keys(self) -> Self:
        if len({pair.source for pair in self.values}) != len(self.values):
            raise ValueError("map_values source labels must be unique")
        return self


class Cast(Contract):
    name: Literal["cast"]
    type: Literal["string", "integer", "number", "boolean"]


class Constant(Contract):
    name: Literal["constant"]
    value: Scalar


class Drop(Contract):
    name: Literal["drop"]


Transform = Rename | Combine | Split | ParseDate | MapValues | Cast | Constant


class FieldMapping(Contract):
    target: str = Field(min_length=1)
    sources: list[str]
    transform: Transform
    confidence: Confidence
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def source_count(self) -> Self:
        count = len(self.sources)
        name = self.transform.name
        if len(set(self.sources)) != count or any(not s for s in self.sources):
            raise ValueError("sources must be nonempty names without duplicates")
        if name == "constant" and count != 0:
            raise ValueError("constant takes no sources")
        if name == "combine" and count < 2:
            raise ValueError("combine requires at least two sources")
        if name not in {"constant", "combine"} and count != 1:
            raise ValueError("this transform requires one source")
        return self


class DroppedColumn(Contract):
    sources: list[str] = Field(min_length=1)
    transform: Drop
    confidence: Confidence
    reason: str = Field(min_length=1)


class Mapping(Contract):
    fields: list[FieldMapping]
    drop: list[DroppedColumn]
    unmapped_required: list[str]
    unmapped_optional: list[str]

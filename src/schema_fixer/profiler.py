"""Deterministic type summaries and masked samples, with no provider calls."""

import math
import re
from datetime import date
from numbers import Integral, Real

import pandas as pd

from schema_fixer.models import ColumnProfile, FileProfile

EMAIL = re.compile(r"[^\s@,;<>]+@[^\s@,;<>]+")
PHONE = re.compile(r"(?<!\w)(?:\+?\d|\(\d)[\d(). \-]{5,}\d(?!\w)")
INTEGER = re.compile(r"[+-]?\d+")
NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
DATE_SAMPLE = re.compile(
    r"(?:\d{4}[-.]\d{1,2}[-.]\d{1,2}|\d{1,2}[-.]\d{1,2}[-.]\d{2,4})"
)


def is_null(value: object) -> bool:
    return (
        value is None
        or (isinstance(value, str) and not value.strip())
        or bool(pd.isna(value))
    )


def is_iso_date(value: object) -> bool:
    if not isinstance(value, str) or not ISO_DATE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def value_type(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, Integral):
        return "integer"
    if isinstance(value, Real):
        return "number" if math.isfinite(value) else "string"
    if not isinstance(value, str):
        return "string"
    if value.casefold() in {"true", "false"}:
        return "boolean"
    if INTEGER.fullmatch(value):
        return "integer"
    if NUMBER.fullmatch(value):
        try:
            if math.isfinite(float(value)):
                return "number"
        except (ValueError, OverflowError):
            pass
    if is_iso_date(value):
        return "date"
    return "string"


def mask_sample(value: object, column: str = "") -> str:
    text = str(value)
    name = re.sub(r"[^a-z]", "", column.casefold())
    if "email" in name:
        return "[EMAIL]"
    if any(token in name for token in ("phone", "mobile", "telephone", "telnumber")):
        return "[PHONE]"
    text = EMAIL.sub("[EMAIL]", text)

    def phone_replacement(match: re.Match) -> str:
        candidate = match.group().strip()
        # Preserve recognizable date representations, including invalid dates,
        # so later proposals can see the source format without seeing phone numbers.
        if DATE_SAMPLE.fullmatch(candidate):
            return match.group()
        digits = sum(char.isdigit() for char in candidate)
        return "[PHONE]" if 7 <= digits <= 15 else match.group()

    text = PHONE.sub(phone_replacement, text)
    return text if len(text) <= 120 else text[:117] + "..."


def sample_values(values, column: str) -> list[str]:
    # Select distinct raw samples before masking; never retain raw values in profiles.
    seen = set()
    samples = []
    for value in values:
        if is_null(value):
            continue
        key = (type(value).__name__, str(value))
        if key in seen:
            continue
        seen.add(key)
        samples.append(mask_sample(value, column))
        if len(samples) == 3:
            break
    return samples


def profile_table(frame: pd.DataFrame) -> FileProfile:
    profiles = []
    for name in frame.columns:
        values = frame[name].tolist()
        non_null = [value for value in values if not is_null(value)]
        types = {value_type(value) for value in non_null}
        if not types:
            inferred = "unknown"
        elif types <= {"integer", "number"}:
            inferred = "number" if "number" in types else "integer"
        else:
            inferred = next(iter(types)) if len(types) == 1 else "mixed"
        profiles.append(
            ColumnProfile(
                name=name,
                inferred_type=inferred,
                null_percent=round(100 * (len(values) - len(non_null)) / len(values), 2)
                if values
                else 0.0,
                samples=sample_values(non_null, name),
            )
        )
    return FileProfile(row_count=len(frame), columns=profiles)

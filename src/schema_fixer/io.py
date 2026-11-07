"""Read tabular inputs without silently repairing malformed records."""

import csv
import json
from io import StringIO
from pathlib import Path

import pandas as pd
import yaml
from pydantic import ValidationError

from schema_fixer.models import TargetSchema


class InputError(ValueError):
    """An input cannot safely be interpreted as the requested table or schema."""


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError("Duplicate keys are not allowed.")
        result[key] = value
    return result


class UniqueSafeLoader(yaml.SafeLoader):
    pass


def _yaml_mapping(loader, node):
    return _unique_pairs(loader.construct_pairs(node, deep=True))


UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _yaml_mapping
)


def load_schema(path: Path | str) -> TargetSchema:
    try:
        data = yaml.load(
            Path(path).read_text(encoding="utf-8"), Loader=UniqueSafeLoader
        )
        return TargetSchema.model_validate(data)
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError, TypeError) as exc:
        raise InputError(
            f"Cannot load target schema {path}: invalid schema or YAML."
        ) from exc


def _check_headers(headers: list[str]) -> None:
    if not headers or any(not name.strip() for name in headers):
        raise InputError("A table must have nonblank column names.")
    if len(set(headers)) != len(headers):
        raise InputError("Duplicate column names are not allowed.")


def _read_csv(text: str) -> pd.DataFrame:
    # pandas otherwise renames duplicate headers or infers an index on extra cells.
    try:
        reader = csv.reader(StringIO(text), strict=True)
        headers = next(reader, [])
        _check_headers(headers)
        for position, row in enumerate(reader, start=1):
            if len(row) != len(headers):
                raise InputError(
                    f"CSV data row {position} has the wrong number of cells."
                )
        return pd.read_csv(
            StringIO(text),
            dtype=object,
            keep_default_na=False,
            na_filter=False,
            skip_blank_lines=False,
        )
    except (csv.Error, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise InputError(
            "Cannot parse CSV. Check quoting, headers and row widths."
        ) from exc


def _invalid_constant(value: str):
    raise InputError("JSON must not contain NaN or Infinity.")


def _read_json(text: str) -> pd.DataFrame:
    try:
        records = json.loads(
            text, object_pairs_hook=_unique_pairs, parse_constant=_invalid_constant
        )
    except json.JSONDecodeError as exc:
        raise InputError("JSON must be an array of flat objects.") from exc
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise InputError("JSON must be an array of flat objects.")
    if not records:
        return pd.DataFrame()
    if any(isinstance(v, (list, dict)) for row in records for v in row.values()):
        raise InputError("Nested JSON values are not supported; use flat records.")
    # Keep native scalars and numeric strings distinct. No date or numeric coercion.
    frame = pd.DataFrame(records, dtype=object)
    _check_headers(list(frame.columns))
    return frame


def read_table(path: Path | str) -> pd.DataFrame:
    path = Path(path)
    if path.suffix.lower() not in {".csv", ".json"}:
        raise InputError(
            "Supported inputs are .csv and .json (an array of flat objects)."
        )
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise InputError(f"Cannot read UTF-8 input {path}.") from exc
    return _read_csv(text) if path.suffix.lower() == ".csv" else _read_json(text)

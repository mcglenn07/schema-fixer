"""Fixed, local transforms shared by checks and apply. No file or code execution."""

import math
from datetime import datetime

from schema_fixer.mapping import FieldMapping
from schema_fixer.profiler import is_null, value_type


def cast_value(value: object, target: str) -> object:
    if is_null(value):
        return None
    if target == "string":
        return str(value)
    if target == "integer":
        if isinstance(value, bool):
            raise ValueError("true/false is not a whole number")
        if value_type(value) == "integer":
            return int(value)
        if isinstance(value, float) and math.isfinite(value) and value.is_integer():
            return int(value)
        raise ValueError("not a whole number")
    if target == "number":
        if value_type(value) not in {"integer", "number"}:
            raise ValueError("not a number")
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("not a finite number")
        return result
    if target == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.casefold() in {"true", "false"}:
            return value.casefold() == "true"
        raise ValueError("not true or false")
    raise ValueError("Unknown cast type")


def transform_field(entry: FieldMapping, row: dict) -> object:
    transform = entry.transform
    if transform.name == "constant":
        return transform.value
    values = [row[source] for source in entry.sources]
    if any(is_null(value) for value in values):
        return None
    value = values[0]
    match transform.name:
        case "rename":
            return value
        case "combine":
            if not all(isinstance(v, str) for v in values):
                raise ValueError("combine requires text sources")
            return transform.separator.join(values)
        case "split":
            if not isinstance(value, str):
                raise TypeError("split requires text")
            return value.split(transform.separator)[transform.index]
        case "parse_date":
            return datetime.strptime(value, transform.format).date().isoformat()
        case "map_values":
            for pair in transform.values:
                if isinstance(value, str) and value == pair.source:
                    return pair.target
            return value
        case "cast":
            return cast_value(value, transform.type)
    raise ValueError("Transform is not allowed")

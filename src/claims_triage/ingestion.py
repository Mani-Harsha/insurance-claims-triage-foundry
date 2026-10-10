"""Bounded file ingestion; row validation belongs to the intake specialist."""

import csv
import io
import json
from decimal import Decimal
from typing import Any

from .domain import FIELDS, AppError

MAX_BYTES = 1_048_576
MAX_CLAIMS = 100


def reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON number")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def validate_batch(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_CLAIMS:
        raise AppError("invalid_batch", f"Expected between 1 and {MAX_CLAIMS} claim objects.")
    if any(not isinstance(row, dict) for row in rows):
        raise AppError("invalid_batch", "Every claim row must be an object.")
    try:
        encoded = json.dumps(rows, default=str, allow_nan=False).encode()
    except (ValueError, TypeError) as exc:
        raise AppError("invalid_batch", "Claims must contain finite JSON values.") from exc
    if len(encoded) > MAX_BYTES:
        raise AppError("input_too_large", "Batch exceeds the one MiB limit.", 413)
    return rows


def parse_claims(content: bytes, format: str) -> list[dict[str, Any]]:
    if len(content) > MAX_BYTES:
        raise AppError("input_too_large", "File exceeds the one MiB limit.", 413)
    try:
        text = content.decode("utf-8-sig")
        if format == "json":
            rows = json.loads(
                text, parse_float=Decimal, parse_constant=reject_constant, object_pairs_hook=unique_object
            )
        elif format == "csv":
            reader = csv.DictReader(io.StringIO(text), strict=True)
            if (
                not reader.fieldnames
                or len(set(reader.fieldnames)) != len(reader.fieldnames)
                or set(reader.fieldnames) != set(FIELDS)
            ):
                raise ValueError("CSV requires unique headers matching the seven claim fields")
            rows = []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("CSV row width differs from headers")
                rows.append(row)
                if len(rows) > MAX_CLAIMS:
                    raise ValueError("Too many claims")
        else:
            raise ValueError("Unsupported format")
        return validate_batch(rows)
    except (ValueError, UnicodeError, csv.Error, RecursionError) as exc:
        raise AppError(
            "malformed_input", "Provide a valid UTF-8 JSON array or seven-column CSV within the batch limits."
        ) from exc

import json
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("claims_triage")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": record.levelname,
                "event": record.getMessage(),
                **getattr(record, "fields", {}),
            }
        )


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logging.getLogger("azure").setLevel(logging.WARNING)


def log(event: str, **fields: Any) -> None:
    # Callers pass identifiers/metadata only, never claim descriptions or credentials.
    logger.info(event, extra={"fields": fields})

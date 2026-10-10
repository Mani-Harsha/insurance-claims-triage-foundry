"""CLI suitable for a reproducible screen-share demonstration."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .bootstrap import create_service
from .config import Settings
from .domain import AppError
from .ingestion import MAX_BYTES, parse_claims
from .observability import configure_logging, log


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthetic four-agent insurance claims triage")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Initialize storage and return a new conversation session")
    triage = commands.add_parser("triage", help="Triage a synthetic JSON/CSV batch")
    triage.add_argument("file", type=Path)
    triage.add_argument("--synthetic", action="store_true", required=True)
    triage.add_argument("--session")
    chat = commands.add_parser("chat")
    chat.add_argument("session")
    chat.add_argument("message")
    review = commands.add_parser("review")
    review.add_argument("session")
    review.add_argument("batch")
    review.add_argument("row", type=int)
    review.add_argument("decision", choices=["approve", "investigate", "request_documentation"])
    review.add_argument("--note", required=True)
    show = commands.add_parser("show")
    show.add_argument("session")
    show.add_argument("batch")
    commands.add_parser(
        "provision", help="Create/resume four Foundry agents using the configured Azure project"
    )
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    configure_logging()
    service = None
    try:
        settings = Settings()
        if args.command == "serve":
            import uvicorn

            from .api import create_app

            uvicorn.run(create_app(settings), host=args.host, port=args.port, workers=1)
            return 0
        service = create_service(settings)
        if args.command == "init":
            result = {"session_id": service.repo.create_session(), "mode": settings.mode, "synthetic": True}
        elif args.command == "triage":
            with args.file.open("rb") as stream:
                rows = parse_claims(stream.read(MAX_BYTES + 1), args.file.suffix.lower().lstrip("."))
            session = args.session or service.repo.create_session()
            result = service.triage(session, rows, args.synthetic)
        elif args.command == "chat":
            result = service.chat(args.session, args.message)
        elif args.command == "review":
            result = service.review(args.session, args.batch, args.row, args.decision, args.note)
        elif args.command == "show":
            result = service.repo.batch(args.session, args.batch)
        else:
            from .azure_runtime import AzureRuntime

            if not isinstance(service.runtime, AzureRuntime):
                raise AppError(
                    "azure_mode_required",
                    "Set TRIAGE_MODE=azure and configure a project/model before provisioning.",
                )
            result = service.runtime.provision()
        print(json.dumps(result, indent=2, ensure_ascii=True, default=str))
        return 0
    except AppError as exc:
        print(json.dumps({"error": {"code": exc.code, "message": exc.message}}), file=sys.stderr)
        return 1
    except (OSError, ValidationError) as exc:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "configuration_or_file_error",
                        "message": "Check configuration and input file access.",
                        "type": type(exc).__name__,
                    }
                }
            ),
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        log("command_failed", error_type=type(exc).__name__)
        print(
            json.dumps(
                {"error": {"code": "internal_error", "message": "Command failed. Consult the service logs."}}
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        if service:
            service.runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())

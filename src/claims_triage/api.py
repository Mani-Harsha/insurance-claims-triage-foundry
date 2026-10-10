"""Authenticated single-tenant API. CLI access is secured by local OS permissions."""

import json
import secrets
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import Body, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .bootstrap import create_service
from .config import Settings
from .domain import AppError
from .ingestion import MAX_BYTES, parse_claims, reject_constant, unique_object
from .observability import configure_logging, log
from .service import TriageService
from .tools import ROLE_TOOLS, TOOLS

SHOWCASE_CLAIMS = [
    {"claim_id": "C-2031", "policy_number": "POL-5521", "claim_type": "water_damage", "loss_date": "2026-08-15", "report_date": "2026-08-16", "claim_amount": 8500, "description": "Pipe burst in kitchen"},
    {"claim_id": "C-2032", "policy_number": "POL-5521", "claim_type": "water_damage", "loss_date": "2026-02-10", "report_date": "2026-02-12", "claim_amount": 4200, "description": "Basement flooding"},
    {"claim_id": "C-2033", "policy_number": "POL-9981", "claim_type": "theft", "loss_date": "2026-08-30", "report_date": "2026-08-30", "claim_amount": 25000, "description": "Jewelry theft, filed 3 days after policy start"},
    {"claim_id": "C-2034", "policy_number": "POL-4410", "claim_type": "fire", "loss_date": "", "report_date": "2026-08-20", "claim_amount": 0, "description": "Missing loss date and amount - flag"},
]
BATCH_EXAMPLES = {
    "starter": {"summary": "Four synthetic claims: history, clean coverage, anomalies, invalid intake", "value": {"synthetic": True, "claims": SHOWCASE_CLAIMS}}
}
CHAT_EXAMPLES = {
    "explain": {"summary": "Supervisor routes to briefing and stored evidence", "value": {"message": "Why was claim C2031 flagged?"}},
    "followup": {"summary": "Follow-up using conversation memory", "value": {"message": "Explain its recommendation"}},
    "triage": {"summary": "Supervisor routes a new batch through all specialists", "value": {"message": "Triage this batch of claims", "synthetic": True, "claims": SHOWCASE_CLAIMS}},
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BatchRequest(StrictModel):
    synthetic: StrictBool
    claims: list[dict[str, Any]] = Field(min_length=1, max_length=100)


class ChatRequest(StrictModel):
    message: str = Field(min_length=1, max_length=2000)
    claims: list[dict[str, Any]] | None = Field(default=None, min_length=1, max_length=100)
    synthetic: StrictBool = False


class ReviewRequest(StrictModel):
    decision: Literal["approve", "investigate", "request_documentation"]
    note: str = Field(min_length=3, max_length=2000)


class BoundedBody:
    """Enforce size while reading even without Content-Length; reject ambiguous JSON."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > MAX_BYTES:
                await JSONResponse(
                    {"error": {"code": "input_too_large", "message": "Request exceeds one MiB."}}, 413
                )(scope, receive, send)
                return
            chunks.append(body)
            if not message.get("more_body", False):
                break
        content = b"".join(chunks)
        headers = dict(scope.get("headers", []))
        if content and b"application/json" in headers.get(b"content-type", b""):
            try:
                json.loads(content, parse_constant=reject_constant, object_pairs_hook=unique_object)
            except (ValueError, UnicodeError, RecursionError):
                await JSONResponse(
                    {"error": {"code": "malformed_input", "message": "Malformed or ambiguous JSON."}}, 400
                )(scope, receive, send)
                return
        delivered = False

        async def buffered_receive() -> Any:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": content, "more_body": False}
            return await receive()

        await self.app(scope, buffered_receive, send)


def create_app(settings: Settings | None = None, service: TriageService | None = None) -> FastAPI:
    config = settings or Settings()
    token = config.api_token.get_secret_value()
    if len(token) < 24:
        raise AppError(
            "api_token_required",
            "Set TRIAGE_API_TOKEN to a random token of at least 24 characters before serving.",
            503,
        )
    configure_logging()
    triage = service or create_service(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        triage.runtime.close()

    app = FastAPI(
        title="Synthetic Claims Triage",
        version="1.0.0",
        lifespan=lifespan,
        description=(
            "Single-tenant synthetic claims assistant. All recommendations require a human decision.\n\n"
            "## End-to-end showcase\n"
            "1. Authorize with the server's bearer token.\n"
            "2. POST /sessions and copy session_id.\n"
            "3. POST /sessions/{session_id}/batches using the starter example; copy the returned id as batch_id.\n"
            "4. POST /sessions/{session_id}/chat with the explanation, then follow-up example.\n"
            "5. Review rows 0/1/2/3 as investigate/approve/investigate/request_documentation.\n"
            "6. GET the batch again: state becomes REVIEWED after all four decisions.\n\n"
            "## Agent functions\n"
            + "\n".join(
                f"- **{role}**: " + "; ".join(f"`{name}` — {TOOLS[name]['description']}" for name in names)
                for role, names in ROLE_TOOLS.items()
            )
            + "\n\nThese are internal, context-bound tools invoked by the workflow. "
            "Coverage retrieves rules inside check_coverage; search_knowledge is an additional registered tool. "
            "Mock mode executes local tools and persistence; it does not prove Azure inference or hosted file search. "
            "Use a new session for each independent batch demo to avoid duplicate flags."
        ),
    )
    app.add_middleware(BoundedBody)
    app.state.service = triage
    bearer = HTTPBearer(auto_error=False)

    def authenticate(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> str:
        if credentials is None or not secrets.compare_digest(
            credentials.credentials.encode(), token.encode()
        ):
            raise AppError("unauthorized", "A valid bearer token is required.", 401)
        return "api-adjuster"

    auth = [Depends(authenticate)]

    @app.exception_handler(AppError)
    async def application_error(request: Request, exc: AppError):
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}},
            status_code=exc.status,
            headers={"WWW-Authenticate": "Bearer"} if exc.status == 401 else None,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_request",
                    "message": "Request shape or parameter validation failed.",
                    "fields": [list(error["loc"]) for error in exc.errors()],
                }
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        log("request_failed", error_type=type(exc).__name__)
        return JSONResponse(
            {"error": {"code": "internal_error", "message": "Request failed. Consult the service logs."}},
            status_code=500,
        )

    @app.get("/health", tags=["Operations"])
    def health():
        return {"status": "ok", "mode": config.mode, "synthetic": True}

    @app.post("/sessions", status_code=201, dependencies=auth, tags=["Sessions"])
    def create_session():
        return {"session_id": triage.repo.create_session(), "synthetic": True}

    @app.get("/sessions/{session_id}/messages", dependencies=auth, tags=["Sessions"])
    def messages(session_id: str):
        return {"messages": triage.repo.messages(session_id)}

    @app.post("/sessions/{session_id}/batches", status_code=201, dependencies=auth, tags=["Triage"])
    def batch(session_id: str, body: Annotated[BatchRequest, Body(openapi_examples=BATCH_EXAMPLES)]):
        return triage.triage(session_id, body.claims, body.synthetic)

    @app.post(
        "/sessions/{session_id}/uploads", status_code=201, dependencies=auth, tags=["Triage"],
        description="Paste raw JSON or CSV. Match format to the selected media type and set synthetic=true.",
        openapi_extra={"requestBody": {"required": True, "content": {
            "application/json": {"schema": {"type": "array", "items": {"type": "object"}}, "example": SHOWCASE_CLAIMS},
            "text/csv": {"schema": {"type": "string"}, "example": "claim_id,policy_number,claim_type,loss_date,report_date,claim_amount,description\nC-2032,POL-5521,water_damage,2026-02-10,2026-02-12,4200,Basement flooding\n"},
        }}},
    )
    async def upload(
        session_id: str, request: Request, format: Literal["json", "csv"], synthetic: bool = False
    ):
        from starlette.concurrency import run_in_threadpool

        rows = parse_claims(await request.body(), format)
        return await run_in_threadpool(triage.triage, session_id, rows, synthetic)

    @app.get("/sessions/{session_id}/batches", dependencies=auth, tags=["Triage"])
    def list_batches(session_id: str):
        return {"batches": triage.repo.batches(session_id)}

    @app.get("/sessions/{session_id}/batches/{batch_id}", dependencies=auth, tags=["Triage"])
    def get_batch(session_id: str, batch_id: str):
        return triage.repo.batch(session_id, batch_id)

    @app.post("/sessions/{session_id}/chat", dependencies=auth, tags=["Conversation"])
    def chat(session_id: str, body: Annotated[ChatRequest, Body(openapi_examples=CHAT_EXAMPLES)]):
        return triage.chat(session_id, body.message, body.claims, body.synthetic)

    @app.post(
        "/sessions/{session_id}/batches/{batch_id}/reviews/{row_index}", dependencies=auth, tags=["Review"]
    )
    def review(
        session_id: str,
        batch_id: str,
        row_index: int,
        body: Annotated[ReviewRequest, Body(openapi_examples={
            "investigate": {"summary": "Rows 0 and 2: investigate", "value": {"decision": "investigate", "note": "Reviewed synthetic anomaly and history evidence"}},
            "approve": {"summary": "Row 1: clean claim approval", "value": {"decision": "approve", "note": "Reviewed synthetic coverage evidence"}},
            "documentation": {"summary": "Row 3: request missing information", "value": {"decision": "request_documentation", "note": "Please supply the missing loss date and a valid amount"}},
        })],
        reviewer: Annotated[str, Depends(authenticate)],
    ):
        return triage.review(session_id, batch_id, row_index, body.decision, body.note, reviewer)

    return app

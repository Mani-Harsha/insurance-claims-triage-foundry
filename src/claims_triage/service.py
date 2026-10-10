"""Supervisor-owned, inspectable routine. Model responses cannot bypass checkpoints."""

from __future__ import annotations

import re
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import date
from typing import Any

from .domain import AppError, Json, build_brief, check_coverage, route_request, validate_claim
from .ingestion import validate_batch
from .observability import log
from .ports import AgentRuntime, Knowledge, Repository
from .tools import bound_dispatch

ROUTINE = (
    "INTAKE",
    "VALIDATE",
    "VALIDATION_CHECKPOINT",
    "COVERAGE_AND_ANOMALIES",
    "BRIEF",
    "HUMAN_REVIEW_PENDING",
)


class TriageService:
    def __init__(
        self,
        repository: Repository,
        policies: dict[str, Json],
        knowledge: Knowledge,
        runtime: AgentRuntime,
        today: Callable[[], date] = date.today,
    ):
        self.repo, self.policies, self.knowledge, self.runtime, self.today = (
            repository,
            policies,
            knowledge,
            runtime,
            today,
        )

    def _agent(
        self,
        role: str,
        session: str,
        tool: str,
        args: Json,
        operation: Callable[[], Json],
        failures: list[str],
        batch_id: str | None = None,
    ) -> Json:
        dispatch = bound_dispatch(role, tool, args, operation, self.knowledge.search, session, batch_id)
        try:
            reply = self.runtime.invoke(role, session, tool, args, dispatch)
            # Execute/obtain the authoritative cached result even if a custom runtime returns different output.
            result = dispatch(tool, args)
            log("agent_completed", agent=role, session_id=session, batch_id=batch_id, mode=self.runtime.mode)
            if reply.output != result:
                raise AppError("agent_evidence_mismatch", "Agent returned inconsistent evidence.", 503)
            return result
        except Exception as exc:
            code = exc.code if isinstance(exc, AppError) else "agent_failed"
            failures.append(f"{role}:{code}")
            log(
                "agent_failed",
                agent=role,
                session_id=session,
                batch_id=batch_id,
                error_type=type(exc).__name__,
                code=code,
            )
            # Recovery uses real deterministic tools and is explicitly labelled as incomplete agent evidence.
            return operation()

    def triage(self, session: str, rows: list[Json], synthetic: bool) -> Json:
        if synthetic is not True:
            raise AppError("synthetic_required", "Explicitly declare that all submissions are synthetic.")
        validate_batch(rows)
        with self.repo.session_lock(session):
            failures: list[str] = []
            self._agent(
                "supervisor",
                session,
                "route_request",
                {"message": "triage this batch of claims"},
                lambda: route_request("triage this batch of claims"),
                failures,
            )
            self.repo.add_message(session, "user", f"Triage this synthetic batch of {len(rows)} claims.")
            return self._triage(session, rows, failures)

    def _triage(self, session: str, rows: list[Json], supervisor_failures: list[str]) -> Json:
        batch_id = str(uuid.uuid4())
        batch: Json = {
            "id": batch_id,
            "session_id": session,
            "mode": self.runtime.mode,
            "synthetic": True,
            "knowledge_version": self.knowledge.version,
            "state": "INTAKE",
            "results": [],
            "events": [],
        }
        history_to_save: list[Json] = []

        def step(state: str, **detail: Any) -> None:
            batch["state"] = state
            batch["events"].append({"state": state, "detail": detail})
            log("routine_step", session_id=session, batch_id=batch_id, state=state, **detail)

        try:
            step("INTAKE", row_count=len(rows))
            ids = [r.get("claim_id", "").strip() for r in rows if isinstance(r.get("claim_id"), str)]
            duplicates = {k for k, n in Counter(ids).items() if n > 1} | self.repo.seen_ids(session)
            step("VALIDATE")
            for index, raw in enumerate(rows):
                self.repo.renew_lease(session)
                failures = list(supervisor_failures)

                def intake_operation(raw: Json = raw) -> Json:
                    return validate_claim(raw, self.policies, duplicates, self.today()).to_dict()

                intake = self._agent(
                    "intake",
                    session,
                    "validate_claim",
                    {"row_index": index},
                    intake_operation,
                    failures,
                    batch_id,
                )
                raw_id = raw.get("claim_id")
                claim_id = (
                    raw_id.strip()
                    if isinstance(raw_id, str) and re.fullmatch(r"C-\d{1,20}", raw_id.strip())
                    else f"row-{index}"
                )
                batch["results"].append(
                    {
                        "row_index": index,
                        "claim_id": claim_id,
                        "intake": intake,
                        "coverage": {
                            "status": "skipped_invalid_intake",
                            "issues": [],
                            "citations": [],
                            "history": [],
                        },
                        "service_issues": failures,
                    }
                )
            step(
                "VALIDATION_CHECKPOINT",
                valid=sum(r["intake"]["valid"] for r in batch["results"]),
                invalid=sum(not r["intake"]["valid"] for r in batch["results"]),
            )
            step("COVERAGE_AND_ANOMALIES")
            valid_rows = sorted(
                (r for r in batch["results"] if r["intake"]["valid"]),
                key=lambda r: (r["intake"]["claim"]["loss_date"], r["row_index"]),
            )
            for row in valid_rows:
                self.repo.renew_lease(session)
                claim = row["intake"]["claim"]
                policy = self.policies[claim["policy_number"]]
                history = self.repo.history(claim["policy_number"]) + history_to_save
                # Deduplicate persisted and current-batch history without treating future records as evidence.
                history = list({(h["policy_number"], h["claim_id"]): h for h in history}.values())

                def coverage_operation(
                    claim: Json = claim, policy: Json = policy, history: list[Json] = history
                ) -> Json:
                    return check_coverage(
                        claim, policy, self.knowledge.applicable_rules(claim, policy), history
                    )

                row["coverage"] = self._agent(
                    "coverage",
                    session,
                    "check_coverage",
                    {"row_index": row["row_index"]},
                    coverage_operation,
                    row["service_issues"],
                    batch_id,
                )
                row["coverage"]["status"] = "checked"
                history_to_save.append(
                    {
                        **{k: claim[k] for k in ("claim_id", "policy_number", "claim_type", "loss_date")},
                        "flagged": bool(row["coverage"]["issues"]),
                        "note": "Synthetic triage evidence; not a fraud determination.",
                    }
                )
            step("BRIEF")
            for row in batch["results"]:
                self.repo.renew_lease(session)

                def brief(row: Json = row) -> Json:
                    return build_brief(row["claim_id"], row["intake"], row["coverage"], row["service_issues"])

                row["brief"] = self._agent(
                    "briefing",
                    session,
                    "build_brief",
                    {"row_index": row["row_index"]},
                    brief,
                    row["service_issues"],
                    batch_id,
                )
                # A briefing failure added after initial tool execution must also close the approval path.
                if row["service_issues"]:
                    row["brief"] = brief()
            step("HUMAN_REVIEW_PENDING", requires_human_decision=True)
        except Exception as exc:
            step("FAILED", error_type=type(exc).__name__)
            batch["results"] = []
            self.repo.save_batch(batch, [])
            raise AppError("triage_failed", f"Triage failed safely. Audit batch: {batch_id}.", 503) from exc
        self.repo.save_batch(batch, history_to_save)
        last_claim = batch["results"][-1]["claim_id"]
        self.repo.add_message(
            session,
            "assistant",
            f"Batch {batch_id}: {len(rows)} synthetic claim rows are pending human review.",
            last_claim,
        )
        return batch

    def chat(
        self, session: str, message: str, rows: list[Json] | None = None, synthetic: bool = False
    ) -> Json:
        if not isinstance(message, str) or not message.strip() or len(message) > 2000:
            raise AppError("invalid_message", "Message must contain 1–2000 characters.")
        with self.repo.session_lock(session):
            context = self.repo.session(session)
            failures: list[str] = []
            route = self._agent(
                "supervisor",
                session,
                "route_request",
                {"message": message},
                lambda: route_request(message, context["last_claim_id"]),
                failures,
            )
            if route["intent"] == "triage":
                if synthetic is not True:
                    raise AppError("synthetic_required", "Declare synthetic input before triage.")
                validate_batch(rows)
                self.repo.add_message(session, "user", message)
                return self._triage(session, rows or [], failures)
            self.repo.add_message(session, "user", message)
            if route["intent"] == "explain" and route["claim_id"]:
                evidence = self.repo.claim_results(session, route["claim_id"])
                if not evidence:
                    answer = {
                        "answer": "No evidence for that claim exists in this session.",
                        "claim_id": route["claim_id"],
                        "evidence": [],
                    }
                else:
                    latest = evidence[0]
                    brief_failures = list(latest["service_issues"]) + failures
                    brief = self._agent(
                        "briefing",
                        session,
                        "build_brief",
                        {"row_index": latest["row_index"]},
                        lambda: build_brief(
                            latest["claim_id"], latest["intake"], latest["coverage"], brief_failures
                        ),
                        brief_failures,
                    )
                    if brief_failures:
                        brief = build_brief(
                            latest["claim_id"], latest["intake"], latest["coverage"], brief_failures
                        )
                    failures = brief_failures
                    answer = {
                        "answer": brief["summary"],
                        "recommended_action": brief["recommended_action"],
                        "claim_id": route["claim_id"],
                        "evidence": evidence,
                    }
            else:
                answer = {
                    "answer": "Submit a synthetic batch to triage, or ask 'why was claim C2031 flagged?'. Include a claim ID if no claim is in context."
                }
            answer.update(synthetic=True, service_issues=failures, mode=self.runtime.mode)
            self.repo.add_message(session, "assistant", answer["answer"], route.get("claim_id"))
            return answer

    def review(
        self,
        session: str,
        batch: str,
        row_index: int,
        decision: str,
        note: str,
        reviewer: str = "local-adjuster",
    ) -> Json:
        if decision not in {"approve", "investigate", "request_documentation"}:
            raise AppError("invalid_decision", "Unsupported human decision.")
        if not isinstance(note, str) or not 3 <= len(note.strip()) <= 2000:
            raise AppError("invalid_note", "Review note must contain 3–2000 characters.")
        if type(row_index) is not int or row_index < 0:
            raise AppError("invalid_row", "Row index must be a nonnegative integer.")
        return self.repo.review(session, batch, row_index, decision, note.strip(), reviewer)

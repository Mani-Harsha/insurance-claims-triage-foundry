"""Streamlit frontend. All claim operations use the authenticated FastAPI backend."""

import json
import os
from pathlib import Path

import streamlit as st

from claims_triage.config import Settings
from claims_triage.domain import AppError
from claims_triage.ingestion import MAX_BYTES
from claims_triage.showcase import ShowcaseClient, demonstrated_by_batch, requirement_rows
from claims_triage.tools import ROLE_TOOLS, TOOLS

ROOT = Path(__file__).resolve().parents[1]
ACTION_LABELS = {
    "auto_approve": "Auto approve recommendation",
    "route_to_investigator": "Investigator review",
    "request_more_documentation": "More documentation",
}
PRESETS = {
    "Starter property claims": "claims.json",
    "Auto claims (CSV)": "claims_auto.csv",
    "Validation edge cases": "showcase_validation.json",
    "Coverage edge cases": "showcase_coverage.json",
}


def main():
    st.set_page_config(page_title="Claims triage desk", page_icon="📋", layout="wide")
    st.title("Claims triage desk")
    st.caption("SYNTHETIC CLAIMS ONLY · Four specialist roles · Evidence before decisions")
    st.session_state.setdefault("observed", set())
    st.session_state.setdefault("session_id", "")
    st.session_state.setdefault("active_batch", None)
    st.session_state.setdefault("chat_turns", 0)
    settings = Settings()
    token = settings.api_token.get_secret_value()
    with st.sidebar:
        st.header("Showcase workspace")
        if not token:
            token = st.text_input(
                "API access token", type="password", help="Use the same token as the running API."
            )
        base_url = os.getenv("TRIAGE_API_URL", "http://127.0.0.1:8000")
        st.caption(f"Backend: {base_url}")
        st.link_button("Swagger API showcase", base_url.rstrip("/") + "/docs")
    if not token:
        st.info("Start both services with tools/start-showcase.ps1, or enter the API token in the sidebar.")
        return
    client = ShowcaseClient(base_url, token)
    try:
        health = client.request("GET", "/health")
        st.info(
            "Local mock mode: real validation, retrieval and memory; no LLM calls."
            if health["mode"] == "mock"
            else "Azure mode: review per-claim service issues. Mode alone does not prove successful cloud execution."
        )
        with st.sidebar:
            st.metric("Runtime", health["mode"].upper())
            if st.button("New session", key="new_session", type="primary", width="stretch"):
                st.session_state.session_id = client.request("POST", "/sessions")["session_id"]
                st.session_state.active_batch = None
                st.session_state.chat_turns = 0
                st.session_state.pop("last_answer", None)
                st.session_state.pop("batch_choice", None)
                st.rerun()
            with st.expander("Resume a saved session"):
                with st.form("resume_session"):
                    saved = st.text_input("Session ID", key="resume_id")
                    resume = st.form_submit_button("Resume session")
                if resume:
                    messages = client.request("GET", f"/sessions/{saved.strip()}/messages")["messages"]
                    st.session_state.session_id = saved.strip()
                    st.session_state.active_batch = None
                    st.session_state.pop("last_answer", None)
                    st.session_state.chat_turns = len(messages) // 2
                    st.session_state.pop("batch_choice", None)
                    if messages:
                        st.session_state.observed.add("R23")
                    st.rerun()
            session = st.session_state.session_id
            if session:
                st.caption("Save this ID to resume after restarting")
                st.code(session, language=None)
                batches = client.request("GET", f"/sessions/{session}/batches")["batches"]
                if st.button("Refresh batches", key="refresh_batches"):
                    st.rerun()
                if batches:
                    if "pending_batch" in st.session_state:
                        st.session_state["batch_choice"] = st.session_state.pop("pending_batch")
                    selected = st.selectbox(
                        "Saved batches",
                        [b["id"] for b in batches],
                        format_func=lambda bid: (
                            f"{bid[:8]} · {next(b['state'] for b in batches if b['id'] == bid)}"
                        ),
                        key="batch_choice",
                    )
                    st.session_state.active_batch = client.request(
                        "GET", f"/sessions/{session}/batches/{selected}"
                    )
                st.caption(
                    "New sessions separate conversation. Policy history remains persisted in this demo workspace."
                )
        batch = st.session_state.active_batch
        if batch:
            st.session_state.observed.update(demonstrated_by_batch(batch))
        triage_tab, claims_tab, chat_tab, routine_tab, dashboard_tab = st.tabs(
            [
                "1 · Triage",
                "2 · Claims & review",
                "3 · Conversation",
                "4 · Evidence & routine",
                "5 · Requirements dashboard",
            ]
        )
        with triage_tab:
            st.subheader("Start with a synthetic batch")
            st.write(
                "Upload JSON or CSV, or choose a prepared scenario. Every row receives an adjuster recommendation."
            )
            source = st.radio(
                "Claim source", [*PRESETS, "Upload JSON / CSV"], horizontal=True, key="claim_source"
            )
            content, file_format = b"", "json"
            if source == "Upload JSON / CSV":
                uploaded = st.file_uploader(
                    "Synthetic claim file · maximum 1 MiB / 100 rows", type=["json", "csv"], key="claim_file"
                )
                if uploaded:
                    content = uploaded.getvalue()
                    file_format = Path(uploaded.name).suffix.lower().lstrip(".")
            else:
                fixture = ROOT / "data" / PRESETS[source]
                content, file_format = fixture.read_bytes(), fixture.suffix.lstrip(".")
                st.download_button(
                    "Download this fixture",
                    content,
                    file_name=fixture.name,
                    mime="text/csv" if file_format == "csv" else "application/json",
                )
            if content:
                with st.expander("Preview submitted data"):
                    st.code(content[:12000].decode("utf-8-sig", errors="replace"), language=file_format)
            synthetic = st.checkbox("I confirm these submissions are synthetic.", key="synthetic_confirm")
            if not session:
                st.caption("Create a session from the sidebar first.")
            if st.button(
                "Run triage",
                key="run_triage",
                type="primary",
                disabled=not (session and content and synthetic),
            ):
                if len(content) > MAX_BYTES:
                    raise AppError("input_too_large", "Upload is larger than one MiB.", 413)
                with st.spinner("Supervisor → intake → coverage & anomalies → briefing → human review"):
                    result = client.request(
                        "POST",
                        f"/sessions/{session}/uploads",
                        params={"format": file_format, "synthetic": "true"},
                        content=content,
                    )
                st.session_state.active_batch = result
                st.session_state["pending_batch"] = result["id"]
                st.session_state.observed.update(demonstrated_by_batch(result))
                st.rerun()
            if batch:
                st.success(f"Batch {batch['id'][:8]} · {len(batch['results'])} claims · {batch['state']}")
                st.caption("Open Claims & review to inspect recommendations and record decisions.")
        with claims_tab:
            render_claims(client, session, batch)
        with chat_tab:
            st.subheader("Ask the supervisor")
            st.caption("Try: Why was claim C2031 flagged? Then: Explain its recommendation.")
            if session:
                for message in client.request("GET", f"/sessions/{session}/messages")["messages"]:
                    with st.chat_message(message["role"]):
                        st.text(message["content"])
                with st.form("conversation"):
                    question = st.text_input(
                        "Question", value="Why was claim C2031 flagged?", max_chars=2000, key="question"
                    )
                    ask = st.form_submit_button("Ask supervisor")
                if ask:
                    with st.spinner("Retrieving session evidence…"):
                        answer = client.request(
                            "POST", f"/sessions/{session}/chat", json={"message": question}
                        )
                    st.session_state.chat_turns += 1
                    if answer.get("evidence"):
                        st.session_state.observed.add("R16")
                        if st.session_state.chat_turns > 1:
                            st.session_state.observed.add("R19")
                    st.session_state.last_answer = answer
                    st.rerun()
                if st.session_state.get("last_answer", {}).get("service_issues"):
                    st.warning(
                        "Agent service issues: " + ", ".join(st.session_state.last_answer["service_issues"])
                    )
            else:
                st.info("Create or resume a session to ask questions.")
        with routine_tab:
            render_evidence(batch)
        with dashboard_tab:
            render_dashboard()
    except AppError as exc:
        st.error(f"{exc.code}: {exc.message}")
        st.session_state.observed.add("R24")
        st.caption("Correct the input or connection and retry. The backend retains committed evidence.")


def render_claims(client, session, batch):
    st.subheader("Adjuster workbench")
    if not batch or not batch["results"]:
        st.info("Run a batch or select a saved batch to see claim evidence.")
        return
    rows = batch["results"]
    columns = st.columns(4)
    for column, label, count in zip(
        columns,
        ["Claims", "Approve recommended", "Investigator", "Documentation"],
        [
            len(rows),
            *[sum(r["brief"]["recommended_action"] == action for r in rows) for action in ACTION_LABELS],
        ],
        strict=True,
    ):
        column.metric(label, count)
    st.dataframe(
        [
            {
                "Row": r["row_index"],
                "Claim": r["claim_id"],
                "Recommendation": ACTION_LABELS[r["brief"]["recommended_action"]],
                "Review": r["brief"]["review_status"],
                "Agent issues": len(r["service_issues"]),
            }
            for r in rows
        ],
        hide_index=True,
        width="stretch",
    )
    row_index = st.selectbox(
        "Inspect claim",
        [r["row_index"] for r in rows],
        format_func=lambda index: f"Row {index} · {rows[index]['claim_id']}",
        key=f"claim_{batch['id']}",
    )
    row = rows[row_index]
    st.write(row["brief"]["summary"])
    if row["service_issues"]:
        st.warning("Degraded agent evidence: " + ", ".join(row["service_issues"]))
    left, right = st.columns(2)
    with left:
        st.markdown("**Intake & coverage findings**")
        findings = row["intake"]["issues"] + row["coverage"].get("issues", [])
        if findings:
            st.dataframe(findings, hide_index=True, width="stretch")
        else:
            st.success("Intake and coverage checks passed with no review indicators.")
        st.caption(f"Coverage evaluation: {row['coverage']['status']}")
    with right:
        st.markdown("**Earlier policy history**")
        if row["coverage"].get("history"):
            st.dataframe(row["coverage"]["history"], hide_index=True, width="stretch")
        else:
            st.info("No eligible earlier similar history for this claim.")
    with st.expander("Retrieved underwriting rules and citations", expanded=True):
        citations = row["coverage"].get("citations", [])
        if not citations:
            st.caption("Coverage was skipped for invalid intake; no coverage evidence is asserted.")
        for citation in citations:
            st.markdown(f"**{citation['id']} · {citation['title']}**")
            st.text(citation["text"])
            st.caption(citation["source"])
    st.markdown("**Human decision**")
    if row.get("review"):
        st.success(f"Recorded: {row['review']['decision']} · {row['review']['reviewer']}")
        st.text(row["review"]["note"])
    else:
        st.caption(
            "A recommendation does not settle a claim. The API rejects approval of flagged or incomplete evidence."
        )
        with st.form(f"review_{batch['id']}_{row_index}"):
            decision = st.selectbox(
                "Decision",
                ["approve", "investigate", "request_documentation"],
                index=0
                if row["brief"]["recommended_action"] == "auto_approve"
                else (1 if row["brief"]["recommended_action"] == "route_to_investigator" else 2),
                key=f"decision_{batch['id']}_{row_index}",
            )
            note = st.text_area("Review note", max_chars=2000, key=f"note_{batch['id']}_{row_index}")
            record = st.form_submit_button("Record human decision")
        if record:
            client.request(
                "POST",
                f"/sessions/{session}/batches/{batch['id']}/reviews/{row_index}",
                json={"decision": decision, "note": note},
            )
            st.session_state.observed.add("R18")
            st.rerun()


def render_evidence(batch):
    st.subheader("Inspectable routine and evidence")
    st.write("Supervisor → Intake & Validation → Anomaly & Coverage → Adjuster Briefing → Human decision")
    st.markdown("**Four agents and their functions**")
    for role, names in ROLE_TOOLS.items():
        with st.expander(f"{role.title()} agent · {', '.join(names)}"):
            for name in names:
                st.markdown(f"**`{name}`** — {TOOLS[name]['description']}")
                st.json(TOOLS[name]["parameters"], expanded=False)
    st.caption(
        "This catalog shows registered functions, not a tool execution log. "
        "Coverage retrieves rules inside check_coverage. The additional search_knowledge tool "
        "is available to the Azure coverage agent; the mock workflow does not invoke it separately."
    )
    if not batch:
        st.info("Run a batch to inspect the actual recorded steps.")
        return
    st.dataframe(
        [
            {"Step": index + 1, "State": event["state"], "Detail": json.dumps(event["detail"])}
            for index, event in enumerate(batch["events"])
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(f"Batch runtime: {batch['mode']} · Knowledge SHA-256: {batch['knowledge_version']}")
    st.info(
        "Local grounding uses sparse TF-IDF retrieval. Azure hosted file-search configuration is implemented; this view does not prove a hosted search occurred."
    )
    st.download_button(
        "Download full evidence JSON",
        json.dumps(batch, indent=2, default=str),
        file_name=f"triage-{batch['id']}.json",
        mime="application/json",
    )
    with st.expander("Full audit payload"):
        st.json(batch)


def render_dashboard():
    st.subheader("Requirements dashboard")
    st.write("Every original requirement group, with implementation and verification references.")
    rows = requirement_rows(ROOT, st.session_state.observed)
    report = json.loads((ROOT / "docs/verification.json").read_text())
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Requirement groups", len(rows))
    col2.metric("Observed in this showcase", sum(r["Current showcase"] == "Observed" for r in rows))
    col3.metric("Recorded passing tests", report["tests"]["passed"])
    col4.metric("Recorded coverage", f"{report['coverage']['percent']}%")
    st.caption(
        f"Test results are from the saved verification report ({report['verified_on']}), not tests run by opening this page. Observed counters describe this browser showcase, not complete acceptance testing."
    )
    st.warning(
        "Live Azure, hosted retrieval, container build and cloud deployment require separate verification. Registering a tool or selecting Azure mode is not proof of a successful live run."
    )
    selection = st.selectbox(
        "Requirement filter",
        ["All requirements", "Observed in this showcase", "Not observed yet", "Azure / live verification"],
        key="requirement_filter",
    )
    filtered = rows
    if selection == "Observed in this showcase":
        filtered = [r for r in rows if r["Current showcase"] == "Observed"]
    elif selection == "Not observed yet":
        filtered = [r for r in rows if r["Current showcase"] != "Observed"]
    elif selection == "Azure / live verification":
        filtered = [r for r in rows if r["ID"] in {"R11", "R20", "R21", "R22", "R27"}]
    st.dataframe(filtered, hide_index=True, width="stretch")
    st.download_button(
        "Download requirement evidence",
        json.dumps(rows, indent=2),
        file_name="requirement-coverage.json",
        mime="application/json",
    )
    with st.expander("Showcase sequence", expanded=True):
        st.markdown(
            "1. New session → starter claims → confirm synthetic → Run triage.\n2. Inspect C-2031 history and citations; compare C-2032 and C-2033.\n3. Record the clean C-2032 decision and demonstrate a rejected C-2031 approval.\n4. Ask why C2031 was flagged, then ask a contextual follow-up.\n5. Run validation and coverage edge cases and the auto CSV.\n6. Refresh or restart, resume the saved session, and reopen evidence.\n7. Show this dashboard and distinguish observed behavior from pending cloud checks."
        )
    for title, filename in [
        ("Step-by-step showcase guide", "13-streamlit-showcase.md"),
        ("Implementation guide", "12-implementation-guide.md"),
    ]:
        path = ROOT / "docs" / filename
        if path.exists():
            st.download_button(title, path.read_bytes(), file_name=filename, mime="text/markdown")


if __name__ == "__main__":
    main()

"""Start the API and Streamlit together; keep the generated API token server-side."""

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import httpx

from claims_triage.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def wait_ready(url, process, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("A showcase service exited. Inspect var/showcase-* logs.")
        try:
            if httpx.get(url, timeout=2, trust_env=False).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise RuntimeError("Showcase startup timed out. Inspect var/showcase-* logs.")


def smoke(base_url, token):
    with httpx.Client(
        base_url=base_url, headers={"Authorization": f"Bearer {token}"}, trust_env=False, timeout=60
    ) as client:
        docs = client.get("/docs")
        docs.raise_for_status()
        assert "swagger-ui" in docs.text
        schema = client.get("/openapi.json").json()
        assert "requestBody" in schema["paths"]["/sessions/{session_id}/uploads"]["post"]
        session_response = client.post("/sessions")
        session_response.raise_for_status()
        sid = session_response.json()["session_id"]
        response = client.post(
            f"/sessions/{sid}/uploads?format=json&synthetic=true",
            content=(ROOT / "data/claims.json").read_bytes(),
        )
        response.raise_for_status()
        batch = response.json()
        assert [row["brief"]["recommended_action"] for row in batch["results"]] == [
            "route_to_investigator",
            "auto_approve",
            "route_to_investigator",
            "request_more_documentation",
        ]
        assert all(not row["service_issues"] for row in batch["results"])
        answer = client.post(f"/sessions/{sid}/chat", json={"message": "Why was C2031 flagged?"})
        answer.raise_for_status()
        assert "C-1900" in answer.json()["answer"]
        followup = client.post(f"/sessions/{sid}/chat", json={"message": "Explain its recommendation"})
        followup.raise_for_status()
        assert followup.json()["claim_id"] == "C-2031"
        decision = client.post(
            f"/sessions/{sid}/batches/{batch['id']}/reviews/1",
            json={"decision": "approve", "note": "Live HTTP synthetic smoke review"},
        )
        decision.raise_for_status()
        unsafe = client.post(
            f"/sessions/{sid}/batches/{batch['id']}/reviews/0",
            json={"decision": "approve", "note": "Demonstrate the synthetic human review guard"},
        )
        assert unsafe.status_code == 409 and unsafe.json()["error"]["code"] == "unsafe_approval"
        for index, action in [(0, "investigate"), (2, "investigate"), (3, "request_documentation")]:
            client.post(
                f"/sessions/{sid}/batches/{batch['id']}/reviews/{index}",
                json={"decision": action, "note": "Completed synthetic showcase review"},
            ).raise_for_status()
        saved = client.get(f"/sessions/{sid}/batches/{batch['id']}").json()
        assert saved["state"] == "REVIEWED"
        assert client.get(f"/sessions/{sid}/batches").json()["batches"][0]["id"] == batch["id"]
        return {
            "result": "passed",
            "checks": [
                "API startup",
                "Streamlit startup",
                "HTTP upload",
                "four expected outcomes",
                "memory chat",
                "human decision",
                "saved batch lookup",
                "Swagger HTML and upload schema",
                "conversation follow-up",
                "unsafe approval rejected",
                "all four decisions persisted and batch REVIEWED",
            ],
            "mode": batch["mode"],
        }


def smoke_widgets(base_url, token):
    """Drive actual Streamlit controls with real network requests; no fake API/client."""
    from streamlit.testing.v1 import AppTest

    with patch.dict(os.environ, {"TRIAGE_API_TOKEN": token, "TRIAGE_API_URL": base_url, "TRIAGE_MODE": "mock"}):
        ui = AppTest.from_file(str(ROOT / "ui/app.py"), default_timeout=45).run()
        assert not ui.exception
        ui.button(key="new_session").click().run()
        ui.checkbox(key="synthetic_confirm").check().run()
        ui.button(key="run_triage").click().run()
        assert not ui.exception and not ui.error
        batch = ui.session_state["active_batch"]
        assert len(batch["results"]) == 4
        next(b for b in ui.button if b.label == "Ask supervisor").click().run()
        assert "C-1900" in ui.session_state["last_answer"]["answer"]
        ui.selectbox(key=f"claim_{batch['id']}").select(1).run()
        ui.text_area(key=f"note_{batch['id']}_1").set_value("Live UI over HTTP review")
        next(b for b in ui.button if b.label == "Record human decision").click().run()
        assert not ui.exception and not ui.error
        assert ui.session_state["active_batch"]["results"][1]["review"]["decision"] == "approve"
        assert next(m.value for m in ui.metric if m.label == "Requirement groups") == "35"


def main():
    parser = argparse.ArgumentParser(description="Start the local Streamlit + API showcase")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--ui-port", type=int, default=8501)
    parser.add_argument(
        "--smoke", action="store_true", help="Exercise local mock HTTP workflow, then stop both services"
    )
    args = parser.parse_args()
    for port in (args.api_port, args.ui_port):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(f"Port {port} is unavailable. Use --api-port and --ui-port to choose unused ports.") from exc
    config = Settings()
    if args.smoke and config.mode != "mock":
        raise RuntimeError("Use TRIAGE_MODE=mock for the local smoke; live Azure has a separate opt-in test.")
    env = dict(os.environ)
    env["TRIAGE_API_TOKEN"] = config.api_token.get_secret_value() or secrets.token_urlsafe(32)
    env["TRIAGE_DATABASE"] = str(
        config.database if "database" in config.model_fields_set else ROOT / "var/showcase.db"
    )
    env["TRIAGE_API_URL"] = f"http://127.0.0.1:{args.api_port}"
    env["PYTHONUNBUFFERED"] = "1"
    log_dir = ROOT / f"var/showcase-{args.api_port}"
    log_dir.mkdir(parents=True, exist_ok=True)
    processes = []
    try:
        with (log_dir / "api.log").open("w") as api_log, (log_dir / "ui.log").open("w") as ui_log:
            for command, log_file in [
                ([sys.executable, "-m", "claims_triage", "serve", "--port", str(args.api_port)], api_log),
                (
                    [
                        sys.executable,
                        "-m",
                        "streamlit",
                        "run",
                        "ui/app.py",
                        "--server.port",
                        str(args.ui_port),
                        "--server.address",
                        "127.0.0.1",
                        "--server.headless",
                        "true",
                    ],
                    ui_log,
                ),
            ]:
                processes.append(
                    subprocess.Popen(
                        command,
                        cwd=ROOT,
                        env=env,
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )
                )
            wait_ready(env["TRIAGE_API_URL"] + "/health", processes[0])
            wait_ready(f"http://127.0.0.1:{args.ui_port}/_stcore/health", processes[1])
            print(
                f"Showcase ready: http://127.0.0.1:{args.ui_port}\nAPI: {env['TRIAGE_API_URL']}\nMode: {config.mode}\nLogs: {log_dir}\nPress Ctrl+C to stop both services.",
                flush=True,
            )
            if args.smoke:
                result = smoke(env["TRIAGE_API_URL"], env["TRIAGE_API_TOKEN"])
                smoke_widgets(env["TRIAGE_API_URL"], env["TRIAGE_API_TOKEN"])
                result["checks"].append("Streamlit widgets through real HTTP: triage, chat, review, requirement dashboard")
                (ROOT / "var/showcase-smoke.json").write_text(json.dumps(result, indent=2))
                print(json.dumps(result), flush=True)
                return
            while all(process.poll() is None for process in processes):
                time.sleep(0.5)
    except KeyboardInterrupt:
        print("Stopping showcase services.")
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()

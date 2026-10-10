"""Real subprocess checks exercise installed entry point and cross-process memory."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def cli(tmp_path):
    env = dict(
        os.environ,
        TRIAGE_MODE="mock",
        TRIAGE_DATABASE=str(tmp_path / "cli.db"),
        TRIAGE_DATA_DIR=str(ROOT / "data"),
        TRIAGE_KNOWLEDGE_DIR=str(ROOT / "knowledge"),
    )

    def execute(*args):
        return subprocess.run(
            [sys.executable, "-m", "claims_triage", *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    return execute


def test_cli_batch_followup_and_review_across_processes(cli):
    triage = cli("triage", "data/claims.json", "--synthetic")
    assert triage.returncode == 0, triage.stderr
    result = json.loads(triage.stdout)
    assert len(result["results"]) == 4
    sid, bid = result["session_id"], result["id"]
    question = cli("chat", sid, "why was claim C2031 flagged?")
    assert question.returncode == 0
    assert "C-1900" in json.loads(question.stdout)["answer"]
    followup = cli("chat", sid, "explain why it was flagged")
    assert json.loads(followup.stdout)["claim_id"] == "C-2031"
    review = cli("review", sid, bid, "1", "approve", "--note", "Reviewed synthetic evidence")
    assert review.returncode == 0
    shown = cli("show", sid, bid)
    assert json.loads(shown.stdout)["results"][1]["brief"]["review_status"] == "reviewed"
    # Raw descriptions never appear in operational logs.
    assert "Pipe burst in kitchen" not in triage.stderr
    assert '"event": "routine_step"' in triage.stderr


def test_cli_invalid_input_and_mock_provision_are_clear_errors(cli):
    invalid = cli("triage", "data/does-not-exist.json", "--synthetic")
    assert invalid.returncode == 1
    assert json.loads(invalid.stderr.splitlines()[-1])["error"]["code"] == "configuration_or_file_error"
    provision = cli("provision")
    assert provision.returncode == 1
    assert json.loads(provision.stderr.splitlines()[-1])["error"]["code"] == "azure_mode_required"
    missing_opt_in = cli("triage", "data/claims.json")
    assert missing_opt_in.returncode == 2


def test_cli_init_and_csv(cli):
    initialized = cli("init")
    sid = json.loads(initialized.stdout)["session_id"]
    result = cli("triage", "data/claims_auto.csv", "--synthetic", "--session", sid)
    assert result.returncode == 0
    actions = [row["brief"]["recommended_action"] for row in json.loads(result.stdout)["results"]]
    assert actions == ["auto_approve", "route_to_investigator"]

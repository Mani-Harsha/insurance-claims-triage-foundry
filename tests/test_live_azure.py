"""Explicit opt-in: incurs live model calls using an already provisioned profile."""

import json
import os

import pytest

from claims_triage.bootstrap import create_service
from claims_triage.config import Settings

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("TRIAGE_RUN_LIVE") != "1",
        reason="Live Azure test requires explicit opt-in and configured provisioned profile",
    ),
]


def test_live_four_agents_with_grounding_and_followup():
    settings = Settings()
    assert settings.mode == "azure", "Configure TRIAGE_MODE=azure first"
    service = create_service(settings)
    try:
        manifest = service.repo.metadata("azure_manifest")
        assert manifest and len(manifest["agents"]) == 4, "Run provision first"
        rows = json.loads((settings.data_dir / "claims.json").read_text())
        session_id = service.repo.create_session()
        result = service.triage(session_id, rows[:1], True)
        assert result["mode"] == "azure"
        assert result["results"][0]["service_issues"] == []
        assert result["results"][0]["coverage"]["citations"]
        threads = {role: service.repo.thread(session_id, role) for role in manifest["agents"]}
        assert all(threads.values())
        answer = service.chat(session_id, "Why was claim C2031 flagged?")
        assert "C-1900" in answer["answer"]
        assert answer["service_issues"] == []
        assert service.repo.thread(session_id, "supervisor") == threads["supervisor"]
        assert service.repo.thread(session_id, "briefing") == threads["briefing"]
    finally:
        service.runtime.close()

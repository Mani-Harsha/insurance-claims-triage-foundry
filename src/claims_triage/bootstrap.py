import json

from .config import Settings
from .domain import AppError, parse_date
from .knowledge import FileVectorKnowledge, load_policies
from .ports import AgentRuntime
from .repository import SQLiteRepository
from .runtime import MockRuntime
from .service import TriageService


def create_service(settings: Settings) -> TriageService:
    knowledge = FileVectorKnowledge(settings.knowledge_dir)
    policies = load_policies(settings.data_dir / "policy_coverage.json")
    repository = SQLiteRepository(settings.database)
    try:
        seed = json.loads((settings.data_dir / "memory_seed.json").read_text(encoding="utf-8"))
        for entry in seed:
            parse_date(entry["loss_date"])
            if entry["policy_number"] not in policies or type(entry["flagged"]) is not bool:
                raise ValueError("Invalid history")
        repository.seed_history(seed)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise AppError("invalid_memory_seed", "Synthetic memory seed is missing or invalid.", 503) from exc
    runtime: AgentRuntime = MockRuntime()
    if settings.mode == "azure":
        from .azure_runtime import AzureRuntime

        runtime = AzureRuntime(
            repository,
            settings.azure_endpoint,
            settings.azure_model,
            settings.knowledge_dir,
            knowledge.version,
            settings.agent_timeout_seconds,
        )
    return TriageService(repository, policies, knowledge, runtime)

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRIAGE_", env_file=".env", extra="ignore")
    mode: Literal["mock", "azure"] = "mock"
    database: Path = Path("var/claims.db")
    data_dir: Path = Path("data")
    knowledge_dir: Path = Path("knowledge")
    api_token: SecretStr = SecretStr("")
    azure_endpoint: str = ""
    azure_model: str = ""
    agent_timeout_seconds: float = Field(default=60, ge=1, le=120)

    @model_validator(mode="after")
    def azure_configured(self) -> "Settings":
        if self.mode == "azure":
            parsed = urlparse(self.azure_endpoint)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or not parsed.path.startswith("/api/projects/")
                or not self.azure_model
            ):
                raise ValueError(
                    "Azure mode needs an HTTPS Foundry project endpoint and a model deployment name."
                )
        return self

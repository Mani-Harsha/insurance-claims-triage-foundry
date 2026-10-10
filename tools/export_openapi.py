import json
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import SecretStr

from claims_triage.api import create_app
from claims_triage.config import Settings


def main() -> None:
    Path("var").mkdir(exist_ok=True)
    with TemporaryDirectory(dir="var") as folder:
        app = create_app(
            Settings(
                _env_file=None,
                mode="mock",
                database=Path(folder) / "schema.db",
                api_token=SecretStr("schema-generation-only-token"),
            )
        )
        Path("docs/openapi.json").write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
        app.state.service.runtime.close()


if __name__ == "__main__":
    main()

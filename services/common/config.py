"""Access to config/models.json, the project's single source of model choices."""

import json
import os
from functools import lru_cache
from pathlib import Path

ROLES = ("agent", "flow", "compare", "judge", "embeddings")
PLACEHOLDER_PREFIX = "REPLACE_ME"


def _default_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "models.json"


@lru_cache(maxsize=1)
def load_models(path: str | None = None) -> dict:
    target = Path(path or os.environ.get("MODELS_CONFIG_PATH") or _default_path())
    return json.loads(target.read_text())


def model_id(role: str) -> str:
    """Model ID for a single-model role (agent, flow, judge, embeddings)."""
    entry = load_models()["roles"][role]
    if isinstance(entry, list):
        raise ValueError(f"Role '{role}' has several models; use load_models()['roles']['{role}']")
    return entry["modelId"]


def unfilled_roles() -> list[str]:
    """Roles whose model IDs are still placeholders."""
    missing = []
    for role, entry in load_models()["roles"].items():
        entries = entry if isinstance(entry, list) else [entry]
        if any(str(e.get("modelId", "")).startswith(PLACEHOLDER_PREFIX) for e in entries):
            missing.append(role)
    return missing

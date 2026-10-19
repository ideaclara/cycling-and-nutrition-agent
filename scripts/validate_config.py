"""CI check: config/models.json matches its JSON schema and the action-group
OpenAPI documents are valid.

    uv run --project services python scripts/validate_config.py
"""

import json
import sys
from pathlib import Path

import jsonschema
import yaml
from openapi_spec_validator import validate

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    config = json.loads((ROOT / "config" / "models.json").read_text())
    schema = json.loads((ROOT / "config" / "models.schema.json").read_text())
    jsonschema.validate(config, schema)
    print("ok  config/models.json")

    for path in sorted((ROOT / "bedrock" / "action-groups").glob("*.yaml")):
        validate(yaml.safe_load(path.read_text()))
        print(f"ok  {path.relative_to(ROOT)}")

    placeholders = [
        role
        for role, entry in config["roles"].items()
        for e in (entry if isinstance(entry, list) else [entry])
        if e["modelId"].startswith("REPLACE_ME")
    ]
    if placeholders:
        print(f"note: model IDs still to fill in for roles: {', '.join(sorted(set(placeholders)))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

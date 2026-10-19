"""Read-only drift check: do the Bedrock resources you built in the console use
the models named in config/models.json?

Only calls get-*/list-* APIs and only prints a report; it never changes
anything. Exit code is 0 unless --strict is passed and drift is found.

    uv run --project services python scripts/check_model_config.py [--strict]
"""

import argparse
import json
import sys
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]


def model_name(identifier: str | None) -> str:
    """Reduce an ARN or ID to the bare model / inference-profile ID for comparison."""
    if not identifier:
        return ""
    return identifier.split("/")[-1]


def list_all(call, key, **kwargs):
    while True:
        page = call(**kwargs)
        yield from page.get(key, [])
        if not page.get("nextToken"):
            return
        kwargs["nextToken"] = page["nextToken"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="exit 1 if drift is found")
    args = parser.parse_args()

    config = json.loads((ROOT / "config" / "models.json").read_text())
    roles = config["roles"]

    def ids(role: str) -> set[str]:
        entries = roles[role] if isinstance(roles[role], list) else [roles[role]]
        return {model_name(m) for e in entries for m in (e.get("modelId"), e.get("fallback")) if m}

    agent_models = ids("agent")
    allowed_runtime = agent_models | ids("flow") | ids("compare")

    client = boto3.client("bedrock-agent", region_name=config["region"])
    findings: list[str] = []
    checked = 0

    for summary in list_all(client.list_agents, "agentSummaries"):
        agent = client.get_agent(agentId=summary["agentId"])["agent"]
        used = model_name(agent.get("foundationModel"))
        checked += 1
        status = "ok " if used in agent_models else "DRIFT"
        if status != "ok ":
            findings.append(f"agent {agent['agentName']}: uses {used}, config allows {sorted(agent_models)}")
        print(f"{status} agent  {agent['agentName']:<30} {used}")

    for summary in list_all(client.list_flows, "flowSummaries"):
        flow = client.get_flow(flowIdentifier=summary["id"])
        for node in (flow.get("definition") or {}).get("nodes", []):
            prompt_cfg = (node.get("configuration") or {}).get("prompt", {}).get("sourceConfiguration", {})
            inline = prompt_cfg.get("inline")
            if not inline:
                continue
            used = model_name(inline.get("modelId"))
            checked += 1
            status = "ok " if used in allowed_runtime else "DRIFT"
            if status != "ok ":
                findings.append(f"flow {flow['name']} node {node['name']}: uses {used}")
            print(f"{status} flow   {flow['name'] + '/' + node['name']:<30} {used}")

    for summary in list_all(client.list_prompts, "promptSummaries"):
        prompt = client.get_prompt(promptIdentifier=summary["id"])
        for variant in prompt.get("variants", []):
            used = model_name(variant.get("modelId"))
            checked += 1
            status = "ok " if used in allowed_runtime else "DRIFT"
            if status != "ok ":
                findings.append(f"prompt {prompt['name']} variant {variant['name']}: uses {used}")
            print(f"{status} prompt {prompt['name'] + '/' + variant['name']:<30} {used}")

    print(f"\nChecked {checked} model references; {len(findings)} differ from config/models.json")
    return 1 if findings and args.strict else 0


if __name__ == "__main__":
    sys.exit(main())

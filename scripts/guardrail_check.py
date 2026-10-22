"""Run the Module B test cases through a guardrail with ApplyGuardrail and compare with what's expected.

Read-only: ApplyGuardrail evaluates text against a guardrail you built in the
console; it creates and changes nothing. Each call is billed per text unit
(1,000 characters), so a full run costs well under a cent.

    uv run --project services python scripts/guardrail_check.py --guardrail <id> [--version DRAFT] [--only deny-]

Cases come from bedrock/guardrails/test_cases.jsonl. A case with `grounding` and
`query` is sent with content qualifiers, so the contextual grounding check runs.
`expect` is NONE, GUARDRAIL_INTERVENED, or DETECTED: a policy in Detect mode
fired, but nothing was blocked.
"""

import argparse
import json
import os
import sys

import boto3

CASES = os.path.join(os.path.dirname(__file__), "..", "bedrock", "guardrails", "test_cases.jsonl")


def content(case: dict) -> list[dict]:
    if "grounding" not in case:
        return [{"text": {"text": case["text"]}}]
    return [
        {"text": {"text": case["grounding"], "qualifiers": ["grounding_source"]}},
        {"text": {"text": case["query"], "qualifiers": ["query"]}},
        {"text": {"text": case["text"], "qualifiers": ["guard_content"]}},
    ]


def reasons(assessments: list[dict]) -> list[str]:
    """Short labels for every policy that fired, e.g. topic:Medical diagnosis, grounding:0.12<0.75."""
    found = []
    for a in assessments:
        for t in a.get("topicPolicy", {}).get("topics", []):
            found.append(f"topic:{t['name']}" + (" (detect)" if t.get("action") == "NONE" else ""))
        for f in a.get("contentPolicy", {}).get("filters", []):
            found.append(f"content:{f['type']}/{f['confidence']}")
        for w in a.get("wordPolicy", {}).get("customWords", []) + a.get("wordPolicy", {}).get("managedWordLists", []):
            found.append(f"word:{w['match']}")
        for p in a.get("sensitiveInformationPolicy", {}).get("piiEntities", []):
            found.append(f"pii:{p['type']}/{p['action']}")
        for g in a.get("contextualGroundingPolicy", {}).get("filters", []):
            mark = "<" if g["action"] == "BLOCKED" else ">="
            found.append(f"{g['type'].lower()}:{g['score']:.2f}{mark}{g['threshold']}")
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--guardrail", required=True, help="guardrail ID or ARN")
    parser.add_argument("--version", default="DRAFT", help="guardrail version (default DRAFT, the working draft)")
    parser.add_argument("--only", help="run only cases whose id starts with this")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    runtime = boto3.client("bedrock-runtime", region_name=args.region)
    with open(CASES) as f:
        cases = [json.loads(line) for line in f if line.strip()]
    if args.only:
        cases = [c for c in cases if c["id"].startswith(args.only)]

    failures = 0
    for case in cases:
        resp = runtime.apply_guardrail(
            guardrailIdentifier=args.guardrail,
            guardrailVersion=args.version,
            source=case["source"],
            content=content(case),
        )
        action = resp["action"]
        fired = ", ".join(reasons(resp.get("assessments", [])))
        ok = (action == "NONE" and bool(fired)) if case["expect"] == "DETECTED" else action == case["expect"]
        failures += not ok
        if action == "GUARDRAIL_INTERVENED":
            returned = " ".join(o["text"] for o in resp.get("outputs", []))
            outcome = f"{fired or action} --> {returned}"
        else:
            outcome = f"NONE ({fired})" if fired else "NONE"
        query = f"  [query: {case['query']}]" if "query" in case else ""
        print(f"{'PASS' if ok else 'FAIL'}  {case['id']} ({case['source']}): {case['text']}{query}")
        print(f"      expect:  {case['expect']}")
        print(f"      outcome: {outcome}")
        print()

    print(f"{len(cases) - failures}/{len(cases)} as expected")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()

"""Run the same queries against several Knowledge Bases and compare what comes back.

Read-only: it calls ListKnowledgeBases and Retrieve, never creates or changes
anything. Use it in Module A to compare chunking strategies, one KB per strategy.

    uv run --project services python scripts/kb_compare.py                 # all coach-kb-* KBs
    uv run --project services python scripts/kb_compare.py --kb coach-kb-fixed --kb coach-kb-semantic
    uv run --project services python scripts/kb_compare.py --domain nutrition -k 3 \\
        --query "How much carbohydrate per hour on a 4-hour ride?"

Queries come from --query (repeatable) or bedrock/kb/queries.txt.
"""

import argparse
import json
import os
import sys

import boto3

REGION = "us-east-1"
DEFAULT_PREFIX = "coach-kb-"
QUERIES = os.path.join(os.path.dirname(__file__), "..", "bedrock", "kb", "queries.txt")


def knowledge_bases(agent, wanted: list[str]) -> dict[str, str]:
    """Map name -> id, for the KBs named in `wanted` (names or ids) or all coach-kb-*."""
    found = {}
    for page in agent.get_paginator("list_knowledge_bases").paginate():
        for kb in page["knowledgeBaseSummaries"]:
            found[kb["name"]] = kb["knowledgeBaseId"]
    if not wanted:
        return {n: i for n, i in sorted(found.items()) if n.startswith(DEFAULT_PREFIX)}
    by_id = {i: n for n, i in found.items()}
    selected = {}
    for w in wanted:
        if w in found:
            selected[w] = found[w]
        elif w in by_id:
            selected[by_id[w]] = w
        else:
            sys.exit(f"No knowledge base named or with id {w!r}")
    return selected


def load_queries(args) -> list[str]:
    if args.query:
        return args.query
    with open(QUERIES) as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def retrieve(runtime, kb_id: str, query: str, k: int, domain: str | None) -> list[dict]:
    search: dict = {"numberOfResults": k}
    if domain:
        search["filter"] = {"equals": {"key": "domain", "value": domain}}
    resp = runtime.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": query},
        retrievalConfiguration={"vectorSearchConfiguration": search},
    )
    return resp["retrievalResults"]


def source(result: dict) -> str:
    uri = (result.get("location") or {}).get("s3Location", {}).get("uri", "?")
    return uri.split("/", 3)[-1]  # drop s3://bucket/


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--kb", action="append", default=[], help="KB name or id (repeatable)")
    parser.add_argument("--query", action="append", help="query text (repeatable)")
    parser.add_argument("-k", type=int, default=5, help="results per query (default 5)")
    parser.add_argument("--domain", help="metadata filter: domain = <value>")
    parser.add_argument("--json", metavar="FILE", help="also write full results to FILE")
    args = parser.parse_args()

    agent = boto3.client("bedrock-agent", region_name=REGION)
    runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)
    kbs = knowledge_bases(agent, args.kb)
    if not kbs:
        sys.exit(f"No knowledge bases found (looked for names starting {DEFAULT_PREFIX!r})")

    dump = []
    for query in load_queries(args):
        print(f"\n=== {query}")
        for name, kb_id in kbs.items():
            results = retrieve(runtime, kb_id, query, args.k, args.domain)
            lengths = [len(r["content"].get("text", "")) for r in results]
            avg = sum(lengths) // len(lengths) if lengths else 0
            print(f"--- {name} ({len(results)} results, avg {avg} chars)")
            for rank, r in enumerate(results, 1):
                text = " ".join(r["content"].get("text", "").split())
                print(f"  {rank}. {r.get('score', 0):.3f}  {source(r)}")
                print(f"     {text[:160]}")
            dump.append({"query": query, "kb": name, "results": results})

    if args.json:
        with open(args.json, "w") as f:
            json.dump(dump, f, indent=2, default=str)
        print(f"\nFull results written to {args.json}")


if __name__ == "__main__":
    main()

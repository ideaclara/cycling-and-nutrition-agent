"""Save one day of your FatSecret food diary, and that month's daily totals, as raw JSON.

    uv run --project services python scripts/fatsecret_probe.py [YYYY-MM-DD]   (default: yesterday)

Lists every field that has a value, so we can see what FatSecret actually
returns for your foods (fibre and sugar are "where available"). The output is
your food diary, so it goes to a git-ignored folder.
"""

import json
import os
import sys
from collections import Counter
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services"))
os.environ.setdefault("FATSECRET_SECRET_ID", "fatsecret/oauth")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from common import fatsecret_api  # noqa: E402

OUT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "documentation", "initial-setup-documentation", "fatsecret-example-responses"
)


def main():
    day = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today() - timedelta(days=1)
    creds = fatsecret_api.credentials()
    os.makedirs(OUT_DIR, exist_ok=True)

    month = fatsecret_api.call("food_entries.get_month.v2", creds, date=fatsecret_api.date_int(day))
    entries = fatsecret_api.call("food_entries.get.v2", creds, date=fatsecret_api.date_int(day))
    for name, body in ((f"month_{day:%Y-%m}.json", month), (f"entries_{day}.json", entries)):
        path = os.path.join(OUT_DIR, name)
        with open(path, "w") as f:
            json.dump(body, f, indent=2)
        print(f"Saved {os.path.normpath(path)}")

    rows = fatsecret_api.as_list((entries.get("food_entries") or {}).get("food_entry"))
    counts = Counter(k for row in rows for k, v in row.items() if v not in (None, ""))
    print(f"\n{len(rows)} entries on {day}. Fields with a value (number of entries):")
    for field, count in sorted(counts.items()):
        print(f"  {field:<28} {count}")


if __name__ == "__main__":
    main()

"""Build the clean Knowledge Base source tree from the raw reference documents.

Reads SOURCE (never modifies it) and rebuilds bedrock/kb-docs/{library,papers}/:

    library/   Markdown for the default parser
      periodisation/friel-cyclists-training-bible.md
      nutrition/racing-weight/chapter-04-improving-your-diet-quality.md
      power_models/allen-coggan/training-and-racing-with-a-power-meter.md
      power_models/xert/high-intensity-energy-hie.md
    papers/    PDFs for the foundation-model parser, reference lists removed
      nutrition/ioc-reds-2023.pdf

Every document gets a `<file>.metadata.json` sidecar with `domain`, `source_type`
and `title` (plus `year`, `chapter`, `xert_section`, `source_url` where known).

    uv run --project services python scripts/prepare_kb_docs.py "~/Documents/Racing/S3 Vectors Folder"
"""

import argparse
import io
import json
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup
from markdownify import markdownify
from pypdf import PdfReader, PdfWriter

OUT = Path(__file__).resolve().parent.parent / "bedrock" / "kb-docs"

RACING_WEIGHT = "nutrition/Racing Weight by Matt Fitzgerald"
RACING_WEIGHT_TITLE = "Racing Weight (2nd ed.)"
RACING_WEIGHT_SKIP = {
    "chapter_14_references_and_about_the_author.md": "reference list and author bio",
    "appendix_strength_exercises_for_runners.md": "running-specific",
}
FRIEL = "periodisation/Cyclist's Training Bible, 5th Ed, Joe Friel v2.md"
ALLEN_COGGAN = (
    "power_models/Training and Racing with a Power Meter/"
    "Training and Racing with a Power Meter by Allen, Coggan and McGregor.md"
)
XERT = "power_models/XERT Documentation"
# Device, app-install and sync support: no coaching value.
XERT_SKIP_SECTIONS = {
    "Getting Started > Connect Your Apps & Devices",
    "Troubleshooting > Devices & Apps",
    "Troubleshooting > Syncing & Activities",
    "Using Xert > Xert On Your Bike Computer",
}
PAPERS = {
    "nutrition/2023 IOC Consensus Statement on Relative Energy Deficiency in Sport.pdf": (
        "nutrition/ioc-reds-2023.pdf",
        {
            "title": "IOC consensus statement on Relative Energy Deficiency in Sport (REDs)",
            "year": 2023,
        },
    ),
    "nutrition/ISSN exercise & sports nutrition review - research and recommendations.pdf": (
        "nutrition/issn-sports-nutrition-review-2018.pdf",
        {
            "title": "ISSN exercise & sports nutrition review update: research & recommendations",
            "year": 2018,
        },
    ),
}


def slugify(text: str) -> str:
    """Lowercase ASCII slug; NFKC turns full-width ：？＋ into their ASCII forms first."""
    text = unicodedata.normalize("NFKC", text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


LATEX_SYMBOLS = {
    "approx": "≈",
    "times": "×",
    "ge": "≥",
    "geq": "≥",
    "le": "≤",
    "leq": "≤",
    "tau": "τ",
    "implies": "⇒",
    "rightarrow": "→",
    "to": "→",
    "pm": "±",
    "cdot": "·",
}


def delatex(span: str) -> str:
    span = re.sub(r"\\text\{([^}]*)\}", r"\1", span)
    span = re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", r"(\1) / (\2)", span)
    span = span.replace("\\%", "%")
    return re.sub(r"\\([a-zA-Z]+)", lambda m: LATEX_SYMBOLS.get(m.group(1), m.group(0)), span)


# $…$ or $$…$$ on one line, but not currency such as $10,000.
MATH_SPAN = re.compile(r"\${1,2}(?!\d{1,3},\d{3})([^$\n]+?)\${1,2}")


def _math(match: re.Match) -> str:
    inner = match.group(1)
    if re.search(r"[\\_^=<>%]", inner) or re.fullmatch(r"[\d.,–+\- ]+|[a-zA-Z]", inner):
        return delatex(inner)
    return match.group(0)


def tidy(markdown: str) -> str:
    # Inline maths like $\approx 1.3\text{ g/kg}$ reads (and embeds) better as plain text.
    markdown = MATH_SPAN.sub(_math, markdown)
    lines = [line.rstrip() for line in markdown.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def write(rel: str, text_or_bytes, metadata: dict, report: list) -> None:
    path = OUT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text_or_bytes, bytes):
        path.write_bytes(text_or_bytes)
        size = f"{len(text_or_bytes) // 1024} KB"
    else:
        path.write_text(text_or_bytes, encoding="utf-8")
        size = f"{len(text_or_bytes.split())} words"
    sidecar = json.dumps({"metadataAttributes": metadata}, indent=2, ensure_ascii=False)
    if len(sidecar.encode()) > 900:  # S3 Vectors allows ~1 KB of custom metadata per vector
        raise ValueError(f"{rel}: sidecar is {len(sidecar.encode())} bytes")
    Path(f"{path}.metadata.json").write_text(sidecar + "\n", encoding="utf-8")
    report.append(("wrote", rel, size))


# --- Friel ---------------------------------------------------------------------


def clean_friel(raw: str) -> str:
    """The file is a Python snippet: content = \"\"\"<escaped markdown>\"\"\" plus a changelog."""
    match = re.search(r'content \\?= """(.*?)\n"""', raw, re.DOTALL)
    if not match:
        raise ValueError('Friel: expected content = """ ... """ wrapper')
    body = re.sub(r"\\([\\`*_{}\[\]()#+\-.!=<>|~$])", r"\1", match.group(1))
    body = body.replace("\\\\", "\\")  # the ASCII diagrams were double-escaped
    body = re.sub(r"\s*for Gemini Gem Knowledge Base", "", body)
    return tidy(body)


# --- Racing Weight ---------------------------------------------------------------


def split_front_matter(raw: str) -> tuple[dict, str]:
    match = re.match(r"---\n(.*?)\n---\n", raw, re.DOTALL)
    if not match:
        return {}, raw
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip('"')
    return fields, raw[match.end() :]


def racing_weight_doc(name: str, raw: str) -> tuple[str, str, dict]:
    fields, body = split_front_matter(raw)
    number = re.match(r"chapter_(\d+)", name)
    # Put the book name in the heading so the first chunk says where it comes from.
    body = re.sub(r"^# ", f"# {RACING_WEIGHT_TITLE}: ", body.lstrip(), count=1)
    metadata = {
        "domain": "nutrition",
        "source_type": "book_notes",
        "title": RACING_WEIGHT_TITLE,
        "authors": "Matt Fitzgerald",
        "section": fields.get("chapter", name)[:120],
    }
    if number:
        metadata["chapter"] = int(number.group(1))
    rel = f"library/nutrition/racing-weight/{slugify(Path(name).stem)}.md"
    return rel, tidy(body), metadata


# --- Xert ------------------------------------------------------------------------


def xert_doc(raw_html: str) -> tuple[str, str, str, dict] | None:
    """(section, title, markdown, metadata) from a saved Zendesk article, or None if empty."""
    soup = BeautifulSoup(raw_html, "html.parser")
    body = soup.select_one("div.article-body")
    heading = soup.select_one("h1.article-title")
    if not body or not heading or not body.get_text(strip=True):
        return None
    title = heading.get("title") or heading.get_text(strip=True)
    crumbs = [a.get_text(strip=True) for a in soup.select("ol.breadcrumbs a")][1:]
    section = " > ".join(crumbs)
    # Links and images only add URL noise to the embedded text.
    text = markdownify(str(body), heading_style="ATX", strip=["a", "img"])
    markdown = tidy(f"# Xert: {title}\n\n_{section}_\n\n{text}")
    canonical = soup.select_one('link[rel="canonical"]')
    metadata = {
        "domain": "power_models",
        "source_type": "vendor_docs",
        "title": title[:120],
        "xert_section": section,
    }
    if canonical and canonical.get("href"):
        metadata["source_url"] = canonical["href"][:200]
    return section, title, markdown, metadata


# --- Papers ----------------------------------------------------------------------


def trim_references(reader: PdfReader) -> tuple[PdfWriter, int]:
    """Keep pages up to and including the one where a 'References' heading starts."""
    last = len(reader.pages) - 1
    for i, page in enumerate(reader.pages):
        lines = (page.extract_text() or "").splitlines()
        if i > 0 and any(re.fullmatch(r"\s*references\s*", line, re.IGNORECASE) for line in lines):
            last = i
            break
    writer = PdfWriter()
    for page in reader.pages[: last + 1]:
        writer.add_page(page)
    return writer, last + 1


# --------------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", help="folder holding nutrition/, periodisation/, power_models/")
    args = parser.parse_args()
    src = Path(os.path.expanduser(args.source))
    if not (src / "nutrition").is_dir():
        sys.exit(f"{src} has no nutrition/ folder")

    for sub in ("library", "papers"):
        shutil.rmtree(OUT / sub, ignore_errors=True)
    report: list[tuple[str, str, str]] = []

    friel = clean_friel((src / FRIEL).read_text(encoding="utf-8"))
    write(
        "library/periodisation/friel-cyclists-training-bible.md",
        friel,
        {
            "domain": "periodisation",
            "source_type": "book_notes",
            "title": "The Cyclist's Training Bible (5th ed.)",
            "authors": "Joe Friel",
            "year": 2018,
        },
        report,
    )

    for path in sorted((src / RACING_WEIGHT).glob("*.md")):
        if path.name in RACING_WEIGHT_SKIP:
            report.append(("skipped", path.name, RACING_WEIGHT_SKIP[path.name]))
            continue
        rel, text, metadata = racing_weight_doc(path.name, path.read_text(encoding="utf-8"))
        write(rel, text, metadata, report)

    write(
        "library/power_models/allen-coggan/training-and-racing-with-a-power-meter.md",
        tidy((src / ALLEN_COGGAN).read_text(encoding="utf-8")),
        {
            "domain": "power_models",
            "source_type": "book",
            "title": "Training and Racing with a Power Meter (3rd ed.)",
            "authors": "Hunter Allen, Andrew Coggan, Stephen McGregor",
            "year": 2019,
        },
        report,
    )

    for path in sorted((src / XERT).glob("*.html")):
        doc = xert_doc(path.read_text(encoding="utf-8", errors="replace"))
        if doc is None:
            report.append(("skipped", path.name[:70], "no article body (index page)"))
            continue
        section, title, markdown, metadata = doc
        if section in XERT_SKIP_SECTIONS:
            report.append(("skipped", title[:70], f"device/app support ({section})"))
            continue
        write(f"library/power_models/xert/{slugify(title)}.md", markdown, metadata, report)

    for rel_src, (rel_out, extra) in PAPERS.items():
        reader = PdfReader(src / rel_src)
        writer, kept = trim_references(reader)
        buffer = io.BytesIO()
        writer.write(buffer)
        metadata = {"domain": "nutrition", "source_type": "consensus", **extra}
        write(f"papers/{rel_out}", buffer.getvalue(), metadata, report)
        report.append(("trimmed", rel_out, f"kept {kept} of {len(reader.pages)} pages"))

    for action, name, detail in report:
        print(f"{action:8} {name:<75} {detail}")
    wrote = sum(1 for r in report if r[0] == "wrote")
    skipped = sum(1 for r in report if r[0] == "skipped")
    print(f"\n{wrote} documents written to {OUT}, {skipped} skipped")


if __name__ == "__main__":
    main()

import importlib.util
import os

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "prepare_kb_docs.py")
_spec = importlib.util.spec_from_file_location("prepare_kb_docs", SCRIPT)
kb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kb)

XERT_PAGE = """<html><head><link rel="canonical" href="https://example.zendesk.com/hc/articles/1-HIE"></head>
<body><nav>Submit a request</nav>
<ol class="breadcrumbs"><li><a href="/">Knowledgebase</a></li><li><a href="/c">Glossary</a></li>
<li><a href="/s">Fitness Signature</a></li></ol>
<aside>Articles in this section: Threshold Power (TP), Peak Power (PP)</aside>
<article><h1 title="High Intensity Energy (HIE)" class="article-title">High Intensity Energy (HIE)</h1>
<div class="article-body"><h2>Definition</h2><p>HIE is measured in <a href="/kj">kilojoules</a>.</p>
<img src="data:image/png;base64,AAAA"></div></article>
<section>Recently viewed articles: Fatigue</section></body></html>"""


def test_slugify_normalises_full_width_punctuation():
    assert kb.slugify("Why is my Training Status always Red or Yellow？") == (
        "why-is-my-training-status-always-red-or-yellow"
    )
    assert kb.slugify("Xert ＋ Garmin：Setup") == "xert-garmin-setup"


def test_xert_doc_keeps_only_the_article():
    section, title, markdown, metadata = kb.xert_doc(XERT_PAGE)
    assert section == "Glossary > Fitness Signature"
    assert title == "High Intensity Energy (HIE)"
    assert markdown.startswith("# Xert: High Intensity Energy (HIE)\n\n_Glossary > Fitness Signature_")
    assert "## Definition" in markdown
    assert "measured in kilojoules." in markdown  # link text kept, URL dropped
    for noise in ("Submit a request", "Articles in this section", "Recently viewed", "data:image", "/kj"):
        assert noise not in markdown
    assert metadata == {
        "domain": "power_models",
        "source_type": "vendor_docs",
        "title": "High Intensity Energy (HIE)",
        "xert_section": "Glossary > Fitness Signature",
        "source_url": "https://example.zendesk.com/hc/articles/1-HIE",
    }


def test_xert_doc_skips_pages_without_an_article():
    assert kb.xert_doc("<html><body><h1>Knowledgebase</h1></body></html>") is None


def test_clean_friel_unwraps_and_unescapes():
    raw = (
        'content \\= """\\# Training Bible\n\\#\\# Core Reference for Gemini Gem Knowledge Base\n'
        "1\\. \\*\\*Train Moderately\\*\\*  \n   /  \\\\\n"
        '"""\n\nfilename \\= "x.md"\n### **Key Improvements Implemented**\n> 1. Restored Section 4\n'
    )
    cleaned = kb.clean_friel(raw)
    assert cleaned == "# Training Bible\n## Core Reference\n1. **Train Moderately**\n   /  \\\n"


def test_racing_weight_front_matter_becomes_metadata():
    raw = (
        '---\nsource: "Racing Weight"\nchapter: "Chapter 4: Step 1 – Improving Your Diet Quality"\n'
        "tags: [DQS]\n---\n\n# Chapter 4: Improving Your Diet Quality\n\nBody.\n"
    )
    rel, text, metadata = kb.racing_weight_doc("chapter_04_improving_your_diet_quality.md", raw)
    assert rel == "library/nutrition/racing-weight/chapter-04-improving-your-diet-quality.md"
    assert text.startswith("# Racing Weight (2nd ed.): Chapter 4: Improving Your Diet Quality")
    assert "tags:" not in text
    assert metadata["chapter"] == 4
    assert metadata["section"] == "Chapter 4: Step 1 – Improving Your Diet Quality"
    assert metadata["domain"] == "nutrition"


def test_front_matter_after_html_comment_is_removed():
    raw = '<!-- METADATA BLOCK -->\n---\nchapter: "Chapter 00: Preface"\n---\n\n# Preface\n'
    rel, text, metadata = kb.racing_weight_doc("chapter_00_preface.md", raw)
    assert text == "# Racing Weight (2nd ed.): Preface\n"
    assert metadata["section"] == "Chapter 00: Preface"


TABLE_MARKDOWN = (
    "# Racing Weight: Chapter 4\n\n## Structured Data\n\n### Table 4.1: Diet Score\n\n"
    "| Tier | Category | 1st Serving | 2nd Serving |\n"
    "| :--- | :--- | :---: | ---: |\n"
    "| High Quality | **Fruits** | +2 | +1 |\n"
    "| Low Quality | Fatty proteins | -1 | -2 |\n"
    "| Low Quality | Sweets | -2 | -2 |\n\n"
    "## Notes\n\n| A | B |\n|---|---|\n| x \\| y | |\n"
)


def test_extract_tables_leaves_pointers_and_keeps_heading_paths():
    text, tables = kb.extract_tables(TABLE_MARKDOWN)
    assert "|" not in text.replace("x | y", "")
    assert "_(Table 4.1, Diet Score: indexed as a separate table document.)_" in text
    assert "_(Notes: indexed as a separate table document.)_" in text
    first, second = tables
    assert first.path == ["Racing Weight: Chapter 4", "Structured Data"]
    assert first.caption == "Table 4.1, Diet Score"
    assert first.rows[1] == ["Low Quality", "Fatty proteins", "-1", "-2"]
    assert second.caption == "Notes"
    assert second.rows == [["x | y", ""]]


def test_table_doc_keeps_signs_and_summarises_rows():
    _, tables = kb.extract_tables(TABLE_MARKDOWN)
    assert kb.table_doc(tables[0], "Racing Weight, by Matt Fitzgerald") == (
        "# Racing Weight: Chapter 4: Table 4.1, Diet Score\n\n"
        "Source: Racing Weight, by Matt Fitzgerald\n\n"
        "_Structured Data_\n\n"
        "Table 4.1, Diet Score, a table of 3 rows with the columns Tier, Category, 1st Serving, 2nd Serving. "
        "Rows: Fruits, Fatty proteins, Sweets.\n\n"
        "- Tier: High Quality; Category: Fruits; 1st Serving: +2; 2nd Serving: +1\n"
        "- Tier: Low Quality; Category: Fatty proteins; 1st Serving: -1; 2nd Serving: -2\n"
        "- Tier: Low Quality; Category: Sweets; 1st Serving: -2; 2nd Serving: -2\n"
    )


def test_short_cuts_on_a_word_boundary():
    assert kb._short("Green – Very Fresh: Low & High systems prepared", 20) == "Green – Very Fresh…"
    assert kb._short("Endurance", 20) == "Endurance"


def test_tidy_turns_inline_latex_into_text_but_leaves_currency():
    assert kb.tidy("about $\\approx 1.3\\text{ g/kg/day}$ of protein") == "about ≈ 1.3 g/kg/day of protein\n"
    assert kb.tidy("BMI $18.5–24.9$ and $>10\\%$ fat") == "BMI 18.5–24.9 and >10% fat\n"
    assert kb.tidy("$$W = \\frac{LBM}{0.88}$$") == "W = (LBM) / (0.88)\n"
    assert kb.tidy("costs upward of $10,000 per unit") == "costs upward of $10,000 per unit\n"


GOOGLE_DOC = (
    "Intro with fat \\+ sugar and 2016 \\- trial.\n\n"
    "## **Part 1: Strategies**\n\n### **Layer 1: Food**\n\nEat slowly.![chart](x.png)\n\n"
    "| Tool | Protocol |\n| :---- | :---- |\n| **If-Then** | Brew tea<br>wait 15 min |\n\n"
    "## **Part 2: Building a RAG corpus**\n\n### Tier 1\n\nRAG Utility: ignore.\n\n"
    "## **Interactive Architecture: Simulator**\n\nUse the simulator.\n"
)


def test_eating_behaviour_doc_cleans_google_export_and_drops_kb_sections():
    rel, text, metadata, dropped = kb.eating_behaviour_doc("Avoiding Binge-Eating.md", GOOGLE_DOC)
    assert rel == "library/eating_behaviour/avoiding-binge-eating.md"
    assert text.startswith("# Avoiding Binge-Eating\n\nIntro with fat + sugar and 2016 - trial.")
    assert "## Part 1: Strategies" in text and "### Layer 1: Food" in text
    assert "| **If-Then** | Brew tea; wait 15 min |" in text
    for gone in ("x.png", "RAG", "simulator", "Tier 1"):
        assert gone not in text
    assert dropped == ["Part 2: Building a RAG corpus", "Interactive Architecture: Simulator"]
    assert metadata == {"domain": "eating_behaviour", "source_type": "strategy", "title": "Avoiding Binge-Eating"}

    _, tables = kb.extract_tables(text)
    assert tables[0].caption == "Layer 1: Food"
    assert tables[0].rows == [["If-Then", "Brew tea; wait 15 min"]]

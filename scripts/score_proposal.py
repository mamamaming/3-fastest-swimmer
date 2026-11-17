"""Score one proposal for C5 (docs/SPEC.md, ภาคผนวก ค). Owner: Ming.

Scores the parts code can check, and leaves blank columns for the parts people score:
  - complete:  all 12 CSII sections are there and not empty (11 when no budget is requested)
  - budget:    the request items add up to the Total (rounded up by at most one step), the Total in
               words and in "Total budget: N baht" match it, and the club budget's remaining amount
               equals the initial budget minus every project
  - sourced:   every number and every "Mr./Ms./Dr. Name" in the AI-written text also appears in the
               form (brief) or the library files; anything else is listed for a person to look at

Works on the app's .docx and on an old proposal .pdf, so the real proposal can be scored the same
way as the app's version.

    python scripts/score_proposal.py OUT.docx --brief data/briefs/X.json \
        --facts uploads/club-facts.md --library uploads/ --hide realbiz --label "RealBiz (app)"

--library takes files or folders. --hide drops library files whose name contains that word, so the
proposal being rewritten is not counted as a source. Hiding Inclusive Workshop 2 or Members Only
Workshop 1 also needs --hide merged. Each run adds a row to --csv (default data/eval/results.csv).
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import logging  # noqa: E402

from config import BUDGET_TOTAL_ROUND_UP_TO, DATA_FOLDER  # noqa: E402
from export import baht_words  # noqa: E402

# The 12 numbered sections of the CSII form, with the words that start each heading.
SECTIONS = [
    ("1 Introduction", r"introduction"),
    ("2 Objectives", r"objectives"),
    ("3 Type of Activity", r"type of activity"),
    ("4 Project Duration", r"project duration"),
    ("5 Facilities Needed", r"facilities needed"),
    ("6 Benefits", r"benefits for"),
    ("7 Activity KPIs", r"activity key performance"),
    ("8 Desired Characteristics", r"desired characteristics of chulalongkorn"),
    ("9 Schedule", r"schedule"),
    ("10 Responsibilities", r"responsibilities"),
    ("11 Project Budget", r"project budget"),
    ("12 CSII Budget Resource", r"csii budget resource"),
]
AI_SECTIONS = ["introduction", "objectives", "benefits", "activity_kpis", "characteristics", "schedule", "facilities"]
MONEY = re.compile(r"(?<![\d,])\d{1,3}(?:,\d{3})*\.\d{2}(?!\d)")
NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?")
PERSON = re.compile(r"\b(?:Mr|Ms|Mrs|Dr|Asst\. Prof|Assoc\. Prof|Prof)\.\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?")
HUMAN_COLUMNS = ["clarity_1to5", "specific_1to5", "persuasive_1to5", "guessed_ai_correctly",
                 "form_fields_filled", "minutes_to_fill"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("proposal", type=Path, help=".docx from the app, or an old proposal .pdf/.docx")
    ap.add_argument("--brief", type=Path, help="event brief JSON the app used (needed for 'sourced')")
    ap.add_argument("--facts", type=Path, help="club-facts.md")
    ap.add_argument("--library", type=Path, nargs="*", default=[], help="library files or folders")
    ap.add_argument("--hide", nargs="*", default=[], help="skip library files whose name contains these words")
    ap.add_argument("--label", default="", help="row name in the results table")
    ap.add_argument("--csv", type=Path, default=DATA_FOLDER / "eval" / "results.csv")
    args = ap.parse_args()
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # old PDFs print harmless repair notes

    text = read_text(args.proposal)
    brief = json.loads(args.brief.read_text(encoding="utf-8")) if args.brief else None

    # No-budget events (Inclusive Workshop 1, First Meet) drop section 11; CSII Budget Resource becomes 11.
    # ("Budget Request" alone is no sign: the Appendix of every proposal has that title.)
    has_budget = bool(re.search(r"^\s*(?:\d+\.?\s*)?project budget", text, re.I | re.M))
    found, missing = score_sections(text, has_budget)
    expected = len(SECTIONS) - (0 if has_budget else 1)
    budget_issues = score_budget(text) if has_budget else []
    unsourced = None
    if brief is not None:
        sources = source_text(brief, args.facts, library_files(args.library, args.hide))
        unsourced = score_sourced(ai_text(brief, text), sources)

    print(f"Proposal: {args.proposal.name}")
    print(f"Complete: {found}/{expected}" + (f"  missing or empty: {', '.join(missing)}" if missing else ""))
    print("Budget:   " + ("no budget requested" if not has_budget else "correct" if not budget_issues else "PROBLEMS"))
    for issue in budget_issues:
        print(f"  - {issue}")
    if unsourced is None:
        print("Sourced:  skipped (no --brief)")
    else:
        print(f"Sourced:  {len(unsourced)} item(s) not found in the form or library" + (" — check each:" if unsourced else ""))
        for item in unsourced:
            print(f"  - {item}")

    row = {
        "label": args.label or args.proposal.stem, "file": args.proposal.name,
        "sections_found": f"{found}/{expected}", "sections_missing": "; ".join(missing),
        "budget_correct": "n/a" if not has_budget else "yes" if not budget_issues else "no",
        "budget_issues": "; ".join(budget_issues),
        "unsourced_count": "" if unsourced is None else len(unsourced),
        "unsourced": "" if unsourced is None else "; ".join(unsourced),
        **{c: "" for c in HUMAN_COLUMNS},
    }
    write_row(args.csv, row)
    print(f"Row added to {args.csv} (fill in the people-scored columns there)")


# ---------- reading ----------

def read_text(path):
    """Plain text in reading order; table rows become 'cell | cell | cell'."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    if path.suffix.lower() == ".docx":
        import docx
        from docx.oxml.ns import qn

        def walk(el):
            for c in el.iterchildren():
                if c.tag == qn("w:p"):
                    yield "".join(_run_text(c, qn))
                elif c.tag == qn("w:tbl"):
                    for r in c.iter(qn("w:tr")):
                        yield " | ".join("".join(_run_text(tc, qn)) for tc in r.iter(qn("w:tc")))
                elif c.tag == qn("w:sdt"):
                    yield from walk(c)
        return "\n".join(line for line in walk(docx.Document(str(path)).element.body) if line.strip())
    return path.read_text(encoding="utf-8")


def _run_text(el, qn):
    for x in el.iter(qn("w:t"), qn("w:tab"), qn("w:br")):
        yield (x.text or "") if x.tag == qn("w:t") else " "


def library_files(paths, hide):
    out = []
    for p in paths:
        files = sorted(p.rglob("*")) if p.is_dir() else [p]
        out += [f for f in files if f.is_file() and f.suffix.lower() in (".pdf", ".docx", ".md", ".txt")
                and not any(h.lower() in f.name.lower() for h in hide)]
    return out


# ---------- complete ----------

def score_sections(text, has_budget=True):
    lines = [l.strip() for l in text.splitlines()]
    sections = [s for s in SECTIONS if has_budget or s[1] != "project budget"]
    starts = []
    for name, pattern in sections:
        rx = re.compile(rf"^(?:\d+\.?\s*)?{pattern}", re.I)
        idx = next((i for i, l in enumerate(lines) if rx.match(l) and (not starts or i > starts[-1][1])), None)
        starts.append((name, idx if idx is not None else (starts[-1][1] if starts else -1)))
    found, missing = 0, []
    for k, (name, idx) in enumerate(starts):
        pattern = sections[k][1]
        if idx < 0 or not re.match(rf"^(?:\d+\.?\s*)?{pattern}", lines[idx], re.I):
            missing.append(name)
            continue
        end = next((s for _, s in starts[k + 1:] if s > idx), len(lines))
        # The heading line may carry its content (the Desired Characteristics checkboxes do).
        body = [l for l in [re.sub(rf"^(?:\d+\.?\s*)?{pattern}", "", lines[idx], flags=re.I)] + lines[idx + 1:end]
                if l and not re.fullmatch(r"\[TO CONFIRM[^\]]*\]", l)]
        if body:
            found += 1
        else:
            missing.append(name)
    return found, missing


# ---------- budget ----------

def score_budget(text):
    issues = []
    request = _between(text, r"(?:11\.2\s*)?budget request", r"csii budget resource")
    if not request:
        return ["Budget Request (11.2) not found"]
    lines = request.splitlines()
    total_idx = next((i for i, l in enumerate(lines) if re.match(r"\s*total\b", l, re.I) and MONEY.search(l)), None)
    if total_idx is None:
        return ["no Total line with an amount in 11.2"]
    items = [_money(m) for l in lines[:total_idx] for m in MONEY.findall(l)]
    total = _money(MONEY.findall(lines[total_idx])[-1])
    items_sum = round(sum(items), 2)
    step = BUDGET_TOTAL_ROUND_UP_TO or 1
    if not (items_sum <= total < items_sum + step):
        issues.append(f"items add up to {items_sum:,.2f} but the Total is {total:,.2f}")
    words = next((l for l in lines[total_idx:] if "baht only" in l.lower()), None)
    if words and _norm(words) != _norm(baht_words(total)):
        issues.append(f"Total in words '{words.strip()}' does not match {total:,.2f}")
    stated = re.search(r"total budget:\s*([\d,]+(?:\.\d+)?)", request, re.I)
    if stated and _money(stated.group(1)) != total:
        issues.append(f"'Total budget: {stated.group(1)}' does not match the Total {total:,.2f}")

    club = _between(text, r"(?:11\.1\s*)?club budget", r"(?:11\.2\s*)?budget request")
    initial = remaining = None
    projects = []
    for l in club.splitlines():
        amounts = MONEY.findall(l)
        if not amounts:
            continue
        if re.search(r"initial budget", l, re.I):
            initial = _money(amounts[-1])
        elif re.search(r"remaining", l, re.I):
            remaining = _money(amounts[-1])
        else:
            projects.append(_money(amounts[-1]))
    if initial is not None and remaining is not None:
        expected = round(initial - sum(projects), 2)
        if expected != remaining:
            issues.append(f"club budget: {initial:,.2f} minus projects {sum(projects):,.2f} is "
                          f"{expected:,.2f}, but Remaining says {remaining:,.2f}")
    return issues


def _between(text, start, end):
    m = re.search(start, text, re.I)
    if not m:
        return ""
    e = re.search(end, text[m.end():], re.I)
    return text[m.end(): m.end() + e.start()] if e else text[m.end():]


def _money(s):
    return float(str(s).replace(",", ""))


def _norm(s):
    return re.sub(r"[^a-z]", "", s.lower())


# ---------- sourced ----------

def ai_text(brief, document_text):
    """The AI-written sections, from the brief the app filled."""
    sections = brief.get("sections") or {}
    parts = [_flatten(sections.get(s)) for s in AI_SECTIONS]
    if any(parts):
        return "\n".join(parts)
    return document_text  # an old proposal: no AI text, check the whole thing


def source_text(brief, facts_path, files):
    form = {k: v for k, v in brief.items() if k not in ("sections", "to_confirm")}
    parts = [_flatten(form)]
    if facts_path:
        parts.append(Path(facts_path).read_text(encoding="utf-8"))
    parts += [read_text(f) for f in files]
    return "\n".join(parts)


def score_sourced(ai, sources):
    source_numbers = {_num_key(n) for n in NUMBER.findall(sources)}
    flat_sources = re.sub(r"\s+", " ", sources).lower()
    out = []
    for n in NUMBER.findall(ai):
        if _num_key(n) not in source_numbers and n not in out:
            out.append(n)
    for p in PERSON.findall(ai):
        if re.sub(r"\s+", " ", p).lower() not in flat_sources and p not in out:
            out.append(p)
    return out


def _num_key(n):
    """'1,100' == '1100' == '1100.00'; '80%' == '80'."""
    n = n.rstrip("%").replace(",", "").rstrip(".")
    try:
        return f"{float(n):g}"
    except ValueError:
        return n


def _flatten(value):
    if isinstance(value, dict):
        return "\n".join(_flatten(v) for v in value.values())
    if isinstance(value, list):
        return "\n".join(_flatten(v) for v in value)
    return "" if value is None else str(value)


def write_row(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)


if __name__ == "__main__":
    main()

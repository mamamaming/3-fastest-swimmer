"""Check C1 + C2 + C4 without the AI or the real club file.

Fills samples/brief.example.json with made-up section text, builds the .docx with made-up club
facts, and checks the budget totals and the consistency warnings.

Run: python scripts/check_export.py   (writes samples/out/example.docx, git-ignored)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from checker import check_brief  # noqa: E402
from export import baht_words, build_context, fill_docx  # noqa: E402
from score_proposal import read_text, score_budget, score_sections, score_sourced  # noqa: E402

# Same shape as knowledge.load_club_facts(): one key per "## " heading, tables -> list of dicts.
FAKE_FACTS = {
    "Club": {"Name": "BAScii Business Competition Club (BizComp)", "Academic year": "AY2026 (August 2026 – May 2027)"},
    "Advisor": [{"Title": "Dr.", "First name": "Anong", "Last name": "Sample", "Role": "Club Advisor"}],
    "Officers": [
        {"Title": "Ms.", "First name": "Kanya", "Last name": "Example", "Role": "President"},
        {"Title": "Mr.", "First name": "Somchai", "Last name": "Placeholder", "Role": "Vice President"},
        {"Title": "Ms.", "First name": "Pim", "Last name": "Testdata", "Role": "Treasurer"},
    ],
    "School KPIs": [
        {"Code": "KPI1", "KPI": "Foster the growth of 10 student-led innovation ventures"},
        {"Code": "KPI3", "KPI": "Maintain stakeholder satisfaction above 80%"},
    ],
    "Fund codes (CSII Budget Resource)": [{"Code": "0000000001", "Name": "Sample Activities Fund"}],
    "Budget AY2026": [
        {"Project": "RealBiz Project", "Planned (THB)": "31,500"},
        {"Project": "BizTour", "Planned (THB)": "21,300"},
        {"Project": "Workshops (total)", "Planned (THB)": "3,500"},
        {"Project": "HSBC Training Program", "Planned (THB)": "3,300"},
    ],
    "Proposal signatories": {
        "Club Advisor": "Dr. Anong Sample",
        "Responsible Officer": "Ms. Officer Example",
        # Keys over 60 characters stay as text in load_club_facts().
        "text": ["Assistant to Executive Director, Academics and Student Development: Dr. Director Example"],
    },
    # "Key: value" lines next to a table land here, as in load_club_facts().
    "notes": {
        "Budget AY2026": {
            "Starting budget": "60,000 THB. Amounts set aside per project.",
            "Workshop split": "Inclusive workshop 1 = 0 · Inclusive workshop 2 = 1,100 · Exclusive workshop 1 = 1,100",
        },
    },
}

FAKE_SECTIONS = {
    "introduction": "The First Inclusive Workshop of BizComp AY2026 is an introductory workshop for 51 people.",
    "objectives": ["Introduce BizComp and its opportunities.", "Teach pitch deck structure."],
    "benefits": ["Strengthens the BAScii learning ecosystem.", "Expands BAScii's professional network."],
    "activity_kpis": ["Workshop attendance over 35 people", "Participants satisfaction rate ≥ 3.8/5.0"],
    "characteristics": {"ticked": ["Knowledgeable", "Analytical Thinking"], "explanation": "Sample explanation."},
    "schedule": [
        {"time": "2nd Week of September", "activity": "Finding Mentor", "description": "Mentor's representative"},
        {"time": "3rd Week of October", "activity": "D-Day", "description": "Day of the workshop"},
    ],
    "facilities": ["Projector and screen", "Paper 30", "Pen 30"],
}


def main():
    brief = json.loads((ROOT / "samples" / "brief.example.json").read_text())
    brief["sections"] = FAKE_SECTIONS

    scalars, lists, rows = build_context(brief, FAKE_FACTS)
    assert scalars["total_participants"] == "51", scalars["total_participants"]
    # Items add up to 1,099 (240 + 230 + 129 + 500); CSII asks for a total rounded up to 100.
    assert scalars["budget_total"] == "1,100.00", scalars["budget_total"]
    assert scalars["budget_total_words"] == "One Thousand One Hundred baht only"
    assert scalars["budget_remaining"] == "400.00", scalars["budget_remaining"]
    assert scalars["assistant_director"] == "Dr. Director Example", scalars["assistant_director"]
    assert "Inclusive workshop 2\t1,100 THB" in rows["club_budget"][2][0], rows["club_budget"][2][0]

    # The real reader (A4) on its made-up file, when knowledge.py is there.
    try:
        from knowledge import load_club_facts
    except ImportError:
        load_club_facts = None
    if load_club_facts:
        example = load_club_facts(ROOT / "samples" / "club-facts.example.md")
        s, _, _ = build_context(brief, example)
        assert (s["budget_initial"], s["budget_remaining"]) == ("10,000.00", "1,000.00"), s["budget_initial"]
        assert s["assistant_director"] == "Dr. Example Director", s["assistant_director"]
    assert [r[2] for r in rows["budget_rows"]] == ["240.00", "230.00", "129.00", "500.00"]
    assert baht_words(12.5) == "Twelve baht and Fifty satang only"
    assert baht_words(31_500) == "Thirty-One Thousand Five Hundred baht only"

    out = ROOT / "samples" / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "example.docx").write_bytes(fill_docx(brief, FAKE_FACTS))

    warnings = check_brief(brief)
    for w in warnings:
        print("WARN", w)
    joined = "\n".join(warnings)
    assert "Pen: 30 for 51 people" in joined, "spec check: 30 pens for 51 people must warn"
    assert "3rd Week of October" in joined, "event-day week must warn (12 Oct is week 2)"
    assert "Check: Introduction says 'The First Inclusive Workshop'" in joined, "ordinal must ask a person"
    numbered = json.loads(json.dumps(brief))
    numbered["sections"]["introduction"] = "BizComp Inclusive Workshop 3 opens to all students."
    assert any(w.startswith("Introduction says") for w in check_brief(numbered)), "wrong number must warn"

    # RealBiz style: lump-sum items (qty 1) never warn; meals x days compare per day.
    lump = json.loads(json.dumps(brief))
    lump["budget_items"] = [{"item": "Pen", "qty": 1, "unit_price": 230},
                            {"item": "Food (20 participants x 2 days)", "qty": 40, "unit_price": 240}]
    lump_warnings = check_brief(lump)
    assert not any(w.startswith("Pen: 1 ") for w in lump_warnings), lump_warnings
    assert any("20 per day for 51 people" in w for w in lump_warnings), lump_warnings

    clean = json.loads(json.dumps(brief))
    clean["sections"]["introduction"] = "BizComp Inclusive Workshop 2 is an introductory workshop."
    clean["sections"]["schedule"][1]["time"] = "2nd Week of October"
    clean["sections"]["facilities"] = ["Projector and screen", "Paper 51", "Pen 51"]
    assert check_brief(clean) == [], check_brief(clean)

    # C2, no budget: section 11 and the Quotations page go, as in the real no-budget proposals.
    no_budget = json.loads(json.dumps(brief))
    no_budget["budget_items"] = []
    (out / "no-budget.docx").write_bytes(fill_docx(no_budget, FAKE_FACTS))
    text = read_text(out / "no-budget.docx")
    lines = [l.strip() for l in text.splitlines()]
    assert not any(l.startswith(("Project Budget", "11.2", "Quotations")) for l in lines), "section 11 still there"
    assert "CSII Budget Resource" in text
    assert score_sections(text, has_budget=False) == (11, []), score_sections(text, has_budget=False)

    # C5 scorer: the app's file scores 12/12 and a correct budget; RealBiz-style mistakes are caught.
    text = read_text(out / "example.docx")
    assert score_sections(text) == (12, []), score_sections(text)
    assert score_budget(text) == [], score_budget(text)
    realbiz_like = ("Club Budget\nInitial Budget AY2026 60,000.00 THB\nRealBiz Project 31,500.00 THB\n"
                    "Biztour 21,300.00 THB\nRemaining Budget for AY2026 28,500.00 THB\n"
                    "Budget Request\n1 Food 10,560.00\n2 Pens 2,970.00\nTotal 30,000.00\n"
                    "(Thirty Thousand baht only)\nCSII Budget Resource\n")
    issues = score_budget(realbiz_like)
    assert any("items add up to 13,530.00" in i for i in issues), issues
    assert any("Remaining says 28,500.00" in i for i in issues), issues
    made_up = score_sourced("Hosted by Dr. Somsak Invented for 77 people on 12 October.",
                            "BizComp Inclusive Workshop 2 · 12 October 2026 · 51 people")
    assert made_up == ["77", "Dr. Somsak Invented"], made_up

    print("OK: totals correct, warnings fire, clean brief passes ->", out / "example.docx")


if __name__ == "__main__":
    main()

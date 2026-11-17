"""Fill the CSII Word template from the event brief and club facts. Owner: Ming.

The template (templates/proposal_template.docx) uses three kinds of placeholder:
  {{name}}             replaced by a value; always the whole text of one run
  {{#name}} paragraph  cloned once per item of a list (Objectives, Benefits, ...)
  {{#name}} row        a table row starting with this is cloned once per row of a table

All numbers (participant total, budget lines, totals, remaining club budget) are computed
here from the brief and club facts. Text written by the AI is copied in as is.
"""
import io
import math
import re
from copy import deepcopy
from datetime import date
from pathlib import Path

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

from config import BUDGET_TOTAL_ROUND_UP_TO
from knowledge import committee

TEMPLATE = Path(__file__).parent / "templates" / "proposal_template.docx"

DEFAULT_CHARACTERISTICS = [
    ("Knowledgeable", "Helps students gain or apply academic or professional knowledge"),
    ("Ethical", "Promotes integrity, responsibility, and respectful behavior"),
    ("Analytical Thinking", "Encourages critical thinking and problem-solving"),
    ("Capable", "Develops practical skills such as planning, teamwork, and execution"),
    ("Lifelong Learner", "Encourages curiosity and continuous learning"),
    ("Leadership", "Provides opportunities for students to lead and collaborate with others"),
    ("Healthy", "Supports physical or mental well-being"),
    ("Social Responsibility", "Encourages contribution to society or the community"),
    ("Global Mindset", "Promotes awareness of diverse cultures and global perspectives"),
]


# ---------- public ----------

def fill_docx(brief, facts):
    """Return the finished proposal as .docx bytes (C1 + C2). Budget numbers come from code, never from AI text.

    brief: the event brief (docs/SPEC.md, ภาคผนวก ข).
    facts: load_club_facts() output — one key per "## " heading of club-facts.md; tables are lists
           of dicts keyed by column name; "- Key: value" lines are dict entries.
    """
    scalars, lists, rows = build_context(brief, facts or {})
    doc = docx.Document(str(TEMPLATE))
    _fill(doc, scalars, lists, rows)
    if not brief.get("budget_items"):
        _drop_budget(doc)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_context(brief, facts):
    """Everything the template needs, as (scalars, lists, rows). Separate from fill_docx so it can be tested."""
    sections = brief.get("sections") or {}
    participants = brief.get("participants") or []
    total_people = sum(_num(p.get("count")) for p in participants)

    budget = budget_lines(brief.get("budget_items") or [])
    club = club_budget(facts)

    sig = _section(facts, "proposal signatories") or {}
    advisors = _rows(_section(facts, "advisor"))
    advisor_name = _get(sig, "club advisor") or (_person(advisors[0]) if advisors else "")

    scalars = {
        "event_name": brief.get("event_name", ""),
        "date_time": format_date_time(brief.get("date", ""), brief.get("time", ""), brief.get("end_date", "")),
        "total_participants": _int_str(total_people),
        "location": brief.get("location", ""),
        "introduction": sections.get("introduction", ""),
        "characteristics_explanation": (sections.get("characteristics") or {}).get("explanation", ""),
        "academic_year": club["academic_year"],
        "budget_initial": _money(club["initial"]) if club["initial"] is not None else "[TO CONFIRM: initial budget]",
        "budget_remaining": _money(club["remaining"]) if club["remaining"] is not None else "[TO CONFIRM: remaining budget]",
        "budget_total": _money(budget["requested"]),
        "budget_total_short": _money(budget["requested"], decimals=False),
        "budget_total_words": baht_words(budget["requested"]),
        "proposer": brief.get("proposer", ""),
        "advisor_name": advisor_name,
        "responsible_officer": _get(sig, "responsible officer"),
        "assistant_director": _get(sig, "assistant to executive director"),
    }

    lists = {
        "participants": [f"{p.get('group', '')} – {_int_str(_num(p.get('count')))} "
                         f"{'person' if _num(p.get('count')) == 1 else 'people'}" for p in participants],
        "objectives": [f"2.{i} {t}" for i, t in enumerate(_strings(sections.get("objectives")), 1)],
        "facilities": [_facility(f) for f in sections.get("facilities") or []],
        "school_kpis": [f"{i}. {r.get('KPI', '')}" for i, r in enumerate(_rows(_section(facts, "school kpis")), 1)],
        "benefits": [f"6.{i} {t}" for i, t in enumerate(_strings(sections.get("benefits")), 1)],
        "activity_kpis": _strings(sections.get("activity_kpis")),
        "advisors": [f"10.1.{i}. {_person_columns(r)}" for i, r in enumerate(advisors, 1)],
        "officers": [f"10.2.{i}. {line}" for i, line in enumerate(committee_lines(brief, facts), 1)],
        "characteristics": characteristic_lines(sections.get("characteristics") or {}, facts),
        "fund_codes": [f"{r.get('Code', '')} {r.get('Name', '')}" for r in _rows(_section(facts, "fund codes"))],
    }

    rows = {
        "schedule": [_schedule_row(s) for s in sections.get("schedule") or []],
        "club_budget": [[name + "".join(f"\n{sub}\t{_money(a, decimals=False)} THB" for sub, a in subs),
                         _money(amount), "THB"] for name, amount, subs in club["projects"]],
        "budget_rows": [[str(i), line["label"], _money(line["total"])] for i, line in enumerate(budget["lines"], 1)],
        "quotations": [[line["item"], f"{_fmt_num(line['qty'])} × {_money(line['unit_price'], decimals=False)} THB",
                        "(attach quotation)"] for line in budget["lines"]],
    }
    return scalars, lists, rows


def budget_lines(items):
    """qty × unit price per item, the exact total, and the requested total rounded up as CSII asks."""
    lines = []
    for it in items:
        qty, price = _num(it.get("qty")), _num(it.get("unit_price"))
        total = round(qty * price, 2)
        lines.append({
            "item": it.get("item", ""), "qty": qty, "unit_price": price, "total": total,
            "label": f"{it.get('item', '')}\n{_money(price, decimals=False)} THB × {_fmt_num(qty)}",
        })
    total = round(sum(l["total"] for l in lines), 2)
    step = BUDGET_TOTAL_ROUND_UP_TO or 1
    return {"lines": lines, "total": total, "requested": math.ceil(total / step - 1e-9) * step}


def club_budget(facts):
    """Initial budget, planned projects and what remains, from the club facts."""
    club = _section(facts, "club") or {}
    year = (_get(club, "academic year") or "").split(" ")[0] or "[TO CONFIRM: academic year]"
    sec = _section(facts, "budget")
    # load_club_facts() puts the table in facts[heading] and "Key: value" lines next to it in
    # facts["notes"][heading]; read both.
    notes = _section(facts.get("notes") or {}, "budget") or {}
    initial = None
    projects = []
    split = []
    if isinstance(sec, list):
        sec = {"_table": sec}
    if isinstance(sec, dict):
        for k, v in {**notes, **sec}.items():
            if "starting budget" in k.lower() or "initial budget" in k.lower():
                initial = _parse_money(v)
            elif "workshop split" in k.lower():
                split = _split_line(v)
            elif isinstance(v, list) and any(isinstance(r, dict) for r in v):
                projects = _project_rows(v)
    projects = [(name, amount, split if name.lower().startswith("workshop") else [])
                for name, amount in projects]
    remaining = None if initial is None else round(initial - sum(a for _, a, _ in projects), 2)
    return {"academic_year": year, "initial": initial, "projects": projects, "remaining": remaining}


def format_date_time(iso_date, time, end_date=""):
    """'2026-10-12', '16:30-18:30' -> '12th October 2026, 16:30-18:30'.

    With an end date: '12th–13th October 2026, ...' (same month) or
    '30th October – 2nd November 2026, ...'.
    """
    def ordinal(n):
        return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"

    try:
        d = date.fromisoformat(iso_date)
        text = f"{ordinal(d.day)} {d.strftime('%B')} {d.year}"
        if end_date:
            e = date.fromisoformat(end_date)
            if (e.year, e.month) == (d.year, d.month):
                text = f"{ordinal(d.day)}–{ordinal(e.day)} {d.strftime('%B')} {d.year}"
            elif e.year == d.year:
                text = f"{ordinal(d.day)} {d.strftime('%B')} – {ordinal(e.day)} {e.strftime('%B')} {e.year}"
            else:
                text = f"{text} – {ordinal(e.day)} {e.strftime('%B')} {e.year}"
    except (TypeError, ValueError):
        text = iso_date or "[TO CONFIRM: date]"
    return f"{text}, {time}" if time else text


def committee_lines(brief, facts):
    """10.2: the 4 core officers, then the members of the department in charge (brief["department"]).

    A long project lists its own project team, which the form does not collect yet, so it gets a
    [TO CONFIRM] line when no department is chosen.
    """
    department = (brief.get("department") or "").strip()
    lines = [_person_columns(r) for r in committee(facts, department or None)]
    if not department and brief.get("event_type") == "long project":
        lines.append("[TO CONFIRM: project team (Project Director, Project Leader, Project Members)]")
    return lines


def characteristic_lines(characteristics, facts):
    """Nine (box, text) pairs; ticked ones come from the AI's list."""
    table = _rows(_section(facts, "desired characteristics"))
    options = [(r.get("Characteristic", ""), r.get("Meaning", "")) for r in table] or DEFAULT_CHARACTERISTICS
    ticked = {t.strip().lower() for t in characteristics.get("ticked") or []}
    return [("☑" if name.lower() in ticked else "☐", f" {name} – {meaning.rstrip('.')}.") for name, meaning in options]


ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven",
        "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def number_words(n):
    """Whole number to English words, e.g. 1100 -> 'One Thousand One Hundred'."""
    n = int(n)
    if n == 0:
        return "Zero"
    parts = []
    for value, name in ((1_000_000_000, "Billion"), (1_000_000, "Million"), (1_000, "Thousand")):
        if n >= value:
            parts.append(f"{number_words(n // value)} {name}")
            n %= value
    if n >= 100:
        parts.append(f"{ONES[n // 100]} Hundred")
        n %= 100
    if n >= 20:
        parts.append(TENS[n // 10] + (f"-{ONES[n % 10]}" if n % 10 else ""))
    elif n:
        parts.append(ONES[n])
    return " ".join(parts)


def baht_words(amount):
    """1100 -> 'One Thousand One Hundred baht only'; 12.5 -> '... baht and Fifty satang only'."""
    baht = int(round(amount * 100)) // 100
    satang = int(round(amount * 100)) % 100
    text = f"{number_words(baht)} baht"
    if satang:
        text += f" and {number_words(satang)} satang"
    return text + " only"


# ---------- filling the document ----------

def _fill(doc, scalars, lists, rows):
    body = doc.element.body
    for p_el in list(body.iter(docx.oxml.ns.qn("w:p"))):
        p = Paragraph(p_el, doc)
        text = p.text.strip()
        m = re.fullmatch(r"\{\{#(\w+)\}\}", text)
        if m and m.group(1) in lists and not _in_table(p_el):
            _clone_paragraph(p_el, lists[m.group(1)])
    for t_el in list(body.iter(docx.oxml.ns.qn("w:tbl"))):
        table = Table(t_el, doc)
        for row in list(table.rows):
            m = re.fullmatch(r"\{\{#(\w+)\}\}", row.cells[0].text.strip())
            if m and m.group(1) in rows:
                _clone_row(row, rows[m.group(1)], doc)
    _fill_checkboxes(doc, lists.get("characteristics") or [])
    for p_el in body.iter(docx.oxml.ns.qn("w:p")):
        for run in Paragraph(p_el, doc).runs:
            if "{{" in run.text:
                run.text = re.sub(r"\{\{(\w+)\}\}", lambda m: str(scalars.get(m.group(1), m.group(0))), run.text)


def _drop_budget(doc):
    """No budget requested: remove section 11 and the Quotations page, as the real no-budget
    proposals do (Inclusive Workshop 1, First Meet). Headings use Word numbering, so
    'CSII Budget Resource' becomes 11 by itself."""
    kids = list(doc.element.body.iterchildren())
    texts = ["".join(t.text or "" for t in k.iter(docx.oxml.ns.qn("w:t"))).strip() for k in kids]
    start = next((i for i, t in enumerate(texts) if t.startswith("Project Budget")), None)
    end = next((i for i, t in enumerate(texts) if t.startswith("CSII Budget Resource")), None)
    drop = list(range(start, end)) if start is not None and end is not None and start < end else []
    quot = next((i for i, t in enumerate(texts) if t == "Quotations"), None)
    if quot is not None:
        first = quot
        # the "Appendix" title and the page break before it belong to the Quotations page
        while first > 0 and (texts[first - 1] in ("Appendix", "")) and first - 1 > (drop[-1] if drop else 0):
            first -= 1
            if texts[first] == "" and any(b.get(docx.oxml.ns.qn("w:type")) == "page"
                                          for b in kids[first].iter(docx.oxml.ns.qn("w:br"))):
                break
        drop += [i for i in range(first, len(kids))
                 if kids[i].tag != docx.oxml.ns.qn("w:sectPr")
                 and kids[i].find(".//" + docx.oxml.ns.qn("w:sectPr")) is None]
    for i in drop:
        doc.element.body.remove(kids[i])


def _clone_paragraph(proto, items):
    for item in items:
        new = deepcopy(proto)
        proto.addprevious(new)
        _set_single_run(Paragraph(new, None), item)
    proto.getparent().remove(proto)


def _clone_row(proto_row, items, doc):
    tr = proto_row._tr
    for item in items:
        new = deepcopy(tr)
        tr.addprevious(new)
        for cell_el, value in zip(new.iter(docx.oxml.ns.qn("w:tc")), item):
            _set_cell(cell_el, value)
    tr.getparent().remove(tr)


def _set_cell(cell_el, value):
    """Line 1 -> first paragraph; each further line -> a copy of the second paragraph (detail or bullet)."""
    paras = cell_el.findall(docx.oxml.ns.qn("w:p"))
    lines = str(value).split("\n")
    _set_single_run(Paragraph(paras[0], None), lines[0])
    if len(paras) < 2:
        if len(lines) > 1:
            _set_single_run(Paragraph(paras[0], None), str(value))
        return
    proto = paras[1]
    for p in paras[2:]:
        cell_el.remove(p)
    anchor = proto
    for line in lines[1:]:
        new = deepcopy(proto)
        anchor.addnext(new)
        _set_single_run(Paragraph(new, None), line)
        anchor = new
    cell_el.remove(proto)


def _fill_checkboxes(doc, pairs):
    """Section 8: repeat [line break, checkbox run, text run] per characteristic, keeping each run's font."""
    q = docx.oxml.ns.qn
    for p_el in doc.element.body.iter(q("w:p")):
        runs = Paragraph(p_el, doc).runs
        box = next((r for r in runs if r.text == "{{cb_box}}"), None)
        text = next((r for r in runs if r.text == "{{cb_text}}"), None)
        if box is None or text is None:
            continue
        anchor = text._r
        for i, (mark, words) in enumerate(pairs):
            if i:
                br = deepcopy(text._r)
                anchor.addnext(br)
                docx.text.run.Run(br, None).text = "\n"
                anchor = br
            for proto, value in ((box, mark), (text, words)):
                new = deepcopy(proto._r)
                anchor.addnext(new)
                docx.text.run.Run(new, None).text = value
                anchor = new
        box._r.getparent().remove(box._r)
        text._r.getparent().remove(text._r)
        return


def _set_single_run(p, text):
    runs = p.runs
    if runs:
        for r in runs[1:]:
            r._r.getparent().remove(r._r)
        runs[0].text = text
    else:
        p.add_run(text)


def _in_table(el):
    return any(a.tag == docx.oxml.ns.qn("w:tbl") for a in el.iterancestors())


# ---------- helpers ----------

def _section(facts, prefix):
    for k, v in facts.items():
        if k.lower().startswith(prefix):
            return v
    return None


def _rows(value):
    if isinstance(value, list):
        return [r for r in value if isinstance(r, dict)]
    if isinstance(value, dict):
        for v in value.values():
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
    return []


def _get(d, prefix):
    if not isinstance(d, dict):
        return ""
    for k, v in d.items():
        if k.lower().startswith(prefix):
            return str(v)
    # load_club_facts() keeps long "Key: value" lines (key over 60 characters) as plain text.
    for line in d.get("text") or []:
        key, sep, value = str(line).partition(":")
        if sep and key.strip().lower().startswith(prefix):
            return value.strip()
    return ""


def _person_columns(r):
    """'Ms. Kanya<TAB>Example<TAB>President', matching the three columns in the PDF."""
    first = " ".join(x for x in (r.get("Title", ""), r.get("First name", "")) if x)
    return f"{first}\t{r.get('Last name', '')}\t{r.get('Role', '')}"


def _split_line(value):
    """'Inclusive workshop 1 = 0 · Inclusive workshop 2 = 1,100' -> [(name, amount), ...]."""
    out = []
    for part in re.split(r"[·;\n]", str(value)):
        if "=" in part:
            name, amount = part.split("=", 1)
            out.append((name.strip(" -"), _parse_money(amount) or 0))
    return out


def _person(r):
    return " ".join(x for x in (r.get("Title", ""), r.get("First name", ""), r.get("Last name", "")) if x)


def _project_rows(table):
    out = []
    for r in table:
        if not isinstance(r, dict):
            continue
        name = r.get("Project") or next(iter(r.values()), "")
        amount_key = next((k for k in r if "planned" in k.lower() or "thb" in k.lower()), None)
        if amount_key:
            out.append((name, _parse_money(r[amount_key]) or 0))
    return out


def _facility(f):
    if isinstance(f, dict):
        qty = f.get("qty")
        return f"{f.get('item', '')} {_fmt_num(_num(qty))}" if qty not in (None, "") else f.get("item", "")
    return str(f)


def _schedule_row(s):
    if isinstance(s, dict):
        return [s.get("time", ""), s.get("activity", ""), s.get("description", "")]
    if isinstance(s, (list, tuple)):
        return [str(x) for x in list(s) + ["", "", ""]][:3]
    return [str(s), "", ""]


def _strings(value):
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(v) for v in value or []]


def _num(v):
    if isinstance(v, (int, float)):
        return v
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return 0


def _parse_money(v):
    m = re.search(r"[\d,]+(?:\.\d+)?", str(v))
    return float(m.group(0).replace(",", "")) if m else None


def _money(v, decimals=True):
    return f"{v:,.2f}" if decimals else (f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}")


def _fmt_num(v):
    return f"{int(v)}" if float(v).is_integer() else f"{v}"


def _int_str(v):
    return _fmt_num(v)

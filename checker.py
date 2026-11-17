"""Consistency checks before download. Owner: Ming.

Each check catches a mistake that real BizComp proposals have made (docs/SPEC.md, ภาคผนวก ง):
wrong week for the event in the Schedule, 30 pens for 51 people. Ordinal words ("The First
Inclusive Workshop" in Workshop 2) only raise a "Check:" note, because "first" may be correct.
"""
import math
import re
from datetime import date

ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
            "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6}
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]
# Items each participant needs one of. Packs, boxes and sets are skipped: one pack can serve many people.
PER_PERSON = ["pen", "pencil", "paper", "notebook", "name tag", "lanyard", "t-shirt", "shirt",
              "certificate", "badge", "folder", "lunch", "meal", "snack", "food", "drink", "water", "bag"]
BULK_UNITS = ["pack", "box", "set of", "ream", "bundle", "roll"]
EVENT_DAY_WORDS = ["d-day", "day of the", "event day", "workshop day", "main event"]


def check_brief(brief):
    """Return a list of warning strings (C4). An empty list means no problems found."""
    warnings = []
    warnings += check_participants(brief)
    warnings += check_schedule_date(brief)
    warnings += check_event_name(brief)
    warnings += check_quantities(brief)
    warnings += check_to_confirm(brief)
    warnings += check_budget_items(brief)
    return warnings


def check_participants(brief):
    groups = brief.get("participants") or []
    total = sum(_num(g.get("count")) for g in groups)
    out = []
    stated = brief.get("total_participants")
    if stated not in (None, "") and _num(stated) != total:
        out.append(f"Participant groups add up to {_fmt(total)}, but the total says {_fmt(_num(stated))}.")
    for g in groups:
        if _num(g.get("count")) <= 0:
            out.append(f"Participant group '{g.get('group', '?')}' has no headcount.")
    for sec in ("introduction", "activity_kpis"):
        for n in re.findall(r"(\d+)\s+(?:participants|people|students|attendees)\b", _text(brief, sec), re.I):
            if total and int(n) > total:
                out.append(f"{sec.replace('_', ' ').title()} mentions {n} people, more than the {_fmt(total)} in the form.")
    return out


def check_schedule_date(brief):
    """The event-day row of the Schedule must point at the event date (exact date or 'Nth Week of Month')."""
    try:
        event = date.fromisoformat(brief.get("date", ""))
    except (TypeError, ValueError):
        return []
    out = []
    for row in (brief.get("sections") or {}).get("schedule") or []:
        cells = _cells(row)
        joined = " ".join(cells).lower()
        if not any(w in joined for w in EVENT_DAY_WORDS) and brief.get("event_name", "").lower() not in joined:
            continue
        when = cells[0]
        week = re.search(r"(\w+)\s+week\s+of\s+(\w+)", when, re.I)
        if week:
            n = ORDINALS.get(week.group(1).lower())
            month = week.group(2).lower()
            event_week = math.ceil(event.day / 7)
            if month in MONTHS and (MONTHS.index(month) + 1 != event.month or (n and n != event_week)):
                out.append(f"Schedule puts the event in the '{when}', but the event date "
                           f"{event:%d %B %Y} is in week {event_week} of {event:%B}.")
            continue
        found = _dates_in(when, event.year)
        if found and event not in found:
            out.append(f"Schedule date '{when}' does not match the event date {event:%d %B %Y}.")
    return out


def check_event_name(brief):
    """Catch 'The First Inclusive Workshop' inside the Inclusive Workshop 2 proposal."""
    name = brief.get("event_name", "")
    m = re.search(r"([A-Za-z]+)\s+(\d+)\s*$", name)
    if not m:
        return []
    noun, number = m.group(1), int(m.group(2))
    out = []
    for sec in ("introduction", "objectives", "benefits", "activity_kpis", "characteristics", "schedule"):
        text = _text(brief, sec)
        word = r"(?:[A-Z][\w-]*|first|second|third|fourth|fifth|sixth|\d+(?:st|nd|rd|th))"
        pattern = rf"((?:\b{word}\s+){{0,4}}){noun}\b(?:\s+(\d+))?"
        for hit in re.finditer(pattern, text):
            ordinal = next((ORDINALS[w.lower()] for w in hit.group(1).split() if w.lower() in ORDINALS), None)
            label = sec.replace("_", " ").title()
            if hit.group(2) and int(hit.group(2)) != number:
                out.append(f"{label} says '{hit.group(0).strip()}', but the event is '{name}'.")
            elif not hit.group(2) and ordinal is not None and ordinal != number:
                # "First" can mean first of the year or first of its kind, so only ask a person to look.
                out.append(f"Check: {label} says '{hit.group(0).strip()}' while the event is '{name}'. "
                           f"Does that match the real order of events?")
    return out


def check_quantities(brief):
    total = sum(_num(g.get("count")) for g in brief.get("participants") or [])
    if not total:
        return []
    out = []
    candidates = []
    for f in (brief.get("sections") or {}).get("facilities") or []:
        if isinstance(f, dict):
            candidates.append((f.get("item", ""), _num(f.get("qty"))))
        else:
            m = re.match(r"(.+?)\s+(\d+)\s*$", str(f).strip())
            if m:
                candidates.append((m.group(1), int(m.group(2))))
    for it in brief.get("budget_items") or []:
        candidates.append((it.get("item", ""), _num(it.get("qty"))))
    for item, qty in candidates:
        low = item.lower()
        # Quantity 1 is a lump sum ("Pen 230 baht" in RealBiz), not one pen.
        if any(u in low for u in BULK_UNITS) or qty <= 1:
            continue
        # "20 participants x 2 days" is entered as 40 meals: compare per day.
        days = re.search(r"(\d+)\s*days?\b", low)
        per = " per day" if days and int(days.group(1)) > 1 else ""
        if per:
            qty = qty / int(days.group(1))
        if any(re.search(rf"\b{re.escape(w)}s?\b", low) for w in PER_PERSON) and 0 < qty < total:
            out.append(f"{item}: {_fmt(qty)}{per} for {_fmt(total)} people.")
    return out


def check_to_confirm(brief):
    out = []
    for item in brief.get("to_confirm") or []:
        out.append(f"Still to confirm: {item}")
    for sec, text in ((s, _text(brief, s)) for s in (brief.get("sections") or {})):
        for hit in re.findall(r"\[TO CONFIRM:?[^\]]*\]", text):
            if not any(hit in w for w in out):
                out.append(f"{sec.replace('_', ' ').title()} still has {hit}")
    return out


def check_budget_items(brief):
    out = []
    for it in brief.get("budget_items") or []:
        if _num(it.get("qty")) <= 0 or _num(it.get("unit_price")) < 0:
            out.append(f"Budget item '{it.get('item', '?')}' needs a quantity and a unit price.")
    return out


# ---------- helpers ----------

def _text(brief, section):
    value = (brief.get("sections") or {}).get(section)
    return _flatten(value)


def _flatten(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(_flatten(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return "\n".join(_flatten(v) for v in value)
    return "" if value is None else str(value)


def _cells(row):
    if isinstance(row, dict):
        return [str(row.get(k, "")) for k in ("time", "activity", "description")]
    if isinstance(row, (list, tuple)):
        return [str(x) for x in row] + [""] * (3 - len(row))
    return [str(row), "", ""]


def _dates_in(text, default_year):
    found = set()
    for y, m, d in re.findall(r"(\d{4})-(\d{2})-(\d{2})", text):
        found.add(_safe_date(int(y), int(m), int(d)))
    for d, mon, y in re.findall(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s*(\d{4})?", text):
        if mon.lower() in MONTHS:
            found.add(_safe_date(int(y or default_year), MONTHS.index(mon.lower()) + 1, int(d)))
    for d, m, y in re.findall(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text):
        found.add(_safe_date(int(y), int(m), int(d)))
    found.discard(None)
    return found


def _safe_date(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _num(v):
    if isinstance(v, (int, float)):
        return v
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return 0


def _fmt(v):
    return f"{int(v)}" if float(v).is_integer() else f"{v}"

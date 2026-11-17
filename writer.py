"""Form -> event brief, gap questions, and AI-written sections. Owner: Yuay."""

import json
import re
import uuid
from datetime import date

from config import BRIEFS_FOLDER

SECTIONS = [
    "introduction", "objectives", "benefits", "activity_kpis",
    "characteristics", "schedule", "facilities",
]

# Same list as the upload page in knowledge.py (Boom), so search can match event types.
EVENT_TYPES = ["open workshop", "members-only workshop", "social event", "long project", "other"]

MIN_ACTIVITIES = 3
MAX_ACTIVITIES = 5
TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
BRIEF_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class BriefError(ValueError):
    """The form has problems. `problems` lists one message per problem, for the form page."""

    def __init__(self, problems):
        super().__init__("; ".join(problems))
        self.problems = problems


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _number(value):
    """Return value as int or float, or None if it is not a number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = value
    elif isinstance(value, str) and value.strip():
        try:
            number = float(value.strip().replace(",", ""))
        except ValueError:
            return None
    else:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return int(number) if float(number).is_integer() else number


CORE_ROLES = {"President", "Vice President", "Secretary", "Treasurer"}
MONTHS = {name: number for number, name in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)}
ACADEMIC_YEAR_PATTERN = re.compile(r"\((\w+)\s+(\d{4})\s*[–-]\s*(\w+)\s+(\d{4})\)")


def club_facts():
    """Club facts as a dict, or {} until load_club_facts (task A4, Boom) is available."""
    try:
        from knowledge import load_club_facts
        facts = load_club_facts()
    except Exception:
        return {}
    return facts if isinstance(facts, dict) else {}


def _officers(facts):
    return [row for row in facts.get("Officers", []) if isinstance(row, dict)]


def proposer_options(facts=None):
    """Officer names for the proposer dropdown. Empty list means the form shows a text box."""
    options = []
    for row in _officers(club_facts() if facts is None else facts):
        name = " ".join(
            part for part in (_text(row.get("Title")), _text(row.get("First name")), _text(row.get("Last name"))) if part
        )
        if name:
            options.append({"name": name, "role": _text(row.get("Role"))})
    return options


def department_options(facts=None):
    """Departments that can be in charge of an event: officer roles other than the 4 core roles."""
    roles = []
    for row in _officers(club_facts() if facts is None else facts):
        role = _text(row.get("Role"))
        if role and role not in CORE_ROLES and role not in roles:
            roles.append(role)
    return roles


def academic_year(facts=None):
    """(first day, last day) of the academic year from club facts, e.g. "(August 2026 – May 2027)"."""
    club = (club_facts() if facts is None else facts).get("Club", {})
    line = club.get("Academic year", "") if isinstance(club, dict) else ""
    match = ACADEMIC_YEAR_PATTERN.search(line) if isinstance(line, str) else None
    if not match or match.group(1) not in MONTHS or match.group(3) not in MONTHS:
        return None
    first = date(int(match.group(2)), MONTHS[match.group(1)], 1)
    end_month, end_year = MONTHS[match.group(3)], int(match.group(4))
    next_month = date(end_year + end_month // 12, end_month % 12 + 1, 1)
    return first, date.fromordinal(next_month.toordinal() - 1)


def brief_warnings(brief, facts=None, today=None):
    """Things to double-check that should not block saving (old proposals are re-entered for testing)."""
    warnings = []
    today = today or date.today()
    start = date.fromisoformat(brief["date"])
    end = date.fromisoformat(brief["end_date"]) if brief.get("end_date") else start
    if start < today:
        warnings.append("The event date is in the past. That is fine for testing with an old proposal.")
    year = academic_year(facts)
    if year and not (year[0] <= start and end <= year[1]):
        warnings.append(
            f"The event is outside the academic year ({year[0]:%d %b %Y} to {year[1]:%d %b %Y}) in club facts."
        )
    return warnings


def build_brief(form):
    """Turn the submitted form into an event brief dict (B1). See docs/SPEC.md, ภาคผนวก ข.

    `form` is the JSON object sent by static/new.js. Raises BriefError listing every problem.
    """
    if not isinstance(form, dict):
        raise BriefError(["The form data is missing."])
    problems = []

    event_name = _text(form.get("event_name"))
    if not event_name:
        problems.append("Enter the event name.")

    event_type = _text(form.get("event_type"))
    if event_type not in EVENT_TYPES:
        problems.append("Choose an event type.")

    event_date, end_date = _text(form.get("date")), _text(form.get("end_date"))
    try:
        first_day = date.fromisoformat(event_date)
    except ValueError:
        first_day = None
        problems.append("Enter the event date.")
    if end_date:
        try:
            last_day = date.fromisoformat(end_date)
        except ValueError:
            problems.append("The end date is not a valid date.")
        else:
            if first_day and last_day < first_day:
                problems.append("The end date must be on or after the start date.")
            elif first_day and last_day == first_day:
                end_date = ""  # same day: a one-day event

    start, end = _text(form.get("start_time")), _text(form.get("end_time"))
    if not TIME_PATTERN.match(start) or not TIME_PATTERN.match(end):
        problems.append("Enter a start and end time.")
    elif end <= start:
        problems.append("The end time must be after the start time.")

    location = _text(form.get("location"))
    if not location:
        problems.append("Enter the location.")

    participants = []
    for row in form.get("participants") or []:
        if not isinstance(row, dict):
            continue
        group, count = _text(row.get("group")), _number(row.get("count"))
        if not group and count is None:
            continue  # empty row
        if not group or not isinstance(count, int) or count < 1:
            problems.append("Each participant group needs a name and a whole number of people (1 or more).")
            break
        participants.append({"group": group, "count": count})
    else:
        if not participants:
            problems.append("Add at least one participant group.")

    attendance_target = None
    raw_target = form.get("attendance_target")
    target_given = bool(_text(raw_target)) if isinstance(raw_target, str) else raw_target is not None
    if target_given:
        attendance_target = _number(raw_target)
        if not isinstance(attendance_target, int) or attendance_target < 1:
            problems.append("The minimum attendance target must be a whole number (1 or more).")
            attendance_target = None
        elif participants and attendance_target > sum(row["count"] for row in participants):
            problems.append("The minimum attendance target is higher than the total number of participants.")

    activities = [_text(item) for item in form.get("activities") or [] if _text(item)]
    if not MIN_ACTIVITIES <= len(activities) <= MAX_ACTIVITIES:
        problems.append(f"List {MIN_ACTIVITIES} to {MAX_ACTIVITIES} things that happen at the event.")

    speakers = [_text(item) for item in form.get("speakers") or [] if _text(item)]

    budget_items = []
    if not form.get("no_budget"):
        for row in form.get("budget_items") or []:
            if not isinstance(row, dict):
                continue
            item = _text(row.get("item"))
            qty, unit_price = _number(row.get("qty")), _number(row.get("unit_price"))
            if not item and qty is None and unit_price is None:
                continue  # empty row
            if not item or qty is None or qty <= 0 or unit_price is None or unit_price < 0:
                problems.append("Each budget item needs a name, a quantity above 0 and a unit price (0 or more).")
                break
            budget_items.append({"item": item, "qty": qty, "unit_price": unit_price})
        else:
            if not budget_items:
                problems.append('Add at least one budget item, or tick "No budget".')

    proposer = _text(form.get("proposer"))
    if not proposer:
        problems.append("Choose who is proposing this event.")

    # Department in charge (PIC): lists its members under Responsibilities. Long projects list
    # their own project team instead, so it is optional for them.
    department = _text(form.get("department"))
    if not department and event_type != "long project":
        problems.append("Choose the department in charge of this event.")

    if problems:
        raise BriefError(problems)

    return {
        "event_name": event_name,
        "event_type": event_type,
        "date": event_date,
        "end_date": end_date,
        "time": f"{start}-{end}",
        "location": location,
        "participants": participants,
        "attendance_target": attendance_target,
        "activities": activities,
        "speakers": speakers,
        "budget_items": budget_items,
        "proposer": proposer,
        "department": department,
        "followup_answers": {},
        "sections": {
            "introduction": "",
            "objectives": [],
            "benefits": [],
            "activity_kpis": [],
            "characteristics": {"ticked": [], "explanation": ""},
            "schedule": [],
            "facilities": [],
        },
        "to_confirm": [],
    }


def save_brief(brief, brief_id=None):
    """Save the brief to data/briefs/<id>.json and return the id."""
    brief_id = brief_id or uuid.uuid4().hex
    if not BRIEF_ID_PATTERN.match(brief_id):
        raise ValueError("Invalid brief id.")
    BRIEFS_FOLDER.mkdir(parents=True, exist_ok=True)
    path = BRIEFS_FOLDER / f"{brief_id}.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return brief_id


def load_brief(brief_id):
    """Read a saved brief. Raises FileNotFoundError if the id is unknown."""
    if not isinstance(brief_id, str) or not BRIEF_ID_PATTERN.match(brief_id):
        raise FileNotFoundError(brief_id)
    return json.loads((BRIEFS_FOLDER / f"{brief_id}.json").read_text(encoding="utf-8"))


def find_gaps(brief):
    """Return up to 3 questions about information the sections need but the brief lacks (B5)."""
    raise NotImplementedError("find_gaps is task B5 (Yuay). See docs/SPEC.md.")


def write_section(brief, section):
    """Write one section with the model, using examples from knowledge.search_sections (B3)."""
    raise NotImplementedError("write_section is task B3 (Yuay). See docs/SPEC.md.")


def write_all_sections(brief):
    """Fill brief["sections"] for every name in SECTIONS and return the brief (B4)."""
    raise NotImplementedError("write_all_sections is task B4 (Yuay). See docs/SPEC.md.")

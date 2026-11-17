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


def proposer_options():
    """Officer names for the proposer dropdown, from club facts. Empty list if not available yet."""
    try:
        from knowledge import load_club_facts
        facts = load_club_facts()
    except Exception:
        # load_club_facts is task A4 (Boom). Until it works, the form shows a text box instead.
        return []
    options = []
    for row in facts.get("Officers", []) if isinstance(facts, dict) else []:
        if not isinstance(row, dict):
            continue
        name = " ".join(
            part for part in (_text(row.get("Title")), _text(row.get("First name")), _text(row.get("Last name"))) if part
        )
        if name:
            options.append({"name": name, "role": _text(row.get("Role"))})
    return options


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

    event_date = _text(form.get("date"))
    try:
        date.fromisoformat(event_date)
    except ValueError:
        problems.append("Enter the event date.")

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

    if problems:
        raise BriefError(problems)

    return {
        "event_name": event_name,
        "event_type": event_type,
        "date": event_date,
        "time": f"{start}-{end}",
        "location": location,
        "participants": participants,
        "activities": activities,
        "speakers": speakers,
        "budget_items": budget_items,
        "proposer": proposer,
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

"""Form -> event brief, gap questions, and AI-written sections. Owner: Yuay."""

import json
import re
import uuid
from datetime import date
from pathlib import Path

from config import BRIEFS_FOLDER, MODEL, OLLAMA_CHAT_TIMEOUT, OLLAMA_CHAT_URL
from ollama_client import OllamaError, ollama_post

PROMPTS_FOLDER = Path(__file__).resolve().parent / "prompts"

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


# ---------------------------------------------------------------------------------------------
# B5: follow-up questions before writing
# ---------------------------------------------------------------------------------------------

MAX_QUESTIONS = 3
SPEAKER_WORDS = re.compile(r"\b(speaker|mentor|guest|alumn\w*|trainer|panel\w*|judge\w*)\b", re.IGNORECASE)
# The model must not ask about things the form already collects or that code handles.
ALREADY_KNOWN = re.compile(
    r"\b(budget|cost|price|baht|fund|event name|title|date|location|venue|room|proposer|department)\b",
    re.IGNORECASE,
)
ATTENDANCE_WORDS = re.compile(r"\b(attend\w*|turnout|how many (people|participants))\b", re.IGNORECASE)
GAPS_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": {
        "type": "object",
        "properties": {"question": {"type": "string"}, "needed_for": {"type": "string"}},
        "required": ["question", "needed_for"],
    }}},
    "required": ["questions"],
}


def _code_gaps(brief):
    """Gaps code can find for sure, without the model."""
    questions = []
    if brief.get("attendance_target") is None:
        questions.append({
            "field": "attendance_target",
            "question": "What is the minimum number of people who must attend for the event to count as a success?",
            "needed_for": "Activity KPIs",
        })
    if not brief.get("speakers") and any(SPEAKER_WORDS.search(item) for item in brief.get("activities", [])):
        questions.append({
            "field": "speakers",
            "question": "The activities mention a speaker or mentor. Who is it (name, or a description such as "
                        "\"1 BAScii alumnus\")?",
            "needed_for": "Introduction, Schedule",
        })
    return questions


def _model_gaps(brief, count):
    """Ask the model what else the 7 sections need that the brief does not say. [] if it fails."""
    if count <= 0:
        return []
    messages = [
        {"role": "system", "content": (PROMPTS_FOLDER / "common.txt").read_text(encoding="utf-8")},
        {"role": "user", "content": (PROMPTS_FOLDER / "gaps.txt").read_text(encoding="utf-8").replace(
            "{count}", str(count)) + "\n\nEVENT BRIEF:\n" + json.dumps(brief_facts(brief), ensure_ascii=False, indent=2)},
    ]
    try:
        reply = call_model(messages, GAPS_SCHEMA)
    except (OllamaError, SectionError):
        return []
    questions = []
    for item in reply.get("questions") or [] if isinstance(reply, dict) else []:
        question = _text(item.get("question")) if isinstance(item, dict) else ""
        # Attendance is asked by code when it is missing, so the model never needs to ask it.
        if not question or ALREADY_KNOWN.search(question) or ATTENDANCE_WORDS.search(question):
            continue
        questions.append({"field": "", "question": question, "needed_for": _text(item.get("needed_for"))})
    return questions


def find_gaps(brief):
    """Return up to 3 questions about information the sections need but the brief lacks (B5).

    Each question is {"id", "field", "question", "needed_for"}. "field" names the brief field an
    answer fills (attendance_target, speakers), or is "" for answers kept in followup_answers.
    Works without Ollama: the model's questions are then simply left out.
    """
    questions = _code_gaps(brief)
    asked = {question["question"].lower() for question in questions}
    for question in _model_gaps(brief, MAX_QUESTIONS - len(questions)):
        if question["question"].lower() not in asked:
            asked.add(question["question"].lower())
            questions.append(question)
    return [dict(question, id=f"q{number}") for number, question in enumerate(questions[:MAX_QUESTIONS], start=1)]


def apply_answers(brief, questions, answers):
    """Put the user's answers into the brief and return it (B5).

    Answers to field questions fill that field. Other answers go to followup_answers, keyed by the
    question. Every unanswered question goes to to_confirm, so the writer marks it [TO CONFIRM].
    Raises BriefError if an attendance answer is not a usable whole number.
    """
    answers = answers if isinstance(answers, dict) else {}
    followup = dict(brief.get("followup_answers") or {})
    to_confirm = list(brief.get("to_confirm") or [])
    problems = []
    for question in questions if isinstance(questions, list) else []:
        if not isinstance(question, dict) or not _text(question.get("question")):
            continue
        text, field = _text(question["question"]), _text(question.get("field"))
        answer = _text(answers.get(_text(question.get("id"))))
        if not answer:
            to_confirm.append(text)
            continue
        if field == "attendance_target":
            number = _number(answer)
            total = sum(row.get("count", 0) for row in brief.get("participants", []))
            if not isinstance(number, int) or number < 1:
                problems.append("The minimum attendance must be a whole number (1 or more).")
            elif number > total:
                problems.append(f"The minimum attendance ({number}) is higher than the total participants ({total}).")
            else:
                brief["attendance_target"] = number
        elif field == "speakers":
            brief["speakers"] = [*brief.get("speakers", []), answer]
        else:
            followup[text] = answer
    if problems:
        raise BriefError(problems)
    brief["followup_answers"] = followup
    brief["to_confirm"] = list(dict.fromkeys(to_confirm))
    return brief


# ---------------------------------------------------------------------------------------------
# B3 + B4: writing the 7 sections
# ---------------------------------------------------------------------------------------------

# Section key in the brief -> section name used by knowledge.search_sections (Boom).
SECTION_LABELS = {
    "introduction": "Introduction",
    "objectives": "Objectives",
    "benefits": "Benefits",
    "activity_kpis": "Activity KPIs",
    "characteristics": "Desired Characteristics",
    "schedule": "Schedule",
    "facilities": "Facilities",
}
# How many list items each section must have (from SPEC.md, ภาคผนวก ข).
ITEM_LIMITS = {"objectives": (4, 6), "benefits": (4, 6), "activity_kpis": (2, 3), "facilities": (1, 15)}
CHARACTERISTIC_LIMITS = (2, 4)
SCHEDULE_LIMITS = (3, 6)
EXAMPLE_COUNT = 3
MAX_ATTEMPTS = 2  # first try + one retry with the problems listed

TO_CONFIRM_PATTERN = re.compile(r"\[TO CONFIRM:\s*([^\]]+)\]")
MONEY_PATTERN = re.compile(r"(฿|\bTHB\b|\bbaht\b|บาท)", re.IGNORECASE)
NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)*")
KPI_CODE_PATTERN = re.compile(r"\(([^()]*\bKPI\s*\d+[^()]*)\)")


class SectionError(Exception):
    """The model could not produce a usable section."""


def _facts_table(facts, heading_start):
    """Rows of the club-facts table whose heading starts with heading_start (case-insensitive)."""
    for heading, value in facts.items():
        if heading.lower().startswith(heading_start.lower()) and isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def school_kpis(facts):
    return [
        {"code": _text(row.get("Code")), "kpi": _text(row.get("KPI"))}
        for row in _facts_table(facts, "School KPIs") if _text(row.get("Code"))
    ]


def characteristic_options(facts):
    return [
        {"name": _text(row.get("Characteristic")), "meaning": _text(row.get("Meaning"))}
        for row in _facts_table(facts, "Desired characteristics") if _text(row.get("Characteristic"))
    ]


def brief_facts(brief):
    """The facts the model may use, without the empty sections."""
    facts = {key: value for key, value in brief.items() if key not in {"sections", "to_confirm"}}
    facts["total_participants"] = sum(row.get("count", 0) for row in brief.get("participants", []))
    # Item names and quantities help with Facilities; prices are left out so they cannot leak into text.
    facts["budget_items"] = [
        {"item": row.get("item", ""), "qty": row.get("qty")} for row in brief.get("budget_items", [])
    ]
    return facts


def find_examples(brief, section, skip=None):
    """Up to 3 past examples of this section from knowledge.search_sections (Boom, task A3).

    Returns [] if search is not available yet, so writing still works without examples.
    """
    try:
        from knowledge import search_sections
        query = " ".join([brief.get("event_name", ""), *brief.get("activities", [])])
        kwargs = {"skip": skip} if skip else {}
        results = search_sections(SECTION_LABELS[section], brief.get("event_type", ""), query, k=EXAMPLE_COUNT, **kwargs)
    except (NotImplementedError, ImportError, OllamaError, TypeError, OSError, ValueError):
        return []
    return [result for result in results if isinstance(result, dict) and _text(result.get("text"))]


def build_messages(brief, section, facts, examples):
    """The system and user messages sent to the model for one section."""
    system = (PROMPTS_FOLDER / "common.txt").read_text(encoding="utf-8")
    instructions = (PROMPTS_FOLDER / f"{section}.txt").read_text(encoding="utf-8")
    parts = [instructions, "EVENT BRIEF:\n" + json.dumps(brief_facts(brief), ensure_ascii=False, indent=2)]
    if section == "benefits":
        parts.append("SCHOOL KPIS:\n" + json.dumps(school_kpis(facts), ensure_ascii=False, indent=2))
    if section == "characteristics":
        parts.append("DESIRED CHARACTERISTICS:\n" + json.dumps(characteristic_options(facts), ensure_ascii=False, indent=2))
    unanswered = [item for item in brief.get("to_confirm") or [] if isinstance(item, str)]
    if unanswered:
        parts.append("UNANSWERED QUESTIONS (if this section needs one of these, write [TO CONFIRM: ...] "
                     "instead of guessing):\n- " + "\n- ".join(unanswered))
    if examples:
        parts.append("EXAMPLES:\n" + "\n\n".join(
            f"--- Example {number}: {example.get('event_name') or example.get('source', 'past proposal')} ---\n"
            f"{example['text'].strip()}"
            for number, example in enumerate(examples, start=1)
        ))
    else:
        parts.append("EXAMPLES: none available. Follow the instructions above.")
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n\n".join(parts)}]


def output_schema(section, facts):
    """JSON schema passed to Ollama's `format`, so the model replies in the right shape."""
    strings = {"type": "array", "items": {"type": "string"}}
    if section == "introduction":
        return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    if section == "characteristics":
        names = [option["name"] for option in characteristic_options(facts)]
        ticked = {"type": "array", "items": {"type": "string", "enum": names} if names else {"type": "string"}}
        return {"type": "object", "properties": {"ticked": ticked, "explanation": {"type": "string"}},
                "required": ["ticked", "explanation"]}
    if section == "schedule":
        row = {"type": "object", "properties": {key: {"type": "string"} for key in ("time", "activity", "description")},
               "required": ["time", "activity", "description"]}
        return {"type": "object", "properties": {"rows": {"type": "array", "items": row}}, "required": ["rows"]}
    return {"type": "object", "properties": {"items": strings}, "required": ["items"]}


def call_model(messages, schema):
    """One chat call to the local model. Returns the parsed JSON reply."""
    response = ollama_post(
        OLLAMA_CHAT_URL,
        {"model": MODEL, "messages": messages, "format": schema, "stream": False,
         "options": {"temperature": 0.4}},
        timeout=OLLAMA_CHAT_TIMEOUT,
    )
    content = (response.get("message") or {}).get("content") if isinstance(response, dict) else None
    if not isinstance(content, str):
        raise SectionError("The model's reply had no text.")
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError as error:
        raise SectionError("The model did not reply with valid JSON.") from error


def parse_section(section, reply):
    """Turn the model's JSON into the value stored in brief["sections"][section]."""
    if not isinstance(reply, dict):
        raise SectionError("The reply was not a JSON object.")
    if section == "introduction":
        return _text(reply.get("text"))
    if section == "characteristics":
        ticked = [_text(name) for name in reply.get("ticked") or [] if _text(name)]
        return {"ticked": list(dict.fromkeys(ticked)), "explanation": _text(reply.get("explanation"))}
    if section == "schedule":
        rows = []
        for row in reply.get("rows") or []:
            if isinstance(row, dict) and _text(row.get("activity")):
                rows.append({key: _text(row.get(key)) for key in ("time", "activity", "description")})
        return rows
    return [_text(item) for item in reply.get("items") or [] if _text(item)]


def _section_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_section_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_section_text(item) for item in value)
    return ""


def _number_variants(value):
    """'1,099.50' -> {'1,099.50', '1099.50', '1099.5'}; '12' -> {'12'}."""
    text = str(value)
    variants = {text, text.replace(",", "")}
    try:
        number = float(text.replace(",", ""))
        variants.add(str(int(number)) if number.is_integer() else str(number))
    except ValueError:
        pass
    return variants


def allowed_numbers(brief, facts):
    """Every number the model may write: from the brief, follow-up answers and club facts."""
    model_facts = {"kpis": school_kpis(facts), "characteristics": characteristic_options(facts)}
    sources = json.dumps(brief_facts(brief), ensure_ascii=False) + json.dumps(model_facts, ensure_ascii=False)
    allowed = set()
    for match in NUMBER_PATTERN.findall(sources):
        allowed |= _number_variants(match)
    for key in ("date", "end_date"):
        if brief.get(key):
            day = date.fromisoformat(brief[key])
            allowed |= {str(day.day), str(day.month), str(day.year), f"{day.day:02d}", f"{day.month:02d}"}
    # Small numbers are used for ratings (4 out of 5), weeks ("3rd week") and counts of steps.
    allowed |= {str(number) for number in range(0, 6)} | {"4.0", "4.5", "5.0"}
    return allowed


def check_section(section, value, brief, facts):
    """Return a list of rule problems in the section (empty list = OK). Rules from SPEC.md."""
    problems = []
    text = _section_text(value)
    if not text.strip():
        return ["The section is empty."]

    if MONEY_PATTERN.search(text):
        problems.append("Do not write any money amounts or the word baht/THB.")
    numbers = allowed_numbers(brief, facts)
    invented = sorted({number for number in NUMBER_PATTERN.findall(TO_CONFIRM_PATTERN.sub("", text))
                       if not _number_variants(number) & numbers})
    if invented:
        problems.append(f"These numbers are not in the brief or club facts: {', '.join(invented)}. "
                        "Remove them or write [TO CONFIRM: ...].")

    if section in ITEM_LIMITS:
        low, high = ITEM_LIMITS[section]
        if not low <= len(value) <= high:
            problems.append(f"Write {low} to {high} items, not {len(value)}.")

    if section == "introduction":
        sentences = [part for part in re.split(r"(?<=[.!?])\s+", value) if part.strip()]
        if not 3 <= len(sentences) <= 7:
            problems.append("Write one paragraph of 4 to 6 sentences.")
        if brief["event_name"].lower() not in value.lower():
            problems.append(f'Use the exact event name "{brief["event_name"]}".')

    if section == "benefits":
        codes = {row["code"].replace(" ", "").upper() for row in school_kpis(facts)}
        for item in value:
            found = {code.replace(" ", "").upper()
                     for group in KPI_CODE_PATTERN.findall(item) for code in re.findall(r"KPI\s*\d+", group)}
            if not found:
                problems.append(f'Add the KPI code in brackets to: "{item}".')
            elif codes and not found <= codes:
                problems.append(f'Use only these KPI codes: {", ".join(sorted(codes))}. Wrong in: "{item}".')

    if section == "characteristics":
        names = [option["name"] for option in characteristic_options(facts)]
        ticked, explanation = value["ticked"], value["explanation"].lower()
        low, high = CHARACTERISTIC_LIMITS
        if not low <= len(ticked) <= high:
            problems.append(f"Tick {low} to {high} characteristics, not {len(ticked)}.")
        if names and any(name not in names for name in ticked):
            problems.append("Tick only names from DESIRED CHARACTERISTICS, written exactly.")
        missing = [name for name in ticked if name.lower() not in explanation]
        if missing:
            problems.append(f"The explanation must mention: {', '.join(missing)}.")
        extra = [name for name in names if name not in ticked and name.lower() in explanation]
        if extra:
            problems.append(f"The explanation mentions characteristics that are not ticked: {', '.join(extra)}.")

    if section == "schedule":
        low, high = SCHEDULE_LIMITS
        if not low <= len(value) <= high:
            problems.append(f"Write {low} to {high} schedule rows, not {len(value)}.")
        day = date.fromisoformat(brief["date"])
        date_forms = {brief["date"], f"{day.day} {day:%B}", f"{day:%B} {day.day}", f"{day.day} {day:%b}"}
        times = " ".join(row["time"] for row in value).lower()
        if not any(form.lower() in times for form in date_forms) and not re.search(
                rf"\b{day.day}(st|nd|rd|th)?\s+{day:%B}".lower(), times):
            problems.append(f"One row's time must be the event date, {day.day} {day:%B} {day.year}.")

    if section == "activity_kpis":
        target = brief.get("attendance_target")
        if target is None and not any("TO CONFIRM" in item for item in value):
            problems.append("attendance_target is null: write [TO CONFIRM: minimum attendance] for attendance.")
        if target is not None and not any(re.search(rf"\b{target}\b", TO_CONFIRM_PATTERN.sub("", item)) for item in value):
            problems.append(f"Use the attendance target from the brief ({target}) in the attendance KPI.")

    return problems


def write_section(brief, section, facts=None, skip=None):
    """Write one section with the model (B3). Returns (value, problems_left).

    The model gets one retry with the list of broken rules. Problems that remain are returned so
    write_all_sections can list them for a person to check.
    """
    if section not in SECTIONS:
        raise ValueError(f"Unknown section: {section}")
    facts = club_facts() if facts is None else facts
    messages = build_messages(brief, section, facts, find_examples(brief, section, skip))
    schema = output_schema(section, facts)
    value, problems = None, []
    for _attempt in range(MAX_ATTEMPTS):
        try:
            value = parse_section(section, call_model(messages, schema))
        except SectionError as error:
            problems = [str(error)]
            continue
        problems = check_section(section, value, brief, facts)
        if not problems:
            break
        messages = [*messages,
                    {"role": "assistant", "content": json.dumps(value, ensure_ascii=False)},
                    {"role": "user", "content": "Fix these problems and reply with the full JSON again:\n- "
                                                + "\n- ".join(problems)}]
    if value is None:
        raise SectionError(f"{SECTION_LABELS[section]}: {problems[0] if problems else 'no reply'}")
    return value, problems


def write_all_sections(brief, skip=None):
    """Fill brief["sections"] for every name in SECTIONS and return the brief (B4).

    [TO CONFIRM: ...] notes and rules the model still broke after a retry are added to
    brief["to_confirm"], so the checker and the person reviewing the file see them.
    Raises OllamaError if the model cannot be reached.
    """
    facts = club_facts()
    sections = dict(brief.get("sections") or {})
    to_confirm = list(brief.get("to_confirm") or [])
    for section in SECTIONS:
        try:
            value, problems = write_section(brief, section, facts, skip)
        except SectionError as error:
            value, problems = None, [str(error)]
        label = SECTION_LABELS[section]
        if value is None:
            to_confirm.append(f"{label}: could not be written ({problems[0]}). Write it by hand.")
            continue
        sections[section] = value
        to_confirm += [f"{label}: {note.strip()}" for note in TO_CONFIRM_PATTERN.findall(_section_text(value))]
        to_confirm += [f"{label}: check this, {problem}" for problem in problems]
    brief["sections"] = sections
    brief["to_confirm"] = list(dict.fromkeys(to_confirm))
    return brief

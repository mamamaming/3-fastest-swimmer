"""Knowledge base: reading files, splitting them into chunks, search, club facts. Owner: Boom."""

import json
import math
import re
import threading
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

from docx import Document
from pypdf import PdfReader

from config import (
    CHUNK_OVERLAP, CHUNK_SIZE, CLUB_FACTS_PATH, DATA_FOLDER, EMBED_MODEL, INDEX_PATH,
    OLLAMA_EMBED_URL, RETRIEVAL_COUNT, SAMPLES_FOLDER, UPLOAD_FOLDER,
)
from ollama_client import OllamaError, ollama_post

INDEX_LOCK = threading.Lock()

# Yuay's form dropdown must use exactly these words.
EVENT_TYPES = ["open workshop", "members-only workshop", "social event", "long project", "other"]

# Section headings of the CSII proposal form, in order. The heading number in old proposals is
# sometimes wrong ("6 Activity KPIs", "1. Desired Characteristics"), so headings are matched by
# title: a line that starts with a number and then one of these titles.
PROPOSAL_SECTIONS = [
    ("Introduction", r"Introduction"),
    ("Objectives", r"Objectives"),
    ("Type of Activity", r"Type of Activity"),
    ("Project Duration", r"Project Duration"),
    ("Facilities", r"Facilities Needed"),
    ("Benefits", r"Benefits for"),
    ("Activity KPIs", r"Activity Key Performance"),
    ("Desired Characteristics", r"Desired Characteristics of Chulalongkorn"),
    ("Schedule", r"Schedule"),
    ("Responsibilities", r"Responsibilities"),
    ("Project Budget", r"Project Budget"),
    ("CSII Budget Resource", r"CSII Budget Resource"),
]
HEADING_PATTERN = re.compile(
    r"^[ \t]*\d{1,2}[ \t]*\.?[ \t]*(?P<title>"
    + "|".join(pattern for _, pattern in PROPOSAL_SECTIONS)
    + r")\b",
    re.IGNORECASE | re.MULTILINE,
)
# Everything from the proposer's acknowledgement onwards is the fixed CSII text.
APPENDIX_PATTERN = re.compile(r"^[ \t]*Proposer[ \t]*\(Acknowledgement\)", re.IGNORECASE | re.MULTILINE)
EVENT_NAME_PATTERN = re.compile(r"Activity/Event Name:[ \t]*(?P<name>[^\n]+)", re.IGNORECASE)
# Letterhead text repeated on every page. A line made only of these phrases is dropped from
# section text; a line with anything else in it (e.g. a heading) is kept.
LETTERHEAD_PHRASES = (
    "Room 318, 3rd Fl., Chaloem Rajakumari 60 Bldg.,",
    "Phayathai Road, Pathumwan, Bangkok 10330, Thailand",
    "Tel: 02-218-1251",
    "http://www.csii.chula.ac.th",
    "Bachelor of Arts and Science in Integrated Innovation",
    "Chulalongkorn School of Integrated Innovation",
)
# Short names Yuay's writer uses (writer.SECTIONS) mapped to the section labels above.
SECTION_ALIASES = {
    "introduction": "Introduction",
    "objectives": "Objectives",
    "benefits": "Benefits",
    "activity_kpis": "Activity KPIs",
    "kpis": "Activity KPIs",
    "characteristics": "Desired Characteristics",
    "desired_characteristics": "Desired Characteristics",
    "schedule": "Schedule",
    "facilities": "Facilities",
}
# A file that holds other files' text: hiding one of these hides the merged file too.
# Key = words that must all be in the merged file's name, in any order, so both
# "workshops-merged" and "19.10.26_ProposalBizcomp_Merged_Workshops_Final.pdf" match.
MERGED_SOURCES = {
    ("merged", "workshops"): ("inclusive-workshop-2", "members-only-workshop-1"),
}


def embed_texts(texts):
    """Create embeddings in modest batches to avoid oversized API requests."""
    vectors = []
    batch_size = 32
    for offset in range(0, len(texts), batch_size):
        response = ollama_post(
            OLLAMA_EMBED_URL,
            {"model": EMBED_MODEL, "input": texts[offset:offset + batch_size]},
            timeout=300,
        )
        batch = response.get("embeddings") if isinstance(response, dict) else None
        if not isinstance(batch, list) or len(batch) != len(texts[offset:offset + batch_size]):
            raise OllamaError(
                f"Ollama did not return embeddings. Ensure the {EMBED_MODEL} model is available."
            )
        for vector in batch:
            if not isinstance(vector, list) or not vector or not all(
                isinstance(value, (int, float)) and math.isfinite(value) for value in vector
            ):
                raise OllamaError("Ollama returned an invalid embedding.")
            vectors.append(vector)
    return vectors


def extract_document(filename, content):
    extension = Path(filename).suffix.lower()
    if extension == ".pdf":
        reader = PdfReader(BytesIO(content))
        pages = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append((page_number, text))
    elif extension == ".docx":
        document = Document(BytesIO(content))
        lines = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        for table in document.tables:
            for row in table.rows:
                lines.append(" | ".join(cell.text for cell in row.cells))
        pages = [(None, "\n".join(lines))]
    else:
        try:
            pages = [(None, content.decode("utf-8-sig"))]
        except UnicodeDecodeError as error:
            raise ValueError("This text file is not valid UTF-8 encoded text.") from error

    if not any(text.strip() for _, text in pages):
        raise ValueError("No readable text was found in this file. Scanned PDFs need OCR before upload.")
    return pages


def split_text(text, page_number=None):
    text = " ".join(text.split())
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start + CHUNK_SIZE // 2, end)
            if boundary > start:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append({"page": page_number, "text": chunk})
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def _is_letterhead(line):
    rest = line
    for phrase in LETTERHEAD_PHRASES:
        rest = rest.replace(phrase, "")
    return rest.strip() != line.strip() and not rest.strip()


def _clean_section_text(text):
    lines = [line for line in text.splitlines() if not _is_letterhead(line)]
    return " ".join(" ".join(lines).split())


def split_document(pages, event_type="other"):
    """Split a file into labelled chunks (A2).

    A proposal (a file with at least 3 known section headings) gives one chunk per section,
    labelled with section, event_name and event_type. Any other file (club facts, CSII rules)
    is split every CHUNK_SIZE characters and labelled section="reference".
    """
    if event_type not in EVENT_TYPES:
        event_type = "other"

    # Join the pages, remembering where each page starts so chunks keep a page number.
    full_text = ""
    page_starts = []
    for page_number, text in pages:
        page_starts.append((len(full_text), page_number))
        full_text += text + "\n"

    def page_at(offset):
        current = None
        for start, page_number in page_starts:
            if start > offset:
                break
            current = page_number
        return current

    headings = []
    for match in HEADING_PATTERN.finditer(full_text):
        title = match.group("title").lower()
        label = next(
            name for name, pattern in PROPOSAL_SECTIONS
            if re.fullmatch(pattern, title, re.IGNORECASE)
        )
        headings.append((match.start(), label))

    if len({label for _, label in headings}) < 3:
        chunks = []
        for page_number, text in pages:
            for chunk in split_text(text, page_number):
                chunk.update(section="reference", event_name="", event_type="")
                chunks.append(chunk)
        return chunks

    # A heading only counts if it comes after the previous one in form order. This skips
    # numbered lines inside a section that happen to start with a title word.
    order = [name for name, _ in PROPOSAL_SECTIONS]
    kept = []
    for start, label in headings:
        if not kept or order.index(label) > order.index(kept[-1][1]) or label == "Introduction":
            kept.append((start, label))

    appendix = APPENDIX_PATTERN.search(full_text, kept[-1][0])
    boundaries = kept + ([(appendix.start(), "Appendix")] if appendix else [])

    chunks = []
    for index, (start, label) in enumerate(boundaries):
        end = boundaries[index + 1][0] if index + 1 < len(boundaries) else len(full_text)
        names = [m.group("name").strip() for m in EVENT_NAME_PATTERN.finditer(full_text, 0, start)]
        text = _clean_section_text(full_text[start:end])
        if text:
            chunks.append({
                "page": page_at(start),
                "text": text,
                "section": label,
                "event_name": names[-1] if names else "",
                "event_type": event_type,
            })
    return chunks


def load_index():
    if not INDEX_PATH.exists():
        return []
    with INDEX_PATH.open("r", encoding="utf-8") as source:
        data = json.load(source)
    if not isinstance(data, list):
        raise ValueError("The local document index is not a valid list.")
    source_chunk_counts = {}
    for chunk in data:
        source = chunk.get("source", "")
        source_chunk_counts[source] = source_chunk_counts.get(source, 0) + 1
        chunk.setdefault("chunk", source_chunk_counts[source])
    return data


def save_index(chunks):
    DATA_FOLDER.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=DATA_FOLDER, delete=False) as temporary:
        json.dump(chunks, temporary, ensure_ascii=False)
        temporary_path = Path(temporary.name)
    temporary_path.replace(INDEX_PATH)


def cosine_similarity(left, right):
    if len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def retrieve_context(question):
    with INDEX_LOCK:
        chunks = load_index()
    if not chunks:
        return []
    question_vector = embed_texts([question])[0]
    ranked = sorted(
        ((cosine_similarity(question_vector, item["embedding"]), item) for item in chunks),
        key=lambda pair: pair[0],
        reverse=True,
    )
    return [item for score, item in ranked[:RETRIEVAL_COUNT] if score > 0]


def document_records():
    with INDEX_LOCK:
        chunks = load_index()
    counts = {}
    kinds = {}
    for chunk in chunks:
        counts[chunk["source"]] = counts.get(chunk["source"], 0) + 1
        if chunk.get("section") == "reference":
            kinds[chunk["source"]] = "reference"
        elif chunk.get("event_type"):
            kinds[chunk["source"]] = chunk["event_type"]
    files = []
    for path in UPLOAD_FOLDER.iterdir():
        if path.is_file():
            count = counts.get(path.name, 0)
            files.append({
                "name": path.name, "size": path.stat().st_size, "chunks": count,
                "event_type": kinds.get(path.name, ""),
            })
    return sorted(files, key=lambda item: item["name"].lower())


def section_label(section):
    """Turn "introduction", "activity_kpis" or "Activity KPIs" into the stored section label."""
    key = (section or "").strip()
    alias = SECTION_ALIASES.get(key.lower().replace(" ", "_"))
    if alias:
        return alias
    for name, _ in PROPOSAL_SECTIONS:
        if name.lower() == key.lower():
            return name
    return key


def _file_key(filename):
    return re.sub(r"[^a-z0-9]+", "-", filename.lower())


def hidden_sources(skip, sources):
    """Return the set of source filenames to leave out of a search.

    skip holds filenames or parts of them, e.g. ["inclusive-workshop-2"]. Hiding Inclusive
    Workshop 2 or Members Only Workshop 1 also hides workshops-merged, which contains both.
    """
    wanted = [_file_key(name) for name in (skip or []) if name and name.strip()]
    hidden = {source for source in sources if any(key in _file_key(source) for key in wanted)}
    for merged_words, parts in MERGED_SOURCES.items():
        if any(part in _file_key(source) for source in hidden for part in parts):
            hidden |= {source for source in sources
                       if all(word in _file_key(source) for word in merged_words)}
    return hidden


def search_sections(section, event_type, query, k=3, skip=None):
    """Return up to k chunks of one section from the most similar past proposals (A3).

    Only chunks whose section matches are returned, at most one per source file, so the
    writer gets k different examples. Chunks from the same event_type get a small bonus.
    skip: filenames (or parts of them) to leave out, for testing on unseen proposals.
    Each result has source, section, event_name, event_type, page, text and score.
    """
    label = section_label(section)
    with INDEX_LOCK:
        chunks = load_index()
    candidates = [chunk for chunk in chunks if chunk.get("section") == label and chunk.get("embedding")]
    hidden = hidden_sources(skip, {chunk.get("source", "") for chunk in candidates})
    candidates = [chunk for chunk in candidates if chunk.get("source") not in hidden]
    if not candidates:
        return []

    query_text = (query or "").strip() or f"{label} of a {event_type or 'club'} event"
    query_vector = embed_texts([query_text])[0]
    scored = []
    for chunk in candidates:
        score = cosine_similarity(query_vector, chunk["embedding"])
        if event_type and chunk.get("event_type") == event_type:
            score += 0.1
        scored.append((score, chunk))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    results = []
    seen_sources = set()
    for score, chunk in scored:
        if chunk["source"] in seen_sources:
            continue
        seen_sources.add(chunk["source"])
        result = {key: value for key, value in chunk.items() if key != "embedding"}
        result["score"] = round(score, 4)
        results.append(result)
        if len(results) >= max(1, int(k)):
            break
    return results


TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
TABLE_DIVIDER = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
KEY_VALUE = re.compile(r"^\s*(?:-\s+)?(?P<key>[A-Z][^:|]{0,60}?):\s+(?P<value>.+?)\s*$")


def parse_club_facts(text):
    """Parse club-facts Markdown into a dict. See load_club_facts()."""
    sections = {}
    current = None
    header = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = {"rows": [], "text": []}
            sections[line[3:].strip()] = current
            header = None
            continue
        if current is None or not line.strip():
            header = None if not line.strip() else header
            continue
        if TABLE_ROW.match(line):
            if TABLE_DIVIDER.match(line):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if header is None:
                header = cells
            else:
                current["rows"].append(dict(zip(header, cells)))
            continue
        header = None
        pair = KEY_VALUE.match(line)
        if pair and pair.group("key") not in current:
            current[pair.group("key").strip()] = pair.group("value")
        else:
            current["text"].append(line.strip().lstrip("- ").strip())

    facts = {"notes": {}}
    for heading, section in sections.items():
        rows, lines = section.pop("rows"), section.pop("text")
        if lines:
            section["text"] = lines
        if rows:
            facts[heading] = rows
            if section:
                facts["notes"][heading] = section
        else:
            facts[heading] = section
    return facts


def load_club_facts(path=CLUB_FACTS_PATH):
    """Read club-facts.md into a dict (A4).

    Each "## " heading is a key:
      - a section with a Markdown table -> list of dicts (column name -> cell text),
        e.g. facts["Officers"][0]["First name"]
      - a section of "- Key: value" lines -> dict, e.g. facts["Club"]["Name"]
    "Key: value" lines and other text written next to a table go to facts["notes"][heading],
    e.g. facts["notes"]["Budget AY2026"]["Remaining"] -> "400 THB".
    If the real file is missing, the made-up samples/club-facts.example.md is used, and
    facts["_source"] says which file was read.
    """
    path = Path(path)
    if not path.exists():
        path = SAMPLES_FOLDER / "club-facts.example.md"
    facts = parse_club_facts(path.read_text(encoding="utf-8-sig"))
    facts["_source"] = path.name
    return facts


def committee(facts, department=None):
    """Officers to list in a proposal: the 4 core officers, then the department in charge."""
    core = ["President", "Vice President", "Secretary", "Treasurer"]
    officers = facts.get("Officers", [])
    listed = [row for role in core for row in officers if row.get("Role") == role]
    if department:
        listed += [row for row in officers if row.get("Role", "").lower() == department.lower()]
    return listed

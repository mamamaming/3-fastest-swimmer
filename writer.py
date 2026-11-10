"""Form -> event brief, gap questions, and AI-written sections. Owner: Yuay."""

SECTIONS = [
    "introduction", "objectives", "benefits", "activity_kpis",
    "characteristics", "schedule", "facilities",
]


def build_brief(form):
    """Turn the submitted form into an event brief dict (B1). See docs/SPEC.md, ภาคผนวก ข."""
    raise NotImplementedError("build_brief is task B1 (Yuay). See docs/SPEC.md.")


def find_gaps(brief):
    """Return up to 3 questions about information the sections need but the brief lacks (B5)."""
    raise NotImplementedError("find_gaps is task B5 (Yuay). See docs/SPEC.md.")


def write_section(brief, section):
    """Write one section with the model, using examples from knowledge.search_sections (B3)."""
    raise NotImplementedError("write_section is task B3 (Yuay). See docs/SPEC.md.")


def write_all_sections(brief):
    """Fill brief["sections"] for every name in SECTIONS and return the brief (B4)."""
    raise NotImplementedError("write_all_sections is task B4 (Yuay). See docs/SPEC.md.")

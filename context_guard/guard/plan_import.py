"""Parsing a phased PLAN-N.md into the structure `cg new --from-plan`
materializes as changes.

Plans are written by humans and by disciplined-scaffold's template, in
Spanish or English, and rarely follow the template exactly. The parser is
deliberately permissive about sub-blocks (a missing one is empty, not an
error) and strict about one thing only: a document with no phase heading is
not a plan.
"""

import os
import re

from .errors import EXIT_VALIDATION, GuardError

# `## F1 — Name`, `## F2 - Name`, `## F3: Name`, or just `## F1`.
PHASE_RE = re.compile(r"^##\s+(F\d+)\s*(?:[—–\-:]\s*(.*))?$")

# Any `## ` heading closes the preceding phase, including "Out of scope".
SECTION_RE = re.compile(r"^##\s+")

TITLE_RE = re.compile(r"^#\s+(.*)$")

# `**Spec:**`, `**Tests:** trailing text on the same line`, etc. The template
# puts prose after the label, so the remainder of the line is captured too.
SUBBLOCK_RE = re.compile(r"^\*\*\s*([^*:]+?)\s*:?\s*\*\*:?\s*(.*)$")

# Sub-block labels, English and the Spanish equivalents the repo's own plans
# use. Matched case-insensitively against the label text.
SUBBLOCK_ALIASES = {
    "spec": {"spec", "especificación", "especificacion"},
    "tests": {"tests", "test", "pruebas"},
    "acceptance": {
        "acceptance criteria",
        "acceptance",
        "criterios de aceptación",
        "criterios de aceptacion",
        "criterio",
        "criterios",
    },
}


class PlanPhase:
    """One `## F<N>` block: what changes, and the sub-blocks that describe
    how it is specified, tested and accepted."""

    def __init__(self, id, name, body="", spec="", tests="", acceptance=""):
        self.id = id
        self.name = name
        self.body = body
        self.spec = spec
        self.tests = tests
        self.acceptance = acceptance

    def __repr__(self):
        return f"PlanPhase({self.id!r}, {self.name!r})"


class Plan:
    def __init__(self, title, objective, phases, path=None):
        self.title = title
        self.objective = objective
        self.phases = phases
        self.path = path

    def __repr__(self):
        return f"Plan({self.title!r}, {len(self.phases)} phases)"


def _classify(label):
    normalized = label.strip().lower()
    for key, aliases in SUBBLOCK_ALIASES.items():
        if normalized in aliases:
            return key
    return None


def _join(lines):
    return "\n".join(lines).strip()


def parse_plan(path):
    """Read a PLAN-N.md and return a Plan.

    Raises GuardError for a missing file or a document with no phases.
    """
    if not os.path.isfile(path):
        raise GuardError(f"FAIL|PLAN_NOT_FOUND|{path}", EXIT_VALIDATION)

    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    title = ""
    objective_lines = []
    phases = []

    current = None          # PlanPhase being filled
    current_block = None    # None -> body, else one of SUBBLOCK_ALIASES keys
    buffers = {}
    seen_title = False

    def flush():
        if current is None:
            return
        current.body = _join(buffers.get("body", []))
        current.spec = _join(buffers.get("spec", []))
        current.tests = _join(buffers.get("tests", []))
        current.acceptance = _join(buffers.get("acceptance", []))
        phases.append(current)

    for line in lines:
        title_match = TITLE_RE.match(line)
        if title_match and not seen_title:
            title = title_match.group(1).strip()
            seen_title = True
            continue

        phase_match = PHASE_RE.match(line)
        if phase_match:
            flush()
            current = PlanPhase(
                phase_match.group(1), (phase_match.group(2) or "").strip()
            )
            current_block = None
            buffers = {"body": [], "spec": [], "tests": [], "acceptance": []}
            continue

        if SECTION_RE.match(line):
            # A non-phase section ends the current phase; anything after it
            # (Out of scope, cycle criteria) belongs to no phase.
            flush()
            current = None
            current_block = None
            buffers = {}
            continue

        if current is None:
            # Prose between the H1 and the first `## ` heading is the
            # one-sentence objective.
            if seen_title and not phases:
                objective_lines.append(line)
            continue

        sub_match = SUBBLOCK_RE.match(line)
        if sub_match:
            kind = _classify(sub_match.group(1))
            if kind is not None:
                current_block = kind
                remainder = sub_match.group(2).strip()
                if remainder:
                    buffers[kind].append(remainder)
                continue

        buffers["body" if current_block is None else current_block].append(line)

    flush()

    if not phases:
        raise GuardError(f"FAIL|PLAN_NO_PHASES|{path}", EXIT_VALIDATION)

    return Plan(title, _join(objective_lines), phases, path=path)

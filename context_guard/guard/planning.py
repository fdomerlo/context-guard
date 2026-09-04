"""Native planning engine for Context Guard (Fase 3: Planning).

Transforms human requirements or legacy PLAN-N.md files into structured
changes in .context-guard/changes/{name}/, with:
- Objective
- Specification
- Phases (F1, F2...)
- Tasks
- Dependencies
- Acceptance criteria
- Verification criteria

The manifest.json is the single source of truth; plan.md, objective.md, and
tasks.md are derived views synchronized with the state.
"""

import os
import re

from .assets import PHASES, get_phase
from .errors import CommandResult, EXIT_OK, EXIT_VALIDATION, GuardError
from .manifest import (
    add_phase,
    create_initial_manifest,
    load_manifest,
    save_manifest,
)
from .paths import (
    get_paths,
    list_changes,
    resolve_change,
    validate_change_name,
)
from .plan_import import (
    neutralize_sentinel,
    parse_plan,
    phase_objective,
    phase_tasks,
)
from .setup import (
    antigravity_detected,
    cursor_detected,
    materialise_antigravity_rule,
    materialise_cursor_rule,
    materialise_phases,
)
from .transaction import cmd_begin

# Stop words stripped when generating change name from requirement
STOP_WORDS = {
    "a", "an", "the", "and", "or", "to", "for", "of", "in", "on", "at",
    "un", "una", "el", "la", "los", "las", "de", "para", "en", "con",
    "implementar", "implement", "agregar", "add", "crear", "create",
}


def slugify_requirement(text, max_length=40):
    """Generate a valid, human-readable change name from a requirement string."""
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    meaningful = [w for w in words if w not in STOP_WORDS]
    if not meaningful:
        meaningful = words or ["change"]
    
    slug = "-".join(meaningful)
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    if not slug:
        slug = "change"
    return slug


def render_plan_markdown(manifest):
    """Render a human-readable plan.md from manifest state."""
    name = manifest.get("change_name", "unnamed")
    objective = manifest.get("objective") or manifest.get("requirement", "No objective specified.")
    lines = [
        f"# Plan: {name}",
        "",
        "## Objective",
        objective,
        "",
    ]
    if manifest.get("spec"):
        lines.extend(["## Specification", manifest["spec"], ""])

    phases = manifest.get("phases", [])
    if phases:
        lines.extend(["## Phases", ""])
        for p in phases:
            p_id = p.get("id", "F1")
            p_name = p.get("name", "")
            lines.append(f"### {p_id} — {p_name}".rstrip(" —"))
            lines.append("")
            if p.get("spec"):
                lines.extend([f"**Spec:** {p['spec']}", ""])
            if p.get("dependencies"):
                deps = ", ".join(p["dependencies"])
                lines.extend([f"**Dependencies:** {deps}", ""])
            
            tasks = p.get("tasks", [])
            if tasks:
                lines.append("**Tasks:**")
                for t in tasks:
                    status_char = "x" if t.get("status") == "done" else " "
                    lines.append(f"- [{status_char}] {t.get('id', '')} {t.get('description', '')}".strip())
                lines.append("")

            criteria = p.get("acceptance_criteria", [])
            if criteria:
                lines.append("**Acceptance Criteria:**")
                for c in criteria:
                    status_char = "x" if c.get("completed") else " "
                    lines.append(f"- [{status_char}] {c.get('description', '')}")
                lines.append("")

            verif = p.get("verification", {})
            if isinstance(verif, dict) and verif.get("command"):
                lines.extend([f"**Verification:** `{verif['command']}`", ""])

    out_of_scope = manifest.get("out_of_scope")
    if out_of_scope:
        lines.extend(["## Out of Scope", out_of_scope, ""])

    return "\n".join(lines).strip() + "\n"


def render_tasks_markdown(manifest):
    """Render tasks.md for next-task and agent tracking across phases."""
    name = manifest.get("change_name", "unnamed")
    phases = manifest.get("phases", [])
    if not phases:
        return f"# Tasks: {name}\n\n- [ ] 1.1 Complete required change\n"

    lines = [f"# Tasks: {name}", ""]
    for p in phases:
        p_id = p.get("id", "F1")
        p_name = p.get("name", "")
        lines.append(f"## {p_id} — {p_name}".rstrip(" —"))
        lines.append("")

        tasks = p.get("tasks", [])
        if tasks:
            lines.append("### Tasks")
            for t in tasks:
                status_char = "x" if t.get("status") == "done" else " "
                lines.append(f"- [{status_char}] {t.get('id', '')} {t.get('description', '')}".strip())
            lines.append("")

        criteria = p.get("acceptance_criteria", [])
        if criteria:
            lines.append("### Acceptance Criteria")
            for c in criteria:
                status_char = "x" if c.get("completed") else " "
                crit_id = c.get("id", "")
                desc = c.get("description", "")
                prefix = f"{crit_id} " if crit_id else ""
                lines.append(f"- [{status_char}] {prefix}{desc}".strip())
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def cmd_plan(context=".", requirement=None, name=None, from_plan=None, spec=None, phases=None):
    """Create or inspect a structured change plan.

    If requirement or from_plan is given:
      Creates a new change structured into Objective, Phases, Tasks, Acceptance criteria.
      The change lands in lock_phase=PLAN, requiring human `cg approve` to reach EXECUTE.
    If neither is given:
      Inspects and prints the plan of the active change.
    """
    # Inspection mode if no requirement or from_plan
    if not requirement and not from_plan:
        try:
            active_change = resolve_change(context, name)
        except Exception as e:
            return CommandResult(
                "FAIL|NO_REQUIREMENT|Provide a requirement string or --from-plan <file>\n"
                "  Example: cg plan \"Implement OAuth2 authentication\"\n"
                "  Example: cg plan --from-plan PLAN-1.md",
                EXIT_VALIDATION,
            )
        p = get_paths(context, active_change)
        plan_path = os.path.join(p["base"], "plan.md")
        if os.path.isfile(plan_path):
            with open(plan_path, "r", encoding="utf-8") as f:
                return CommandResult(f.read().strip(), EXIT_OK)
        manifest = load_manifest(context, active_change)
        if manifest:
            return CommandResult(render_plan_markdown(manifest).strip(), EXIT_OK)
        return CommandResult(f"FAIL|PLAN_NOT_FOUND|change={active_change}", EXIT_VALIDATION)

    # Creation mode from legacy PLAN-N.md
    if from_plan:
        plan = parse_plan(from_plan)
        change_name = name or slugify_requirement(plan.title or os.path.basename(from_plan))
        change_name = validate_change_name(change_name)
        p = get_paths(context, change_name)

        if os.path.exists(p["manifest"]):
            return CommandResult(f"FAIL|CHANGE_EXISTS|{change_name}", EXIT_VALIDATION)

        os.makedirs(p["base"], exist_ok=True)
        structured_phases = []
        for idx, phase in enumerate(plan.phases, start=1):
            phase_id = phase.id or f"F{idx}"
            # Extract tasks from phase
            tasks = []
            if phase.tests:
                for line in phase.tests.splitlines():
                    s = line.strip().lstrip("-* ").strip()
                    if s:
                        tasks.append({"id": f"{idx}.{len(tasks) + 1}", "description": s, "status": "pending"})
            if not tasks and phase.body:
                tasks.append({"id": f"{idx}.1", "description": phase.body.splitlines()[0], "status": "pending"})

            # Extract criteria
            criteria = []
            if phase.acceptance:
                for line in phase.acceptance.splitlines():
                    s = line.strip().lstrip("-* []").strip()
                    if s:
                        criteria.append({"id": f"ac-{idx}.{len(criteria) + 1}", "description": s, "completed": False})

            structured_phases.append({
                "id": phase_id,
                "name": phase.name,
                "status": "pending",
                "spec": phase.spec,
                "dependencies": [f"F{idx - 1}"] if idx > 1 else [],
                "tasks": tasks,
                "acceptance_criteria": criteria,
                "verification": {"command": "pytest", "status": "pending"},
            })

        manifest = create_initial_manifest(
            context,
            change=change_name,
            requirement=plan.title,
            objective=plan.objective or plan.title,
            phases=structured_phases,
        )
        save_manifest(context, manifest, change_name)

        # Write artifacts
        plan_md = render_plan_markdown(manifest)
        tasks_md = render_tasks_markdown(manifest)
        obj_md = f"# Objective: {change_name}\n\n{plan.objective or plan.title}\n"
        with open(os.path.join(p["base"], "plan.md"), "w", encoding="utf-8") as f:
            f.write(plan_md)
        with open(os.path.join(p["base"], "tasks.md"), "w", encoding="utf-8") as f:
            f.write(tasks_md)
        with open(os.path.join(p["base"], "objective.md"), "w", encoding="utf-8") as f:
            f.write(obj_md)
        with open(os.path.join(p["base"], "snapshot.md"), "w", encoding="utf-8") as f:
            f.write("[PENDING] Snapshot recorded when work starts\n")

        # Begin PLAN phase transaction
        cmd_begin(context, "PLAN", change=change_name)
        materialise_phases(context)

        return CommandResult(
            f"SUCCESS|PLAN_CREATED|{change_name}|phases={len(structured_phases)}|status=PLAN\n"
            f"  Next: review .context-guard/changes/{change_name}/plan.md\n"
            f"  Then ask human: cg approve --change {change_name}",
            EXIT_OK,
        )

    # Creation mode from requirement string
    change_name = name or slugify_requirement(requirement)
    change_name = validate_change_name(change_name)
    p = get_paths(context, change_name)

    if os.path.exists(p["manifest"]):
        return CommandResult(f"FAIL|CHANGE_EXISTS|{change_name}", EXIT_VALIDATION)

    os.makedirs(p["base"], exist_ok=True)

    # Decompose into phases
    if phases and isinstance(phases, list):
        phase_list = phases
    else:
        # Standard structured decomposition into phases:
        # F1: Spec & Core implementation
        # F2: Verification & Edge cases
        phase_list = [
            {
                "id": "F1",
                "name": "Core Implementation",
                "status": "pending",
                "spec": spec or f"Implement core functionality for: {requirement}",
                "dependencies": [],
                "tasks": [
                    {"id": "1.1", "description": "Write failing unit/adversarial tests (RED)", "status": "pending"},
                    {"id": "1.2", "description": "Implement feature code to pass tests (GREEN)", "status": "pending"},
                ],
                "acceptance_criteria": [
                    {"id": "ac-1.1", "description": f"Core requirement demonstrably functional: {requirement}", "completed": False},
                    {"id": "ac-1.2", "description": "Unit and regression test suite passes cleanly", "completed": False},
                ],
                "verification": {"command": "pytest", "status": "pending"},
            },
            {
                "id": "F2",
                "name": "Verification & Integration",
                "status": "pending",
                "spec": "Comprehensive test coverage, edge cases, and verification",
                "dependencies": ["F1"],
                "tasks": [
                    {"id": "2.1", "description": "Add adversarial edge case tests", "status": "pending"},
                    {"id": "2.2", "description": "Verify end-to-end integration and run full suite", "status": "pending"},
                ],
                "acceptance_criteria": [
                    {"id": "ac-2.1", "description": "Zero regressions across entire test suite", "completed": False},
                ],
                "verification": {"command": "pytest", "status": "pending"},
            },
        ]

    manifest = create_initial_manifest(
        context,
        change=change_name,
        requirement=requirement,
        objective=requirement,
        phases=phase_list,
    )
    if spec:
        manifest["spec"] = spec
    save_manifest(context, manifest, change_name)

    # Derived artifacts
    plan_md = render_plan_markdown(manifest)
    tasks_md = render_tasks_markdown(manifest)
    obj_md = f"# Objective: {change_name}\n\n{requirement}\n"
    with open(os.path.join(p["base"], "plan.md"), "w", encoding="utf-8") as f:
        f.write(plan_md)
    with open(os.path.join(p["base"], "tasks.md"), "w", encoding="utf-8") as f:
        f.write(tasks_md)
    with open(os.path.join(p["base"], "objective.md"), "w", encoding="utf-8") as f:
        f.write(obj_md)
    with open(os.path.join(p["base"], "snapshot.md"), "w", encoding="utf-8") as f:
        f.write("[PENDING] Snapshot recorded when work starts\n")

    # Begin PLAN phase transaction
    cmd_begin(context, "PLAN", change=change_name)
    materialise_phases(context)

    return CommandResult(
        f"SUCCESS|PLAN_CREATED|{change_name}|phases={len(phase_list)}|status=PLAN\n"
        f"  Objective: {requirement}\n"
        f"  Plan view: .context-guard/changes/{change_name}/plan.md\n"
        f"  Tasks:     .context-guard/changes/{change_name}/tasks.md\n"
        f"  Next: human reviews plan, then runs: cg approve --change {change_name}",
        EXIT_OK,
    )

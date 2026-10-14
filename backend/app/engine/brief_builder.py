"""Template-only brief rendering; facts are supplied by the deterministic snapshot."""
from __future__ import annotations

import html


def _lines(values):
    return [str(value).strip() for value in values if str(value).strip()]


def build_morning_brief(snapshot: dict, *, now) -> dict:
    attention = snapshot.get("attention", {})
    needs = list(attention.get("needs_now", ()))
    decisions = list(attention.get("decisions_waiting", ()))
    risk = list(attention.get("at_risk", ()))
    plan = snapshot.get("plan", {})
    counts = snapshot.get("counts", {})
    top = [f"{item.get('title', 'Action')}: {item.get('reason', '')}" for item in (needs + decisions)[:3]]
    content = {
        "headline": f"{counts.get('on_track', 0)} on track · {len(needs)} need you · {len(decisions)} decision waiting",
        "if_you_only_do_three_things": _lines(top),
        "key_times_today": _lines(snapshot.get("key_times", ())),
        "on_duty": _lines(snapshot.get("on_duty", ())),
        "routine_plan": _lines([f"{block.get('title')} · {block.get('start'):%H:%M}–{block.get('end'):%H:%M}" for block in plan.get("blocks", ()) if block.get("kind") == "ROUTINE_BLOCK"]),
        "decisions_waiting": _lines([item.get("title", "Decision") for item in decisions]),
        "at_risk_next_48h": _lines([item.get("reason", item.get("title", "")) for item in risk]),
        "incidents_last_24h": _lines(snapshot.get("incidents_last_24h", ())),
        "carry_overs": _lines(snapshot.get("carry_overs", ())),
    }
    rendered = "CareCircle morning summary\n" + content["headline"] + "\n\nIf you only do 3 things:\n" + "\n".join(f"• {x}" for x in content["if_you_only_do_three_things"])
    for key, label in (("key_times_today", "Key times today"), ("on_duty", "On duty"), ("routine_plan", "Routine plan"), ("decisions_waiting", "Decisions waiting"), ("at_risk_next_48h", "At risk next 48 hours"), ("incidents_last_24h", "Incidents in the last 24 hours"), ("carry_overs", "Carry-overs")):
        if content[key]: rendered += f"\n\n{label}:\n" + "\n".join(f"• {x}" for x in content[key])
    rendered = rendered[:2000]
    return {"content": content, "rendered_text": rendered, "rendered_html": "<article><h1>" + html.escape(content["headline"]) + "</h1><pre>" + html.escape(rendered) + "</pre></article>", "ai_enhanced": False}


def build_handover_brief(snapshot: dict, *, now, notes: str = "") -> dict:
    safe_notes = "".join(ch for ch in notes if ch in "\n\t" or ord(ch) >= 32)[:2000]
    content = {"done_today": _lines(snapshot.get("done_today", ())), "carry_over": _lines(snapshot.get("carry_over", ())), "incidents": _lines(snapshot.get("incidents", ())), "pending_actions": _lines(snapshot.get("pending_actions", ())), "tomorrow": _lines(snapshot.get("tomorrow", ())), "overnight_coverage": _lines(snapshot.get("overnight_coverage", ())), "medication_support_completed": _lines(snapshot.get("medication_support_completed", ())), "notes": safe_notes}
    labels = (("done_today", "Done today"), ("carry_over", "Carry over"), ("incidents", "Incidents"), ("pending_actions", "Pending actions"), ("tomorrow", "Tomorrow"), ("overnight_coverage", "Overnight / early morning coverage"), ("medication_support_completed", "Medication-support tasks completed"), ("notes", "Outgoing caretaker notes"))
    rendered = "CareCircle end-of-day handover"
    for key, label in labels:
        if content[key]: rendered += f"\n\n{label}:\n" + "\n".join(f"• {x}" for x in ([content[key]] if isinstance(content[key], str) else content[key]))
    rendered = rendered[:2000]
    return {"content": content, "rendered_text": rendered, "rendered_html": "<article><h1>CareCircle end-of-day handover</h1><pre>" + html.escape(rendered) + "</pre></article>", "ai_enhanced": False}

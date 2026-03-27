import uuid
from typing import Any


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def create_agent_trace(*, label: str, kind: str, summary: str | None = None) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "label": label,
        "kind": kind,
        "status": "running",
        "summary": _clean_text(summary),
        "reasoning": [],
        "steps": [],
        "children": [],
    }


def set_agent_summary(agent_trace: dict[str, Any], summary: str | None) -> None:
    agent_trace["summary"] = _clean_text(summary)


def add_agent_reasoning(agent_trace: dict[str, Any], text: str | None) -> None:
    cleaned = _clean_text(text)
    if not cleaned:
        return
    reasoning = agent_trace.setdefault("reasoning", [])
    if cleaned not in reasoning:
        reasoning.append(cleaned)


def add_agent_step(
    agent_trace: dict[str, Any],
    *,
    title: str,
    kind: str,
    tool_name: str | None = None,
    summary: str | None = None,
    status: str = "running",
    input_summary: str | None = None,
    output_summary: str | None = None,
    citations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    step = {
        "id": str(uuid.uuid4()),
        "title": title,
        "kind": kind,
        "toolName": tool_name,
        "status": status,
        "summary": _clean_text(summary),
        "inputSummary": _clean_text(input_summary),
        "outputSummary": _clean_text(output_summary),
        "citations": citations or [],
    }
    agent_trace.setdefault("steps", []).append(step)
    return step


def update_agent_step(
    step: dict[str, Any],
    *,
    status: str | None = None,
    summary: str | None = None,
    input_summary: str | None = None,
    output_summary: str | None = None,
    citations: list[dict[str, Any]] | None = None,
) -> None:
    if status:
        step["status"] = status
    if summary is not None:
        step["summary"] = _clean_text(summary)
    if input_summary is not None:
        step["inputSummary"] = _clean_text(input_summary)
    if output_summary is not None:
        step["outputSummary"] = _clean_text(output_summary)
    if citations is not None:
        step["citations"] = citations


def add_child_agent(agent_trace: dict[str, Any], child_trace: dict[str, Any]) -> None:
    agent_trace.setdefault("children", []).append(child_trace)


def complete_agent(agent_trace: dict[str, Any], *, summary: str | None = None) -> None:
    agent_trace["status"] = "completed"
    if summary is not None:
        set_agent_summary(agent_trace, summary)


def fail_agent(agent_trace: dict[str, Any], message: str) -> None:
    agent_trace["status"] = "failed"
    set_agent_summary(agent_trace, message)
    add_agent_reasoning(agent_trace, message)

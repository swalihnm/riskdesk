"""Function-calling drafter (async).

The local model may call only the engine tools listed in TOOL_SPECS, with arguments checked by
validate_call(). Every figure it can see comes from a tool result. The final note is constrained to the
JSON schema and then checked by the grounding gate in the graph, so a figure it writes that no tool returned
is blocked.

Flow:  call tools (up to MAX_STEPS)  ->  constrained final note  ->  return (text, tool results, calls)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from riskdesk import tools as T
from riskdesk.agents.drafters import NOTE_SCHEMA, parse_note
from riskdesk.config import OLLAMA_MODEL, OLLAMA_URL
from riskdesk.engine.book import DESKS

MAX_STEPS = 6
ALLOWED_METHODS = ["historical", "parametric"]  # monte_carlo is excluded: too slow for an interactive note
DESK_ENUM = list(DESKS)

TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "limit_status",
        "description": "Utilisation and status (OK, WARNING, BREACH) for every desk and limit.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "compute_var",
        "description": "One-day 99% VaR for one desk.",
        "parameters": {"type": "object", "properties": {
            "desk": {"type": "string", "enum": DESK_ENUM},
            "method": {"type": "string", "enum": ALLOWED_METHODS}}, "required": ["desk"]}}},
    {"type": "function", "function": {
        "name": "attribution",
        "description": "Euler component VaR by underlying for one desk, with the top-two margin.",
        "parameters": {"type": "object", "properties": {"desk": {"type": "string", "enum": DESK_ENUM}},
                       "required": ["desk"]}}},
    {"type": "function", "function": {
        "name": "data_checks",
        "description": "Jump checks and quality flags for the underlyings one desk holds.",
        "parameters": {"type": "object", "properties": {"desk": {"type": "string", "enum": DESK_ENUM}},
                       "required": ["desk"]}}},
    {"type": "function", "function": {
        "name": "stress_test",
        "description": "Worst stress loss for one desk across named and historical scenarios.",
        "parameters": {"type": "object", "properties": {"desk": {"type": "string", "enum": DESK_ENUM}},
                       "required": ["desk"]}}},
    {"type": "function", "function": {
        "name": "search_policy",
        "description": "Find policy sections by topic. Returns section IDs and headings only.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string", "maxLength": 200}},
                       "required": ["query"]}}},
]
TOOL_NAMES = {t["function"]["name"] for t in TOOL_SPECS}


def validate_call(name: str, args: dict[str, Any]) -> str | None:
    """Returns an error message if the call is not allowed, else None."""
    if name not in TOOL_NAMES:
        return f"unknown tool '{name}'"
    if not isinstance(args, dict):
        return "arguments must be an object"
    if name == "limit_status":
        return None if not args else "limit_status takes no arguments"
    if name == "search_policy":
        q = args.get("query")
        if not isinstance(q, str) or not q.strip() or len(q) > 200:
            return "query must be a non-empty string of at most 200 characters"
        return None
    desk = args.get("desk")
    if desk not in DESK_ENUM:
        return f"desk must be one of {DESK_ENUM}"
    if name == "compute_var" and args.get("method", "historical") not in ALLOWED_METHODS:
        return f"method must be one of {ALLOWED_METHODS}"
    extra = set(args) - {"desk", "method"} if name == "compute_var" else set(args) - {"desk"}
    if extra:
        return f"unexpected arguments: {sorted(extra)}"
    return None


def _dispatch(session, name: str, args: dict[str, Any]) -> dict:
    """Runs one validated tool call against the engine. Synchronous; called in a worker thread."""
    if name == "limit_status":
        return {"limit_rows": T.limit_status(session)}
    if name == "compute_var":
        return T.compute_var(session, args["desk"], args.get("method", "historical"))
    if name == "attribution":
        return T.attribution(session, args["desk"])
    if name == "data_checks":
        return T.data_checks(session, args["desk"])
    if name == "stress_test":
        return T.stress(session, args["desk"])
    if name == "search_policy":
        hits = T.search_policy(session, args["query"], 3)
        return {"policy_hits": [{"id": h["id"], "heading": h["heading"]} for h in hits if not h["quarantined"]]}
    raise ValueError(name)


async def run_tool_agent(session, context: dict, prompt: dict, *, model: str = OLLAMA_MODEL,
                         url: str = OLLAMA_URL, client: httpx.AsyncClient | None = None,
                         max_steps: int = MAX_STEPS) -> dict:
    """Returns {"summary", "tool_outputs", "tool_calls", "tokens", "error"}.

    summary is None when the model made no valid tool call or its final note fails validation; the graph then
    falls back to the template drafter and records the reason.
    """
    own = client is None
    client = client or httpx.AsyncClient(timeout=300)
    messages: list[dict] = [{"role": "system", "content": prompt["system"]},
                            {"role": "user", "content": prompt["tool_prompt"].format(
                                desk=context["desk"], metric=context["metric"],
                                classification=context["classification"])}]
    tool_outputs: list[dict] = []
    calls: list[dict] = []
    tokens = 0
    error = None
    try:
        for _ in range(max_steps):
            r = await client.post(f"{url}/api/chat", json={
                "model": model, "messages": messages, "tools": TOOL_SPECS, "stream": False,
                "options": {"temperature": 0}})
            r.raise_for_status()
            body = r.json()
            tokens += body.get("eval_count", 0)
            msg = body["message"]
            messages.append(msg)
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                break
            for tc in tool_calls:
                fn = tc["function"]
                name, args = fn.get("name", ""), fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = None
                err = validate_call(name, args) if args is not None else "arguments were not valid JSON"
                if err:
                    result = {"error": err}
                else:
                    result = await asyncio.to_thread(_dispatch, session, name, args)
                    tool_outputs.append(result)
                calls.append({"name": name, "args": args, "ok": err is None})
                messages.append({"role": "tool", "name": name, "content": json.dumps(result, default=str)})
        if not calls or not any(c["ok"] for c in calls):
            return {"summary": None, "tool_outputs": tool_outputs, "tool_calls": calls, "tokens": tokens,
                    "error": "no valid tool call"}
        messages.append({"role": "user", "content": 'Now write the note. Respond with JSON {"summary": "..."} only.'})
        r = await client.post(f"{url}/api/chat", json={
            "model": model, "messages": messages, "stream": False, "format": NOTE_SCHEMA,
            "options": {"temperature": 0}})
        r.raise_for_status()
        body = r.json()
        tokens += body.get("eval_count", 0)
        summary = parse_note(body["message"]["content"])
        return {"summary": summary, "tool_outputs": tool_outputs, "tool_calls": calls, "tokens": tokens,
                "error": None}
    except Exception as e:  # any failure falls back to the template drafter in the graph
        error = f"{type(e).__name__}: {str(e)[:200]}"
        return {"summary": None, "tool_outputs": tool_outputs, "tool_calls": calls, "tokens": tokens,
                "error": error}
    finally:
        if own:
            await client.aclose()

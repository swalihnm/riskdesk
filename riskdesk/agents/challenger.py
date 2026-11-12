"""Challenger agent: an independent second reviewer of the breach classification (async).

Why a second agent: effective challenge. The first analyst's conclusion is checked by a reviewer who
was not shown it, who uses only read-only engine tools, and who reaches a conclusion of their own.

Authority: the challenger can add an escalation, never remove one. Disagreement, or low confidence, or a
failure of the challenge itself, sends the case to a human. Agreement changes nothing.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from riskdesk import tools as T
from riskdesk.agents.tool_agent import DESK_ENUM
from riskdesk.config import OLLAMA_MODEL, OLLAMA_URL

MAX_STEPS = 6
CONFIDENCE_FLOOR = 0.5
CHALLENGE_TOOLS = ["limit_status", "attribution", "baseline", "data_checks"]

TOOL_SPECS = [
    {"type": "function", "function": {"name": "limit_status", "description": "Utilisation and status for every desk and limit.",
                                      "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "attribution", "description": "Euler component VaR by underlying for one desk.",
                                      "parameters": {"type": "object", "properties": {"desk": {"type": "string", "enum": DESK_ENUM}},
                                                     "required": ["desk"]}}},
    {"type": "function", "function": {"name": "baseline", "description": "Baseline one-day 99% VaR and hard limit for one desk.",
                                      "parameters": {"type": "object", "properties": {"desk": {"type": "string", "enum": DESK_ENUM}},
                                                     "required": ["desk"]}}},
    {"type": "function", "function": {"name": "data_checks", "description": "Jump checks and quality flags for one desk.",
                                      "parameters": {"type": "object", "properties": {"desk": {"type": "string", "enum": DESK_ENUM}},
                                                     "required": ["desk"]}}},
]

CHALLENGE_SCHEMA = {
    "type": "object",
    "properties": {
        "classification": {"type": "string", "enum": ["market_move", "data_issue", "limit_error"]},
        "top_driver": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["classification", "top_driver", "confidence"],
}


class Challenge(BaseModel):
    classification: Literal["market_move", "data_issue", "limit_error"]
    top_driver: str = Field(min_length=1, max_length=40)
    confidence: float = Field(ge=0.0, le=1.0)


def validate_call(name: str, args: Any) -> str | None:
    if name not in CHALLENGE_TOOLS:
        return f"unknown tool '{name}'"
    if not isinstance(args, dict):
        return "arguments must be an object"
    if name == "limit_status":
        return None if not args else "limit_status takes no arguments"
    if args.get("desk") not in DESK_ENUM:
        return f"desk must be one of {DESK_ENUM}"
    if set(args) - {"desk"}:
        return f"unexpected arguments: {sorted(set(args) - {'desk'})}"
    return None


def _dispatch(session, name: str, args: dict) -> dict:
    if name == "limit_status":
        return {"limit_rows": T.limit_status(session)}
    if name == "attribution":
        return T.attribution(session, args["desk"])
    if name == "baseline":
        return T.baseline(session, args["desk"])
    if name == "data_checks":
        return T.data_checks(session, args["desk"])
    raise ValueError(name)


def compare(primary: dict, challenge: dict) -> tuple[bool, list[str]]:
    """Returns (agrees, reasons). Reasons are empty when the challenge agrees."""
    reasons = []
    if challenge["classification"] != primary["classification"]:
        reasons.append(f"classification disagrees: challenger {challenge['classification']}, "
                       f"primary {primary['classification']}")
    if primary.get("top_driver") and challenge["top_driver"] != primary["top_driver"]:
        reasons.append(f"top driver disagrees: challenger {challenge['top_driver']}, primary {primary['top_driver']}")
    if challenge["confidence"] < CONFIDENCE_FLOOR:
        reasons.append(f"challenger confidence {challenge['confidence']:.2f} is below {CONFIDENCE_FLOOR}")
    return (not reasons), reasons


async def run_challenger(session, context: dict, prompt: dict, *, model: str = OLLAMA_MODEL,
                         url: str = OLLAMA_URL, client: httpx.AsyncClient | None = None) -> dict:
    """Returns {"challenge": Challenge fields or None, "tool_calls": [...], "tokens", "error"}."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=300)
    messages: list[dict] = [
        {"role": "system", "content": prompt["system"]},
        {"role": "user", "content": prompt["tool_prompt"].format(desk=context["desk"], metric=context["metric"])},
    ]
    calls: list[dict] = []
    tokens = 0
    try:
        for _ in range(MAX_STEPS):
            r = await client.post(f"{url}/api/chat", json={"model": model, "messages": messages,
                                                           "tools": TOOL_SPECS, "stream": False,
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
                err = validate_call(name, args)
                if err:
                    result = {"error": err}
                else:
                    result = await asyncio.to_thread(_dispatch, session, name, args)
                calls.append({"name": name, "args": args, "ok": err is None})
                messages.append({"role": "tool", "name": name, "content": json.dumps(result, default=str)})
        if not any(c["ok"] for c in calls):
            return {"challenge": None, "tool_calls": calls, "tokens": tokens,
                    "error": "challenger made no valid tool call"}
        messages.append({"role": "user", "content": "Give your conclusion now as JSON only."})
        r = await client.post(f"{url}/api/chat", json={"model": model, "messages": messages, "stream": False,
                                                       "format": CHALLENGE_SCHEMA, "options": {"temperature": 0}})
        r.raise_for_status()
        body = r.json()
        tokens += body.get("eval_count", 0)
        challenge = Challenge.model_validate(json.loads(body["message"]["content"]))
        return {"challenge": challenge.model_dump(), "tool_calls": calls, "tokens": tokens, "error": None}
    except (json.JSONDecodeError, ValidationError) as e:
        return {"challenge": None, "tool_calls": calls, "tokens": tokens,
                "error": f"invalid challenger output: {type(e).__name__}"}
    except Exception as e:
        return {"challenge": None, "tool_calls": calls, "tokens": tokens,
                "error": f"{type(e).__name__}: {str(e)[:200]}"}
    finally:
        if own:
            await client.aclose()

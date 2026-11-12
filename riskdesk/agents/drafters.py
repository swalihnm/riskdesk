"""Drafters turn engine facts into a note. They never introduce numbers: the grounding check runs afterwards.

Output contract: every drafter returns {"text": str, "tokens": int}. Local-model output is constrained to
NOTE_SCHEMA by Ollama and validated with DraftNote before use.

- TemplateDrafter: deterministic, used in CI and tests. Its numbers come straight from the facts.
- OllamaDrafter: a local model through Ollama (free), constrained to JSON. Falls back to the template on failure.
"""

from __future__ import annotations

import json
import os
import time

import httpx
from pydantic import BaseModel, Field, ValidationError

from riskdesk.config import OLLAMA_MODEL, OLLAMA_URL, PROMPTS_DIR

NOTE_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string", "maxLength": 700}},
    "required": ["summary"],
}


class DraftNote(BaseModel):
    summary: str = Field(min_length=20, max_length=700)


def load_prompt(name: str = "breach_report") -> dict:
    import yaml
    with open(os.path.join(PROMPTS_DIR, f"{name}.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_note(raw: str) -> str:
    """Validate a model's JSON output against the note schema. Raises ValueError if it does not conform."""
    try:
        return DraftNote.model_validate(json.loads(raw)).summary
    except (json.JSONDecodeError, ValidationError) as e:
        raise ValueError(f"model output is not a valid note: {e}") from e


class TemplateDrafter:
    name = "template"

    def draft(self, facts: dict, citations: list[str], prompt: dict) -> dict:
        f = facts
        share = f"{f['top_share']:.0%}" if f.get("top_share") is not None else "n/a"
        text = (
            f"Desk {f['desk']} {f['metric_label']} is {f['value']:,.0f} against a hard limit of "
            f"{f['limit']:,.0f}, which is {f['utilisation']:.0%} utilisation (status {f['status']}). "
            f"Classification: {f['classification']}. "
            f"Largest component driver: {f['top_driver'] or 'none'}, contributing {share} of the total. "
            f"Escalated: {'yes' if f['escalate'] else 'no'}. "
            f"Policy reference: {', '.join(citations) if citations else 'none'}."
        )
        return {"text": text, "tokens": 0}


class OllamaDrafter:
    name = "ollama"

    def __init__(self, model: str = OLLAMA_MODEL, url: str = OLLAMA_URL, timeout: float = 120.0):
        self.model, self.url, self.timeout = model, url, timeout

    def _messages(self, facts: dict, citations: list[str], prompt: dict) -> list[dict]:
        examples = []
        for ex in prompt.get("examples", []):
            examples.append({"role": "user", "content": prompt["template"].format(
                facts=json.dumps(ex["facts"]), citations=json.dumps(ex["citations"]))})
            examples.append({"role": "assistant", "content": json.dumps(ex["output"])})
        user = prompt["template"].format(facts=json.dumps(facts, default=str), citations=json.dumps(citations))
        return [{"role": "system", "content": prompt.get("system", "")}, *examples,
                {"role": "user", "content": user}]

    def draft(self, facts: dict, citations: list[str], prompt: dict) -> dict:
        body = {"model": self.model, "messages": self._messages(facts, citations, prompt), "stream": False,
                "format": NOTE_SCHEMA, "options": {"temperature": 0}}
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(f"{self.url}/api/chat", json=body)
            r.raise_for_status()
            out = r.json()
        text = parse_note(out["message"]["content"])
        return {"text": text, "tokens": out.get("eval_count", 0)}


def get_drafter(kind: str | None = None):
    kind = kind or os.environ.get("RISKDESK_DRAFTER", "template")
    if kind in ("ollama", "tools"):
        return OllamaDrafter()
    return TemplateDrafter()


def timed(fn, *args):
    t = time.perf_counter()
    out = fn(*args)
    out["latency_ms"] = (time.perf_counter() - t) * 1000
    return out

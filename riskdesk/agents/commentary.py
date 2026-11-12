"""Second workflow (week 9): daily VaR commentary.

Compares each desk's one-day 99% VaR today with yesterday (the window shifted one day), drafts a short
commentary from those numbers, runs the same grounding and PII checks, and queues it for approval.
It never changes a limit or a position.
"""

from __future__ import annotations

import os
import uuid

import numpy as np

from riskdesk import audit
from riskdesk.agents.drafters import TemplateDrafter, get_drafter, load_prompt
from riskdesk.config import APPROVAL_PATH
from riskdesk.engine.book import DESKS, positions_by_desk
from riskdesk.engine.risk import portfolio_pnl, var_from_pnl, WINDOW
from riskdesk.guardrails import approval
from riskdesk.guardrails.grounding import check_grounding
from riskdesk.guardrails.pii import redact
from riskdesk.tools import Session


def _var_window(session: Session, desk: str, end: int) -> float:
    """VaR using the WINDOW days ending at index `end` (exclusive)."""
    ps = positions_by_desk(session.book, desk)
    m = session.market
    rets = m.rets[end - WINDOW:end]
    dvol = m.dvol[end - WINDOW:end]
    return var_from_pnl(portfolio_pnl(ps, m, rets, dvol))


def daily_commentary(session: Session, drafter_kind: str | None = None,
                     approval_path: str = APPROVAL_PATH) -> list[dict]:
    today_end = len(session.market.rets)
    out = []
    for desk in DESKS:
        today = _var_window(session, desk, today_end)
        yesterday = _var_window(session, desk, today_end - 1)
        change = today - yesterday
        change_pct = change / yesterday if yesterday else 0.0
        limit = session.limits[desk]["limits"]["var99"]
        facts = {"desk": desk, "var_today": today, "var_yesterday": yesterday, "change": change,
                 "change_pct": change_pct, "limit": limit, "utilisation": today / limit}
        drafter = get_drafter(drafter_kind)
        prompt = load_prompt("var_commentary")
        text = (f"{desk} one-day 99% VaR is {today:,.0f}, against {yesterday:,.0f} yesterday, "
                f"a change of {change:+,.0f} ({change_pct:+.1%}). The hard limit is {limit:,.0f}, "
                f"so utilisation is {facts['utilisation']:.0%}.")
        try:
            res = drafter.draft({**facts, "task": "daily_commentary"}, [], prompt)
            text = res["text"]
            used = drafter.name
        except Exception:
            used = "template_fallback"
        clean = redact(text)
        g = check_grounding(clean["text"], [facts])
        status = "queued" if g["ok"] else "blocked"
        if g["ok"]:
            approval.submit(approval_path, "daily_commentary", desk,
                            {"text": clean["text"], "facts": facts, "prompt_version": prompt["version"],
                             "drafter": used})
        audit.append("commentary.generated", {"desk": desk, "status": status, "drafter": used,
                                             "unsupported": g["unsupported"]})
        out.append({"desk": desk, "status": status, "text": clean["text"], "drafter": used,
                    "unsupported": g["unsupported"], "run_id": uuid.uuid4().hex[:8]})
    return out

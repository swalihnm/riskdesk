"""riskdesk-mcp: the risk engine exposed as MCP tools.

Every tool reads from the engine through riskdesk/tools.py, returns typed numbers, and writes an audit entry.
Run as a stdio server:  python -m riskdesk.mcp.server
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from riskdesk import tools as T
from riskdesk.engine.book import DESKS

mcp = FastMCP("riskdesk-mcp")
_SESSION: T.Session | None = None


def session() -> T.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = T.Session.base()
    return _SESSION


def set_session(s: T.Session) -> None:
    """Point the server at another market state (used by tests and the golden-set runner)."""
    global _SESSION
    _SESSION = s


@mcp.tool()
def list_desks() -> list[str]:
    """Trading desks in the synthetic book."""
    return DESKS


@mcp.tool()
def limit_status() -> list[dict]:
    """Utilisation and status (OK, WARNING, BREACH) for every desk and limit."""
    return T.limit_status(session())


@mcp.tool()
def compute_var(desk: str, method: str = "historical") -> dict:
    """One-day 99% VaR for a desk. method: historical, parametric or monte_carlo."""
    return T.compute_var(session(), desk, method)


@mcp.tool()
def compute_es(desk: str) -> dict:
    """One-day 97.5% Expected Shortfall (historical) for a desk."""
    return T.compute_es(session(), desk)


@mcp.tool()
def attribution(desk: str) -> dict:
    """Euler component VaR by underlying for a desk, with the top-two margin."""
    return T.attribution(session(), desk)


@mcp.tool()
def stress_test(desk: str) -> dict:
    """Worst stress loss for a desk across named and historical scenarios, both directions."""
    return T.stress(session(), desk)


@mcp.tool()
def data_checks(desk: str) -> dict:
    """Jump checks and quality flags for the underlyings a desk holds."""
    return T.data_checks(session(), desk)


@mcp.tool()
def backtest(desk: str = "") -> dict:
    """250-day 99% VaR backtest with Kupiec test and Basel traffic light. Empty desk means the whole book."""
    return T.backtest(session(), desk or None)


@mcp.tool()
def search_policy(query: str, k: int = 5) -> list[dict]:
    """Hybrid search over policy and regulatory text. Returns IDs, headings and passages."""
    return T.search_policy(session(), query, k)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

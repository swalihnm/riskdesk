"""P&L attribution test: zone thresholds from MAR32.42 Table 2, and a cash-only control book."""

import pytest

from riskdesk.config import CACHE_PATH
from riskdesk.engine.book import build_book, positions_by_desk
from riskdesk.engine.market import load_market
from riskdesk.engine.pla import pla_test, pla_zone


@pytest.mark.parametrize("corr, ks, zone", [
    (0.95, 0.01, "green"),
    (0.85, 0.08, "green"),
    (0.75, 0.05, "amber"),   # correlation between 0.70 and 0.80
    (0.95, 0.10, "amber"),   # KS between 0.09 and 0.12
    (0.65, 0.01, "red"),     # correlation below 0.70
    (0.95, 0.20, "red"),     # KS above 0.12
])
def test_zone_thresholds(corr, ks, zone):
    assert pla_zone(corr, ks) == zone


@pytest.fixture(scope="module")
def market():
    return load_market(CACHE_PATH)


def test_cash_only_book_is_green(market):
    cash = [p for p in build_book(market) if p.kind == "cash"]
    r = pla_test(cash, market)
    assert r["zone"] == "green"
    assert r["spearman"] > 0.999


def test_every_desk_gets_a_zone(market):
    book = build_book(market)
    for desk in ["DESK_EQ", "DESK_VOL", "DESK_FX"]:
        assert pla_test(positions_by_desk(book, desk), market)["zone"] in ("green", "amber", "red")

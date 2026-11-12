"""Fetch the real market data and rates, and store them with provenance in data/real/.

Run:  python scripts/fetch_real_data.py
Needs internet access. The committed copy in data/real/ lets the project run offline.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from riskdesk.engine import realdata  # noqa: E402


def main() -> None:
    prices, provenance = realdata.fetch()
    realdata.save(prices, provenance)
    print(f"saved {len(prices)} rows ({prices.index[0].date()} to {prices.index[-1].date()}) to {realdata.REAL_DIR}")
    print(f"rd={provenance['rd']:.4f} ({provenance['rd_date']}); rf={provenance['rf']}")


if __name__ == "__main__":
    main()

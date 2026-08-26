from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _table_rows(path: Path, table: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if exists is None:
            return []
        rows = connection.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
    return [{key: row[key] for key in row.keys()} for row in rows]


def build_diagnostic_export(data_dir: str | Path, starting_cash: float) -> bytes:
    root = Path(data_dir)
    paper_orders = _table_rows(root / "paper.sqlite3", "paper_orders")
    positions = _table_rows(root / "paper.sqlite3", "positions")
    account = _table_rows(root / "paper.sqlite3", "account")
    theses = _table_rows(root / "theses.sqlite3", "theses")
    audit_events = _table_rows(root / "operations.sqlite3", "audit_events")
    snapshots = _table_rows(root / "dashboard.sqlite3", "portfolio_snapshots")

    losses = []
    for order in paper_orders:
        realized = float(order.get("realized_pnl") or 0.0)
        if realized < 0:
            symbol = str(order.get("symbol") or "")
            related = [item for item in theses if str(item.get("symbol") or "") == symbol]
            losses.append(
                {
                    "order": order,
                    "related_theses": related,
                    "diagnostic_note": (
                        "Realized loss. Inspect related thesis, evidence IDs, exit reason, "
                        "market context and audit events around this trade."
                    ),
                }
            )

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "starting_cash": starting_cash,
        "account": account,
        "positions": positions,
        "orders": paper_orders,
        "realized_losses": losses,
        "theses": theses,
        "audit_events": audit_events,
        "portfolio_snapshots": snapshots,
        "security": {
            "credentials_included": False,
            "zerodha_session_included": False,
            "note": "Broker secrets and access tokens are intentionally excluded.",
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True, default=str).encode("utf-8")

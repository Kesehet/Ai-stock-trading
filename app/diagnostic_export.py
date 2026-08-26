from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _query_rows(path: Path, query: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(query).fetchall()
        except sqlite3.OperationalError:
            return []
    return [{key: row[key] for key in row.keys()} for row in rows]


def build_diagnostic_export(data_dir: str | Path, starting_cash: float) -> bytes:
    root = Path(data_dir)
    paper_orders = _query_rows(root / "paper.sqlite3", "SELECT * FROM paper_orders")
    positions = _query_rows(root / "paper.sqlite3", "SELECT * FROM positions")
    account = _query_rows(root / "paper.sqlite3", "SELECT * FROM account")
    theses = _query_rows(root / "theses.sqlite3", "SELECT * FROM theses")
    audit_events = _query_rows(
        root / "operations.sqlite3",
        "SELECT * FROM audit_events ORDER BY id",
    )
    snapshots = _query_rows(
        root / "dashboard.sqlite3",
        "SELECT * FROM portfolio_snapshots ORDER BY captured_at",
    )

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
            "ollama_api_key_included": False,
            "note": (
                "Broker credentials, Zerodha session tokens and Ollama API keys "
                "are intentionally excluded."
            ),
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True, default=str).encode("utf-8")

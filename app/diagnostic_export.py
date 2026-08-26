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


def _json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _live_realized_losses(
    live_orders: list[dict[str, Any]],
    theses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    books: dict[tuple[str, str], tuple[int, float]] = {}
    losses: list[dict[str, Any]] = []
    for order in live_orders:
        if str(order.get("status") or "") != "COMPLETE":
            continue
        quantity = int(order.get("filled_quantity") or 0)
        price = float(order.get("average_price") or 0.0)
        if quantity <= 0 or price <= 0:
            continue
        symbol = str(order.get("symbol") or "")
        product = str(order.get("product") or "")
        side = str(order.get("side") or "")
        key = (symbol, product)
        current_qty, current_avg = books.get(key, (0, price))
        if side == "BUY":
            new_qty = current_qty + quantity
            new_avg = ((current_qty * current_avg) + (quantity * price)) / new_qty
            books[key] = (new_qty, new_avg)
            continue
        sold = min(current_qty, quantity)
        realized = (price - current_avg) * sold
        remaining = max(0, current_qty - sold)
        if remaining:
            books[key] = (remaining, current_avg)
        else:
            books.pop(key, None)
        if realized < 0:
            related = [item for item in theses if str(item.get("symbol") or "") == symbol]
            losses.append(
                {
                    "order": order,
                    "estimated_realized_pnl_before_broker_charges": realized,
                    "related_theses": related,
                    "diagnostic_note": (
                        "Live realized loss reconstructed from bot-managed fills. "
                        "Broker statutory charges may make the final loss slightly larger."
                    ),
                }
            )
    return losses


def build_diagnostic_export(data_dir: str | Path, starting_cash: float) -> bytes:
    root = Path(data_dir)
    paper_orders = _query_rows(root / "paper.sqlite3", "SELECT * FROM paper_orders")
    paper_positions = _query_rows(root / "paper.sqlite3", "SELECT * FROM positions")
    paper_account = _query_rows(root / "paper.sqlite3", "SELECT * FROM account")
    live_orders = _query_rows(root / "live-orders.sqlite3", "SELECT * FROM live_orders")
    theses = _query_rows(root / "theses.sqlite3", "SELECT * FROM theses")
    audit_events = _query_rows(
        root / "operations.sqlite3",
        "SELECT * FROM audit_events ORDER BY id",
    )
    snapshots = _query_rows(
        root / "dashboard.sqlite3",
        "SELECT * FROM portfolio_snapshots ORDER BY captured_at",
    )

    paper_losses = []
    for order in paper_orders:
        realized = float(order.get("realized_pnl") or 0.0)
        if realized < 0:
            symbol = str(order.get("symbol") or "")
            related = [item for item in theses if str(item.get("symbol") or "") == symbol]
            paper_losses.append(
                {
                    "order": order,
                    "related_theses": related,
                    "diagnostic_note": (
                        "Paper realized loss including configured simulated charges/slippage. "
                        "Inspect the thesis, evidence IDs and nearby audit events."
                    ),
                }
            )

    live_losses = _live_realized_losses(live_orders, theses)
    payload = {
        "schema_version": 2,
        "generated_at": datetime.now(UTC).isoformat(),
        "starting_cash": starting_cash,
        "runtime_mode": _json_file(root / "runtime-mode.json").get("mode", "paper"),
        "runtime_state": _json_file(root / "runtime-state.json"),
        # Backward-compatible paper aliases used by earlier analysis/tests.
        "account": paper_account,
        "positions": paper_positions,
        "orders": paper_orders,
        "realized_losses": paper_losses,
        "paper": {
            "account": paper_account,
            "positions": paper_positions,
            "orders": paper_orders,
            "realized_losses": paper_losses,
        },
        "live": {
            "bot_managed_orders": live_orders,
            "realized_losses": live_losses,
            "note": (
                "Only orders initiated by this system are included; "
                "unrelated broker holdings are excluded."
            ),
        },
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

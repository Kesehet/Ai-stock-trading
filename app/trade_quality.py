from __future__ import annotations

from datetime import datetime
from typing import Any


def _as_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _setup_tag(point: dict[str, Any] | None) -> str:
    if point is None:
        return "unknown"
    try:
        move = float(point.get("move_pct") or 0.0)
        breakout = float(point.get("breakout_pct") or 0.0)
        volume = float(point.get("volume_pace") or 0.0)
        position = float(point.get("intraday_position") or 0.5)
    except (TypeError, ValueError):
        return "unknown"

    if (move >= 0.10 and position >= 0.85) or (
        breakout >= 0.06 and position >= 0.90
    ):
        return "extended_momentum"
    if move >= 0.04 and position <= 0.65 and volume >= 1.2:
        return "pullback_momentum"
    if breakout >= 0.02 and volume >= 1.5 and 0.55 <= position <= 0.90:
        return "breakout_confirmation"
    if move >= 0.02 and volume >= 1.0:
        return "balanced_momentum"
    return "neutral"


def _current_cycle_start(
    orders: list[dict[str, Any]],
    symbol: str,
    product: str,
) -> datetime | None:
    relevant = [
        item
        for item in orders
        if str(item.get("symbol") or "").upper() == symbol
        and str(item.get("product") or "") == product
        and str(item.get("status") or "").upper() == "FILLED"
    ]
    relevant.sort(key=lambda item: int(item.get("order_id") or 0))
    running_quantity = 0
    cycle_start: datetime | None = None
    latest_buy: datetime | None = None
    for item in relevant:
        try:
            quantity = int(item.get("filled_quantity") or item.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
        side = str(item.get("side") or "").upper()
        executed_at = _as_datetime(item.get("executed_at"))
        if side == "BUY":
            if running_quantity <= 0:
                cycle_start = executed_at
            running_quantity += quantity
            latest_buy = executed_at or latest_buy
        elif side == "SELL":
            running_quantity = max(0, running_quantity - quantity)
            if running_quantity == 0:
                cycle_start = None
                latest_buy = None
    return latest_buy or cycle_start


def _nearest_entry_point(
    points: list[dict[str, Any]], entry_at: datetime | None
) -> dict[str, Any] | None:
    if not points:
        return None
    parsed = [
        (stamp, point)
        for point in points
        if (stamp := _as_datetime(point.get("at"))) is not None
    ]
    if not parsed:
        return None
    parsed.sort(key=lambda item: item[0])
    if entry_at is None:
        return parsed[0][1]
    before = [item for item in parsed if item[0] <= entry_at]
    if before:
        candidate = before[-1]
        if abs((entry_at - candidate[0]).total_seconds()) <= 300:
            return candidate[1]
    after = [item for item in parsed if item[0] > entry_at]
    if after and abs((after[0][0] - entry_at).total_seconds()) <= 300:
        return after[0][1]
    return None


def build_trade_quality(
    broker_state: dict[str, Any],
    scanner_state: object | None,
) -> dict[str, Any]:
    positions = broker_state.get("positions")
    orders = broker_state.get("orders")
    if not isinstance(positions, list):
        positions = []
    if not isinstance(orders, list):
        orders = []

    history: dict[str, list[dict[str, Any]]] = {}
    if isinstance(scanner_state, dict):
        raw_history = scanner_state.get("opportunity_history")
        if isinstance(raw_history, dict):
            for raw_symbol, raw_points in raw_history.items():
                if not isinstance(raw_symbol, str) or not isinstance(raw_points, list):
                    continue
                history[raw_symbol.upper()] = [
                    point for point in raw_points if isinstance(point, dict)
                ]

    rows: list[dict[str, Any]] = []
    for position in positions:
        if not isinstance(position, dict):
            continue
        symbol = str(position.get("symbol") or "").upper()
        product = str(position.get("product") or "")
        try:
            quantity = int(position.get("quantity") or 0)
            average_price = float(position.get("average_price") or 0.0)
        except (TypeError, ValueError):
            continue
        if not symbol or quantity <= 0 or average_price <= 0:
            continue

        entry_at = _current_cycle_start(orders, symbol, product)
        points = history.get(symbol, [])
        parsed_points = [
            (stamp, point)
            for point in points
            if (stamp := _as_datetime(point.get("at"))) is not None
        ]
        parsed_points.sort(key=lambda item: item[0])
        post_entry = [
            point
            for stamp, point in parsed_points
            if entry_at is None or stamp >= entry_at
        ]
        entry_point = _nearest_entry_point(points, entry_at)
        prices: list[float] = []
        for point in post_entry:
            price = _as_float(point.get("price"))
            if price is not None and price > 0:
                prices.append(price)

        current_price = prices[-1] if prices else None
        high_price = max(prices) if prices else None
        low_price = min(prices) if prices else None
        current_return = (
            (current_price / average_price) - 1.0
            if current_price is not None
            else None
        )
        mfe = (high_price / average_price) - 1.0 if high_price is not None else None
        mae = (low_price / average_price) - 1.0 if low_price is not None else None
        giveback = (
            max(0.0, mfe - current_return)
            if mfe is not None and current_return is not None
            else None
        )

        entry_score = _as_float(entry_point.get("score")) if entry_point else None
        entry_move = _as_float(entry_point.get("move_pct")) if entry_point else None
        entry_breakout = (
            _as_float(entry_point.get("breakout_pct")) if entry_point else None
        )
        entry_position = (
            _as_float(entry_point.get("intraday_position")) if entry_point else None
        )
        entry_volume = (
            _as_float(entry_point.get("volume_pace")) if entry_point else None
        )

        rows.append(
            {
                "symbol": symbol,
                "product": product,
                "quantity": quantity,
                "average_price": round(average_price, 4),
                "tracking_from": entry_at.isoformat() if entry_at is not None else None,
                "observations": len(prices),
                "entry_setup": _setup_tag(entry_point),
                "entry_score": round(entry_score, 5)
                if entry_score is not None
                else None,
                "entry_move_pct": round(entry_move * 100, 4)
                if entry_move is not None
                else None,
                "entry_breakout_pct": round(entry_breakout * 100, 4)
                if entry_breakout is not None
                else None,
                "entry_intraday_position": round(entry_position, 4)
                if entry_position is not None
                else None,
                "entry_volume_pace": round(entry_volume, 3)
                if entry_volume is not None
                else None,
                "current_return_pct": round(current_return * 100, 4)
                if current_return is not None
                else None,
                "mfe_pct": round(mfe * 100, 4) if mfe is not None else None,
                "mae_pct": round(mae * 100, 4) if mae is not None else None,
                "giveback_from_mfe_pct": round(giveback * 100, 4)
                if giveback is not None
                else None,
            }
        )

    measured = [row for row in rows if int(row["observations"]) > 0]
    immediate_adverse = [
        row
        for row in measured
        if isinstance(row.get("mae_pct"), (int, float))
        and float(row["mae_pct"]) <= -1.0
        and (
            not isinstance(row.get("mfe_pct"), (int, float))
            or float(row["mfe_pct"]) < 0.5
        )
    ]
    gave_back = [
        row
        for row in measured
        if isinstance(row.get("mfe_pct"), (int, float))
        and isinstance(row.get("giveback_from_mfe_pct"), (int, float))
        and float(row["mfe_pct"]) >= 1.0
        and float(row["giveback_from_mfe_pct"]) >= 1.0
    ]

    by_setup: dict[str, dict[str, float | int]] = {}
    for row in measured:
        setup = str(row.get("entry_setup") or "unknown")
        bucket = by_setup.setdefault(
            setup,
            {
                "count": 0,
                "avg_current_return_pct": 0.0,
                "avg_mfe_pct": 0.0,
                "avg_mae_pct": 0.0,
            },
        )
        count = int(bucket["count"])
        current = float(row.get("current_return_pct") or 0.0)
        mfe_value = float(row.get("mfe_pct") or 0.0)
        mae_value = float(row.get("mae_pct") or 0.0)
        new_count = count + 1
        bucket["count"] = new_count
        bucket["avg_current_return_pct"] = (
            float(bucket["avg_current_return_pct"]) * count + current
        ) / new_count
        bucket["avg_mfe_pct"] = (
            float(bucket["avg_mfe_pct"]) * count + mfe_value
        ) / new_count
        bucket["avg_mae_pct"] = (
            float(bucket["avg_mae_pct"]) * count + mae_value
        ) / new_count

    for bucket in by_setup.values():
        for field in ("avg_current_return_pct", "avg_mfe_pct", "avg_mae_pct"):
            bucket[field] = round(float(bucket[field]), 4)

    return {
        "positions": rows,
        "measured_positions": len(measured),
        "unmeasured_positions": len(rows) - len(measured),
        "immediate_adverse_entries": immediate_adverse,
        "gave_back_winners": gave_back,
        "by_entry_setup": by_setup,
    }

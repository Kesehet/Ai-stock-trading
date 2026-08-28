from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock

from app.models import Position, Product, Quote


@dataclass
class PositionExcursion:
    symbol: str
    product: str
    quantity: int
    average_price: float
    started_at: str
    updated_at: str
    first_mark: float
    current_mark: float
    high_mark: float
    low_mark: float
    mfe_pct: float
    mae_pct: float
    current_return_pct: float
    entry_setup: str = "unknown"
    entry_score: float | None = None
    entry_move_pct: float | None = None
    entry_breakout_pct: float | None = None
    entry_intraday_position: float | None = None
    entry_volume_pace: float | None = None


class TradeExcursionStore:
    """Persist broker-neutral position MAE/MFE and entry-quality metadata."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    @staticmethod
    def _key(symbol: str, product: Product | str) -> str:
        value = product.value if isinstance(product, Product) else str(product)
        return f"{symbol.upper()}::{value}"

    def _load(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}
        try:
            parsed = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _save(self, rows: dict[str, dict[str, object]]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def _metrics(average_price: float, high: float, low: float, current: float) -> tuple[float, float, float]:
        if average_price <= 0:
            return 0.0, 0.0, 0.0
        return (
            (high / average_price) - 1.0,
            (low / average_price) - 1.0,
            (current / average_price) - 1.0,
        )

    def observe(
        self,
        positions: list[Position],
        quotes: dict[str, Quote],
        now: datetime,
    ) -> None:
        with self._lock:
            rows = self._load()
            active_keys: set[str] = set()
            for position in positions:
                quote = quotes.get(position.symbol)
                if quote is None or quote.last_price <= 0:
                    continue
                key = self._key(position.symbol, position.product)
                active_keys.add(key)
                mark = float(quote.last_price)
                existing = rows.get(key)
                basis_changed = (
                    existing is None
                    or int(existing.get("quantity", 0)) != position.quantity
                    or abs(float(existing.get("average_price", 0.0)) - position.average_price) > 1e-9
                )
                if basis_changed:
                    started_at = now.isoformat()
                    first_mark = mark
                    high_mark = mark
                    low_mark = mark
                    setup = str(existing.get("entry_setup", "unknown")) if existing else "unknown"
                    entry_score = existing.get("entry_score") if existing else None
                    entry_move_pct = existing.get("entry_move_pct") if existing else None
                    entry_breakout_pct = existing.get("entry_breakout_pct") if existing else None
                    entry_intraday_position = existing.get("entry_intraday_position") if existing else None
                    entry_volume_pace = existing.get("entry_volume_pace") if existing else None
                else:
                    started_at = str(existing.get("started_at") or now.isoformat())
                    first_mark = float(existing.get("first_mark", mark))
                    high_mark = max(float(existing.get("high_mark", mark)), mark)
                    low_mark = min(float(existing.get("low_mark", mark)), mark)
                    setup = str(existing.get("entry_setup", "unknown"))
                    entry_score = existing.get("entry_score")
                    entry_move_pct = existing.get("entry_move_pct")
                    entry_breakout_pct = existing.get("entry_breakout_pct")
                    entry_intraday_position = existing.get("entry_intraday_position")
                    entry_volume_pace = existing.get("entry_volume_pace")
                mfe, mae, current_return = self._metrics(
                    position.average_price,
                    high_mark,
                    low_mark,
                    mark,
                )
                row = PositionExcursion(
                    symbol=position.symbol.upper(),
                    product=position.product.value,
                    quantity=position.quantity,
                    average_price=position.average_price,
                    started_at=started_at,
                    updated_at=now.isoformat(),
                    first_mark=first_mark,
                    current_mark=mark,
                    high_mark=high_mark,
                    low_mark=low_mark,
                    mfe_pct=mfe,
                    mae_pct=mae,
                    current_return_pct=current_return,
                    entry_setup=setup,
                    entry_score=float(entry_score) if entry_score is not None else None,
                    entry_move_pct=float(entry_move_pct) if entry_move_pct is not None else None,
                    entry_breakout_pct=float(entry_breakout_pct) if entry_breakout_pct is not None else None,
                    entry_intraday_position=(
                        float(entry_intraday_position)
                        if entry_intraday_position is not None
                        else None
                    ),
                    entry_volume_pace=(
                        float(entry_volume_pace) if entry_volume_pace is not None else None
                    ),
                )
                rows[key] = asdict(row)

            for key in list(rows):
                if key not in active_keys:
                    rows.pop(key, None)
            self._save(rows)

    def annotate_entry(
        self,
        *,
        symbol: str,
        product: Product,
        setup: str,
        score: float | None,
        move_pct: float | None,
        breakout_pct: float | None,
        intraday_position: float | None,
        volume_pace: float | None,
    ) -> None:
        key = self._key(symbol, product)
        with self._lock:
            rows = self._load()
            row = rows.get(key)
            if row is None:
                return
            row.update(
                {
                    "entry_setup": setup,
                    "entry_score": score,
                    "entry_move_pct": move_pct,
                    "entry_breakout_pct": breakout_pct,
                    "entry_intraday_position": intraday_position,
                    "entry_volume_pace": volume_pace,
                }
            )
            rows[key] = row
            self._save(rows)

    def snapshot(self) -> list[dict[str, object]]:
        with self._lock:
            rows = self._load()
        return [rows[key] for key in sorted(rows)]

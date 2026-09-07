from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date, datetime, time
from pathlib import Path

from app.config import Settings
from app.microstructure_replay import MicrostructureReplay, ReplayConfig, StrategyScore
from app.microstructure_store import IST, MicrostructureEventStore


def build_report(
    settings: Settings,
    *,
    session_date: date,
    max_events: int = 1_000_000,
) -> dict[str, object]:
    data_dir = Path(settings.data_dir)
    event_path = data_dir / "microstructure-events.sqlite3"
    start = datetime.combine(session_date, time(9, 15), tzinfo=IST)
    end = datetime.combine(session_date, time(15, 30), tzinfo=IST)

    if not event_path.exists():
        return {
            "generated_at": datetime.now(IST).isoformat(),
            "session_date": session_date.isoformat(),
            "starting_nav": settings.starting_cash,
            "events": 0,
            "symbols": 0,
            "scores": [],
            "best": None,
            "status": "no_data",
        }

    with MicrostructureEventStore(event_path) as store:
        ticks = list(store.iter_ticks(start_at=start, end_at=end, limit=max_events))

    replay = MicrostructureReplay(
        ReplayConfig(
            starting_nav=settings.starting_cash,
            max_position_pct=settings.max_position_pct,
            slippage_bps_each_way=settings.paper_slippage_bps,
        )
    )
    result = replay.run(ticks)
    scores = [_score_payload(score) for score in result.scores]
    best = next((score for score in result.scores if score.trades > 0), None)
    unique_symbols = len({tick.symbol for tick in ticks})
    return {
        "generated_at": datetime.now(IST).isoformat(),
        "session_date": session_date.isoformat(),
        "starting_nav": settings.starting_cash,
        "position_cap_pct": settings.max_position_pct,
        "slippage_bps_each_way": settings.paper_slippage_bps,
        "events": len(ticks),
        "symbols": unique_symbols,
        "fitted_models": result.fitted_models,
        "scores": scores,
        "best": _score_payload(best) if best is not None else None,
        "status": "scored" if best is not None else "no_executable_trades",
        "warning": (
            "Best observed score is an out-of-sample replay result, not proof of a future edge. "
            "No strategy receives live authority from this report."
        ),
    }


def _score_payload(score: StrategyScore) -> dict[str, object]:
    payload = asdict(score)
    for key in (
        "hit_rate",
        "gross_pnl",
        "costs",
        "net_pnl",
        "net_expectancy",
        "profit_factor",
        "max_drawdown",
        "starting_nav",
        "ending_nav",
    ):
        payload[key] = round(float(payload[key]), 4)
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay recorded NSE depth events in shadow mode")
    parser.add_argument("--date", help="IST session date YYYY-MM-DD; defaults to today")
    parser.add_argument("--max-events", type=int, default=1_000_000)
    parser.add_argument("--output", help="Optional JSON output path")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    session_date = date.fromisoformat(args.date) if args.date else datetime.now(IST).date()
    report = build_report(Settings(), session_date=session_date, max_events=args.max_events)
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()

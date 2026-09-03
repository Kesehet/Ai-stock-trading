from app.trade_quality import build_trade_quality


def test_trade_quality_reconstructs_entry_and_excursions() -> None:
    broker = {
        "positions": [
            {
                "symbol": "ABC",
                "product": "DELIVERY",
                "quantity": 10,
                "average_price": 100.0,
            }
        ],
        "orders": [
            {
                "order_id": 1,
                "symbol": "ABC",
                "side": "BUY",
                "product": "DELIVERY",
                "quantity": 10,
                "filled_quantity": 10,
                "status": "FILLED",
                "executed_at": "2026-08-28T10:00:00+05:30",
            }
        ],
    }
    scanner = {
        "opportunity_history": {
            "ABC": [
                {
                    "at": "2026-08-28T09:59:00+05:30",
                    "price": 100.0,
                    "score": 0.18,
                    "move_pct": 0.055,
                    "breakout_pct": 0.025,
                    "volume_pace": 2.1,
                    "intraday_position": 0.72,
                    "acceleration_pct": 0.004,
                },
                {
                    "at": "2026-08-28T10:01:00+05:30",
                    "price": 102.0,
                    "score": 0.19,
                    "move_pct": 0.06,
                    "breakout_pct": 0.03,
                    "volume_pace": 2.2,
                    "intraday_position": 0.78,
                    "acceleration_pct": 0.003,
                },
                {
                    "at": "2026-08-28T10:02:00+05:30",
                    "price": 97.0,
                    "score": 0.11,
                    "move_pct": 0.01,
                    "breakout_pct": -0.01,
                    "volume_pace": 2.3,
                    "intraday_position": 0.35,
                    "acceleration_pct": -0.02,
                },
                {
                    "at": "2026-08-28T10:03:00+05:30",
                    "price": 101.0,
                    "score": 0.15,
                    "move_pct": 0.04,
                    "breakout_pct": 0.01,
                    "volume_pace": 2.4,
                    "intraday_position": 0.6,
                    "acceleration_pct": 0.01,
                },
            ]
        }
    }

    result = build_trade_quality(broker, scanner)
    row = result["positions"][0]

    assert result["measured_positions"] == 1
    assert row["entry_setup"] == "breakout_confirmation"
    assert row["mfe_pct"] == 2.0
    assert row["mae_pct"] == -3.0
    assert row["current_return_pct"] == 1.0
    assert row["giveback_from_mfe_pct"] == 1.0


def test_trade_quality_flags_extended_immediate_adverse_entry() -> None:
    broker = {
        "positions": [
            {
                "symbol": "CHASE",
                "product": "DELIVERY",
                "quantity": 5,
                "average_price": 200.0,
            }
        ],
        "orders": [
            {
                "order_id": 7,
                "symbol": "CHASE",
                "side": "BUY",
                "product": "DELIVERY",
                "quantity": 5,
                "filled_quantity": 5,
                "status": "FILLED",
                "executed_at": "2026-08-28T11:00:00+05:30",
            }
        ],
    }
    scanner = {
        "opportunity_history": {
            "CHASE": [
                {
                    "at": "2026-08-28T10:59:30+05:30",
                    "price": 200.0,
                    "score": 0.2,
                    "move_pct": 0.13,
                    "breakout_pct": 0.07,
                    "volume_pace": 4.0,
                    "intraday_position": 0.94,
                    "acceleration_pct": 0.01,
                },
                {
                    "at": "2026-08-28T11:01:00+05:30",
                    "price": 198.0,
                    "score": 0.1,
                    "move_pct": 0.11,
                    "breakout_pct": 0.05,
                    "volume_pace": 4.1,
                    "intraday_position": 0.8,
                    "acceleration_pct": -0.01,
                },
                {
                    "at": "2026-08-28T11:02:00+05:30",
                    "price": 196.0,
                    "score": 0.05,
                    "move_pct": 0.08,
                    "breakout_pct": 0.02,
                    "volume_pace": 4.2,
                    "intraday_position": 0.6,
                    "acceleration_pct": -0.01,
                },
            ]
        }
    }

    result = build_trade_quality(broker, scanner)
    row = result["positions"][0]

    assert row["entry_setup"] == "extended_momentum"
    assert row["mfe_pct"] < 0.5
    assert row["mae_pct"] <= -1.0
    assert result["immediate_adverse_entries"][0]["symbol"] == "CHASE"


def test_trade_quality_add_on_buy_does_not_reset_open_cycle() -> None:
    broker = {
        "positions": [
            {
                "symbol": "AVERAGE",
                "product": "DELIVERY",
                "quantity": 12,
                "average_price": 96.0,
            }
        ],
        "orders": [
            {
                "order_id": 1,
                "symbol": "AVERAGE",
                "side": "BUY",
                "product": "DELIVERY",
                "quantity": 10,
                "filled_quantity": 10,
                "status": "FILLED",
                "executed_at": "2026-08-28T10:00:00+05:30",
            },
            {
                "order_id": 2,
                "symbol": "AVERAGE",
                "side": "BUY",
                "product": "DELIVERY",
                "quantity": 2,
                "filled_quantity": 2,
                "status": "FILLED",
                "executed_at": "2026-08-28T10:05:00+05:30",
            },
        ],
    }
    scanner = {
        "opportunity_history": {
            "AVERAGE": [
                {
                    "at": "2026-08-28T10:00:30+05:30",
                    "price": 100.0,
                    "score": 0.16,
                    "move_pct": 0.04,
                    "breakout_pct": 0.02,
                    "volume_pace": 2.0,
                    "intraday_position": 0.7,
                },
                {
                    "at": "2026-08-28T10:03:00+05:30",
                    "price": 90.0,
                    "score": 0.08,
                    "move_pct": -0.03,
                    "breakout_pct": -0.04,
                    "volume_pace": 2.2,
                    "intraday_position": 0.2,
                },
                {
                    "at": "2026-08-28T10:05:30+05:30",
                    "price": 92.0,
                    "score": 0.09,
                    "move_pct": -0.01,
                    "breakout_pct": -0.02,
                    "volume_pace": 2.1,
                    "intraday_position": 0.35,
                },
                {
                    "at": "2026-08-28T10:07:00+05:30",
                    "price": 97.0,
                    "score": 0.12,
                    "move_pct": 0.01,
                    "breakout_pct": 0.0,
                    "volume_pace": 1.8,
                    "intraday_position": 0.55,
                },
            ]
        }
    }

    result = build_trade_quality(broker, scanner)
    row = result["positions"][0]

    assert row["tracking_from"] == "2026-08-28T10:00:00+05:30"
    assert row["observations"] == 4
    assert row["mfe_pct"] == 4.1667
    assert row["mae_pct"] == -6.25
    assert row["current_return_pct"] == 1.0417


def test_trade_quality_uses_latest_scanner_mark_for_current_return_and_giveback() -> None:
    broker = {
        "positions": [
            {
                "symbol": "GIVEBACK",
                "product": "DELIVERY",
                "quantity": 10,
                "average_price": 100.0,
            }
        ],
        "orders": [
            {
                "order_id": 1,
                "symbol": "GIVEBACK",
                "side": "BUY",
                "product": "DELIVERY",
                "quantity": 10,
                "filled_quantity": 10,
                "status": "FILLED",
                "executed_at": "2026-08-28T10:00:00+05:30",
            }
        ],
    }
    scanner = {
        "updated_at": "2026-08-28T15:29:00+05:30",
        "previous_prices": {"GIVEBACK": 98.0},
        "opportunity_history": {
            "GIVEBACK": [
                {
                    "at": "2026-08-28T10:00:30+05:30",
                    "price": 100.0,
                    "score": 0.17,
                    "move_pct": 0.04,
                    "breakout_pct": 0.025,
                    "volume_pace": 2.0,
                    "intraday_position": 0.72,
                },
                {
                    "at": "2026-08-28T10:15:00+05:30",
                    "price": 104.0,
                    "score": 0.19,
                    "move_pct": 0.06,
                    "breakout_pct": 0.04,
                    "volume_pace": 2.3,
                    "intraday_position": 0.82,
                },
                {
                    "at": "2026-08-28T10:30:00+05:30",
                    "price": 103.0,
                    "score": 0.16,
                    "move_pct": 0.05,
                    "breakout_pct": 0.03,
                    "volume_pace": 2.1,
                    "intraday_position": 0.75,
                },
            ]
        },
    }

    result = build_trade_quality(broker, scanner)
    row = result["positions"][0]

    assert row["observations"] == 3
    assert row["current_price"] == 98.0
    assert row["current_price_source"] == "scanner_mark"
    assert row["mark_updated_at"] == "2026-08-28T15:29:00+05:30"
    assert row["current_return_pct"] == -2.0
    assert row["mfe_pct"] == 4.0
    assert row["mae_pct"] == -2.0
    assert row["giveback_from_mfe_pct"] == 6.0
    assert result["gave_back_winners"][0]["symbol"] == "GIVEBACK"


def test_trade_quality_preserves_closed_cycle_excursions_after_exit() -> None:
    broker = {
        "positions": [],
        "orders": [
            {
                "order_id": 1,
                "symbol": "CLOSED",
                "side": "BUY",
                "product": "DELIVERY",
                "quantity": 1,
                "filled_quantity": 1,
                "status": "FILLED",
                "price": 100.0,
                "executed_at": "2026-08-28T10:00:00+05:30",
                "realized_pnl": 0.0,
            },
            {
                "order_id": 2,
                "symbol": "CLOSED",
                "side": "SELL",
                "product": "DELIVERY",
                "quantity": 1,
                "filled_quantity": 1,
                "status": "FILLED",
                "price": 102.0,
                "executed_at": "2026-08-28T10:30:00+05:30",
                "realized_pnl": 1.85,
            },
        ],
    }
    scanner = {
        "opportunity_history": {
            "CLOSED": [
                {
                    "at": "2026-08-28T09:59:30+05:30",
                    "price": 100.0,
                    "score": 0.18,
                    "move_pct": 0.05,
                    "breakout_pct": 0.025,
                    "volume_pace": 2.0,
                    "intraday_position": 0.72,
                },
                {
                    "at": "2026-08-28T10:10:00+05:30",
                    "price": 106.0,
                    "score": 0.21,
                    "move_pct": 0.08,
                    "breakout_pct": 0.05,
                    "volume_pace": 3.0,
                    "intraday_position": 0.88,
                },
                {
                    "at": "2026-08-28T10:20:00+05:30",
                    "price": 98.0,
                    "score": 0.10,
                    "move_pct": 0.01,
                    "breakout_pct": -0.01,
                    "volume_pace": 2.4,
                    "intraday_position": 0.35,
                },
            ]
        }
    }

    result = build_trade_quality(broker, scanner)

    assert result["positions"] == []
    assert result["measured_positions"] == 0
    assert result["measured_closed_trades"] == 1
    row = result["recent_closed_trades"][0]
    assert row["symbol"] == "CLOSED"
    assert row["closed"] is True
    assert row["entry_setup"] == "breakout_confirmation"
    assert row["exit_price"] == 102.0
    assert row["mfe_pct"] == 6.0
    assert row["mae_pct"] == -2.0
    assert row["current_return_pct"] == 2.0
    assert row["giveback_from_mfe_pct"] == 4.0
    assert row["realized_pnl"] == 1.85
    assert result["closed_by_entry_setup"]["breakout_confirmation"]["count"] == 1

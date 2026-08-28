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

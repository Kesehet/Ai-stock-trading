from datetime import UTC, datetime

from app.microstructure_universe import discover_affordable_universe, parse_nse_equity_tokens
from app.zerodha_api import LiveMarketSnapshot


class FakeMarketData:
    headers: dict[str, str] = {}
    timeout_seconds = 1.0

    def __init__(self, prices: dict[str, tuple[float, float]]) -> None:
        self.prices = prices

    def market_snapshots(
        self,
        symbols: tuple[str, ...] | list[str],
    ) -> dict[str, LiveMarketSnapshot]:
        result: dict[str, LiveMarketSnapshot] = {}
        for symbol in symbols:
            price, volume = self.prices[symbol]
            result[symbol] = LiveMarketSnapshot(
                symbol=symbol,
                last_price=price,
                open_price=price,
                high_price=price,
                low_price=price,
                previous_close=price,
                volume=volume,
                as_of=datetime(2026, 9, 7, tzinfo=UTC),
            )
        return result


def test_parse_nse_equity_tokens_excludes_non_equity_rows() -> None:
    csv_text = "\n".join(
        [
            "instrument_token,tradingsymbol,exchange,segment,instrument_type",
            "101,AAA,NSE,NSE,EQ",
            "102,BBB,NSE,NSE,EQ",
            "103,NIFTY,NSE,NSE,INDEX",
            "104,CCC,BSE,BSE,EQ",
        ]
    )

    tokens = parse_nse_equity_tokens(csv_text)

    assert tokens == {"AAA": 101, "BBB": 102}


def test_universe_requires_whole_share_to_fit_position_cap_and_ranks_liquidity() -> None:
    api = FakeMarketData(
        {
            "AAA": (50.0, 1_000_000.0),
            "BBB": (240.0, 2_000_000.0),
            "CCC": (260.0, 5_000_000.0),
            "DDD": (10.0, 10_000_000.0),
        }
    )
    tokens = {"AAA": 101, "BBB": 102, "CCC": 103, "DDD": 104}

    universe = discover_affordable_universe(
        api,
        tokens,
        bankroll=500.0,
        max_position_pct=0.50,
        min_price=20.0,
        limit=10,
        batch_size=2,
    )

    assert [item.symbol for item in universe] == ["BBB", "AAA"]
    assert all(item.last_price <= 250.0 for item in universe)

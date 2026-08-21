from datetime import date

from app.nse_bhavcopy import NSEBhavcopySource, parse_udiff_csv


def test_udiff_parser_normalizes_equity_ohlcv() -> None:
    content = (
        "TradDt,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol\n"
        "2026-08-21,TCS,EQ,3100,3150,3090,3140,1234567\n"
        "2026-08-21,TCS,BE,3000,3010,2990,3005,100\n"
    )

    candles = parse_udiff_csv(content, date(2026, 8, 21))

    assert len(candles) == 1
    assert candles[0].symbol == "TCS"
    assert candles[0].close == 3140
    assert candles[0].volume == 1_234_567


def test_udiff_url_uses_yyyymmdd() -> None:
    source = NSEBhavcopySource()

    assert "20260821" in source.url_for(date(2026, 8, 21))

# Microstructure weekend build

## Objective

Build an event-driven, intraday-only research subsystem that predicts the next 1, 3 and 5 market-data events and rejects signals that cannot produce positive rupee expectancy with a ₹500 bankroll.

This subsystem starts in **shadow mode**. It must not enable live execution and must not bypass the existing shared deterministic risk boundary.

## Architecture

1. **Market-data recorder** — consume Zerodha Kite WebSocket `full` ticks, retaining top-five bid/ask price, quantity and order count plus LTP, last quantity, cumulative volume and timestamps.
2. **Feature engine** — level-1 queue imbalance, weighted five-level imbalance, microprice displacement, order-flow imbalance, trade/volume acceleration, spread and short realized volatility.
3. **Competing forecasters** — transparent baseline first (logistic/event-score); then empirical calibration, gradient boosting and LOB sequence models only after enough recorded NSE data exists.
4. **₹500 economics gate** — whole shares, available cash, max-position limit, bid/ask spread, intraday brokerage/taxes/fees and adverse slippage. A correct directional forecast that cannot clear costs is not a trade.
5. **Shadow execution/replay** — record every qualifying signal, hypothetical limit entry, target/stop, expiry event, fill assumptions, MFE/MAE, realized net result and model/version IDs.
6. **Promotion gate** — no model reaches paper/live execution merely because in-sample classification accuracy is high. Require out-of-sample positive net expectancy, sufficient sample size and drawdown controls.

## Weekend sequence

### Phase A — implemented on branch

`app/microstructure.py` adds pure event-level feature extraction, 1/3/5-event baseline forecasts and a ₹500-aware shadow opportunity gate. It cannot place orders.

### Phase B — next

Wire Kite `MODE_FULL` WebSocket ingestion into a dedicated recorder. Keep the existing slower scanner intact. Persist compact event rows in SQLite with bounded retention and symbol/token mapping loaded once, not looked up per tick.

### Phase C

Add labelled outcomes for +1/+2/+3/+5/+10 events, first-touch target/stop labels, MFE/MAE, spread and cost-adjusted P&L. Train/calibrate models from chronological splits only.

### Phase D

Add a dashboard panel comparing strategies by horizon: sample size, calibration, hit rate, gross expectancy, net expectancy, profit factor, MFE/MAE, drawdown and ₹500 executable count.

### Phase E

Monday runs shadow-first. Existing trading logic remains authoritative until the microstructure subsystem demonstrates positive out-of-sample post-cost expectancy. Any later paper/live integration must pass through the same shared risk/execution engine.

## Research basis

- Gould & Bonart: queue imbalance contains statistically significant information about the next mid-price movement, especially for large-tick stocks.
- Stoikov: microprice incorporates spread and imbalance and can improve short-term price estimation versus plain mid-price.
- DeepLOB: convolutional/recurrent models can extract short-horizon LOB structure, but model complexity is deferred until we have our own NSE event dataset.
- Indian evidence: order imbalance in active NSE stocks contains short-term return information.

## Important limitations

Kite Connect exposes top-five depth, not the complete NSE order book. A snapshot change does not uniquely identify whether quantity changed because of cancellation, modification or execution, so our `order_flow_imbalance` is an observable depth-change proxy, not true message-level exchange OFI. We must preserve that distinction in telemetry and research conclusions.

Retail API latency is not exchange-colocation latency. The target is therefore event horizons that survive network/API latency and costs, not microsecond HFT. We will measure signal-to-order latency before considering execution.

Retail algo/API rules and broker limits must be checked before any live deployment. The subsystem remains shadow-only until those operational requirements are satisfied.

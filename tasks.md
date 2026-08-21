# AI Stock Trading — Development Roadmap

> Goal: build an autonomous Indian-equity trading system where GPT-OSS via Ollama performs research and portfolio reasoning, while deterministic services enforce risk, validate orders, and execute trades through a broker API without requiring human approval per trade.
>
> **Core rule:** the LLM may propose trades, strategies, and portfolio actions, but it must never be able to bypass deterministic risk controls or directly issue unrestricted broker orders.

---

## 0. Research findings that shape the architecture

Before implementation, we reviewed several mature open-source approaches:

### TradingAgents
- Uses specialized agents for market/technical analysis, fundamentals, news and sentiment.
- Adds Bull vs Bear research debate before the trader acts.
- Uses separate aggressive, neutral and conservative risk agents plus a portfolio manager.
- Uses structured final decisions and maintains decision/report state.
- Supports local Ollama models.

**What we should borrow:** specialized research roles, opposing analysis, structured outputs, persistent decision logs.

**What we should change:** our final safety approval must be deterministic code, not another LLM agent.

### virattt/ai-hedge-fund
- Uses multiple investment/persona agents plus fundamentals, technical, sentiment and risk components.
- Has moved toward an always-on fund architecture with separate broker, portfolio, risk, backtesting, feature and pipeline modules.
- Treats strategies/alpha models as pluggable components.
- Includes backtesting and local Ollama support.

**What we should borrow:** modular alpha models, fund-level mandates, broker abstraction, separation between research/backtest/live infrastructure.

**What we should change:** we intend to support real Indian broker execution, so production-grade reconciliation, idempotency, circuit breakers and regulatory constraints are mandatory.

### FinRL / FinRL-Trading
- Separates data, trading environment, strategy/agent and application layers.
- Demonstrates technical indicators and machine-learning/RL strategies.
- Compares strategies with benchmarks and reports Sharpe, Sortino, drawdown and returns.
- FinRL-Trading demonstrates the full path from data acquisition to backtesting to paper/live broker execution.

**What we should borrow:** rigorous backtesting, benchmark comparison, transaction-cost modelling, strategy interfaces and paper/live parity.

### Design conclusion

The system should behave like an investment firm, not like a chatbot connected to a Buy button:

```text
Market + Fundamental + News Data
              |
              v
     Research / Analysis Agents
              |
       Bull/Bear Challenge
              |
              v
       GPT-OSS Fund Manager
              |
       Structured TradeIntent
              |
              v
   DETERMINISTIC RISK ENGINE
              |
       approve / reject
              |
              v
      Execution / Broker
              |
              v
 NSE/BSE + reconciliation loop
```

---

# Phase 1 — Repository foundation

- [ ] Create Python project structure and dependency management.
- [ ] Add Docker support.
- [ ] Add `.env.example`; never commit broker or data credentials.
- [ ] Add linting, formatting, typing and pytest.
- [ ] Add CI for tests and static checks.
- [ ] Add structured JSON logging.
- [ ] Add configuration profiles: `backtest`, `paper`, `live`.
- [ ] Add SQLite initially, with a clean repository layer so PostgreSQL can replace it later.
- [ ] Add append-only audit/event log for all AI decisions, risk decisions and broker actions.

Suggested layout:

```text
app/
  ai/
  research/
  strategies/
  market_data/
  fundamentals/
  news/
  portfolio/
  risk/
  execution/
  brokers/
  backtest/
  scheduler/
  storage/
  api/
  dashboard/
tests/
docs/
```

---

# Phase 2 — Ollama / GPT-OSS intelligence layer

- [ ] Add generic LLM provider interface.
- [ ] Implement Ollama provider.
- [ ] Configure `gpt-oss:120b` as the primary deep-reasoning model.
- [ ] Support a smaller/faster Ollama model for routine tasks.
- [ ] Require JSON-schema/structured outputs from trading agents.
- [ ] Validate every LLM response before it enters another subsystem.
- [ ] Add retry/timeout handling without duplicating trade actions.
- [ ] Persist prompts, model version, inputs, outputs and reasoning summary for auditability.
- [ ] Prevent untrusted web/news text from issuing tool instructions or trade commands.

### TradeIntent schema

- [ ] Define an immutable `TradeIntent` containing at least:
  - symbol / instrument ID
  - BUY / SELL / HOLD
  - delivery / intraday
  - thesis ID
  - strategy ID
  - target allocation or desired exposure
  - preferred entry range
  - invalidation/stop level
  - target/exit conditions
  - confidence
  - time horizon
  - supporting evidence IDs
  - decision timestamp and data cut-off timestamp

The LLM **must not specify unrestricted raw broker payloads**.

---

# Phase 3 — Indian market data layer

- [ ] Build canonical NSE/BSE instrument master with stable internal IDs.
- [ ] Handle symbol changes, corporate actions, delistings and instrument-token refreshes.
- [ ] Integrate real-time quotes via WebSocket.
- [ ] Integrate historical OHLCV candles.
- [ ] Store normalized candles/ticks locally for repeatable testing.
- [ ] Add trading calendar and NSE market-session awareness.
- [ ] Add pre-open, normal market and post-market state handling.
- [ ] Add corporate-action adjustment for historical prices.
- [ ] Add data freshness metadata to every observation.
- [ ] Reject decisions based on stale or incomplete critical market data.

---

# Phase 4 — Fundamental and public-information research

- [ ] NSE/BSE corporate-announcement ingestion.
- [ ] Quarterly and annual results ingestion.
- [ ] Company financial statement normalization.
- [ ] Corporate actions and board-meeting events.
- [ ] Shareholding/promoter changes where available.
- [ ] Market/index/sector context.
- [ ] RBI / macroeconomic data inputs where relevant.
- [ ] Financial-news ingestion from legally usable sources.
- [ ] Deduplicate syndicated news.
- [ ] Record publication time separately from event time.
- [ ] Create source/evidence store so every AI claim can point to input evidence.
- [ ] Add sentiment analysis as one signal only, never as an independent trading authority.

---

# Phase 5 — AI research team

Implement independent agents that return structured reports rather than broker actions.

- [ ] Market Regime Analyst — trend, breadth, volatility, sector leadership.
- [ ] Technical Analyst — momentum, trend, volume, volatility, support/resistance.
- [ ] Fundamental Analyst — growth, margins, balance sheet, cash flow, valuation.
- [ ] News/Event Analyst — recent events, earnings, announcements and macro news.
- [ ] Sentiment Analyst — public/news sentiment with source confidence.
- [ ] Portfolio Analyst — existing exposure, concentration, correlation and cash.
- [ ] Bull Researcher — strongest evidence for taking/increasing a position.
- [ ] Bear Researcher — strongest evidence against the proposed position.
- [ ] Research Manager — reconciles evidence and highlights unresolved uncertainty.
- [ ] Fund Manager — produces final `TradeIntent` or `NO_TRADE`.

### Important

- [ ] Add explicit `NO_TRADE` as a first-class successful outcome.
- [ ] Agents must see only point-in-time data available at the decision timestamp.
- [ ] Add maximum debate/research budget to avoid endless agent loops.
- [ ] Cache stable research so GPT-OSS does not repeatedly reread unchanged filings.

---

# Phase 6 — Deterministic strategy library

The AI can select/configure eligible strategies, but intraday execution logic should normally be deterministic.

- [ ] Define common `Strategy` interface.
- [ ] Build baseline buy-and-hold benchmark.
- [ ] Build moving-average trend baseline.
- [ ] Build momentum / relative-strength baseline.
- [ ] Build mean-reversion baseline.
- [ ] Build breakout + volume-confirmation baseline.
- [ ] Add VWAP-based intraday strategy candidate.
- [ ] Add volatility/regime filters.
- [ ] Add liquidity/average-volume filters.
- [ ] Add gap/open filters where relevant.
- [ ] Record exact strategy version on every signal/trade.
- [ ] Allow AI to recommend strategy activation but never alter protected risk bounds.

Later research:

- [ ] Random Forest / gradient-boosted stock scoring.
- [ ] Ensemble strategies.
- [ ] FinRL-style PPO/A2C/SAC experiments.
- [ ] Regime-specific strategy selection.

Do not promote ML/RL strategies merely because in-sample results are attractive.

---

# Phase 7 — Backtesting engine (must precede live trading)

- [ ] Event-driven or otherwise leakage-safe backtester.
- [ ] Ensure point-in-time fundamental/news data.
- [ ] Prevent look-ahead bias.
- [ ] Prevent survivorship bias where practical.
- [ ] Model brokerage.
- [ ] Model STT, exchange charges, GST, stamp duty and other applicable transaction costs.
- [ ] Model bid/ask spread and configurable slippage.
- [ ] Model partial/unfilled orders where material.
- [ ] Model intraday square-off rules.
- [ ] Benchmark against NIFTY 50 and appropriate strategy/index baselines.
- [ ] Report CAGR/annualised return.
- [ ] Report Sharpe and Sortino.
- [ ] Report maximum drawdown.
- [ ] Report volatility.
- [ ] Report win rate and profit factor.
- [ ] Report expectancy and average win/loss.
- [ ] Report turnover and cost drag.
- [ ] Report exposure by stock and sector.
- [ ] Export full trade ledger.

### Robustness validation

- [ ] Train/test split with strict chronology.
- [ ] Walk-forward testing.
- [ ] Parameter sensitivity tests.
- [ ] Multiple market regimes including crashes and sideways markets.
- [ ] Purged/CPCV-style validation where applicable.
- [ ] Deflated Sharpe / probability-of-backtest-overfitting research.
- [ ] Require an out-of-sample promotion gate before paper trading.

---

# Phase 8 — Broker abstraction and Indian broker selection

Create a broker-neutral interface first.

- [ ] `Broker.get_funds()`
- [ ] `Broker.get_holdings()`
- [ ] `Broker.get_positions()`
- [ ] `Broker.get_orders()`
- [ ] `Broker.place_order()`
- [ ] `Broker.modify_order()`
- [ ] `Broker.cancel_order()`
- [ ] `Broker.get_order_status()`
- [ ] `Broker.stream_orders()`
- [ ] `Broker.stream_market_data()` or separate data adapter.

### Broker candidates to evaluate

- [ ] Zerodha Kite Connect.
  - Mature REST order API and WebSocket feed.
  - Personal order/portfolio API available; paid Connect tier currently adds live/historical data.
  - No official sandbox, so we need our own simulation/paper adapter.
- [ ] Upstox Developer API.
  - V3 order API, live WebSocket feeds and documented sandbox-enabled order endpoints.
  - Evaluate current algo/static-IP requirements and session/auth behaviour.
- [ ] Evaluate DhanHQ and FYERS against the same checklist before choosing.

### Selection checklist

- [ ] Current SEBI/NSE retail-algo compliance support.
- [ ] Static-IP requirements.
- [ ] API reliability and rate limits.
- [ ] Order-update streaming.
- [ ] Historical + live-data availability/cost.
- [ ] Sandbox/paper support.
- [ ] Authentication/session renewal behaviour.
- [ ] Order varieties and stop-loss support.
- [ ] Developer SDK quality.
- [ ] Instrument-master quality.
- [ ] Cost.

---

# Phase 9 — Paper broker / simulated exchange

- [ ] Implement `PaperBroker` behind the same interface as the live broker.
- [ ] Simulate market, limit, SL and SL-M orders.
- [ ] Simulate fills using market data rather than instantly assuming success.
- [ ] Configurable latency and slippage.
- [ ] Partial fills.
- [ ] Rejections.
- [ ] Market-closed behaviour.
- [ ] Order update events.
- [ ] Portfolio/funds ledger.
- [ ] Paper-trading mode must run the exact same AI/risk/execution pipeline as live mode.

---

# Phase 10 — Deterministic risk engine

**This component has authority over the AI and cannot be overridden by prompts.**

- [ ] Maximum capital deployed.
- [ ] Maximum position size.
- [ ] Maximum sector exposure.
- [ ] Maximum correlated exposure.
- [ ] Maximum number of open positions.
- [ ] Maximum intraday trades/day.
- [ ] Maximum loss per trade.
- [ ] Maximum daily realised + unrealised loss.
- [ ] Maximum portfolio drawdown before safe mode.
- [ ] Minimum liquidity / volume rules.
- [ ] Price-band / circuit-limit awareness.
- [ ] Reject penny/illiquid instruments by default.
- [ ] Reject stale quotes.
- [ ] Reject orders outside allowed market/session rules.
- [ ] Reject duplicate/near-duplicate orders.
- [ ] Validate quantity, tick size, product and instrument token.
- [ ] Validate stop/target geometry.
- [ ] Validate available buying power/margin.
- [ ] Add per-strategy risk budget.
- [ ] Add portfolio-level exposure budget.
- [ ] Freeze risk-limit changes during active market hours by default.

### Kill switches

- [ ] `PAUSE_NEW_TRADES`.
- [ ] `CLOSE_INTRADAY`.
- [ ] `CANCEL_OPEN_ORDERS`.
- [ ] `FULL_KILL_SWITCH`.
- [ ] Automatic kill on daily loss limit.
- [ ] Automatic kill on broker/data inconsistency.
- [ ] Automatic kill on repeated order errors.
- [ ] Automatic kill when portfolio reconciliation fails.

---

# Phase 11 — Execution engine

- [ ] Convert approved `TradeIntent` into deterministic `OrderPlan`.
- [ ] Risk engine calculates maximum executable quantity.
- [ ] Prefer appropriate protected/limit orders rather than blindly using market orders.
- [ ] Generate unique client order IDs/idempotency keys.
- [ ] Persist intent before sending an order.
- [ ] Persist broker acknowledgement immediately.
- [ ] Handle timeout where broker may have accepted the order even though response was lost.
- [ ] Never retry a placement blindly.
- [ ] Reconcile via broker order book before retrying.
- [ ] Handle rejected, open, partial, filled and cancelled states.
- [ ] Attach/manage exit logic where broker capabilities permit.
- [ ] Intraday forced-exit scheduler with safety buffer before broker square-off.
- [ ] Reconcile holdings/positions/order book regularly.

---

# Phase 12 — Autonomous scheduler / market-day lifecycle

- [ ] Startup health check.
- [ ] Confirm broker session/authentication.
- [ ] Confirm market-data feed health.
- [ ] Confirm clock/timezone and trading calendar.
- [ ] Pre-market research cycle.
- [ ] Generate watchlist and portfolio plan.
- [ ] Market-open strategy activation.
- [ ] Intraday event loop.
- [ ] Periodic AI portfolio reassessment without blocking deterministic exits.
- [ ] End-of-day intraday square-off verification.
- [ ] Delivery portfolio reconciliation.
- [ ] Daily performance report.
- [ ] Post-trade/post-day AI critique.
- [ ] Persist all state so restart/recovery cannot duplicate trades.

---

# Phase 13 — Portfolio and delivery/swing manager

- [ ] Portfolio target-weight representation.
- [ ] Cash reserve policy.
- [ ] Delivery position sizing.
- [ ] Sector diversification.
- [ ] Concentration limits.
- [ ] Portfolio rebalancing engine.
- [ ] Thesis lifecycle: proposed → active → challenged → invalidated → closed.
- [ ] Re-evaluate positions after earnings/material announcements.
- [ ] Trailing/protective exit policy.
- [ ] Maximum holding thesis age without explicit revalidation.
- [ ] Benchmark attribution by stock/sector/strategy.

---

# Phase 14 — Intraday manager

- [ ] Separate intraday capital pool from delivery capital.
- [ ] Use deterministic real-time strategies for entries/exits.
- [ ] AI selects market regime and eligible strategy set; AI is not in the millisecond execution loop.
- [ ] Tick/quote stream health monitor.
- [ ] VWAP/momentum/breakout candidates.
- [ ] Volatility and liquidity filters.
- [ ] Stop-loss placement immediately after/with entry where broker semantics permit.
- [ ] Hard maximum holding duration.
- [ ] No averaging down unless a specifically tested strategy allows it.
- [ ] Daily loss circuit breaker.
- [ ] Forced flat state before configured cutoff.

---

# Phase 15 — Strategy discovery / AI quant lab

- [ ] Allow GPT-OSS to generate **hypotheses**, not production code/orders directly.
- [ ] Translate hypotheses into testable strategy specifications.
- [ ] Automated backtest queue.
- [ ] Automated rejection of strategies failing minimum sample size.
- [ ] Out-of-sample validation.
- [ ] Compare against simple baselines.
- [ ] Penalise high turnover and fragile parameters.
- [ ] Strategy registry with lifecycle:
  - experimental
  - backtesting
  - validated
  - paper
  - small-live
  - live
  - degraded
  - retired
- [ ] Detect live performance drift/strategy degradation.
- [ ] Automatically disable degraded strategies, but do not automatically loosen thresholds.

---

# Phase 16 — Dashboard / observability

- [ ] Web dashboard.
- [ ] Current broker connection and market-data health.
- [ ] Capital / cash / holdings / positions.
- [ ] Realised and unrealised P&L.
- [ ] NIFTY benchmark comparison.
- [ ] Today's orders/trades.
- [ ] Active strategies.
- [ ] Current market regime.
- [ ] Current research/watchlist.
- [ ] Risk utilisation and limits.
- [ ] Kill-switch controls.
- [ ] AI activity timeline.
- [ ] Agent reports and evidence.
- [ ] "Why did you do this?" view for every position/trade.
- [ ] Backtest and paper-trading reports.
- [ ] Strategy leaderboard by out-of-sample/live performance.

---

# Phase 17 — Alerts

- [ ] Trade opened/closed.
- [ ] Stop/target events.
- [ ] Order rejection.
- [ ] Daily loss warning.
- [ ] Kill switch activated.
- [ ] Broker disconnected.
- [ ] Market feed stale.
- [ ] Reconciliation mismatch.
- [ ] Daily summary.

Alerts are informational. Routine trades must not wait for human approval.

---

# Phase 18 — Security

- [ ] Secrets only through environment/secret store.
- [ ] Encrypt sensitive broker tokens at rest if persisted.
- [ ] Principle of least privilege.
- [ ] Dashboard authentication.
- [ ] CSRF/session security.
- [ ] Restrict live broker requests to execution service only.
- [ ] LLM/research services have no broker credential access.
- [ ] Network allow-list/static outbound IP where required.
- [ ] Audit configuration/risk-limit changes.
- [ ] Dependency and secret scanning in CI.
- [ ] Backup and recovery tests.

---

# Phase 19 — Indian regulatory/compliance checklist

Before enabling live automated trading, verify the then-current requirements directly with SEBI/NSE and the selected broker.

- [ ] Retail algo/API registration requirements.
- [ ] Order-per-second threshold rules.
- [ ] Static-IP requirements.
- [ ] Algo tagging requirements.
- [ ] Broker-specific API/algo onboarding.
- [ ] Exchange/broker restrictions on order types.
- [ ] Maintain required audit/order logs.
- [ ] Review rules again immediately before first live deployment because requirements can change.

---

# Phase 20 — Test suite

### Unit
- [ ] Indicator calculations.
- [ ] Position sizing.
- [ ] Risk limits.
- [ ] TradeIntent validation.
- [ ] OrderPlan generation.
- [ ] Cost/slippage models.
- [ ] Broker response parsing.

### Integration
- [ ] Market data → strategy → intent.
- [ ] Intent → risk approval/rejection.
- [ ] Approved intent → paper broker.
- [ ] Broker events → portfolio ledger.
- [ ] Restart → state recovery without duplicate orders.

### Failure injection
- [ ] LLM timeout.
- [ ] Malformed LLM JSON.
- [ ] Hallucinated symbol.
- [ ] Broker timeout after accepting order.
- [ ] WebSocket disconnect.
- [ ] Duplicate event.
- [ ] Partial fill.
- [ ] Broker order rejection.
- [ ] Stale market data.
- [ ] Database temporarily unavailable.
- [ ] Process crash immediately before/after order placement.

### Safety invariants
- [ ] AI cannot bypass risk engine.
- [ ] AI cannot change protected risk limits.
- [ ] No unvalidated symbol reaches broker.
- [ ] No order exceeds configured exposure.
- [ ] Daily kill limit always blocks new entries.
- [ ] Paper/live adapters satisfy the same broker contract.

---

# Phase 21 — Promotion gates

Do not enable the next stage merely because the software runs.

## Gate A — Backtest → Paper
- [ ] No known look-ahead leak.
- [ ] Costs/slippage included.
- [ ] Walk-forward/out-of-sample results recorded.
- [ ] Benchmark comparison recorded.
- [ ] Risk behaviour verified.

## Gate B — Paper → Tiny live capital
- [ ] Extended paper run completed across enough market conditions/trades.
- [ ] Zero duplicate-order incidents.
- [ ] Reconciliation is reliable.
- [ ] Kill switches tested.
- [ ] Broker/regulatory checklist completed.
- [ ] Live capital ceiling hard-coded/configured outside the LLM.

## Gate C — Capital increases
- [ ] Minimum live trade/sample threshold reached.
- [ ] Positive performance after all costs.
- [ ] Drawdown inside declared limit.
- [ ] No material safety incidents.
- [ ] Strategy remains statistically credible vs benchmark.
- [ ] Capital increases occur in explicit steps rather than automatically doubling exposure.

---

# Recommended implementation order

## Milestone 1 — Research simulator
- [ ] Repository foundation.
- [ ] Ollama/GPT-OSS integration.
- [ ] Historical Indian market data.
- [ ] Research agents.
- [ ] Initial strategy library.
- [ ] Backtesting engine.
- [ ] Risk engine.

**Result:** AI can research and backtest Indian equities but cannot touch a broker.

## Milestone 2 — Autonomous paper fund
- [ ] Paper broker.
- [ ] Scheduler.
- [ ] Portfolio manager.
- [ ] Intraday manager.
- [ ] Dashboard.
- [ ] Alerts.

**Result:** the whole system runs through market days autonomously with virtual capital.

## Milestone 3 — Broker-ready
- [ ] Select broker.
- [ ] Implement broker adapter.
- [ ] Authentication/session management.
- [ ] Order reconciliation.
- [ ] Compliance checklist.
- [ ] Failure-injection testing.

**Result:** production plumbing exists, but live orders remain disabled by configuration.

## Milestone 4 — Tiny-capital live pilot
- [ ] Enable cash-equity delivery/swing trading first.
- [ ] Hard capital ceiling.
- [ ] Hard daily loss ceiling.
- [ ] Monitor every trade and reconciliation event.

**Result:** autonomous real-money validation with deliberately small financial exposure.

## Milestone 5 — Limited live intraday
- [ ] Promote only validated intraday strategies.
- [ ] Separate intraday capital/risk pool.
- [ ] Strict daily kill switch.
- [ ] Automatic square-off verification.

**Result:** autonomous intraday trading without human per-trade approval.

## Explicitly out of V1
- [ ] Futures/options trading.
- [ ] Leverage-heavy strategies.
- [ ] High-frequency trading.
- [ ] AI-controlled risk-limit changes.
- [ ] AI-generated code automatically deployed into live trading without review/validation.

---

# First workstream to implement

1. Project scaffold + Docker + tests.
2. Ollama provider and typed `TradeIntent`.
3. Market-data interfaces and local historical store.
4. Deterministic risk-engine skeleton.
5. Paper broker contract.
6. A simple benchmark strategy and one momentum strategy.
7. Backtester with Indian transaction costs/slippage.
8. First GPT-OSS research agent working only on historical snapshots.
9. End-to-end historical simulation: data → research → intent → risk → simulated fill → portfolio → metrics.

Only after this pipeline is trustworthy should we spend time on live broker integration or a polished dashboard.

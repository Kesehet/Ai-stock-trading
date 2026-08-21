# Implementation Status

This file is the concise execution view. `tasks.md` remains the full production roadmap.

## Completed / substantially implemented

- [x] Python project scaffold and dependency management
- [x] Dockerfile and environment template
- [x] Ruff, strict mypy, pytest, and GitHub Actions CI
- [x] Typed `TradeIntent`, `OrderPlan`, quotes, positions, and risk decisions
- [x] Ollama structured-output client for GPT-OSS
- [x] Deterministic position sizing and risk gate
- [x] Maximum position cap, daily loss guard, stale quote rejection, open-position cap
- [x] Paper broker contract and in-memory execution
- [x] Evidence models with source tier/trust/provenance
- [x] RSS/Atom ingestion abstraction
- [x] Evidence deduplication and SQLite evidence store
- [x] Point-in-time evidence queries using `available_at`
- [x] First-pass event classification
- [x] Canonical instrument master using exchange/symbol/ISIN/internal ID
- [x] Text-to-instrument resolution for evidence ingestion
- [x] Official NSE equity-security CSV adapter/parser
- [x] Official-source RSS adapter factory for NSE feeds
- [x] NSE UDiFF daily bhavcopy downloader/parser
- [x] Cached NSE date-range history loader
- [x] Point-in-time historical OHLCV store
- [x] Generic split/bonus historical price adjustment engine
- [x] Buy-and-hold benchmark strategy
- [x] Momentum strategy
- [x] Configurable transaction-cost/slippage model
- [x] Current date-aware NSE cash-equity charge schedule abstraction
- [x] Leakage-conscious first backtest loop with return, drawdown, and Sharpe output
- [x] Next-bar execution backtester with Sharpe, Sortino, drawdown, and turnover
- [x] Deterministic evidence materiality scoring
- [x] GPT research context built only from evidence/candles visible at decision time
- [x] Prompt-injection boundary: fetched text is treated as untrusted evidence, not instructions
- [x] Technical, fundamental, news, and portfolio specialist-agent orchestration
- [x] Bull-vs-bear challenge and research-manager orchestration
- [x] Fund-manager agent producing `TradeIntent` / `NO_TRADE`
- [x] First end-to-end historical intent → risk → paper-fill simulation

## Critical path remaining before autonomous paper trading

1. [ ] Add BSE instrument/data adapters where dual-exchange coverage is useful
2. [ ] Ingest real split/bonus/corporate-action events into the adjustment engine
3. [ ] Wire concrete production NSE filing/result/corporate-action feed URLs/configuration
4. [ ] RBI/macro and selected legally usable financial-news adapters
5. [ ] Better entity resolution and ambiguity handling
6. [ ] Evidence clustering/syndication dedup beyond exact fingerprints
7. [ ] Fundamental-statement normalization and calculated ratios
8. [ ] Deterministic technical feature calculations for specialist context
9. [ ] Portfolio exposure/correlation context for the portfolio specialist
10. [ ] Limit/stop/partial-fill simulation beyond next-bar market fills
11. [ ] Historical charge schedules for older backtest periods
12. [ ] NIFTY benchmark data and full metrics suite
13. [ ] Walk-forward/out-of-sample validation and overfitting checks
14. [ ] Persistent portfolio ledger and thesis lifecycle
15. [ ] Autonomous market-day scheduler
16. [ ] Realistic paper exchange with latency/slippage/rejections
17. [ ] Dashboard, evidence/explanation timeline, and kill switches
18. [ ] Alerts and daily reports

## Critical path remaining before live trading

19. [ ] Compare current Zerodha / Upstox / Dhan / FYERS APIs and choose broker
20. [ ] Implement full broker interface and authentication/session management
21. [ ] Order update streaming and portfolio/order reconciliation
22. [ ] Idempotent execution and timeout-after-acceptance recovery
23. [ ] Static-IP/network requirements where applicable
24. [ ] Complete deterministic risk limits: sector/correlation/liquidity/drawdown/etc.
25. [ ] Kill-switch engine and automatic safe mode
26. [ ] Failure-injection test suite
27. [ ] Security hardening and secrets separation
28. [ ] Re-check then-current SEBI/NSE/broker retail-algo requirements
29. [ ] Extended autonomous paper run
30. [ ] Tiny-capital delivery/swing live gate
31. [ ] Only after validation: limited intraday live gate

## Later / non-blocking research

- [ ] Mean reversion, breakout, VWAP and regime strategies
- [ ] ML/ensemble stock scoring
- [ ] FinRL/RL experiments
- [ ] Automated AI strategy hypothesis lab
- [ ] Strategy degradation detection and retirement
- [ ] PostgreSQL migration when SQLite becomes insufficient
- [ ] F&O (explicitly not V1)

## Current milestone definition

The next milestone is complete when the system can be given a historical timestamp and capital amount, then autonomously:

1. resolve the tradable universe,
2. load only market/evidence data available at that time,
3. run research agents,
4. emit `TradeIntent` or `NO_TRADE`,
5. apply deterministic risk,
6. simulate realistic fills and Indian costs,
7. update the portfolio,
8. repeat through time, and
9. produce benchmarked performance and an auditable explanation for every decision.

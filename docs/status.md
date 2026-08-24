# Implementation Status

This file is the concise execution view. `tasks.md` remains the full production roadmap.

## Completed / substantially implemented

- [x] Python project scaffold and dependency management
- [x] Hardened non-root Docker image and environment template
- [x] Safe-default `compose.yaml` plus explicit `compose.live.yaml` override
- [x] Compose Linux host-gateway support, bounded logs, resources and graceful shutdown
- [x] Ruff, strict mypy, pytest, and GitHub Actions CI
- [x] Docker image + paper/live Compose validation in GitHub Actions
- [x] Scheduled/PR dependency and Python security scans (`pip-audit` + Bandit)
- [x] Explicit live-mode arming gate and confirmation phrase
- [x] Broker secrets/access tokens masked by Pydantic secret types
- [x] Container heartbeat/liveness healthcheck and graceful shutdown
- [x] Secrets/data/log exclusions in `.gitignore` and `.dockerignore`
- [x] Production security audit and Docker deployment runbook
- [x] Persistent SQLite operational audit log and safe-mode state
- [x] Emergency safe-mode CLI with explicit clear confirmation
- [x] Zerodha login URL/request-token exchange implementation
- [x] Zerodha session expiry model (6 AM next day), restricted session storage and status CLI
- [x] Live runtime automatically trips persistent safe mode for missing/expired Zerodha session
- [x] Transactional persistent paper broker with restart-safe cash/positions/orders
- [x] Paper-order idempotency using `intent_id`
- [x] Persistent thesis lifecycle with evidence, cutoff, horizon and close/invalidation reason
- [x] Deterministic India market-phase scheduler
- [x] Verified 2026 NSE Capital Market holiday calendar with fail-closed unknown-year behavior
- [x] Runtime audit events for market-phase transitions
- [x] Simple read-only financial dashboard home page
- [x] Dashboard shows paper/real mode, starting capital, deployed capital, current value and P&L
- [x] Dashboard portfolio-value trend and open-position allocation graphics
- [x] Dashboard valuation history store with explicit cost-basis fallback when no market mark exists
- [x] Dashboard isolated as a separate low-resource container and published only to host localhost by default
- [x] AI reasoning/planning intentionally excluded from the dashboard; detailed internals remain in logs
- [x] Typed `TradeIntent`, `OrderPlan`, quotes, positions, and risk decisions
- [x] Ollama structured-output client for GPT-OSS
- [x] Deterministic position sizing and risk gate
- [x] Maximum position cap, daily loss guard, stale quote rejection, open-position cap
- [x] Paper broker contract and in-memory execution
- [x] Evidence models with source tier/trust/provenance
- [x] RSS/Atom ingestion abstraction using hardened `defusedxml` parsing
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
- [x] NSE historical-index CSV parser and point-in-time benchmark store
- [x] Benchmark excess return, tracking error and information-ratio metrics
- [x] Configurable transaction-cost/slippage model
- [x] Current date-aware NSE cash-equity charge schedule abstraction
- [x] Leakage-conscious first backtest loop with return, drawdown, and Sharpe output
- [x] Next-bar execution backtester with Sharpe, Sortino, drawdown, and turnover
- [x] Deterministic evidence materiality scoring
- [x] GPT research context built only from evidence/candles visible at decision time
- [x] Prompt-injection boundary: fetched text is treated as untrusted evidence, not instructions
- [x] Technical, fundamental, news, and portfolio specialist-agent orchestration
- [x] Deterministic technical features: SMA/EMA/RSI/returns/volatility/volume/high-distance
- [x] Point-in-time fundamental snapshots with growth, margin, ROE, D/E and P/E calculations
- [x] Point-in-time macro-regime snapshot store
- [x] Portfolio exposure, cash weight, position weight and pair-correlation context
- [x] Role-specific specialist prompts instead of one shared generic context
- [x] Bull-vs-bear challenge and research-manager orchestration
- [x] Fund-manager agent producing `TradeIntent` / `NO_TRADE`
- [x] First end-to-end historical intent → risk → paper-fill simulation
- [x] Live broker selected: Zerodha Kite Connect

## Critical path remaining before autonomous paper trading

1. [ ] Add BSE instrument/data adapters where dual-exchange coverage is useful
2. [ ] Ingest real split/bonus/corporate-action events into the adjustment engine
3. [ ] Wire concrete production NSE filing/result/corporate-action feed URLs/configuration
4. [ ] RBI/macro and selected legally usable financial-news adapters
5. [ ] Better entity resolution and ambiguity handling
6. [ ] Evidence clustering/syndication dedup beyond exact fingerprints
7. [ ] Production fundamental-statement adapters feeding normalized snapshots
8. [ ] Limit/stop/partial-fill simulation beyond next-bar market fills
9. [ ] Historical charge schedules for older backtest periods
10. [ ] Automated official NIFTY/TRI source feeding the benchmark store
11. [ ] Walk-forward/out-of-sample validation and overfitting checks
12. [ ] Wire persistent paper broker + thesis store into the autonomous lifecycle
13. [ ] Load/refresh NSE holiday calendars automatically for future years
14. [ ] Run scheduled premarket/open/closing/postmarket jobs, not only phase detection
15. [ ] Realistic paper exchange with latency/slippage/rejections
16. [ ] Feed regular marked portfolio snapshots into the dashboard from market data
17. [ ] Alerts and daily reports

## Critical path remaining before live trading

18. [ ] Implement Zerodha broker order/portfolio interface (authentication lifecycle foundation exists)
19. [ ] Order update streaming and portfolio/order reconciliation
20. [ ] Idempotent execution and timeout-after-acceptance recovery
21. [ ] Confirm and implement static-IP/network requirements where applicable
22. [ ] Complete deterministic risk limits: sector/correlation/liquidity/drawdown/etc.
23. [ ] Wire safe-mode state into every future order path and add close/cancel kill actions
24. [ ] Failure-injection test suite
25. [ ] Persistent transaction-safe live order/portfolio ledger and tested backups
26. [ ] Re-check then-current SEBI/NSE/Zerodha retail-algo requirements
27. [ ] Extended autonomous paper run
28. [ ] Tiny-capital delivery/swing live gate
29. [ ] Only after validation: limited intraday live gate

## Later / non-blocking research

- [ ] Mean reversion, breakout, VWAP and regime strategies
- [ ] ML/ensemble stock scoring
- [ ] FinRL/RL experiments
- [ ] Automated AI strategy hypothesis lab
- [ ] Strategy degradation detection and retirement
- [ ] PostgreSQL migration when SQLite becomes insufficient
- [ ] F&O (explicitly not V1)

## Current deployment verdict

- **Paper/backtest Docker deployment:** APPROVED on the current branch. CI, Security and Docker workflows are green.
- **Dashboard:** APPROVED on the current branch. It is read-only, low-resource and localhost-only by default.
- **Real-money live execution:** intentionally blocked. There is still no broker order-placement route, and live mode fails closed when its safety/session prerequisites are not satisfied.

# Implementation Status

This file is the concise execution view. `tasks.md` remains the full production roadmap.

## Completed / substantially implemented

- [x] Python project scaffold and dependency management
- [x] Dockerfile and environment template
- [x] Ruff, strict mypy, pytest, GitHub Actions CI, Docker validation, security scans
- [x] Typed `TradeIntent`, `OrderPlan`, quotes, positions, and risk decisions
- [x] Ollama structured-output client for GPT-OSS
- [x] Deterministic position sizing and risk gate
- [x] Maximum position cap, daily loss guard, stale quote rejection, open-position cap
- [x] Persistent SQLite paper broker with idempotent intents and restart-safe cash/positions
- [x] Evidence models with source tier/trust/provenance
- [x] RSS/Atom ingestion abstraction
- [x] Evidence deduplication and SQLite evidence store
- [x] Point-in-time evidence queries using `available_at`
- [x] Canonical instrument master using exchange/symbol/ISIN/internal ID
- [x] Official NSE equity-security CSV adapter/parser
- [x] NSE UDiFF daily bhavcopy downloader/parser and cached range loader
- [x] Point-in-time historical OHLCV store
- [x] Generic split/bonus historical price adjustment engine
- [x] Date-aware NSE cash-equity charge schedule abstraction
- [x] Leakage-conscious next-bar backtester with Sharpe, Sortino, drawdown, turnover
- [x] Technical/fundamental/news/portfolio specialist context
- [x] Bull-vs-bear challenge, research manager, and fund-manager orchestration
- [x] Broker-agnostic `AutonomousFundEngine` shared by paper and future live modes
- [x] Empty universe default = auto-discover official NSE EQ master
- [x] Full-exchange deterministic screening by history, price, traded value and momentum
- [x] Configurable candidate cap after screening; no hardcoded production stock list
- [x] Autonomous NSE-open fund cycles with audited HOLD/reject/fill/error outcomes
- [x] Read-only Zerodha live quote adapter for paper execution
- [x] Hardened Docker/Compose runtime and live arming controls
- [x] Zerodha session lifecycle/safe-mode enforcement

## Critical path remaining before autonomous paper trading is considered mature

1. [ ] Ingest real split/bonus/corporate-action events into the adjustment engine
2. [ ] Wire production NSE filing/result/corporate-action feeds end to end
3. [ ] RBI/macro and selected legally usable financial-news adapters
4. [ ] Better entity resolution and evidence clustering/syndication dedup
5. [ ] NIFTY benchmark feed and full daily performance reporting
6. [ ] Walk-forward/out-of-sample validation and overfitting checks
7. [ ] Persistent thesis lifecycle and richer portfolio ledger/P&L attribution
8. [ ] Limit/stop/partial-fill simulation, latency and rejection modeling
9. [ ] Dashboard explanation timeline and kill switches
10. [ ] Alerts and daily reports
11. [ ] Extended unattended autonomous paper run

## Critical path remaining before live trading

12. [ ] Implement Zerodha live `Broker` adapter behind the existing common engine
13. [ ] Order update streaming and broker portfolio/order reconciliation
14. [ ] Idempotent timeout-after-acceptance recovery
15. [ ] Complete deterministic risk: existing exposure, SELL sizing, sector/correlation/liquidity/drawdown
16. [ ] Kill-switch engine and automatic safe mode wired to execution
17. [ ] Failure-injection suite for broker/network/restart/partial-fill scenarios
18. [ ] Security hardening review immediately before live promotion
19. [ ] Re-check then-current SEBI/NSE/Zerodha retail-algo requirements
20. [ ] Tiny-capital delivery/swing live gate
21. [ ] Only after validation: limited intraday live gate

## Important architecture invariant

Paper and live must not have separate trading logic. The shared pipeline is:

`universe -> research -> fund decision -> deterministic risk -> Broker`

Paper injects `PersistentPaperBroker`. Future live injects `ZerodhaBroker`. Switching modes must not change stock selection, AI prompts, risk rules, scheduling, or audit behavior.

## Later / non-blocking research

- [ ] Mean reversion, breakout, VWAP and regime strategies
- [ ] ML/ensemble stock scoring
- [ ] FinRL/RL experiments
- [ ] Automated AI strategy hypothesis lab
- [ ] Strategy degradation detection and retirement
- [ ] PostgreSQL migration when SQLite becomes insufficient
- [ ] F&O (explicitly not V1)

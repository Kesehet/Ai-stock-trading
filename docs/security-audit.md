# Production Security Audit

Date: 2026-08-25
Scope: current `feat/foundation-paper-engine` deployment and live-trading preparation.

## Executive summary

Current posture is suitable for **paper/backtest deployment**, not yet for real-money trading. The live execution adapter is intentionally absent. The highest-risk boundary is protected by deterministic risk controls plus an explicit live-mode arming gate.

## Findings and remediations

### 1. Critical — accidental live-mode activation
**Status:** remediated in this branch.

`APP_MODE=live` alone no longer enables startup. Live mode requires:
- `LIVE_TRADING_ARMED=true`
- an exact confirmation phrase
- Zerodha API key and API secret

The live broker adapter remains disabled until a later reviewed milestone.

### 2. High — container previously ran as root
**Status:** remediated.

The Docker image now creates and runs as an unprivileged `app` user.

### 3. High — writable container root filesystem
**Status:** remediated in Compose.

The service uses a read-only root filesystem. Persistent application state is isolated to `/var/lib/ai-stock-trading`; `/tmp` is tmpfs.

### 4. High — excessive Linux container privileges
**Status:** remediated in Compose.

All Linux capabilities are dropped and `no-new-privileges` is enabled. PID, memory, and CPU limits are defined.

### 5. High — broker/API secrets leaking into source or images
**Status:** remediated structurally; operational discipline still required.

`.dockerignore` and `.gitignore` exclude `.env`, secrets, data files and logs. Real broker credentials must be injected at runtime by the server/orchestrator secret store and must never be committed.

Do not pass secrets as Docker build args.

### 6. High — Zerodha session lifecycle
**Status:** known operational requirement.

Kite Connect access tokens expire at 6 AM the next day. The final broker-auth flow must persist only the current server-side session token and move to safe mode if authentication expires. It must never silently continue with stale credentials.

### 7. High — public network exposure
**Status:** safe in current Compose design.

The trading worker exposes no host port. A future dashboard/API must be a separate authenticated service, ideally behind TLS/reverse proxy, with CSRF/session protection and no direct broker-secret exposure.

### 8. Medium — dependency vulnerabilities
**Status:** automated check added.

A GitHub Security workflow now runs `pip-audit` on PRs/main and weekly.

### 9. Medium — Python security lint
**Status:** automated check added.

The Security workflow runs Bandit against `app/`.

### 10. Medium — process liveness
**Status:** remediated for deployment readiness.

The runtime writes a heartbeat and Docker has a healthcheck that fails on a missing/stale heartbeat. SIGTERM/SIGINT are handled for graceful container shutdown.

### 11. Medium — persistence and database integrity
**Status:** partially addressed.

Runtime data lives on a dedicated persistent volume. Before live trading, portfolio/order/audit ledgers must move to transaction-safe persistent storage with backups and reconciliation after restart.

### 12. Medium — prompt injection from financial/news content
**Status:** substantially remediated.

Fetched filings/news are marked as untrusted evidence and agents are instructed not to treat source text as executable instructions. Deterministic code, not the LLM, owns risk/execution.

### 13. Medium — stale or future data
**Status:** substantially remediated.

Point-in-time stores and `available_at` timestamps prevent historical future-data leakage. Live mode must also stop new entries on stale market data or reconciliation failures.

## Required before real-money trading

- Implement and review Zerodha broker adapter.
- Implement daily Kite login/session-token lifecycle and expiry safe mode.
- Add order idempotency and timeout-after-acceptance reconciliation.
- Add broker/order/position reconciliation on startup and periodically.
- Complete kill-switch engine and failure-injection tests.
- Add liquidity, sector, correlation and portfolio drawdown limits.
- Put dashboard/API behind authenticated TLS; do not expose the worker directly.
- Use server-side secret storage; rotate any secret ever pasted into logs/chat/source.
- Add persistent audit/order/portfolio ledger with backups.
- Verify current SEBI/NSE/Zerodha retail-algo requirements immediately before enabling live execution.
- Complete an extended autonomous paper-trading period before live promotion.

## Deployment verdict

**Paper/backtest Docker deployment:** APPROVED with current hardening, subject to CI/security workflow passing.

**Real-money live trading:** NOT APPROVED yet. Live broker execution remains intentionally unimplemented and should stay that way until the remaining controls above are complete.

# Docker Deployment Runbook

## Safe paper deployment

1. Copy `.env.example` to `.env` on the server.
2. Keep `APP_MODE=paper` and `LIVE_TRADING_ARMED=false`.
3. Set `OLLAMA_BASE_URL` to the reachable Ollama endpoint. Do not expose Ollama publicly without authentication/network controls.
4. Start:

```bash
docker compose up -d --build
```

5. Verify:

```bash
docker compose ps
docker compose logs --tail=200 trader
```

The worker exposes no public port. Runtime state is stored in the `trader-data` volume.

## Explicit live override

Do **not** use this until the live-readiness checklist in `docs/security-audit.md` is complete and the broker adapter has been reviewed.

The live override is intentionally separate:

```bash
docker compose -f compose.yaml -f compose.live.yaml up -d --build
```

Live startup additionally requires server-side environment secrets including the explicit arming controls and Zerodha credentials. Do not commit these values to GitHub.

## Zerodha session lifecycle

`ZERODHA_API_KEY` and `ZERODHA_API_SECRET` are long-lived application credentials and belong in the server secret store. The Kite `access_token` is a session credential and expires at 6 AM the next day; it must be renewed through the normal login/token-exchange flow.

The final production system should enter safe mode and block new orders when the broker session expires or reconciliation cannot be completed.

## Container security defaults

- unprivileged runtime user
- read-only root filesystem
- all Linux capabilities dropped
- `no-new-privileges`
- no host ports
- CPU/memory/PID limits
- persistent state isolated to a named volume
- tmpfs `/tmp`
- liveness heartbeat healthcheck
- `.env`, secrets, DBs, logs and local data excluded from Docker build context

## Backups

Before real-money activation, migrate the order/portfolio/audit ledger to durable transactional storage and configure tested backups. Do not rely on an ephemeral container filesystem.

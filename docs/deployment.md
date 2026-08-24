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

## Emergency safety controls

These controls work before the dashboard exists and persist across container restarts.

Check safe-mode state:

```bash
docker compose run --rm trader python -m app.safety_cli status
```

Immediately trip safe mode:

```bash
docker compose run --rm trader python -m app.safety_cli trip --reason MANUAL_EMERGENCY_STOP
```

Safe mode is deliberately harder to clear. Clear it only after the underlying cause has been investigated:

```bash
docker compose run --rm trader python -m app.safety_cli clear \
  --confirmation I_HAVE_RESOLVED_THE_SAFETY_CAUSE
```

Future broker order paths must check this persistent safe-mode state before every new order. Clearing a Zerodha authentication problem cannot clear a different risk/safety trip.

## Explicit live override

Do **not** use this until the live-readiness checklist in `docs/security-audit.md` is complete and the broker adapter has been reviewed.

The live override is intentionally separate:

```bash
docker compose -f compose.yaml -f compose.live.yaml up -d --build
```

Live startup additionally requires server-side environment secrets including the explicit arming controls and Zerodha credentials. Do not commit these values to GitHub.

## Zerodha session lifecycle

`ZERODHA_API_KEY` and `ZERODHA_API_SECRET` are long-lived application credentials and belong in the server secret store. Kite access tokens expire at 6 AM the next day and must be renewed through the normal login/token-exchange flow.

The worker now fails closed: if live mode is armed and the locally stored Zerodha session is missing or expired, persistent safe mode is enabled automatically. Restarting the container does not clear that state.

Generate the normal Kite login URL without exposing the API secret:

```bash
docker compose run --rm trader python -m app.zerodha_cli login-url
```

After logging in to Zerodha, exchange the returned `request_token`. The CLI prompts interactively so the request token is not placed in the shell command/history:

```bash
docker compose run --rm trader python -m app.zerodha_cli exchange
```

Check session and safe-mode status:

```bash
docker compose run --rm trader python -m app.zerodha_cli status
```

A successful session refresh automatically clears safe mode **only** when its reason is `ZERODHA_SESSION_MISSING_OR_EXPIRED`. Other safety trips are never cleared by broker authentication.

## Persistent operations state

The `trader-data` volume contains the operational SQLite audit/safety ledger and the permission-restricted Zerodha session file. The audit store uses WAL mode and full synchronous durability. Raw broker secrets/access tokens must never be written to the audit payload.

## Container security defaults

- unprivileged runtime user
- read-only root filesystem
- all Linux capabilities dropped
- `no-new-privileges`
- no host ports
- CPU/memory/PID limits
- bounded Docker JSON logs
- persistent state isolated to a named volume
- tmpfs runtime temp directory
- liveness heartbeat healthcheck
- `.env`, secrets, DBs, logs and local data excluded from Docker build context

## Backups

Before real-money activation, extend the durable ledger to orders/positions/reconciliation state and configure tested backups. Do not rely on an ephemeral container filesystem.

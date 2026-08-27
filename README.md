# AI Stock Trading

Autonomous Indian cash-equity research, risk, backtesting, paper trading, and future live execution platform.

## Core rule

AI proposes trades. Deterministic code owns risk and execution approval.

The production architecture intentionally uses the same trading pipeline in paper and live modes:

```text
NSE universe -> deterministic screening -> research agents -> fund decision
-> deterministic risk -> Broker
```

Only the injected broker changes:

- paper: `PersistentPaperBroker`
- future live: `ZerodhaBroker`

This prevents paper and production behavior from drifting apart.

## Dynamic universe

`PAPER_UNIVERSE` is empty by default. Empty means the service downloads the official NSE EQ security master, scans the available historical data for the whole exchange, filters out names that fail deterministic liquidity/history/price rules, ranks the survivors, and sends only the top candidates to the expensive multi-agent research stage.

Set `PAPER_UNIVERSE=TCS,RELIANCE` only when deliberately constraining the mandate for debugging or a controlled test.

Default screening controls:

```text
UNIVERSE_CANDIDATE_LIMIT=75
UNIVERSE_MIN_PRICE=20
UNIVERSE_MIN_HISTORY_BARS=20
UNIVERSE_MIN_AVG_TRADED_VALUE=50000000
```

The candidate limit is applied after scanning the exchange; it is not a hardcoded stock universe.

## Safety

- Live mode requires explicit arming and an exact confirmation phrase.
- Zerodha is read-only in paper mode.
- No real-money order route is enabled yet.
- Broker secrets are runtime secrets and must never be committed.
- The Docker runtime is non-root, read-only where possible, capability-dropped, and resource bounded.

## Development

```bash
pip install -e '.[dev]'
ruff check .
mypy app
pytest
```

## Docker

```bash
cp .env.example .env
docker compose up --build
```

The default Compose deployment starts in paper mode.

See:

- `docs/status.md` for the current execution board
- `docs/deployment.md` for deployment instructions
- `docs/security-audit.md` for the security review
- `tasks.md` for the full roadmap

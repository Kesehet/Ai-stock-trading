# AI Stock Trading

Autonomous Indian-equity research and trading platform built around a strict separation of concerns:

- **GPT-OSS / Ollama** researches and proposes structured trade intents.
- **Deterministic risk code** decides whether a proposal is executable and caps quantity/exposure.
- **Broker adapters** execute only approved order plans.
- **Paper/backtest modes** use the same intent → risk → execution boundary planned for live mode.

> This project is experimental trading infrastructure, not a promise of profitable returns. Live trading must remain disabled until backtesting, paper trading, broker reconciliation, operational controls and current Indian regulatory requirements have been validated.

## Current milestone

The foundation branch implements:

- Pydantic `TradeIntent`, `OrderPlan`, quote/position and risk-decision models.
- Deterministic position sizing and risk rejection rules.
- Broker protocol plus an in-memory `PaperBroker`.
- Ollama structured-output client.
- Tests proving AI-requested allocations cannot exceed deterministic risk caps.
- CI with Ruff, mypy and pytest.

No live broker adapter exists yet.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e '.[dev]'
cp .env.example .env
pytest
python -m app.demo
```

## Ollama

Run Ollama separately and configure `.env`:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gpt-oss:120b
```

The LLM client requires output that validates against a Pydantic/JSON schema before it can enter the trading pipeline.

## Safety invariant

The AI never receives unrestricted broker-order authority. It emits a `TradeIntent`. Deterministic code validates market data, portfolio state and protected risk limits, then produces an `OrderPlan`. Only a broker adapter can execute the resulting plan.

See `tasks.md` for the full roadmap.

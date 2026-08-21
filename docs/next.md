# Immediate Next Milestone

After the foundation PR passes CI:

1. Add historical OHLCV provider abstraction and local fixture data.
2. Add a leakage-safe event-driven backtest loop.
3. Implement buy-and-hold and momentum baselines.
4. Add Indian transaction-cost model (configurable, date-aware inputs).
5. Add performance metrics: return, drawdown, Sharpe, Sortino, win rate, profit factor and turnover.
6. Wire GPT-OSS into a research-only agent that emits `TradeIntent` objects from point-in-time inputs.
7. Run the complete pipeline against historical dates before adding any live broker adapter.

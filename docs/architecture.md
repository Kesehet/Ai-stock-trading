# Foundation Architecture

## Trust boundary

```text
Research / LLM / Strategy
          |
          v
     TradeIntent
          |
          v
   RiskEngine (hard gate)
          |
     approve/reject
          |
          v
      OrderPlan
          |
          v
        Broker
```

The LLM is not a broker client. It cannot choose arbitrary raw broker fields, bypass portfolio limits, or increase protected risk limits.

## Foundation invariants

1. `TradeIntent` is schema validated.
2. A `HOLD` intent does not become an order.
3. Quotes must match the requested symbol and must be fresh.
4. Daily-loss limits can block new trades.
5. Maximum position allocation caps the AI's requested allocation.
6. Entry ranges stop the system from blindly chasing price.
7. Only an approved `OrderPlan` is sent to a broker adapter.
8. Paper and eventual live modes must share this same boundary.

## Current limitations

The V1 paper broker intentionally uses immediate fills at the plan's limit price. It is a state-machine foundation, not yet a realistic exchange simulator. Later milestones add OHLC/tick-aware fills, slippage, latency, partial fills, rejections, market sessions, transaction costs and broker reconciliation.

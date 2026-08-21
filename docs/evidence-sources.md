# Evidence and Information Sources

The trading AI should reason from normalized evidence, not browse arbitrary pages directly during a trade decision.

## Trust hierarchy

1. **OFFICIAL** — NSE/BSE filings, SEBI/RBI/government releases and exchange circulars.
2. **PRIMARY** — company investor-relations releases, annual reports and earnings-call material.
3. **WIRE** — reputable news wires.
4. **NEWS** — reputable financial publications and broadcasters.
5. **SOCIAL** — social/community sources used for discovery or sentiment, never as sole authority for a trade.

Trust tier is not the same as bullish/bearish sentiment. An official filing can contain bad news and a social post can be factually correct; the tier describes provenance and verification quality.

## Point-in-time rule

Every `EvidenceItem` has:

- `published_at` — timestamp supplied by the publisher/source.
- `event_at` — when the underlying event occurred, if known.
- `retrieved_at` — when our system retrieved the item.
- `available_at` — earliest timestamp at which this trading system is allowed to use the item.

Backtests and historical simulations query the `EvidenceStore` using `available_at`. This prevents future-information leakage.

## Initial production adapters

### NSE

Use official RSS/filing feeds for categories such as:

- corporate announcements
- annual reports
- board meetings
- corporate actions
- financial results
- insider trading
- related-party transactions
- shareholding patterns
- exchange circulars

The generic `RSSSource` is intentionally configured by URL instead of embedding exchange endpoints throughout the codebase.

### BSE / SEBI / RBI

Implement dedicated adapters as source behaviour and availability are verified. They must produce the same `EvidenceItem` schema.

### Financial news

News adapters should preserve the original publisher, URL and publication timestamp, and should deduplicate syndicated copies. A discovery service (for example a news index) is not itself treated as the evidence publisher.

## Ingestion path

```text
Source adapter
    -> EvidenceItem
    -> fingerprint deduplication
    -> EvidenceStore
    -> deterministic event classification
    -> entity/symbol resolution (next)
    -> materiality/relevance scoring (next)
    -> research agents / GPT-OSS
```

## Safety rule

Text fetched from filings/news is untrusted data. It can provide facts to a research prompt, but it cannot provide system instructions, change risk limits, or directly invoke broker tools.

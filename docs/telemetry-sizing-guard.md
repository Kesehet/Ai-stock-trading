# Telemetry and whole-share sizing guard

This change addresses two small-account reliability issues observed on 3 Sep 2026.

## Whole-share allocation granularity

The risk engine may round an AI-requested allocation up to one whole share when fractional execution is impossible. The override is now bounded: the minimum executable one-share notional may not exceed 2x the requested allocation. This prevents a low-single-digit allocation request from silently becoming a near-half-portfolio position while preserving modest whole-share overshoots.

The guard is part of the shared deterministic risk engine, so paper and live modes use the same rule.

## Fund telemetry retrieval

The Fund Telemetry workflow now fetches strategy memory first and gives the deep fund-status endpoint a bounded 60-second request window with one retry. The workflow-level timeout is three minutes. This makes manual and scheduled snapshots more tolerant of temporary SQLite/read contention while remaining bounded.

If deep fund-status requests continue to need tens of seconds after this change, the next step should be precomputed server-side telemetry rather than increasing timeouts further.

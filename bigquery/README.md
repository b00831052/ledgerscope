# Ledgerscope → BigQuery — Migration Plan

*Status: **ready to activate**. Every file here works the moment the BigQuery connector is authorized. Until then, `build.py` already writes daily snapshots to `../snapshots/` locally — so the proprietary time series is accumulating now, warehouse or not.*

## Why (the actual gain, not just "a warehouse")

1. **Kills the survivorship bias.** Today the historical chart is rebuilt each run from DefiLlama's `/protocol/{slug}` — which only knows protocols *alive today*. By appending our own dated snapshot every run, protocols that later die stay in past partitions. The history becomes complete and honest. *(This is the caveat flagged in `../METHODOLOGY.md §7`.)*
2. **Proprietary data moat.** Our snapshots capture our *computed* fields — LS Score, NAV gap, peer-relative percentile, rating — not just raw TVL. That daily rating time series cannot be reconstructed from DefiLlama by anyone else. It is the asset an acquirer (S&P, MSCI) actually pays for.
3. **Real analytics.** Rating migration, verdict changes, concentration trend, stress log, APAC book over time — SQL over `queries.sql`, not JS over a single snapshot.

## Architecture

```
build.py (daily, unchanged pipeline)
   ├── terminal.html / index.html        (unchanged — the live product)
   ├── data.json                          (unchanged — latest snapshot)
   └── snapshots/rwa_YYYY-MM-DD.ndjson    (NEW — one row per fund per day)  ← accumulating NOW
                     │
                     ▼   (on authorize)
        bigquery/load.sh  →  ledgerscope.rwa_snapshots  (partitioned by date, clustered cls+slug)
                     │
                     ├── VIEW rwa_latest        → terminal "today"
                     ├── VIEW class_history     → survivorship-free history chart
                     └── VIEW fund_trajectory   → rating/verdict migration
```

## Activation steps (once you authorize)

**Option A — connector (no local setup):** authorize `bigquery` in your claude.ai connector settings, then ask me to run the DDL (`schema.sql`) and load, using the `data:sql-queries` skill against the connector.

**Option B — CLI (service account / gcloud):**
```bash
export GCP_PROJECT=your-project-id          # e.g. ledgerscope-prod
export BQ_LOCATION=asia-southeast1          # Singapore
gcloud auth login                           # your account, your action
bq query --use_legacy_sql=false < bigquery/schema.sql   # create dataset + tables + views
./bigquery/load.sh --all                    # load every accumulated snapshot
```

Then point the terminal's history at BigQuery (Phase 3 below).

## Phases

| Phase | What | Status |
|---|---|---|
| 0 | Emit daily snapshots locally | ✅ **done** (running now) |
| 1 | Dataset + tables + views (`schema.sql`) | ready — needs auth to run |
| 2 | Load accumulated snapshots (`load.sh`) | ready — needs auth to run |
| 3 | `build.py --from-bq` reads `class_history` for the chart (kills survivorship bias in the UI) | to wire after first load |
| 4 | Backfill seed from `/protocol` history (one-off) so the chart isn't empty on day 1 | optional, script on request |

## Cost
Trivial at this scale: ~150 rows/day × 40 columns. Storage is cents/month; queries scan KBs–MBs (partition pruning). Well within the BigQuery free tier.

## Files
- `schema.sql` — DDL: fact table + 3 views.
- `load.sh` — idempotent per-partition loader (`--all` to reload).
- `queries.sql` — the 6 analytics that showcase the warehouse.
- `../snapshots/` — the accumulating NDJSON (git-ignored raw caches excluded; snapshots kept).

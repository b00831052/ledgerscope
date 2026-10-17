-- Ledgerscope — BigQuery schema (DDL)
-- Dataset: ledgerscope   Location: recommend asia-southeast1 (Singapore)
-- Run once after authorizing the connector / setting your project.
--   bq --location=asia-southeast1 mk --dataset "${GCP_PROJECT}:ledgerscope"
-- Then execute this file:  bq query --use_legacy_sql=false < schema.sql

-- ============================================================
-- FACT: daily snapshot, one row per fund per day.
-- This is the proprietary time series. Protocols that later die
-- simply stop appearing in new partitions — their history stays.
-- Partitioned by date (cheap incremental loads + pruning),
-- clustered by class + slug for the common query paths.
-- ============================================================
CREATE TABLE IF NOT EXISTS `ledgerscope.rwa_snapshots` (
  snapshot_date        DATE      NOT NULL,
  generated_ts         TIMESTAMP,
  slug                 STRING    NOT NULL,
  name                 STRING,
  symbol               STRING,
  cls                  STRING,
  tvl                  FLOAT64,
  chg1d                FLOAT64,
  chg7d                FLOAT64,
  chains               ARRAY<STRING>,
  listed_at            INT64,
  manager              STRING,
  apac                 STRING,
  -- LS Score (quality/risk)
  ls                   INT64,
  ls_band              STRING,
  ls_stress            BOOL,
  ls_size              FLOAT64,
  ls_stability         FLOAT64,
  ls_resil             FLOAT64,
  -- yield / signal NAV gap
  apy                  FLOAT64,
  sigma                FLOAT64,
  rf                   FLOAT64,
  fair_signal          FLOAT64,
  gap_signal_bps       INT64,
  verdict_signal       STRING,
  -- fundamental valuation
  fv_rating            STRING,
  fv_seniority         STRING,
  fv_liquidity         STRING,
  fv_manager_tier      INT64,
  fv_req               FLOAT64,
  fv_gap_bps           INT64,
  fv_verdict           STRING,
  fv_conf              STRING,
  fv_jurisdiction      STRING,
  -- unified + peer-relative
  gap_unified_bps      INT64,
  gap_unified_src      STRING,
  gap_unified_verdict  STRING,
  rel_pctile           INT64,
  rel_z                FLOAT64,
  rel_rv               STRING,
  rel_peer_med         INT64
)
PARTITION BY snapshot_date
CLUSTER BY cls, slug
OPTIONS (description = "Ledgerscope daily RWA fund snapshots — proprietary survivorship-free time series.");

-- ============================================================
-- VIEW: latest snapshot (what the terminal reads for "today").
-- ============================================================
CREATE OR REPLACE VIEW `ledgerscope.rwa_latest` AS
SELECT * EXCEPT(rn) FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY slug ORDER BY snapshot_date DESC) rn
  FROM `ledgerscope.rwa_snapshots`
) WHERE rn = 1;

-- ============================================================
-- VIEW: survivorship-FREE class history (replaces the /protocol
-- fetch). Includes every protocol ever snapshotted, even dead ones.
-- ============================================================
CREATE OR REPLACE VIEW `ledgerscope.class_history` AS
SELECT snapshot_date, cls, SUM(tvl) AS tvl, COUNT(*) AS n_funds
FROM `ledgerscope.rwa_snapshots`
GROUP BY snapshot_date, cls
ORDER BY snapshot_date, cls;

-- ============================================================
-- VIEW: rating / verdict migration (a fund's trajectory over time).
-- The kind of analysis DefiLlama re-fetch can never reconstruct.
-- ============================================================
CREATE OR REPLACE VIEW `ledgerscope.fund_trajectory` AS
SELECT
  slug, name, cls, snapshot_date,
  tvl, ls, ls_band, gap_unified_bps, gap_unified_verdict, rel_pctile, rel_rv,
  LAG(ls_band)             OVER w AS prev_ls_band,
  LAG(gap_unified_verdict) OVER w AS prev_verdict
FROM `ledgerscope.rwa_snapshots`
WINDOW w AS (PARTITION BY slug ORDER BY snapshot_date);

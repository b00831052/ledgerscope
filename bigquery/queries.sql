-- Ledgerscope — example analytics on the warehouse.
-- These are the queries the terminal / research will run once snapshots accumulate.
-- Run via the BigQuery connector (data:sql-queries skill) or `bq query`.

-- 1) Survivorship-FREE class history (replaces the /protocol fetch, no bias)
SELECT snapshot_date, cls, ROUND(tvl/1e9, 3) AS tvl_bn, n_funds
FROM `ledgerscope.class_history`
WHERE cls = 'Private credit'
ORDER BY snapshot_date;

-- 2) Private-debt funds today, by peer-relative value (best value first)
SELECT name, symbol, ROUND(tvl/1e6,1) AS tvl_m, ls, fv_rating,
       gap_unified_bps, gap_unified_verdict, rel_pctile, rel_rv
FROM `ledgerscope.rwa_latest`
WHERE cls = 'Private credit' AND gap_unified_bps IS NOT NULL
ORDER BY rel_pctile DESC;

-- 3) Verdict migration — funds whose rating band or verdict CHANGED vs prior snapshot
SELECT snapshot_date, name, prev_ls_band, ls_band, prev_verdict, gap_unified_verdict
FROM `ledgerscope.fund_trajectory`
WHERE (prev_ls_band IS NOT NULL AND prev_ls_band != ls_band)
   OR (prev_verdict IS NOT NULL AND prev_verdict != gap_unified_verdict)
ORDER BY snapshot_date DESC, name;

-- 4) Concentration over time — top-fund share of private credit each day
WITH d AS (
  SELECT snapshot_date, name, tvl,
         SUM(tvl) OVER (PARTITION BY snapshot_date) AS day_total
  FROM `ledgerscope.rwa_snapshots` WHERE cls = 'Private credit')
SELECT snapshot_date, name AS top_fund,
       ROUND(MAX(tvl)/ANY_VALUE(day_total)*100, 1) AS top_share_pct
FROM d GROUP BY snapshot_date, name
QUALIFY tvl = MAX(tvl) OVER (PARTITION BY snapshot_date)
ORDER BY snapshot_date DESC;

-- 5) Stress episodes ever recorded (the alert log, historised)
SELECT snapshot_date, name, cls, chg7d, ls, gap_unified_bps
FROM `ledgerscope.rwa_snapshots`
WHERE ls_stress = TRUE
ORDER BY snapshot_date DESC, chg7d ASC;

-- 6) APAC private-debt book over time (the relocalisation thesis, tracked)
SELECT snapshot_date, ROUND(SUM(tvl)/1e6,1) AS apac_tvl_m, COUNT(*) AS n
FROM `ledgerscope.rwa_snapshots`
WHERE apac IS NOT NULL
GROUP BY snapshot_date ORDER BY snapshot_date;

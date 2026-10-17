#!/bin/bash
# Ledgerscope — load accumulated daily snapshots into BigQuery.
# Prerequisites (one-time): authorize the BigQuery connector (claude.ai settings)
#   OR install gcloud/bq CLI and `gcloud auth login`; then set GCP_PROJECT.
# Usage:
#   export GCP_PROJECT=your-project-id
#   ./bigquery/load.sh            # loads any snapshot not yet loaded
#   ./bigquery/load.sh --all      # reloads every snapshot (idempotent: WRITE_TRUNCATE per partition)
set -euo pipefail
cd "$(dirname "$0")/.."
: "${GCP_PROJECT:?set GCP_PROJECT to your Google Cloud project id}"
DS="${GCP_PROJECT}:ledgerscope"
LOC="${BQ_LOCATION:-asia-southeast1}"
TABLE="${DS}.rwa_snapshots"

command -v bq >/dev/null || { echo "✗ bq CLI not found. Install Google Cloud SDK, then gcloud auth login."; exit 1; }

# ensure dataset + schema exist
bq --location="$LOC" mk -f --dataset "$DS" >/dev/null 2>&1 || true
bq --location="$LOC" query --use_legacy_sql=false < bigquery/schema.sql >/dev/null

loaded_marker="snapshots/.loaded"
touch "$loaded_marker"
shopt -s nullglob
for f in snapshots/rwa_*.ndjson; do
  date=$(basename "$f" .ndjson | sed 's/rwa_//')
  if [ "${1:-}" != "--all" ] && grep -qx "$date" "$loaded_marker"; then
    echo "· $date already loaded — skip"; continue
  fi
  echo "→ loading $date …"
  # WRITE_TRUNCATE on the specific date partition = idempotent re-loads
  # table schema is already defined by schema.sql; bq uses it for the partition load
  bq --location="$LOC" load \
     --source_format=NEWLINE_DELIMITED_JSON \
     --replace \
     "${TABLE}\$${date//-/}" \
     "$f"
  grep -qx "$date" "$loaded_marker" || echo "$date" >> "$loaded_marker"
done
echo "✓ done. Query: bq query --use_legacy_sql=false 'SELECT * FROM \`${DS}.rwa_latest\` LIMIT 20'"

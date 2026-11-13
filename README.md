# Ledgerscope

**Independent ratings for tokenized private credit and real-world-asset funds.** By RWA Credit Intelligence, Singapore.

Live site: https://b00831052.github.io/ledgerscope/

## What it does

A daily pipeline reads public data (CoinGecko fund values, DefiLlama platform values and yields, on-chain contract state), classifies every tokenized fund by asset class, and publishes four proprietary layers:

- **LS Score (0-100):** quality and risk from observable on-chain signals (size, value stability, network resilience), with a redemption-stress flag.
- **NAV gap:** offered yield vs the yield the fund's risk requires, with guards for unobserved and unverified yields.
- **Key Risk:** who can upgrade, mint, pause or freeze each fund token, read from the chain.
- **Track record:** every grade frozen daily in a hash-chained public ledger, scored against what happened next.

Full method and limits: [METHODOLOGY.md](METHODOLOGY.md).

## Data

- `data.json`: the full daily dataset behind the site.
- `snapshots/rwa_YYYY-MM-DD.ndjson`: one row per asset per day (no survivorship: dead funds stay in old snapshots).
- `snapshots/ratings_ledger.ndjson`: the hash-chained ratings ledger.
- `snapshots/keyrisk_YYYY-MM-DD.ndjson`: daily contract-control grades.

## Run locally

```bash
python3 build.py
```

Writes `data.json`, `index.html` and the daily snapshots. No API keys needed.

## Status

Independent research based on public data and proprietary models. Not investment advice, not a credit rating under any regulation.

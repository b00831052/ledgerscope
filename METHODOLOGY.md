# Ledgerscope Methodology

Ledgerscope by RWA Credit Intelligence. Version 3, 13 November 2026.

This document describes how every number on the Ledgerscope site is produced, the assumptions behind it, and its limits. The goal is reproducibility: a third party should be able to rebuild every figure from public data and this document.

## 1. Data sources

| Source | Use | Frequency |
|---|---|---|
| CoinGecko `/coins/markets` (asset-class categories) | Fund universe and value: market cap = units outstanding x NAV | Daily |
| CoinGecko `/coins/{id}` | Contract addresses per chain, homepage | Cached, new tokens resolved each run |
| CoinGecko `/coins/{id}/market_chart` | 12-month daily value history, top 40 funds | Daily |
| DefiLlama `/protocols` | Platforms with no priced token: Maple, Huma, OpenTrade, KAIO, RealT | Daily |
| DefiLlama yields `/pools` | Offered yield (APY) and yield volatility | Daily |
| Public RPC nodes | Contract control: EIP-1967 slots, Safe thresholds, timelock delays, roles | Daily |
| `fundamentals.json` | Curated rating, seniority, liquidity, manager tier, jurisdiction | Manual review |

Exclusions: registry-only records that are not freely transferable tokens (for example Figure HELOC) and tokens under $1M. A FDV fallback is used only for a curated list of flagship funds that CoinGecko reports with zero market cap (for example BENJI).

## 2. Asset classes

Each token takes the class of the first matching CoinGecko category, in this order: private credit, US Treasuries and money market funds, yield-bearing cash, non-US government debt, commodities, real estate, tokenized equity. Curated flagship funds are pinned to their class.

## 3. LS Score (0-100)

```
LS = 100 x (0.42 x size + 0.40 x stability + 0.18 x resilience)
size       = log10(value) / log10($2B), capped at 1
stability  = 1 - |7-day value change| / 25%, floored at 0 (0.5 if unknown)
resilience = number of networks / 3, capped at 1
```

Bands: Green 68+, Amber 48-67, Red under 48.
Stress flag: an income fund (Treasuries, credit, yield cash, government debt) loses 8% or more of its value in 7 days.

## 4. NAV gap (yield vs risk)

NAV gap (bps) = offered yield - required yield. RICH at -75 bps or lower, CHEAP at +150 bps or higher, otherwise fair.

Required yield, fundamental model (used when a fund is curated):

- Treasury and cash wrappers: risk-free + wrapper spread (AAA 0, AA 0.10, A 0.25, BBB 0.50, unrated 0.75) + liquidity (daily 0, monthly 0.10, quarterly 0.25, locked 0.50) + manager tier (-0.05 / 0 / +0.15), floored at risk-free - 0.25 (fees). The assets are T-bills, so the spread covers only issuer, operational and liquidity risk.
- Credit funds: risk-free + rating spread (AAA 0.8 to B 6.5, unrated 5.5) + seniority, liquidity and manager adjustments, floored at risk-free + 0.5.

Required yield, signal model (used when a fund is not curated):

- Treasury and cash wrappers: risk-free + 0.25 + (1 - LS/100) x 1.0 + yield volatility penalty (max 1.0).
- Credit funds: risk-free + 2.0 + (1 - LS/100) x 10.0 + yield volatility penalty (max 3.0).

Risk-free rate: median on-chain T-bill yield.

Guards:

- Yield under 0.5% on-chain is treated as unobserved (income accrues inside the NAV). No valuation call.
- A credit fund paying less than risk-free + 2% on-chain (risk-free + 0.5% for AAA/AA-rated credit) is marked unverified, not RICH. The gap is shown greyed out and raises no alert.

Peer-relative value: within each class with 4 or more valued funds, each fund's gap is ranked against its peers (percentile and z-score).

## 5. Loan books

- Maple (public GraphQL `api.maple.finance/v2/graphql`): every active open-term loan. Per pool: principal outstanding, loans, borrowers, top borrower's share, rate weighted by principal, collateral value (CoinGecko prices) / principal ("cover"), share of crypto collateral, and the crypto price fall that would bring cover to 1.0x: (collateral - principal) / crypto collateral. Maple's `defaultDate` field is the next payment deadline, not a default; an active loan past that deadline is flagged "past deadline".
- Centrifuge (public GraphQL `api.centrifuge.io`): token supply, NAV per share and pending redemption orders. Queue = pending shares / shares issued through Centrifuge (a fund can also have tokens on other platforms, so this is not the whole fund). A queue of 10% or more raises an alert.
- Alert weights: past deadline or impaired +3, redemption queue or cover under 1.2x +2, top borrower 50%+ of a $50M+ pool +0.7.

## 6. Key Risk (contract control)

For each fund token with an EVM contract: who can upgrade the code, and who holds mint, pause, freeze or blacklist powers. A Safe multisig with a meaningful threshold, or a timelock, counts as verifiable governance. A key held by a single address is not called unsafe, because institutions often use MPC custody that looks like one address on-chain. Its governance cannot be verified on-chain, so the grade is capped at C. This is a contract-level view only, not an assessment of the fund's assets.

## 7. Track record

- Ledger: every run writes each fund's LS score, band, stress flag, fundamental rating and key-risk grade to `snapshots/ratings_ledger.ndjson`. Each day's entries carry a SHA-256 hash of the previous day's hash plus that day's rows, and are committed to the public git repository. A past grade cannot be changed without breaking the chain.
- Outcome test: a "bad outcome" is a loss of 20% or more of the fund's value at any point in the next 30 days.
- Live scorecard: grades become scorable 30 days after they are issued. First live readout: 13 December 2026.
- Rating actions: every band change between consecutive daily ratings, counted from the first day the ledger stores score components (size, stability, resilience); changes caused only by newly discovered networks are excluded, plus a watch list (redemption stress, or LS down 10+ points in a week, funds of $5M+).
- Backtest: the same LS rules replayed every 14 days on 12 months of CoinGecko history. Labelled as a backtest, never as live.

## 8. Limits

- History covers funds that exist today (survivorship bias); backtest failure rates understate reality.
- Backtest uses today's network count for resilience.
- Value change mixes investor flows and NAV moves.
- On-chain yields can miss income that accrues off-chain or inside the NAV.
- Curated fundamentals are reviewed by hand and carry a confidence level (high / medium / low).
- Platforms without any public on-chain value (for example DigiFT today) are not covered.

## 9. Status

Independent research based on public data and proprietary models. Not investment advice, not an official valuation, not a credit rating under any regulation, not a solicitation.

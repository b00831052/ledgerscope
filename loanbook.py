"""
Loan-book module: looks INSIDE credit funds, not just at their market value.

Maple (public GraphQL api.maple.finance/v2/graphql): every active loan, its
borrower, rate, collateral, impairment/call status and on-chain payment deadline.
  -> per pool: outstanding, loans, borrowers, top-borrower share, weighted rate,
     collateral cover, collateral mix, crypto drop that would erase the cover,
     loans past their payment deadline.
Centrifuge (public GraphQL api.centrifuge.io): token supply, NAV per share and
pending redemption orders.
  -> per fund: redemption queue in $ and as % of the fund.

Field note: Maple's `defaultDate` is the loan's next payment deadline, not a
default. An active loan whose deadline has passed is reported as "past deadline".
"""
import json, time, urllib.request, urllib.error
from collections import defaultdict

UA = {"content-type": "application/json", "User-Agent": "ledgerscope/2.0"}
STABLE = {"USDC", "USDG", "USDT", "PYUSD", "USDtb", "aUSDT", "USDS", "DAI", "FDUSD", "RLUSD"}
CG_IDS = {"BTC": "bitcoin", "WBTC": "bitcoin", "cbBTC": "bitcoin", "ETH": "ethereum", "WETH": "ethereum",
          "stETH": "ethereum", "XRP": "ripple", "SOL": "solana",
          "USTB": "superstate-short-duration-us-government-securities-fund-ustb"}
# Centrifuge token symbol -> Ledgerscope asset slug
CFG_SLUG = {"JAAA": "janus-henderson-anemoy-aaa-clo-fund", "JTRSY": "janus-henderson-anemoy-treasury-fund",
            "ACRDX": "anemoy-tokenized-apollo-diversified-credit-fund"}


def _gql(url, query):
    req = urllib.request.Request(url, data=json.dumps({"query": query}).encode(), headers=UA)
    try:
        return json.load(urllib.request.urlopen(req, timeout=60))
    except Exception as e:
        print(f"  ! loanbook {url}: {e}")
        return {}


def _prices():
    ids = ",".join(sorted(set(CG_IDS.values())))
    try:
        req = urllib.request.Request(f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd",
                                     headers={"User-Agent": "ledgerscope/2.0"})
        p = json.load(urllib.request.urlopen(req, timeout=30))
    except Exception as e:
        print(f"  ! prices: {e}"); p = {}
    out = {s: 1.0 for s in STABLE}
    for sym, cid in CG_IDS.items():
        if cid in p: out[sym] = p[cid]["usd"]
    return out


def maple():
    loans, skip = [], 0
    while True:
        d = _gql("https://api.maple.finance/v2/graphql",
                 "{ openTermLoans(first:500, skip:%d, where:{state:Active}){ id principalOwed interestRate isImpaired "
                 "isCalled defaultDate fundingPool{ id name } borrower{ id } collateral{ asset assetAmount decimals } } }" % skip)
        rows = ((d.get("data") or {}).get("openTermLoans")) or []
        loans += rows
        if len(rows) < 500: break
        skip += 500
    if not loans: return None
    px, now = _prices(), time.time()
    P = defaultdict(lambda: {"out": 0.0, "n": 0, "borrowers": defaultdict(float), "rate_w": 0.0,
                             "coll": 0.0, "coll_crypto": 0.0, "mix": defaultdict(float), "unpriced": 0,
                             "late_n": 0, "late_amt": 0.0, "impaired": 0, "called": 0})
    for l in loans:
        p = P[l["fundingPool"]["name"]]
        amt = int(l["principalOwed"] or 0) / 1e6
        p["out"] += amt; p["n"] += 1
        p["borrowers"][l["borrower"]["id"]] += amt
        p["rate_w"] += amt * int(l["interestRate"] or 0) / 1e4
        c = l.get("collateral") or {}
        a = c.get("asset")
        if a:
            if a in px:
                v = int(c.get("assetAmount") or 0) / 10 ** int(c.get("decimals") or 0) * px[a]
                p["coll"] += v; p["mix"][a] += v
                if a not in STABLE and a != "USTB": p["coll_crypto"] += v
            else:
                p["unpriced"] += 1
        dd = int(l.get("defaultDate") or 0)
        if 0 < dd < now:
            p["late_n"] += 1; p["late_amt"] += amt
        p["impaired"] += bool(l.get("isImpaired")); p["called"] += bool(l.get("isCalled"))
    pools = []
    for name, p in P.items():
        if p["out"] < 1e6: continue
        cover = p["coll"] / p["out"] if p["out"] else None
        safe = p["coll"] - p["coll_crypto"]
        drop = ((p["coll"] - p["out"]) / p["coll_crypto"]) if p["coll_crypto"] > 0 else None
        top = max(p["borrowers"].values()) if p["borrowers"] else 0
        pools.append({"pool": name, "outstanding": round(p["out"]), "loans": p["n"], "borrowers": len(p["borrowers"]),
                      "top_borrower_pct": round(100 * top / p["out"]), "rate": round(p["rate_w"] / p["out"], 2),
                      "collateral": round(p["coll"]), "cover": round(cover, 2) if cover is not None else None,
                      "crypto_pct": round(100 * p["coll_crypto"] / p["coll"]) if p["coll"] else 0,
                      "crypto_drop_to_1x": round(100 * drop) if drop is not None else None,
                      "mix": {k: round(100 * v / p["coll"]) for k, v in sorted(p["mix"].items(), key=lambda t: -t[1])[:4]} if p["coll"] else {},
                      "unpriced": p["unpriced"], "late_n": p["late_n"], "late_amt": round(p["late_amt"]),
                      "impaired": p["impaired"], "called": p["called"]})
    pools.sort(key=lambda x: -x["outstanding"])
    tot = sum(x["outstanding"] for x in pools); coll = sum(x["collateral"] for x in pools)
    return {"pools": pools, "outstanding": tot, "loans": sum(x["loans"] for x in pools),
            "cover": round(coll / tot, 2) if tot else None,
            "late_n": sum(x["late_n"] for x in pools), "late_amt": sum(x["late_amt"] for x in pools),
            "impaired": sum(x["impaired"] for x in pools), "prices": {k: px[k] for k in ("BTC", "ETH", "XRP") if k in px}}


def centrifuge():
    d = _gql("https://api.centrifuge.io",
             "{ tokens(limit:200){ items{ id name symbol decimals totalIssuance tokenPrice isActive } } "
             "pendingRedeemOrders(limit:1000){ items{ tokenId pendingSharesAmount queuedSharesAmount updatedAt } } }")
    data = d.get("data") or {}
    toks = {t["id"]: t for t in ((data.get("tokens") or {}).get("items") or [])}
    q = defaultdict(float)
    for o in ((data.get("pendingRedeemOrders") or {}).get("items") or []):
        t = toks.get(o["tokenId"])
        if t: q[o["tokenId"]] += (int(o["pendingSharesAmount"] or 0) + int(o["queuedSharesAmount"] or 0)) / 10 ** int(t["decimals"])
    funds = []
    for tid, t in toks.items():
        sup = int(t["totalIssuance"] or 0) / 10 ** int(t["decimals"]); pr = int(t["tokenPrice"] or 0) / 1e18
        val = sup * pr
        if val < 1e6 or "test" in (t["name"] or "").lower(): continue
        qs = q.get(tid, 0.0)
        funds.append({"symbol": t["symbol"], "name": t["name"], "slug": CFG_SLUG.get(t["symbol"]),
                      "value": round(val), "nav_per_share": round(pr, 4),
                      "queue_usd": round(qs * pr), "queue_pct": round(100 * qs / sup, 1) if sup else 0.0})
    funds.sort(key=lambda x: -x["value"])
    return {"funds": funds}


def run():
    print("→ Loan books (Maple loans, Centrifuge redemption queues) …")
    m, c = maple(), centrifuge()
    if m:
        print(f"  Maple: {m['loans']} active loans · ${m['outstanding']/1e9:.2f}B out · cover {m['cover']}x · "
              f"{m['late_n']} past deadline (${m['late_amt']/1e6:.1f}M) · {m['impaired']} impaired")
    if c:
        top = max(c["funds"], key=lambda f: f["queue_pct"], default=None)
        print(f"  Centrifuge: {len(c['funds'])} funds · largest queue {top['symbol']} {top['queue_pct']}%" if top else "  Centrifuge: no funds")
    return {"maple": m, "centrifuge": c, "as_of": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}


def flags_for(lb):
    """slug -> list of credit flags, fed into alerts and the fund profile."""
    out = defaultdict(list)
    m = (lb or {}).get("maple")
    if m:
        for p in m["pools"]:
            if p["late_n"]: out["proto-maple"].append(f"{p['pool']}: {p['late_n']} loan(s) past payment deadline (${p['late_amt']/1e6:.1f}M)")
            if p["impaired"]: out["proto-maple"].append(f"{p['pool']}: {p['impaired']} impaired loan(s)")
            if p["cover"] is not None and p["collateral"] and p["cover"] < 1.2: out["proto-maple"].append(f"{p['pool']}: collateral cover {p['cover']}x (under 1.2x)")
            if p["top_borrower_pct"] >= 50 and p["outstanding"] >= 50e6: out["proto-maple"].append(f"{p['pool']}: top borrower {p['top_borrower_pct']}% of loans")
    for f in ((lb or {}).get("centrifuge") or {}).get("funds", []):
        if f["slug"] and f["queue_pct"] >= 10:
            out[f["slug"]].append(f"Redemption queue {f['queue_pct']}% of Centrifuge-issued shares (${f['queue_usd']/1e6:.1f}M waiting)")
    return dict(out)

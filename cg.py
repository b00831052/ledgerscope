"""
Ledgerscope data layer v2: CoinGecko (free) replaces DefiLlama protocol TVL.

Why: DefiLlama moved RWA values out of protocol TVL (Nov 2026) into a paid
Pro dataset. CoinGecko publishes every tokenized fund with its market cap
(= units outstanding x NAV) under precise asset-class categories.

Output: a list of "raw" records shaped like the old DefiLlama protocol objects,
so the rest of the engine (classification, LS Score, NAV gap, key risk) is unchanged.
"""
import json, os, time, datetime, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
REG = os.path.join(HERE, "cg_registry.json")
HIST = os.path.join(HERE, "cg_history.json")
CG = "https://api.coingecko.com/api/v3"

# asset class -> CoinGecko categories, in precedence order (first match wins)
CLASS_CATS = [
    ("Private credit", ["tokenized-private-credit", "tokenized-credit"]),
    ("U.S. Treasuries", ["tokenized-treasuries", "tokenized-t-bills", "tokenized-money-market-fund-mmfs"]),
    ("Cash / yield stablecoin", ["us-treasury-backed-stablecoin", "tokenized-bank-deposit"]),
    ("Non-US government debt", ["tokenized-non-us-government-securities"]),
    ("Commodities", ["tokenized-gold", "tokenized-commodities"]),
    ("Real estate", ["real-estate"]),
    ("Tokenized stocks / equity", ["tokenized-stock", "tokenized-exchange-traded-funds-etfs", "tokenized-pre-ipo-stocks"]),
]
# registry-only records, not freely transferable tokens: excluded by default (rwa.xyz "represented" logic)
REPRESENTED = {"figr_heloc"}
# flagship funds CoinGecko files outside the asset-class categories
PINNED = {
    "franklin-templeton-benji": "U.S. Treasuries", "openeden-tbill": "U.S. Treasuries", "vaneck-treasury-fund": "U.S. Treasuries",
    "apollo-diversified-credit-securitize-fund": "Private credit", "anemoy-tokenized-apollo-diversified-credit-fund": "Private credit",
    "hamilton-lane-senior-credit-opportunities-securitize-fund": "Private credit",
    "usdtb": "Cash / yield stablecoin", "frax-usd": "Cash / yield stablecoin", "usual-usd": "Cash / yield stablecoin",
}
MIN_MCAP = 1_000_000
HISTORY_TOP = 40          # funds with full 12-month chart (rate-limit budget)
RESOLVE_PER_RUN = 25      # new contract-address lookups per run

_last = [0.0]
def cg_get(path, tries=5):
    """Paced CoinGecko call: >=7s apart, backs off on 429."""
    for i in range(tries):
        wait = 7.0 - (time.time() - _last[0])
        if wait > 0: time.sleep(wait)
        _last[0] = time.time()
        try:
            req = urllib.request.Request(CG + path, headers={"User-Agent": "ledgerscope/2.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(65 * (i + 1)); continue
            return None
        except Exception:
            time.sleep(5)
    return None

def _load(p, d):
    try: return json.load(open(p))
    except Exception: return d

def value(x):
    """Market cap. FDV fallback ONLY for curated pinned funds (all units outstanding, issuer verified):
    category tokens with mcap 0 and a big FDV are typically junk (e.g. fake 'gold' coins with $100B+ FDV)."""
    if x.get("market_cap"): return x["market_cap"]
    return (x.get("fully_diluted_valuation") or 0) if x.get("id") in PINNED else 0

def fetch_universe():
    seen = {}
    for cls, cats in CLASS_CATS:
        for cat in cats:
            rows = cg_get(f"/coins/markets?vs_currency=usd&category={cat}&per_page=250&page=1")
            if not isinstance(rows, list):
                print(f"  ! {cat}: no data"); continue
            n = 0
            for x in rows:
                if x["id"] in seen or (x.get("symbol") or "").lower() in REPRESENTED: continue
                if value(x) < MIN_MCAP: continue
                seen[x["id"]] = {**x, "_cls": cls}; n += 1
            print(f"  {cat}: +{n}")
    miss = [i for i in PINNED if i not in seen]
    if miss:
        rows = cg_get(f"/coins/markets?vs_currency=usd&ids={','.join(miss)}&per_page=250")
        for x in rows if isinstance(rows, list) else []:
            if value(x) >= MIN_MCAP: seen[x["id"]] = {**x, "_cls": PINNED[x["id"]]}
        print(f"  pinned flagships: +{sum(1 for i in miss if i in seen)}")
    return list(seen.values())

def resolve(universe):
    """Contract addresses + homepage per coin (cached forever, a few new per run)."""
    reg = _load(REG, {})
    today = datetime.date.today().isoformat()
    baseline = not reg
    for x in universe:
        e = reg.setdefault(x["id"], {"resolved": False})
        e.setdefault("first_seen", None if baseline else today)
    todo = [x for x in sorted(universe, key=lambda x: -value(x)) if not reg[x["id"]]["resolved"]][:RESOLVE_PER_RUN]
    for x in todo:
        r = cg_get(f"/coins/{x['id']}?localization=false&tickers=false&market_data=false&community_data=false&developer_data=false")
        if not isinstance(r, dict): continue
        reg[x["id"]].update({"resolved": True,
                             "platforms": {k: v for k, v in (r.get("platforms") or {}).items() if v and k},
                             "homepage": ((r.get("links") or {}).get("homepage") or [""])[0]})
    json.dump(reg, open(REG, "w"), indent=1, sort_keys=True)
    return reg

EVM_PREF = ["ethereum", "base", "arbitrum-one", "polygon-pos", "binance-smart-chain", "avalanche", "xdai", "zksync"]
CHAIN_LABEL = {"ethereum": "Ethereum", "base": "Base", "arbitrum-one": "Arbitrum", "polygon-pos": "Polygon",
               "binance-smart-chain": "BNB Chain", "avalanche": "Avalanche", "xdai": "Gnosis", "solana": "Solana",
               "stellar": "Stellar", "aptos": "Aptos", "sui": "Sui", "tron": "Tron", "ripple": "XRP Ledger",
               "algorand": "Algorand", "optimistic-ethereum": "Optimism", "plume-network": "Plume",
               "provenance-blockchain": "Provenance", "zksync": "zkSync", "linea": "Linea", "mantle": "Mantle"}

def history(universe):
    """12-month daily market-cap charts for the top funds, cached 1 day."""
    h = _load(HIST, {"fetched": {}, "series": {}})
    top = sorted(universe, key=lambda x: -value(x))[:HISTORY_TOP]
    today = datetime.date.today().isoformat()
    for x in top:
        if h["fetched"].get(x["id"]) == today: continue
        r = cg_get(f"/coins/{x['id']}/market_chart?vs_currency=usd&days=365&interval=daily")
        if isinstance(r, dict) and r.get("market_caps"):
            h["series"][x["id"]] = [[int(t / 1000), v] for t, v in r["market_caps"] if v]
            h["fetched"][x["id"]] = today
    json.dump(h, open(HIST, "w"))
    return h

def chg_7d(series):
    if not series or len(series) < 8: return None
    now, then = series[-1][1], series[-8][1]
    return (now / then - 1) * 100 if then else None

def raw_records():
    print("→ CoinGecko universe (asset-class categories) …")
    uni = fetch_universe()
    reg = resolve(uni)
    print("→ CoinGecko 12-month charts (top funds) …")
    hist = history(uni)
    out = []
    for x in uni:
        e = reg.get(x["id"], {})
        plats = e.get("platforms") or {}
        chains = [CHAIN_LABEL.get(c, c.replace("-", " ").title()) for c in plats] or []
        evm = sorted([(c, a) for c, a in plats.items() if c in EVM_PREF and str(a).startswith("0x")],
                     key=lambda t: EVM_PREF.index(t[0]))
        fs = e.get("first_seen")
        out.append({
            "category": "RWA", "_cls": x["_cls"],
            "slug": x["id"], "gecko_id": "", "name": x.get("name", ""), "symbol": (x.get("symbol") or "").upper(),
            "tvl": value(x), "chains": chains, "chainTvls": {},
            "change_1d": x.get("market_cap_change_percentage_24h"),
            "change_7d": chg_7d(hist["series"].get(x["id"])),
            "listedAt": int(datetime.datetime.fromisoformat(fs).timestamp()) if fs else None,
            "url": e.get("homepage") or "", "description": "",
            "address": f"{evm[0][0]}:{evm[0][1]}" if evm else "",
            "_platforms": plats,
        })
    print(f"  {len(out)} fund tokens · ${sum(r['tvl'] for r in out)/1e9:.2f}B · "
          f"{sum(1 for r in out if r['address'])} with EVM contract")
    return out, hist

def class_history(hist, records, months=12):
    """Monthly stacked value by class from cached charts (top funds)."""
    cls_of = {r["slug"]: r["_cls"] for r in records}
    today = datetime.date.today()
    ends = []
    for k in range(months):
        y, m = today.year, today.month - k
        while m <= 0: m += 12; y -= 1
        last = (datetime.date(y + (m == 12), (m % 12) + 1, 1) - datetime.timedelta(days=1)) if k else today
        ends.append(last)
    ends.reverse()
    acc = {}
    for cid, ser in hist["series"].items():
        c = cls_of.get(cid)
        if not c or not ser: continue
        row = acc.setdefault(c, [0.0] * len(ends))
        for i, d in enumerate(ends):
            ts = int(datetime.datetime(d.year, d.month, d.day).timestamp()) + 86399
            past = [v for t, v in ser if t <= ts]
            row[i] += past[-1] if past else 0.0
    ordered = sorted(acc.items(), key=lambda kv: -kv[1][-1])
    return {"labels": [d.strftime("%m/%y") for d in ends],
            "series": [{"cls": c, "values": v} for c, v in ordered],
            "note": f"Top {HISTORY_TOP} funds by value, CoinGecko market cap (units x NAV), month-end."}

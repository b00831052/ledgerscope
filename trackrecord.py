"""
Track record engine: turns grades into proof.

1. LEDGER (live, append-only): every run freezes each fund's grade in
   snapshots/ratings_ledger.ndjson. Each day is hash-chained (sha256 of the
   previous day's hash + today's rows) and committed to public git, so no grade
   can be rewritten after the fact.
2. LIVE SCORECARD: once a grade is 30+ days old, we check what happened next
   (30-day value change, worst drawdown) and aggregate by band.
3. BACKTEST: same LS Score rules replayed point-in-time on 12 months of
   CoinGecko market-cap history (top funds). Labelled as a backtest, never as live.
"""
import json, os, hashlib, datetime, statistics, math

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "snapshots", "ratings_ledger.ndjson")
INCOME = {"U.S. Treasuries", "Private credit", "Cash / yield stablecoin", "Non-US government debt"}
HORIZON = 30
DD_EVENT = -20.0      # "bad outcome" = value fell 20%+ at some point within 30 days


def ls_score(tvl, c7, nch):
    size = max(0.0, min(1.0, math.log10(max(tvl, 1)) / math.log10(2e9)))
    stab = max(0.0, 1 - abs(c7) / 25) if c7 is not None else 0.5
    resil = min(1.0, (nch or 1) / 3)
    ls = round(100 * (0.42 * size + 0.40 * stab + 0.18 * resil))
    return ls, ("green" if ls >= 68 else "amber" if ls >= 48 else "red")


# ---------------------------------------------------------------- ledger
def _read_ledger():
    if not os.path.exists(LEDGER): return []
    return [json.loads(l) for l in open(LEDGER, encoding="utf-8") if l.strip()]

def append_ledger(ds):
    rows = _read_ledger()
    date = ds["generated"][:10]
    if any(r["date"] == date for r in rows): return rows
    prev = rows[-1]["chain_hash"] if rows else "genesis"
    kr = {k["slug"]: k.get("grade") for k in ds.get("keyrisk", []) if k.get("slug")}
    new = []
    for a in ds["assets"]:
        s = a.get("sig") or {}
        new.append({"date": date, "slug": a["slug"], "name": a["name"], "symbol": a.get("symbol"),
                    "cls": a["cls"], "tvl": round(a["tvl"]), "ls": s.get("ls"), "band": s.get("band"),
                    "stress": bool(s.get("stress")), "size": s.get("size"), "stab": s.get("stability"),
                    "resil": s.get("resil"), "fv_rating": (a.get("fv") or {}).get("rating"),
                    "key_grade": kr.get(a["slug"])})
    body = json.dumps(new, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha256((prev + body).encode()).hexdigest()
    with open(LEDGER, "a", encoding="utf-8") as f:
        for r in new:
            f.write(json.dumps({**r, "chain_hash": h}, ensure_ascii=False) + "\n")
    print(f"→ ratings ledger {date}: {len(new)} grades frozen · hash {h[:12]}")
    return rows + [{**r, "chain_hash": h} for r in new]


# ---------------------------------------------------------------- outcomes
def _at(ser, ts):
    past = [v for t, v in ser if t <= ts]
    return past[-1] if past else None

def _fwd(ser, ts, days=HORIZON):
    end = ts + days * 86400
    win = [v for t, v in ser if ts < t <= end]
    v0 = _at(ser, ts)
    if not v0 or not win or ser[-1][0] < end: return None
    return {"chg": (win[-1] / v0 - 1) * 100, "dd": (min(win) / v0 - 1) * 100}

def _agg(obs):
    out = []
    for band in ("green", "amber", "red"):
        xs = [o for o in obs if o["band"] == band]
        if not xs: out.append({"band": band, "n": 0}); continue
        out.append({"band": band, "n": len(xs),
                    "med_chg": round(statistics.median(o["chg"] for o in xs), 1),
                    "med_dd": round(statistics.median(o["dd"] for o in xs), 1),
                    "hit_dd": round(100 * sum(o["dd"] <= DD_EVENT for o in xs) / len(xs))})
    return out

def backtest(hist, assets):
    meta = {a["slug"]: a for a in assets}
    obs, stress = [], []
    for cid, ser in hist.get("series", {}).items():
        a = meta.get(cid)
        if not a or len(ser) < 60: continue
        nch = len(a.get("chains") or [])
        t0, t_end = ser[0][0] + 8 * 86400, ser[-1][0] - HORIZON * 86400
        t = t0
        while t <= t_end:                         # one rating every 14 days
            v, v7 = _at(ser, t), _at(ser, t - 7 * 86400)
            if v and v7 and v >= 1e6:
                c7 = (v / v7 - 1) * 100
                ls, band = ls_score(v, c7, nch)
                f = _fwd(ser, t)
                if f:
                    o = {"band": band, **f}
                    obs.append(o)
                    if a["cls"] in INCOME:
                        stress.append({"flag": c7 <= -8, **f})
            t += 14 * 86400
    fl = [s for s in stress if s["flag"]]; nf = [s for s in stress if not s["flag"]]
    def med(xs, k): return round(statistics.median(x[k] for x in xs), 1) if xs else None
    return {"n": len(obs), "funds": sum(1 for c in hist.get("series", {}) if c in meta),
            "bands": _agg(obs),
            "stress": {"n_flag": len(fl), "n_clean": len(nf),
                       "flag_med_chg": med(fl, "chg"), "clean_med_chg": med(nf, "chg"),
                       "flag_hit": round(100 * sum(s["dd"] <= DD_EVENT for s in fl) / len(fl)) if fl else None,
                       "clean_hit": round(100 * sum(s["dd"] <= DD_EVENT for s in nf) / len(nf)) if nf else None}}

def live_scorecard(rows, hist):
    """Grades from the ledger that are 30+ days old, scored against what happened next."""
    ser = hist.get("series", {})
    today = datetime.date.today()
    obs = []
    for r in rows:
        d = datetime.date.fromisoformat(r["date"])
        if (today - d).days < HORIZON or r["slug"] not in ser: continue
        ts = int(datetime.datetime(d.year, d.month, d.day).timestamp()) + 86399
        f = _fwd(ser[r["slug"]], ts)
        if f: obs.append({"band": r["band"], **f})
    dates = sorted({r["date"] for r in rows})
    first = dates[0] if dates else today.isoformat()
    ready = (datetime.date.fromisoformat(first) + datetime.timedelta(days=HORIZON)).isoformat()
    return {"since": first, "days": len(dates), "grades": len(rows), "scored": len(obs),
            "first_readout": ready, "bands": _agg(obs) if obs else [],
            "head_hash": rows[-1]["chain_hash"] if rows else None}

def run(ds, hist):
    rows = append_ledger(ds)
    bt = backtest(hist, ds["assets"])
    lv = live_scorecard(rows, hist)
    g = {b["band"]: b for b in bt["bands"]}
    print(f"  backtest: {bt['n']} point-in-time grades on {bt['funds']} funds · "
          f"30d drawdown≥20%: green {g['green'].get('hit_dd')}% / amber {g['amber'].get('hit_dd')}% / red {g['red'].get('hit_dd')}%")
    print(f"  live: {lv['grades']} grades over {lv['days']} day(s), first 30d readout {lv['first_readout']}")
    ac = actions(rows)
    print(f"  rating actions: {len(ac['actions'])} band changes over {ac['dates']} day(s) · watch list {len(ac['watch'])}")
    return {"horizon": HORIZON, "dd_event": DD_EVENT, "backtest": bt, "live": lv, "ratings": ac}


# ---------------------------------------------------------------- grade history
def actions(rows, keep_days=120):
    """Per-fund grade history + rating actions (band changes) + watch list, from the ledger."""
    by = {}
    for r in rows:
        by.setdefault(r["slug"], []).append(r)
    dates = sorted({r["date"] for r in rows})
    hist, acts = {}, []
    order = {"red": 0, "amber": 1, "green": 2}
    for slug, rs in by.items():
        rs.sort(key=lambda r: r["date"])
        hist[slug] = [[r["date"], r["ls"], r["band"]] for r in rs][-keep_days:]
        for a, b in zip(rs, rs[1:]):
            # a rating action must come from the fund, not from our data coverage: skip pairs without
            # components, and band changes explained only by newly discovered networks (resilience)
            if a["band"] != b["band"] and a.get("resil") is not None and b.get("resil") is not None:
                core = lambda r: 0.42 * (r["size"] or 0) + 0.40 * (r["stab"] or 0)
                if abs(core(b) - core(a)) * 100 < 3 and a["resil"] != b["resil"]:
                    continue
                acts.append({"date": b["date"], "slug": slug, "name": b["name"], "cls": b["cls"],
                             "from": a["band"], "to": b["band"], "ls_from": a["ls"], "ls_to": b["ls"],
                             "kind": "upgrade" if order[b["band"]] > order[a["band"]] else "downgrade",
                             "tvl": b["tvl"]})
    acts.sort(key=lambda x: (x["date"], -x["tvl"]), reverse=True)
    # watch list: latest grade has stress, or LS fell 10+ points vs 7 grades ago
    watch = []
    for slug, rs in by.items():
        last = rs[-1]
        prev = rs[-8] if len(rs) >= 8 else rs[0]
        why = []
        if last.get("stress"): why.append("redemption stress")
        if prev is not last and (prev["ls"] or 0) - (last["ls"] or 0) >= 10: why.append(f"LS down {prev['ls'] - last['ls']} pts")
        if why and last["tvl"] >= 5e6:
            watch.append({"slug": slug, "name": last["name"], "cls": last["cls"], "ls": last["ls"],
                          "band": last["band"], "tvl": last["tvl"], "why": why})
    watch.sort(key=lambda x: -x["tvl"])
    comp = sorted({r["date"] for r in rows if r.get("resil") is not None})
    return {"dates": len(dates), "since": comp[0] if comp else None, "first": dates[0] if dates else None, "last": dates[-1] if dates else None,
            "actions": acts[:200], "watch": watch, "hist": hist}

#!/usr/bin/env python3
"""
Ledgerscope — pipeline de données RWA (étape 1 : vraie donnée on-chain).
Source : DefiLlama public API (gratuit, sans clé).
Récupère les protocoles RWA, les classe par classe d'actifs, calcule les
agrégats, et génère un terminal HTML autonome avec la donnée réelle bakée.

Usage:  python3 build.py
Sortie: data.json  +  terminal.html
"""
import json, os, time, urllib.request, datetime, html

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.llama.fi/protocols"
POOLS_API = "https://yields.llama.fi/pools"

# ---------- 1. FETCH ----------
def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ledgerscope/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def fetch():
    print("→ Fetch DefiLlama /protocols …")
    data = _get(API)
    print(f"  {len(data)} protocoles reçus")
    return data

def fetch_stables():
    print("→ Fetch DefiLlama /stablecoins …")
    try:
        d = _get("https://stablecoins.llama.fi/stablecoins?includePrices=false")
        arr = d.get("peggedAssets", d)
        tot = 0.0
        for a in arr:
            c = a.get("circulating", {})
            tot += (c.get("peggedUSD", 0) if isinstance(c, dict) else 0) or 0
        print(f"  stablecoins total ${tot/1e9:.1f}B")
        return tot, len(arr)
    except Exception as e:
        print("  ⚠ stablecoins indisponibles:", e)
        return 0, 0

def fetch_pools():
    print("→ Fetch DefiLlama /pools (rendements) …")
    try:
        d = _get(POOLS_API)
        pools = d.get("data", d) if isinstance(d, dict) else d
        print(f"  {len(pools)} pools reçus")
        return pools
    except Exception as e:
        print("  ⚠ pools indisponibles:", e)
        return []

import datetime as _dt
def month_ends(n=28):
    """n derniers fins-de-mois (unix), du plus ancien au plus récent."""
    today = _dt.date.today()
    y, m = today.year, today.month
    outs = []
    for k in range(n):
        yy, mm = y, m - k
        while mm <= 0:
            mm += 12; yy -= 1
        # dernier jour du mois
        if mm == 12:
            last = _dt.date(yy, 12, 31)
        else:
            last = _dt.date(yy, mm+1, 1) - _dt.timedelta(days=1)
        outs.append(last)
    outs.reverse()
    return [(d, int(_dt.datetime(d.year,d.month,d.day).timestamp())) for d in outs]

def fetch_history(assets, min_tvl=10e6, cap=55):
    """Série temporelle réelle de TVL par classe, via /protocol/{slug} de DefiLlama.
    On agrège les gros protocoles (couvrent >95% de la TVL) par mois et par classe."""
    sel = [a for a in assets if a["tvl"] >= min_tvl and a.get("slug")][:cap]
    print(f"→ Historique : fetch {len(sel)} protocoles (/protocol/slug) …")
    buckets = month_ends(28)
    labels = [d.strftime("%m/%y") for d, _ in buckets]
    # accumulateur : classe -> [valeur par mois]
    acc = {}
    ok = 0
    for a in sel:
        try:
            d = _get(f"https://api.llama.fi/protocol/{a['slug']}")
        except Exception:
            continue
        series = d.get("tvl") or []
        if not series:
            continue
        pts = sorted((p.get("date",0), p.get("totalLiquidityUSD",0) or 0) for p in series)
        cls = a["cls"]
        row = acc.setdefault(cls, [0.0]*len(buckets))
        j = 0
        for i, (_, ts) in enumerate(buckets):
            # dernière valeur connue <= fin de mois
            val = 0.0
            while j < len(pts) and pts[j][0] <= ts:
                val = pts[j][1]; j += 1
            # si on a dépassé, garder la dernière avant ts
            if j > 0:
                val = pts[j-1][1] if pts[j-1][0] <= ts else 0.0
            row[i] += val
        ok += 1
    print(f"  {ok} protocoles historisés · {len(labels)} mois")
    # trie les classes par valeur finale desc
    ordered = sorted(acc.items(), key=lambda kv: -kv[1][-1])
    return {"labels": labels, "series": [{"cls": c, "values": v} for c, v in ordered]}

# slugs de fonds monétaires / T-bills tokenisés → taux « sans risque » on-chain
TBILL_SLUGS = {"blackrock-buidl","circle-usyc","ondo-yield-assets","superstate",
               "openeden","franklin-onchain-us-government-money-fund","wisdomtree",
               "invesco","vaneck","hashnote","spiko","mountain-protocol"}

def build_yield_map(pools):
    """project -> {apy (pondéré TVL), sigma (vol de rendement), n}."""
    agg = {}
    for p in pools:
        proj = p.get("project"); apy = p.get("apy"); tvl = p.get("tvlUsd") or 0
        if not proj or apy is None or tvl <= 0:
            continue
        a = agg.setdefault(proj, {"wapy": 0.0, "wsig": 0.0, "tvl": 0.0, "n": 0})
        a["wapy"] += apy * tvl
        a["wsig"] += (p.get("sigma") or 0) * tvl
        a["tvl"] += tvl
        a["n"] += 1
    ymap = {}
    for proj, a in agg.items():
        if a["tvl"] > 0:
            ymap[proj] = {"apy": a["wapy"]/a["tvl"], "sigma": a["wsig"]/a["tvl"], "n": a["n"]}
    # taux sans risque on-chain = médiane des APY des T-bills tokenisés
    rf_vals = sorted(ymap[s]["apy"] for s in TBILL_SLUGS if s in ymap)
    rf = rf_vals[len(rf_vals)//2] if rf_vals else 4.0
    return ymap, rf

# ---------- 2. CLASSIFY ----------
# DefiLlama ne sous-classe pas les RWA. On utilise une LISTE BLANCHE par slug (curée
# à la main depuis les 124 protocoles réels) — bien plus fiable que les mots-clés.
# Le CRÉDIT PRIVÉ n'est attribué QUE par cette liste : zéro faux positif.
WHITELIST = {
  "Private credit": {
    "centrifuge-protocol","anemoy-capital","hastra","nest-credit",
    "securitize-tokenized-aaa-clo-fund","apollo-diversified-credit-securitize-fund",
    "hamilton-lane-senior-credit-opportunities","nawa-protocol","gaib","kaio",
    "kea-credit","zivoe","untangled-rwa","untangled-old","naos-finance",
    "tprotocol-v1","tprotocol-v2","defa-by-invoicemate","bondlink-finance",
    "byzanlink-rwa-markets","raac","elyfi","ztln-p","hiyield","clearpool-tpool",
  },
  "U.S. Treasuries": {
    "blackrock-buidl","circle-usyc","ondo-yield-assets","spiko","invesco-ustb",
    "wisdomtree","openeden-tbill","openeden-usdo","vaneck-treasury-fund","digift",
    "theo-network-thbill","matrixdock-stbt","sygnum-fiusd-liquidity-fund",
    "asseto-aoabt","asseto-cash+","fortunafi","arca-labs-arcoin","kuma-protocol",
    "midas-rwa","trucore","opentrade","sky-rwa","etherfuse","theo-network",
  },
  "Cash / yield stablecoin": {
    "frax-usd","usual-usd0","usual-eur0","ethena-usdtb","anzen-v1","anzen-v2",
    "stusdt","solayer-usd","international-stable-currency","wstgbp","usual",
  },
  "Commodities": {
    "tether-gold","paxos-gold","matrixdock-xaum","meld-gold","goldfinger","aurus",
    "comtech-gold","oro-finance","cache.gold","goldstation-rwa","gold-dao",
    "asa.gold","uranium.io","vnx","denario",
  },
  "Tokenized stocks / equity": {
    "ondo-global-markets","xstocks","blockchain-capital","backedfi","aktionariat",
    "vesta-equity",
  },
  "Real estate": {
    "realt-tokens","lofty","tangible-rwa","estate-protocol","landshare","subunit",
    "propbase","realtyx","binaryx-platform","landx-finance","chateau",
  },
  "Other (carbon/insurance/art)": {
    "re","onre","toucan-protocol","klimadao","newrlrwa",
    "cana-holdings-california-carbon-credits","liveart","frigg.eco","boson-protocol",
  },
}
SLUG2CLASS = {slug: cls for cls, slugs in WHITELIST.items() for slug in slugs}

# Gestionnaires d'actifs (curé) : slug -> maison de gestion. Pour les protocoles
# non listés, on retombe sur le nom du protocole (souvent son propre gestionnaire).
ASSET_MANAGERS = {
    "blackrock-buidl":"BlackRock","ondo-yield-assets":"Ondo Finance","ondo-global-markets":"Ondo Finance",
    "circle-usyc":"Circle","spiko":"Spiko","paxos-gold":"Paxos","tether-gold":"Tether",
    "centrifuge-protocol":"Centrifuge","anemoy-capital":"Anemoy","invesco-ustb":"Invesco",
    "wisdomtree":"WisdomTree","hastra":"Hastra","openeden-tbill":"OpenEden","openeden-usdo":"OpenEden",
    "vaneck-treasury-fund":"VanEck","digift":"DigiFT","securitize-tokenized-aaa-clo-fund":"Securitize",
    "apollo-diversified-credit-securitize-fund":"Apollo Global","hamilton-lane-senior-credit-opportunities":"Hamilton Lane",
    "matrixdock-xaum":"Matrixdock","matrixdock-stbt":"Matrixdock","nest-credit":"Nest Credit",
    "kaio":"Libre / KAIO","gaib":"GAIB","sygnum-fiusd-liquidity-fund":"Sygnum",
    "blockchain-capital":"Blockchain Capital","xstocks":"Backed / xStocks","re":"Re","onre":"OnRe",
}

# Émetteurs rattachés à l'APAC (domiciliation / régulateur asiatique) — la cible de
# relocalisation Singapour. Curé à la main ; le marché on-chain APAC est encore mince,
# c'est précisément la thèse : bâtir la couche data locale avant qu'il grossisse.
APAC_SLUGS = {
    "digift":               "Singapour (MAS, exchange RWA régulé)",
    "kaio":                 "Singapour / ADGM (ex-Libre Capital)",
    "matrixdock-xaum":      "Singapour (Matrixport)",
    "matrixdock-stbt":      "Singapour (Matrixport)",
    "openeden-tbill":       "Singapour (OpenEden)",
    "openeden-usdo":        "Singapour (OpenEden)",
    "asseto-aoabt":         "APAC (Asseto, money market CMS)",
    "asseto-cash+":         "APAC (Asseto)",
    "sygnum-fiusd-liquidity-fund": "Singapour/Suisse (Sygnum, hub SG)",
}

# Repli mots-clés pour les protocoles hors liste (jamais vers "Private credit").
FALLBACK = [
    ("U.S. Treasuries", ["tbill","t-bill","treasury","money market","gov secur"]),
    ("Commodities",     ["gold","silver","xaut","paxg","metal","uranium"]),
    ("Real estate",     ["real estate","real-estate","property","realty"]),
    ("Tokenized stocks / equity", ["stock","equity"]),
    ("Cash / yield stablecoin", ["stablecoin","digital dollar"]),
]
def classify(p):
    slug = p.get("slug","")
    if slug in SLUG2CLASS:
        return SLUG2CLASS[slug]
    hay = (p.get("name","") + " " + (p.get("description") or "")).lower()
    for cls, kws in FALLBACK:
        if any(k in hay for k in kws):
            return cls
    return "Other RWA"

# ---------- 2b. CREDIT SIGNALS (couche analytique propriétaire) ----------
# rwa.xyz s'arrête à la donnée brute. Ici on calcule un score de qualité/risque
# à partir des SEULS signaux on-chain observables (TVL, volatilité, momentum,
# résilience multi-chaîne). Transparent et honnête : c'est un score de SIGNAL,
# pas une valorisation fondamentale (qui exigerait la donnée off-chain du fonds).
import math
def credit_signals(a):
    tvl = a["tvl"]; c7 = a["chg7d"]; c1 = a["chg1d"]; nch = len(a["chains"]) or 1
    # 1. Taille : plus le fonds est gros, plus il est établi (échelle log, plafond 2 Md$)
    size = max(0.0, min(1.0, math.log10(max(tvl,1)) / math.log10(2e9)))
    # 2. Stabilité : faible volatilité hebdo = bon signe (>25%/sem = 0)
    vol = abs(c7) if c7 is not None else 0
    stability = max(0.0, 1 - vol/25)
    # 3. Résilience : diversification multi-chaîne (plafond 3)
    resil = min(1.0, nch/3)
    # 4. Composite
    ls = round(100 * (0.42*size + 0.40*stability + 0.18*resil))
    band = "green" if ls >= 68 else "amber" if ls >= 48 else "red"
    # 5. Stress flag : sortie nette marquée = pression de rachat / risque de survalorisation NAV
    stress = (c7 is not None and c7 <= -8)
    # 6. Commentaire auto
    bits = []
    bits.append("taille solide" if size>0.7 else "petite taille" if size<0.4 else "taille moyenne")
    bits.append("stable" if stability>0.7 else "volatil" if stability<0.4 else "volatilité modérée")
    if stress: bits.append("⚠ sorties nettes 7j")
    if nch>=3: bits.append("multi-chaîne")
    return {"ls": ls, "band": band, "stress": stress,
            "size": round(size,2), "stability": round(stability,2), "resil": round(resil,2),
            "note": ", ".join(bits)}

# ---------- 2c. MODÈLE FAIR-YIELD / NAV GAP ----------
# Cœur analytique étape 3. Idée : un prêt privé doit rémunérer son risque.
#   rendement_juste = taux_sans_risque + prime_exigée(risque)
#   prime_exigée     = 2% (base illiquidité) + (1 - LS/100) * 12%   [en points]
# NAV gap (bps) = (rendement_offert − rendement_juste) * 100
#   < 0  → l'investisseur est SOUS-payé pour le risque → token « cher », NAV probablement survalorisée.
#   > 0  → coussin de rendement au-dessus du risque → token « bon marché » ou risque caché à creuser.
def nav_gap(asset, ymap, rf):
    slug = asset.get("slug")
    y = ymap.get(slug)
    if not y:
        return None
    offered = y["apy"]
    ls = asset["sig"]["ls"]
    sigma = y["sigma"] or 0
    # prime exigée = base illiquidité + prime de risque (LS) + prime de volatilité de rendement
    vol_pen = min(3.0, sigma * 20)               # sigma 0.15 → +3 pts
    req_premium = 2.0 + (1 - ls/100) * 10.0 + vol_pen
    fair = rf + req_premium
    gap_bps = round((offered - fair) * 100)
    verdict = ("rich" if gap_bps <= -75 else "cheap" if gap_bps >= 150 else "fair")
    return {"apy": round(offered,2), "sigma": round(sigma,3), "volpen": round(vol_pen,2),
            "rf": round(rf,2), "fair": round(fair,2), "spread": round(offered-rf,2),
            "gap_bps": gap_bps, "verdict": verdict}

# ---------- 2d. VALORISATION FONDAMENTALE (étape 4) ----------
# Rendement requis à partir des fondamentaux CURÉS (fundamentals.json) — approche
# analyste crédit / agence, distincte du modèle de signal on-chain (étape 3).
#   requis = rf + base_illiquidité + spread_crédit(rating) + ajust(séniorité) + ajust(lockup) + ajust(manager)
# NAV gap fondamentale (bps) = (rendement_offert − requis) * 100.
# Modèle GÉNÉRALISÉ à toutes les classes (v2). Plus de base d'illiquidité fixe :
# elle est portée par la liquidité, pour être juste sur les classes liquides
# (T-bills daily) comme illiquides (crédit privé locked).
RATING_SPREAD = {"AAA":0.8,"AA":1.2,"A":1.8,"BBB":2.8,"BB":4.5,"B":6.5,"NR":5.5}  # points
SENIORITY_ADJ = {"senior_secured":-0.5,"senior":0.0,"asset_backed":0.0,
                 "subordinated":1.5,"unsecured":1.2,"first_loss":3.0,"physical":-0.3,"equity":2.5}
LIQUIDITY_ADJ = {"daily":0.0,"monthly":0.8,"quarterly":1.6,"locked":2.8}
MANAGER_ADJ   = {1:-0.6, 2:0.0, 3:1.2}

def fundamental_val(asset, fund, rf):
    f = fund.get(asset.get("slug",""))
    if not f:
        return None
    req = (rf
           + RATING_SPREAD.get(f.get("rating","NR"),5.5)
           + SENIORITY_ADJ.get(f.get("seniority","unsecured"),1.2)
           + LIQUIDITY_ADJ.get(f.get("liquidity","monthly"),0.8)
           + MANAGER_ADJ.get(f.get("manager_tier",3),1.2))
    yg = asset.get("yg")
    offered = yg["apy"] if yg else None
    gap_bps = round((offered - req)*100) if offered is not None else None
    verdict = None
    if gap_bps is not None:
        verdict = "rich" if gap_bps <= -75 else "cheap" if gap_bps >= 150 else "fair"
    return {"rating":f.get("rating"),"seniority":f.get("seniority"),"liquidity":f.get("liquidity"),
            "manager_tier":f.get("manager_tier"),"jurisdiction":f.get("jurisdiction"),
            "note":f.get("note"),"conf":f.get("conf","low"),
            "req":round(req,2),"offered":offered,"gap_bps":gap_bps,"verdict":verdict}

# ---------- 3. TRANSFORM ----------
def _managers(assets):
    agg = {}
    for a in assets:
        m = a["manager"]
        g = agg.setdefault(m, {"value":0.0,"n":0,"classes":set(),"chains":set()})
        g["value"] += a["tvl"]; g["n"] += 1
        g["classes"].add(a["cls"]); g["chains"].update(a["chains"])
    out = [{"name":m,"value":g["value"],"n":g["n"],
            "classes":sorted(g["classes"]),"nchains":len(g["chains"])}
           for m,g in agg.items()]
    return sorted(out, key=lambda x:-x["value"])

def build_dataset(raw, ymap, rf, fund):
    rwa = [p for p in raw if p.get("category") == "RWA"]
    assets = []
    netagg = {}   # réseau -> {value, n}
    for p in rwa:
        tvl = p.get("tvl") or 0
        if tvl <= 0:
            continue
        # agrégation par réseau (vraie valeur par chaîne via chainTvls)
        chs = p.get("chains", []) or []
        ct = p.get("chainTvls", {}) or {}
        for ch in chs:
            v = ct.get(ch)
            if v is None:
                v = tvl/len(chs) if chs else 0
            na = netagg.setdefault(ch, {"value":0.0,"n":0})
            na["value"] += v; na["n"] += 1
        assets.append({
            "name": p.get("name",""),
            "symbol": p.get("symbol","-") or "-",
            "slug": p.get("slug",""),
            "cls": classify(p),
            "chains": p.get("chains", []),
            "tvl": tvl,
            "chg7d": p.get("change_7d"),
            "chg1d": p.get("change_1d"),
            "listedAt": p.get("listedAt"),
            "url": p.get("url",""),
        })
    # couche analytique : score de signal crédit + modèle NAV gap + tag APAC
    for a in assets:
        a["sig"] = credit_signals(a)
        a["yg"] = nav_gap(a, ymap, rf)
        a["fv"] = fundamental_val(a, fund, rf)       # valo fondamentale (None si non curé)
        a["apac"] = APAC_SLUGS.get(a.get("slug"))   # None si hors APAC
        a["manager"] = ASSET_MANAGERS.get(a.get("slug"), a["name"])
        # NAV gap unifié : fondamental (cross-class, calibré) si dispo, sinon signal (LS)
        fv, yg = a.get("fv"), a.get("yg")
        if fv and fv.get("gap_bps") is not None:
            a["gapu"] = {"apy":fv["offered"],"fair":fv["req"],"gap_bps":fv["gap_bps"],
                         "verdict":fv["verdict"],"src":"fond."}
        elif yg:
            a["gapu"] = {"apy":yg["apy"],"fair":yg["fair"],"gap_bps":yg["gap_bps"],
                         "verdict":yg["verdict"],"src":"signal"}
        else:
            a["gapu"] = None
    # --- Valorisation RELATIVE aux pairs (dé-biaise le niveau absolu du modèle) ---
    # Pour chaque classe avec >=4 fonds notés, on situe le NAV gap de chaque fonds
    # dans la distribution de ses pairs (percentile + z-score). "rich/cheap" devient
    # alors relatif au marché, indépendant de la calibration absolue du fair-yield.
    import statistics as _st
    by_cls = {}
    for a in assets:
        if a.get("gapu"):
            by_cls.setdefault(a["cls"], []).append(a["gapu"]["gap_bps"])
    for a in assets:
        a["gaprel"] = None
        gu = a.get("gapu")
        if not gu:
            continue
        peers = by_cls.get(a["cls"], [])
        if len(peers) < 4:
            continue
        g = gu["gap_bps"]
        med = _st.median(peers)
        sd = _st.pstdev(peers) or 1
        pct = round(sum(1 for p in peers if p <= g) / len(peers) * 100)
        z = round((g - med) / sd, 2)
        rv = "cheap" if pct >= 75 else "rich" if pct <= 25 else "in-line"
        a["gaprel"] = {"pctile": pct, "z": z, "peer_med": round(med), "rv": rv, "n": len(peers)}
    assets.sort(key=lambda a: -a["tvl"])

    total = sum(a["tvl"] for a in assets)
    # by class
    byclass = {}
    for a in assets:
        byclass[a["cls"]] = byclass.get(a["cls"], 0) + a["tvl"]
    byclass = sorted(byclass.items(), key=lambda x: -x[1])
    # net flows 7d (approx: chg7d applied to tvl)
    flows = {}
    for a in assets:
        if a["chg7d"] is not None:
            prev = a["tvl"] / (1 + a["chg7d"]/100) if a["chg7d"] != -100 else 0
            flows[a["cls"]] = flows.get(a["cls"], 0) + (a["tvl"] - prev)
    flows = sorted(flows.items(), key=lambda x: -abs(x[1]))
    # private credit focus
    pc = [a for a in assets if a["cls"] == "Private credit"]
    pc_total = sum(a["tvl"] for a in pc)
    # recent (listedAt desc)
    recent = sorted([a for a in assets if a.get("listedAt")],
                    key=lambda a: -a["listedAt"])[:12]
    # qualité crédit agrégée (private credit)
    pc_bands = {"green":0,"amber":0,"red":0}
    for a in pc: pc_bands[a["sig"]["band"]] += 1
    pc_stress = [a["name"] for a in pc if a["sig"]["stress"]]
    pc_avg_ls = round(sum(a["sig"]["ls"] for a in pc)/len(pc)) if pc else 0
    # couverture rendement + verdicts NAV gap
    pc_yield = [a for a in pc if a.get("yg")]
    pc_rich = [a["name"] for a in pc_yield if a["yg"]["verdict"]=="rich"]
    pc_cheap = [a["name"] for a in pc_yield if a["yg"]["verdict"]=="cheap"]
    # ---- moteur d'alertes : synthèse actionnable, TOUTES CLASSES (tvl >= 20M) ----
    alerts = []
    for a in [x for x in assets if x["tvl"] >= 20e6]:
        sig = a["sig"]; yg = a.get("yg"); gu = a.get("gapu"); reasons = []; sev = 0.0
        if sig["stress"]:
            reasons.append(f"Sorties nettes 7j ({a['chg7d']:+.1f}%) — pression de rachat")
            sev += 3
        if gu and gu["gap_bps"] <= -75:
            reasons.append(f"Survalorisé ({gu['src']}) : offre {gu['apy']:.1f}% vs juste {gu['fair']:.1f}% ({gu['gap_bps']:+d} bps)")
            sev += min(4.0, abs(gu["gap_bps"])/120)
        if sig["band"] == "red":
            reasons.append(f"Score qualité faible ({sig['ls']}/100)")
            sev += 2
        if yg and (yg.get("sigma") or 0) >= 0.10:
            reasons.append(f"Rendement instable (σ={yg['sigma']:.2f})")
            sev += 1
        if gu and gu["verdict"] == "cheap":
            reasons.append(f"Rendement excédentaire ({gu['gap_bps']:+d} bps) — vérifier risque caché")
            sev += 0.8
        if reasons:
            level = "high" if sev >= 4 else "med" if sev >= 2 else "low"
            alerts.append({"name": a["name"], "symbol": a["symbol"], "tvl": a["tvl"],
                           "slug": a["slug"], "cls": a["cls"],
                           "ls": sig["ls"], "band": sig["band"], "level": level,
                           "sev": round(sev,1), "reasons": reasons})
    alerts.sort(key=lambda x: -x["sev"])

    return {
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source": "DefiLlama public API (live)",
        "n_assets": len(assets),
        "total_tvl": total,
        "pc_total": pc_total,
        "n_pc": len(pc),
        "byclass": byclass,
        "flows": flows,
        "assets": assets,
        "recent": recent,
        "pc_bands": pc_bands,
        "pc_stress": pc_stress,
        "pc_avg_ls": pc_avg_ls,
        "rf": round(rf,2),
        "pc_yield_n": len(pc_yield),
        "pc_rich": pc_rich,
        "pc_cheap": pc_cheap,
        "alerts": alerts,
        "apac_n": sum(1 for a in assets if a["apac"]),
        "apac_tvl": sum(a["tvl"] for a in assets if a["apac"]),
        "fv_n": sum(1 for a in pc if a.get("fv")),
        "networks": sorted([{"chain":k,"value":v["value"],"n":v["n"]} for k,v in netagg.items()],
                           key=lambda x:-x["value"]),
        "managers": _managers(assets),
        "history": fetch_history(assets),
    }

# ---------- 4. RENDER ----------
def fmt(n):
    n = n or 0
    if abs(n) >= 1e9: return f"${n/1e9:.2f}B"
    if abs(n) >= 1e6: return f"${n/1e6:.1f}M"
    if abs(n) >= 1e3: return f"${n/1e3:.0f}K"
    return f"${n:.0f}"

def render(ds):
    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    blob = json.dumps(ds, ensure_ascii=False)
    out = tpl.replace("/*__DATA__*/", "window.DATA = " + blob + ";")
    for fn in ("terminal.html", "index.html"):   # index.html = servi par Pages/Vercel
        open(os.path.join(HERE, fn), "w", encoding="utf-8").write(out)
    print("→ terminal.html + index.html générés")

def write_snapshot(ds):
    """Écrit un snapshot quotidien NDJSON (une ligne = un actif, tous champs aplatis).
    Objectif : accumuler NOTRE série temporelle propriétaire — les protocoles qui
    disparaîtront restent dans les snapshots passés → zéro biais de survivance.
    Chargé tel quel dans BigQuery (voir bigquery/). Idempotent par date."""
    snap_dir = os.path.join(HERE, "snapshots")
    os.makedirs(snap_dir, exist_ok=True)
    date = ds["generated"][:10]
    ts = ds["generated"]
    rows = []
    for a in ds["assets"]:
        s = a.get("sig") or {}; yg = a.get("yg") or {}; fv = a.get("fv") or {}
        gu = a.get("gapu") or {}; gr = a.get("gaprel") or {}
        rows.append({
            "snapshot_date": date, "generated_ts": ts,
            "slug": a.get("slug"), "name": a.get("name"), "symbol": a.get("symbol"),
            "cls": a.get("cls"), "tvl": a.get("tvl"),
            "chg1d": a.get("chg1d"), "chg7d": a.get("chg7d"),
            "chains": a.get("chains", []), "listed_at": a.get("listedAt"),
            "manager": a.get("manager"), "apac": a.get("apac"),
            "ls": s.get("ls"), "ls_band": s.get("band"), "ls_stress": s.get("stress"),
            "ls_size": s.get("size"), "ls_stability": s.get("stability"), "ls_resil": s.get("resil"),
            "apy": yg.get("apy"), "sigma": yg.get("sigma"), "rf": ds.get("rf"),
            "fair_signal": yg.get("fair"), "gap_signal_bps": yg.get("gap_bps"), "verdict_signal": yg.get("verdict"),
            "fv_rating": fv.get("rating"), "fv_seniority": fv.get("seniority"), "fv_liquidity": fv.get("liquidity"),
            "fv_manager_tier": fv.get("manager_tier"), "fv_req": fv.get("req"), "fv_gap_bps": fv.get("gap_bps"),
            "fv_verdict": fv.get("verdict"), "fv_conf": fv.get("conf"), "fv_jurisdiction": fv.get("jurisdiction"),
            "gap_unified_bps": gu.get("gap_bps"), "gap_unified_src": gu.get("src"), "gap_unified_verdict": gu.get("verdict"),
            "rel_pctile": gr.get("pctile"), "rel_z": gr.get("z"), "rel_rv": gr.get("rv"), "rel_peer_med": gr.get("peer_med"),
        })
    fpath = os.path.join(snap_dir, f"rwa_{date}.ndjson")
    with open(fpath, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # index cumulatif des snapshots disponibles
    idx = os.path.join(snap_dir, "index.txt")
    dates = set()
    if os.path.exists(idx):
        dates = set(open(idx).read().split())
    dates.add(date)
    open(idx, "w").write("\n".join(sorted(dates)) + "\n")
    print(f"→ snapshot {date} : {len(rows)} lignes → snapshots/rwa_{date}.ndjson "
          f"({len(dates)} snapshot(s) accumulé(s))")

def main():
    raw = fetch()
    pools = fetch_pools()
    ymap, rf = build_yield_map(pools)
    print(f"  taux sans risque on-chain (T-bills médians) : {rf:.2f}%")
    stbl_tvl, stbl_n = fetch_stables()
    fund = json.load(open(os.path.join(HERE,"fundamentals.json"),encoding="utf-8")).get("funds",{})
    print(f"  fondamentaux curés : {len(fund)} fonds")
    ds = build_dataset(raw, ymap, rf, fund)
    ds["stbl_tvl"] = stbl_tvl
    ds["stbl_n"] = stbl_n
    json.dump(ds, open(os.path.join(HERE, "data.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"→ data.json : {ds['n_assets']} actifs, "
          f"total {fmt(ds['total_tvl'])}, crédit privé {fmt(ds['pc_total'])} ({ds['n_pc']} actifs)")
    print("  Répartition par classe :")
    for c, v in ds["byclass"]:
        print(f"    {fmt(v):>10}  {c}")
    print(f"  Signaux crédit : score moyen {ds['pc_avg_ls']}/100 · "
          f"🟢{ds['pc_bands']['green']} 🟡{ds['pc_bands']['amber']} 🔴{ds['pc_bands']['red']}"
          + (f" · ⚠ stress: {', '.join(ds['pc_stress'])}" if ds['pc_stress'] else " · aucun stress détecté"))
    print(f"  NAV gap : {ds['pc_yield_n']} fonds avec rendement matché · "
          f"RICH (sous-payé/risque): {ds['pc_rich'] or '—'} · CHEAP: {ds['pc_cheap'] or '—'}")
    print(f"  Alerts : {len(ds['alerts'])} signaux actionnables"
          + (f" · top: {ds['alerts'][0]['name']} (sev {ds['alerts'][0]['sev']})" if ds['alerts'] else ""))
    render(ds)
    write_snapshot(ds)
    print("✓ terminé —", ds["generated"])

if __name__ == "__main__":
    main()

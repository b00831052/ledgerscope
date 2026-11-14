"""
Fund pages: one static, shareable rating report per fund at fund/<slug>/index.html,
plus a searchable directory at fund/index.html. Rebuilt on every run from data.json.
"""
import os, json, html, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fund")
SITE = "https://b00831052.github.io/ledgerscope/"
BAND = {"green": "Green", "amber": "Amber", "red": "Red"}
E = lambda x: html.escape(str(x)) if x is not None else ""


def fmt(n):
    if n is None: return "–"
    a = abs(n)
    if a >= 1e9: return f"${n/1e9:.2f}B"
    if a >= 1e6: return f"${n/1e6:.1f}M"
    if a >= 1e3: return f"${n/1e3:.0f}K"
    return f"${n:,.0f}"


def pct(x, d=1):
    if x is None: return "–"
    if round(x, d) == 0: x = 0.0
    return f"{'+' if x >= 0 else ''}{x:.{d}f}%"


CSS = """
:root{--ground:#f6f7f9;--panel:#fff;--panel-2:#f9fafb;--ink:#0f1b2d;--ink-soft:#4b5869;--ink-faint:#6b7686;--line:#e4e7ec;--accent:#0b3d91;--accent-soft:#e8eef9;--up:#137a4b;--down:#b42318;--gold:#a15c07;color-scheme:light}
:root[data-theme=dark]{--ground:#1f2023;--panel:#232427;--panel-2:#27282b;--ink:#e8eaed;--ink-soft:#bdc1c6;--ink-faint:#9aa0a6;--line:#3c3d41;--accent:#8ab4f8;--accent-soft:#2b2e33;--up:#5bd69a;--down:#f28b82;--gold:#fdd663;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--ground);color:var(--ink);font:14px/1.55 Inter,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.top{display:flex;align-items:center;gap:12px;padding:12px 24px;background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
.mk{width:24px;height:24px;border-radius:4px;background:var(--accent);color:var(--panel);display:grid;place-items:center;font-weight:800;font-size:13px}
.brand{font-weight:700;color:var(--ink)}.brand em{font-style:normal;color:var(--accent)}
.top .sp{flex:1}.btn{border:1px solid var(--line);background:var(--panel);color:var(--ink-soft);border-radius:6px;padding:6px 12px;font:600 12.5px Inter,sans-serif;cursor:pointer}
.btn:hover{color:var(--ink)}
.wrap{max-width:1080px;margin:0 auto;padding:28px 24px 60px}
.crumb{font:500 11px "IBM Plex Mono",Menlo,monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--accent)}
h1{font-size:30px;line-height:1.15;margin:6px 0 4px;letter-spacing:-.02em}h1 .sym{color:var(--ink-faint);font-weight:500;font-size:20px}
.sub{color:var(--ink-soft)}.faint{color:var(--ink-faint)}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px 16px}
.card .k{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-faint)}
.card .v{font-size:22px;font-weight:650;margin-top:4px;font-variant-numeric:tabular-nums}
.grade{display:flex;gap:18px;align-items:center;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin-top:18px}
.badge{min-width:84px;text-align:center;border-radius:8px;padding:10px 12px;color:#fff;font-weight:800;font-size:28px;line-height:1}
.badge small{display:block;font-size:11px;font-weight:600;letter-spacing:.06em;margin-top:5px;opacity:.9}
.b-green{background:#137a4b}.b-amber{background:#a15c07}.b-red{background:#b42318}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:6px 20px 16px;margin-top:16px}
h2{font-size:16px;margin:16px 0 8px}
table{width:100%;border-collapse:collapse;font-size:13.5px}td,th{padding:8px 6px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--ink-faint);font-weight:600}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.kv td:first-child{color:var(--ink-soft);width:38%}
.up{color:var(--up)}.down{color:var(--down)}.gold{color:var(--gold)}
.flag{color:var(--down);font-weight:600}
ul{margin:6px 0;padding-left:20px}li{margin:3px 0}
.foot{margin-top:26px;font-size:12px;color:var(--ink-faint);line-height:1.6}
.search{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink);font:14px Inter,sans-serif;margin:16px 0}
@media(max-width:760px){.grid{grid-template-columns:1fr 1fr}.wrap{padding:20px 16px 40px}.top{padding:10px 16px}h1{font-size:24px}table{font-size:12.5px}.hide-m{display:none}}
@media print{.top,.noprint{display:none!important}body{background:#fff;color:#000}section,.card,.grade{break-inside:avoid;border-color:#ccc}}
"""

HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><meta name="description" content="{desc}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website"><meta property="og:title" content="{title}"><meta property="og:description" content="{desc}"><meta property="og:url" content="{url}"><meta property="og:site_name" content="Ledgerscope">
<meta name="twitter:card" content="summary"><meta property="og:image" content="https://b00831052.github.io/ledgerscope/logo.png">
<link rel="icon" type="image/svg+xml" href="{root}favicon.svg"><link rel="icon" type="image/png" href="{root}logo.png"><link rel="apple-touch-icon" href="{root}apple-touch-icon.png"><meta name="twitter:title" content="{title}"><meta name="twitter:description" content="{desc}">
<script>try{{document.documentElement.setAttribute("data-theme",localStorage.getItem("ls-theme")==="dark"?"dark":"light");}}catch(e){{document.documentElement.setAttribute("data-theme","light");}}</script>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{css}</style></head><body>
<div class="top"><a href="{root}" style="display:flex;align-items:center;gap:9px;text-decoration:none"><img src="{root}logo.svg" alt="Ledgerscope" style="width:26px;height:26px;border-radius:6px;display:block"><span class="brand">Ledger<em>scope</em></span></a>
<span class="sp"></span><a class="btn noprint" href="{root}fund/">All funds</a><button class="btn noprint" onclick="navigator.clipboard&&navigator.clipboard.writeText(location.href).then(()=>{{this.textContent='Link copied'}})">Copy link</button><button class="btn noprint" onclick="window.print()">PDF</button><button class="btn noprint" id="tb">Dark mode</button></div>
"""

TAIL = """<script>(function(){{var b=document.getElementById('tb'),r=document.documentElement,d=r.getAttribute('data-theme')==='dark';b.textContent=d?'Light mode':'Dark mode';
b.onclick=function(){{d=!d;r.setAttribute('data-theme',d?'dark':'light');b.textContent=d?'Light mode':'Dark mode';try{{localStorage.setItem('ls-theme',d?'dark':'light');}}catch(e){{}}}};}})();</script>
</body></html>"""


def _kv(rows):
    return "<table class='kv'>" + "".join(f"<tr><td>{E(k)}</td><td>{v}</td></tr>" for k, v in rows) + "</table>"


def page(a, ds, kr, al, hist, lb):
    slug, s = a["slug"], a.get("sig") or {}
    band = s.get("band", "amber")
    url = f"{SITE}fund/{slug}/"
    title = (f"{a['name']} rating report | Ledgerscope" if a['name'].endswith(")") or not a.get('symbol')
             else f"{a['name']} ({a['symbol']}) rating report | Ledgerscope")
    desc = (f"{a['name']}: LS Score {s.get('ls')}/100 ({BAND.get(band, band)}), {fmt(a['tvl'])} on-chain, "
            f"{a['cls']}. Independent rating by Ledgerscope, {ds['generated']}.")
    h = [HEAD.format(title=E(title), desc=E(desc), url=E(url), css=CSS, root="../../")]
    h.append("<div class='wrap'>")
    h.append(f"<div class='crumb'>Ledgerscope rating report · {E(a['cls'])}</div>")
    h.append(f"<h1>{E(a['name'])} <span class='sym'>{E(a.get('symbol'))}</span></h1>")
    meta = [E(a.get("manager") or "Issuer not identified")]
    if (a.get("fv") or {}).get("jurisdiction"): meta.append(E(a["fv"]["jurisdiction"]))
    meta.append(f"Data as of {E(ds['generated'])}")
    h.append(f"<div class='sub'>{' · '.join(meta)}</div>")
    # grade block
    note = E(s.get("note") or "")
    stress = "<div class='flag' style='margin-top:4px'>Redemption stress: net outflow of 8%+ over 7 days</div>" if s.get("stress") else ""
    h.append(f"<div class='grade'><div class='badge b-{band}'>{s.get('ls','–')}<small>{BAND.get(band, band).upper()}</small></div>"
             f"<div><div style='font-weight:650;font-size:16px'>LS Score {s.get('ls','–')}/100</div><div class='sub'>{note}</div>{stress}</div></div>")
    # key numbers
    c7, c1 = a.get("chg7d"), a.get("chg1d")
    cards = [("On-chain value", fmt(a["tvl"])),
             ("7-day change", f"<span class='{'up' if (c7 or 0) >= 0 else 'down'}'>{pct(c7)}</span>"),
             ("1-day change", f"<span class='{'up' if (c1 or 0) >= 0 else 'down'}'>{pct(c1)}</span>"),
             ("Networks", str(len(a.get("chains") or [])) if a.get("chains") else "–")]
    h.append("<div class='grid'>" + "".join(f"<div class='card'><div class='k'>{k}</div><div class='v'>{v}</div></div>" for k, v in cards) + "</div>")
    # alerts
    if al:
        h.append("<section><h2>Active signals</h2><ul>" + "".join(f"<li>{E(r)}</li>" for r in al["reasons"]) + "</ul></section>")
    # score breakdown
    h.append("<section><h2>Score breakdown</h2>" + _kv([
        ("Size (42%)", f"{s.get('size','–')}"), ("Value stability (40%)", f"{s.get('stability','–')}"),
        ("Network resilience (18%)", f"{s.get('resil','–')}"),
        ("Bands", "Green 68+ · Amber 48-67 · Red under 48")]) + "</section>")
    # valuation
    gu, fv = a.get("gapu"), a.get("fv")
    if gu or fv:
        rows = []
        if gu:
            v = gu.get("verdict")
            vt = {"rich": "<span class='down'>RICH: yield below risk</span>", "cheap": "<span class='up'>CHEAP: yield above risk</span>",
                  "fair": "In line", "unverified": "<span class='faint'>Unverified: on-chain yield below the floor for its rating</span>"}.get(v, "–")
            rows += [("Offered yield (on-chain)", f"{gu['apy']:.2f}%"), ("Required yield", f"{gu['fair']:.2f}%"),
                     ("NAV gap", f"{gu['gap_bps']:+d} bps"), ("Verdict", vt),
                     ("Model", "Fundamental" if gu.get("src") == "fond." else "Signal")]
        if fv:
            rows += [("Rating input", E(fv.get("rating"))), ("Seniority", E((fv.get("seniority") or "").replace("_", " "))),
                     ("Liquidity", E(fv.get("liquidity"))), ("Manager tier", E(fv.get("manager_tier"))),
                     ("Data confidence", E(fv.get("conf"))), ("Note", E(fv.get("note")))]
        gr = a.get("gaprel")
        if gr: rows.append(("Peer position", f"{E(gr['rv'])} · {gr['pctile']}th percentile of {gr['n']} peers"))
        h.append("<section><h2>Valuation</h2>" + _kv(rows) + "</section>")
    elif a["cls"] in ("U.S. Treasuries", "Private credit", "Cash / yield stablecoin", "Non-US government debt"):
        h.append("<section><h2>Valuation</h2><p class='faint'>No observable on-chain yield: income likely accrues inside the NAV. No valuation call.</p></section>")
    # loan book
    m = (lb or {}).get("maple")
    if slug == "proto-maple" and m:
        rows = "".join(f"<tr><td>{E(p['pool'])}</td><td class='n'>{fmt(p['outstanding'])}</td><td class='n hide-m'>{p['loans']}</td>"
                       f"<td class='n hide-m'>{p['borrowers']}</td><td class='n'>{p['top_borrower_pct']}%</td><td class='n'>{p['rate']:.2f}%</td>"
                       f"<td class='n'>{(str(p['cover'])+'x') if p['collateral'] else 'unsecured'}</td>"
                       f"<td class='n'>{('-'+str(p['crypto_drop_to_1x'])+'%') if p['crypto_drop_to_1x'] is not None else '–'}</td>"
                       f"<td>{('<span class=flag>'+str(p['late_n'])+' past deadline</span>') if p['late_n'] else ''}</td></tr>" for p in m["pools"])
        h.append(f"<section><h2>Loan book</h2><p class='sub'>{m['loans']} active loans · {fmt(m['outstanding'])} lent out · collateral cover {m['cover']}x · source: Maple public API</p>"
                 f"<table><tr><th>Pool</th><th class='n'>Lent out</th><th class='n hide-m'>Loans</th><th class='n hide-m'>Borrowers</th><th class='n'>Top borrower</th><th class='n'>Rate</th><th class='n'>Cover</th><th class='n'>Crypto drop to 1.0x</th><th>Flags</th></tr>{rows}</table></section>")
    for f in ((lb or {}).get("centrifuge") or {}).get("funds", []):
        if f.get("slug") == slug:
            h.append("<section><h2>Redemption queue (Centrifuge)</h2>" + _kv([
                ("Tokens issued via Centrifuge", fmt(f["value"])), ("NAV per share", f"{f['nav_per_share']:,.4f}"),
                ("Waiting to redeem", fmt(f["queue_usd"])),
                ("Share of Centrifuge-issued shares", f"<span class='{'flag' if f['queue_pct'] >= 10 else ''}'>{f['queue_pct']}%</span>")]) + "</section>")
    # key risk
    if kr:
        rows = [("Grade", f"<b>{E(kr.get('grade'))}</b> ({kr.get('score')}/100)"), ("Contract", f"<span style='font-family:IBM Plex Mono,monospace;font-size:12px'>{E(kr.get('chain'))}:{E(kr.get('address'))}</span>"),
                ("Upgrade control", E(kr.get("upgrade"))), ("Powers held by", E(kr.get("owner"))),
                ("Powers", E(", ".join(kr.get("powers") or []) or "none")), ("Holders", E(kr.get("holders")))]
        notes = (kr.get("hard") or []) + (kr.get("flags") or [])
        if notes: rows.append(("Notes", E(" · ".join(notes))))
        h.append("<section><h2>Contract control (Key Risk)</h2>" + _kv(rows) + "</section>")
    # history
    if hist:
        rows = "".join(f"<tr><td style='font-family:IBM Plex Mono,monospace'>{E(d)}</td><td class='n'>{ls}</td><td>{BAND.get(b, b)}</td></tr>" for d, ls, b in reversed(hist[-30:]))
        h.append(f"<section><h2>Grade history</h2><p class='sub'>From the hash-chained public ratings ledger.</p><table><tr><th>Date</th><th class='n'>LS Score</th><th>Band</th></tr>{rows}</table></section>")
    # on-chain facts
    rows = [("Networks", E(", ".join(a.get("chains") or []) or "–")), ("Asset class", E(a["cls"]))]
    if a.get("address"): rows.append(("Main contract", f"<span style='font-family:IBM Plex Mono,monospace;font-size:12px'>{E(a['address'])}</span>"))
    if a.get("url"): rows.append(("Website", f"<a href='{E(a['url'])}' rel='nofollow noopener' target='_blank'>{E(a['url'].replace('https://','').replace('http://','').rstrip('/'))}</a>"))
    h.append("<section><h2>On-chain facts</h2>" + _kv(rows) + "</section>")
    h.append(f"<div class='foot'>Ledgerscope by RWA Credit Intelligence, Singapore. Independent research based on public data and proprietary models: "
             f"not investment advice, not a credit rating under any regulation, not a solicitation. "
             f"<a href='../../#method'>Methodology</a> · <a href='../../'>Open the terminal</a> · Permanent link: <a href='{E(url)}'>{E(url)}</a></div>")
    h.append("</div>" + TAIL.format())
    return "".join(h)


def directory(ds):
    rows = "".join(
        f"<tr data-q='{E((a['name']+' '+(a.get('symbol') or '')+' '+a['cls']+' '+(a.get('manager') or '')).lower())}'>"
        f"<td><a href='{E(a['slug'])}/'>{E(a['name'])}</a> <span class='faint'>{E(a.get('symbol'))}</span></td>"
        f"<td class='hide-m'>{E(a['cls'])}</td><td class='n'>{fmt(a['tvl'])}</td>"
        f"<td class='n'><b class='{ {'green':'up','amber':'gold','red':'down'}.get((a.get('sig') or {}).get('band'),'') }'>{(a.get('sig') or {}).get('ls','–')}</b></td></tr>"
        for a in ds["assets"])
    url = f"{SITE}fund/"
    h = HEAD.format(title="All rated funds | Ledgerscope", desc=f"{len(ds['assets'])} tokenized funds with an independent Ledgerscope rating report.",
                    url=url, css=CSS, root="../")
    h += (f"<div class='wrap'><div class='crumb'>Ledgerscope · rating reports</div><h1>All rated funds</h1>"
          f"<div class='sub'>{len(ds['assets'])} funds · {fmt(ds['total_tvl'])} on-chain · {E(ds['generated'])}</div>"
          f"<input class='search' id='q' placeholder='Search a fund, ticker, class or manager…' autocomplete='off'>"
          f"<section style='padding-top:4px'><table id='t'><tr><th>Fund</th><th class='hide-m'>Class</th><th class='n'>Value</th><th class='n'>LS Score</th></tr>{rows}</table></section>"
          "<script>document.getElementById('q').addEventListener('input',function(){var v=this.value.toLowerCase();document.querySelectorAll('#t tr[data-q]').forEach(function(r){r.style.display=r.dataset.q.indexOf(v)>-1?'':'none';});});</script>"
          "</div>" + TAIL.format())
    return h.replace("href='../../#method'", "href='../#method'")


def build(ds):
    if os.path.isdir(OUT): shutil.rmtree(OUT)
    os.makedirs(OUT)
    kr = {k["slug"]: k for k in ds.get("keyrisk", []) if k.get("slug")}
    al = {x["slug"]: x for x in ds.get("alerts", [])}
    hist = ((ds.get("track") or {}).get("ratings") or {}).get("hist", {})
    lb = ds.get("loanbook")
    for a in ds["assets"]:
        d = os.path.join(OUT, a["slug"]); os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "index.html"), "w", encoding="utf-8").write(page(a, ds, kr.get(a["slug"]), al.get(a["slug"]), hist.get(a["slug"]), lb))
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(directory(ds))
    # sitemap for search engines
    urls = [SITE, SITE + "fund/"] + [f"{SITE}fund/{a['slug']}/" for a in ds["assets"]]
    open(os.path.join(HERE, "sitemap.xml"), "w").write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                                       + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>\n")
    print(f"→ fund pages: {len(ds['assets'])} reports + directory + sitemap")

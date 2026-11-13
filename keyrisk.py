"""
Launchscope module: Launch & Key Risk for institutional tokens.

For every tokenized real-world-asset token we can locate on-chain, answer the
question an institution asks first: who can change this contract, mint it,
or freeze it, and is that power held by one person or by a governed set?

Reads, per token (all public, no key):
  - EIP-1967 storage slots (upgrade implementation + admin)
  - GoPlus token security (owner, mint/pause/blacklist powers, verified code, holders)
  - the key holder's own code: Safe multisig threshold, OpenZeppelin timelock delay

Registry of token addresses: tokens.json (auto-resolved from DefiLlama +
CoinGecko, then frozen so a rating can always be traced to the same contract).
"""
import json, os, time, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
REG = os.path.join(HERE, "tokens.json")

# chain name (DefiLlama / CoinGecko) -> (canonical, GoPlus id, RPC)
CHAINS = {
    "ethereum": ("ethereum", 1, "https://ethereum-rpc.publicnode.com"),
    "base": ("base", 8453, "https://base-rpc.publicnode.com"),
    "bsc": ("bsc", 56, "https://bsc-rpc.publicnode.com"),
    "binance-smart-chain": ("bsc", 56, "https://bsc-rpc.publicnode.com"),
    "arbitrum": ("arbitrum", 42161, "https://arbitrum-one-rpc.publicnode.com"),
    "arbitrum-one": ("arbitrum", 42161, "https://arbitrum-one-rpc.publicnode.com"),
    "polygon": ("polygon", 137, "https://polygon-bor-rpc.publicnode.com"),
    "polygon-pos": ("polygon", 137, "https://polygon-bor-rpc.publicnode.com"),
    "xdai": ("gnosis", 100, "https://gnosis-rpc.publicnode.com"),
    "avalanche": ("avalanche", 43114, "https://avalanche-c-chain-rpc.publicnode.com"),
}
CHAIN_PREF = ["ethereum", "base", "arbitrum", "bsc", "polygon", "gnosis", "avalanche"]
SLOT_IMPL = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
SLOT_ADMIN = "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"
ZERO = "0x" + "0" * 40
DEAD = {ZERO, "0x000000000000000000000000000000000000dead"}

def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "ledgerscope/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def _rpc(url, method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "ledgerscope/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r).get("result")
    except Exception:
        return None

def _addr_from_slot(v):
    if not v or len(v) < 42: return ZERO
    return "0x" + v[-40:].lower()

def _is_contract(rpc, a):
    if not a or a in DEAD: return False
    code = _rpc(rpc, "eth_getCode", [a, "latest"])
    return bool(code and len(code) > 2)

def _call_uint(rpc, to, selector):
    r = _rpc(rpc, "eth_call", [{"to": to, "data": selector}, "latest"])
    try:
        return int(r, 16) if r and r != "0x" and len(r) <= 66 else None
    except (TypeError, ValueError):
        return None

def _call_addr(rpc, to, data):
    r = _rpc(rpc, "eth_call", [{"to": to, "data": data}, "latest"])
    if not r or r == "0x" or len(r) < 66: return None
    a = "0x" + r[-40:].lower()
    return None if a == ZERO else a

def find_controller(rpc, token):
    """Who can act as admin of a token: owner() first, then AccessControl DEFAULT_ADMIN_ROLE member 0."""
    o = _call_addr(rpc, token, "0x8da5cb5b")                                   # owner()
    if o: return o
    return _call_addr(rpc, token, "0x9010d07c" + "0" * 64 + "0" * 64)          # getRoleMember(0x00, 0)

def key_holder(rpc, a, depth=0):
    """Classify who holds a power: renounced / single key / multisig N-of-M / timelock / contract."""
    if not a:
        return {"type": "unknown", "label": "Holder not found on-chain"}
    if a in DEAD:
        return {"type": "none", "label": "Renounced (no holder)"}
    if not _is_contract(rpc, a):
        return {"type": "eoa", "label": "Single wallet (one private key)"}
    thr = _call_uint(rpc, a, "0xe75235b8")                                    # Safe.getThreshold()
    if thr:
        r = _rpc(rpc, "eth_call", [{"to": a, "data": "0xa0e67e2b"}, "latest"])  # Safe.getOwners()
        try: n = int(r[66:130], 16) if r and len(r) >= 130 else None
        except (TypeError, ValueError): n = None
        if n is not None and not (1 <= n <= 100): n = None
        return {"type": "multisig", "threshold": thr, "owners": n, "label": f"Multisig {thr}-of-{n or '?'}"}
    delay = _call_uint(rpc, a, "0xf27a0c92")                                  # TimelockController.getMinDelay()
    if delay is not None and 0 < delay < 10**8:
        return {"type": "timelock", "delay_h": round(delay / 3600, 1), "label": f"Timelock {round(delay/3600,1)}h"}
    if depth < 2:                                                            # e.g. ProxyAdmin -> its owner
        up = _call_addr(rpc, a, "0x8da5cb5b")
        if up and up != a:
            inner = key_holder(rpc, up, depth + 1)
            if inner["type"] != "unknown":
                inner = dict(inner); inner["label"] = "Admin contract owned by " + inner["label"].lower()
                return inner
    return {"type": "contract", "label": "Contract (governance not verified)"}

# ---------- registry ----------
def resolve_registry(assets, max_new=25):
    """slug -> {chain, address}. Resolves only what's missing, then freezes it."""
    reg = json.load(open(REG)) if os.path.exists(REG) else {}
    new = 0
    for a in sorted(assets, key=lambda x: -x["tvl"]):
        slug = a.get("slug")
        if not slug or slug in reg: continue
        if new >= max_new: break
        cand = []
        raw = a.get("address") or ""
        if raw:
            ch, ad = (raw.split(":", 1) if ":" in raw else ("ethereum", raw))
            cand.append((ch, ad))
        if not cand and a.get("gecko_id"):
            try:
                r = _get(f"https://api.coingecko.com/api/v3/coins/{a['gecko_id']}?localization=false&tickers=false"
                         "&market_data=false&community_data=false&developer_data=false")
                for ch, ad in (r.get("platforms") or {}).items():
                    if ad: cand.append((ch, ad))
            except Exception:
                pass
            time.sleep(3)
            new += 1
        evm = [(CHAINS[c][0], ad) for c, ad in cand if c in CHAINS and ad.startswith("0x")]
        evm.sort(key=lambda x: CHAIN_PREF.index(x[0]) if x[0] in CHAIN_PREF else 99)
        reg[slug] = {"chain": evm[0][0], "address": evm[0][1].lower()} if evm else {"chain": None, "address": None}
    json.dump(reg, open(REG, "w"), indent=1, sort_keys=True)
    return reg

# ---------- rating ----------
def rate_token(a, ent):
    canon = ent["chain"]; addr = ent["address"]
    meta = next(v for v in CHAINS.values() if v[0] == canon)
    _, gp_id, rpc = meta
    flags, hard = [], []
    # 1. upgrade control (35)
    impl = _addr_from_slot(_rpc(rpc, "eth_getStorageAt", [addr, SLOT_IMPL, "latest"]))
    adm = _addr_from_slot(_rpc(rpc, "eth_getStorageAt", [addr, SLOT_ADMIN, "latest"]))
    gp = None
    try:
        d = _get(f"https://api.gopluslabs.io/api/v1/token_security/{gp_id}?contract_addresses={addr}")
        res = d.get("result") if isinstance(d, dict) else None
        if isinstance(res, dict) and res:
            v = res.get(addr) or list(res.values())[0]
            gp = v if isinstance(v, dict) else None
    except Exception:
        pass
    time.sleep(2.1)
    g = (lambda k: str((gp or {}).get(k, "0")) == "1")
    owner = ((gp or {}).get("owner_address") or "").lower() or None
    if not owner or owner == ZERO:
        owner = find_controller(rpc, addr) or owner
    upgradeable = impl != ZERO or g("is_proxy")
    if not upgradeable:
        up = {"type": "immutable", "label": "Not upgradeable (code locked)"}; us = 35
    else:
        holder = adm if adm != ZERO else owner            # transparent proxy admin, else UUPS owner/admin role
        up = key_holder(rpc, holder)
        std = impl != ZERO                                   # standard EIP-1967 proxy, upgrade path provable
        if up["type"] == "eoa" and std: us = 0; hard.append("Upgrade admin is a single wallet: one private key can change the code")
        elif up["type"] == "eoa": us = 8; flags.append("Flagged as proxy (non-standard), owner is a single wallet")
        elif up["type"] == "timelock": us = 30
        elif up["type"] == "multisig": us = 25 if (up.get("threshold") or 0) >= 3 else 18
        elif up["type"] == "none": us = 35
        elif up["type"] == "unknown": us = 10; flags.append("Upgradeable, upgrade admin not identifiable on-chain")
        else: us = 12; flags.append("Upgrade admin is a contract we could not verify")
    # 2. privileged powers (25): mint / pause / blacklist held by whom
    powers = [p for k, p in [("is_mintable", "mint"), ("transfer_pausable", "pause"), ("is_blacklisted", "blacklist")] if g(k)]
    ow = key_holder(rpc, owner)
    if not powers: ps = 25
    elif ow["type"] in ("multisig", "timelock", "none"): ps = 25 if ow["type"] != "multisig" or (ow.get("threshold") or 0) >= 2 else 15
    elif ow["type"] == "unknown": ps = 12; flags.append(f"{', '.join(powers)} power exists, holder not identifiable")
    elif ow["type"] == "eoa":
        ps = 5; flags.append(f"Single key controls {', '.join(powers)}")
        if "mint" in powers: hard.append("A single wallet holds the mint power")
    else: ps = 15; flags.append(f"{', '.join(powers)} held by unverified contract")
    # 3. code transparency (15)
    if gp is None:
        cs = 5; flags.append("Security scanner has no data")
    elif g("is_open_source"): cs = 15
    else: cs = 0; hard.append("Contract source code not verified")
    if g("is_honeypot"): flags.append("Transfers restricted (likely permissioned)")
    # 4. holder base (15)
    hc = int(float((gp or {}).get("holder_count") or 0))
    hs = 15 if hc >= 1000 else 10 if hc >= 100 else 5 if hc >= 10 else 2
    # 5. market behaviour (10) from the Ledgerscope LS signal
    ms = round(10 * ((a.get("sig") or {}).get("stability") or 0))
    score = int(us + ps + cs + hs + ms)
    grd = "F" if hard else "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50 else "D" if score >= 35 else "F"
    kind = "asset" if a.get("cls") in ("U.S. Treasuries", "Cash / yield stablecoin", "Commodities") else "platform"
    return {"kind": kind, "chain": canon, "address": addr, "score": score, "grade": grd, "hard": hard, "flags": flags,
            "upgrade": up["label"], "upgrade_type": up["type"], "owner": ow["label"], "owner_type": ow["type"],
            "powers": powers, "holders": hc, "parts": {"upgrade": us, "powers": ps, "code": cs, "holders": hs, "market": ms}}

def run(assets):
    reg = resolve_registry(assets)
    out = []
    for a in assets:
        ent = reg.get(a.get("slug") or "")
        if not ent or not ent.get("address"): continue
        try:
            kr = rate_token(a, ent)
        except Exception as e:
            continue
        kr.update({"slug": a["slug"], "name": a["name"], "symbol": a["symbol"], "cls": a["cls"], "tvl": a["tvl"],
                   "listed_at": a.get("listedAt"), "manager": a.get("manager")})
        out.append(kr)
    print(f"  key risk: {len(out)} tokens rated (registry {sum(1 for v in reg.values() if v.get('address'))} resolved)")
    return sorted(out, key=lambda x: -x["tvl"])

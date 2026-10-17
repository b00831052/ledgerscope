# Ledgerscope — Méthodologie & Limites

*Version validée le 2026-09-07. Ce document décrit exactement comment chaque chiffre du Terminal et des Credit Reviews est produit, ses hypothèses et ses limites. Il suit un standard de reproductibilité : un tiers doit pouvoir recréer nos résultats.*

---

## 1. Sources de données

| Source | Endpoint | Usage | Fréquence |
|---|---|---|---|
| DefiLlama Protocols | `api.llama.fi/protocols` | Univers RWA, TVL, chaînes, variations | quotidien |
| DefiLlama Yields | `yields.llama.fi/pools` | APY, volatilité de rendement (σ) | quotidien |
| DefiLlama Protocol history | `api.llama.fi/protocol/{slug}` | Séries temporelles de TVL (28 mois) | quotidien |
| DefiLlama Stablecoins | `stablecoins.llama.fi/stablecoins` | Total stablecoins | quotidien |
| `fundamentals.json` | fichier curé à la main | Rating, séniorité, liquidité, gérant, juridiction | manuel |

Toutes les sources API sont **publiques et gratuites**. Aucune donnée propriétaire tierce n'est redistribuée. Snapshot horodaté (`generated`) sur chaque vue. Données non temps réel.

## 2. Classification par classe d'actif

Attribution par **liste blanche de slugs** curée (`WHITELIST` dans `build.py`), et non par heuristique de mots-clés, pour éliminer les faux positifs. Le crédit privé n'est attribué **que** par la liste blanche. Repli mots-clés pour les protocoles hors liste (jamais vers « crédit privé »).

**Limite :** la liste blanche doit être maintenue à chaque nouveau protocole ; un protocole non curé retombe sur l'heuristique ou « Other RWA ».

## 3. LS Score (0–100) — qualité / risque

Signal on-chain observable, sans données off-chain :

```
LS = 100 × (0,42·taille + 0,40·stabilité + 0,18·résilience)
  taille     = log10(TVL) / log10(2 Md$)          (plafonné 0–1)
  stabilité  = max(0, 1 − |Δ7j TVL| / 25)         (>25%/sem ⇒ 0)
  résilience = min(1, nb_chaînes / 3)
```

Bandes : 🟢 ≥68 · 🟡 48–67 · 🔴 <48. Flag **STRESS** si Δ7j ≤ −8% (pression de rachat).

**Distribution observée** (validation) : min 32 / médiane 78 / max 99, σ=14 → le score discrimine, mais **skew haussier** (majorité 🟢). À lire comme un proxy taille/stabilité, pas un gate de qualité strict.

## 4. NAV gap — écart de valorisation

Deux modèles, puis unification.

**4a. Modèle fondamental** (cross-classe, préféré quand fondamentaux curés) :
```
requis = rf + spread(rating) + ajust(séniorité) + ajust(liquidité) + ajust(gérant)
gap_fond = rendement_offert − requis   (bps)
```
La prime d'illiquidité est **portée par la liquidité** (daily 0 → locked +2,8 pts), pas par une base fixe — ce qui rend le modèle juste sur les classes liquides (T-bills) comme illiquides (crédit privé).

**4b. Modèle signal** (repli si pas de fondamentaux) :
```
requis = rf + 2% + (1 − LS/100)×10% + pénalité_volatilité(σ)
```

**4c. NAV gap unifié** = fondamental si disponible, sinon signal. RICH ≤ −75 bps · CHEAP ≥ +150 bps.

**rf (taux sans risque on-chain)** = médiane des APY des fonds monétaires / T-bills tokenisés (BUIDL, USYC, Ondo, Spiko…). Observé ~3,4–3,5%, cohérent avec les T-bills réels.

### ⚠️ Limite critique — biais de calibration
En absolu, ~74% des fonds notés ressortent « rich » (gap négatif). **C'est en partie un vrai signal** (le crédit tokenisé sous-rémunère son risque) **et en partie une calibration conservatrice** du rendement requis. Un résultat qui confirme aussi nettement l'hypothèse doit être traité avec prudence.

## 5. Valorisation relative aux pairs (dé-biaisage)

Pour neutraliser le biais de niveau absolu, chaque fonds noté est situé **dans la distribution de ses pairs de classe** (classes à ≥4 fonds notés) :
```
percentile = rang du gap parmi les pairs
z          = (gap − médiane_pairs) / σ_pairs
rv = CHEAP si pctile ≥ 75 · RICH si pctile ≤ 25 · IN-LINE sinon
```
Exemple : Apollo est « rich » en absolu mais **IN-LINE** vs pairs ; Centrifuge est le vrai retardataire relatif (17ᵉ pctile). **C'est le signal le plus défendable** car indépendant de la calibration absolue.

## 6. Valorisation fondamentale — barème

| Rating | spread (pts) | | Séniorité | ajust | | Liquidité | ajust | | Gérant | ajust |
|---|---|---|---|---|---|---|---|---|---|---|
| AAA | 0,8 | | senior secured | −0,5 | | daily | 0 | | Tier 1 | −0,6 |
| AA | 1,2 | | senior / ABS | 0 | | monthly | +0,8 | | Tier 2 | 0 |
| A | 1,8 | | unsecured | +1,2 | | quarterly | +1,6 | | Tier 3 | +1,2 |
| BBB | 2,8 | | subordinated | +1,5 | | locked | +2,8 | | | |
| BB / B / NR | 4,5 / 6,5 / 5,5 | | first-loss / equity | +3,0 / +2,5 | | | | | | |

Barème paramétrable, révisable à mesure que des données de spreads réels (ex. via Capital IQ, en calibration privée) deviennent disponibles.

## 7. Historique & agrégats

- **Historique** : séries `/protocol/{slug}` des ~54 plus gros protocoles (>95% de la TVL), agrégées par classe et par mois sur 28 mois.
  - ⚠️ **Biais de survivance** : seuls les protocoles **vivants aujourd'hui** sont inclus ; les protocoles disparus sont absents, ce qui lisse la trajectoire passée. La courbe reflète « l'histoire des survivants », pas l'histoire complète du marché.
- **Réseaux** : valeur par chaîne via `chainTvls` (pas de double-comptage — validé : Σ réseaux = total exact).
- **Managers** : agrégation par gérant curé (`ASSET_MANAGERS`), repli sur le nom du protocole.
- **Croissance par classe** (1M/3M/YTD/1A) : dérivée des séries historiques (variation de TVL, **pas un rendement** — inclut les flux nets).

## 8. Alertes

Générées sur tous les actifs ≥ 20 M$ ; sévérité = somme pondérée de : stress de rachat (+3), survalorisation (jusqu'à +4), score faible (+2), volatilité de rendement (+1), rendement excédentaire (+0,8). Triées décroissant.

## 9. Résumé de la validation (pré-diffusion)

| Contrôle | Résultat |
|---|---|
| Σ classes / réseaux / managers = total | ✅ exact (aucun double-comptage) |
| rf plausible | ✅ 3,4–3,5% |
| LS Score discrimine | ✅ σ=14, min 32 max 99 |
| Skew « rich » absolu | 🟡 74% — traité par la valo relative (§5) |
| Biais de survivance historique | 🟡 documenté (§7) |

**Statut : diffusable avec caveats** — les résultats absolus doivent toujours être lus avec le signal relatif (§5), et l'historique avec le caveat de survivance (§7).

## 10. Portée & avertissement

Recherche indépendante à visée informative, fondée sur des données publiques et des modèles propriétaires. **Ne constitue ni un conseil en investissement, ni une notation de crédit officielle réglementée, ni une sollicitation.** Les avis reflètent l'état du marché à la date du snapshot et évoluent avec les données.

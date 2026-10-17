# Ledgerscope

**La couche de données et d'analytique indépendante sur le crédit privé tokenisé.**
Réplique fonctionnelle de rwa.xyz + une couche analytique propriétaire (LS Score, NAV gap, Alerts) que rwa.xyz n'offre pas. Focus APAC / Singapour.

## Ce que ça fait

Un pipeline Python interroge les API publiques gratuites de DefiLlama (protocoles + rendements), classe les protocoles RWA par classe d'actifs (liste blanche curée), calcule deux modèles propriétaires, et génère un terminal HTML autonome.

- **LS Score** (0–100) — qualité/risque depuis les signaux on-chain : taille (42%) + stabilité de TVL (40%) + résilience multi-chaîne (18%).
- **NAV gap** — rendement juste = taux sans risque on-chain (médiane des T-bills tokenisés) + prime exigée par le risque `[2% + (1−LS/100)×10% + pénalité de volatilité σ]`. Gap = rendement offert − rendement juste. `RICH` = NAV probablement survalorisée ; `CHEAP` = coussin / risque caché.
- **Alerts** — synthèse actionnable priorisée par sévérité.

## Lancer en local

```bash
python3 build.py        # aucune dépendance externe (stdlib seule)
open terminal.html
```

`build.py` régénère `data.json`, `terminal.html` et `index.html`.

## Déploiement (hébergement gratuit + auto-refresh)

### Option A — GitHub Pages (recommandé, tout gratuit)
1. Créer un repo GitHub et y pousser ce dossier.
2. Dans **Settings → Pages**, source = **GitHub Actions**.
3. Le workflow [`.github/workflows/refresh.yml`](.github/workflows/refresh.yml) rebuild la donnée **chaque jour à 06:00 UTC** et redéploie. Bouton « Run workflow » pour forcer.

```bash
cd ~/Downloads/ledgerscope
git init && git add -A && git commit -m "Ledgerscope MVP"
git branch -M main
git remote add origin https://github.com/<TON_USER>/ledgerscope.git
git push -u origin main
```

### Option B — Vercel / Netlify
Importer le repo ; build command `python3 build.py`, output directory `.` (index.html à la racine). Pour l'auto-refresh, garder le cron GitHub Actions ou un cron Vercel.

## Données
DefiLlama public API (`api.llama.fi/protocols`, `yields.llama.fi/pools`) — gratuit, sans clé. Snapshot, non temps réel. Ni conseil en investissement, ni valorisation officielle.

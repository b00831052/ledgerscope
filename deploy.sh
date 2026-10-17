#!/bin/bash
# Ledgerscope — déploiement en une commande sur GitHub Pages.
# Usage :  ./deploy.sh [nom-du-repo]      (défaut : ledgerscope)
# La SEULE étape manuelle = approuver la connexion GitHub dans ton navigateur
# (aucun mot de passe n'est tapé ni stocké par le script).
set -e
cd "$(dirname "$0")"
GH="./.tools/gh"
REPO="${1:-ledgerscope}"

[ -x "$GH" ] || { echo "✗ gh introuvable dans .tools/ — relance la préparation."; exit 1; }

# 1. Authentification (une fois) — device flow dans TON navigateur
if ! "$GH" auth status >/dev/null 2>&1; then
  echo "→ Connexion à GitHub requise (une seule fois)."
  echo "  Suis les instructions : GitHub.com → HTTPS → Login with a web browser."
  "$GH" auth login
fi
USER="$("$GH" api user -q .login)"
echo "→ Connecté comme : $USER"

# 2. Repo git local prêt ?
git rev-parse --git-dir >/dev/null 2>&1 || { git init -q && git add -A && git commit -qm "Ledgerscope"; }
git branch -M main 2>/dev/null || true

# 3. Créer le repo distant s'il n'existe pas, sinon juste push
if "$GH" repo view "$USER/$REPO" >/dev/null 2>&1; then
  echo "→ Repo $USER/$REPO existe déjà — push."
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$USER/$REPO.git"
  git push -u origin main
else
  echo "→ Création du repo public $USER/$REPO + push…"
  "$GH" repo create "$REPO" --public --source=. --remote=origin --push
fi

# 4. Activer GitHub Pages (source = GitHub Actions)
echo "→ Activation de GitHub Pages…"
"$GH" api -X POST "repos/$USER/$REPO/pages" -f build_type=workflow >/dev/null 2>&1 \
 || "$GH" api -X PUT "repos/$USER/$REPO/pages" -f build_type=workflow >/dev/null 2>&1 \
 || echo "  (si erreur : Settings → Pages → Source = GitHub Actions, manuellement)"

# 5. Lancer le premier build
"$GH" workflow run "Refresh & Deploy Ledgerscope" >/dev/null 2>&1 || true

echo ""
echo "✓ Déployé — le build tourne (~1-2 min)."
echo "  Site : https://$USER.github.io/$REPO/"
echo "  Actions : https://github.com/$USER/$REPO/actions"
echo "  Rafraîchissement automatique : tous les jours à 06:00 UTC."

#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Restauration d'essai (08/10/2026). Une sauvegarde jamais restauree n'est
# qu'une hypothese : ce script restaure le dernier dump dans une base
# temporaire du conteneur db, compte les pieces, puis supprime cette base.
# La base de production n'est jamais touchee.
#
#   ~/hakili_gestion_caisse/backup/restauration_essai.sh            (dernier dump)
#   ~/hakili_gestion_caisse/backup/restauration_essai.sh <fichier>  (un dump precis)
# A faire une fois maintenant, puis chaque trimestre.
# ---------------------------------------------------------------------------
set -uo pipefail
PROJET="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJET" || exit 1
lire_env() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"'\r'; }
UTILISATEUR="$(lire_env POSTGRES_USER)"; UTILISATEUR="${UTILISATEUR:-hakili_admin}"
BASE="$(lire_env POSTGRES_DB)";         BASE="${BASE:-Hakili_compta}"

FICHIER="${1:-$(ls -1t backup/sauvegardes/hakili_*.dump 2>/dev/null | head -1)}"
if [ -z "$FICHIER" ] || [ ! -s "$FICHIER" ]; then
    echo "Aucune sauvegarde trouvee dans backup/sauvegardes." >&2
    exit 1
fi
ESSAI="restauration_essai"
psql_db() { docker compose exec -T db psql -U "$UTILISATEUR" -d "$1" -v ON_ERROR_STOP=1 -qAt -c "$2"; }

psql_db postgres "DROP DATABASE IF EXISTS $ESSAI" && psql_db postgres "CREATE DATABASE $ESSAI" || exit 1
if ! docker compose exec -T db pg_restore -U "$UTILISATEUR" -d "$ESSAI" --no-owner < "$FICHIER"; then
    echo "ECHEC : la restauration de $(basename "$FICHIER") a produit des erreurs." >&2
fi
echo "Sauvegarde : $(basename "$FICHIER")"
echo "Pieces restaurees      : $(psql_db "$ESSAI" 'SELECT count(DISTINCT id_piece) FROM ecritures')"
echo "Pieces en production   : $(psql_db "$BASE" 'SELECT count(DISTINCT id_piece) FROM ecritures')"
echo "Tiers restaures        : $(psql_db "$ESSAI" 'SELECT count(*) FROM tiers')"
psql_db postgres "DROP DATABASE $ESSAI"
echo "Base d'essai supprimee. Les deux nombres de pieces doivent etre proches (ecart = saisies depuis la sauvegarde)."

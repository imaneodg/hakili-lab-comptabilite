#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Sauvegarde de la base, a lancer sur le SERVEUR par le crontab personnel
# d'imane (08/10/2026, C1 de l'audit du 07/10).
#
# Pourquoi ce script : cron_sauvegarde_host.sh exige pg_dump sur l'hote, qui
# n'y est pas installe (et le compte n'a pas sudo pour l'installer). Celui-ci
# passe par le conteneur "db", qui a deja pg_dump dans la bonne version (16).
# Aucun droit administrateur n'est necessaire.
#
# Installation (une fois) :
#   chmod +x ~/hakili_gestion_caisse/backup/sauvegarde.sh
#   crontab -e    puis ajouter la ligne :
#   30 22 * * * ~/hakili_gestion_caisse/backup/sauvegarde.sh >> ~/hakili_gestion_caisse/backup/sauvegardes/journal.log 2>&1
#
# Copie hors du serveur (fortement conseillee) : definir HAKILI_BACKUP_RCLONE_REMOTE
# dans .env (ex. hakili-backup:hakili-lab/postgres) si rclone est disponible.
# ---------------------------------------------------------------------------
set -uo pipefail

PROJET="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJET" || exit 1
DOSSIER="$PROJET/backup/sauvegardes"
RETENTION_JOURS="${HAKILI_BACKUP_RETENTION_JOURS:-30}"
mkdir -p "$DOSSIER"

maintenant() { date "+%Y-%m-%d %H:%M:%S"; }

# Lit une variable de .env sans executer le fichier.
lire_env() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"'\r'; }
UTILISATEUR="$(lire_env POSTGRES_USER)"; UTILISATEUR="${UTILISATEUR:-hakili_admin}"
BASE="$(lire_env POSTGRES_DB)";         BASE="${BASE:-Hakili_compta}"
DISTANT="${HAKILI_BACKUP_RCLONE_REMOTE:-$(lire_env HAKILI_BACKUP_RCLONE_REMOTE)}"

FICHIER="$DOSSIER/hakili_$(date +%Y%m%d_%H%M).dump"
TEMP="$FICHIER.partiel"

if ! docker compose exec -T db pg_dump -U "$UTILISATEUR" -d "$BASE" -Fc > "$TEMP"; then
    echo "$(maintenant)  ECHEC : pg_dump dans le conteneur db a echoue." >&2
    rm -f "$TEMP"
    exit 1
fi
# Un dump vide ou tronque ne doit jamais remplacer une bonne sauvegarde.
if [ ! -s "$TEMP" ] || ! docker compose exec -T db pg_restore --list < "$TEMP" > /dev/null 2>&1; then
    echo "$(maintenant)  ECHEC : le fichier produit n'est pas une sauvegarde lisible." >&2
    rm -f "$TEMP"
    exit 1
fi
mv "$TEMP" "$FICHIER"
echo "$(maintenant)  OK : $(basename "$FICHIER") ($(du -h "$FICHIER" | cut -f1))."

if [ -n "$DISTANT" ]; then
    if command -v rclone > /dev/null 2>&1 && rclone copy "$FICHIER" "$DISTANT"; then
        echo "$(maintenant)  Copie hors site : OK ($DISTANT)."
    else
        echo "$(maintenant)  ECHEC de la copie hors site vers $DISTANT (la sauvegarde locale existe)." >&2
    fi
fi

find "$DOSSIER" -name 'hakili_*.dump' -mtime +"$RETENTION_JOURS" -delete
exit 0

#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Lance backup/pg_backup.py depuis la machine HOTE (jamais depuis le
# conteneur app) et l'ajoute au cron du serveur.
#
# Ajoute le 22/09/2026 (m8 de l'audit du 18/09/2026) : docker-compose.yml
# montait ./backup/sauvegardes:/app/backup/sauvegardes dans le service app,
# ce qui laissait croire que les sauvegardes s'y executaient automatiquement.
# En realite, rien ne les declenchait jamais (aucun cron ni tache planifiee
# dans l'image app), et meme declenchees, elles auraient echoue : l'image
# app (voir Dockerfile) n'installe pas le client PostgreSQL, donc le binaire
# pg_dump qu'appelle pg_backup.py n'existe pas dans ce conteneur.
#
# Plutot que d'alourdir l'image app avec postgresql-client et un ordonnanceur
# (cron, supervisor...) pour un seul job quotidien, ce script tourne sur
# l'HOTE : le service db publie deja PostgreSQL sur 127.0.0.1:5432 (voir
# docker-compose.yml), donc pg_dump installe sur l'hote s'y connecte
# directement, sans toucher a Docker. C'est aussi ce que .env.example
# suppose deja (DATABASE_URL=postgresql://...@localhost:5432/...).
#
# Prerequis sur l'hote (une seule fois) :
#   sudo apt-get install postgresql-client   # fournit pg_dump
#   pip install python-dotenv                # ou: pip install -r requirements.txt
#
# Installation (une seule fois), avec le vrai chemin du depot :
#   crontab -e
#   0 2 * * *  /chemin/vers/HAKILI_LAB_postgres_2/backup/cron_sauvegarde_host.sh >> /var/log/hakili_backup.log 2>&1
#
# Le script s'arrete immediatement et avec un message clair si pg_dump ou
# python3 sont introuvables, et journalise aussi l'echec de pg_backup.py
# lui-meme (voir plus bas) : une sauvegarde qui echoue doit se voir dans
# /var/log/hakili_backup.log, jamais disparaitre silencieusement dans un
# cron qui "tourne" sans rien produire.
# ---------------------------------------------------------------------------

set -uo pipefail
# Pas de "set -e" : le code de sortie de pg_backup.py est capture
# explicitement ci-dessous pour etre journalise avant de se propager - sous
# "set -e", la ligne "CODE=$?" ne serait jamais atteinte, le script
# s'arreterait a l'echec de la commande precedente sans le message clair
# qu'on cherche justement a produire.

DOSSIER_PROJET="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DOSSIER_PROJET"

horodatage() { date "+%Y-%m-%d %H:%M:%S"; }

if ! command -v pg_dump >/dev/null 2>&1; then
    echo "$(horodatage)  ECHEC sauvegarde : pg_dump introuvable sur cette machine. " \
         "Installer le client PostgreSQL (postgresql-client) avant de reessayer." >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "$(horodatage)  ECHEC sauvegarde : python3 introuvable sur cette machine." >&2
    exit 1
fi

if [ ! -f .env ]; then
    echo "$(horodatage)  ECHEC sauvegarde : fichier .env absent de $DOSSIER_PROJET " \
         "(DATABASE_URL introuvable)." >&2
    exit 1
fi

echo "$(horodatage)  Lancement de la sauvegarde (pg_backup.py)."
python3 backup/pg_backup.py
CODE=$?

if [ "$CODE" -eq 0 ]; then
    echo "$(horodatage)  Sauvegarde terminee avec succes."
else
    echo "$(horodatage)  ECHEC sauvegarde : pg_backup.py a renvoye le code $CODE." >&2
fi

exit "$CODE"

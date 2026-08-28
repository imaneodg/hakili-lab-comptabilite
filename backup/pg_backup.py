#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# Sauvegarde automatique de la base HAKILI LAB
#
# Produit un dump Postgres au format "custom" (compresse, restaurable avec
# pg_restore, y compris sur une base vide ou dans une base differente). Purge
# ensuite les sauvegardes plus vieilles que RETENTION_JOURS, mais ne descend
# jamais sous MIN_SAUVEGARDES fichiers meme si tous sont vieux : une purge
# qui tournerait un jour ou pg_dump echouerait silencieusement en amont ne
# doit jamais pouvoir effacer la seule sauvegarde valable restante.
#
# Usage :
#   python backup/pg_backup.py
#
# A planifier (voir README.md) : une fois par jour suffit pour une
# comptabilite de cette taille, plus souvent si le volume de saisie
# l'impose. Le nom du fichier inclut la date et l'heure, deux executions le
# meme jour ne s'ecrasent donc jamais.
# ---------------------------------------------------------------------------

import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DOSSIER_SAUVEGARDES = Path(os.environ.get("HAKILI_BACKUP_DIR", Path(__file__).parent / "sauvegardes"))
RETENTION_JOURS = int(os.environ.get("HAKILI_BACKUP_RETENTION_JOURS", 30))
MIN_SAUVEGARDES = 3
FICHIER_JOURNAL = DOSSIER_SAUVEGARDES / "journal.log"


def _log(message):
    ligne = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}"
    print(ligne)
    DOSSIER_SAUVEGARDES.mkdir(parents=True, exist_ok=True)
    with open(FICHIER_JOURNAL, "a", encoding="utf-8") as f:
        f.write(ligne + "\n")


def _args_connexion():
    """pg_dump accepte directement une DATABASE_URL comme premier argument.
    A defaut, on retombe sur les variables PG* standard, deja lues par
    libpq elle-meme (pas besoin de les repasser explicitement)."""
    url = os.environ.get("DATABASE_URL")
    return [url] if url else []


def sauvegarder():
    DOSSIER_SAUVEGARDES.mkdir(parents=True, exist_ok=True)
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
    fichier = DOSSIER_SAUVEGARDES / f"hakilisso_{horodatage}.dump"
    fichier_tmp = fichier.with_suffix(".dump.tmp")

    commande = ["pg_dump", "-Fc", "-f", str(fichier_tmp), *_args_connexion()]
    resultat = subprocess.run(commande, capture_output=True, text=True)

    if resultat.returncode != 0 or not fichier_tmp.exists() or fichier_tmp.stat().st_size == 0:
        fichier_tmp.unlink(missing_ok=True)
        _log(f"ECHEC de la sauvegarde : {resultat.stderr.strip() or 'pg_dump a echoue sans message.'}")
        return False

    # Renomme seulement une fois le dump termine et non vide : un fichier
    # ".dump" present sur disque est donc toujours une sauvegarde complete,
    # jamais une sauvegarde coupee en cours d'ecriture.
    fichier_tmp.rename(fichier)
    taille_ko = fichier.stat().st_size // 1024
    _log(f"Sauvegarde reussie : {fichier.name} ({taille_ko} Ko)")
    return True


def purger():
    dumps = sorted(DOSSIER_SAUVEGARDES.glob("hakilisso_*.dump"), key=lambda p: p.stat().st_mtime)
    if len(dumps) <= MIN_SAUVEGARDES:
        return
    limite = datetime.now() - timedelta(days=RETENTION_JOURS)
    a_garder = dumps[-MIN_SAUVEGARDES:]
    for f in dumps[:-MIN_SAUVEGARDES]:
        if datetime.fromtimestamp(f.stat().st_mtime) < limite:
            f.unlink()
            _log(f"Ancienne sauvegarde supprimee : {f.name}")


if __name__ == "__main__":
    ok = sauvegarder()
    purger()
    sys.exit(0 if ok else 1)

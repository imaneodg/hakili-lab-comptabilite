"""Ne garde dans la base que les pieces du DEBUT au FIN (bornes incluses).
Tout le reste est supprime definitivement, quel que soit le statut
(y compris les pieces exportees), sans historique. L'historique des
suppressions est vide et les compteurs de numerotation sont recalcules.
Une seule transaction : en cas d'erreur, rien n'est modifie.

Usage (sur le serveur) :
    docker compose exec app python garder_periode.py
"""
import os
import re

import psycopg2
from dotenv import load_dotenv

DEBUT = "2026-04-01"
FIN = "2026-04-04"

load_dotenv()
DSN = os.environ.get("DATABASE_URL")
if not DSN:
    raise RuntimeError("DATABASE_URL introuvable")


def recalculer_compteurs(cur):
    """Chaque compteur revient au plus grand numero encore utilise ; un
    compteur sans piece restante est supprime (le mois repart a 1)."""
    cur.execute("SELECT journal, centre, date_piece, num_provisoire, num_definitif, "
                "reference_transfert FROM ecritures")
    utilises = {}

    def noter(cle, n):
        utilises[cle] = max(utilises.get(cle, 0), n)

    for journal, centre, d, prov, dfn, trf in cur.fetchall():
        mois = d.strftime("%Y%m")
        m = re.search(r"(\d+)$", prov or "")
        if m:
            noter(f"prov:{centre}:{mois}", int(m.group(1)))
        m = re.search(r"(\d{3})$", dfn or "")
        if m:
            noter(f"def:{journal}:{mois}", int(m.group(1)))
        m = re.match(r"TRF-(\d{6})-(\d+)$", trf or "")
        if m:
            noter(f"trf:{m.group(1)}", int(m.group(2)))

    cur.execute("DELETE FROM compteurs WHERE NOT (cle = ANY(%s))", (list(utilises),))
    for cle, n in utilises.items():
        cur.execute("INSERT INTO compteurs (cle, valeur) VALUES (%s, %s) "
                    "ON CONFLICT (cle) DO UPDATE SET valeur = EXCLUDED.valeur", (cle, n))


def compter(cur):
    cur.execute("SELECT count(*), count(DISTINCT id_piece), min(date_piece), max(date_piece) "
                "FROM ecritures")
    return cur.fetchone()


conn = psycopg2.connect(DSN)
try:
    cur = conn.cursor()
    print("AVANT :", compter(cur))
    cur.execute("DELETE FROM ecritures WHERE date_piece < %s OR date_piece > %s", (DEBUT, FIN))
    print(f"{cur.rowcount} lignes supprimees.")
    cur.execute("DELETE FROM suppressions_ecritures")
    recalculer_compteurs(cur)
    conn.commit()
    print("APRES (lignes, pieces, 1re date, derniere date) :", compter(cur))
except Exception as e:
    conn.rollback()
    print("ERREUR :", e, "- aucune modification.")
    raise
finally:
    conn.close()

# ---------------------------------------------------------------------------
# Comparaison base <-> plans Sage - LECTURE SEULE
#
# Repond a la seule question qui bloque le chargement : que deviennent les
# fiches deja en base face aux plans exportes de Sage ?
#   - lesquelles se recouvrent (intitule corrige, aucun risque)
#   - lesquelles n'existent pas dans Sage (doublons a arbitrer)
#   - lesquelles sont citees par des ecritures (donc non supprimables)
#
# Ne fait que des SELECT et lit deux classeurs. N'ecrit rien.
#
# Usage, depuis la racine du projet, venv active :
#     python outils/comparer_plans.py
# ---------------------------------------------------------------------------

import os
import sys
from pathlib import Path

import openpyxl
import psycopg2
from dotenv import load_dotenv

load_dotenv()

RACINE = Path(__file__).resolve().parent.parent
F_TIERS = RACINE / "Plan_tiers.xlsx"
F_COMPTES = RACINE / "Plan_comptable.xlsx"


def titre(t):
    print()
    print(t)
    print("-" * len(t))


def lire(fichier, feuille, col_code, col_intitule):
    if not fichier.exists():
        print(f"Classeur introuvable : {fichier.name}")
        sys.exit(1)
    ws = openpyxl.load_workbook(fichier, data_only=True)[feuille]
    lignes = {}
    for r in ws.iter_rows(min_row=9, values_only=True):
        code, intitule = r[col_code], r[col_intitule]
        if code and intitule:
            lignes[str(code).strip()] = str(intitule).strip()
    return lignes


sage_tiers = lire(F_TIERS, "Plan tiers", 0, 4)
sage_comptes = lire(F_COMPTES, "Plan comptable", 0, 3)
print(f"Plan Sage lu : {len(sage_comptes)} comptes, {len(sage_tiers)} tiers")

DSN = os.environ.get("DATABASE_URL")
conn = psycopg2.connect(DSN)
visible = DSN.split("@")[-1] if "@" in DSN else DSN
print(f"Base interrogee : ...@{visible}")

with conn, conn.cursor() as cur:

    cur.execute("SELECT code_tiers, intitule FROM tiers")
    base_tiers = dict(cur.fetchall())
    cur.execute("SELECT compte, intitule FROM comptes")
    base_comptes = dict(cur.fetchall())

    # Codes reellement cites par des ecritures : ceux-la ne peuvent pas
    # simplement disparaitre, une piece les reference.
    cur.execute("SELECT DISTINCT code_tiers FROM ecritures WHERE code_tiers <> ''")
    tiers_utilises = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT DISTINCT compte FROM ecritures")
    comptes_utilises = {r[0] for r in cur.fetchall()}

    titre("COMPTES")
    communs = set(base_comptes) & set(sage_comptes)
    print(f"  en base           {len(base_comptes):>5}")
    print(f"  dans Sage         {len(sage_comptes):>5}")
    print(f"  communs           {len(communs):>5}  (intitule aligne sur Sage au chargement)")
    absents_sage = sorted(set(base_comptes) - set(sage_comptes))
    print(f"  en base, pas dans Sage : {len(absents_sage)}")
    for c in absents_sage:
        marque = "  <-- UTILISE par des ecritures" if c in comptes_utilises else ""
        print(f"    {c}  {base_comptes[c]}{marque}")
    print(f"  dans Sage, pas en base : {len(set(sage_comptes) - set(base_comptes))}  (a ajouter)")

    titre("TIERS")
    communs_t = set(base_tiers) & set(sage_tiers)
    orphelins = sorted(set(base_tiers) - set(sage_tiers))
    print(f"  en base           {len(base_tiers):>5}")
    print(f"  dans Sage         {len(sage_tiers):>5}")
    print(f"  communs           {len(communs_t):>5}  (intitule corrige, aucun risque)")
    print(f"  a ajouter         {len(set(sage_tiers) - set(base_tiers)):>5}")
    print(f"  en base, INCONNUS de Sage : {len(orphelins)}")

    orph_utilises = [c for c in orphelins if c in tiers_utilises]
    print(f"    dont cites par des ecritures : {len(orph_utilises)}")

    if communs_t:
        print("\n  Exemples d'intitules qui vont etre corriges :")
        for c in sorted(communs_t)[:10]:
            print(f"    {c:24} '{base_tiers[c]}'  ->  '{sage_tiers[c]}'")

    if orphelins:
        print("\n  Fiches inconnues de Sage (les 30 premieres) :")
        for c in orphelins[:30]:
            marque = "  <-- CITE par une ecriture" if c in tiers_utilises else ""
            print(f"    {c:24} {base_tiers[c]}{marque}")

    titre("EXPORT SAGE : ce qui serait refuse aujourd'hui")
    bloquants_c = sorted(c for c in comptes_utilises if c not in sage_comptes)
    bloquants_t = sorted(t for t in tiers_utilises if t not in sage_tiers)
    print(f"  comptes cites par des ecritures et absents de Sage : {len(bloquants_c)}")
    for c in bloquants_c:
        print(f"    {c}  {base_comptes.get(c, '?')}")
    print(f"  tiers cites par des ecritures et absents de Sage   : {len(bloquants_t)}")
    for t in bloquants_t[:20]:
        print(f"    {t}  {base_tiers.get(t, '?')}")

conn.close()
print("\nTermine. Aucune ecriture n'a ete faite.")

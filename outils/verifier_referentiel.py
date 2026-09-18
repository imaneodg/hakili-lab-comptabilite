# ---------------------------------------------------------------------------
# Diagnostic du referentiel - LECTURE SEULE
#
# Repond a une seule question : que contient reellement la base par rapport
# a ce que l'application suppose ? Ne fait que des SELECT, n'ecrit rien,
# ne modifie aucun fichier.
#
# Usage, depuis la racine du projet, venv active :
#     python outils/verifier_referentiel.py
# ---------------------------------------------------------------------------

import os
import sys

from dotenv import load_dotenv
import psycopg2

load_dotenv()

DSN = os.environ.get("DATABASE_URL")
if not DSN:
    print("DATABASE_URL introuvable dans .env — impossible de se connecter.")
    sys.exit(1)

# Ne jamais afficher le mot de passe a l'ecran.
visible = DSN.split("@")[-1] if "@" in DSN else DSN
print(f"Base interrogee : ...@{visible}\n")


def titre(t):
    print()
    print(t)
    print("-" * len(t))


try:
    conn = psycopg2.connect(DSN)
except Exception as e:
    print(f"Connexion impossible : {e}")
    print("\nSi la base est sur le serveur, ce script doit tourner sur le serveur,")
    print("ou passer par un tunnel SSH vers 127.0.0.1:5432.")
    sys.exit(1)

with conn, conn.cursor() as cur:

    titre("1. Volumes")
    for table in ("comptes", "tiers", "journaux", "centres", "utilisateurs", "ecritures"):
        cur.execute(f"SELECT count(*) FROM {table}")
        print(f"  {table:16} {cur.fetchone()[0]:>6}")

    titre("2. Plan tiers : charge ou pas ?")
    cur.execute("SELECT count(*) FROM tiers WHERE code_tiers LIKE '411%'")
    n411 = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM tiers WHERE code_tiers LIKE '401%'")
    n401 = cur.fetchone()[0]
    print(f"  eleves (411)      {n411:>6}   (le plan Sage en compte 1280)")
    print(f"  fournisseurs (401){n401:>6}   (le plan Sage en compte  164)")
    # Un intitule en un seul mot = fiche creee a la volee par resoudre_tiers,
    # jamais un nom venu du plan Sage (qui est toujours "NOM PRENOM").
    cur.execute("SELECT count(*) FROM tiers WHERE intitule NOT LIKE '% %'")
    print(f"  intitules en un seul mot : {cur.fetchone()[0]}  "
          "(creees a la saisie, pas issues de Sage)")
    print("\n  Echantillon :")
    cur.execute("SELECT code_tiers, intitule FROM tiers ORDER BY code_tiers LIMIT 15")
    for code, nom in cur.fetchall():
        print(f"    {nom:38} ({code})")

    titre("3. Compte d'attente 471000")
    cur.execute("SELECT intitule FROM comptes WHERE compte = '471000'")
    r = cur.fetchone()
    print(f"  en base : {r[0]}" if r else "  ABSENT de la base")
    print("  absent du plan comptable Sage (verifie dans Plan_comptable.xlsx)")
    cur.execute("SELECT count(DISTINCT id_piece) FROM ecritures WHERE compte = '471000'")
    print(f"  pieces qui l'utilisent deja : {cur.fetchone()[0]}")

    titre("4. Journal Banque : quel compte ?")
    cur.execute("SELECT journal, intitule, compte_contrepartie FROM journaux ORDER BY journal")
    for j, lib, cc in cur.fetchall():
        cur.execute("SELECT intitule FROM comptes WHERE compte = %s", (cc,))
        r = cur.fetchone()
        print(f"  {j:8} {lib:26} -> {cc or '(aucun)'}  {r[0] if r else ''}")
    print("  rappel Sage : 521100 = 'BDU', 521200 = 'Coris bank international'")

    titre("5. Codes d'acces encore en clair")
    cur.execute("SELECT identifiant, centre, role FROM utilisateurs "
                "WHERE code_acces NOT LIKE '$2%' ORDER BY identifiant")
    clairs = cur.fetchall()
    if clairs:
        for ident, centre, role in clairs:
            print(f"  {ident:16} {centre:6} {role}")
        print(f"  -> {len(clairs)} compte(s) dont le code est lisible en base.")
    else:
        print("  aucun : tous les codes sont haches. Bien.")

    titre("6. Migrations appliquees")
    cur.execute("SELECT to_regclass('schema_migrations')")
    if cur.fetchone()[0] is None:
        print("  table schema_migrations ABSENTE : aucun registre des migrations.")
    else:
        cur.execute("SELECT version, applique_le FROM schema_migrations ORDER BY version")
        for v, d in cur.fetchall():
            print(f"  {v:52} {d:%Y-%m-%d}")

conn.close()
print("\nTermine. Aucune ecriture n'a ete faite.")

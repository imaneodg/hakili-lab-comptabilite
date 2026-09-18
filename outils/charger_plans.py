# ---------------------------------------------------------------------------
# Lanceur des scripts de chargement (plan comptable, plan tiers)
#
# Existe parce que psql n'est pas toujours dans le PATH sous Windows, alors
# que psycopg2 est deja dans le venv du projet. Fait exactement ce que ferait
# psql : execute le fichier instruction par instruction, dans la transaction
# declaree par le fichier lui-meme (BEGIN ... COMMIT), et affiche les
# resultats des SELECT de compte-rendu.
#
# Les meta-commandes psql (\set, \echo) sont interpretees ici : \echo affiche
# son texte, \set est sans objet puisque la moindre exception annule tout.
#
# Usage, depuis la racine du projet, venv active :
#     python outils/charger_plans.py sql/charger_plan_comptable.sql
#     python outils/charger_plans.py sql/charger_plan_tiers.sql
#
# Ou, pour enchainer les deux dans le bon ordre (le plan comptable d'abord :
# tiers.compte_collectif a une cle etrangere vers comptes) :
#     python outils/charger_plans.py
# ---------------------------------------------------------------------------

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

RACINE = Path(__file__).resolve().parent.parent
PAR_DEFAUT = ["sql/charger_plan_comptable.sql", "sql/charger_plan_tiers.sql"]


def decouper(sql):
    """Decoupe un script en instructions, en respectant les chaines SQL.

    Un simple split(";") couperait au milieu d'un intitule contenant un
    point-virgule. On suit donc l'etat "dans une chaine", en tenant compte de
    l'echappement par doublement ('') propre a SQL, et on sort les
    meta-commandes psql (lignes commencant par \\) telles quelles.
    """
    instructions = []
    courant = []
    dans_chaine = False
    i = 0
    debut_de_ligne = True
    while i < len(sql):
        c = sql[i]

        # Meta-commande psql : toute la ligne, hors chaine.
        if debut_de_ligne and not dans_chaine and c == "\\":
            fin = sql.find("\n", i)
            fin = len(sql) if fin == -1 else fin
            instructions.append(("meta", sql[i:fin].strip()))
            i = fin + 1
            continue

        # Commentaire -- : jusqu'a la fin de la ligne, hors chaine.
        if not dans_chaine and c == "-" and sql[i:i + 2] == "--":
            fin = sql.find("\n", i)
            if fin == -1:
                break
            courant.append("\n")
            i = fin + 1
            debut_de_ligne = True
            continue

        if c == "'":
            if dans_chaine and sql[i:i + 2] == "''":
                courant.append("''")
                i += 2
                debut_de_ligne = False
                continue
            dans_chaine = not dans_chaine

        if c == ";" and not dans_chaine:
            texte = "".join(courant).strip()
            if texte:
                instructions.append(("sql", texte + ";"))
            courant = []
            i += 1
            debut_de_ligne = True
            continue

        courant.append(c)
        debut_de_ligne = (c == "\n")
        i += 1

    reste = "".join(courant).strip()
    if reste:
        instructions.append(("sql", reste))
    return instructions


def afficher(cur):
    """Affiche le resultat d'un SELECT, facon psql : en-tetes, colonnes
    alignees sur le contenu le plus large."""
    if cur.description is None:
        return
    entetes = [d.name for d in cur.description]
    lignes = [["" if v is None else str(v) for v in r] for r in cur.fetchall()]
    largeurs = [max(len(e), *(len(l[i]) for l in lignes)) if lignes else len(e)
                for i, e in enumerate(entetes)]
    print("  " + " | ".join(e.ljust(largeurs[i]) for i, e in enumerate(entetes)))
    print("  " + "-+-".join("-" * l for l in largeurs))
    for l in lignes:
        print("  " + " | ".join(l[i].ljust(largeurs[i]) for i in range(len(entetes))))
    print(f"  ({len(lignes)} ligne{'s' if len(lignes) > 1 else ''})")


def jouer(conn, chemin):
    fichier = RACINE / chemin
    if not fichier.exists():
        print(f"Fichier introuvable : {fichier}")
        return False

    sql = fichier.read_text(encoding="utf-8")
    instructions = decouper(sql)
    nb_sql = sum(1 for genre, _ in instructions if genre == "sql")
    print(f"\n{'=' * 70}")
    print(f"{fichier.name}  ({nb_sql} instructions)")
    print("=" * 70)

    cur = conn.cursor()
    try:
        for genre, texte in instructions:
            if genre == "meta":
                # \echo 'texte' -> on affiche ; \set -> sans objet ici.
                if texte.startswith("\\echo"):
                    reste = texte[5:].strip()
                    if reste.startswith("'") and reste.endswith("'"):
                        # Dans un \echo, psql lit '' comme une apostrophe.
                        reste = reste[1:-1].replace("''", "'")
                    print(reste)
                continue
            cur.execute(texte)
            afficher(cur)
    except Exception as e:
        conn.rollback()
        print(f"\nECHEC — rien n'a ete applique.\n  {type(e).__name__} : {e}")
        return False
    finally:
        cur.close()
    return True


def main():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL introuvable dans .env.")
        sys.exit(1)

    fichiers = sys.argv[1:] or PAR_DEFAUT
    visible = dsn.split("@")[-1] if "@" in dsn else dsn
    print(f"Base : ...@{visible}")

    try:
        # autocommit : ce sont les BEGIN/COMMIT ecrits dans les fichiers qui
        # delimitent la transaction, exactement comme sous psql.
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
    except Exception as e:
        print(f"Connexion impossible : {e}")
        sys.exit(1)

    try:
        for f in fichiers:
            if not jouer(conn, f):
                sys.exit(1)
    finally:
        conn.close()

    print("\nTermine.")


if __name__ == "__main__":
    main()

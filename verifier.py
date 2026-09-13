# ---------------------------------------------------------------------------
# Verifie que le projet est encore fiable apres une modification : recree une
# base de test jetable a partir de sql/schema.sql + sql/seed.sql, puis lance
# la vraie suite pytest dessus. Ne touche JAMAIS a Hakili_compta - la base
# reelle n'est ni lue ni modifiee par ce script.
#
# Usage (a la racine du projet, environnement virtuel active) :
#     python verifier.py
#
# Prerequis, a faire une seule fois : creer dans pgAdmin, sur le meme
# serveur Postgres que Hakili_compta, une base VIDE nommee "hakili_test"
# (clic droit sur Databases -> Create -> Database -> Database name:
# hakili_test -> onglet "Definition" -> Encoding: UTF8). Le script se charge
# ensuite de tout le reste a chaque execution : il efface et recree le
# contenu de cette base de test a partir des fichiers reels du projet,
# jamais de Hakili_compta.
#
# Si "hakili_test" a ete creee sans forcer Encoding: UTF8 (frequent sur un
# Postgres installe avec une locale Windows francaise, qui propose souvent
# WIN1252 par defaut), schema.sql/seed.sql (qui contiennent tres
# occasionnellement un accent, ex. "pièce") peuvent declencher une
# UnicodeDecodeError a l'execution au lieu d'un message clair - corrige
# ci-dessous en forcant explicitement l'encodage de la connexion.
# ---------------------------------------------------------------------------

import os
import subprocess
import sys
import traceback
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg2
from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parent
NOM_BASE_TEST = "hakili_test"


def url_base_test():
    """Reprend l'hote/le port/l'utilisateur/le mot de passe de DATABASE_URL
    (.env), mais force le nom de la base sur NOM_BASE_TEST - jamais sur
    Hakili_compta, quoi que contienne le .env."""
    load_dotenv(RACINE / ".env")
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL absent de .env - impossible de savoir a quel serveur Postgres se connecter.")
    morceaux = urlsplit(url)
    return urlunsplit(morceaux._replace(path=f"/{NOM_BASE_TEST}"))


def _etape(nom, fn):
    """Execute fn() en nommant l'etape dans toute exception : sans ca, une
    UnicodeDecodeError generique ne dit pas QUELLE operation (connexion,
    lecture d'un fichier precis, execution SQL) l'a declenchee - impossible
    a corriger a l'aveugle. Le traceback complet reste imprime en plus."""
    try:
        return fn()
    except Exception:
        print(f"\n--- Echec a l'etape : {nom} ---")
        traceback.print_exc()
        raise RuntimeError(f"echec a l'etape « {nom} » (traceback complet ci-dessus)")


def recreer_base_test(url_test):
    print(f"Recreation de la base de test '{NOM_BASE_TEST}' a partir de sql/schema.sql et sql/seed.sql...")
    conn = _etape("connexion a hakili_test", lambda: psycopg2.connect(url_test))
    # Force l'encodage de la connexion independamment de celui negocie par
    # defaut avec le serveur : sur certaines installations Postgres/Windows,
    # une base creee sans preciser Encoding: UTF8 herite de l'encodage de la
    # locale systeme (souvent WIN1252 en francais), ce qui fait echouer
    # l'envoi des rares caracteres accentues de schema.sql/seed.sql avec une
    # UnicodeDecodeError peu comprehensible. UTF8 explicite ici couvre ce cas
    # (WIN1252/LATIN1 savent tous deux representer les accents utilises) et
    # ne change rien quand la base est deja en UTF8.
    _etape("reglage de l'encodage client (UTF8)", lambda: conn.set_client_encoding("UTF8"))
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            _etape("DROP/CREATE SCHEMA public",
                   lambda: cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
            texte_schema = _etape("lecture de sql/schema.sql",
                                   lambda: (RACINE / "sql" / "schema.sql").read_text(encoding="utf-8"))
            _etape("execution de sql/schema.sql", lambda: cur.execute(texte_schema))
            texte_seed = _etape("lecture de sql/seed.sql",
                                 lambda: (RACINE / "sql" / "seed.sql").read_text(encoding="utf-8"))
            _etape("execution de sql/seed.sql", lambda: cur.execute(texte_seed))
    finally:
        conn.close()


def lancer_tests(url_test):
    print("Lancement de la suite de tests (pytest tests/ -v)...\n")
    env = os.environ.copy()
    env["DATABASE_URL"] = url_test
    resultat = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-v"], cwd=RACINE, env=env)
    return resultat.returncode


def main():
    url_test = url_base_test()
    try:
        recreer_base_test(url_test)
    except Exception as e:
        sys.exit(
            f"Impossible de preparer la base de test '{NOM_BASE_TEST}' : {e}\n"
            f"Verifiez qu'elle existe deja (a creer une seule fois dans pgAdmin, voir "
            f"l'entete de ce fichier) et que DATABASE_URL dans .env est correct."
        )
    code = lancer_tests(url_test)
    print("\n" + ("TOUT EST OK - rien n'est casse." if code == 0 else
                  "DES TESTS ONT ECHOUE - voir le detail ci-dessus avant de deployer quoi que ce soit."))
    sys.exit(code)


if __name__ == "__main__":
    main()
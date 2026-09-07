# ---------------------------------------------------------------------------
# conftest.py (racine du projet)
#
# Necessaire pour deux raisons :
#   1. Ancrer pytest sur la racine du projet pour que les imports du projet
#      se resolvent quel que soit le repertoire depuis lequel pytest est lance.
#   2. Charger le .env AVANT que tests/test_auth.py, tests/test_utils.py ou
#      tests/test_analyse.py n'importent logic.donnees : ce module ouvre une
#      connexion Postgres reelle des l'import (voir logic/donnees.py, ligne
#      "_POOL = ThreadedConnectionPool(...)"), avec DATABASE_URL lu depuis
#      les variables d'environnement. app.py appelle deja load_dotenv() avant
#      d'importer logic.* pour cette meme raison.
# ---------------------------------------------------------------------------

from dotenv import load_dotenv

load_dotenv()

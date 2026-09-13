# ---------------------------------------------------------------------------
# conftest.py (racine du projet)
#
# Necessaire pour deux raisons :
#   1. Ancrer pytest sur la racine du projet, pour que "import logic.analyse"
#      et "import logic.donnees" se resolvent sans avoir a lancer pytest
#      d'une facon particuliere.
#   2. Charger le .env AVANT que tests/test_auth.py, tests/test_utils.py ou
#      tests/test_analyse.py n'importent logic.donnees : ce module ouvre une
#      connexion Postgres reelle des l'import (voir logic/donnees.py, ligne
#      "_POOL = ThreadedConnectionPool(...)"), avec DATABASE_URL lu depuis
#      les variables d'environnement. app.py et mcp_server/server.py
#      appellent deja load_dotenv() avant d'importer logic.* pour cette
#      meme raison ; les tests doivent faire pareil, sinon psycopg2 tente de
#      se connecter avec des parametres par defaut (localhost, utilisateur
#      du systeme, sans mot de passe) au lieu de Hakili_compta.
# ---------------------------------------------------------------------------

from dotenv import load_dotenv

load_dotenv()

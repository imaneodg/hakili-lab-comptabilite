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


import sys  # noqa: E402
from datetime import date  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _date_du_jour_des_tests(monkeypatch):
    """Les pieces de test sont datees de 2098-2099 (jamais melees aux vraies) :
    pour elles, "aujourd'hui" est le 1er janvier 2100. Le controle des dates
    futures a ses propres tests, qui passent leur date du jour explicitement."""
    dl = sys.modules.get("logic.donnees")
    if dl is not None and hasattr(dl, "_aujourd_hui"):
        monkeypatch.setattr(dl, "_aujourd_hui", lambda: date(2100, 1, 1))
    yield

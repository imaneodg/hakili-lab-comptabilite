# ---------------------------------------------------------------------------
# Point d'entree du serveur MCP - Assistant IA Hakili Lab
#
# Difference avec l'ancien server.py de Finova : plus de reload_data() ni de
# fichier Excel en memoire. Chaque outil lit Hakili_compta (PostgreSQL) au
# moment de l'appel, via logic.donnees, exactement comme le reste de
# l'application Shiny - il n'y a plus qu'une seule source de verite.
#
# Pour ajouter un nouveau groupe d'outils :
#   1. Creer mcp_server/tools/<nom_du_groupe>.py sur le modele de recettes.py
#   2. Ajouter une ligne d'import ci-dessous
#   C'est tout, rien d'autre a modifier ici.
#
# Lancement (depuis la racine du projet Hakili Lab, meme venv que l'app) :
#   python -m mcp_server.server
# ---------------------------------------------------------------------------

from dotenv import load_dotenv

load_dotenv()  # avant tout import de logic.* : c'est la que le pool de
                # connexions Postgres est cree, il a besoin de DATABASE_URL
                # (meme ordre que dans app.py).

from mcp_server.instance import mcp

# --- enregistrement des groupes d'outils -----------------------------------
from mcp_server.tools import recettes       # noqa: F401
from mcp_server.tools import depenses       # noqa: F401
from mcp_server.tools import rentabilite    # noqa: F401
from mcp_server.tools import comparaison    # noqa: F401
from mcp_server.tools import suivi          # noqa: F401
from mcp_server.tools import controle       # noqa: F401
from mcp_server.tools import impayes        # noqa: F401
from mcp_server.tools import personnel      # noqa: F401
from mcp_server.tools import recherche      # noqa: F401


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
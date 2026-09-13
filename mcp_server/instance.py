# ---------------------------------------------------------------------------
# Instance MCP partagee.
#
# Chaque fichier de mcp_server/tools/ importe `mcp` depuis ici et enregistre
# ses outils avec @mcp.tool(). Un seul serveur, un seul point
# d'enregistrement - c'est ce qui evite l'import circulaire que l'on aurait
# si server.py creait l'objet lui-meme et que tools/recettes.py devait
# importer server.py en retour.
# ---------------------------------------------------------------------------

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="hakili-lab-assistant",
    instructions=(
        "Serveur MCP d'analyse financiere et comptable pour Hakili Lab. "
        "Expose des outils regroupes par theme (recettes, depenses, "
        "rentabilite par centre, comparaison de centres, suivi mensuel, "
        "controle) pour repondre en langage naturel a des questions de "
        "pilotage financier sur les donnees reelles de Hakili_compta, "
        "centre par centre et mois par mois."
    ),
)

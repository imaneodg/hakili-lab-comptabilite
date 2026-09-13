# ---------------------------------------------------------------------------
# Outils MCP - Impayes
#
# Categorie marquee indisponible sur decision de la direction (06/09/2026) :
# Hakili_compta ne contient pas d'echeancier par eleve, seulement le solde du
# compte 411000. Un proxy aurait ete possible (comme effectif_actif_centre_mois
# ailleurs dans l'appli), mais la direction a prefere que l'assistant dise
# clairement qu'il ne peut pas repondre plutot que de laisser croire a un
# chiffre d'impayes fiable. La categorie reste suggeree dans le chatbot
# (voir logic/questions_assistant.py) pour que le comptable qui pose la
# question obtienne cette explication au lieu d'un silence ou d'un plantage.
# ---------------------------------------------------------------------------

from typing import Optional

import logic.analyse as an
from mcp_server import portee
from mcp_server.instance import mcp


@mcp.tool()
def situation_impayes(centre: Optional[str] = None) -> dict:
    """Montant des impayes en cours, anciennete des retards (30/60/90 jours),
    et eleve ou famille avec le plus gros retard.

    Indisponible actuellement : il n'existe pas d'echeancier par eleve dans
    Hakili_compta. Renvoie une reponse structuree expliquant pourquoi,
    plutot que d'approximer un chiffre a partir du solde client."""
    centre = portee.resoudre(centre)
    return an.situation_impayes(centre)

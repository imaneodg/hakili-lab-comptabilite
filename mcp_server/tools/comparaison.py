# ---------------------------------------------------------------------------
# Outils MCP - Comparaison de centres
# ---------------------------------------------------------------------------

import logic.analyse as an
from mcp_server import portee
from mcp_server.instance import mcp


@mcp.tool()
def recettes_trimestre(centre: str, mois_fin: str) -> dict:
    """Total des recettes encaissees par un centre sur les 3 mois se
    terminant au mois indique (AAAAMM) inclus."""
    centre = portee.resoudre(centre)
    return {"centre": centre, "mois_fin": mois_fin,
            "recettes_trimestre": an.recettes_centre_trimestre(centre, mois_fin)}


@mcp.tool()
def structure_couts(centre: str, mois: str) -> dict:
    """Depenses rapportees aux recettes du centre sur le mois, en
    pourcentage : plus ce ratio est bas, plus la structure de couts est
    legere."""
    centre = portee.resoudre(centre)
    return an.structure_couts_centre_mois(centre, mois)


@mcp.tool()
def contribution_centres(mois: str) -> list:
    """Part de chaque centre dans le total consolide des recettes du mois."""
    lignes = an.contribution_centres_mois(mois).to_dict("records")
    autorises = set(portee.restreindre_centres([l["centre"] for l in lignes]))
    return [l for l in lignes if l["centre"] in autorises]


@mcp.tool()
def classement_centres_par_recettes_trimestre(mois_fin: str) -> list:
    """Classe tous les centres par recettes cumulees sur les 3 mois se
    terminant a mois_fin (AAAAMM) inclus, du plus au moins eleve."""
    lignes = an.classement_centres_recettes_trimestre(mois_fin).to_dict("records")
    autorises = set(portee.restreindre_centres([l["centre"] for l in lignes]))
    return [l for l in lignes if l["centre"] in autorises]


@mcp.tool()
def classement_structure_couts(mois: str) -> list:
    """Classe les centres par ratio depenses/recettes sur le mois, du plus
    leger (le meilleur) au plus lourd."""
    lignes = an.classement_structure_couts(mois).to_dict("records")
    autorises = set(portee.restreindre_centres([l["centre"] for l in lignes]))
    return [l for l in lignes if l["centre"] in autorises]

# ---------------------------------------------------------------------------
# Outils MCP - Rentabilite par centre
#
# La rentabilite n'est jamais rendue en recettes-depenses en valeur absolue :
# voir logic.analyse.marge_centre_mois et classement_rentabilite_centres pour
# le detail de la formule retenue et pourquoi.
# ---------------------------------------------------------------------------

from typing import Optional

import logic.analyse as an
from mcp_server import portee
from mcp_server.instance import mcp


@mcp.tool()
def marge_centre(centre: str, mois: str) -> dict:
    """Marge en pourcentage d'un centre sur le mois : (recettes - depenses)
    / recettes x 100. Mesure de rentabilite comparable entre centres de
    tailles differentes, contrairement a un simple recettes moins
    depenses en valeur absolue."""
    centre = portee.resoudre(centre)
    return an.marge_centre_mois(centre, mois)


@mcp.tool()
def seuil_rentabilite(centre: str, mois: Optional[str] = None) -> dict:
    """Nombre d'eleves payants necessaire pour couvrir les charges fixes
    d'un centre.

    Indisponible actuellement : suppose un tarif moyen par eleve fiable, qui
    suppose lui-meme une grille tarifaire absente de Hakili_compta. Renvoie
    une reponse structuree expliquant pourquoi plutot que d'inventer un
    seuil a partir d'un proxy trompeur."""
    centre = portee.resoudre(centre)
    return an.seuil_rentabilite_centre(centre, mois)


@mcp.tool()
def recette_par_eleve(centre: str, mois: str) -> dict:
    """Recette encaissee par le centre sur le mois, rapportee au nombre
    d'eleves actifs (proxy calcule sur les ecritures faute de table
    d'inscriptions - a preciser dans la reponse si l'ecart parait
    important)."""
    centre = portee.resoudre(centre)
    return an.recette_par_eleve_centre_mois(centre, mois)


@mcp.tool()
def classement_rentabilite(mois: str) -> list:
    """Classe les centres par marge en pourcentage sur le mois - le centre
    le plus rentable est celui dont la marge est la plus elevee, pas
    necessairement celui qui encaisse le plus."""
    lignes = an.classement_rentabilite_centres(mois).to_dict("records")
    autorises = set(portee.restreindre_centres([l["centre"] for l in lignes]))
    return [l for l in lignes if l["centre"] in autorises]


@mcp.tool()
def effectif_actif(centre: str, mois: str) -> dict:
    """Effectif actif d'un centre sur le mois (proxy calcule sur les
    ecritures, faute de table d'inscriptions - a rappeler dans la reponse si
    la question porte sur un effectif reel)."""
    centre = portee.resoudre(centre)
    return {"centre": centre, "mois": mois, "effectif_proxy": an.effectif_actif_centre_mois(centre, mois)}


@mcp.tool()
def effectif_actif_evolution(centre: str, mois_fin: str, nb_mois: int = 6) -> list:
    """Evolution de l'effectif actif proxy d'un centre, mois par mois, sur
    les nb_mois (6 par defaut) se terminant a mois_fin (AAAAMM) inclus."""
    centre = portee.resoudre(centre)
    return an.effectif_actif_evolution(centre, mois_fin, nb_mois).to_dict("records")


@mcp.tool()
def evolution_resultat_par_centre(mois_fin: str, nb_mois: int = 6) -> list:
    """Resultat net (recettes - depenses), centre par centre et mois par
    mois, sur les nb_mois (6 par defaut) se terminant a mois_fin (AAAAMM)
    inclus - pour comparer l'evolution des centres entre eux, pas seulement
    le total consolide (voir evolution_six_mois pour le consolide)."""
    lignes = an.evolution_resultat_par_centre(mois_fin, nb_mois).to_dict("records")
    autorises = set(portee.restreindre_centres([l["centre"] for l in lignes]))
    return [l for l in lignes if l["centre"] in autorises]

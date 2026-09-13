# ---------------------------------------------------------------------------
# Outils MCP - Personnel et masse salariale
#
# La masse salariale regroupe deux comptes distincts du plan comptable
# (confirme avec la direction le 06/09/2026) : 422000 (modele "remuneration",
# journal CMD) et 632710 (modele "vacation", journal ACH) - voir
# logic.analyse.part_masse_salariale pour le detail.
# ---------------------------------------------------------------------------

from typing import Optional

import logic.analyse as an
from mcp_server import portee
from mcp_server.instance import mcp


@mcp.tool()
def vacations_du_mois(mois: str, centre: Optional[str] = None) -> list:
    """Detail des vacations et remunerations versees sur le mois, beneficiaire
    par beneficiaire, pour un centre precis ou pour l'ensemble si centre est
    omis."""
    centre = portee.resoudre(centre)
    return an.vacations_du_mois(mois, centre)


@mcp.tool()
def personnel_multi_centres(mois_fin: Optional[str] = None, nb_mois: int = 3) -> list:
    """Liste les enseignants/employes qui ont ete payes (vacation ou
    remuneration) sur plusieurs centres distincts au cours des nb_mois
    derniers mois (3 par defaut) se terminant a mois_fin (AAAAMM, mois
    courant si omis) inclus, avec leur remuneration par centre et le total
    cumule - pour verifier la coherence des montants verses a une meme
    personne."""
    if portee.centre_impose():
        # Cet outil n'a de sens qu'en croisant plusieurs centres : le refuser
        # explicitement vaut mieux que de renvoyer une liste vide, qui se
        # lirait comme "personne n'intervient sur plusieurs centres".
        raise portee.PorteeRefusee(
            "Cette question croise les donnees de plusieurs centres ; cette session n'a acces "
            "qu'a un seul centre. Elle releve du comptable du siege.")
    return an.personnel_multi_centres(mois_fin, nb_mois)


@mcp.tool()
def avances_personnel(centre: Optional[str] = None) -> list:
    """Solde restant du des avances/acomptes verses au personnel (compte
    422300), personne par personne, pour un centre precis ou pour
    l'ensemble si centre est omis. N'inclut pas les avances deja remboursees."""
    centre = portee.resoudre(centre)
    return an.avances_personnel(centre)


@mcp.tool()
def cout_vacation_par_eleve(mois: str) -> list:
    """Masse salariale du mois rapportee a l'effectif actif proxy, centre par
    centre - pour comparer le cout du personnel entre centres de tailles
    differentes."""
    lignes = an.cout_vacation_par_eleve(mois).to_dict("records")
    autorises = set(portee.restreindre_centres([l["centre"] for l in lignes]))
    return [l for l in lignes if l["centre"] in autorises]

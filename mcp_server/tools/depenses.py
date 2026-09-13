# ---------------------------------------------------------------------------
# Outils MCP - Depenses
#
# Tous ces outils partagent desormais le meme perimetre de charge, defini une
# seule fois par logic.analyse.lignes_depense : comptes de nature 'charge',
# salaires du modele "remuneration" (422000), et reglements passes directement
# par le collectif fournisseur 401000, reconstitues a partir du libelle. Avant
# le 11/09/2026, ce dernier cas etait ignore, ce qui laissait 92,6 % des
# depenses reelles de Hakili Lab hors de toute analyse - voir la table
# VENTILATION_REGLEMENTS_FOURNISSEUR et l'outil charges_non_ventilees.
# ---------------------------------------------------------------------------

from typing import Optional

import logic.analyse as an
from mcp_server import portee
from mcp_server.instance import mcp


@mcp.tool()
def poste_depense_principal(mois: str, centre: Optional[str] = None) -> dict:
    """Le compte de charge qui a pese le plus lourd sur le mois donne
    (AAAAMM), pour un centre precis ou pour l'ensemble si centre est omis.
    Se base sur la comptabilisation de la charge, pas sur la sortie de
    caisse. Renvoie aussi total_charges, pour situer ce poste dans
    l'ensemble des depenses du mois."""
    centre = portee.resoudre(centre)
    return an.poste_depense_principal(mois, centre)


@mcp.tool()
def part_masse_salariale(mois: str, centre: Optional[str] = None) -> dict:
    """Part de la masse salariale dans le total des charges du mois. Regroupe
    les salaires du modele "remuneration" (compte 422000) et les vacations
    (compte 632710), y compris quand celles-ci ont ete reglees directement par
    le collectif fournisseur - ce qui est le cas courant a Hakili Lab, ou la
    vacation est le mode de paiement dominant."""
    centre = portee.resoudre(centre)
    return an.part_masse_salariale(mois, centre)


@mcp.tool()
def part_charges_fixes(mois: str, centre: Optional[str] = None) -> dict:
    """Part des charges fixes (loyer, gardiennage, eau, electricite) dans le
    total des charges du mois."""
    centre = portee.resoudre(centre)
    return an.part_charges_fixes(mois, centre)


@mcp.tool()
def depenses_anormales(mois: str, centre: Optional[str] = None) -> list:
    """Liste les comptes de charge dont la depense du mois depasse
    nettement leur moyenne des mois precedents (meme compte, meme centre) -
    utile pour reperer une depense inhabituelle a verifier."""
    centre = portee.resoudre(centre)
    return an.depense_anormale(mois, centre)


@mcp.tool()
def part_loyer_eau_electricite(mois: str, centre: Optional[str] = None) -> dict:
    """Part du loyer, de l'eau (ONEA) et de l'electricite (SONABEL / Cash
    Power) dans le total des charges du mois - pour un centre precis ou pour
    l'ensemble si centre est omis. Ne compte pas le gardiennage,
    contrairement a part_charges_fixes qui donne un indicateur plus large."""
    centre = portee.resoudre(centre)
    return an.part_loyer_eau_electricite(mois, centre)


@mcp.tool()
def depense_moyenne_par_categorie(centre: Optional[str] = None,
                                   mois_fin: Optional[str] = None,
                                   nb_mois: int = 6) -> dict:
    """Depense mensuelle moyenne sur nb_mois mois (6 par defaut) pour
    chacune des categories suivies : nettoyage, telecom (internet), fournitures
    de bureau/pedagogiques, carburant. mois_fin (AAAAMM) borne la periode ;
    omis, le mois courant est utilise."""
    centre = portee.resoudre(centre)
    return an.depense_moyenne_categorie(centre, nb_mois=nb_mois, mois_fin=mois_fin)


@mcp.tool()
def charges_non_ventilees(mois: Optional[str] = None,
                           centre: Optional[str] = None) -> dict:
    """Reglements fournisseurs que l'application n'a pas su rattacher a une
    categorie de charge, faute de mot-cle reconnu dans leur libelle.

    Ces montants comptent bien dans le total des depenses, mais ne sont
    imputes a aucun poste : ils expliquent l'ecart quand la somme des
    categories ne retombe pas sur le total. A signaler au comptable comme du
    travail d'imputation restant, jamais comme une anomalie ou une perte."""
    centre = portee.resoudre(centre)
    return an.charges_non_ventilees(mois, centre)

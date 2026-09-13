# ---------------------------------------------------------------------------
# Outils MCP - Recherche libre / audit
#
# Categorie "question ouverte" : le comptable precise lui-meme un centre,
# une date, un tiers ou un montant. Chaque outil plafonne son resultat (voir
# logic.analyse.LIMITE_RECHERCHE_LIBRE) pour ne jamais renvoyer des milliers
# de lignes au modele de langage d'un coup.
# ---------------------------------------------------------------------------

from typing import Optional

import logic.analyse as an
from mcp_server import portee
from mcp_server.instance import mcp


@mcp.tool()
def transactions_caisse_jour(centre: str, date: str) -> list:
    """Toutes les lignes d'ecriture d'un centre pour une date precise
    (format AAAA-MM-JJ), tous journaux confondus."""
    centre = portee.resoudre(centre)
    return an.transactions_caisse_jour(centre, date)


@mcp.tool()
def transactions_tiers(tiers: str, mois: Optional[str] = None) -> list:
    """Toutes les lignes d'ecriture d'un tiers (eleve, fournisseur,
    enseignant...), identifie par son code exact ou par une recherche sur son
    nom. Limiter a un mois (AAAAMM) si precise dans la question."""
    return an.transactions_tiers(tiers, mois)


@mcp.tool()
def depenses_superieures_a(montant_min: float, mois: Optional[str] = None, centre: Optional[str] = None) -> list:
    """Lignes de charge dont le montant depasse montant_min, sur la periode
    et le centre donnes si precises."""
    centre = portee.resoudre(centre)
    return an.depenses_superieures_a(montant_min, mois, centre)


@mcp.tool()
def detail_ecritures_mois(mois: str, centre: Optional[str] = None) -> dict:
    """Detail des ecritures d'un mois (et centre si precise), pour
    verification par le comptable. Un export fichier (CSV/Excel) au sens
    strict reste a faire depuis l'onglet Export existant de l'application -
    cet outil affiche le detail dans la conversation, il ne produit pas de
    fichier telechargeable."""
    centre = portee.resoudre(centre)
    return an.detail_ecritures_mois(mois, centre)

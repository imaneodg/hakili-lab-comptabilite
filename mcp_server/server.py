# ---------------------------------------------------------------------------
# Serveur MCP de Hakili Lab - facade sur les outils de l'assistant.
#
# Depuis le 24/09/2026, l'application n'utilise plus ce serveur : l'onglet
# Assistant IA appelle les outils directement (assistant/outils.py), ce qui a
# supprime le sous-processus par session, le decodage du JSON fragmente et la
# transmission des secrets. Ce serveur reste disponible pour interroger
# Hakili_compta depuis un autre client MCP (Claude Desktop par exemple), avec
# EXACTEMENT les memes calculs, puisqu'il appelle le meme moteur.
#
# Portee : variable HAKILI_PORTEE_CENTRE (code d'un centre) pour limiter le
# serveur a ce centre ; absente = tous les centres.
#
# Lancement (racine du projet, meme venv que l'app) :
#   python -m mcp_server.server
# ---------------------------------------------------------------------------

import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()  # avant logic.* : le pool Postgres a besoin de DATABASE_URL

from mcp.server.fastmcp import FastMCP  # noqa: E402

from assistant import moteur  # noqa: E402
from assistant.comprehension import Incomprehension  # noqa: E402

_centre = (os.environ.get("HAKILI_PORTEE_CENTRE") or "").strip().upper()
ctx = moteur.Contexte(portee=[_centre] if _centre else None)

mcp = FastMCP(
    name="hakili-lab-assistant",
    instructions=("Analyse financiere de Hakili Lab (centres de soutien scolaire, Ouagadougou) sur "
                  "les donnees reelles de Hakili_compta. Commencer par l'outil contexte. Les "
                  "parametres centre et periode acceptent le texte libre (fautes tolerees)."),
)


def _appel(fonction, **kwargs):
    try:
        _, payload = fonction(ctx, **kwargs)
        return payload
    except Incomprehension as e:
        return e.en_dict()


@mcp.tool()
def contexte() -> dict:
    """Date du jour, plage des donnees, centres, caisses, categories, limites connues."""
    return moteur.contexte(ctx)


@mcp.tool()
def analyser(indicateurs: Optional[list[str]] = None, periode: Optional[str] = None,
             du: Optional[str] = None, au: Optional[str] = None, centres: Optional[str] = None,
             regrouper_par: Optional[list[str]] = None, categorie: Optional[str] = None,
             compte: Optional[str] = None, tiers: Optional[str] = None,
             journal_caisse: Optional[str] = None, statut: str = "tous") -> dict:
    """Indicateurs (encaissements, decaissements, flux_net, charges, masse_salariale,
    charges_fixes, marge_pct, part_pct, eleves_payants...) sur une periode et des centres,
    regroupes par 0 a 2 dimensions (centre, mois, semaine, jour, categorie, compte, tiers...)."""
    return _appel(moteur.analyser, indicateurs=indicateurs, periode=periode, du=du, au=au,
                  centres=centres, regrouper_par=regrouper_par, categorie=categorie, compte=compte,
                  tiers=tiers, journal=journal_caisse, statut=statut)


@mcp.tool()
def comparer(indicateurs: Optional[list[str]] = None, periode: Optional[str] = None,
             reference: Optional[str] = None, centres: Optional[str] = None,
             regrouper_par: Optional[list[str]] = None) -> dict:
    """Compare une periode a une reference (periode precedente, annee precedente, ou texte)."""
    return _appel(moteur.comparer, indicateurs=indicateurs, periode=periode, reference=reference,
                  centres=centres, regrouper_par=regrouper_par)


@mcp.tool()
def soldes(date_arret: Optional[str] = None, centres: Optional[str] = None,
           journal_caisse: Optional[str] = None, seuil: Optional[float] = None) -> dict:
    """Soldes des caisses par centre et de la banque commune, a une date."""
    return _appel(moteur.soldes, date_arret=date_arret, centres=centres, journal=journal_caisse,
                  seuil=seuil)


@mcp.tool()
def lister_ecritures(periode: Optional[str] = None, centres: Optional[str] = None,
                     compte: Optional[str] = None, tiers: Optional[str] = None,
                     texte: Optional[str] = None, montant_min: Optional[float] = None) -> dict:
    """Detail des lignes d'ecriture filtrees."""
    return _appel(moteur.lister_ecritures, periode=periode, centres=centres, compte=compte,
                  tiers=tiers, texte=texte, montant_min=montant_min)


@mcp.tool()
def controles(type_controle: str, periode: Optional[str] = None,
              centres: Optional[str] = None) -> dict:
    """doublons, dates_douteuses, a_corriger, non_validees, compte_attente,
    transferts_centres, non_ventile, depenses_inhabituelles."""
    return _appel(moteur.controles, type_controle=type_controle, periode=periode, centres=centres)


@mcp.tool()
def personnel(type_demande: str = "paiements", periode: Optional[str] = None,
              centres: Optional[str] = None, personne: Optional[str] = None) -> dict:
    """paiements, multi_centres, avances."""
    return _appel(moteur.personnel, type_demande=type_demande, periode=periode, centres=centres,
                  personne=personne)


@mcp.tool()
def chercher(texte: str, type_recherche: str = "tiers") -> dict:
    """Recherche approximative de tiers, comptes ou categories."""
    return moteur.chercher(ctx, texte, type_recherche)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

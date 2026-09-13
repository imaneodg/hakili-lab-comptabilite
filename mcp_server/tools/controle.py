# ---------------------------------------------------------------------------
# Outils MCP - Controle et anomalies
# ---------------------------------------------------------------------------

from typing import Optional

import logic.analyse as an
from mcp_server import portee
from mcp_server.instance import mcp


@mcp.tool()
def paiements_suspects(mois: str) -> list:
    """Liste les pieces du mois qui partagent exactement la meme date, le meme
    tiers et le meme montant - doublons probables de saisie, ou paiements a
    verifier en priorite.

    Fonctionne dans les deux sens : encaissement d'eleve comme reglement
    fournisseur. Le champ "sens" distingue les deux, et deux operations
    inverses du meme montant ne sont jamais rapprochees a tort. Les transferts
    entre caisses sont exclus : approvisionner deux caisses du meme montant le
    meme jour est une routine, pas une anomalie.

    Un rapprochement n'est pas une accusation : trois reglements identiques le
    meme jour peuvent etre trois enfants d'une meme famille. A presenter comme
    des pieces a verifier, jamais comme des doublons averes."""
    return an.paiements_suspects(mois)


@mcp.tool()
def evolution_reclassement(mois: str) -> dict:
    """Compare le montant total encore en attente de reclassement (compte
    471000, tous centres confondus) entre le mois donne et le mois
    precedent - indicateur de la charge de travail de reclassement pour le
    comptable."""
    return an.evolution_montant_a_reclasser(mois)


@mcp.tool()
def ecritures_a_verifier(mois: Optional[str] = None,
                          centre: Optional[str] = None) -> dict:
    """Nombre de pieces qui restent du travail pour le comptable : celles
    renvoyees a corriger (statut 'a_corriger') et celles encore sur le
    compte d'attente 471000. Les deux sont comptees separement et
    additionnees - une piece peut relever de l'une, de l'autre, ou des deux."""
    centre = portee.resoudre(centre)
    return an.ecritures_a_verifier(mois, centre)


@mcp.tool()
def transferts_entre_centres(mois: Optional[str] = None) -> dict:
    """Rapprochement des remises d'argent d'un centre a un autre - notamment
    le depot mensuel au centre SIAO.

    Renvoie quatre paniers : les transferts SOLDES (les deux centres ont
    enregistre, meme montant), ceux EN TRANSIT (partis recemment, pas encore
    enregistres a l'arrivee : c'est normal, l'argent est sur la route), les
    ANOMALIES (ecart de montant, recu en double, jamais recu apres le delai),
    et ceux SANS REFERENCE (historique saisi avant la mise en place du
    mecanisme, a regulariser a la main).

    Ne jamais presenter un transfert "en transit" comme une anomalie.

    Un transfert n'est ni une recette ni une depense : l'argent change de
    caisse, Hakili Lab ne gagne ni ne perd rien. Il n'apparait donc dans aucun
    total de recettes ou de depenses, et c'est voulu.

    Le champ solde_compte_585000 doit valoir zero quand tout est termine. S'il
    ne l'est pas alors qu'aucune anomalie n'est signalee, c'est qu'un virement
    de fonds a ete saisi hors du formulaire de transfert - a signaler au
    comptable."""
    return an.transferts_internes(mois)


@mcp.tool()
def ecritures_mal_datees(centre: Optional[str] = None,
                          annee_min: Optional[int] = None) -> dict:
    """Ecritures dont la date de piece est manifestement erronee : bien
    anterieure a la periode d'activite, ou posterieure a aujourd'hui.

    Une faute de frappe sur l'annee (2006 au lieu de 2026, 2024 au lieu de
    2026) est silencieuse par nature : l'ecriture sort de toutes les periodes
    interrogees, donc de tous les totaux mensuels, sans que rien ne l'indique.
    C'est exactement ce que cet outil rend visible. annee_min permet de fixer
    soi-meme la borne basse (par defaut, deux ans avant l'annee en cours)."""
    centre = portee.resoudre(centre)
    return an.ecritures_date_douteuse(centre, annee_min)

# ---------------------------------------------------------------------------
# Outils MCP - Suivi mensuel / tresorerie
# ---------------------------------------------------------------------------

from typing import Optional

import logic.analyse as an
import logic.donnees as dl
from mcp_server import portee
from mcp_server.instance import mcp


@mcp.tool()
def resultat_net(mois: str) -> dict:
    """Resultat net (recettes moins depenses), tous centres confondus, sur
    le mois donne, avec comparaison au mois precedent. Les transferts entre
    caisses sont exclus des deux cotes : ils ne creent ni recette ni depense."""
    portee.verifier_non_restreinte("resultat_net")
    ref = dl.lire_referentiel()
    actuel = an.resultat_net_mois(mois, ref)
    precedent = an.resultat_net_mois(an.mois_precedent(mois), ref)
    return {"mois": mois, "resultat_mois": actuel,
            "mois_precedent": an.mois_precedent(mois), "resultat_mois_precedent": precedent}


@mcp.tool()
def evolution_six_mois(mois_fin: str) -> list:
    """Recettes et depenses consolidees, mois par mois, sur les 6 derniers
    mois se terminant au mois indique (AAAAMM) inclus. Adapte a un
    affichage sous forme de graphique en support de la reponse."""
    portee.verifier_non_restreinte("evolution_six_mois")
    return an.evolution_6mois(mois_fin).to_dict("records")


@mcp.tool()
def solde_caisse_centre(centre: str, journal: str) -> dict:
    """Solde actuel d'une caisse donnee (journal CP, CMD ou "Banque") pour un
    centre precis. CP et CMD sont de vraies caisses physiques, une par
    centre : le solde renvoye est bien celui de ce centre. "Banque" est un
    compte partage par tous les centres (aucun centre n'a "sa part") : le
    centre fourni est alors ignore et le solde global de la banque est
    renvoye tel quel."""
    centre = portee.resoudre(centre)
    ref = dl.lire_referentiel()
    d = dl.lire_ecritures(centre=centre)
    return {"centre": centre, "journal": journal,
            "solde": dl.solde_caisse(journal, ref, d, centre=centre)}


@mcp.tool()
def tresorerie_disponible(centre: Optional[str] = None) -> dict:
    """Solde de tresorerie actuel (toutes caisses et banques confondues) -
    pour un centre precis, ou pour l'ensemble des centres si centre est
    omis. C'est une photo a l'instant present, pas un cumul depuis le debut
    de l'annee (voir resultat_annee_vs_precedente pour un cumul de resultat)."""
    centre = portee.resoudre(centre)
    return an.tresorerie_disponible(centre)


@mcp.tool()
def caisse_sous_seuil(centre: str, journal: str, seuil: float) -> dict:
    """Indique si le solde actuel d'une caisse (journal CP, CMD ou "Banque")
    d'un centre est sous le seuil fourni - voir solde_caisse_centre pour la
    portee exacte du centre selon le journal. Le seuil n'est jamais
    devine par l'outil : il doit venir de la question posee (ex. "sous 100000
    F ?") ou etre demande au directeur avant d'appeler cet outil."""
    centre = portee.resoudre(centre)
    return an.caisse_sous_seuil(centre, journal, seuil)


@mcp.tool()
def projection_depenses_fixes_mois_prochain(centre: Optional[str] = None) -> dict:
    """Projection naive des depenses fixes du mois prochain (masse
    salariale + charges fixes), a partir de la moyenne des 3 derniers mois
    clos. Ce n'est pas un budget valide par la direction, seulement une
    extrapolation mecanique de l'historique recent - a presenter comme telle."""
    centre = portee.resoudre(centre)
    return an.projection_depenses_fixes_mois_prochain(centre)


@mcp.tool()
def projection_recettes_mois_prochain(centre: Optional[str] = None) -> dict:
    """Projection des recettes attendues le mois prochain a partir des
    inscriptions connues.

    Indisponible actuellement : il n'existe pas de table d'inscriptions dans
    Hakili_compta permettant de savoir qui sera reellement inscrit le mois
    prochain - une projection basee uniquement sur l'historique
    d'encaissements serait trompeuse. Renvoie une reponse structuree
    expliquant pourquoi."""
    centre = portee.resoudre(centre)
    return an.projection_recettes_mois_prochain(centre)


@mcp.tool()
def resultat_annee_vs_precedente(mois_fin: str) -> dict:
    """Cumul recettes/depenses/resultat net depuis janvier jusqu'au mois
    indique (AAAAMM) inclus, compare a la meme periode de l'annee civile
    precedente.

    Attention : annee CIVILE (janvier a decembre). Quand la question porte sur
    "l'annee" au sens scolaire, utiliser resultat_annee_academique, qui
    compare deux rentrees comparables."""
    portee.verifier_non_restreinte("resultat_annee_vs_precedente")
    return an.resultat_annee_vs_precedente(mois_fin)


@mcp.tool()
def resultat_annee_academique(date_reference: Optional[str] = None,
                               centre: Optional[str] = None) -> dict:
    """Cumul recettes/depenses/resultat de l'annee academique en cours (du
    1er septembre au 31 aout), compare a la meme portion de l'annee
    academique precedente. date_reference (AAAA-MM-JJ) fixe le point d'arret ;
    omise, c'est aujourd'hui.

    C'est la lecture a privilegier des que la question parle de "cette annee",
    "l'annee derniere" ou "depuis la rentree" : l'activite de Hakili Lab suit
    l'annee scolaire, et comparer deux periodes civiles melangerait deux
    rentrees differentes."""
    centre = portee.resoudre(centre)
    return an.resultat_annee_academique_vs_precedente(date_reference, centre)

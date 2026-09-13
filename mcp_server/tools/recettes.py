# ---------------------------------------------------------------------------
# Outils MCP - Recettes
#
# Chaque outil appelle logic.analyse (calculs deterministes sur les donnees
# de Hakili_compta) et renvoie des nombres deja calcules. Le modele de
# langage choisit l'outil, lit le resultat et le formule en francais
# courant - il ne calcule jamais lui-meme.
#
# Depuis le 11/09/2026, chaque outil qui prend un centre le fait passer par
# mcp_server.portee.resoudre() : une session limitee a un centre ne peut pas
# interroger les autres. Sans restriction (comptable du siege), le
# comportement est strictement inchange.
# ---------------------------------------------------------------------------

from typing import Optional

import logic.analyse as an
import logic.donnees as dl
from mcp_server import portee
from mcp_server.instance import mcp


@mcp.tool()
def recettes_du_mois(centre: str, mois: str) -> dict:
    """Total encaisse par un centre sur un mois donne (format mois : AAAAMM,
    ex. '202603'). Inclut les sommes encore en attente de reclassement sur
    le compte 471000 : l'argent est deja dans la caisse, seul son etiquetage
    comptable est provisoire. Exclut les transferts internes entre caisses
    (approvisionnement de la caisse menues depenses, versement en banque,
    retrait bancaire) : ces mouvements ne font que deplacer de l'argent deja
    compte, ils ne sont ni une recette ni une depense."""
    centre = portee.resoudre(centre)
    ref = dl.lire_referentiel()
    return {"centre": centre, "mois": mois,
            "recettes": an.recettes_centre_mois(centre, mois, ref)}


@mcp.tool()
def comparaison_recettes_mois_precedent(centre: str, mois: str) -> dict:
    """Compare les recettes encaissees par un centre entre le mois donne
    (AAAAMM) et le mois precedent."""
    centre = portee.resoudre(centre)
    ref = dl.lire_referentiel()
    mp = an.mois_precedent(mois)
    return {"centre": centre, "mois": mois, "mois_precedent": mp,
            "recettes_mois": an.recettes_centre_mois(centre, mois, ref),
            "recettes_mois_precedent": an.recettes_centre_mois(centre, mp, ref)}


@mcp.tool()
def repartition_recettes(centre: str, mois: str) -> dict:
    """Repartit les recettes du mois d'un centre entre frais de scolarite
    encaisses (compte 411000, journal CP) et prestations facturees (journal
    ventes). Les deux montants ne sont pas sur la meme base comptable - le
    second peut inclure des factures pas encore payees - et doivent etre
    presentes separement dans la reponse, jamais additionnes.

    Renvoie aussi total_recettes_encaissees, identique a ce que repond
    recettes_du_mois, et autres_encaissements (frais de dossier, ventes
    diverses, remboursements) : scolarite + autres redonne le total, ce qui
    evite d'annoncer deux chiffres contradictoires selon l'outil utilise."""
    centre = portee.resoudre(centre)
    return an.repartition_recettes_mois(centre, mois)


@mcp.tool()
def montant_en_attente_de_reclassement(centre: str, mois: str) -> dict:
    """Montant et nombre de pieces encore sur le compte d'attente 471000
    pour un centre et un mois donnes. C'est du travail de reclassement
    restant pour le comptable, pas un manque de tresorerie. Un resultat a
    zero signifie qu'aucune piece du mois n'attend d'etre reclassee - a dire
    tel quel, sans en tirer d'autre conclusion."""
    centre = portee.resoudre(centre)
    return an.montant_a_reclasser(centre, mois)


@mcp.tool()
def classement_centres_par_recettes(mois: str) -> list:
    """Classe tous les centres par recettes encaissees sur le mois donne, du
    plus eleve au moins eleve."""
    lignes = an.classement_centres_recettes(mois).to_dict("records")
    autorises = set(portee.restreindre_centres([l["centre"] for l in lignes]))
    return [l for l in lignes if l["centre"] in autorises]


@mcp.tool()
def recettes_attendues_vs_realisees(centre: str, mois: str) -> dict:
    """Compare le montant theorique du a un centre sur le mois (nb eleves
    inscrits x tarif applicable) au montant reellement encaisse, calcule
    l'ecart et le taux de recouvrement, et identifie les eleves inscrits qui
    n'ont rien paye ce mois-ci.

    Categorie actuellement indisponible : Hakili_compta ne contient ni
    grille tarifaire par centre/formule ni table d'inscriptions/echeances,
    deux prealables indispensables pour ne pas inventer un montant
    "attendu". Renvoie une reponse structuree expliquant pourquoi plutot que
    de planter ou d'approximer - a restituer telle quelle au comptable. Pour
    le seul montant reellement encaisse (sans comparaison), utiliser
    recettes_du_mois."""
    centre = portee.resoudre(centre)
    return an.recettes_attendues_vs_realisees(centre, mois)


@mcp.tool()
def resultat_periode(date_debut: str, date_fin: str,
                      centre: Optional[str] = None) -> dict:
    """Recettes, depenses et resultat net entre deux dates precises (format
    AAAA-MM-JJ, bornes incluses), pour un centre ou pour l'ensemble si centre
    est omis.

    A utiliser des que la question ne porte pas sur des mois entiers : "entre
    la rentree et Noel", "du 15 mars au 15 avril", "depuis le debut du
    trimestre". Le detail mois par mois accompagne le total ; les mois de
    debut et de fin sont partiels, ce qu'il faut signaler dans la reponse.
    Pour un mois entier, recettes_du_mois reste plus direct."""
    centre = portee.resoudre(centre)
    return an.resultat_periode(date_debut, date_fin, centre)

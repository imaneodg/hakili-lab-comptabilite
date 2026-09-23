# ---------------------------------------------------------------------------
# Cloisonnement par centre des outils MCP : verification EXHAUSTIVE, par
# enumeration - meme principe que tests/test_autorisation_exhaustive.py cote
# Shiny, applique ici cote assistant IA.
#
# Ajoute le 22/09/2026 (M7 de l'audit du 18/09/2026) : sept outils MCP
# consolides tous-centres-confondus (resultat_net, evolution_six_mois,
# resultat_annee_vs_precedente, paiements_suspects, evolution_reclassement,
# transferts_entre_centres, transactions_tiers) n'appliquaient encore aucun
# controle de portee. Le risque etait masque par app.py, qui reserve l'onglet
# Assistant au comptable du siege - jusqu'a l'ouverture, deja annoncee dans
# mcp_server/portee.py, aux directeurs de centre.
#
# Ce fichier ENUMERE tous les outils MCP (@mcp.tool()) de mcp_server/tools/
# et exige que chacun applique un controle de portee, sous une forme ou une
# autre :
#   - il a un parametre `centre` et appelle portee.resoudre() (le cas normal,
#     un outil qui filtre sur un centre) ;
#   - il appelle portee.restreindre_centres() (un classement inter-centres,
#     reduit a la portee de la session) ;
#   - il appelle portee.verifier_non_restreinte() (un indicateur consolide,
#     sans notion de centre a filtrer - refuse entierement pour une session
#     restreinte) ;
#   - il consulte lui-meme portee.centre_impose() pour construire son propre
#     refus (cas de personnel_multi_centres, qui a une raison specifique de
#     rediger son propre message d'erreur).
#
# Un nouvel outil MCP est donc couvert des son ecriture, sans qu'il faille
# penser a mettre une liste a jour - exactement le raisonnement qui a motive
# test_autorisation_exhaustive.py le 15/09/2026.
#
# Purement syntaxique (module ast) : aucune session MCP, aucune base.
# ---------------------------------------------------------------------------

import ast
from pathlib import Path

DOSSIER_OUTILS = Path(__file__).resolve().parent.parent / "mcp_server" / "tools"

# Un controle acceptable, sous quelque forme que ce soit.
CONTROLES = {"resoudre", "restreindre_centres", "verifier_non_restreinte", "centre_impose"}

# Les seules dispenses admises. Chacune doit porter sa justification.
DISPENSES = set()


def _outils_mcp(arbre):
    """Toutes les fonctions decorees @mcp.tool() du module."""
    resultat = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in noeud.decorator_list:
            cible = deco.func if isinstance(deco, ast.Call) else deco
            if isinstance(cible, ast.Attribute) and cible.attr == "tool":
                resultat.append(noeud)
                break
            if isinstance(cible, ast.Name) and cible.id == "tool":
                resultat.append(noeud)
                break
    return resultat


def _noms_appeles(fonction):
    noms = set()
    for noeud in ast.walk(fonction):
        if isinstance(noeud, ast.Call):
            cible = noeud.func
            if isinstance(cible, ast.Name):
                noms.add(cible.id)
            elif isinstance(cible, ast.Attribute):
                noms.add(cible.attr)
        # personnel_multi_centres construit son propre refus a partir de
        # portee.centre_impose() sans passer par un nom de fonction commun
        # aux autres controles - un Attribute "centre_impose" est deja capte
        # par la branche ci-dessus, donc rien de plus a faire ici.
    return noms


def _fichiers_outils():
    return sorted(DOSSIER_OUTILS.glob("*.py"))


def test_tout_outil_mcp_applique_un_controle_de_portee():
    sans_controle = {}
    for chemin in _fichiers_outils():
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        for fonction in _outils_mcp(arbre):
            if fonction.name in DISPENSES:
                continue
            noms = _noms_appeles(fonction)
            if not (noms & CONTROLES):
                sans_controle[f"{chemin.name}:{fonction.name}"] = sorted(noms)[:10]

    assert not sans_controle, (
        "Ces outils MCP n'appliquent aucun controle de portee (ni "
        "portee.resoudre, ni portee.restreindre_centres, ni "
        "portee.verifier_non_restreinte, ni portee.centre_impose) : une "
        "session limitee a un centre pourrait interroger les donnees d'un "
        "autre centre, ou obtenir un chiffre consolide tous-centres-"
        "confondus. Ajouter le controle adapte, ou inscrire l'outil dans "
        f"DISPENSES avec sa justification : {sans_controle}"
    )


def test_les_outils_sans_parametre_centre_refusent_les_sessions_restreintes():
    """Un outil qui n'a pas de parametre `centre` du tout ne peut pas se
    reduire A UN centre via resoudre(), qui n'a rien a filtrer sans lui. Deux
    controles restent legitimes dans ce cas : restreindre_centres() pour un
    classement inter-centres (la liste se reduit alors au centre de la
    session), ou un refus complet (verifier_non_restreinte, ou le refus
    manuel de personnel_multi_centres) pour un chiffre unique deja consolide
    qu'aucune liste ne permet de reduire."""
    manquants = {}
    for chemin in _fichiers_outils():
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        for fonction in _outils_mcp(arbre):
            if fonction.name in DISPENSES:
                continue
            parametres = {a.arg for a in fonction.args.args}
            if "centre" in parametres:
                continue
            noms = _noms_appeles(fonction)
            if not (noms & {"verifier_non_restreinte", "centre_impose", "restreindre_centres"}):
                manquants[f"{chemin.name}:{fonction.name}"] = sorted(noms)[:10]

    assert not manquants, (
        "Ces outils MCP n'ont pas de parametre `centre` (ils calculent donc "
        "forcement un resultat consolide) mais ne refusent pas explicitement "
        "les sessions restreintes a un centre. Appeler "
        f"portee.verifier_non_restreinte(...) : {manquants}"
    )

# ---------------------------------------------------------------------------
# Controle d'acces : verification EXHAUSTIVE, par enumeration.
#
# Complete tests/test_authorisation.py, qui verifie une liste de fonctions
# ecrite a la main. Cette liste est utile (elle fige des invariants precis,
# role par role) mais elle a un angle mort structurel : une fonction qu'on
# oublie d'y inscrire est une fonction non testee, et rien ne signale
# l'oubli. C'est exactement ce qui s'est produit - l'audit du 15/09/2026 a
# trouve deux fonctions qui ecrivaient en base sans aucun controle de centre
# (_supprimer, _attribuer), et les tests passaient au vert parce qu'aucune
# des deux ne figurait dans les listes.
#
# Ce fichier prend le probleme dans l'autre sens : il ENUMERE toutes les
# fonctions de app.py qui appellent une fonction d'ecriture de logic.donnees,
# et exige que chacune porte un controle. Une nouvelle action sensible est
# donc couverte le jour ou elle est ecrite, sans que personne ait a penser a
# mettre une liste a jour. Seules les exceptions sont listees, et chacune
# doit etre justifiee ici noir sur blanc.
#
# Comme test_authorisation.py, l'analyse est purement syntaxique (module ast) :
# aucune session Shiny, aucune base, aucun navigateur.
# ---------------------------------------------------------------------------

import ast
from pathlib import Path

APP_PY = Path(__file__).resolve().parent.parent / "app.py"

# Fonctions de logic.donnees qui ECRIVENT en base. Toute fonction de app.py
# qui en appelle une doit etre protegee.
ECRITURES = {
    "enregistrer_operation", "valider_pieces", "rejeter_pieces", "supprimer_piece",
    "marquer_exporte", "reclasser_piece", "resoudre_tiers", "reparer_tiers_manquants",
    "ajouter_compte", "ajouter_tiers", "ajouter_utilisateur", "desactiver_utilisateur",
    "maj_solde_ouverture", "maj_solde_ouverture_centre", "nouvelle_annee_academique",
}

# Un controle acceptable : soit une garde de role, soit un controle de centre.
CONTROLES = {"est_comptable", "est_validateur", "_hors_centre"}

# Les seules dispenses admises. Chacune doit porter sa justification : si on
# ne sait pas ecrire pourquoi une fonction peut ecrire sans controle, c'est
# qu'elle n'en a pas le droit.
DISPENSES = {
    # Enregistre une piece NEUVE dans le centre de l'utilisateur connecte :
    # le centre vient de util()["centre"], jamais d'une selection a l'ecran.
    # Il n'y a donc pas de piece d'un autre centre a atteindre, et la saisie
    # est ouverte a tous les roles par construction.
    "_enregistrer_piece",
}


def _fonctions(arbre):
    """Toutes les FunctionDef/AsyncFunctionDef du module, y compris imbriquees."""
    return [n for n in ast.walk(arbre)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _appels_propres(fonction):
    """Appels ecrits DANS cette fonction, en excluant ceux de ses fonctions
    imbriquees. Sans cela, server() - qui contient tout app.py - apparaitrait
    comme appelant chaque fonction d'ecriture de l'application."""
    imbriquees = set()
    for noeud in ast.walk(fonction):
        if noeud is fonction:
            continue
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
            imbriquees.update(id(x) for x in ast.walk(noeud))
    return [n for n in ast.walk(fonction)
            if isinstance(n, ast.Call) and id(n) not in imbriquees]


def _noms_appeles(fonction):
    noms = set()
    for appel in _appels_propres(fonction):
        cible = appel.func
        if isinstance(cible, ast.Name):
            noms.add(cible.id)
        elif isinstance(cible, ast.Attribute):
            noms.add(cible.attr)
    return noms


def test_toute_ecriture_en_base_est_protegee():
    arbre = ast.parse(APP_PY.read_text(encoding="utf-8"))

    sans_controle = {}
    for fonction in _fonctions(arbre):
        if fonction.name in DISPENSES:
            continue
        noms = _noms_appeles(fonction)
        ecritures = noms & ECRITURES
        if ecritures and not (noms & CONTROLES):
            sans_controle[fonction.name] = sorted(ecritures)

    assert not sans_controle, (
        "Ces fonctions de app.py ecrivent en base sans aucun controle de role "
        "ni de centre. Ajouter une garde (est_comptable/est_validateur) ou un "
        "controle de centre (_hors_centre) - ou, si l'ecriture est legitimement "
        "ouverte a tous, inscrire la fonction dans DISPENSES avec sa "
        f"justification : {sans_controle}"
    )


def test_les_pieces_liees_sont_elargies_avant_le_controle_de_centre():
    """avec_liees() doit precéder _hors_centre(), jamais l'inverse.

    Faille trouvee le 15/09/2026 sur _rejeter : le controle portait sur la
    selection brute, puis rejeter_pieces() elargissait aux pieces liees en
    interne - donc APRES le controle. Un validateur local pouvait choisir une
    piece de son centre liee a une piece d'un autre centre : _hors_centre ne
    voyait que la sienne, et l'autre partait avec. Un approvisionnement relie
    precisement deux pieces de deux centres differents.
    """
    arbre = ast.parse(APP_PY.read_text(encoding="utf-8"))

    # Ces fonctions de logic.donnees appellent avec_liees() elles-memes : leur
    # passer une liste, c'est accepter qu'elle soit elargie aux pieces
    # solidaires avant l'ecriture. Le controle de centre doit donc avoir porte
    # sur la liste DEJA elargie.
    ELARGISSANTES = {"valider_pieces", "rejeter_pieces", "supprimer_piece", "marquer_exporte"}

    fautives = {}
    for fonction in _fonctions(arbre):
        appels = _appels_propres(fonction)
        noms = _noms_appeles(fonction)
        if "_hors_centre" not in noms or not (noms & ELARGISSANTES):
            continue
        lignes_elargit = [a.lineno for a in appels
                          if isinstance(a.func, ast.Attribute) and a.func.attr == "avec_liees"]
        lignes_controle = [a.lineno for a in appels
                           if isinstance(a.func, ast.Name) and a.func.id == "_hors_centre"]
        if not lignes_elargit:
            fautives[fonction.name] = "n'appelle jamais dl.avec_liees()"
        elif min(lignes_elargit) > min(lignes_controle):
            fautives[fonction.name] = "appelle dl.avec_liees() APRES _hors_centre()"

    assert not fautives, (
        "Ces fonctions controlent le centre sur une liste de pieces que "
        "logic.donnees elargira ensuite aux pieces liees : le controle peut "
        "etre contourne en selectionnant une piece de son propre centre liee a "
        "une piece d'un autre centre. Elargir avec dl.avec_liees() AVANT "
        f"d'appeler _hors_centre() : {fautives}"
    )


def test_les_actions_sur_pieces_existantes_controlent_le_centre():
    """Toute action qui agit sur des pieces DEJA enregistrees doit borner son
    perimetre au centre de l'utilisateur, faute de quoi le cloisonnement entre
    centres ne tient qu'a l'affichage."""
    arbre = ast.parse(APP_PY.read_text(encoding="utf-8"))
    fonctions = {f.name: f for f in _fonctions(arbre)}

    attendues = ["_valider", "_rejeter", "_supprimer", "_attribuer"]
    manquantes = [nom for nom in attendues if nom not in fonctions]
    assert not manquantes, f"Fonction(s) introuvable(s) dans app.py : {manquantes}"

    sans_centre = [nom for nom in attendues
                   if "_hors_centre" not in _noms_appeles(fonctions[nom])]
    assert not sans_centre, (
        "Ces fonctions agissent sur des pieces existantes sans controler leur "
        f"centre : {sans_centre}"
    )

# ---------------------------------------------------------------------------
# Tests de non-regression sur le controle d'acces cote serveur (app.py).
#
# Ce que ce fichier ne fait PAS et pourquoi : les fonctions concernees
# (_valider, _rejeter, _soldes...) sont des closures definies a l'interieur
# de server() et dependent de l'environnement reactif d'une session Shiny
# reelle (util(), input.xxx(), reactive.calc...). Les invoquer directement
# sans session active demanderait de reconstruire des Inputs/Outputs/Session
# Shiny mockes - une dependance de test lourde, proche d'un test Playwright
# de bout en bout, qui detonnerait avec le reste de la suite (tests purs,
# sans navigateur, voir test_analyse.py et test_utils.py).
#
# A la place, ce fichier verifie directement le code source de app.py par
# analyse syntaxique (module ast de la bibliotheque standard) :
#   - que chacune des dix fonctions listees dans l'audit du 10/09/2026
#     (faille no 1 - aucun controle de role cote serveur, corrigee au
#     Groupe 1) commence toujours par "if not est_comptable(): ... return" ;
#   - que _soldes() (Groupe 3) n'avale plus une exception avec
#     `except Exception: pass` tout en affichant un message de succes.
# Une regression future (une de ces gardes retiree par un refactor) fait
# echouer ce test immediatement, sans navigateur ni base de donnees.
#
# _attribuer (reclassement depuis Controles) n'est volontairement PAS dans
# la liste ci-dessous : confirme avec Afiya le 10/09/2026 que l'absence de
# garde y est intentionnelle (voir claude/corrections-hakili-suivi.md) - un
# test qui l'exigerait serait fige sur une decision metier qui peut changer.
#
# Mise a jour du 11/09/2026 : le role "validation" existe desormais a deux
# niveaux (comptable du siege, centre SIE ; validateur local, n'importe quel
# autre centre - voir est_comptable()/est_validateur() dans app.py). _valider
# et _rejeter sont donc sortis de FONCTIONS_RESERVEES_AU_COMPTABLE (ils
# doivent rester accessibles a un validateur local, pas seulement au siege)
# et verifies a part, avec leur propre invariant : garde sur est_validateur()
# en premiere instruction, ET un appel a _hors_centre() quelque part dans le
# corps pour borner l'action au centre de l'utilisateur quand il n'est pas
# comptable. _marquer (export Sage) reste, lui, strictement reserve au
# comptable du siege - l'export vers Sage est centralise, voir le
# commentaire de a_exporter() dans app.py.
# ---------------------------------------------------------------------------

import ast
from pathlib import Path

APP_PY = Path(__file__).resolve().parent.parent / "app.py"

# _ajouter_tiers et _ajouter_compte sont sortis de cette liste le 23/09/2026 :
# decision d'Afiya, tout agent peut creer un compte ou un tiers (actif tout de
# suite). Voir DISPENSES dans test_autorisation_exhaustive.py et le test
# test_creation_referentiel_exige_une_session ci-dessous.
FONCTIONS_RESERVEES_AU_COMPTABLE = [
    "_marquer", "_reparer",
    "_ajouter_utilisateur", "_desactiver_utilisateur",
    "_soldes", "_nouvelle_annee",
]

FONCTIONS_RESERVEES_A_LA_VALIDATION = ["_valider", "_rejeter"]


def _fonctions_par_nom(arbre, noms):
    fonctions = {}
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.FunctionDef) and noeud.name in noms:
            fonctions.setdefault(noeud.name, []).append(noeud)
    return fonctions


def _appelle(sous_arbre, nom_fonction):
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == nom_fonction
        for n in ast.walk(sous_arbre)
    )


def _appelle_est_comptable(sous_arbre):
    return _appelle(sous_arbre, "est_comptable")


def _premiere_instruction_est_garde(fonction_def, nom_garde="est_comptable"):
    # La garde doit etre la toute premiere instruction du corps : un `if`
    # place plus bas laisserait deja s'executer du code avant le controle.
    if not fonction_def.body:
        return False
    premiere = fonction_def.body[0]
    return isinstance(premiere, ast.If) and _appelle(premiere.test, nom_garde)


def test_les_fonctions_reservees_au_comptable_verifient_le_role():
    arbre = ast.parse(APP_PY.read_text(encoding="utf-8"))
    fonctions = _fonctions_par_nom(arbre, FONCTIONS_RESERVEES_AU_COMPTABLE)

    manquantes = [nom for nom in FONCTIONS_RESERVEES_AU_COMPTABLE if nom not in fonctions]
    assert not manquantes, f"Fonction(s) introuvable(s) dans app.py : {manquantes}"

    sans_garde = [
        nom for nom, defs in fonctions.items()
        if not any(_premiere_instruction_est_garde(d, "est_comptable") for d in defs)
    ]
    assert not sans_garde, (
        "Ces fonctions reservees au comptable n'ont plus (ou n'ont jamais eu) de "
        f"controle de role en premiere instruction - faille du 10/09/2026 : {sans_garde}"
    )


def test_valider_et_rejeter_verifient_le_role_et_le_centre():
    # Faille decouverte par Afiya le 11/09/2026 en testant avec un compte
    # "validation" sur un centre autre que SIE : _valider/_rejeter
    # n'etaient gardes que par est_comptable() (donc inaccessibles a un
    # validateur local) et, plus grave, ne verifiaient jamais que les pieces
    # visees appartenaient bien au centre de l'utilisateur quand il n'etait
    # pas le comptable du siege.
    source = APP_PY.read_text(encoding="utf-8")
    arbre = ast.parse(source)
    fonctions = _fonctions_par_nom(arbre, FONCTIONS_RESERVEES_A_LA_VALIDATION)

    manquantes = [nom for nom in FONCTIONS_RESERVEES_A_LA_VALIDATION if nom not in fonctions]
    assert not manquantes, f"Fonction(s) introuvable(s) dans app.py : {manquantes}"

    sans_garde = [
        nom for nom, defs in fonctions.items()
        if not any(_premiere_instruction_est_garde(d, "est_validateur") for d in defs)
    ]
    assert not sans_garde, (
        "Ces fonctions doivent commencer par 'if not est_validateur(): ... return' "
        f"(accessible a un validateur local, pas seulement au siege) : {sans_garde}"
    )

    sans_controle_centre = [
        nom for nom, defs in fonctions.items()
        if not any(_appelle(d, "_hors_centre") for d in defs)
    ]
    assert not sans_controle_centre, (
        "Ces fonctions n'appellent plus _hors_centre() : un validateur local pourrait de "
        f"nouveau agir sur les pieces d'un autre centre que le sien : {sans_controle_centre}"
    )


def test_est_comptable_exige_le_centre_siege():
    # Coeur du correctif du 11/09/2026 : "validation" seul ne suffit plus a
    # etre traite comme le comptable du siege (banque visible, tous les
    # centres consolides, administration du referentiel) - il faut aussi
    # etre rattache au centre SIE.
    source = APP_PY.read_text(encoding="utf-8")
    arbre = ast.parse(source)
    (fn,) = _fonctions_par_nom(arbre, ["est_comptable"])["est_comptable"]
    corps = ast.get_source_segment(source, fn)
    assert '"SIE"' in corps, (
        "est_comptable() ne verifie plus le centre SIE - un validateur local d'un autre "
        "centre serait de nouveau traite comme le comptable du siege."
    )


def test_onglet_referentiel_utilise_est_comptable():
    # L'administration du referentiel (comptes, tiers, utilisateurs, soldes
    # d'ouverture, nouvelle annee) doit rester reservee au comptable du
    # siege, jamais a un simple test du role brut ("validation" existe
    # aussi pour un validateur local, voir est_comptable()).
    source = APP_PY.read_text(encoding="utf-8")
    arbre = ast.parse(source)
    (fn,) = _fonctions_par_nom(arbre, ["onglet_referentiel"])["onglet_referentiel"]
    assert _appelle_est_comptable(fn), (
        "onglet_referentiel() n'appelle plus est_comptable() pour decider qui voit "
        "l'administration du referentiel."
    )


def test_soldes_ne_confond_plus_un_echec_avec_un_succes():
    source = APP_PY.read_text(encoding="utf-8")
    arbre = ast.parse(source)
    (fn_soldes,) = _fonctions_par_nom(arbre, ["_soldes"])["_soldes"]

    # Regression exacte du Groupe 3 : un `except ...: pass` (l'erreur est
    # avalee, "Soldes d'ouverture enregistres" s'affichait quand meme).
    for noeud in ast.walk(fn_soldes):
        if isinstance(noeud, ast.ExceptHandler):
            avale_silencieusement = len(noeud.body) == 1 and isinstance(noeud.body[0], ast.Pass)
            assert not avale_silencieusement, "_soldes() avale de nouveau une exception avec `except ...: pass`"

    corps = ast.get_source_segment(source, fn_soldes)
    assert "echecs" in corps, "_soldes() ne semble plus accumuler/signaler les echecs par journal"


def test_creation_referentiel_exige_une_session():
    # Ouvertes a tous les roles, mais jamais sans utilisateur connecte : la
    # premiere instruction lit util(), la seconde sort si personne n'est
    # connecte, et l'identifiant est transmis pour tracer l'auteur.
    arbre = ast.parse(APP_PY.read_text(encoding="utf-8"))
    fonctions = _fonctions_par_nom(arbre, ["_ajouter_tiers", "_ajouter_compte"])
    assert set(fonctions) == {"_ajouter_tiers", "_ajouter_compte"}
    for nom, defs in fonctions.items():
        d = defs[0]
        assert _appelle(d.body[0], "util"), f"{nom} doit commencer par u = util()"
        assert isinstance(d.body[1], ast.If), f"{nom} doit sortir si aucun utilisateur n'est connecte"
        assert any(isinstance(n, ast.keyword) and n.arg == "par" for n in ast.walk(d)), \
            f"{nom} doit transmettre l'auteur (par=...) a logic.donnees"


def test_corriger_depuis_validation_est_reserve_a_la_validation():
    arbre = ast.parse(APP_PY.read_text(encoding="utf-8"))
    defs = _fonctions_par_nom(arbre, ["_corriger_depuis_validation"])["_corriger_depuis_validation"]
    assert _premiere_instruction_est_garde(defs[0], "est_validateur")

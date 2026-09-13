# ---------------------------------------------------------------------------
# Tests de non-regression sur la portee reactive de page()/corps()/m_champs()
# (app.py), correctif du 10/09/2026 (suite a l'audit "ecrans roses / onglets
# instables").
#
# Contexte du bug corrige : page() appelait onglets(u) directement, qui lit
# ref() -> _disque() (sondage 0,5 s sur les ecritures des 5 centres). Toute
# piece enregistree n'importe ou invalidait donc page() entierement - tous
# les onglets recrees, m_modele/m_journal remis a leur valeur par defaut,
# formulaire de Saisie en cours efface. m_champs() (les champs Eleve/Compte/
# Montant du formulaire) avait le meme defaut via sa propre lecture directe
# de ref(). Voir claude/corrections-hakili-suivi.md pour le detail.
#
# Meme approche que test_authorisation.py et pour la meme raison : page(),
# corps() et m_champs() sont des closures qui dependent d'une session Shiny
# reelle, impossibles a invoquer isolement sans session mockee. On verifie
# donc directement le code source par analyse syntaxique (module ast) :
#   - page() ne doit plus appeler onglets() directement ;
#   - corps() doit exister et n'appeler onglets() qu'a l'interieur d'un
#     `with reactive.isolate():` ;
#   - m_champs() ne doit lire ref() qu'a l'interieur d'un
#     `with reactive.isolate():`.
# Une regression future (isolate() retire par un refactor ulterieur) fait
# echouer ce test immediatement, sans navigateur ni base de donnees.
# ---------------------------------------------------------------------------

import ast
from pathlib import Path

APP_PY = Path(__file__).resolve().parent.parent / "app.py"
# Le CSS a ete extrait de app.py vers www/app.css (refonte visuelle, etape 1 -
# extraction des tokens de design) : le test ci-dessous qui l'inspecte lit
# desormais ce fichier plutot que app.py.
APP_CSS = Path(__file__).resolve().parent.parent / "www" / "app.css"


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


def _est_appel_reactive_isolate(node):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "isolate"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "reactive"
    )


def _blocs_isoles(fonction_def):
    return [
        n for n in ast.walk(fonction_def)
        if isinstance(n, ast.With)
        and any(_est_appel_reactive_isolate(item.context_expr) for item in n.items)
    ]


def test_page_ne_construit_plus_les_onglets_directement():
    arbre = ast.parse(APP_PY.read_text(encoding="utf-8"))
    (fn_page,) = _fonctions_par_nom(arbre, ["page"])["page"]
    assert not _appelle(fn_page, "onglets"), (
        "page() appelle onglets() directement : la structure des onglets redeviendrait "
        "dependante de _disque() (sondage 0,5 s), reproduisant le tremblement du 10/09/2026."
    )


def test_corps_construit_les_onglets_sous_reactive_isolate():
    arbre = ast.parse(APP_PY.read_text(encoding="utf-8"))
    fonctions = _fonctions_par_nom(arbre, ["corps"])
    assert "corps" in fonctions, "corps() est introuvable : le correctif du 10/09/2026 a-t-il ete retire ?"
    (fn_corps,) = fonctions["corps"]
    blocs = _blocs_isoles(fn_corps)
    assert blocs and any(_appelle(bloc, "onglets") for bloc in blocs), (
        "corps() n'appelle plus onglets() a l'interieur d'un `with reactive.isolate():` - "
        "la structure des onglets redeviendrait sensible a chaque ecriture ailleurs."
    )


def test_m_champs_isole_la_lecture_du_referentiel():
    arbre = ast.parse(APP_PY.read_text(encoding="utf-8"))
    (fn_champs,) = _fonctions_par_nom(arbre, ["m_champs"])["m_champs"]
    blocs = _blocs_isoles(fn_champs)
    assert blocs and any(_appelle(bloc, "ref") for bloc in blocs), (
        "m_champs() lit ref() hors d'un `with reactive.isolate():` - les champs "
        "Eleve/Compte/Montant redeviendraient effaces par une ecriture ailleurs."
    )


# ---------------------------------------------------------------------------
# Correctif du 10/09/2026 (bis) : avertissement "journal" affiche a tort a
# chaque connexion.
#
# Cause reelle (distincte du correctif ci-dessus, trouvee en lisant le code
# source installe de Shiny) : ui.input_select("m_journal", ...) dans
# onglet_saisie() est cree sans "selected=" - sa valeur de depart est donc
# le premier journal dans l'ordre de la table `journaux` (ACH), qui ne
# correspond pas au journal impose par le modele affiche par defaut
# ("Encaissement de frais de scolarite" -> CP). @reactive.event() s'execute
# par defaut des le demarrage de la session (ignore_init=False - "If False,
# the event triggers on the first run", docstring de shiny.reactive.event) :
# _garde_journal() se declenchait donc une fois a chaque connexion avec
# cette valeur de depart incorrecte et affichait l'avertissement alors que
# l'utilisateur n'avait rien choisi. Confirme empiriquement par Playwright :
# la notification apparait des la connexion sur le code d'avant ce
# correctif, avec exactement le texte remonte par Afiya, et disparait apres.
# ---------------------------------------------------------------------------

def test_garde_journal_ignore_le_declenchement_initial():
    arbre = ast.parse(APP_PY.read_text(encoding="utf-8"))
    fonctions = [
        n for n in ast.walk(arbre)
        if isinstance(n, ast.FunctionDef) and n.name == "_garde_journal"
    ]
    assert fonctions, "_garde_journal() est introuvable dans app.py"
    (fn_garde,) = fonctions

    # Le decorateur juste au-dessus de "def _garde_journal():" doit etre
    # @reactive.event(input.m_journal, ignore_init=True) - sinon
    # l'avertissement redevient affiche a chaque connexion sur le modele par
    # defaut (Encaissement de frais de scolarite -> CP, alors que m_journal
    # demarre sur ACH).
    decorateurs_event = [
        d for d in fn_garde.decorator_list
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
        and d.func.attr == "event"
    ]
    assert decorateurs_event, "_garde_journal() n'a plus de decorateur @reactive.event(...)"
    (decorateur,) = decorateurs_event

    ignore_init_vrai = any(
        kw.arg == "ignore_init"
        and isinstance(kw.value, ast.Constant)
        and kw.value.value is True
        for kw in decorateur.keywords
    )
    assert ignore_init_vrai, (
        "@reactive.event(input.m_journal) sur _garde_journal() n'a plus "
        "ignore_init=True - l'avertissement \"n'existe que sur le journal ...\" "
        "redeviendrait affiche a chaque connexion sur le modele par defaut."
    )


# ---------------------------------------------------------------------------
# Correctif du 11/09/2026 : le message "n'existe que sur le journal ..."
# etait revenu, signale par Afiya sur "Encaissement de frais de scolarite".
#
# Cause reelle : ignore_init=True (correctif ci-dessus) ne supprime que le
# tout premier declenchement de _garde_journal() pour toute la duree de la
# session Shiny (la connexion websocket) - jamais reconsomme ensuite. Or
# "Fermer la session" (_deconnexion) ne fait que util.set(None) : la MEME
# session Shiny continue, et se reconnecter (meme onglet de navigateur)
# reconstruit corps() -> onglets() -> onglet_saisie(), qui recree le <select>
# "m_journal" a zero. Sans "selected=" explicite dessus, ce nouveau <select>
# redemarrait sur le premier journal de la table, a nouveau different de
# celui impose par le modele par defaut - et cette fois, ignore_init=True
# (deja consomme depuis longtemps) ne l'empechait plus de declencher
# _garde_journal() pour de vrai. Verifie avec Afiya : le message apparaissait
# a chaque reconnexion dans le meme onglet, pas seulement a la premiere.
#
# La correction retenue supprime l'ecart a la source plutot que de compter
# sur ignore_init=True (qui reste une securite utile, mais insuffisante
# seule) : le <select> "m_journal" est desormais cree avec un "selected="
# qui correspond deja au modele affiche par defaut.
# ---------------------------------------------------------------------------

def test_m_journal_est_cree_avec_une_valeur_de_depart_explicite():
    source = APP_PY.read_text(encoding="utf-8")
    arbre = ast.parse(source)

    appel_select = None
    for noeud in ast.walk(arbre):
        if (isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Attribute)
                and noeud.func.attr == "input_select"
                and noeud.args and isinstance(noeud.args[0], ast.Constant)
                and noeud.args[0].value == "m_journal"):
            appel_select = noeud
            break
    assert appel_select is not None, "ui.input_select(\"m_journal\", ...) est introuvable dans app.py"

    a_un_selected = any(kw.arg == "selected" for kw in appel_select.keywords)
    assert a_un_selected, (
        "ui.input_select(\"m_journal\", ...) est de nouveau cree sans \"selected=\" - sa valeur de "
        "depart redeviendrait le premier journal de la table au lieu de celui impose par le modele "
        "par defaut, et l'avertissement \"n'existe que sur le journal ...\" reapparaitrait a chaque "
        "reconnexion dans la meme session (voir _journal_par_defaut())."
    )


# ---------------------------------------------------------------------------
# Correctif du 10/09/2026 (ter) : panneau "Ecriture generee" instable
# ("ca bouge" a l'ouverture de l'onglet Saisie et pendant la saisie du
# montant, signale par Afiya apres les deux correctifs precedents).
#
# Cause : valeurs(), operation(), m_apercu() et m_ruban() lisaient tous
# ref() (et, pour m_ruban(), donnees()) directement, sans isolate() - le
# meme defaut que page()/m_champs() (Groupe 6), mais sur la chaine qui
# alimente l'apercu de la piece en cours plutot que sur les onglets. Toute
# ecriture enregistree n'importe ou (sondage _disque(), 0,5 s) reconstruisait
# donc ce panneau en entier, meme sans qu'on y touche.
# ---------------------------------------------------------------------------

def test_valeurs_isole_la_lecture_du_referentiel():
    arbre = ast.parse(APP_PY.read_text(encoding="utf-8"))
    (fn,) = _fonctions_par_nom(arbre, ["valeurs"])["valeurs"]
    blocs = _blocs_isoles(fn)
    assert blocs and any(_appelle(bloc, "ref") for bloc in blocs), (
        "valeurs() lit ref() hors d'un `with reactive.isolate():` - l'apercu "
        "\"Ecriture generee\" redeviendrait instable (sondage 0,5 s)."
    )


def test_operation_isole_la_lecture_du_referentiel():
    arbre = ast.parse(APP_PY.read_text(encoding="utf-8"))
    (fn,) = _fonctions_par_nom(arbre, ["operation"])["operation"]
    blocs = _blocs_isoles(fn)
    assert blocs and any(_appelle(bloc, "ref") for bloc in blocs), (
        "operation() lit ref() hors d'un `with reactive.isolate():` - l'apercu "
        "\"Ecriture generee\" redeviendrait instable (sondage 0,5 s)."
    )


def test_m_apercu_isole_la_lecture_du_referentiel():
    arbre = ast.parse(APP_PY.read_text(encoding="utf-8"))
    (fn,) = _fonctions_par_nom(arbre, ["m_apercu"])["m_apercu"]
    blocs = _blocs_isoles(fn)
    assert blocs and any(_appelle(bloc, "ref") for bloc in blocs), (
        "m_apercu() lit ref() hors d'un `with reactive.isolate():` - le panneau "
        "\"Ecriture generee\" se reconstruirait de nouveau toutes les 0,5 s."
    )


def test_m_ruban_isole_ref_et_donnees():
    arbre = ast.parse(APP_PY.read_text(encoding="utf-8"))
    (fn,) = _fonctions_par_nom(arbre, ["m_ruban"])["m_ruban"]
    blocs = _blocs_isoles(fn)
    assert blocs and any(_appelle(bloc, "ref") for bloc in blocs), (
        "m_ruban() lit ref() hors d'un `with reactive.isolate():`."
    )
    assert blocs and any(_appelle(bloc, "donnees") for bloc in blocs), (
        "m_ruban() lit donnees() hors d'un `with reactive.isolate():` - le "
        "ruban d'effet sur les caisses redeviendrait instable (sondage 0,5 s)."
    )


# ---------------------------------------------------------------------------
# Correctif du 10/09/2026 (ter, suite) : "ca bouge" restait present pendant
# la SAISIE du montant elle-meme (pas seulement a cause d'ecritures d'un
# autre centre). Cause distincte, confirmee par un test Playwright avec
# MutationObserver sur #m_apercu/#m_ruban : ui.input_numeric() renvoie sa
# valeur au serveur a chaque frappe par defaut, donc valeurs()/operation()
# et tout le panneau "Ecriture generee" se reconstruisaient a chaque chiffre
# tape. Le parametre natif de Shiny update_on="blur" (n'envoyer la valeur
# qu'en quittant le champ) supprime ce rebuild pendant la frappe, sans rien
# changer au resultat final une fois le champ quitte - verifie
# empiriquement (0 reconstruction pendant 4 frappes, une seule juste apres
# avoir quitte le champ, calcul toujours correct).
# ---------------------------------------------------------------------------

def _appels_input_numeric(arbre):
    return [
        n for n in ast.walk(arbre)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "input_numeric"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "ui"
    ]


def _a_update_on_blur(appel):
    return any(
        kw.arg == "update_on"
        and isinstance(kw.value, ast.Constant)
        and kw.value.value == "blur"
        for kw in appel.keywords
    )


def test_montants_de_la_saisie_ne_renvoient_leur_valeur_qu_au_blur():
    arbre = ast.parse(APP_PY.read_text(encoding="utf-8"))
    # Les deux champs de montant utilises dans le formulaire de Saisie
    # (m_champs(), type "montant" generique, et le tableau de repartition
    # mois/nature/montant de "Encaissement") doivent tous deux avoir
    # update_on="blur". Le troisieme input_numeric du fichier (soldes
    # d'ouverture, panneau Referentiel) n'alimente pas ce panneau et n'est
    # pas concerne par ce correctif.
    appels_sans_blur_dans_saisie = []
    for fn_nom in ("m_champs", "_ligne_repartition_ui"):
        (fn,) = _fonctions_par_nom(arbre, [fn_nom])[fn_nom]
        for appel in _appels_input_numeric(fn):
            if not _a_update_on_blur(appel):
                appels_sans_blur_dans_saisie.append(fn_nom)
    assert not appels_sans_blur_dans_saisie, (
        f"input_numeric() sans update_on=\"blur\" dans : {appels_sans_blur_dans_saisie} - "
        "le panneau \"Ecriture generee\" redeviendrait instable a chaque frappe."
    )


# ---------------------------------------------------------------------------
# Correctif du 10/09/2026 (quater) : tableau de repartition (mois/nature/
# montant du modele "Encaissement") qui se reconstruisait entierement des
# qu'UNE ligne changeait, detruisant aussi les <input> des AUTRES lignes non
# touchees (perte de focus/valeurs en cours de saisie). Signale via une
# analyse externe qu'Afiya a soumise pour verification ; confirme reel et
# distinct du correctif update_on="blur" ci-dessus par un test Playwright
# (marqueur DOM sur la ligne 1, perdu apres avoir seulement modifie la
# ligne 2, avant ce correctif ; survit apres).
#
# Cause : _ligne_repartition_ui(), appelee pour CHAQUE ligne depuis
# m_bloc_repartition() (un @render.ui qui definit ces memes widgets),
# lisait get_input() sur les valeurs de la ligne sans isolate() - donc
# m_bloc_repartition() dependait reactivement des valeurs de TOUTES les
# lignes, pas seulement de la structure (nombre de lignes, modele).
# ---------------------------------------------------------------------------

def test_ligne_repartition_isole_ses_lectures():
    arbre = ast.parse(APP_PY.read_text(encoding="utf-8"))
    (fn,) = _fonctions_par_nom(arbre, ["_ligne_repartition_ui"])["_ligne_repartition_ui"]
    blocs = _blocs_isoles(fn)
    assert blocs, (
        "_ligne_repartition_ui() ne lit plus ses valeurs sous "
        "`with reactive.isolate():` - modifier une ligne du tableau de "
        "repartition reconstruirait de nouveau TOUTES les lignes, y compris "
        "celles non touchees."
    )
    # Les trois lectures (nature, mois, montant) doivent toutes se trouver
    # a l'interieur d'un bloc isole - une seule qui resterait dehors suffit
    # a reproduire le bug pour la valeur correspondante.
    lectures_visees = {"m_rep_nature_", "m_rep_mois_", "m_rep_montant_"}
    lectures_isolees = set()
    for bloc in blocs:
        for n in ast.walk(bloc):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "get_input" and n.args):
                arg0 = n.args[0]
                if isinstance(arg0, ast.JoinedStr):
                    for v in arg0.values:
                        if isinstance(v, ast.Constant) and isinstance(v.value, str):
                            lectures_isolees.add(v.value)
    manquantes = lectures_visees - lectures_isolees
    assert not manquantes, (
        f"Lecture(s) non isolee(s) dans _ligne_repartition_ui() : {manquantes}"
    )


# ---------------------------------------------------------------------------
# Correctif du flash sombre au clic sur les boutons "discrets" (Vider,
# Supprimer, boutons "+" et boutons-texte du Referentiel).
#
# Contexte : .btn-icone, .btn-texte, .btn-discret et .btn-danger-discret sont
# des classes maison, pas des variantes Bootstrap (btn-primary, btn-secondary,
# ...). Sans les variables --bs-btn-active-bg/--bs-btn-active-color/
# --bs-btn-active-border-color, l'etat presse (:active) retombe sur la regle
# de bootstrap.min.css ".btn-outline-default, .btn-default:not(.btn-primary,
# ...)" qui met --bs-btn-active-bg a #404040 (gris tres fonce). Cette regle a
# une specificite de (0,2,0) a cause du :not() - plus elevee que nos classes
# seules (0,1,0) - donc elle gagne meme si notre CSS est declare apres, d'ou
# un flash sombre et brutal a chaque clic. Verifie empiriquement via
# Playwright (getComputedStyle pendant un vrai mousedown) : #404040 avant
# correctif, couleur discrete du bouton apres.
#
# On verifie ici, par simple recherche textuelle (le CSS est un bloc de
# texte dans www/app.css depuis la refonte visuelle, pas du Python), que
# chacune des quatre classes definit bien les trois variables avec
# !important - la seule facon de battre la specificite (0,2,0) de la regle
# Bootstrap.
# ---------------------------------------------------------------------------

def _bloc_regle_css(css_source, selecteur):
    debut = css_source.index(selecteur + " {")
    fin = css_source.index("}", debut)
    return css_source[debut:fin]


def test_boutons_discrets_ne_flashent_plus_sombre_au_clic():
    source = APP_CSS.read_text(encoding="utf-8")
    variables = [
        "--bs-btn-active-bg",
        "--bs-btn-active-color",
        "--bs-btn-active-border-color",
    ]
    for classe in (".btn-icone", ".btn-texte", ".btn-discret", ".btn-danger-discret"):
        bloc = _bloc_regle_css(source, classe)
        for variable in variables:
            assert variable in bloc, (
                f"{classe} ne definit plus {variable} : l'etat :active de ce "
                "bouton va retomber sur le gris tres fonce par defaut de "
                "Bootstrap (.btn-default) et flasher a chaque clic."
            )
            # Bootstrap gagne la cascade sans !important (specificite plus
            # elevee a cause du :not()) : sans !important le correctif ne
            # sert a rien en pratique, meme si la variable est bien presente.
            pos = bloc.index(variable)
            fin_declaration = bloc.index(";", pos)
            assert "!important" in bloc[pos:fin_declaration], (
                f"{classe} definit {variable} sans !important : la regle "
                "Bootstrap plus specifique va quand meme gagner et le bouton "
                "va de nouveau flasher sombre au clic."
            )

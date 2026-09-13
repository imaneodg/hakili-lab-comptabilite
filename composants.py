# ---------------------------------------------------------------------------
# Composants d'interface reutilisables (refonte visuelle HAKILI LAB).
#
# Une fonction par composant, chacune ne faisant que construire du HTML/CSS
# (classes prefixees hk-, definies dans www/app.css) - aucune logique
# metier ici, aucun etat reactif : ces fonctions sont de simples "vues",
# appelees depuis app.py avec les valeurs deja calculees.
#
# A cette etape (3 - Composants), ces fonctions existent mais ne sont pas
# encore appelees depuis app.py : leur cablage dans chaque page (remplacement
# des constructions ad hoc existantes) se fait aux etapes suivantes de la
# refonte, page par page.
# ---------------------------------------------------------------------------

from shiny import ui


def titre_page(icone: str, titre: str, sous_titre: str, extra=None):
    """Bandeau de titre : pastille ronde 64px + titre + sous-titre."""
    return ui.div(
        ui.div(ui.tags.i(class_=f"bi bi-{icone}"), class_="hk-page-pastille"),
        ui.div(
            ui.h1(titre, class_="hk-page-h1"),
            ui.p(sous_titre, class_="hk-page-sous"),
            class_="hk-page-textes",
        ),
        ui.div(extra, class_="hk-page-extra") if extra else None,
        class_="hk-page-titre",
    )


def carte(*enfants, compacte=False, class_extra=None):
    """Carte blanche : unite visuelle de base de toute l'appli. Variante
    compacte (padding reduit) pour un formulaire qui doit tenir sans
    defiler - voir .carte-compacte dans www/app.css, deja utilisee par
    l'onglet Saisie."""
    classes = "carte carte-compacte" if compacte else "carte"
    if class_extra:
        classes += f" {class_extra}"
    return ui.div({"class": classes}, *enfants)


def carte_bandeau(icone, titre, extra=None):
    """Bandeau de section en tete de carte (fond teinte, icone + titre) -
    variante ".carte-bandeau", distincte de l'ancien en-tete a petite
    icone ".carte-entete-icone" deja utilise ailleurs dans l'appli. Les
    deux classes coexistent : chaque page choisit la sienne au moment de
    sa propre etape de refonte. `extra` : element optionnel aligne a
    droite (ex. bouton "+" du Referentiel)."""
    enfants = [
        ui.tags.i({"class": f"bi bi-{icone}"}),
        ui.span(titre),
    ]
    if extra is not None:
        enfants.append(ui.div({"class": "carte-bandeau-extra"}, extra))
    return ui.div({"class": "carte-bandeau"}, *enfants)


def filtre(*enfants):
    """Un filtre au sein d'un panneau filtres() - separateur vertical
    automatique entre filtres voisins, cf. .hk-filtre dans www/app.css."""
    return ui.div({"class": "hk-filtre"}, *enfants)


def filtres(*enfants):
    """Panneau de filtres : fond teinte, une seule ligne, separateurs
    verticaux entre chaque filtre() qu'il contient."""
    return ui.div({"class": "hk-filtres"}, *enfants)


def hk_info(items, titre="Informations"):
    """Encadre "Informations" : icone + titre + liste a puces courte.
    `items` est une liste de textes (deja formules), jamais une regle
    metier inventee ici."""
    return ui.div(
        {"class": "hk-info"},
        ui.div(
            {"class": "hk-info-entete"},
            ui.span({"class": "hk-info-icone"}, ui.tags.i({"class": "bi bi-info-circle"})),
            ui.span({"class": "hk-info-titre"}, titre),
        ),
        ui.tags.ul(*[ui.tags.li(texte) for texte in items]),
    )


# Correspondance avec les cles de STATUTS (app.py) - jamais un nouveau statut
# invente ici, seulement le mapping vers les 4 variantes de couleur de
# .hk-badge (attente/valide/exporte/erreur).
_BADGE_VARIANTE = {
    "saisie": "attente",
    "validee": "valide",
    "a_corriger": "erreur",
    "exportee": "exporte",
}


def badge_statut(cle, libelle):
    """Badge pilule pour un statut de piece (saisie/validee/a_corriger/
    exportee, cf. STATUTS dans app.py). Son cablage dans les tableaux qui
    l'utilisent (Brouillard, Validation) se fait a leurs etapes
    respectives : le mecanisme de style des cellules de render.data_frame
    n'a pas encore ete verifie a cette etape-ci."""
    variante = _BADGE_VARIANTE.get(cle, "attente")
    return ui.span({"class": f"hk-badge hk-badge--{variante}"}, libelle)


def stat(libelle, valeur, icone=None):
    """Un indicateur au sein de .bandeau-indicateurs. L'icone est
    optionnelle : retro-compatible avec les indicateurs actuels (b_stats()
    dans app.py), qui n'en ont pas encore - leur migration vers cette
    fonction se fait a l'etape Brouillard."""
    enfants = []
    if icone:
        enfants.append(ui.span({"class": "stat-icone"}, ui.tags.i({"class": f"bi bi-{icone}"})))
    enfants.append(ui.div({"class": "stat-texte"},
                           ui.div({"class": "l"}, libelle),
                           ui.div({"class": "v"}, valeur)))
    classe = "stat stat-avec-icone" if icone else "stat"
    return ui.div({"class": classe}, *enfants)


def format_montant(valeur) -> str:
    """Formate un montant pour l'affichage seul (zero decimale, espace
    insecable fine en separateur de milliers, ex. "127 000") - jamais une
    valeur reelle ni une donnee envoyee au serveur.

    Distincte de logic.donnees.fcfa(), deja utilisee partout dans l'appli
    (y compris dans des messages de controle generes par logic/donnees.py
    lui-meme, hors perimetre "presentation" de cette refonte) : fcfa()
    n'est pas modifiee, pour ne pas toucher a logic/*.py ni casser
    tests/test_utils.py qui verifie sa sortie exacte. format_montant() est
    a utiliser dans les nouveaux affichages construits pendant la refonte,
    au cas par cas - jamais en remplacement automatique de fcfa()."""
    if valeur is None or valeur == "":
        return ""
    try:
        v = round(float(valeur))
    except (TypeError, ValueError):
        return str(valeur)
    signe = "-" if v < 0 else ""
    return signe + f"{abs(v):,}".replace(",", " ")

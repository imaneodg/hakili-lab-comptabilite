# ---------------------------------------------------------------------------
# Graphiques de l'assistant IA
#
# Principe non negociable (comme pour logic.analyse) : le modele de langage
# ne dessine jamais un graphique lui-meme et ne manipule jamais de PNG/base64
# dans son texte. Ce module transforme directement la valeur DEJA renvoyee
# par un outil MCP (un dict ou une liste de dicts, donc deja calculee par
# logic.analyse) en image PNG encodee en base64. C'est app.py qui, apres
# avoir laisse le modele repondre en texte, lit le resultat brut de l'outil
# via chat_client().get_last_turn(role="user") et appelle
# graphique_pour_outil() pour injecter l'image a part - jamais en la faisant
# passer par la reponse texte de Claude.
#
# Ajouter un graphique pour un nouvel outil : ajouter une entree a
# OUTILS_AVEC_GRAPHIQUE ci-dessous. Rien d'autre a modifier dans app.py.
# ---------------------------------------------------------------------------

import base64
import io
import json
import logging

import matplotlib
matplotlib.use("Agg")  # pas d'affichage interactif : on ne fait que rendre un PNG
import matplotlib.pyplot as plt

logger = logging.getLogger("hakili")

# Palette neutre, coherente avec le reste de l'application (voir www/ pour le
# trait de marque) : pas de couleurs vives ni de degrade, un graphique de
# support doit rester sobre.
COULEUR_PRINCIPALE = "#2f5d62"
COULEUR_SECONDAIRE = "#c98a3b"
PALETTE_CENTRES = ["#2f5d62", "#c98a3b", "#8a4f7d", "#4a6fa5", "#7a8450", "#b0523f"]

FIGSIZE = (6.4, 3.6)
DPI = 140


def _figure_vers_base64(fig):
    tampon = io.BytesIO()
    fig.savefig(tampon, format="png", dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(tampon.getvalue()).decode("ascii")


def _f_cfa(valeur, position=None):
    return f"{valeur:,.0f}".replace(",", " ")


MOIS_COURTS = ["janv.", "fevr.", "mars", "avr.", "mai", "juin",
               "juil.", "aout", "sept.", "oct.", "nov.", "dec."]


def _mois_lisible(valeur):
    """'202603' -> 'mars 2026'. Un axe de graphique se lit d'un coup d'oeil ;
    un code AAAAMM oblige a le dechiffrer. Toute autre valeur est renvoyee
    telle quelle, l'axe n'a pas a savoir ce qu'il affiche."""
    texte = str(valeur)
    if len(texte) == 6 and texte.isdigit():
        mois = int(texte[4:])
        if 1 <= mois <= 12:
            return f"{MOIS_COURTS[mois - 1]} {texte[:4]}"
    return texte


def _cadrer_a_zero(ax, valeurs):
    """Force l'axe des ordonnees a inclure zero.

    Sur un graphique d'argent, un axe qui demarre a la valeur minimale
    transforme une variation de 5 % en falaise : la pente devient un artefact
    du cadrage, pas une information. Un comptable qui lit "les recettes
    s'effondrent" doit pouvoir s'y fier. Les valeurs negatives (un resultat
    net deficitaire) gardent evidemment leur place sous l'axe."""
    valeurs = [v for v in valeurs if v is not None]
    if not valeurs:
        return
    bas, haut = min(valeurs), max(valeurs)
    marge = (haut - bas) * 0.1 or (abs(haut) * 0.1 or 1)
    ax.set_ylim(min(0, bas - marge), max(0, haut + marge))


def courbe(x, series, titre, ylabel=""):
    """series : dict {nom_serie: [valeurs alignees sur x]}. Une ou plusieurs
    lignes sur le meme graphique (ex. recettes vs depenses, ou une ligne par
    centre) - adapte a une evolution mensuelle."""
    fig, ax = plt.subplots(figsize=FIGSIZE)
    etiquettes = [_mois_lisible(v) for v in x]
    for i, (nom, valeurs) in enumerate(series.items()):
        ax.plot(etiquettes, valeurs, marker="o", linewidth=2,
                color=PALETTE_CENTRES[i % len(PALETTE_CENTRES)], label=nom)
    _cadrer_a_zero(ax, [v for valeurs in series.values() for v in valeurs])
    ax.set_title(titre, fontsize=11, weight="bold")
    ax.set_ylabel(ylabel, fontsize=9)
    ax.tick_params(axis="x", rotation=45, labelsize=8)
    ax.yaxis.set_major_formatter(_f_cfa)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    if len(series) > 1:
        ax.legend(fontsize=8, frameon=False)
    return _figure_vers_base64(fig)


def barres(labels, valeurs, titre, ylabel=""):
    """Une barre par element de labels - adapte a une comparaison de
    centres sur un seul indicateur (recettes, marge, ratio de couts...)."""
    fig, ax = plt.subplots(figsize=FIGSIZE)
    couleurs = [PALETTE_CENTRES[i % len(PALETTE_CENTRES)] for i in range(len(labels))]
    ax.bar([_mois_lisible(l) for l in labels], valeurs, color=couleurs)
    _cadrer_a_zero(ax, valeurs)
    ax.set_title(titre, fontsize=11, weight="bold")
    ax.set_ylabel(ylabel, fontsize=9)
    ax.yaxis.set_major_formatter(_f_cfa)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    return _figure_vers_base64(fig)


def secteurs(labels, valeurs, titre):
    """Repartition d'un total entre quelques parts (2 a 6 dans la pratique)
    - contribution des centres, repartition scolarite/prestations..."""
    fig, ax = plt.subplots(figsize=(4.6, 4.2))
    couleurs = [PALETTE_CENTRES[i % len(PALETTE_CENTRES)] for i in range(len(labels))]
    ax.pie(valeurs, labels=labels, autopct="%1.0f%%", colors=couleurs,
           textprops={"fontsize": 8}, wedgeprops={"linewidth": 1, "edgecolor": "white"})
    ax.set_title(titre, fontsize=11, weight="bold")
    return _figure_vers_base64(fig)


# --- association outil MCP -> construction du graphique ---------------------
#
# Chaque entree recoit la valeur deja decodee (voir valeur_outil) et renvoie
# soit une image base64, soit None si la valeur ne s'y prete pas (liste vide,
# question marquee indisponible).

def _liste(valeur):
    """Ramene a une liste ce qui doit en etre une.

    Necessaire parce qu'un outil qui renvoie une liste d'UN SEUL element
    arrive comme un objet isole, indiscernable d'un dict : MCP produit un
    fragment de texte par element, et un fragment unique se decode en dict.
    Le cas est courant - un classement sur un seul centre, une evolution sur
    un seul mois, ou une session limitee a un centre. Sans cette
    normalisation, le constructeur indexait un dict comme une liste et le
    graphique disparaissait silencieusement."""
    if valeur is None:
        return []
    if isinstance(valeur, dict):
        return [valeur]
    return list(valeur)


def _graphique_evolution_six_mois(valeur):
    valeur = _liste(valeur)
    if not valeur:
        return None
    mois = [l["mois"] for l in valeur]
    return courbe(mois, {"Recettes": [l["recettes"] for l in valeur],
                          "Depenses": [l["depenses"] for l in valeur]},
                  "Recettes et depenses - 6 derniers mois", "F CFA")


def _graphique_evolution_resultat_par_centre(valeur):
    valeur = _liste(valeur)
    if not valeur:
        return None
    centres = sorted({l["centre"] for l in valeur})
    noms = {l["centre"]: (l.get("centre_nom") or l["centre"]) for l in valeur}
    mois = sorted({l["mois"] for l in valeur})
    series = {noms[c]: [next((l["resultat_net"] for l in valeur if l["centre"] == c and l["mois"] == m), 0)
                        for m in mois] for c in centres}
    return courbe(mois, series, "Resultat net par centre", "F CFA")


def _graphique_classement_centres(champ_montant, titre, ylabel="F CFA"):
    def _fn(valeur):
        valeur = _liste(valeur)
        if not valeur:
            return None
        labels = [l.get("centre_nom") or l["centre"] for l in valeur]
        valeurs = [l.get(champ_montant) or 0 for l in valeur]
        return barres(labels, valeurs, titre, ylabel)
    return _fn


def _graphique_contribution_centres(valeur):
    valeur = _liste(valeur)
    if not valeur:
        return None
    return secteurs([l.get("centre_nom") or l["centre"] for l in valeur],
                     [l["part_pct"] for l in valeur],
                     "Contribution de chaque centre aux recettes du mois")


def _graphique_repartition_recettes(valeur):
    if not valeur or not isinstance(valeur, dict):
        return None
    labels = ["Scolarite encaissee", "Prestations facturees"]
    valeurs = [valeur.get("scolarite_encaissee") or 0, valeur.get("prestations_facturees") or 0]
    if sum(valeurs) <= 0:
        return None
    return secteurs(labels, valeurs, "Repartition des recettes du mois")


def _graphique_effectif_evolution(valeur):
    valeur = _liste(valeur)
    if not valeur:
        return None
    mois = [l["mois"] for l in valeur]
    return courbe(mois, {"Effectif actif (proxy)": [l["effectif_proxy"] for l in valeur]},
                  "Evolution de l'effectif actif", "Eleves")


def _graphique_resultat_periode(valeur):
    """Evolution mois par mois d'une periode libre (outil resultat_periode).
    Le detail mensuel voyage deja dans la reponse : pas de second appel."""
    if not valeur or not isinstance(valeur, dict):
        return None
    detail = valeur.get("detail_mensuel") or []
    if len(detail) < 2:
        return None
    mois = [l["mois"] for l in detail]
    return courbe(mois, {"Recettes": [l["recettes"] for l in detail],
                          "Depenses": [l["depenses"] for l in detail]},
                  f"Recettes et depenses - {valeur.get('date_debut', '')} au {valeur.get('date_fin', '')}",
                  "F CFA")


def _graphique_annee_academique(valeur):
    if not valeur or not isinstance(valeur, dict):
        return None
    labels = [f"Recettes\n{valeur.get('annee_academique_precedente', 'N-1')}",
              f"Recettes\n{valeur.get('annee_academique', 'N')}",
              f"Depenses\n{valeur.get('annee_academique_precedente', 'N-1')}",
              f"Depenses\n{valeur.get('annee_academique', 'N')}"]
    valeurs = [valeur.get("recettes_annee_precedente") or 0, valeur.get("recettes") or 0,
               valeur.get("depenses_annee_precedente") or 0, valeur.get("depenses") or 0]
    if sum(valeurs) <= 0:
        return None
    return barres(labels, valeurs, "Annee academique en cours et precedente", "F CFA")


OUTILS_AVEC_GRAPHIQUE = {
    "evolution_six_mois": _graphique_evolution_six_mois,
    "resultat_periode": _graphique_resultat_periode,
    "resultat_annee_academique": _graphique_annee_academique,
    "evolution_resultat_par_centre": _graphique_evolution_resultat_par_centre,
    "classement_centres_par_recettes": _graphique_classement_centres("recettes", "Recettes par centre"),
    # La cle doit etre le nom EXACT de l'outil MCP (voir
    # mcp_server/tools/comparaison.py). Corrige le 11/09/2026 : elle etait
    # ecrite "classement_centres_recettes_trimestre", sans "par", et ne
    # correspondait donc a aucun outil - ce graphique n'a jamais pu s'afficher.
    "classement_centres_par_recettes_trimestre": _graphique_classement_centres(
        "recettes_trimestre", "Recettes du trimestre par centre"),
    "classement_rentabilite": _graphique_classement_centres("marge_pct", "Marge (%) par centre", "%"),
    "classement_structure_couts": _graphique_classement_centres(
        "ratio_couts_pct", "Ratio couts/recettes (%) par centre", "%"),
    "contribution_centres": _graphique_contribution_centres,
    "repartition_recettes": _graphique_repartition_recettes,
    "effectif_actif_evolution": _graphique_effectif_evolution,
}


def valeur_outil(valeur):
    """Normalise ce que l'application recoit d'un appel d'outil.

    Point crucial, corrige le 11/09/2026. Quand un outil est servi par un
    serveur MCP (ce qui est le cas de TOUS les outils de Hakili Lab), chatlas
    ne transmet pas l'objet Python renvoye par la fonction : la session MCP
    serialise le resultat en texte, et `ContentToolResult.value` contient donc
    une CHAINE JSON, pas un dict ni une liste (voir chatlas/_tools.py,
    Tool.from_mcp). Chaque constructeur de ce module levait alors un TypeError
    en indexant une chaine, exception qu'un `except Exception: return None`
    muet avalait aussitot. Resultat : aucun graphique ne s'est jamais affiche
    dans l'assistant, et rien dans les journaux ne le signalait.

    Le decodage est fait ici, en un seul endroit, plutot que dans app.py : les
    deux chemins d'appel (question libre et suggestion) passent par
    graphique_pour_outil, et un futur troisieme en beneficiera sans y penser."""
    if isinstance(valeur, (dict, list)):
        return valeur
    if isinstance(valeur, (bytes, bytearray)):
        valeur = valeur.decode("utf-8", errors="replace")
    if isinstance(valeur, str):
        texte = valeur.strip()
        if not texte:
            return None
        try:
            return json.loads(texte)
        except (ValueError, TypeError):
            pass
        # Cas d'un outil qui renvoie une LISTE. MCP ne transmet pas la liste
        # comme un seul document JSON : il en fait un fragment de texte par
        # element (verifie le 11/09/2026 - evolution_six_mois arrive en six
        # fragments, classement_centres_par_recettes_trimestre en six aussi),
        # et chatlas les recolle avec des sauts de ligne. Ce qui arrive ici est
        # donc une SUITE d'objets JSON mis bout a bout, que json.loads refuse -
        # et comme ils sont indentes, un decoupage ligne par ligne ne marche
        # pas non plus. On les decode donc l'un apres l'autre.
        objets, decodeur, position, longueur = [], json.JSONDecoder(), 0, len(texte)
        while position < longueur:
            while position < longueur and texte[position] in " \t\r\n":
                position += 1
            if position >= longueur:
                break
            try:
                objet, position = decodeur.raw_decode(texte, position)
            except ValueError:
                # Du texte libre, ou un fragment tronque : rien a tracer, mais
                # rien d'anormal non plus - on s'arrete sans lever.
                return objets or None
            objets.append(objet)
        if not objets:
            return None
        return objets[0] if len(objets) == 1 else objets
    return None


def graphique_pour_outil(nom_outil, valeur):
    """Point d'entree unique utilise par app.py. Renvoie une image PNG en
    base64, ou None si cet outil n'a pas de graphique associe ou si la
    valeur ne permet pas d'en tracer un (liste vide, reponse 'indisponible'
    de logic.analyse._indisponible, etc.)."""
    constructeur = OUTILS_AVEC_GRAPHIQUE.get(nom_outil)
    if constructeur is None:
        return None
    donnees = valeur_outil(valeur)
    if donnees is None:
        return None
    if isinstance(donnees, dict) and donnees.get("disponible") is False:
        return None
    try:
        return constructeur(donnees)
    except Exception as e:
        # Un graphique manquant n'est jamais une raison de casser la reponse
        # texte, deja rendue par ailleurs - mais il doit laisser une trace,
        # sinon un defaut de ce module reste invisible pendant des semaines.
        logger.warning("Graphique impossible pour l'outil %s : %s", nom_outil, e)
        return None

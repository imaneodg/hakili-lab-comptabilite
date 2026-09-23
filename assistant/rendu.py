# ---------------------------------------------------------------------------
# Rendu a l'ecran des resultats de l'assistant : tableaux et graphiques,
# affiches dans les cartes d'outil du chat (shinychat ToolResultDisplay).
#
# Les graphiques sont traces a partir du resultat EXACT garde en memoire par
# le moteur (jamais a partir de chiffres recopies par le modele), en PNG
# integre a la page (data URI) : pas de fichier sur le disque, pas d'URL
# publique, rien a purger. Le contenu HTML d'une carte shinychat n'est pas
# filtre comme le markdown du message, l'image s'affiche donc toujours.
#
# Palette : ordre categoriel valide (daltonisme, contraste) par le script de
# la charte dataviz ; le bleu de tete est proche du bleu Hakili (#1A5FD0).
# ---------------------------------------------------------------------------

import base64
import io
import itertools

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                      # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402
import pandas as pd                                   # noqa: E402
from htmltools import HTML, TagList, tags             # noqa: E402

from assistant.comprehension import Incomprehension   # noqa: E402
from assistant.indicateurs import INDICATEURS         # noqa: E402
from assistant.texte import mois_court, montant, nombre, pourcentage  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
TEXTE = "#0F2344"
TEXTE_DOUX = "#5B6B82"
GRILLE = "#E3E9F2"
SURFACE = "#FFFFFF"

TYPES = ("auto", "courbe", "barres", "barres_horizontales", "barres_groupees", "barres_empilees")


# =============================================================================
# FORMATS
# =============================================================================

def valeur_affichee(v, unite):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    if isinstance(v, bool) or unite == "bool":
        return "oui" if v else "non"
    if isinstance(v, str):
        return v
    if unite == "F":
        return montant(v)
    if unite == "%":
        return pourcentage(v)
    if isinstance(v, (int, float)):
        return nombre(v)
    return str(v)


def _axe_montant(v, _=None):
    a = abs(v)
    if a >= 1_000_000:
        return f"{v / 1_000_000:.1f} M".replace(".", ",").replace(",0 M", " M")
    if a >= 1_000:
        return f"{v / 1_000:.0f} k"
    return f"{v:.0f}"


def _etiquette(v, unite):
    if unite == "%":
        return pourcentage(v)
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.2f} M".replace(".", ",")
    return _axe_montant(v) if abs(v) >= 1000 else nombre(v)


# =============================================================================
# TABLEAUX
# =============================================================================

def tableau(res, max_lignes=300):
    """Tableau HTML d'un resultat, avec sa ligne de total. Tout est echappe
    par htmltools : un libelle saisi en caisse ne peut rien injecter."""
    cols = [(c, l, u) for c, l, u in res.colonnes if c in res.table.columns or c in res.total]
    entete = tags.tr(*[tags.th(l, class_="num" if u in ("F", "%") else None) for _, l, u in cols])
    lignes = []
    for _, r in res.table.head(max_lignes).iterrows():
        lignes.append(tags.tr(*[tags.td(valeur_affichee(r.get(c), u),
                                        class_="num" if u in ("F", "%") else None)
                                for c, _, u in cols]))
    pied = None
    if res.total and res.type in ("analyse", "comparaison") and len(res.table) > 1:
        cellules = []
        for i, (c, _, u) in enumerate(cols):
            if c in res.total:
                cellules.append(tags.td(valeur_affichee(res.total[c], u), class_="num"))
            else:
                cellules.append(tags.td("Total" if i == 0 else ""))
        pied = tags.tfoot(tags.tr(*cellules))
    note = None
    if len(res.table) > max_lignes:
        note = tags.p(f"{max_lignes} premieres lignes sur {len(res.table)}.", class_="hk-ia-note")
    elif len(res.table) == 0:
        note = tags.p("Aucune ligne.", class_="hk-ia-note")
    return TagList(
        _ligne_perimetre(res),
        tags.div(tags.table(tags.thead(entete), tags.tbody(*lignes), pied, class_="hk-ia-table"),
                 class_="hk-ia-table-wrap"),
        note,
    )


def _ligne_perimetre(res):
    p = res.perimetre or {}
    morceaux = [p.get("periode"), p.get("periode_reference") and f"comparee a {p['periode_reference']}",
                p.get("date") and f"au {p['date']}", p.get("centres"),
                p.get("statut") if p.get("statut") not in (None, "toutes les pieces") else None]
    texte = " · ".join(str(m) for m in morceaux if m)
    return tags.p(texte, class_="hk-ia-perimetre") if texte else None


def resume_total(res):
    """Une ligne de texte pour le titre replie d'une carte."""
    return res.titre


# =============================================================================
# GRAPHIQUES
# =============================================================================

def _figure(largeur=7.2, hauteur=3.3):
    fig, ax = plt.subplots(figsize=(largeur, hauteur), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRILLE)
    ax.tick_params(colors=TEXTE_DOUX, labelsize=8.5, length=0)
    ax.grid(axis="y", color=GRILLE, linewidth=0.8)
    ax.set_axisbelow(True)
    return fig, ax


def _en_image(fig, description):
    tampon = io.BytesIO()
    fig.savefig(tampon, format="png", bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    b64 = base64.b64encode(tampon.getvalue()).decode("ascii")
    return tags.img(src=f"data:image/png;base64,{b64}", alt=description, class_="hk-ia-graphique")


def _cadrer_zero(ax, valeurs, horizontal=False):
    vals = [v for v in valeurs if v is not None and not pd.isna(v)]
    if not vals:
        return
    bas, haut = min(vals), max(vals)
    marge = (haut - bas) * 0.12 or abs(haut) * 0.12 or 1
    lim = (min(0, bas - (marge if bas < 0 else 0)), max(0, haut + marge))
    (ax.set_xlim if horizontal else ax.set_ylim)(*lim)


def _format_axe(ax, unite, horizontal=False):
    f = FuncFormatter(lambda v, _: pourcentage(v) if unite == "%" else _axe_montant(v))
    (ax.xaxis if horizontal else ax.yaxis).set_major_formatter(f)
    (ax.xaxis if horizontal else ax.yaxis).set_major_locator(MaxNLocator(5))


def _legende(ax, n):
    if n >= 2:
        ax.legend(frameon=False, fontsize=8.5, labelcolor=TEXTE, loc="upper left",
                  bbox_to_anchor=(0, 1.13), ncol=min(n, 4), handlelength=1.2)


def _titre(fig, ax, titre):
    import textwrap
    ax.set_title("\n".join(textwrap.wrap(titre, 78)), loc="left", fontsize=10.5, color=TEXTE,
                 pad=24, fontweight="semibold")


def _donnees(res, indicateur):
    """(etiquettes x, {serie: valeurs}, unite) a partir d'un resultat."""
    t = res.table
    if len(t) == 0:
        raise Incomprehension("graphique_vide", "Ce resultat ne contient aucune ligne a tracer.")
    unites = {c: u for c, _, u in res.colonnes}
    if res.type == "comparaison":
        ind = indicateur or res.valeurs[0]
        a, b = getattr(res, "libelles_periodes", ("Periode", "Reference"))
        x = list(t[res.cle_x]) if res.cle_x else [INDICATEURS[ind]["libelle"]]
        if res.cle_x:
            t = t[(t[ind].fillna(0) != 0) | (t[f"{ind}_ref"].fillna(0) != 0)]
            x = list(t[res.cle_x])
        return x, {a: list(t[ind]), b: list(t[f"{ind}_ref"])}, unites.get(ind, "F")
    if res.type == "soldes":
        t = t[t["_centre"] != ""] if "_centre" in t.columns else t
        return ([f"{c} - {j.split(' ')[0]}" for c, j in zip(t["centre"], t["journal"])],
                {"Solde": list(t["solde"])}, "F")
    if res.cle_x is None:
        raise Incomprehension("graphique_impossible",
                              "Un seul chiffre : pas de graphique utile. Refaire l'analyse avec un "
                              "regroupement (par mois, par centre, par categorie...).")
    numeriques = [c for c in res.valeurs if c in t.columns and unites.get(c) in ("F", "%", "")]
    if indicateur:
        if indicateur not in t.columns:
            raise Incomprehension("indicateur_absent", f"« {indicateur} » n'est pas dans ce resultat.",
                                  numeriques)
        choisis = [indicateur]
    else:
        base = numeriques[0] if numeriques else None
        choisis = [c for c in numeriques if unites.get(c) == unites.get(base)][:3]
    if not choisis:
        raise Incomprehension("graphique_impossible", "Aucune valeur chiffree a tracer.")
    unite = unites.get(choisis[0], "F")
    if res.cle_serie and res.cle_serie in t.columns and len(choisis) == 1:
        t = t.assign(_x=_x(t, res.cle_x))
        ordre_x = list(dict.fromkeys(t["_x"]))
        pivot = t.pivot_table(index="_x", columns=res.cle_serie, values=choisis[0],
                              aggfunc="sum", sort=False).reindex(ordre_x)
        series = {str(s): list(pivot[s].fillna(0)) for s in pivot.columns[:8]}
        return ordre_x, series, unite
    libelles = {c: l for c, l, _ in res.colonnes}
    return _x(t, res.cle_x), {INDICATEURS[c]["libelle"] if c in INDICATEURS else libelles.get(c, c): list(t[c])
                              for c in choisis}, unite


def _x(t, cle):
    """Etiquettes de l'axe x : mois en version courte ('mars 26') pour tenir
    sans rotation sur une annee scolaire complete."""
    if cle == "mois" and "_mois" in t.columns:
        return [mois_court(k) for k in t["_mois"]]
    return list(t[cle])


def graphique(res, type_graphique="auto", indicateur=None, titre=None):
    """-> (balise <img>, description courte). Leve Incomprehension si le
    resultat ne se prete pas au graphique demande."""
    type_graphique = (type_graphique or "auto").strip().lower().replace(" ", "_")
    if type_graphique not in TYPES:
        type_graphique = "auto"
    x, series, unite = _donnees(res, indicateur)
    x = [str(v) for v in x]
    n = len(x)
    if type_graphique == "auto":
        if res.type == "comparaison":
            type_graphique = "barres_groupees"
        elif res.temporel and n >= 3:
            type_graphique = "courbe"
        elif len(series) > 1 and res.cle_serie:
            type_graphique = "barres_groupees"
        elif n > 7 or max(len(v) for v in x) > 14:
            type_graphique = "barres_horizontales"
        else:
            type_graphique = "barres_groupees" if len(series) > 1 else "barres"
    if type_graphique == "barres" and len(series) > 1:
        type_graphique = "barres_groupees"
    if n > 25 and type_graphique != "courbe":
        # Classement long (vacataires...) : les 25 premiers, le reste en table.
        x = x[:25]
        series = {k: v[:25] for k, v in series.items()}
        n = 25
    titre = titre or res.titre
    toutes = [v for vals in series.values() for v in vals]

    if type_graphique == "barres_horizontales":
        hauteur = max(2.4, 0.34 * n + 1.2)
        fig, ax = _figure(hauteur=hauteur)
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", color=GRILLE, linewidth=0.8)
        pos = list(range(n))[::-1]
        k = len(series)
        epaisseur = 0.72 / k
        for i, (nom, vals) in enumerate(series.items()):
            decal = [p + (k - 1) / 2 * epaisseur - i * epaisseur for p in pos]
            barres = ax.barh(decal, [v or 0 for v in vals], height=epaisseur * 0.9,
                             color=SERIES[i % 8], label=nom, linewidth=0)
            if k == 1:
                for b, v in zip(barres, vals):
                    if v:
                        ax.text(b.get_width(), b.get_y() + b.get_height() / 2, "  " + _etiquette(v, unite),
                                va="center", ha="left" if v >= 0 else "right", fontsize=8, color=TEXTE)
        ax.set_yticks(pos)
        ax.set_yticklabels(x, fontsize=8.5, color=TEXTE)
        _cadrer_zero(ax, toutes + [max(toutes or [0]) * 1.12], horizontal=True)
        _format_axe(ax, unite, horizontal=True)
        _legende(ax, k)
    elif type_graphique == "courbe":
        fig, ax = _figure()
        for i, (nom, vals) in enumerate(series.items()):
            ax.plot(range(n), [v if v is not None else float("nan") for v in vals], color=SERIES[i % 8],
                    linewidth=2, marker="o", markersize=4.5, markeredgecolor=SURFACE,
                    markeredgewidth=1.2, label=nom)
            derniers = [v[-1] for v in series.values() if v and v[-1] is not None]
            ecart_min = (max(toutes) - min(toutes)) * 0.08 if toutes else 0
            serres = any(abs(a - b) < ecart_min for a, b in itertools.combinations(derniers, 2))
            if len(series) <= 4 and not serres and vals and vals[-1] is not None:
                ax.annotate(_etiquette(vals[-1], unite), (n - 1, vals[-1]), textcoords="offset points",
                            xytext=(6, 0), va="center", fontsize=8, color=TEXTE)
        ax.set_xticks(range(n))
        ax.set_xticklabels(x, fontsize=8.5, color=TEXTE_DOUX, rotation=0 if n <= 8 else 35,
                           ha="center" if n <= 8 else "right")
        ax.set_xlim(-0.3, n - 0.4 + (0.5 if len(series) <= 4 else 0))
        _cadrer_zero(ax, toutes)
        _format_axe(ax, unite)
        _legende(ax, len(series))
    else:  # barres, barres_groupees, barres_empilees
        fig, ax = _figure()
        k = len(series)
        empile = type_graphique == "barres_empilees" and k > 1
        largeur = 0.7 if empile or k == 1 else 0.8 / k
        cumul = [0.0] * n
        for i, (nom, vals) in enumerate(series.items()):
            vals = [v or 0 for v in vals]
            if empile:
                pos = list(range(n))
                barres = ax.bar(pos, vals, width=largeur, bottom=cumul, color=SERIES[i % 8], label=nom,
                                edgecolor=SURFACE, linewidth=1)
                cumul = [c + v for c, v in zip(cumul, vals)]
            else:
                pos = [p - 0.4 + largeur * (i + 0.5) for p in range(n)] if k > 1 else list(range(n))
                barres = ax.bar(pos, vals, width=largeur * 0.92, color=SERIES[i % 8], label=nom,
                                linewidth=0)
                if n * k <= 16:
                    for b, v in zip(barres, vals):
                        if v:
                            ax.text(b.get_x() + b.get_width() / 2, v, _etiquette(v, unite),
                                    ha="center", va="bottom" if v >= 0 else "top", fontsize=7.5,
                                    color=TEXTE)
        ax.set_xticks(range(n))
        ax.set_xticklabels(x, fontsize=8.5, color=TEXTE_DOUX, rotation=0 if n <= 6 else 30,
                           ha="center" if n <= 6 else "right")
        _cadrer_zero(ax, cumul if empile else toutes)
        _format_axe(ax, unite)
        _legende(ax, k)
    # Pas de titre dans l'image : la carte qui l'affiche porte deja le titre.
    ax.set_title("", pad=18 if len(series) >= 2 else 4)
    description = f"Graphique : {titre}"
    return _en_image(fig, description), description


# =============================================================================
# POINT FINANCIER (tableau de bord)
# =============================================================================

def _tuile(titre, valeur, detail=None, signe=False):
    classe = "hk-ia-tuile"
    if signe and valeur is not None:
        classe += " negatif" if valeur < 0 else " positif"
    return tags.div(tags.div(titre, class_="hk-ia-tuile-titre"),
                    tags.div(montant(valeur), class_="hk-ia-tuile-valeur"),
                    tags.div(detail, class_="hk-ia-tuile-detail") if detail else None,
                    class_=classe)


def _evolution(actuel, precedent, libelle):
    if not precedent:
        return f"{libelle} : {montant(precedent)}"
    ecart = (actuel - precedent) / abs(precedent) * 100
    fleche = "+" if ecart >= 0 else ""
    return f"{fleche}{ecart:.0f} % par rapport à {libelle}".replace(".", ",")


def tableau_de_bord(data):
    """Le point financier en une carte : quatre chiffres, les centres, les
    plus grosses depenses, les envois au SIAO et les points a verifier."""
    dispo, mois, prec = data["disponible"], data["mois"], data["mois_precedent"]
    lib_prec = data["periode_precedente"].split(" (")[0]
    detail_dispo = f"caisses {montant(dispo['caisses'])}"
    if dispo.get("banque") is not None:
        detail_dispo += f" · banque {montant(dispo['banque'])}"
    tuiles = tags.div(
        _tuile("Argent disponible", dispo["total"], detail_dispo),
        _tuile(f"Reçu · {data['periode']}", mois["recu"], _evolution(mois["recu"], prec["recu"], lib_prec)),
        _tuile(f"Dépensé · {data['periode']}", mois["depense"],
               _evolution(mois["depense"], prec["depense"], lib_prec)),
        _tuile("Reste du mois", mois["reste"], f"depuis la rentrée : {montant(data['depuis_rentree']['reste'])}",
               signe=True),
        class_="hk-ia-tuiles")
    blocs = [tuiles]
    if data["centres"]:
        lignes = [tags.tr(tags.td(c["centre"]), tags.td(montant(c["recu"]), class_="num"),
                          tags.td(montant(c["depense"]), class_="num"),
                          tags.td(montant(c["caisse"]), class_="num")) for c in data["centres"]]
        blocs.append(tags.div(tags.h6("Centres", class_="hk-ia-sous-titre"), tags.div(tags.table(
            tags.thead(tags.tr(tags.th("Centre"), tags.th("Reçu", class_="num"), tags.th("Dépensé", class_="num"),
                               tags.th("En caisse", class_="num"))),
            tags.tbody(*lignes), class_="hk-ia-table"), class_="hk-ia-table-wrap")))
        if data.get("centres_sans_operation"):
            blocs.append(tags.p("Aucune opération : " + ", ".join(data["centres_sans_operation"]) + ".",
                                class_="hk-ia-note"))
    colonnes = []
    if data["plus_grosses_depenses"]:
        colonnes.append(tags.div(tags.h6("Plus grosses dépenses", class_="hk-ia-sous-titre"), tags.ul(
            *[tags.li(tags.span(x["type"]), tags.span(montant(x["montant"]), class_="num"))
              for x in data["plus_grosses_depenses"]], class_="hk-ia-liste")))
    if data["envois_siao"]:
        colonnes.append(tags.div(tags.h6("Envoyé au SIAO", class_="hk-ia-sous-titre"), tags.ul(
            *[tags.li(tags.span(e["centre"]),
                      tags.span(montant(e["envoye"]) if e["envoye"] else "rien", class_="num"))
              for e in data["envois_siao"]], class_="hk-ia-liste")))
    if colonnes:
        blocs.append(tags.div(*colonnes, class_="hk-ia-colonnes"))
    points = data.get("a_verifier") or []
    blocs.append(tags.div(tags.h6("À vérifier", class_="hk-ia-sous-titre"),
                          tags.ul(*[tags.li(tags.span(p["point"]), tags.span(str(p["nombre"]), class_="num"))
                                    for p in points], class_="hk-ia-liste")
                          if points else tags.p("Rien à signaler.", class_="hk-ia-note")))
    return TagList(*blocs)

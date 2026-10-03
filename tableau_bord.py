# ---------------------------------------------------------------------------
# Tableau de bord (02/10/2026, refondu le 03/10/2026) - interface et serveur
#
# Un seul onglet dans la barre laterale. En haut, toujours visibles : la
# periode (du ... au ...) et les centres. Dessous, deux sous-pages :
#   - Vue d'ensemble : trois phrases, un bandeau par centre, les points a
#     regarder, le comparatif des centres, le compte de resultat mensuel ;
#   - Fiche centre : quatre onglets (Resultat, Eleves, Caisse, Fiabilite).
# Les deux sous-pages lisent le meme appel a logic.tableau_bord.calculer().
#
# Reserve au comptable : le controle est fait ici, cote serveur
# (req(autorise())), pas seulement par l'absence d'onglet.
#
# Branchement dans app.py :
#   ui      : tableau_bord.onglet("tb")
#   serveur : tableau_bord.serveur("tb", autorise=..., actualiser=...)
# ---------------------------------------------------------------------------

import json

import pandas as pd
from shiny import module, reactive, render, req, ui

import logic.tableau_bord as calc
from composants import format_montant

MOIS_COURTS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août",
               "sept.", "oct.", "nov.", "déc."]
MOIS_LONGS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
              "septembre", "octobre", "novembre", "décembre"]
BLOCS = [(calc.ENCAISSEMENT, "Encaissements d'exploitation", "Total encaissements"),
         (calc.CHARGE, "Charges d'exploitation", "Total charges"),
         (calc.HORS, "Sorties hors exploitation", "Total hors exploitation (net)")]
MOTS = {calc.CORRECT: "Correct", calc.SURVEILLER: "À surveiller",
        calc.ATTENTION: "Attention", calc.NEUTRE: "Repère"}
# Couleurs des graphiques (validees : daltonisme, contraste sur blanc).
C_SCOLAIRE, C_CAMP, C_SALAIRES, C_MAXIMUM = "#5B92DE", "#1A4FB0", "#D0700E", "#14866D"
# (cle, libelle, couleur, couleur du texte dans la barre)
RETARDS = [("avance", "Payé d'avance", "#5B92DE", "#0F2344"), ("0", "Dans le mois", "#14866D", "#FFFFFF"),
           ("1", "1 mois de retard", "#E3B341", "#0F2344"), ("2", "2 mois", "#D0700E", "#0F2344"),
           ("3+", "3 mois et plus", "#B42318", "#FFFFFF")]
LISTE_MAX = 50  # operations affichees sous un controle de fiabilite


# --- formats ------------------------------------------------------------------------

def _f(v):
    """Montant en FCFA, separateur de milliers ; « - » si pas de donnee."""
    return "-" if calc._nan(v) else format_montant(v)


def _k(v):
    """Milliers de FCFA, pour les etiquettes des graphiques."""
    return "-" if calc._nan(v) else format_montant(round(v / 1000))


def _mois(aaaa_mm):
    return f"{MOIS_COURTS[int(aaaa_mm[5:]) - 1]} {aaaa_mm[2:4]}"


def _mois_seul(aaaa_mm):
    return MOIS_COURTS[int(aaaa_mm[5:]) - 1].capitalize()


def _periode(debut, fin):
    if debut.year == fin.year:
        if debut.month == fin.month:
            return f"{MOIS_LONGS[debut.month - 1]} {fin.year}"
        return f"{MOIS_LONGS[debut.month - 1]} à {MOIS_LONGS[fin.month - 1]} {fin.year}"
    return f"{MOIS_LONGS[debut.month - 1]} {debut.year} à {MOIS_LONGS[fin.month - 1]} {fin.year}"


def _ratio(v):
    return "-" if calc._nan(v) else f"{v:.2f}".replace(".", ",")


def _ton(v):
    return "" if calc._nan(v) else ("tbx-positif" if v > 0 else "tbx-negatif" if v < 0 else "")


# --- petits composants ----------------------------------------------------------------

def _pastille(niveau, mot=None):
    return ui.span({"class": f"tbx-pastille tbx-{niveau}"}, mot or MOTS[niveau])


def _chiffre(libelle, valeur, ton="", detail=None):
    """Un grand chiffre du bandeau."""
    return ui.div(
        {"class": "tbx-chiffre"},
        ui.div({"class": f"tbx-valeur {ton}".strip()}, _f(valeur), ui.span({"class": "tbx-unite"}, " F")),
        ui.div({"class": "tbx-libelle"}, libelle),
        ui.div({"class": "tbx-detail"}, detail) if detail else None,
    )


def _tuile(titre, valeur, sous_titre=None, niveau=None, mot=None):
    """Un chiffre cle de la fiche centre."""
    return ui.div(
        {"class": "tbx-tuile"},
        ui.div({"class": "tbx-tuile-titre"}, titre),
        ui.div({"class": "tbx-tuile-valeur"}, valeur),
        ui.div({"class": "tbx-tuile-sous"}, sous_titre) if sous_titre else None,
        _pastille(niveau, mot) if niveau else None,
    )


def _section(titre, *contenu, sous_titre=None):
    return ui.div({"class": "tbx-section"},
                  ui.h2({"class": "tbx-h2"}, titre),
                  ui.p({"class": "tbx-section-sous"}, sous_titre) if sous_titre else None,
                  *contenu)


def _message(texte, classe="tbx-vide"):
    return ui.div({"class": f"tbx-carte {classe}"}, texte)


def _deplier(libelle, *contenu, classe=""):
    """Bouton « Afficher le détail » : <details> natif, sans aller-retour serveur."""
    return ui.tags.details({"class": f"tbx-deplier {classe}".strip()},
                           ui.tags.summary(libelle), ui.div({"class": "tbx-deplier-corps"}, *contenu))


def _legende(*elements):
    """[(type, couleur, texte)] ; type : carre, trait, pointille."""
    return ui.div({"class": "tbx-legende"},
                  *[ui.span(ui.tags.i({"class": f"tbx-cle tbx-cle-{t}", "style": f"--c:{c}"}), txt)
                    for t, c, txt in elements])


def _ouvrir(ns, code, texte="Ouvrir la fiche", classe="tbx-lien"):
    """Lien qui ouvre la fiche d'un centre en gardant les filtres."""
    js = f"Shiny.setInputValue({json.dumps(ns('ouvrir'))}, {json.dumps(code)}, {{priority: 'event'}})"
    return ui.tags.button({"type": "button", "class": classe, "onclick": js}, texte)


# --- graphiques (HTML et CSS, lisibles sur telephone) ----------------------------------

def _hauteur(v, echelle):
    return 0 if calc._nan(v) or echelle <= 0 else max(0.0, min(100.0, v / echelle * 100))


def _colonnes(points, echelle, aria=""):
    """Graphique en colonnes. points : dicts avec etiquette, valeur, couleur,
    sous (texte sous la colonne), titre (infobulle), traits [(valeur, couleur,
    style)] : un repere horizontal par colonne (salaires, maximum, cible)."""
    cols = []
    for p in points:
        traits = [ui.tags.i({"class": f"tbx-trait tbx-trait-{s}",
                             "style": f"bottom:{_hauteur(v, echelle):.1f}%;--c:{c}"})
                  for v, c, s in p.get("traits", []) if not calc._nan(v)]
        barre = (ui.div({"class": "tbx-barre", "style": f"height:{_hauteur(p['valeur'], echelle):.1f}%;"
                                                        f"background:{p['couleur']}"})
                 if not calc._nan(p["valeur"]) and p["valeur"] > 0 else None)
        cols.append(ui.div(
            {"class": "tbx-col", "title": p.get("titre", "")},
            ui.div({"class": "tbx-col-zone"}, barre, *traits),
            ui.div({"class": "tbx-col-etiquette"}, p["etiquette"]),
            ui.div({"class": "tbx-col-sous"}, p.get("sous", "")),
        ))
    return ui.div({"class": "tbx-graphique", "role": "img", "aria-label": aria}, *cols)


def _echelle(*series):
    vals = [v for s in series for v in s if not calc._nan(v)]
    return max(vals) * 1.08 if vals and max(vals) > 0 else 1


def _graphique_resultat(fiche):
    m = fiche["mensuel"]
    camp = any(not x["vide"] and x["mois_camp"] for x in m)
    echelle = _echelle([x.get("encaissements", 0) for x in m], [x.get("salaires", 0) for x in m],
                       [x.get("maximum", 0) for x in m])
    points = []
    for x in m:
        if x["vide"]:
            points.append({"etiquette": _mois_seul(x["mois"]), "valeur": float("nan"), "couleur": "",
                           "sous": "-", "titre": f"{_mois(x['mois'])} : aucune donnée"})
            continue
        depasse = x["salaires"] > x["maximum"]
        points.append({
            "etiquette": _mois_seul(x["mois"]), "valeur": x["encaissements"],
            "couleur": C_CAMP if x["mois_camp"] else C_SCOLAIRE, "sous": _k(x["encaissements"]),
            "traits": [(x["salaires"], C_SALAIRES, "plein"), (max(x["maximum"], 0), C_MAXIMUM, "pointille")],
            "titre": (f"{_mois(x['mois'])}{' (camp)' if x['mois_camp'] else ''}\n"
                      f"Argent reçu : {_f(x['encaissements'])} F\nSalaires payés : {_f(x['salaires'])} F\n"
                      f"Plafond salarial : {_f(x['maximum'])} F"
                      + ("\nSalaires au-dessus du plafond" if depasse else "")),
        })
    return ui.div(
        {"class": "tbx-carte"},
        ui.div({"class": "tbx-titre"}, "Recettes, salaires et plafond salarial"),
        ui.p({"class": "tbx-carte-sous"}, "En milliers de FCFA."
             + (" Les mois de camp de vacances sont en bleu foncé." if camp else "")),
        _legende(("carre", C_SCOLAIRE, "Mois scolaire"), *([("carre", C_CAMP, "Camp de vacances")] if camp else []),
                 ("trait", C_SALAIRES, "Salaires payés"), ("pointille", C_MAXIMUM, "Plafond salarial")),
        _colonnes(points, echelle, aria="Recettes, salaires payés et plafond salarial, mois par mois"),
    )


def _graphique_eleves(fiche):
    rangs = fiche["eleves"]["par_mois"]
    echelle = _echelle([x["frais"] for x in rangs], [x["vacations"] for x in rangs])
    points = [{
        "etiquette": _mois_seul(x["mois"]), "valeur": x["frais"], "couleur": C_SCOLAIRE,
        "sous": "-" if calc._nan(x["eleves"]) else calc.nb(int(x["eleves"]), "élève", "élèves"),
        "traits": [(x["vacations"], C_SALAIRES, "plein")],
        "titre": (f"Cours de {MOIS_LONGS[int(x['mois'][5:]) - 1]}\nFrais encaissés : {_f(x['frais'])} F\n"
                  f"Élèves payants : {_f(x['eleves'])}\nVacations rattachées : {_f(x['vacations'])} F"),
    } for x in rangs]
    return ui.div(
        {"class": "tbx-carte"},
        ui.div({"class": "tbx-titre"}, "Recettes et salaires par mois de cours"),
        ui.p({"class": "tbx-carte-sous"}, "Le mois du cours est lu dans le libellé (« FRAIS CA NOM/MARS »), "
                                          "pas la date du paiement. Camp de vacances exclu."),
        _legende(("carre", C_SCOLAIRE, "Frais encaissés pour le mois"),
                 ("trait", C_SALAIRES, "Vacations rattachées au mois")),
        _colonnes(points, echelle, aria="Frais encaissés et vacations par mois du cours"),
    )


def _graphique_caisse(fiche):
    soldes = fiche["soldes_mois"]
    cible = fiche["cible_tresorerie"]
    echelle = _echelle([s for _, s in soldes], [cible])
    points = [{"etiquette": _mois_seul(m), "valeur": s, "couleur": C_SCOLAIRE,
               "sous": _k(s), "traits": [(cible, C_MAXIMUM, "pointille")],
               "titre": f"Fin {_mois(m)} : {_f(s)} F dans les caisses\nCible : {_f(cible)} F"}
              for m, s in soldes]
    return ui.div(
        {"class": "tbx-carte"},
        ui.div({"class": "tbx-titre"}, "Trésorerie en fin de mois et capital de base"),
        ui.p({"class": "tbx-carte-sous"}, "En milliers de FCFA, caisse principale et petite caisse. "
                                          "La banque est commune à tous les centres et n'y figure pas."),
        _legende(("carre", C_SCOLAIRE, "Argent en caisse"),
                 ("pointille", C_MAXIMUM, f"Capital de base : {calc.mois_txt(fiche['parametres']['cible_tresorerie_mois'])}"
                                          " de charges")),
        _colonnes(points, echelle, aria="Argent en caisse en fin de mois comparé à la cible"),
    )


def _barre_retard(eleves):
    r = eleves["retard"]
    parts = [(cle, txt, c, r.get(cle), t) for cle, txt, c, t in RETARDS]
    segments = [ui.div({"class": "tbx-retard-part", "style": f"flex:{v:.4f};background:{c};color:{t}",
                        "title": f"{txt} : {calc.pct(v, 0)}"},
                       calc.pct(v, 0) if v >= 0.08 else "")
                for _, txt, c, v, t in parts if not calc._nan(v) and v > 0]
    return ui.div(
        {"class": "tbx-carte"},
        ui.div({"class": "tbx-titre"}, "Quand les familles paient-elles ?"),
        ui.p({"class": "tbx-carte-sous"}, "Part des frais de cours d'appui encaissés sur la période, "
                                          "selon l'écart entre le mois du cours et le mois du paiement."),
        ui.div({"class": "tbx-retard"}, *segments) if segments else _message("Aucun frais avec un mois de cours lisible."),
        ui.div({"class": "tbx-legende"},
               *[ui.span(ui.tags.i({"class": "tbx-cle tbx-cle-carre", "style": f"--c:{c}"}),
                         f"{txt} : {calc.pct(v, 0)}") for _, txt, c, v, _t in parts]),
    )


# --- tableaux ---------------------------------------------------------------------------

def _ligne(libelle, valeurs, classe=""):
    return ui.tags.tr({"class": classe} if classe else {},
                      ui.tags.th({"scope": "row"}, libelle),
                      *[ui.tags.td(v) for v in valeurs])


def _compte_resultat(tableau, totaux, mois, extra=()):
    """Le compte de resultat mensuel en encaissements. extra : lignes
    supplementaires [(libelle, valeurs, classe)] apres le resultat."""
    colonnes = mois + ["Total"]
    corps = []
    for bloc, titre, libelle_total in BLOCS:
        corps.append(ui.tags.tr({"class": "tbx-groupe"},
                                ui.tags.th({"colspan": len(colonnes) + 1, "scope": "colgroup"}, titre)))
        for ligne in tableau[tableau["bloc"] == bloc].to_dict("records"):
            corps.append(_ligne(ligne["libelle"], [_f(ligne[c]) for c in colonnes]))
        cle = {calc.ENCAISSEMENT: "encaissements", calc.CHARGE: "charges", calc.HORS: "hors_exploitation"}[bloc]
        corps.append(_ligne(libelle_total, [_f(totaux[cle][c]) for c in colonnes], "tbx-total"))
        if bloc == calc.CHARGE:
            corps.append(_ligne("Résultat d'exploitation", [_f(totaux["resultat"][c]) for c in colonnes],
                                "tbx-resultat"))
            corps.append(_ligne("en % des encaissements", [calc.pct(totaux["pct"][c]) for c in colonnes],
                                "tbx-pct"))
            for libelle, valeurs, classe in extra:
                corps.append(_ligne(libelle, valeurs, classe))
    return ui.div({"class": "tbx-defile", "tabindex": "0"},
                  ui.tags.table({"class": "tbx-table"},
                                ui.tags.thead(ui.tags.tr(ui.tags.th({"scope": "col"}, "Poste"),
                                                         *[ui.tags.th({"scope": "col"}, _mois(m)) for m in mois],
                                                         ui.tags.th({"scope": "col"}, "Total"))),
                                ui.tags.tbody(*corps)))


def _table_simple(entetes, lignes, classe=""):
    return ui.div({"class": "tbx-defile", "tabindex": "0"},
                  ui.tags.table({"class": f"tbx-table {classe}".strip()},
                                ui.tags.thead(ui.tags.tr(*[ui.tags.th({"scope": "col"}, e) for e in entetes])),
                                ui.tags.tbody(*[ui.tags.tr(ui.tags.th({"scope": "row"}, l[0]),
                                                           *[ui.tags.td(v) for v in l[1:]]) for l in lignes])))


# --- vue d'ensemble ---------------------------------------------------------------------

def _notes(fiche):
    notes = []
    if fiche["non_validees"]:
        notes.append("dont " + calc.nb(fiche["non_validees"], "pièce non validée", "pièces non validées"))
    if fiche["attente"]:
        notes.append(f"dont {_f(fiche['attente'])} F au compte d'attente")
    return notes


def _bandeau(ns, nom, code, c, notes=(), principal=False):
    """Les trois chiffres d'un centre (ou de l'ensemble)."""
    marge = calc._div(c["resultat"], c["encaissements"])
    mot = "Bénéfice" if c["resultat"] >= 0 else "Perte"
    cible = c.get("cible_tresorerie", float("nan"))
    detail_caisse = f"Capital de base : {_f(cible)} F" if not calc._nan(cible) else "Caisses des centres choisis"
    return ui.div(
        {"class": "tbx-carte tbx-bandeau" + (" tbx-bandeau--principal" if principal else "")},
        ui.div({"class": "tbx-bandeau-tete"},
               ui.div({"class": "tbx-nom"}, nom),
               _ouvrir(ns, code) if code else None),
        ui.div(
            {"class": "tbx-chiffres"},
            _chiffre(f"{mot}, soit {calc.pct(marge)} de l'argent reçu", c["resultat"], _ton(c["resultat"])),
            _chiffre("Sorties hors exploitation", c["hors_exploitation"]),
            _chiffre("Argent disponible", c["argent_disponible"],
                     "tbx-negatif" if c["argent_disponible"] < 0 else "", detail_caisse),
        ),
        ui.div({"class": "tbx-notes"}, " · ".join(notes)) if notes else None,
    )


def _banque(r):
    """La banque, une seule fois : elle n'appartient a aucun centre."""
    return [ui.div({"class": "tbx-carte tbx-banque"},
                   ui.div({"class": "tbx-nom"}, f"Banque {i}"),
                   ui.div({"class": "tbx-banque-valeur"}, _f(s), ui.span({"class": "tbx-unite"}, " F")),
                   ui.div({"class": "tbx-libelle"}, f"au {r['fin']:%d/%m/%Y}, commune à tous les centres"))
            for i, s in r["banque"]]


def _alertes(r, noms):
    alertes = r["alertes"]
    if not alertes:
        return _section("À regarder en priorité",
                        _message("Rien d'anormal sur cette période pour ces centres."))

    def ligne(a):
        niveau, c, texte = a
        return ui.div({"class": "tbx-alerte"}, _pastille(niveau),
                      ui.span({"class": "tbx-alerte-centre"}, noms.get(c, c)),
                      ui.span({"class": "tbx-alerte-texte"}, texte))
    premieres, autres = alertes[:5], alertes[5:]
    return _section(
        "À regarder en priorité",
        ui.div({"class": "tbx-carte tbx-liste"}, *[ligne(a) for a in premieres],
               _deplier(f"Afficher les {len(autres)} autres points", *[ligne(a) for a in autres],
                        classe="tbx-deplier-liste") if autres else None),
    )


def _cible_marge(centres, fiches):
    cibles = {fiches[c]["parametres"]["cible_marge"] for c in centres}
    return f"Cible : {calc.pct(cibles.pop(), 0)}" if len(cibles) == 1 else "Cible propre à chaque centre"


def _comparatif(ns, r, noms):
    fiches = r["fiches"]
    centres = r["centres"]

    def cellule(texte, niveau):
        return ui.div(ui.div({"class": "tbx-cmp-valeur"}, texte), _pastille(niveau))

    def ligne(titre, sous, valeurs):
        return ui.tags.tr(ui.tags.th({"scope": "row"}, ui.div({"class": "tbx-cmp-titre"}, titre),
                                     ui.div({"class": "tbx-cmp-sous"}, sous)),
                          *[ui.tags.td(v) for v in valeurs])
    lignes = [
        ligne("Argent reçu", "Encaissements d'exploitation de la période",
              [cellule(f"{_f(fiches[c]['encaissements'])} F", calc.NEUTRE) for c in centres]),
        ligne("Bénéfice et marge", _cible_marge(centres, fiches),
              [cellule(f"{_f(fiches[c]['resultat'])} F, soit {calc.pct(fiches[c]['marge'])}",
                       fiches[c]["niveaux"]["marge"]) for c in centres]),
        ligne("Salaires contre plafond", "Plafond compatible avec la cible de marge",
              [cellule(f"{_f(fiches[c]['salaires'])} pour {_f(fiches[c]['maximum_salaires'])} F",
                       fiches[c]["niveaux"]["salaires"]) for c in centres]),
        ligne("Élèves payants", "Mois scolaire typique (médiane), face au seuil de rentabilité",
              [cellule("-" if not fiches[c]["eleves"]["eleves_typiques"] else
                       f"{_f(fiches[c]['eleves']['eleves_typiques'])} élèves"
                       + (f" pour {fiches[c]['seuil_eleves']}" if fiches[c]["seuil_eleves"] else ""),
                       fiches[c]["niveaux"]["eleves"]) for c in centres]),
        ligne("Argent disponible", "En mois de charges couverts",
              [cellule(f"{calc.mois_txt(fiches[c]['couverture_mois'])} pour "
                       f"{calc.mois_txt(fiches[c]['parametres']['cible_tresorerie_mois'])}",
                       fiches[c]["niveaux"]["caisse"]) for c in centres]),
        ligne("Retard de paiement des familles", "Part des frais payés avec au moins 1 mois de retard",
              [cellule(calc.pct(fiches[c]["eleves"]["retard_un_mois_et_plus"], 0),
                       fiches[c]["niveaux"]["retard"]) for c in centres]),
        ligne("Fiabilité des chiffres", "Part des pièces déjà validées par le comptable",
              [cellule(calc.pct(fiches[c]["fiabilite"]["part_validee"], 0),
                       fiches[c]["fiabilite"]["niveaux"]["global"]) for c in centres]),
    ]
    return _section(
        "Les centres côte à côte",
        ui.div({"class": "tbx-carte tbx-carte--tableau"},
               ui.div({"class": "tbx-defile", "tabindex": "0"},
                      ui.tags.table({"class": "tbx-table tbx-cmp"},
                                    ui.tags.thead(ui.tags.tr(
                                        ui.tags.th({"scope": "col"}, "Indicateur"),
                                        *[ui.tags.th({"scope": "col"}, _ouvrir(ns, c, noms.get(c, c), "tbx-lien tbx-lien-tete"))
                                          for c in centres])),
                                    ui.tags.tbody(*lignes)))),
    )


def _vue_ensemble(ns, r, noms):
    cartes = []
    plusieurs = len(r["centres"]) > 1
    if plusieurs:
        notes = []
        if r["non_validees"]:
            notes.append("dont " + calc.nb(r["non_validees"], "pièce non validée", "pièces non validées"))
        if r["interne"]:
            notes.append(f"{_f(r['interne'])} F de flux entre ces centres non comptés deux fois")
        cartes.append(_bandeau(ns, "Ensemble des centres choisis", None, r["ensemble"], notes, principal=True))
    for c in r["centres"]:
        cartes.append(_bandeau(ns, noms.get(c, c), c, r["fiches"][c], _notes(r["fiches"][c])))

    avertissements = []
    if r["non_classes"]:
        avertissements.append(ui.div({"class": "tbx-avertissement"},
                                     calc.nb(r["non_classes"], "compte non classé est compté",
                                             "comptes non classés sont comptés")
                                     + " en exploitation : à classer dans la table classement_comptes."))
    # Dans l'ordre de lecture du directeur : les trois chiffres, la
    # comparaison, puis ce qui demande une action. Le compte de resultat
    # detaille reste replie (il est aussi dans chaque fiche centre).
    return ui.TagList(
        *avertissements,
        ui.div({"class": "tbx-bandeaux"}, *cartes),
        ui.div({"class": "tbx-bandeaux-banque"}, *_banque(r)),
        _comparatif(ns, r, noms) if plusieurs else None,
        _alertes(r, noms),
        _deplier("Afficher le compte de résultat mensuel",
                 ui.div({"class": "tbx-carte tbx-carte--tableau"},
                        ui.div({"class": "tbx-titre"}, "Compte de résultat mensuel en encaissements",
                               ui.span({"class": "tbx-sous-titre"},
                                       "en FCFA, sans les flux entre les centres choisis"
                                       if plusieurs else "en FCFA")),
                        _compte_resultat(r["tableau"], r["totaux"], r["mois"]))),
    )


# --- fiche centre --------------------------------------------------------------------

def _onglet_resultat(f, mois):
    p = f["parametres"]
    lignes_salaires = [
        ("Salaires payés", [_f(m.get("salaires")) if not m["vide"] else "-" for m in f["mensuel"]]
         + [_f(f["salaires"])], "tbx-pct"),
        ("Plafond salarial", [_f(m.get("maximum")) if not m["vide"] else "-" for m in f["mensuel"]]
         + [_f(f["maximum_salaires"])], "tbx-pct"),
    ]
    return ui.TagList(
        ui.div({"class": "tbx-tuiles"},
               _tuile("Argent reçu", f"{_f(f['encaissements'])} F", "Encaissements d'exploitation"),
               _tuile("Résultat", f"{_f(f['resultat'])} F",
                      f"{calc.pct(f['marge'])} de l'argent reçu, cible {calc.pct(p['cible_marge'], 0)}",
                      f["niveaux"]["marge"]),
               _tuile("Salaires payés", f"{_f(f['salaires'])} F",
                      f"Plafond : {_f(f['maximum_salaires'])} F", f["niveaux"]["salaires"]),
               _tuile("Rendement des salaires", _ratio(f["rendement_salaires"]),
                      f"F reçus pour 1 F de salaires, cible {_ratio(f['rendement_cible'])}",
                      f["niveaux"]["rendement"])),
        _graphique_resultat(f),
        _deplier("Afficher le détail mois par mois",
                 ui.div({"class": "tbx-carte tbx-carte--tableau"},
                        _compte_resultat(f["tableau"], f["totaux"], mois, lignes_salaires))),
    )


def _onglet_eleves(f, mois):
    e = f["eleves"]
    seuil = f["seuil_eleves"]
    lignes = [(_mois(x["mois"]), "-" if calc._nan(x["eleves"]) else str(int(x["eleves"])),
               _f(x["frais_moyen"]), _f(x["frais"]), _f(x["vacations"]),
               _ratio(calc._div(x["frais"], x["vacations"])))
              for x in e["par_mois"]]
    notes = []
    if e["sans_mois"]:
        notes.append(f"{_f(e['sans_mois'])} F de frais sans mois de cours lisible ne sont pas répartis.")
    return ui.TagList(
        ui.div({"class": "tbx-tuiles tbx-tuiles--3"},
               _tuile("Élèves payants", "-" if not e["eleves_typiques"] else _f(e["eleves_typiques"]),
                      "Mois scolaire typique (médiane des mois de la période)"),
               _tuile("Frais moyen", f"{_f(e['frais_moyen'])} F", "Par élève et par mois de cours"),
               _tuile("Seuil de rentabilité", "-" if not seuil else calc.nb(seuil, "élève", "élèves"),
                      "Élèves payants pour couvrir un mois moyen de charges", f["niveaux"]["eleves"])),
        _graphique_eleves(f),
        _barre_retard(e),
        ui.div({"class": "tbx-notes-bas"}, *[ui.p(n) for n in notes]) if notes else None,
        _deplier("Afficher le détail par mois du cours",
                 ui.div({"class": "tbx-carte tbx-carte--tableau"},
                        _table_simple(["Mois du cours", "Élèves", "Frais moyen", "Frais encaissés",
                                       "Vacations", "Frais / vacations"], lignes))),
    )


def _onglet_caisse(f, r):
    p = f["parametres"]
    lignes = [
        ("Argent en caisse au début de la période", _f(f["caisse_debut"])),
        ("+ Résultat d'exploitation", _f(f["resultat"])),
        ("- Sorties hors exploitation (net)", _f(-f["hors_exploitation"])),
        ("+ Transferts reçus d'autres caisses (net)", _f(f["transferts_nets"])),
        ("- Versements nets à la banque", _f(-f["vers_banque"])),
        ("= Argent attendu en caisse", _f(f["caisse_attendue"])),
        ("Argent constaté en caisse", _f(f["argent_disponible"])),
        ("Écart", _f(f["ecart_caisse"])),
    ]
    detail_hors = f["tableau"][f["tableau"]["bloc"] == calc.HORS]
    hors = [(x["libelle"], _f(x["Total"])) for x in detail_hors.to_dict("records") if not calc._nan(x["Total"])]
    banque = " · ".join(f"{i} {_f(s)} F" for i, s in r["banque"])
    return ui.TagList(
        ui.div({"class": "tbx-tuiles"},
               _tuile("Argent disponible", f"{_f(f['argent_disponible'])} F",
                      " · ".join(f"{i} {_f(s)}" for i, s in f["caisses"]) or "Caisses du centre"),
               _tuile("Capital de base", f"{_f(f['cible_tresorerie'])} F",
                      f"{calc.mois_txt(p['cible_tresorerie_mois'])} de charges d'exploitation"),
               _tuile("Mois de charges couverts", calc.mois_txt(f["couverture_mois"]),
                      f"Charges moyennes : {_f(f['charges_mois'])} F par mois", f["niveaux"]["caisse"]),
               _tuile("Banque", banque or "-", "Commune à tous les centres")),
        _graphique_caisse(f),
        ui.div({"class": "tbx-deux"},
               ui.div({"class": "tbx-carte tbx-carte--tableau"},
                      ui.div({"class": "tbx-titre"}, "Où est passé le résultat"),
                      _table_simple(["", "FCFA"], lignes, "tbx-forces")),
               ui.div({"class": "tbx-carte tbx-carte--tableau"},
                      ui.div({"class": "tbx-titre"}, "Sorties hors exploitation"),
                      _table_simple(["", "FCFA"], hors or [("Aucune sur la période", "-")], "tbx-forces"))),
        ui.p({"class": "tbx-notes-bas"},
             "Les soldes sont recalculés à partir des écritures : un écart différent de zéro signale une "
             "écriture incohérente à faire vérifier."),
    )


CONTROLES = [
    ("jours", "Périodes sans écriture", "Au moins une semaine de jours ouvrés sans aucune écriture"),
    ("sans_tiers", "Encaissements sans élève", "Frais d'élève encaissés sans compte tiers"),
    ("dates", "Dates aberrantes", "Dans le futur ou plus d'un an avant la période, toutes périodes"),
    ("attente", "Opérations au compte d'attente", "Compte définitif encore à choisir"),
    ("non_classe", "Comptes non classés", "Comptés en exploitation faute de classement"),
    ("non_validees", "Pièces non validées", "Saisies ou renvoyées, incluses dans les chiffres"),
]


def _onglet_fiabilite(f):
    fi = f["fiabilite"]
    ctl, niv = fi["controles"], fi["niveaux"]

    def operations(lignes, libelle="Voir les opérations"):
        if not lignes:
            return None
        rangs = [(f"{d:%d/%m/%Y}", p or "", l or "", _f(m) if m is not None else "")
                 for d, p, l, m in lignes[:LISTE_MAX]]
        suite = ui.p({"class": "tbx-notes-bas"}, f"{len(lignes) - LISTE_MAX} autres non affichées.") \
            if len(lignes) > LISTE_MAX else None
        return _deplier(libelle, _table_simple(["Date", "Pièce", "Libellé", "Montant"], rangs, "tbx-ops"), suite)

    lignes = []
    for cle, titre, sous in CONTROLES:
        c = ctl[cle]
        valeur = str(c["nombre"])
        if c.get("montant"):
            valeur += f" · {_f(c['montant'])} F"
        lignes.append(ui.div({"class": "tbx-controle"},
                             ui.div({"class": "tbx-controle-tete"},
                                    ui.div(ui.div({"class": "tbx-cmp-titre"}, titre),
                                           ui.div({"class": "tbx-cmp-sous"}, sous)),
                                    ui.div({"class": "tbx-controle-nombre"}, valeur), _pastille(niv[cle])),
                             operations(c["lignes"], "Voir les périodes" if cle == "jours" else "Voir les opérations")))
    lignes.append(ui.div({"class": "tbx-controle"},
                         ui.div({"class": "tbx-controle-tete"},
                                ui.div(ui.div({"class": "tbx-cmp-titre"}, "Écart entre attendu et constaté"),
                                       ui.div({"class": "tbx-cmp-sous"}, "Caisses du centre, voir l'onglet Caisse")),
                                ui.div({"class": "tbx-controle-nombre"}, f"{_f(f['ecart_caisse'])} F"),
                                _pastille(niv["ecart"]))))
    return ui.TagList(
        ui.div({"class": "tbx-tuiles tbx-tuiles--3"},
               _tuile("Pièces validées", calc.pct(fi["part_validee"], 0),
                      f"{fi['validees']} sur {fi['pieces']} pièces de la période", niv["global"])),
        ui.div({"class": "tbx-carte tbx-liste"}, *lignes),
    )


# --- interface ----------------------------------------------------------------------

@module.ui
def onglet():
    debut, fin = calc.periode_par_defaut()
    centres = calc.centres_proposes()
    choix = dict(zip(centres["code_centre"], centres["intitule"]))
    return ui.nav_panel(
        "Tableau de bord",
        ui.tags.link(rel="stylesheet", href="tableau_bord.css"),
        ui.div(
            {"class": "tbx"},
            ui.div({"class": "tbx-entete"},
                   ui.div({"class": "tbx-surtitre"}, "Hakili Lab"),
                   ui.h1({"class": "tbx-h1"}, "Tableau de bord"),
                   ui.output_text("sous_titre", inline=True)),
            ui.div(
                {"class": "tbx-barre-filtres"},
                ui.div({"class": "tbx-filtres"},
                       ui.input_date_range("dates", "Période", start=debut, end=fin, format="dd/mm/yyyy",
                                           language="fr", separator="au", weekstart=1),
                       ui.input_selectize("centres", "Centres", choix, multiple=True,
                                          options={"placeholder": "Tous les centres",
                                                   "plugins": ["remove_button"]})),
                ui.input_radio_buttons("vue", None, {"ensemble": "Vue d'ensemble", "fiche": "Fiche centre"},
                                       selected="ensemble", inline=True),
            ),
            ui.panel_conditional("input.vue !== 'fiche'", ui.output_ui("ensemble")),
            ui.panel_conditional(
                "input.vue === 'fiche'",
                ui.input_action_link("retour", "Retour à la vue d'ensemble", class_="tbx-lien tbx-retour"),
                ui.div({"class": "tbx-fiche-tete"},
                       ui.output_ui("fiche_titre"),
                       ui.div({"class": "tbx-fiche-choix"},
                              ui.input_select("centre_fiche", "Centre affiché", choix))),
                ui.navset_underline(
                    ui.nav_panel("Résultat", ui.output_ui("f_resultat")),
                    ui.nav_panel("Élèves", ui.output_ui("f_eleves")),
                    ui.nav_panel("Caisse", ui.output_ui("f_caisse")),
                    ui.nav_panel("Fiabilité", ui.output_ui("f_fiabilite")),
                    id="onglet_fiche"),
            ),
        ),
        value="tableau_bord", icon=ui.tags.i({"class": "bi bi-speedometer2"}),
    )


# --- serveur ------------------------------------------------------------------------

@module.server
def serveur(input, output, session, autorise, actualiser):
    """autorise : calc reactif vrai pour le comptable. actualiser : appele
    dans le calcul pour le relancer a chaque nouvelle ecriture."""

    @reactive.calc
    def noms():
        req(autorise())
        p = calc.centres_proposes()
        return dict(zip(p["code_centre"], p["intitule"]))

    @reactive.calc
    def centres_choisis():
        # Jamais de confiance dans la valeur envoyee par le navigateur.
        n = noms()
        return [c for c in (input.centres() or ()) if c in n] or list(n)

    @reactive.calc
    def resultat():
        req(autorise())
        actualiser()
        debut, fin = input.dates() or (None, None)
        if not debut or not fin:
            return {"erreur": "Choisissez une date de début et une date de fin."}
        debut, fin = pd.Timestamp(debut).date(), pd.Timestamp(fin).date()
        if fin < debut:
            return {"erreur": "La date de fin est avant la date de début : corrigez la période."}
        centres = centres_choisis()
        if not centres:
            return {"erreur": "Aucun centre n'a encore de caisse dans l'application."}
        return calc.calculer(debut, fin, centres)

    # La liste de la fiche suit les centres choisis en haut de page.
    @reactive.effect
    def _choix_fiche():
        n = noms()
        centres = centres_choisis()
        with reactive.isolate():
            actuel = input.centre_fiche()
        ui.update_select("centre_fiche", choices={c: n[c] for c in centres},
                         selected=actuel if actuel in centres else centres[0] if centres else None)

    @reactive.effect
    @reactive.event(input.ouvrir)
    def _ouvrir_fiche():
        code = input.ouvrir()
        if code in centres_choisis():
            ui.update_select("centre_fiche", selected=code)
            ui.update_radio_buttons("vue", selected="fiche")

    @reactive.effect
    @reactive.event(input.retour)
    def _retour():
        ui.update_radio_buttons("vue", selected="ensemble")

    @render.text
    def sous_titre():
        r = resultat()
        if "erreur" in r:
            return ""
        n = noms()
        qui = "tous les centres" if len(r["centres"]) == len(n) else ", ".join(n.get(c, c) for c in r["centres"])
        return f"{_periode(r['debut'], r['fin']).capitalize()}, {qui}."

    @render.ui
    def ensemble():
        r = resultat()
        if "erreur" in r:
            return _message(r["erreur"], "tbx-vide tbx-erreur")
        if r["vide"]:
            return _message("Aucun mouvement de caisse ou de banque sur cette période pour ces centres.")
        return _vue_ensemble(session.ns, r, noms())

    def _fiche():
        r = resultat()
        if "erreur" in r:
            return r, None
        c = input.centre_fiche()
        if c not in r["fiches"]:
            c = r["centres"][0]
        return r, c

    @render.ui
    def fiche_titre():
        r, c = _fiche()
        if c is None:
            return _message(r["erreur"], "tbx-vide tbx-erreur")
        f = r["fiches"][c]
        notes = _notes(f)
        return ui.div({"class": "tbx-fiche-titre"},
                      ui.h2({"class": "tbx-h2"}, f"Centre de {noms().get(c, c)}"),
                      ui.p({"class": "tbx-section-sous"},
                           f"{_periode(r['debut'], r['fin']).capitalize()}, au {r['fin']:%d/%m/%Y}."
                           + (" " + ", ".join(notes).capitalize() + "." if notes else "")))

    def _rendu(construire):
        r, c = _fiche()
        if c is None:
            return None
        if r["vide"]:
            return _message("Aucun mouvement de caisse ou de banque sur cette période pour ce centre.")
        return construire(r, r["fiches"][c])

    @render.ui
    def f_resultat():
        return _rendu(lambda r, f: _onglet_resultat(f, r["mois"]))

    @render.ui
    def f_eleves():
        return _rendu(lambda r, f: _onglet_eleves(f, r["mois"]))

    @render.ui
    def f_caisse():
        return _rendu(lambda r, f: _onglet_caisse(f, r))

    @render.ui
    def f_fiabilite():
        return _rendu(lambda r, f: _onglet_fiabilite(f))

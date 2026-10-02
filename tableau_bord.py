# ---------------------------------------------------------------------------
# Tableau de bord (02/10/2026) - interface et serveur
#
# En haut : la periode (du ... au ...) et les centres. Ces deux filtres
# alimentent les bandeaux et le tableau par un seul appel a
# logic.tableau_bord.calculer(). Reserve au comptable : le controle est fait
# ici, cote serveur (autorise()), pas seulement par l'absence d'onglet.
#
# Branchement dans app.py :
#   ui      : tableau_bord.onglet("tb")
#   serveur : tableau_bord.serveur("tb", autorise=..., actualiser=...)
# ---------------------------------------------------------------------------

import math

import pandas as pd
from shiny import module, reactive, render, req, ui

import logic.tableau_bord as calc
from composants import format_montant

MOIS_COURTS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août",
               "sept.", "oct.", "nov.", "déc."]
BLOCS = [(calc.ENCAISSEMENT, "Encaissements d'exploitation", "Total encaissements"),
         (calc.CHARGE, "Charges d'exploitation", "Total charges"),
         (calc.HORS, "Sorties hors exploitation", "Total hors exploitation (net)")]


def _vide(v):
    return v is None or (isinstance(v, float) and math.isnan(v))


def _f(v):
    """Montant en FCFA, separateur de milliers ; « - » si pas de donnee."""
    return "-" if _vide(v) else format_montant(v)


def _mois(aaaa_mm):
    return f"{MOIS_COURTS[int(aaaa_mm[5:]) - 1]} {aaaa_mm[2:4]}"


def _nb(n, singulier, pluriel):
    return f"{n} {singulier if n == 1 else pluriel}"


# --- interface ----------------------------------------------------------------------

@module.ui
def onglet():
    debut, fin = calc.periode_par_defaut()
    centres = calc.centres_proposes()
    return ui.nav_panel(
        "Tableau de bord",
        ui.tags.link(rel="stylesheet", href="tableau_bord.css"),
        ui.div(
            {"class": "tbx"},
            ui.div(
                {"class": "tbx-filtres"},
                ui.input_date_range("dates", "Période", start=debut, end=fin, format="dd/mm/yyyy",
                                    language="fr", separator="au", weekstart=1),
                ui.input_selectize("centres", "Centres",
                                   dict(zip(centres["code_centre"], centres["intitule"])),
                                   multiple=True,
                                   options={"placeholder": "Tous les centres",
                                            "plugins": ["remove_button"]}),
            ),
            ui.output_ui("contenu"),
        ),
        value="tableau_bord", icon=ui.tags.i({"class": "bi bi-speedometer2"}),
    )


# --- morceaux d'affichage -------------------------------------------------------------

def _chiffre(libelle, valeur, ton="", detail=None):
    return ui.div(
        {"class": "tbx-chiffre"},
        ui.div({"class": "tbx-libelle"}, libelle),
        ui.div({"class": f"tbx-valeur {ton}".strip()}, _f(valeur), ui.span({"class": "tbx-unite"}, " F")),
        ui.div({"class": "tbx-detail"}, detail) if detail else None,
    )


def _ton_resultat(v):
    return "tbx-positif" if v > 0 else ("tbx-negatif" if v < 0 else "")


def _bandeau(nom, c, notes=(), principal=False):
    """Les trois chiffres d'un centre (ou de l'ensemble)."""
    caisses = c.get("caisses")
    detail = " · ".join(f"{i} {_f(s)}" for i, s in caisses) if caisses else "caisses des centres choisis"
    return ui.div(
        {"class": "tbx-carte" + (" tbx-carte--principale" if principal else "")},
        ui.div({"class": "tbx-nom"}, nom),
        ui.div(
            {"class": "tbx-chiffres"},
            _chiffre("Résultat", c["resultat"], _ton_resultat(c["resultat"])),
            _chiffre("Sorties hors exploitation", c["hors_exploitation"],
                     "tbx-attention" if c["hors_exploitation"] > 0 else ""),
            _chiffre("Argent disponible", c["argent_disponible"],
                     "tbx-negatif" if c["argent_disponible"] < 0 else "", detail),
        ),
        ui.div({"class": "tbx-notes"}, " · ".join(notes)) if notes else None,
    )


def _notes_centre(c):
    notes = []
    if c["non_validees"]:
        notes.append("dont " + _nb(c["non_validees"], "pièce non validée", "pièces non validées"))
    if c["attente"]:
        notes.append(f"dont {_f(c['attente'])} F en attente de classement")
    return notes


def _banque(r):
    """La banque, une seule fois : elle n'appartient a aucun centre."""
    return [ui.div({"class": "tbx-carte tbx-carte--banque"},
                   ui.div({"class": "tbx-nom"}, f"Banque {i}"),
                   ui.div({"class": "tbx-chiffres"},
                          _chiffre(f"Solde au {r['fin']:%d/%m/%Y}", s, "tbx-negatif" if s < 0 else "",
                                   "commune à tous les centres")))
            for i, s in r["banque"]]


def _ligne(libelle, valeurs, classe=""):
    return ui.tags.tr({"class": classe} if classe else {},
                      ui.tags.th({"scope": "row"}, libelle),
                      *[ui.tags.td(v) for v in valeurs])


def _tableau(r):
    t, tot, mois = r["tableau"], r["totaux"], r["mois"]
    colonnes = mois + ["Total"]
    corps = []
    for bloc, titre, libelle_total in BLOCS:
        corps.append(ui.tags.tr({"class": "tbx-groupe"},
                                ui.tags.th({"colspan": len(colonnes) + 1, "scope": "colgroup"}, titre)))
        for ligne in t[t["bloc"] == bloc].to_dict("records"):
            corps.append(_ligne(ligne["libelle"], [_f(ligne[c]) for c in colonnes]))
        cle = {calc.ENCAISSEMENT: "encaissements", calc.CHARGE: "charges", calc.HORS: "hors_exploitation"}[bloc]
        corps.append(_ligne(libelle_total, [_f(tot[cle][c]) for c in colonnes], "tbx-total"))
        if bloc == calc.CHARGE:
            corps.append(_ligne("Résultat d'exploitation", [_f(tot["resultat"][c]) for c in colonnes],
                                "tbx-resultat"))
            corps.append(_ligne("en % des encaissements",
                                ["-" if _vide(p) else f"{p * 100:.1f} %".replace(".", ",")
                                 for p in (tot["pct"][c] for c in colonnes)], "tbx-pct"))
    return ui.div(
        {"class": "tbx-carte tbx-carte--tableau"},
        ui.div({"class": "tbx-titre"}, "Compte de résultat mensuel en encaissements",
               ui.span({"class": "tbx-sous-titre"}, "en FCFA")),
        ui.div({"class": "tbx-defile", "tabindex": "0"},
               ui.tags.table({"class": "tbx-table"},
                             ui.tags.thead(ui.tags.tr(ui.tags.th({"scope": "col"}, "Poste"),
                                                      *[ui.tags.th({"scope": "col"}, _mois(m)) for m in mois],
                                                      ui.tags.th({"scope": "col"}, "Total"))),
                             ui.tags.tbody(*corps))),
    )


def _message(texte, classe="tbx-vide"):
    return ui.div({"class": f"tbx-carte {classe}"}, texte)


# --- serveur ------------------------------------------------------------------------

@module.server
def serveur(input, output, session, autorise, actualiser):
    """autorise : calc reactif vrai pour le comptable. actualiser : appele
    dans le calcul pour le relancer a chaque nouvelle ecriture."""

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
        proposes = calc.centres_proposes()
        noms = dict(zip(proposes["code_centre"], proposes["intitule"]))
        # Jamais de confiance dans la valeur envoyee par le navigateur.
        centres = [c for c in (input.centres() or ()) if c in noms] or list(noms)
        if not centres:
            return {"erreur": "Aucun centre n'a encore de caisse dans l'application."}
        r = calc.calculer(debut, fin, centres)
        r["noms"] = noms
        return r

    @render.ui
    def contenu():
        r = resultat()
        if "erreur" in r:
            return _message(r["erreur"], "tbx-vide tbx-erreur")

        alertes = []
        if r["non_classes"]:
            alertes.append(ui.div({"class": "tbx-alerte"},
                                  ui.tags.i({"class": "bi bi-exclamation-triangle"}),
                                  _nb(r["non_classes"], "compte non classé compté",
                                      "comptes non classés comptés") + " en exploitation"
                                  " (à classer dans la table classement_comptes)."))

        cartes = []
        if len(r["centres"]) > 1:
            notes = []
            if r["non_validees"]:
                notes.append("dont " + _nb(r["non_validees"], "pièce non validée", "pièces non validées"))
            if r["attente"]:
                notes.append(f"dont {_f(r['attente'])} F en attente de classement")
            cartes.append(_bandeau("Ensemble des centres choisis", r["ensemble"], notes, principal=True))
        for c in r["centres"]:
            cartes.append(_bandeau(r["noms"].get(c, c), r["par_centre"][c], _notes_centre(r["par_centre"][c])))

        tableau = (_message("Aucun mouvement de caisse ou de banque sur cette période pour ces centres.")
                   if r["vide"] else _tableau(r))
        return ui.TagList(*alertes,
                          ui.div({"class": "tbx-bandeaux"}, *cartes, *_banque(r)),
                          tableau)

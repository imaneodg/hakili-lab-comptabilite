# ---------------------------------------------------------------------------
# Camp de vacances, cibles par centre, forces 3 et 4 (07/10/2026).
#
# Les pieces sont construites par les vrais modeles de saisie
# (logic.modeles.construire_operation), puis lues par le tableau de bord :
# on verifie le chemin complet formulaire -> libelle -> rubrique.
#
# Base PostgreSQL reelle (DATABASE_URL), comme test_tableau_bord. Pieces
# datees de 2098, effacees a la fin.
# ---------------------------------------------------------------------------

import json
import math
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import logic.donnees as dl
import logic.modeles as md
import logic.tableau_bord as tb

RACINE = Path(__file__).resolve().parent.parent
MIGRATIONS = sorted((RACINE / "sql" / "migrations").glob("2026-10-0*.sql"))
PREFIXE = "TBCAMP-"
DEBUT, FIN = date(2098, 7, 1), date(2098, 7, 31)
AUJOURD_HUI = date(2098, 12, 31)
JOURNAUX = pd.DataFrame({"journal": ["CP", "CMD", "Banque"],
                         "compte_contrepartie": ["571100", "571200", "521100"],
                         "type": ["tresorerie"] * 3})


def _base_disponible():
    try:
        with dl._connexion() as c, c.cursor() as cur:
            cur.execute("SELECT 1 FROM centres WHERE code_centre IN ('TAM', 'SAA') HAVING count(*) = 2")
            return cur.fetchone() is not None
    except Exception:
        return False


base = pytest.mark.skipif(not _base_disponible(), reason="base PostgreSQL indisponible")


def _op(modele, valeurs, journal):
    op = md.construire_operation(modele, valeurs, journal, JOURNAUX)
    assert op is not None and md.operation_equilibree(op), modele
    return op


# --- formulaires (calcul pur) ---------------------------------------------------

ELEVE = {"tiers": "411KABRE", "tiers_nom": "KABRE CHARLES ELIEL", "montant": 50000}


def _encaissement(activite, nature="avance", mois=("JUILLET",)):
    return {**ELEVE, "activite": activite,
            "repartition": [{"mois": list(mois), "nature": nature, "montant": 50000}]}


def test_encaissement_du_camp_ecrit_cv():
    L = _op("encaissement", _encaissement("camp"), "CP")[0]["lignes"]
    assert list(L["libelle"]) == ["FRAIS CV - KABRE CHARLES ELIEL", "AVANCE CV JUIL - KABRE CHARLES ELIEL"]
    assert all(md.libelle_reconnu_camp(x) for x in L["libelle"])


def test_encaissement_des_cours_inchange():
    L = _op("encaissement", _encaissement("cours"), "CP")[0]["lignes"]
    assert list(L["libelle"]) == ["FRAIS CA - KABRE CHARLES ELIEL", "AVANCE CA JUIL - KABRE CHARLES ELIEL"]
    assert not any(md.libelle_reconnu_camp(x) for x in L["libelle"])
    # une piece enregistree avant le 07/10/2026 n'a pas d'activite : cours d'appui
    sans = {k: v for k, v in _encaissement("cours").items() if k != "activite"}
    assert list(_op("encaissement", sans, "CP")[0]["lignes"]["libelle"]) == list(L["libelle"])


@pytest.mark.parametrize("nature,base", [("frais", "FRAIS CV"), ("solde", "SOLDE CV")])
def test_toutes_les_natures_du_camp(nature, base):
    L = _op("encaissement", _encaissement("camp", nature), "CP")[0]["lignes"]
    assert L.iloc[1]["libelle"].startswith(base + " JUIL")


def _fournisseur(libelle, activite, mois=("JUILLET",)):
    return {"tiers": "401KABORE", "tiers_nom": "KABORE BERNARD", "libelle": libelle, "montant": 30000,
            "timbre": 0, "activite": activite,
            "repartition": [{"mois": list(mois), "nature": "paiement", "montant": 30000}]}


@pytest.mark.parametrize("modele,journal", [("fournisseur", "CMD"), ("fournisseur_banque", "Banque")])
def test_depense_du_camp_porte_le_mot_camp(modele, journal):
    L = _op(modele, _fournisseur("PAIEMENT VACATION", "camp"), journal)[0]["lignes"]
    assert L.iloc[0]["libelle"] == "PAIEMENT CAMP VACATION JUIL - KABORE BERNARD"
    assert all(md.porte_mot_camp(x) for x in L["libelle"])


def test_le_mot_camp_n_est_jamais_double_ni_coupe():
    L = _op("fournisseur", _fournisseur("CAMP VACATION", "camp"), "CMD")[0]["lignes"]
    assert L.iloc[0]["libelle"].count("CAMP") == 1
    long = "ENCADREMENT ET ANIMATION DES ENFANTS PENDANT LES SORTIES"
    lib = md._libelle_reglement_fournisseur("paiement", long, ["JUIN", "JUILLET", "AOUT"], "NOM", camp=True)
    assert len(lib) <= md.LIBELLE_MAX and lib.startswith("PAIEMENT CAMP ")


def test_depense_des_cours_sans_mot_camp():
    L = _op("fournisseur", _fournisseur("PAIEMENT VACATION", "cours"), "CMD")[0]["lignes"]
    assert not any(md.porte_mot_camp(x) for x in L["libelle"])


def test_remuneration_du_camp():
    v = {"personnel": "422OUEDRAOGO", "personnel_nom": "OUEDRAOGO", "mois": "JUILLET", "montant": 15000,
         "activite": "camp"}
    L = _op("remuneration", v, "CMD")[0]["lignes"]
    assert set(L["libelle"]) == {"REMUNERATION CAMP JUILLET/OUEDRAOGO"}


def test_campagne_n_est_pas_le_camp():
    assert not md.porte_mot_camp("CAMPAGNE PUBLICITAIRE")
    assert not md.libelle_reconnu_camp("CAMPAGNE PUBLICITAIRE")
    assert md.porte_mot_camp("PAIEMENT VACATION CAMP")


def test_le_choix_de_l_activite_reste_d_une_piece_a_l_autre():
    champ = next(c for c in md.modele_par_id("encaissement")["champs"] if c["n"] == "activite")
    assert champ["garde"] and champ["affichage"] == "boutons"
    assert next(iter(champ["options"])) == "cours"


# --- import des brouillards : marque du camp ----------------------------------

def test_import_remet_la_marque_du_camp():
    import import_historique as ih
    f = ih.libelle_camp
    assert f("AVANCE FRAIS CV KABRE CHARLES/S1", "AVANCE FRAIS CA KABRE CHARLES ELIEL", "411000", True) \
        == "AVANCE FRAIS CV KABRE CHARLES ELIEL"
    assert f("FRAIS CAMP VACANCES NACRO KORINE/S2", "FRAIS CA NACRO KORINE", "411000", True) \
        == "FRAIS CV NACRO KORINE"
    assert f("AVANE FRAIS CV KANAZOE/S1", "FRAIS CA AVANE KANAZOE AIMANE", "411000", True) \
        == "FRAIS CV AVANE KANAZOE AIMANE"
    # sortie sur le compte eleves : signalee par le script, jamais maquillee
    assert f("AVANCE PAIEMEN CAMP VACANCES S1/KOTIM", "AVANCE FRAIS CA PAIEMEN KOTIM", "411000", False) \
        == "AVANCE FRAIS CA PAIEMEN KOTIM"
    assert f("AVANCE PAIEMENT CAMPS1 BARRO", "AVANCE PAIEMENT CAMPS1 BARRO", "401000", False) \
        == "CAMP AVANCE PAIEMENT CAMPS1 BARRO"
    # sans camp dans l'original, rien ne change
    assert f("FRAIS COURS MPC YODA KENZA/MAI", "FRAIS CA YODA KENZA/MAI", "411000", True) \
        == "FRAIS CA YODA KENZA/MAI"
    assert f("CAMPAGNE AFFICHES", "IMPRESSION AFFICHES", "401000", False) == "IMPRESSION AFFICHES"


# --- base : du formulaire au tableau de bord --------------------------------------

def _inserer(cle, centre, jour, modele, op, valeurs=None, contrepartie=""):
    with dl._connexion() as c, c.cursor() as cur:
        for p in op:
            for i, x in enumerate(p["lignes"].to_dict("records")):
                cur.execute("""
                    INSERT INTO ecritures (id_ligne, id_piece, journal, centre, date_piece, compte,
                                           code_tiers, libelle, debit, credit, statut, modele,
                                           valeurs_json, centre_contrepartie)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'validee', %s, %s, %s)""",
                            (f"{PREFIXE}{cle}-{p['journal']}-{i}", f"{PREFIXE}{cle}-{p['journal']}",
                             p["journal"], centre, jour, x["compte"], x["code_tiers"], x["libelle"],
                             x["debit"], x["credit"], modele,
                             json.dumps(valeurs) if valeurs is not None else None, contrepartie))


def _effacer():
    with dl._connexion() as c, c.cursor() as cur:
        cur.execute("DELETE FROM ecritures WHERE id_ligne LIKE %s", (PREFIXE + "%",))


@pytest.fixture(scope="module")
def juillet():
    with dl._connexion() as c, c.cursor() as cur:
        for m in MIGRATIONS:
            cur.execute(m.read_text(encoding="utf-8"))
    _effacer()
    jour = "2098-07-10"
    _inserer("camp", "TAM", jour, "encaissement", _op("encaissement", _encaissement("camp"), "CP"))
    cours = {**_encaissement("cours"), "montant": 20000,
             "repartition": [{"mois": ["JUILLET"], "nature": "frais", "montant": 20000}]}
    _inserer("cours", "TAM", jour, "encaissement", _op("encaissement", cours, "CP"))
    _inserer("vac", "TAM", jour, "fournisseur", _op("fournisseur", _fournisseur("VACATION", "camp"), "CMD"))
    fourn = {**_fournisseur("FOURNITURE GOUTER", "camp"), "montant": 6000,
             "repartition": [{"mois": ["JUILLET"], "nature": "paiement", "montant": 6000}]}
    _inserer("four", "TAM", jour, "fournisseur", _op("fournisseur", fourn, "CMD"))
    pub = {**_fournisseur("CAMPAGNE PUBLICITAIRE", "cours"), "montant": 3000,
           "repartition": [{"mois": ["JUILLET"], "nature": "paiement", "montant": 3000}]}
    _inserer("pub", "TAM", jour, "fournisseur", _op("fournisseur", pub, "CMD"))
    yield tb.calculer(DEBUT, FIN, ["TAM"], AUJOURD_HUI)
    _effacer()


def _total(r, libelle):
    t = r["fiches"]["TAM"]["tableau"]
    sous = t[t["libelle"] == libelle]
    return float(sous.iloc[0]["Total"]) if len(sous) else float("nan")


@base
def test_camp_et_cours_separes(juillet):
    f = juillet["fiches"]["TAM"]
    assert _total(juillet, "Camp de vacances") == 50000
    assert _total(juillet, "Cours d'appui") == 20000
    assert f["camp"] == 50000 and f["cours_appui"] == 20000
    assert f["mensuel"][0]["mois_camp"] is True


@base
def test_depenses_du_camp_classees_par_nature(juillet):
    assert _total(juillet, "Vacations et salaires") == 30000          # la vacation du camp
    assert _total(juillet, "Fournitures et impressions") == 6000       # pas en salaires
    assert _total(juillet, "Autres charges courantes") == 3000         # CAMPAGNE n'est pas le camp


@base
def test_vacation_du_camp_hors_graphique_des_cours(juillet):
    juil = juillet["fiches"]["TAM"]["eleves"]["par_mois"][0]
    assert juil["frais"] == 20000
    assert math.isnan(juil["vacations"])


@base
def test_forces_trois_et_quatre(juillet):
    f = juillet["fiches"]["TAM"]
    cible, dispo = f["cible_tresorerie"], f["argent_disponible"]
    assert f["reste_a_constituer"] == pytest.approx(max(0, cible - dispo))
    assert f["distribuable"] == pytest.approx(max(0, dispo - cible))
    assert min(f["reste_a_constituer"], f["distribuable"]) == 0


@base
def test_pages_rendues_sans_erreur(juillet):
    import tableau_bord as ui_tb
    noms = {"TAM": "Tampouy"}
    f = juillet["fiches"]["TAM"]
    html = str(ui_tb._onglet_caisse(f, juillet)) + str(ui_tb._onglet_resultat(f, juillet["mois"]))
    assert "Disponible pour distribuer ou investir" in html and "Reste à constituer" in html
    assert '<th scope="row">Plafond salarial</th>' in html and '<th scope="row">Salaires payés</th>' not in html
    deux = tb.calculer(DEBUT, FIN, ["TAM", "SAA"], AUJOURD_HUI)
    page = str(ui_tb._vue_ensemble(lambda x: x, deux, {**noms, "SAA": "Saaba"}))
    assert "dont camp de vacances" in page and "dont cours d" in page


# --- cibles par centre ------------------------------------------------------------

def test_verification_des_cibles():
    assert tb.verifier_parametres(15, 2) == (0.15, 2.0)
    assert tb.verifier_parametres("12.5", "1.5") == (0.125, 1.5)
    for marge, mois in ((150, 2), (-1, 2), (15, 13), (15, -0.5), (None, 2), ("abc", 2), (float("nan"), 2)):
        with pytest.raises(ValueError):
            tb.verifier_parametres(marge, mois)


@base
def test_enregistrement_des_cibles_tout_ou_rien():
    avant = tb.parametres_centres(["TAM", "SAA"])
    try:
        tb.enregistrer_parametres({"TAM": (20, 3), "SAA": (10, 1.5)})
        p = tb.parametres_centres(["TAM", "SAA"])
        assert p["TAM"] == {"cible_marge": 0.2, "cible_tresorerie_mois": 3.0}
        assert p["SAA"] == {"cible_marge": 0.1, "cible_tresorerie_mois": 1.5}
        with pytest.raises(ValueError):
            tb.enregistrer_parametres({"TAM": (25, 2), "SAA": (500, 2)})
        assert tb.parametres_centres(["TAM"])["TAM"]["cible_marge"] == 0.2   # rien n'a change
    finally:
        tb.enregistrer_parametres({c: (v["cible_marge"] * 100, v["cible_tresorerie_mois"])
                                   for c, v in avant.items()})


def test_une_seule_formule_du_plafond():
    assert tb.plafond_salarial(1000, 700, 500, 0.15) == pytest.approx(1000 - 200 - 150)
    source = (RACINE / "tableau_bord.py").read_text(encoding="utf-8")
    assert "def _plafond_salarial" not in source and "calc.plafond_salarial" in source

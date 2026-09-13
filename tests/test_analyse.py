# ---------------------------------------------------------------------------
# Tests des fonctions pures de logic/analyse.py ajoutees le 06/09/2026 pour
# le catalogue de questions de l'assistant IA.
#
# Toutes les fonctions testees ici acceptent ref/d en parametres explicites
# (voir leur signature) : aucun test de ce fichier n'ouvre de connexion
# Postgres, contrairement a tests/test_auth.py. Lancer avec les autres :
#   pytest tests/ -v
# ---------------------------------------------------------------------------

import pandas as pd
import pytest

import logic.analyse as an

CENTRES = ["PIS", "TAM"]


def _ref():
    comptes = pd.DataFrame([
        {"compte": "571100", "intitule": "Caisse principale", "nature": "tresorerie"},
        {"compte": "411000", "intitule": "Clients", "nature": "tiers"},
        {"compte": "422000", "intitule": "Personnel - remunerations", "nature": "tiers"},
        {"compte": "632710", "intitule": "Vacations", "nature": "charge"},
        {"compte": "401000", "intitule": "Fournisseurs", "nature": "tiers"},
        {"compte": "622200", "intitule": "Location de batiment (loyer)", "nature": "charge"},
        {"compte": "632720", "intitule": "Gardiennage bureau", "nature": "charge"},
        {"compte": "605100", "intitule": "Eau", "nature": "charge"},
        {"compte": "605200", "intitule": "Electricite", "nature": "charge"},
        {"compte": "422300", "intitule": "Avances personnel", "nature": "tiers"},
    ])
    journaux = pd.DataFrame([
        {"journal": "CP", "compte_contrepartie": "571100", "type": "tresorerie",
         "solde_ouverture": 0.0},
    ])
    centres = pd.DataFrame([{"code_centre": c} for c in CENTRES])
    tiers = pd.DataFrame([
        {"code_tiers": "422PROF1", "intitule": "M. Kabore"},
        {"code_tiers": "422PROF2", "intitule": "Mme Sawadogo"},
    ])
    return {"comptes": comptes, "journaux": journaux, "centres": centres, "tiers": tiers}


def _ligne(centre, compte, date_piece, debit=0, credit=0, code_tiers="",
           modele="", journal="CP", id_piece="P1", statut="validee"):
    return {"centre": centre, "compte": compte, "date_piece": date_piece,
            "debit": debit, "credit": credit, "code_tiers": code_tiers,
            "modele": modele, "journal": journal, "id_piece": id_piece, "statut": statut}


# --- part_masse_salariale : inclut desormais les vacations (632710) --------

def test_part_masse_salariale_additionne_salaires_et_vacations():
    # 422000 (salaires) est de nature 'tiers', jamais 'charge' : le modele
    # "remuneration" ne touche aucun compte de charge (voir logic/modeles.py).
    # part_masse_salariale doit donc rajouter les salaires au denominateur
    # lui-meme (_total_charges seul ne les compte pas), pour que le
    # numerateur (masse_salariale) reste un sous-ensemble du denominateur
    # (total_charges) et que part_pct ne depasse jamais 100 %.
    ref = _ref()
    d = pd.DataFrame([
        _ligne("PIS", "422000", "2026-03-05", debit=50000, code_tiers="422PROF1"),
        _ligne("PIS", "632710", "2026-03-06", debit=30000, code_tiers="422PROF2"),
        _ligne("PIS", "622200", "2026-03-07", debit=20000),
    ])
    res = an.part_masse_salariale("202603", "PIS", ref, d)
    assert res["salaires"] == 50000
    assert res["vacations"] == 30000
    assert res["masse_salariale"] == 80000
    # _total_charges (632710 + 622200) = 50000, plus les salaires (50000)
    # ajoutes par part_masse_salariale = 100000.
    assert res["total_charges"] == 100000
    assert res["part_pct"] == pytest.approx(80.0)


# --- poste_depense_principal / depense_anormale / part_charges_fixes :
# 422000 (remuneration) doit desormais compter comme une charge (corrige le
# 10/09/2026 - voir _comptes_charge_elargi et _total_charges_avec_salaires).

def test_poste_depense_principal_peut_designer_un_salaire():
    # Avant le correctif, 422000 etait toujours ignore (nature 'tiers'), donc
    # le loyer (moins cher ici) ressortait a tort comme premier poste.
    ref = _ref()
    d = pd.DataFrame([
        _ligne("PIS", "422000", "2026-03-05", debit=150000, code_tiers="422PROF1"),
        _ligne("PIS", "622200", "2026-03-07", debit=40000),
    ])
    res = an.poste_depense_principal("202603", "PIS", ref, d)
    assert res["compte"] == "422000"
    assert res["montant"] == 150000


def test_depense_anormale_peut_signaler_un_salaire():
    ref = _ref()
    d = pd.DataFrame([
        _ligne("PIS", "422000", "2026-01-05", debit=50000, code_tiers="422PROF1"),
        _ligne("PIS", "422000", "2026-02-05", debit=50000, code_tiers="422PROF1"),
        _ligne("PIS", "422000", "2026-03-05", debit=150000, code_tiers="422PROF1"),
    ])
    alertes = an.depense_anormale("202603", "PIS", ref, d)
    comptes_alertes = {a["compte"] for a in alertes}
    assert "422000" in comptes_alertes


def test_part_charges_fixes_inclut_les_salaires_au_denominateur():
    # Sans correctif, total_charges = 40000 (loyer seul) et part_pct = 100%,
    # alors que le loyer ne represente qu'une fraction des depenses reelles
    # une fois le salaire pris en compte.
    ref = _ref()
    d = pd.DataFrame([
        _ligne("PIS", "622200", "2026-03-01", debit=40000),
        _ligne("PIS", "422000", "2026-03-05", debit=160000, code_tiers="422PROF1"),
    ])
    res = an.part_charges_fixes("202603", "PIS", ref, d)
    assert res["total_charges"] == 200000
    assert res["part_pct"] == pytest.approx(20.0)


# --- part_loyer_eau_electricite : exclut le gardiennage ---------------------

def test_part_loyer_eau_electricite_exclut_gardiennage():
    ref = _ref()
    d = pd.DataFrame([
        _ligne("PIS", "622200", "2026-03-01", debit=40000),   # loyer -> compte
        _ligne("PIS", "632720", "2026-03-01", debit=15000),   # gardiennage -> exclu
        _ligne("PIS", "605100", "2026-03-01", debit=5000),    # eau -> compte
        _ligne("PIS", "605200", "2026-03-01", debit=10000),   # electricite -> compte
    ])
    res = an.part_loyer_eau_electricite("202603", "PIS", ref, d)
    assert res["loyer_eau_electricite"] == 55000
    assert res["total_charges"] == 70000


# --- depense_moyenne_categorie : moyenne sur les mois ou la depense existe --

def test_depense_moyenne_categorie_ignore_les_mois_sans_depense():
    ref = _ref()
    d = pd.DataFrame([
        _ligne("PIS", "605300", "2026-01-10", debit=10000),
        _ligne("PIS", "605300", "2026-02-10", debit=20000),
        # pas de compte 605300 en mars : ne doit pas compter comme 0
    ])
    res = an.depense_moyenne_categorie("PIS", ref, d, nb_mois=3, mois_fin="202603")
    assert res["carburant"] == pytest.approx(15000.0)


# --- questions indisponibles : jamais d'exception, jamais de faux chiffre --

def test_recettes_attendues_vs_realisees_est_marque_indisponible():
    res = an.recettes_attendues_vs_realisees("PIS", "202603")
    assert res["disponible"] is False
    assert "prerequis_manquant" in res and res["prerequis_manquant"]


def test_situation_impayes_est_marque_indisponible():
    res = an.situation_impayes("PIS")
    assert res["disponible"] is False


def test_seuil_rentabilite_centre_est_marque_indisponible():
    res = an.seuil_rentabilite_centre("PIS", "202603")
    assert res["disponible"] is False


# --- caisse_sous_seuil ------------------------------------------------------

def test_caisse_sous_seuil_detecte_le_franchissement():
    ref = _ref()
    d = pd.DataFrame([_ligne("PIS", "571100", "2026-03-01", debit=50000)])
    res = an.caisse_sous_seuil("PIS", "CP", 100000, ref, d)
    assert res["solde"] == 50000
    assert res["sous_le_seuil"] is True
    assert type(res["sous_le_seuil"]) is bool  # jamais numpy.bool_ : traverse le MCP en JSON
    res2 = an.caisse_sous_seuil("PIS", "CP", 10000, ref, d)
    assert res2["sous_le_seuil"] is False


# --- personnel_multi_centres : un tiers global, un centre par ecriture -----

def test_personnel_multi_centres_detecte_une_personne_sur_deux_centres():
    ref = _ref()
    d = pd.DataFrame([
        _ligne("PIS", "422000", "2026-03-05", debit=50000, code_tiers="422PROF1"),
        _ligne("TAM", "632710", "2026-03-06", debit=30000, code_tiers="422PROF1"),
        _ligne("PIS", "422000", "2026-03-05", debit=40000, code_tiers="422PROF2"),
    ])
    res = an.personnel_multi_centres("202603", nb_mois=1, ref=ref, d=d)
    assert len(res) == 1
    assert res[0]["code_tiers"] == "422PROF1"
    assert set(res[0]["centres"]) == {"PIS", "TAM"}
    assert res[0]["remuneration_totale"] == 80000


# --- avances_personnel : exclut les avances deja remboursees ---------------

def test_avances_personnel_exclut_solde_nul_ou_rembourse():
    ref = _ref()
    d = pd.DataFrame([
        _ligne("PIS", "422300", "2026-01-10", debit=20000, code_tiers="422PROF1"),
        _ligne("PIS", "422300", "2026-02-10", credit=20000, code_tiers="422PROF1"),  # rembourse
        _ligne("PIS", "422300", "2026-01-15", debit=15000, code_tiers="422PROF2"),   # encore du
    ])
    res = an.avances_personnel("PIS", ref, d)
    assert len(res) == 1
    assert res[0]["code_tiers"] == "422PROF2"
    assert res[0]["solde_du"] == 15000


# --- ecritures_a_verifier : compte les pieces, pas les lignes --------------

def test_ecritures_a_verifier_compte_les_pieces_distinctes():
    d = pd.DataFrame([
        _ligne("PIS", "571100", "2026-03-01", debit=1000, id_piece="P1", statut="a_corriger"),
        _ligne("PIS", "411000", "2026-03-01", credit=1000, id_piece="P1", statut="a_corriger"),
        _ligne("PIS", "471000", "2026-03-02", debit=2000, id_piece="P2", statut="validee"),
    ])
    res = an.ecritures_a_verifier("202603", "PIS", d)
    assert res["pieces_a_corriger"] == 1
    assert res["pieces_en_attente_de_reclassement"] == 1
    assert res["total_pieces_a_verifier"] == 2

# ---------------------------------------------------------------------------
# Reglement d'un fournisseur (caisse et banque) : repartition par mois
# (25/09/2026)
#
#     AVANCE ETAT VACATION OCT-NOV-DEC - KABORE BERNARD
#
# Meme mecanique que l'encaissement des frais de scolarite : une ligne du
# tableau (mois, nature, montant) = une ecriture 401 au debit, dont le
# libelle cite la nature et TOUS les mois coches. La tresorerie est creditee
# du total (plus le timbre en caisse). Si la somme des lignes ne fait pas le
# montant paye, la piece n'est pas equilibree et ne s'enregistre pas.
#
# Aucune session Shiny : logic.modeles est du calcul pur. Seul le dernier
# test (relecture par l'assistant) importe assistant.semantique.
# ---------------------------------------------------------------------------

import ast
import itertools
from datetime import date
from pathlib import Path

import pandas as pd

import logic.modeles as md

JOURNAUX = pd.DataFrame({
    "journal": ["CMD", "Banque"],
    "compte_contrepartie": ["571200", "521200"],
    "type": ["tresorerie", "tresorerie"],
})
NOM = "KABORE BERNARD"
NOM_LE_PLUS_LONG = "TIENDREBEOGO BENI DE DIEU M KENNETH"
LIBELLE_LE_PLUS_LONG = "REGLEMENT FACTURE FOURNISSEUR"


def _valeurs(repartition, montant, timbre=0, libelle="ETAT VACATION"):
    return {"tiers": "401KABORE", "tiers_nom": NOM, "libelle": libelle,
            "montant": montant, "timbre": timbre, "repartition": repartition}


def _op(modele, valeurs, journal):
    return md.construire_operation(modele, valeurs, journal, JOURNAUX)


# --- libelle -----------------------------------------------------------------

def test_libelle_cite_nature_libelle_mois_et_nom():
    lib = md._libelle_reglement_fournisseur(
        "avance", "Etat vacation", ["DECEMBRE", "OCTOBRE", "NOVEMBRE"], NOM)
    assert lib == "AVANCE ETAT VACATION OCT-NOV-DEC - KABORE BERNARD"


def test_la_nature_n_est_pas_repetee():
    assert md._libelle_reglement_fournisseur("paiement", "PAIEMENT VACATION", ["DECEMBRE"], NOM) \
        == "PAIEMENT VACATION DEC - KABORE BERNARD"


def test_le_separateur_du_nom_est_retire_du_libelle_tape():
    """Sinon mois_depuis_libelle(), qui ne lit que ce qui precede " - ",
    ne verrait plus les mois."""
    lib = md._libelle_reglement_fournisseur("avance", "FACTURE ONEA - SAABA", ["MARS"], NOM)
    assert lib == "AVANCE FACTURE ONEA SAABA MAR - KABORE BERNARD"
    assert md.mois_depuis_libelle(lib) == "MARS"


def _combinaisons():
    for nature in md.LIBELLES_NATURE_FOURNISSEUR:
        for n in range(1, 7):
            for combi in itertools.combinations(md.MOIS_FR, n):
                yield nature, list(combi)


def test_limite_sage_nature_et_mois_toujours_entiers():
    """Pire cas reel : libelle le plus long propose pour 401000, nom le plus
    long du plan tiers, six mois dont JUIN et JUILLET."""
    fautifs = []
    for nature, combi in _combinaisons():
        lib = md._libelle_reglement_fournisseur(nature, LIBELLE_LE_PLUS_LONG, combi, NOM_LE_PLUS_LONG)
        tete = lib.split(" - ")[0]
        mois_txt = md._mois_en_libelle(md.mois_tries(combi))
        if (len(lib) > md.LIBELLE_MAX or not tete.startswith(md.LIBELLES_NATURE_FOURNISSEUR[nature])
                or not tete.endswith(mois_txt)):
            fautifs.append(lib)
    assert not fautifs, fautifs[:5]


def test_chaque_libelle_se_relit_sur_son_dernier_mois():
    """Sert a suggerer le mois suivant d'une avance."""
    fautifs = []
    for nature, combi in _combinaisons():
        lib = md._libelle_reglement_fournisseur(nature, "ETAT VACATION", combi, NOM)
        if md.mois_depuis_libelle(lib) != md.mois_tries(combi)[-1]:
            fautifs.append(lib)
    assert not fautifs, fautifs[:5]


# --- ecritures ---------------------------------------------------------------

def test_reglement_en_caisse_sur_plusieurs_mois():
    """90 000 F : 60 000 pour octobre et novembre, 30 000 d'avance sur
    decembre, timbre de 50 F. Deux lignes 401, le timbre, la caisse."""
    op = _op("fournisseur", _valeurs([
        {"mois": ["OCTOBRE", "NOVEMBRE"], "nature": "paiement", "montant": 60000},
        {"mois": ["DECEMBRE"], "nature": "avance", "montant": 30000}], 90000, timbre=50), "CMD")
    assert md.operation_equilibree(op)
    L = op[0]["lignes"]
    assert list(L["compte"]) == ["401000", "401000", "646200", "571200"]
    assert L.iloc[0]["libelle"] == "PAIEMENT ETAT VACATION OCT-NOV - KABORE BERNARD"
    assert L.iloc[1]["libelle"] == "AVANCE ETAT VACATION DEC - KABORE BERNARD"
    assert list(L["debit"][:3]) == [60000, 30000, 50]
    assert L.iloc[3]["credit"] == 90050
    assert L.iloc[3]["libelle"] == "ETAT VACATION"
    assert all(L.iloc[i]["code_tiers"] == "401KABORE" for i in (0, 1))
    assert L.iloc[3]["code_tiers"] == ""


def test_reglement_par_banque_meme_logique_sans_timbre():
    op = _op("fournisseur_banque", _valeurs([
        {"mois": ["OCTOBRE", "NOVEMBRE", "DECEMBRE"], "nature": "solde", "montant": 45000}],
        45000, libelle="FACTURE SONABEL"), "Banque")
    assert md.operation_equilibree(op)
    L = op[0]["lignes"]
    assert list(L["compte"]) == ["401000", "521200"]
    assert L.iloc[0]["libelle"] == "SOLDE FACTURE SONABEL OCT-NOV-DEC - KABORE BERNARD"
    assert L.iloc[1]["credit"] == 45000


def test_repartition_qui_ne_tombe_pas_juste_est_refusee():
    op = _op("fournisseur", _valeurs([
        {"mois": ["OCTOBRE"], "nature": "paiement", "montant": 40000}], 50000), "CMD")
    assert not md.operation_equilibree(op)


def test_une_ligne_sans_mois_est_ignoree():
    """Elle ne compte pas : 20 000 F sans mois laissent la piece
    desequilibree, jamais passes en silence sur un mois devine."""
    op = _op("fournisseur", _valeurs([
        {"mois": ["OCTOBRE"], "nature": "paiement", "montant": 30000},
        {"mois": [], "nature": "paiement", "montant": 20000}], 50000), "CMD")
    assert not md.operation_equilibree(op)
    assert _op("fournisseur", _valeurs([
        {"mois": [], "nature": "paiement", "montant": 5000}], 5000), "CMD") is None


def test_nature_inconnue_retombe_sur_paiement():
    """Une valeur restee d'un autre formulaire ("frais") ne produit jamais un
    libelle d'eleve sur un compte fournisseur."""
    op = _op("fournisseur", _valeurs([
        {"mois": ["MAI"], "nature": "frais", "montant": 1000}], 1000), "CMD")
    assert op[0]["lignes"].iloc[0]["libelle"].startswith("PAIEMENT ")


def test_valeurs_sans_repartition_ne_construisent_rien():
    """Pieces enregistrees avant le 25/09/2026 : a la correction, le mois
    doit etre choisi, l'ecriture n'est pas fabriquee sans lui."""
    v = _valeurs([], 25000)
    del v["repartition"]
    assert _op("fournisseur", v, "CMD") is None


def test_les_modeles_declarent_leurs_natures():
    for id_, natures in [("encaissement", md.NATURES_ENCAISSEMENT),
                         ("fournisseur", md.NATURES_FOURNISSEUR),
                         ("fournisseur_banque", md.NATURES_FOURNISSEUR)]:
        ch = next(c for c in md.modele_par_id(id_)["champs"] if c["t"] == "repartition")
        assert ch["natures"] is natures
    assert next(iter(md.NATURES_FOURNISSEUR)) == "paiement"
    assert next(iter(md.NATURES_ENCAISSEMENT)) == "frais"


# --- relecture par l'assistant ----------------------------------------------

def test_l_assistant_lit_les_plages_et_les_enumerations():
    """Les encaissements du 18 au 25/09/2026 portent "OCT A DEC" : novembre
    doit etre compte. Les nouveaux libelles citent tous les mois."""
    from assistant.semantique import mois_du_libelle
    d = date(2025, 10, 5)
    attendu = [(2025, 10), (2025, 11), (2025, 12)]
    assert mois_du_libelle("FRAIS CA OCT A DEC - OUEDRAOGO", d) == attendu
    assert mois_du_libelle("AVANCE ETAT VACATION OCT-NOV-DEC - KABORE", d) == attendu
    assert len(mois_du_libelle("AVANCE CA SEP A FEV - X", date(2025, 9, 5))) == 6
    # Un "A" qui n'est pas entre deux mois n'est pas une plage.
    assert mois_du_libelle("PAIEMENT A KABORE", d) == []
    assert mois_du_libelle("PAIEMENT DEC A KABORE", date(2026, 1, 5)) == [(2025, 12)]


# --- interface (analyse du source, comme test_authorisation.py) -------------

APP_PY = Path(__file__).resolve().parent.parent / "app.py"


def _fonction(nom):
    arbre = ast.parse(APP_PY.read_text(encoding="utf-8"))
    for n in ast.walk(arbre):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return n
    raise AssertionError(f"{nom} introuvable dans app.py")


def test_tout_selectionner_est_reserve_a_la_validation():
    fn = _fonction("_tout_selectionner")
    appels = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "est_validateur" in appels


def test_tout_selectionner_ne_touche_pas_la_base():
    """Il ne fait que choisir des lignes : la validation reste _valider()."""
    for nom in ("_tout_selectionner", "_tout_deselectionner"):
        fn = _fonction(nom)
        for n in ast.walk(fn):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
                assert n.value.id != "dl", f"{nom} appelle logic.donnees ({n.attr})"


def test_le_tableau_de_repartition_n_est_plus_reserve_a_l_encaissement():
    source = APP_PY.read_text(encoding="utf-8")
    assert '!= "encaissement"' not in source

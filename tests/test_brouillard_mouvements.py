# ---------------------------------------------------------------------------
# Brouillard : une ligne par mouvement de caisse (21/11/2026)
#
# Demande de la comptable : voir dans le Brouillard quels mois un eleve a
# payes. Un paiement de 100 000 F reparti en AVANCE NOV / SOLDE DEC /
# FRAIS JAN s'affiche sur trois lignes, chacune avec son libelle et son
# montant. Corriger et Supprimer agissent toujours sur la piece entiere.
# ---------------------------------------------------------------------------

import ast
from pathlib import Path

import pandas as pd

import logic.donnees as dl
import logic.modeles as md

APP_PY = Path(__file__).resolve().parent.parent / "app.py"
JOURNAUX = pd.DataFrame({
    "journal": ["CP", "CMD", "VTE"],
    "compte_contrepartie": ["571100", "571200", None],
    "type": ["tresorerie", "tresorerie", "operations"],
})
TRESORERIE = {"571100", "571200"}
NOM = "DA FAWZIZ"


def _encaissement_trois_mois():
    v = {"tiers": "411000FAWZIA", "tiers_nom": NOM, "montant": 100000, "repartition": [
        {"nature": "avance", "mois": ["NOVEMBRE"], "montant": 30000},
        {"nature": "solde", "mois": ["DECEMBRE"], "montant": 45000},
        {"nature": "frais", "mois": ["JANVIER"], "montant": 25000}]}
    op = md.construire_operation("encaissement", v, "CP", JOURNAUX)
    assert md.operation_equilibree(op)
    return op[0]["lignes"]


def test_un_paiement_sur_trois_mois_donne_trois_lignes_au_brouillard():
    lignes = dl.lignes_brouillard_piece(_encaissement_trois_mois(), TRESORERIE)
    assert lignes == [(f"AVANCE CA NOV - {NOM}", 30000.0),
                      (f"SOLDE CA DEC - {NOM}", 45000.0),
                      (f"FRAIS CA JAN - {NOM}", 25000.0)]


def test_une_depense_reste_sur_une_ligne():
    v = {"compte": "605100", "libelle": "CARBURANT", "montant": 5000}
    op = md.construire_operation("depense", v, "CMD", JOURNAUX)
    lignes = dl.lignes_brouillard_piece(op[0]["lignes"], TRESORERIE)
    assert lignes == [("CARBURANT", 5000.0)]


def test_une_piece_sans_caisse_garde_une_ligne_et_son_total():
    p = pd.DataFrame([
        {"compte": "411000", "libelle": "FACT N*057/NOV/26 KABORE", "debit": 30000.0, "credit": 0.0},
        {"compte": "706110", "libelle": "FACT N*057/NOV/26 KABORE", "debit": 0.0, "credit": 30000.0}])
    assert dl.lignes_brouillard_piece(p, TRESORERIE) == [("FACT N*057/NOV/26 KABORE", 30000.0)]


def _corps(nom):
    source = APP_PY.read_text(encoding="utf-8")
    for noeud in ast.walk(ast.parse(source)):
        if isinstance(noeud, ast.FunctionDef) and noeud.name == nom:
            return ast.get_source_segment(source, noeud)
    raise AssertionError(f"{nom}() introuvable dans app.py")


def test_corriger_et_supprimer_agissent_sur_la_piece_entiere():
    """Plusieurs lignes du Brouillard peuvent appartenir a la meme piece :
    l'index de la ligne doit etre ramene a l'id_piece avant d'agir."""
    assert "_vue_par_piece(b_table.data_view(selected=True))" in _corps("_supprimer")
    assert "_vue_par_piece(b_table.data_view(selected=True))" in _corps("_corriger")
    assert "par_mouvement=True" in _corps("b_table")


def test_les_lignes_d_une_piece_gardent_l_ordre_de_saisie():
    """La base rend les lignes d'une piece sans ordre garanti : le Brouillard
    les remet dans l'ordre de saisie (id_ligne)."""
    p = _encaissement_trois_mois().copy()
    p["id_ligne"] = range(1, len(p) + 1)
    melange = p.iloc[[2, 0, 4, 1, 5, 3]]
    assert [lib for lib, _ in dl.lignes_brouillard_piece(melange, TRESORERIE)] == [
        f"AVANCE CA NOV - {NOM}", f"SOLDE CA DEC - {NOM}", f"FRAIS CA JAN - {NOM}"]

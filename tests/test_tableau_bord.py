# ---------------------------------------------------------------------------
# Tableau de bord (02/10/2026) : calculs et acces.
#
# Un jeu de pieces dont le resultat, les sorties hors exploitation et les
# soldes sont connus a l'avance : encaissement, camp, vacation, transfert
# entre caisses (exclu), contribution au SIAO (versee et recue), compte
# d'attente 471, emprunt, impot, compte non classe, piece non validee,
# versement en banque.
#
# Base PostgreSQL reelle (DATABASE_URL), comme test_numerotation_date_centre.
# Pieces datees de 2099, effacees a la fin. Les soldes sont compares en
# ecart (avant / apres le jeu), pour rester justes sur une base non vide.
# ---------------------------------------------------------------------------

import ast
import math
from datetime import date
from pathlib import Path

import pytest

import logic.donnees as dl
import logic.tableau_bord as tb

RACINE = Path(__file__).resolve().parent.parent
MIGRATION = RACINE / "sql" / "migrations" / "2026-10-02_tableau_bord.sql"
PREFIXE = "TBTEST-"
DEBUT, FIN = date(2099, 3, 1), date(2099, 4, 30)


def _base_disponible():
    try:
        with dl._connexion() as c, c.cursor() as cur:
            cur.execute("SELECT 1 FROM centres WHERE code_centre IN ('TAM', 'SAA') HAVING count(*) = 2")
            return cur.fetchone() is not None
    except Exception:
        return False


base = pytest.mark.skipif(not _base_disponible(), reason="base PostgreSQL indisponible")

# (piece, centre, journal, date, statut, modele, [(compte, libelle, debit, credit)])
PIECES = [
    ("p1", "TAM", "CP", "2099-03-05", "validee", "", [
        ("571100", "FRAIS CA ELEVE A", 100000, 0), ("411000", "FRAIS CA ELEVE A", 0, 100000)]),
    ("p2", "TAM", "CP", "2099-03-10", "saisie", "", [
        ("571100", "FRAIS CAMP ELEVE B", 30000, 0), ("411000", "FRAIS CAMP ELEVE B", 0, 30000)]),
    ("p3", "TAM", "CMD", "2099-03-12", "validee", "", [
        ("401000", "PAIEMENT VACATION PROF", 40000, 0), ("571200", "PAIEMENT VACATION PROF", 0, 40000)]),
    ("p4a", "TAM", "CP", "2099-03-15", "validee", "", [
        ("585000", "APPROV CMD", 20000, 0), ("571100", "APPROV CMD", 0, 20000)]),
    ("p4b", "TAM", "CMD", "2099-03-15", "validee", "", [
        ("571200", "APPROV CMD", 20000, 0), ("585000", "APPROV CMD", 0, 20000)]),
    ("p5", "TAM", "CP", "2099-04-02", "validee", "transfert_interne", [
        ("585000", "TRANSFERT TAM>SIA", 15000, 0), ("571100", "TRANSFERT TAM>SIA", 0, 15000)]),
    ("p6", "TAM", "CP", "2099-04-03", "validee", "", [
        ("571100", "ENCAISSEMENT A IDENTIFIER", 12000, 0), ("471000", "ENCAISSEMENT A IDENTIFIER", 0, 12000)]),
    ("p7", "TAM", "CP", "2099-04-05", "validee", "", [
        ("160100", "REMBOURSEMENT EMPRUNT", 25000, 0), ("571100", "REMBOURSEMENT EMPRUNT", 0, 25000)]),
    ("p8", "TAM", "CP", "2099-04-06", "validee", "", [
        ("447100", "PAIEMENT IMPOT", 8000, 0), ("571100", "PAIEMENT IMPOT", 0, 8000)]),
    ("p9", "TAM", "CP", "2099-04-07", "validee", "", [
        ("462100", "DIVERS", 5000, 0), ("571100", "DIVERS", 0, 5000)]),
    ("p10", "SAA", "CP", "2099-04-08", "validee", "transfert_interne", [
        ("571100", "TRANSFERT TAM>SIA", 15000, 0), ("585000", "TRANSFERT TAM>SIA", 0, 15000)]),
    ("p11", "TAM", "CP", "2099-04-09", "validee", "versement_banque", [
        ("521100", "VERSEMENT BANQUE", 10000, 0), ("571100", "VERSEMENT BANQUE", 0, 10000)]),
]


def _soldes(fin):
    s = dl._lire_df("SELECT * FROM soldes_tableau_bord(%s, %s)", (fin, ["TAM", "SAA"]))
    return {(r.centre if isinstance(r.centre, str) else None, r.journal): float(r.solde)
            for r in s.itertuples()}


@pytest.fixture(scope="module")
def donnees():
    sql = MIGRATION.read_text(encoding="utf-8")
    with dl._connexion() as c, c.cursor() as cur:
        cur.execute(sql)
        cur.execute("DELETE FROM ecritures WHERE id_ligne LIKE %s", (PREFIXE + "%",))
    avant = _soldes(date(2099, 2, 28))
    with dl._connexion() as c, c.cursor() as cur:
        for piece, centre, journal, jour, statut, modele, lignes in PIECES:
            for i, (compte, libelle, debit, credit) in enumerate(lignes):
                cur.execute("""
                    INSERT INTO ecritures (id_ligne, id_piece, journal, centre, date_piece, compte,
                                           libelle, debit, credit, statut, modele)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (f"{PREFIXE}{piece}-{i}", PREFIXE + piece, journal, centre, jour, compte,
                             libelle, debit, credit, statut, modele))
    yield {"avant": avant, "r": tb.calculer(DEBUT, FIN, ["TAM", "SAA"])}
    with dl._connexion() as c, c.cursor() as cur:
        cur.execute("DELETE FROM ecritures WHERE id_ligne LIKE %s", (PREFIXE + "%",))


def _ligne(r, libelle):
    t = r["tableau"]
    sous = t[t["libelle"] == libelle]
    return sous.iloc[0] if len(sous) else None


@base
def test_trois_chiffres_du_centre(donnees):
    tam = donnees["r"]["par_centre"]["TAM"]
    # encaissements 100 000 + 30 000 (camp) + 12 000 (471) ; charges 40 000
    # (vacation) + 15 000 (contribution) + 5 000 (non classe)
    assert tam["encaissements"] == 142000
    assert tam["charges"] == 60000
    assert tam["resultat"] == 82000
    assert tam["hors_exploitation"] == 33000          # emprunt 25 000 + impot 8 000
    assert tam["non_validees"] == 1
    assert tam["attente"] == 12000


@base
def test_contribution_versee_et_recue(donnees):
    r = donnees["r"]
    assert r["par_centre"]["SAA"]["resultat"] == 15000
    assert _ligne(r, "Contribution au SIAO")["Total"] == 15000
    assert _ligne(r, "Contributions reçues des centres")["Total"] == 15000
    assert r["ensemble"]["resultat"] == 82000 + 15000


@base
def test_transferts_entre_caisses_exclus(donnees):
    r = donnees["r"]
    assert not r["tableau"]["libelle"].str.contains("Transfert").any()
    assert r["tableau"]["Total"].sum() > 0  # le tableau n'est pas vide


@base
def test_camp_separe_et_mois_vide(donnees):
    r = donnees["r"]
    camp = _ligne(r, "Camp de vacances")
    assert camp["2099-03"] == 30000
    assert math.isnan(camp["2099-04"])                  # affiche « - »
    assert _ligne(r, "Cours d'appui")["Total"] == 100000


@base
def test_compte_non_classe_signale(donnees):
    r = donnees["r"]
    assert r["non_classes"] == 1
    assert _ligne(r, "Sorties non classées")["Total"] == 5000


@base
def test_tableau_egal_aux_bandeaux(donnees):
    r = donnees["r"]
    tot = r["totaux"]
    assert tot["encaissements"]["Total"] == r["ensemble"]["encaissements"]
    assert tot["charges"]["Total"] == r["ensemble"]["charges"]
    assert tot["resultat"]["Total"] == r["ensemble"]["resultat"]
    assert tot["hors_exploitation"]["Total"] == r["ensemble"]["hors_exploitation"]
    somme = sum(c["resultat"] for c in r["par_centre"].values())
    assert somme == r["ensemble"]["resultat"]
    # chaque mois : total = somme des lignes
    for m in r["mois"]:
        assert tot["resultat"][m] == tot["encaissements"][m] - (tot["charges"][m] or 0)


@base
def test_un_seul_centre_ne_voit_que_lui(donnees):
    r = tb.calculer(DEBUT, FIN, ["SAA"])
    assert list(r["par_centre"]) == ["SAA"]
    assert r["ensemble"]["resultat"] == 15000
    assert _ligne(r, "Contribution au SIAO")["Total"] != 15000


@base
def test_soldes_caisses_et_banque(donnees):
    avant, apres = donnees["avant"], _soldes(FIN)
    ecart = {k: apres[k] - avant.get(k, 0) for k in apres}
    assert ecart[("TAM", "CP")] == 59000
    assert ecart[("TAM", "CMD")] == -20000
    assert ecart[("SAA", "CP")] == 15000
    banque = [k for k in ecart if k[0] is None]
    assert sum(ecart[k] for k in banque) == 10000


@base
def test_periode_sans_mouvement():
    r = tb.calculer(date(2098, 1, 1), date(2098, 1, 31), ["TAM"])
    assert r["vide"]
    assert r["mois"] == ["2098-01"]


def test_mois_de_la_periode():
    assert tb.mois_de(date(2026, 11, 15), date(2027, 2, 3)) == ["2026-11", "2026-12", "2027-01", "2027-02"]


# --- acces : reserve au comptable (analyse syntaxique, sans session Shiny) ---

def test_onglet_reserve_au_comptable():
    source = (RACINE / "app.py").read_text(encoding="utf-8")
    arbre = ast.parse(source)
    conditions = [ast.unparse(n.test) for n in ast.walk(arbre)
                  if isinstance(n, ast.If) and "tableau_bord.onglet" in ast.unparse(n)
                  and not any("tableau_bord.onglet" in ast.unparse(b) for b in n.orelse)]
    assert conditions and all(c == "est_comptable()" for c in conditions[-1:])
    assert source.count("tableau_bord.onglet(") == 1
    assert 'tableau_bord.serveur("tb", autorise=est_comptable' in source


def test_le_serveur_verifie_le_droit():
    source = (RACINE / "tableau_bord.py").read_text(encoding="utf-8")
    assert "req(autorise())" in source

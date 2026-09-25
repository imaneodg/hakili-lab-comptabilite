# ---------------------------------------------------------------------------
# Numerotation definitive par date puis par centre (25/09/2026)
#
# Ce que ces tests protegent :
#   1. un lot valide recoit ses numeros dans l'ordre date -> centre (SIAO,
#      Tampouy, Saaba, Pissy, Nagrin) -> heure de saisie, quel que soit
#      l'ordre dans lequel les centres ont saisi ;
#   2. un centre absent du lot est saute, sans trou ;
#   3. chaque journal a sa propre suite ;
#   4. une piece oubliee, validee plus tard, prend le numero suivant ;
#   5. une piece renvoyee puis corrigee et revalidee retrouve son numero ;
#   6. la base refuse deux pieces avec le meme numero dans un journal.
#
# Base PostgreSQL reelle (DATABASE_URL). Les pieces sont datees de 2099 pour
# ne jamais croiser de vraies donnees, et tout est efface a la fin.
# ---------------------------------------------------------------------------

import pandas as pd
import psycopg2
import pytest

import logic.donnees as dl

MOIS = "209901"
ANNEE = "2099"


def _base_disponible():
    try:
        with dl._connexion() as c, c.cursor() as cur:
            cur.execute("SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'ecritures' AND column_name = 'num_reserve'")
            return cur.fetchone() is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _base_disponible(),
                                reason="base PostgreSQL migree indisponible")


def _nettoyer():
    with dl._connexion() as c, c.cursor() as cur:
        cur.execute("DELETE FROM ecritures WHERE date_piece >= '2099-01-01'")
        cur.execute("DELETE FROM compteurs WHERE cle LIKE %s", (f"%:{MOIS}",))
        cur.execute("DELETE FROM suppressions_ecritures WHERE contenu->>'date_piece' >= '2099-01-01'")


@pytest.fixture(autouse=True)
def propre():
    _nettoyer()
    yield
    _nettoyer()


def _op(journal="CP", montant=1000):
    compte = {"CP": "571100", "CMD": "571200"}[journal]
    lignes = pd.DataFrame([
        {"compte": compte, "code_tiers": "", "libelle": "TEST NUMEROTATION", "debit": montant, "credit": 0.0},
        {"compte": "707810", "code_tiers": "", "libelle": "TEST NUMEROTATION", "debit": 0.0, "credit": montant},
    ])
    return [{"journal": journal, "lignes": lignes}]


def _saisir(centre, jour, journal="CP"):
    dl.enregistrer_operation(_op(journal), centre, f"{ANNEE}-01-{jour:02d}", "libre", "test")
    with dl._connexion() as c, c.cursor() as cur:
        cur.execute("SELECT id_piece FROM ecritures WHERE date_piece >= '2099-01-01' "
                    "ORDER BY saisi_le DESC, id_piece DESC LIMIT 1")
        return cur.fetchone()[0]


def _numeros():
    with dl._connexion() as c, c.cursor() as cur:
        cur.execute("SELECT DISTINCT id_piece, journal, num_definitif FROM ecritures "
                    "WHERE date_piece >= '2099-01-01'")
        return {i: (j, n) for i, j, n in cur.fetchall()}


def _rang(num):
    return int(num[-3:])


def test_ordre_date_puis_centre():
    # Saisie volontairement dans le desordre : Nagrin et Saaba d'abord, le 2
    # avant le 1er.
    p = {}
    p["nag_1"] = _saisir("NAG", 1)
    p["saa_2"] = _saisir("SAA", 2)
    p["sia_2"] = _saisir("SIA", 2)
    p["tam_1"] = _saisir("TAM", 1)
    p["sia_1a"] = _saisir("SIA", 1)
    p["sia_1b"] = _saisir("SIA", 1)
    res = dl.valider_pieces(list(p.values()), "comptable")
    assert len(res["validees"]) == 6
    n = _numeros()
    attendu = ["sia_1a", "sia_1b", "tam_1", "nag_1", "sia_2", "saa_2"]
    rangs = [_rang(n[p[k]][1]) for k in attendu]
    assert rangs == sorted(rangs), f"ordre recu : {rangs}"
    assert rangs == list(range(rangs[0], rangs[0] + 6)), "la suite doit etre continue (centre absent saute)"


def test_une_suite_par_journal():
    a = _saisir("SIA", 1, "CP")
    b = _saisir("SIA", 1, "CMD")
    c = _saisir("TAM", 1, "CP")
    dl.valider_pieces([a, b, c], "comptable")
    n = _numeros()
    assert _rang(n[c][1]) == _rang(n[a][1]) + 1      # CP : suite continue malgre la piece CMD
    assert n[a][1].startswith("CP9901") and n[b][1].startswith("CMD9901")


def test_oubli_prend_le_numero_suivant():
    a = _saisir("SIA", 3)
    dl.valider_pieces([a], "comptable")
    oubli = _saisir("TAM", 1)
    dl.valider_pieces([oubli], "comptable")
    n = _numeros()
    assert _rang(n[oubli][1]) == _rang(n[a][1]) + 1


def test_piece_renvoyee_retrouve_son_numero():
    a = _saisir("SIA", 1)
    b = _saisir("TAM", 1)
    dl.valider_pieces([a, b], "comptable")
    num_a = _numeros()[a][1]
    dl.rejeter_pieces([a], "montant faux", "comptable")
    assert _numeros()[a][1] == ""
    # Correction (nouvelle piece, meme journal, meme mois), puis revalidation.
    nums = dl.remplacer_piece(a, _op("CP", 2000), "SIA", f"{ANNEE}-01-01", "libre", "caissiere")
    assert nums
    nouvelle = [i for i in _numeros() if i not in (a, b)]
    assert len(nouvelle) == 1
    dl.valider_pieces(nouvelle, "comptable")
    assert _numeros()[nouvelle[0]][1] == num_a
    # Le compteur n'a pas avance : la piece suivante continue la suite.
    c = _saisir("NAG", 2)
    dl.valider_pieces([c], "comptable")
    assert _rang(_numeros()[c][1]) == _rang(_numeros()[b][1]) + 1


def test_renvoi_puis_revalidation_directe():
    a = _saisir("SIA", 1)
    dl.valider_pieces([a], "comptable")
    num_a = _numeros()[a][1]
    dl.rejeter_pieces([a], "a revoir", "comptable")
    with dl._connexion() as c, c.cursor() as cur:
        cur.execute("UPDATE ecritures SET statut = 'saisie' WHERE id_piece = %s", (a,))
    dl.valider_pieces([a], "comptable")
    assert _numeros()[a][1] == num_a


def test_numero_en_double_refuse_par_la_base():
    a = _saisir("SIA", 1)
    b = _saisir("TAM", 1)
    dl.valider_pieces([a, b], "comptable")
    num_a = _numeros()[a][1]
    with pytest.raises(psycopg2.Error):
        with dl._connexion() as c, c.cursor() as cur:
            cur.execute("UPDATE ecritures SET num_definitif = %s WHERE id_piece = %s", (num_a, b))

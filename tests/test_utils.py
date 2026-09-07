# ---------------------------------------------------------------------------
# Tests des fonctions utilitaires pures de logic/donnees.py (aucune n'ouvre
# de connexion elle-meme, mais l'import du module en ouvre une : voir la
# remarque dans test_auth.py).
# ---------------------------------------------------------------------------

from datetime import date

import logic.donnees as dl


def test_fcfa_formate_avec_espaces_milliers():
    assert dl.fcfa(1234567) == "1 234 567"


def test_fcfa_arrondit_et_tolere_une_valeur_vide():
    assert dl.fcfa(999.6) == "1 000"
    assert dl.fcfa(None) == "0"
    assert dl.fcfa("") == "0"


def test_mois_de_formate_annee_mois():
    assert dl.mois_de(date(2026, 3, 7)) == "202603"
    assert dl.mois_de("2026-11-01") == "202611"


def test_slug_ne_garde_que_des_lettres_majuscules():
    assert dl._slug("Aïcha K.") == "AICHAK"
    assert dl._slug("") == "TIERS"
    assert dl._slug("a" * 30, longueur_max=5) == "AAAAA"

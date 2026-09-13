# ---------------------------------------------------------------------------
# Tests des fonctions utilitaires pures de logic/donnees.py (aucune n'ouvre
# de connexion elle-meme, mais l'import du module en ouvre une : voir la
# remarque dans test_auth.py).
# ---------------------------------------------------------------------------

from datetime import date

import pandas as pd

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


# --- ecrire_fichier_sage : cp1252 + errors="replace" (corrige le 10/09/2026) -

def test_ecrire_fichier_sage_couvre_les_caracteres_absents_de_latin1(tmp_path):
    # "oe" (manoeuvre), guillemets typographiques et tiret cadratin : absents
    # de latin1 (l'ancien encodage), couverts par cp1252.
    x = pd.DataFrame([{"Libelle": "MANŒUVRE — « ENTRETIEN »"}])
    chemin = tmp_path / "sage.txt"
    dl.ecrire_fichier_sage(x, str(chemin))
    assert "MANŒUVRE" in chemin.read_bytes().decode("cp1252")


def test_ecrire_fichier_sage_ne_plante_jamais_meme_hors_cp1252(tmp_path):
    # errors="replace" : un caractere que meme cp1252 ne couvre pas (par
    # exemple un emoji colle par erreur dans un libelle) ne doit plus faire
    # planter l'ecriture de tout le fichier - avant, cette meme situation
    # provoquait une UnicodeEncodeError qui bloquait l'export du lot entier.
    x = pd.DataFrame([{"Libelle": "FRAIS \U0001F600"}])
    chemin = tmp_path / "sage_emoji.txt"
    dl.ecrire_fichier_sage(x, str(chemin))  # ne doit lever aucune exception
    assert chemin.exists()

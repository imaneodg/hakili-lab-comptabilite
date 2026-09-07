# ---------------------------------------------------------------------------
# Tests du durcissement de l'authentification (voir logic/donnees.py).
#
# Necessite un Postgres accessible (le meme que pour lancer l'app : la
# ThreadedConnectionPool de logic.donnees se connecte des l'import du
# module). Lancer depuis la racine du projet, .env rempli :
#   .venv\Scripts\pytest tests/ -v          (Windows)
#   .venv/bin/pytest tests/ -v              (Linux/macOS)
# ---------------------------------------------------------------------------

import logic.donnees as dl


def test_hacher_code_produit_un_hash_reconnu():
    hache = dl._hacher_code("1234")
    assert dl._code_est_hache(hache)
    assert hache != "1234"


def test_verifier_code_acces_avec_hash_correct():
    hache = dl._hacher_code("motdepasse42")
    assert dl.verifier_code_acces("motdepasse42", hache) is True


def test_verifier_code_acces_avec_hash_incorrect():
    hache = dl._hacher_code("motdepasse42")
    assert dl.verifier_code_acces("autrechose", hache) is False


def test_verifier_code_acces_compatible_ancien_code_en_clair():
    # Comptes crees avant la migration bcrypt du 05/09/2026 : le code est
    # encore stocke tel quel en base, verifier_code_acces doit continuer a
    # l'accepter (tenter_connexion() le migre ensuite vers un hash).
    assert dl.verifier_code_acces("2468", "2468") is True
    assert dl.verifier_code_acces("0000", "2468") is False


def test_code_est_hache_ne_confond_pas_un_code_en_clair_avec_un_hash():
    assert dl._code_est_hache("2468") is False
    assert dl._code_est_hache("") is False
    assert dl._code_est_hache(dl._hacher_code("x")) is True

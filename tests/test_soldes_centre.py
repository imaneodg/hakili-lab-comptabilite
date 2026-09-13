# ---------------------------------------------------------------------------
# Tests des soldes de caisse par centre (logic/donnees.py), ajoutes le
# 11/09/2026 suite a la confirmation du comptable que chacun des cinq
# centres a sa propre caisse physique (CP, CMD) : un solde d'ouverture
# unique par journal (partage entre les cinq centres) donnait un solde faux
# a chaque centre et pouvait masquer une caisse reellement a sec dans un
# centre derriere l'excedent d'un autre (controler_soldes sommait tous les
# centres avant de verifier le signe). Voir aussi le changement de banque
# (BDU-BF -> Banque/CBI), ou le compte reste global et n'est jamais ventile
# par centre.
#
# Meme approche que test_analyse.py : toutes les fonctions testees ici
# acceptent ref/d en parametres explicites, aucun test n'ouvre de connexion
# Postgres. Lancer avec les autres :
#   pytest tests/ -v
# ---------------------------------------------------------------------------

import pandas as pd

import logic.analyse as an
import logic.donnees as dl

CENTRES = ["PIS", "TAM"]


def _ref(soldes_centre=None):
    comptes = pd.DataFrame([
        {"compte": "571100", "intitule": "Caisse principale", "nature": "tresorerie",
         "tiers_obligatoire": "non"},
        {"compte": "521200", "intitule": "Banques (CBI)", "nature": "tresorerie",
         "tiers_obligatoire": "non"},
        {"compte": "521100", "intitule": "Banques (BDU-BF)", "nature": "tresorerie",
         "tiers_obligatoire": "non"},
    ])
    journaux = pd.DataFrame([
        {"journal": "CP", "compte_contrepartie": "571100", "type": "tresorerie",
         "prefixe_piece": "CP", "solde_ouverture": 0.0, "caisse_physique": "oui", "actif": "oui"},
        {"journal": "Banque", "compte_contrepartie": "521200", "type": "tresorerie",
         "prefixe_piece": "CBI", "solde_ouverture": 100000.0, "caisse_physique": "non", "actif": "oui"},
        # Ancien journal de banque, retire mais toujours en base avec son
        # historique - ne doit plus jamais etre controle ni afficher.
        {"journal": "BDU-BF", "compte_contrepartie": "521100", "type": "tresorerie",
         "prefixe_piece": "BDU", "solde_ouverture": -5000.0, "caisse_physique": "non", "actif": "non"},
    ])
    noms = {"PIS": "Pissy", "TAM": "Tampouy"}
    centres = pd.DataFrame([{"code_centre": c, "intitule": noms[c]} for c in CENTRES])
    tiers = pd.DataFrame(columns=["code_tiers", "intitule"])
    if soldes_centre is None:
        soldes_centre = pd.DataFrame(columns=["centre", "journal", "solde_ouverture"])
    return {"comptes": comptes, "journaux": journaux, "centres": centres,
            "tiers": tiers, "soldes_centre": soldes_centre}


def _ligne(centre, compte, debit=0, credit=0, journal="CP", code_tiers="", modele="",
           id_piece="P1", statut="validee"):
    return {"centre": centre, "compte": compte, "journal": journal, "debit": debit, "credit": credit,
            "date_piece": "2026-03-01", "code_tiers": code_tiers, "modele": modele,
            "id_piece": id_piece, "statut": statut, "num_definitif": "", "num_provisoire": "P1",
            "libelle": "TEST"}


# --- solde_caisse : isolation entre centres pour une caisse physique -------

def test_solde_caisse_isole_chaque_centre_pour_une_caisse_physique():
    sc = pd.DataFrame([
        {"centre": "PIS", "journal": "CP", "solde_ouverture": 20000.0},
        {"centre": "TAM", "journal": "CP", "solde_ouverture": 5000.0},
    ])
    ref = _ref(sc)
    d = pd.DataFrame([
        _ligne("PIS", "571100", debit=10000),
        _ligne("TAM", "571100", credit=3000),
    ])
    # Chaque centre ne voit que son propre solde d'ouverture + ses propres
    # mouvements, jamais ceux de l'autre centre.
    assert dl.solde_caisse("CP", ref, d, centre="PIS") == 30000.0
    assert dl.solde_caisse("CP", ref, d, centre="TAM") == 2000.0
    # Sans centre : le total consolide des deux (comptable).
    assert dl.solde_caisse("CP", ref, d, centre=None) == 32000.0


def test_solde_caisse_defaut_zero_pour_un_centre_sans_solde_seede():
    ref = _ref(pd.DataFrame([{"centre": "PIS", "journal": "CP", "solde_ouverture": 15000.0}]))
    d = pd.DataFrame([_ligne("TAM", "571100", debit=1000)])
    # TAM n'a pas de ligne dans soldes_centre : solde d'ouverture 0, jamais
    # une exception ni le solde d'un autre centre par erreur.
    assert dl.solde_caisse("CP", ref, d, centre="TAM") == 1000.0


# --- solde_caisse : le compte partage (banque) ignore le centre -----------

def test_solde_caisse_banque_ignore_le_centre_fourni():
    ref = _ref()
    d = pd.DataFrame([
        _ligne("PIS", "521200", debit=50000, journal="Banque"),
        _ligne("TAM", "521200", debit=20000, journal="Banque"),
    ])
    attendu = 100000.0 + 50000.0 + 20000.0  # solde_ouverture global + tous les mouvements
    # Le meme total global, quel que soit le centre demande - un centre n'a
    # jamais "sa part" d'un compte bancaire partage.
    assert dl.solde_caisse("Banque", ref, d, centre="PIS") == attendu
    assert dl.solde_caisse("Banque", ref, d, centre="TAM") == attendu
    assert dl.solde_caisse("Banque", ref, d, centre=None) == attendu


# --- controler_soldes : ne masque plus une caisse a sec dans un centre ----

def test_controler_soldes_detecte_un_centre_a_sec_malgre_un_excedent_ailleurs():
    # Avant le correctif du 11/09/2026, un seul solde_ouverture global
    # aurait ete compare a la somme de TOUS les centres : PIS negatif (-8000)
    # + TAM tres positif (+50000) aurait donne un total positif, masquant le
    # probleme reel a Pissy. Chaque centre doit desormais etre verifie
    # independamment.
    sc = pd.DataFrame([
        {"centre": "PIS", "journal": "CP", "solde_ouverture": 2000.0},
        {"centre": "TAM", "journal": "CP", "solde_ouverture": 0.0},
    ])
    ref = _ref(sc)
    d = pd.DataFrame([
        _ligne("PIS", "571100", credit=10000),   # PIS : 2000 - 10000 = -8000
        _ligne("TAM", "571100", debit=50000),    # TAM : 0 + 50000 = +50000
    ])
    res = dl.controler_soldes(ref, d)
    negatifs = res[res["anomalie"].str.contains("negatif")]
    assert len(negatifs) == 1
    assert "Pissy" in negatifs["anomalie"].iloc[0]
    assert "Tampouy" not in negatifs["anomalie"].iloc[0]


def test_controler_soldes_limite_a_un_centre_quand_demande():
    sc = pd.DataFrame([{"centre": "PIS", "journal": "CP", "solde_ouverture": 0.0}])
    ref = _ref(sc)
    d = pd.DataFrame([_ligne("PIS", "571100", credit=1000)])
    # Vue d'un utilisateur non-comptable de PIS : ne verifie que son centre.
    res_pis = dl.controler_soldes(ref, d, centre="PIS")
    assert len(res_pis) == 1
    res_tam = dl.controler_soldes(ref, d, centre="TAM")
    assert len(res_tam) == 0


def test_controler_soldes_ignore_un_journal_retire():
    # BDU-BF (actif='non') a un solde_ouverture negatif dans _ref(), mais un
    # journal retire ne doit plus jamais declencher d'alerte : son solde est
    # fige, plus personne ne doit agir dessus.
    ref = _ref()
    d = pd.DataFrame(columns=["centre", "compte", "journal", "debit", "credit"])
    res = dl.controler_soldes(ref, d)
    assert not res["piece"].eq("BDU-BF").any()


# --- inclure_banque : jamais d'alerte sur la banque pour un non-comptable -

def test_controler_soldes_masque_la_banque_si_inclure_banque_faux():
    ref = _ref()
    d = pd.DataFrame([_ligne("PIS", "521200", credit=500000, journal="Banque")])  # banque tres negative
    avec_banque = dl.controler_soldes(ref, d, inclure_banque=True)
    sans_banque = dl.controler_soldes(ref, d, inclure_banque=False)
    assert avec_banque["piece"].eq("Banque").any()
    assert not sans_banque["piece"].eq("Banque").any()


def test_anomalies_transmet_inclure_banque_et_le_perimetre_centre():
    sc = pd.DataFrame([{"centre": "PIS", "journal": "CP", "solde_ouverture": 0.0}])
    ref = _ref(sc)
    d = pd.DataFrame([
        _ligne("PIS", "571100", credit=1000, id_piece="P1"),                       # caisse PIS a sec
        _ligne("PIS", "521200", credit=500000, journal="Banque", id_piece="P2"),   # banque tres negative
    ])
    # Vue d'une caissiere de PIS (non-comptable) : voit sa propre caisse a
    # sec, ne voit jamais l'alerte sur la banque.
    res = dl.anomalies(d, ref, centre="PIS", inclure_banque=False)
    assert res["piece"].eq("CP").any()
    assert not res["piece"].eq("Banque").any()
    # Vue du comptable : voit les deux.
    res_comptable = dl.anomalies(d, ref, centre=None, inclure_banque=True)
    assert res_comptable["piece"].eq("CP").any()
    assert res_comptable["piece"].eq("Banque").any()


# --- tresorerie_disponible (logic/analyse.py) : pas de double comptage -----

def test_tresorerie_disponible_ne_duplique_pas_la_banque_sur_tous_les_centres():
    # Avant le correctif du 11/09/2026, sommer le solde de la banque une
    # fois par centre agrege l'aurait comptee N fois (N = nombre de
    # centres) au lieu d'une seule : un compte partage n'a qu'un solde.
    sc = pd.DataFrame([
        {"centre": "PIS", "journal": "CP", "solde_ouverture": 10000.0},
        {"centre": "TAM", "journal": "CP", "solde_ouverture": 5000.0},
    ])
    ref = _ref(sc)
    d = pd.DataFrame([
        _ligne("PIS", "521200", debit=20000, journal="Banque", id_piece="P1"),
    ])
    res = an.tresorerie_disponible(centre=None, ref=ref, d=d)
    # CP : 10000 (PIS) + 5000 (TAM) = 15000 ; Banque (compte partage) :
    # 100000 (ouverture) + 20000 = 120000, une seule fois. Total = 135000.
    assert res["total"] == 135000.0
    lignes_banque = [x for x in res["detail"] if x["journal"] == "Banque"]
    assert len(lignes_banque) == 1


def test_tresorerie_disponible_pour_un_centre_garde_le_solde_bancaire_complet():
    # Une demande sur un seul centre ne doit pas non plus sous-compter la
    # banque (compte partage) en ne regardant que les mouvements de ce
    # centre : le solde de la banque reste son solde global complet.
    ref = _ref()
    d = pd.DataFrame([
        _ligne("PIS", "521200", debit=20000, journal="Banque", id_piece="P1"),
        _ligne("TAM", "521200", debit=30000, journal="Banque", id_piece="P2"),
    ])
    res = an.tresorerie_disponible(centre="PIS", ref=ref, d=d)
    lignes_banque = [x for x in res["detail"] if x["journal"] == "Banque"]
    assert len(lignes_banque) == 1
    # 100000 (ouverture) + 20000 (PIS) + 30000 (TAM) : le solde bancaire
    # global, pas seulement la part vue par PIS.
    assert lignes_banque[0]["solde"] == 150000.0


def test_tresorerie_disponible_exclut_un_journal_retire():
    ref = _ref()
    d = pd.DataFrame(columns=["centre", "compte", "journal", "debit", "credit"])
    res = an.tresorerie_disponible(centre=None, ref=ref, d=d)
    assert not any(x["journal"] == "BDU-BF" for x in res["detail"])


# --- maj_solde_ouverture_centre : requete UPSERT correcte -------------------

def test_maj_solde_ouverture_centre_envoie_un_upsert():
    # Pas de fixture monkeypatch (voir l'entete du fichier : aucun test d'ici
    # n'ouvre de connexion Postgres) - on remplace _connexion() a la main le
    # temps de l'appel, et on la restaure toujours, meme si l'appel echoue.
    captured = {}

    class FauxCurseur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params

    class FausseConnexion:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return FauxCurseur()

    import contextlib

    @contextlib.contextmanager
    def _faux_connexion():
        yield FausseConnexion()

    originale = dl._connexion
    dl._connexion = _faux_connexion
    try:
        dl.maj_solde_ouverture_centre("PIS", "CP", 12345)
    finally:
        dl._connexion = originale
    assert "ON CONFLICT (centre, journal)" in captured["sql"]
    assert captured["params"] == ("PIS", "CP", 12345.0)

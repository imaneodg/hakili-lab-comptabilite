# ---------------------------------------------------------------------------
# Tests de l'assistant IA reconstruit (24/09/2026).
#
# Trois familles :
#   1. comprehension : ce que les utilisateurs ecrivent vraiment ("saab",
#      "fevirer", "mars 26", "depuis la rentree"...) -> valeurs exactes, ou
#      question quand c'est ambigu, jamais une devinette silencieuse ;
#   2. moteur : les chiffres, sur les schemas d'ecriture reels de
#      test_assistant_hakili.py (vacation et loyer payes par 401000,
#      approvisionnement via 585000...), avec zero != aucune donnee, la banque
#      jamais ajoutee a un centre, la portee respectee ;
#   3. outils / rendu : un graphique se trace depuis un resultat, les cartes
#      n'exposent pas de JSON brut, le SQL libre est borne.
#
# Aucune requete Postgres : le moteur est branche sur les tables de test par
# monkeypatch (lire_lignes, referentiel.charger...).
# ---------------------------------------------------------------------------

import asyncio
import json
from datetime import date

import pandas as pd
import pytest

from assistant import moteur, referentiel, rendu, semantique as sem
from assistant.comprehension import (Incomprehension, chercher_tiers, resoudre_categories,
                                     resoudre_centres, resoudre_journaux, resoudre_periode,
                                     resoudre_tiers)
from tests.test_assistant_hakili import _ecritures, _ref

AUJ = date(2026, 9, 23)

CATEGORIES = pd.DataFrame([
    {"categorie": "vacations", "libelle": "Vacations et honoraires", "groupe": "masse_salariale",
     "comptes": ["632710"], "motifs": ["VACATION", "HONORAIRE"], "ordre": 10},
    {"categorie": "salaires", "libelle": "Salaires", "groupe": "masse_salariale",
     "comptes": ["422000", "661"], "motifs": ["SALAIRE"], "ordre": 20},
    {"categorie": "loyer", "libelle": "Loyer", "groupe": "charges_fixes",
     "comptes": ["622200"], "motifs": ["LOYER", "BAIL"], "ordre": 30},
    {"categorie": "eau", "libelle": "Eau (ONEA)", "groupe": "charges_fixes",
     "comptes": ["605100"], "motifs": ["ONEA"], "ordre": 40},
    {"categorie": "electricite", "libelle": "Electricite", "groupe": "charges_fixes",
     "comptes": ["605200"], "motifs": ["SONABEL", "CASH POWER"], "ordre": 50},
    {"categorie": "internet_telephone", "libelle": "Internet et telephone", "groupe": "courante",
     "comptes": ["628810", "628820"], "motifs": ["INTERNET"], "ordre": 70},
])
ALIAS = pd.DataFrame([{"alias": "saab", "code_centre": "SAA"}, {"alias": "tampuy", "code_centre": "TAM"},
                      {"alias": "pisi", "code_centre": "PIS"}])


def _referentiel():
    ref = _ref()
    ref["centres"] = pd.DataFrame([
        {"code_centre": "PIS", "intitule": "Pissy", "actif": "oui"},
        {"code_centre": "TAM", "intitule": "Tampouy", "actif": "oui"},
        {"code_centre": "SAA", "intitule": "Saaba", "actif": "oui"},
        {"code_centre": "SIA", "intitule": "SIAO", "actif": "oui"},
        {"code_centre": "NAG", "intitule": "Nagrin", "actif": "oui"},
        {"code_centre": "SIE", "intitule": "Siege", "actif": "oui"},
    ])
    ref["tiers"] = pd.DataFrame([
        {"code_tiers": "411KAELY", "intitule": "BELEMTOUGRI W KAELY", "type": "client"},
        {"code_tiers": "411AMINATA", "intitule": "OUEDRAOGO AMINATA YASMINE", "type": "client"},
        {"code_tiers": "411AMIRAT", "intitule": "OUEDRAOGO AMIRAT", "type": "client"},
        {"code_tiers": "401RACHIDA", "intitule": "PALLO RASSIDATOU", "type": "fournisseur"},
        {"code_tiers": "401BAILLEURTPOUY", "intitule": "Bailleur Tampouy", "type": "fournisseur"},
        {"code_tiers": "401DIVERS", "intitule": "Fournisseur divers", "type": "fournisseur"},
    ])
    ref["soldes_centre"] = pd.DataFrame(
        [{"centre": c, "journal": j, "solde_ouverture": 0.0}
         for c in ("PIS", "TAM", "SAA", "SIA", "NAG", "SIE") for j in ("CP", "CMD")])
    return referentiel.construire(ref, ALIAS, CATEGORIES)


@pytest.fixture
def R():
    return _referentiel()


@pytest.fixture
def ctx(monkeypatch, R):
    """Contexte de conversation branche sur les ecritures de test."""
    d = _ecritures()
    for col in ("num_definitif", "num_provisoire", "observation"):
        d[col] = ""

    def lire_lignes(du=None, au=None, centres=None):
        x = d.copy()
        dates = pd.to_datetime(x["date_piece"]).dt.date
        if du is not None:
            x = x[dates >= du]
            dates = pd.to_datetime(x["date_piece"]).dt.date
        if au is not None:
            x = x[dates <= au]
        if centres:
            x = x[x["centre"].isin(centres)]
        return x.reset_index(drop=True)

    monkeypatch.setattr(sem, "lire_lignes", lire_lignes)
    monkeypatch.setattr(sem, "fournisseurs_en_regime_facture", lambda R_: set())
    monkeypatch.setattr(sem, "plage_donnees", lambda: (date(2026, 2, 3), date(2026, 3, 16)))
    monkeypatch.setattr(referentiel, "charger", lambda forcer=False: R)
    return moteur.Contexte(aujourd_hui=AUJ)


# =============================================================================
# 1. COMPREHENSION
# =============================================================================

@pytest.mark.parametrize("ecrit,code", [
    ("saa", "SAA"), ("SAA", "SAA"), ("saab", "SAA"), ("Saaba", "SAA"), ("sabaa", "SAA"),
    ("centre de saaba", "SAA"), ("tampuy", "TAM"), ("tam", "TAM"), ("Tampouy", "TAM"),
    ("pisi", "PIS"), ("pissy", "PIS"), ("nag", "NAG"), ("nagrine", "NAG"), ("siao", "SIA"),
])
def test_un_centre_mal_ecrit_est_reconnu(R, ecrit, code):
    codes, _ = resoudre_centres(ecrit, R)
    assert codes == [code]


def test_plusieurs_centres_et_tous(R):
    assert resoudre_centres("saab et tampuy", R)[0] == ["SAA", "TAM"]
    assert resoudre_centres(["pisi", "SIA"], R)[0] == ["PIS", "SIA"]
    tous, _ = resoudre_centres("tous", R)
    assert set(tous) == {"PIS", "TAM", "SAA", "SIA", "NAG"}      # siege exclu par defaut
    assert resoudre_centres(None, R)[0] == tous


def test_un_centre_ambigu_ou_inconnu_declenche_une_question(R):
    with pytest.raises(Incomprehension) as e:
        resoudre_centres("s", R)
    assert e.value.code == "centre_ambigu" and "Saaba" in e.value.candidats
    with pytest.raises(Incomprehension) as e:
        resoudre_centres("ouaga 2000", R)
    assert e.value.code == "centre_inconnu"


def test_la_portee_est_respectee(R):
    assert resoudre_centres(None, R, portee=["TAM"])[0] == ["TAM"]
    assert resoudre_centres("tampuy", R, portee=["TAM"])[0] == ["TAM"]
    with pytest.raises(Incomprehension) as e:
        resoudre_centres("saaba", R, portee=["TAM"])
    assert e.value.code == "hors_portee"
    with pytest.raises(Incomprehension):
        resoudre_centres(None, R, portee=[])                  # liste vide = aucun acces


@pytest.mark.parametrize("ecrit,du,au", [
    ("fevrier", "2026-02-01", "2026-02-28"),
    ("fevirer", "2026-02-01", "2026-02-28"),
    ("février 2026", "2026-02-01", "2026-02-28"),
    ("fev 26", "2026-02-01", "2026-02-28"),
    ("202603", "2026-03-01", "2026-03-31"),
    ("2026-03", "2026-03-01", "2026-03-31"),
    ("03/2026", "2026-03-01", "2026-03-31"),
    ("mars 26", "2026-03-01", "2026-03-31"),
    ("decembre", "2025-12-01", "2025-12-31"),               # mois passe le plus proche
    ("ce mois", "2026-09-01", "2026-09-23"),
    ("le mois dernier", "2026-08-01", "2026-08-31"),
    ("T1", "2026-01-01", "2026-03-31"),
    ("premier trimestre 2026", "2026-01-01", "2026-03-31"),
    ("depuis la rentree", "2026-09-01", "2026-09-23"),
    ("l'annee scolaire derniere", "2025-09-01", "2026-08-31"),
    ("annee scolaire 2025-2026", "2025-09-01", "2026-08-31"),
    ("2025-2026", "2025-09-01", "2026-08-31"),
    ("du 15/03/2026 au 15/04/2026", "2026-03-15", "2026-04-15"),
    ("entre janvier et mars", "2026-01-01", "2026-03-31"),
    ("de novembre a fevrier", "2025-11-01", "2026-02-28"),
    ("depuis janvier", "2026-01-01", "2026-09-23"),
    ("15 mars 2026", "2026-03-15", "2026-03-15"),
    ("2026-03-11", "2026-03-11", "2026-03-11"),
    ("11/03/2026", "2026-03-11", "2026-03-11"),
    ("hier", "2026-09-22", "2026-09-22"),
    ("2026", "2026-01-01", "2026-12-31"),
])
def test_une_periode_ecrite_librement_est_comprise(ecrit, du, au):
    p = resoudre_periode(ecrit, auj=AUJ)
    assert (p.du.isoformat(), p.au.isoformat()) == (du, au)


def test_sans_periode_le_dernier_mois_complet():
    p = resoudre_periode(None, auj=AUJ)
    assert (p.du, p.au) == (date(2026, 8, 1), date(2026, 8, 31))
    assert p.libelle == "août 2026"


def test_du_au_iso_et_periode_illisible():
    p = resoudre_periode(du="2026-01-10", au="2026-02-05", auj=AUJ)
    assert (p.du, p.au) == (date(2026, 1, 10), date(2026, 2, 5))
    with pytest.raises(Incomprehension) as e:
        resoudre_periode("n'importe quoi", auj=AUJ)
    assert e.value.code == "periode_invalide"


def test_cette_annee_est_lue_comme_annee_scolaire():
    p = resoudre_periode("cette annee", auj=AUJ)
    assert p.du == date(2026, 9, 1) and "scolaire" in p.interpretation


def test_tiers_approximatif(R):
    assert resoudre_tiers("belemtougri kaely", R)[0] == ["411KAELY"]
    assert resoudre_tiers("pallo rasidatou", R)[0] == ["401RACHIDA"]
    with pytest.raises(Incomprehension) as e:
        resoudre_tiers("ouedraogo", R)
    assert e.value.code == "tiers_ambigu" and len(e.value.candidats) >= 2
    assert chercher_tiers("aminata", R)[0]["code"] == "411AMINATA"


def test_categories_et_journaux(R):
    assert resoudre_categories("loyers", R) == ["loyer"]
    assert resoudre_categories("vacataires", R) == ["vacations"]
    assert set(resoudre_categories("masse salariale", R)) == {"vacations", "salaires"}
    assert resoudre_journaux("caisse principale", R) == ["CP"]
    assert resoudre_journaux("petite caisse", R) == ["CMD"]
    assert resoudre_journaux("banque", R) == ["Banque"]
    assert set(resoudre_journaux("caisses", R)) == {"CP", "CMD"}


# =============================================================================
# 2. MOTEUR
# =============================================================================

def test_encaissements_saab_mars(ctx):
    res, p = moteur.analyser(ctx, indicateurs="recettes", periode="mars 26", centres="saab")
    # 31 500 + 3 x 20 000 ; l'approvisionnement via 585000 n'est pas une recette
    assert p["total"]["encaissements"] == 91500
    assert p["donnees_disponibles"] is True
    assert any("saab" in x for x in p["interpretation"])


def test_decaissements_et_flux_net(ctx):
    _, p = moteur.analyser(ctx, indicateurs=["encaissements", "decaissements", "flux_net"],
                           periode="mars 2026", centres="SAA")
    assert p["total"]["decaissements"] == 120000 + 125000 + 10150 + 30000
    assert p["total"]["flux_net"] == 91500 - 285150


def test_charges_reconstituees_par_categorie(ctx):
    res, p = moteur.analyser(ctx, indicateurs="charges", periode="mars 2026", centres="SAA",
                             regrouper_par="categorie")
    par_cat = {l["categorie"]: l["charges"] for l in p["lignes"]}
    assert par_cat["Vacations et honoraires"] == 120000       # paye par 401000
    # "PAIEMENT LOYER FEVRIER" paye le 06/03 : charge de fevrier, pas de mars
    assert "Loyer" not in par_cat
    assert par_cat["Electricite"] == 10150                     # vrai compte de charge
    assert par_cat["Dépenses sans type"] == 30000
    assert p["total"]["charges"] == 160150
    assert any("sans type" in a for a in p["avertissements"])


def test_masse_salariale_et_part(ctx):
    _, p = moteur.analyser(ctx, indicateurs="masse salariale, part_masse_salariale_pct",
                           periode="mars 2026", centres="SAA")
    assert p["total"]["masse_salariale"] == 120000
    assert p["total"]["part_masse_salariale_pct"] == round(120000 / 160150 * 100, 1)


def test_produits_et_resultat_de_gestion(ctx):
    _, p = moteur.analyser(ctx, indicateurs="benefice, chiffre d'affaires, charges",
                           periode="T1 2026", centres="SAA", regrouper_par="mois")
    par_mois = {l["mois"]: l for l in p["lignes"]}
    assert par_mois["février 2026"]["produits"] == 200000
    assert par_mois["février 2026"]["charges"] == 100000 + 125000      # loyer de fevrier
    assert par_mois["février 2026"]["resultat"] == -25000
    assert par_mois["mars 2026"]["produits"] == 91500
    assert par_mois["mars 2026"]["resultat"] == 91500 - 160150


def test_rattachement_au_mois_de_prestation():
    from assistant.semantique import mois_du_libelle, rattacher
    assert mois_du_libelle("PAIEMENT VACATION DECEMBRE", date(2026, 1, 10)) == [(2025, 12)]
    assert mois_du_libelle("AVANCE CA JAN-JUIN-JUIL - X", date(2026, 3, 1)) == \
        [(2026, 1), (2026, 6), (2026, 7)]
    assert mois_du_libelle("FRAIS CA MAIGA NAFISSATOU/DECEMBRE", date(2026, 1, 5)) == [(2025, 12)]
    assert mois_du_libelle("FRAIS CA TRAORE FARID", date(2026, 2, 1)) == []
    f = rattacher(pd.DataFrame([{"date": date(2026, 3, 1), "libelle": "AVANCE CA JUIN-JUIL",
                                 "montant": 60000.0}]))
    assert list(f["montant"]) == [30000.0, 30000.0]
    assert list(f["date"]) == [date(2026, 6, 1), date(2026, 7, 1)]


def test_remboursement_parent_et_erreur_d_imputation(R):
    d = pd.DataFrame(_ecritures())
    for col in ("num_definitif", "num_provisoire", "observation"):
        d[col] = ""
    extra = pd.DataFrame([
        {"id_piece": "P-REMB", "centre": "SAA", "journal": "CP", "date_piece": "2026-03-20",
         "compte": "411000", "debit": 10000.0, "credit": 0.0, "code_tiers": "411KAELY",
         "libelle": "REMBOURSEMENT PARENT", "modele": "libre", "statut": "validee"},
        {"id_piece": "P-ERR", "centre": "SAA", "journal": "CP", "date_piece": "2026-03-21",
         "compte": "411000", "debit": 50000.0, "credit": 0.0, "code_tiers": "",
         "libelle": "CONTRIBUTION POUR SIAO/FEVRIER", "modele": "libre", "statut": "validee"}])
    d = pd.concat([d, extra], ignore_index=True)
    p = sem.faits_produits(d, R)
    assert p.loc[p["id_piece"] == "P-REMB", "montant"].sum() == -10000   # vient en deduction
    assert "P-ERR" not in set(p["id_piece"])                              # pas un produit negatif
    assert list(sem.imputations_411_a_verifier(d)["id_piece"]) == ["P-ERR"]


def test_aucune_donnee_nest_jamais_zero(ctx):
    _, p = moteur.analyser(ctx, indicateurs="encaissements", periode="juin 2026", centres="pisi")
    assert p["donnees_disponibles"] is False
    assert "Rien n'est enregistré" in p["avertissements"][0]


def test_regroupement_par_centre_garde_les_centres_sans_activite(ctx):
    _, p = moteur.analyser(ctx, indicateurs="encaissements", periode="mars 2026",
                           regrouper_par="centre")
    centres = [l["centre"] for l in p["lignes"]]
    assert centres[0] == "Saaba" and set(centres) == {"Saaba", "Tampouy", "Pissy", "SIAO", "Nagrin"}
    assert any("Rien d'enregistré sur la période pour" in a for a in p["avertissements"])


def test_evolution_mensuelle_complete_les_mois_vides(ctx):
    res, p = moteur.analyser(ctx, indicateurs="encaissements", periode="T1 2026",
                             regrouper_par="mois", centres="SAA")
    assert [l["mois"] for l in p["lignes"]] == ["janvier 2026", "février 2026", "mars 2026"]
    assert [l["encaissements"] for l in p["lignes"]] == [0, 200000, 91500]
    assert p["graphique_suggere"] == "courbe"


def test_argent_recu_et_depense_par_type(ctx):
    _, p = moteur.analyser(ctx, indicateurs="depenses", periode="mars 2026", centres="SAA",
                           regrouper_par="type")
    par_type = {l["categorie"]: l["decaissements"] for l in p["lignes"]}
    # le loyer de fevrier paye en mars est bien une sortie d'argent de mars
    assert par_type["Loyer"] == 125000
    assert par_type["Vacations et honoraires"] == 120000
    _, p = moteur.analyser(ctx, indicateurs="recettes", periode="mars 2026", centres="SAA",
                           regrouper_par="type")
    assert {l["categorie"]: l["encaissements"] for l in p["lignes"]} == {"Frais de cours": 91500}


def test_comparaison_au_mois_precedent(ctx):
    _, p = moteur.comparer(ctx, indicateurs="encaissements", periode="mars 2026", centres="SAA")
    assert p["perimetre"]["periode_reference"] == "février 2026"
    assert p["total"]["encaissements"] == 91500
    assert p["total"]["encaissements_ref"] == 200000
    assert p["total"]["encaissements_ecart"] == -108500


def test_la_banque_nest_jamais_ajoutee_a_un_centre(ctx):
    _, p = moteur.soldes(ctx, centres="SAA")
    assert "banque" in p["total"]
    lignes_saaba = [l for l in p["lignes"] if l["centre"] == "Saaba"]
    assert {l["caisse"] for l in lignes_saaba} == {"Caisse principale", "Petite caisse"}
    # caisses de Saaba : CP 31 500 + 60 000 + 200 000 - 150 000 ; CMD 150 000 - 385 150 + ...
    assert p["total"]["caisses"] == sum(l["solde"] for l in lignes_saaba)


def test_une_session_restreinte_ne_voit_ni_la_banque_ni_un_autre_centre(monkeypatch, R, ctx):
    ctx.portee = ["TAM"]
    _, p = moteur.soldes(ctx)
    assert all(l["centre"] == "Tampouy" for l in p["lignes"])
    assert "banque" not in p["total"]
    with pytest.raises(Incomprehension):
        moteur.analyser(ctx, centres="saaba")
    with pytest.raises(Incomprehension):
        moteur.requete_sql(ctx, "select 1")
    _, p = moteur.analyser(ctx, indicateurs="encaissements", periode="mars 2026",
                           regrouper_par="centre")
    assert [l["centre"] for l in p["lignes"]] == ["Tampouy"]


def test_controle_des_doublons(ctx):
    _, p = moteur.controles(ctx, "paiements suspects", periode="mars 2026")
    assert p["total"]["nb_elements"] == 3
    assert all(l["montant"] == 20000 for l in p["lignes"])


def test_personnel_paiements(ctx):
    _, p = moteur.personnel(ctx, "paiements", periode="fevrier a mars 2026")
    assert p["lignes"][0]["personne"] == "PALLO RASSIDATOU"
    assert p["total"]["montant"] == 220000


# =============================================================================
# 3. SQL, RENDU, OUTILS
# =============================================================================

@pytest.mark.parametrize("sql", [
    "delete from ecritures", "select * from utilisateurs", "select 1; drop table ecritures",
    "select * from ecritures", "update v_lignes set debit = 0", "select pg_read_file('x')",
    "with x as (select 1) insert into centres values ('a')",
])
def test_le_sql_libre_est_borne(sql):
    with pytest.raises(Incomprehension):
        moteur.verifier_sql(sql)


def test_le_sql_libre_accepte_une_lecture_de_v_lignes():
    s = moteur.verifier_sql("with m as (select mois, sum(debit) d from v_lignes group by mois) "
                            "select * from m join centres on true;")
    assert s.endswith("true")


def test_un_graphique_se_trace_depuis_chaque_forme_de_resultat(ctx):
    cas = [
        moteur.analyser(ctx, indicateurs="encaissements,decaissements", periode="T1 2026",
                        regrouper_par="mois")[0],
        moteur.analyser(ctx, indicateurs="encaissements", periode="mars 2026",
                        regrouper_par="centre")[0],
        moteur.analyser(ctx, indicateurs="charges", periode="mars 2026", regrouper_par="categorie")[0],
        moteur.analyser(ctx, indicateurs="encaissements", periode="T1 2026",
                        regrouper_par=["mois", "centre"])[0],
        moteur.comparer(ctx, indicateurs="encaissements", periode="mars 2026",
                        regrouper_par="centre")[0],
        moteur.soldes(ctx)[0],
        moteur.personnel(ctx, "paiements", periode="T1 2026")[0],
    ]
    for res in cas:
        img, description = rendu.graphique(res)
        assert 'src="data:image/png;base64,' in str(img), res.titre


def test_pas_de_graphique_pour_un_chiffre_seul(ctx):
    res, _ = moteur.analyser(ctx, indicateurs="encaissements", periode="mars 2026")
    with pytest.raises(Incomprehension):
        rendu.graphique(res)


def test_le_tableau_echappe_les_libelles(ctx):
    res, _ = moteur.lister_ecritures(ctx, periode="mars 2026", centres="SAA")
    res.table.loc[0, "libelle"] = "<script>alert(1)</script>"
    assert "<script>" not in str(rendu.tableau(res))


def test_les_outils_renvoient_des_cartes_lisibles(ctx):
    from assistant.outils import creer_outils
    trace = []
    outils = {f.__name__: f for f in creer_outils(ctx, trace)}
    assert set(outils) == {"contexte", "point_financier", "analyser", "comparer", "soldes",
                           "lister_ecritures", "a_verifier", "chercher", "controles", "personnel",
                           "graphique", "requete_sql"}
    r = outils["analyser"](indicateurs=["encaissements"], periode="fevirer", centres="saab",
                           regrouper_par=["mois"])
    valeur = json.loads(r.value)
    assert valeur["total"]["encaissements"] == 200000
    assert r.extra["display"]["show_request"] is False
    g = outils["graphique"](id_resultat=valeur["id_resultat"])
    assert "data:image/png" in str(g.extra["display"]["html"]) and g.extra["display"]["open"]
    amb = json.loads(outils["analyser"](centres="s").value)
    assert amb["erreur"] == "centre_ambigu"
    assert json.loads(outils["graphique"](id_resultat="r999").value)["erreur"] == "resultat_introuvable"
    assert [a["outil"] for a in trace][:2] == ["analyser", "graphique"]


def test_session_restreinte_sans_sql(monkeypatch, ctx):
    from assistant.outils import creer_outils
    ctx.portee = ["TAM"]
    assert "requete_sql" not in {f.__name__ for f in creer_outils(ctx, [])}


def test_historique_borne(monkeypatch):
    """Au-dela de N echanges, les plus anciens sont oublies, en coupant
    toujours avant une question (jamais entre un appel d'outil et son resultat)."""
    from chatlas import AssistantTurn, UserTurn
    from assistant import config
    from assistant.session import SessionAssistant
    monkeypatch.setattr(config, "HISTORIQUE_MAX_ECHANGES", 3)

    class Faux:
        def __init__(self):
            self.tours = []

        def get_turns(self):
            return list(self.tours)

        def set_turns(self, t):
            self.tours = list(t)

    s = SessionAssistant()
    s._client = Faux()
    for i in range(6):
        s._client.tours += [UserTurn(f"question {i}"), AssistantTurn(f"reponse {i}")]
    s._elaguer()
    assert [t.text for t in s._client.tours if t.role == "user"] == ["question 4", "question 5"]


def test_message_erreur_lisible():
    from assistant.session import message_erreur
    assert "surchargé" in message_erreur(Exception("Error code: 529 overloaded_error"))
    assert "clé" in message_erreur(type("AuthenticationError", (Exception,), {})("401"))


def test_sans_cle_api_un_message_clair(monkeypatch):
    from assistant.session import SessionAssistant
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("assistant.journal.enregistrer", lambda **k: None)
    s = SessionAssistant()

    async def lire():
        return [m async for m in s.repondre("encaissements")]

    morceaux = asyncio.run(lire())
    assert "ANTHROPIC_API_KEY" in "".join(morceaux)
    assert s.occupe is False


# =============================================================================
# 4. TABLEAU DE BORD DU DIRECTEUR
# =============================================================================

def test_sans_periode_le_mois_en_cours_ou_le_dernier_mois_saisi(ctx):
    per = moteur.periode_par_defaut(ctx)
    # rien en septembre 2026 dans les donnees de test : on passe a mars 2026 et on le dit
    assert (per.du, per.au) == (date(2026, 3, 1), date(2026, 3, 31))
    assert "rien n'est encore enregistré en septembre 2026" in per.interpretation


def test_point_financier(ctx):
    res, p = moteur.point_financier(ctx)
    assert p["periode"] == "mars 2026" and p["periode_precedente"] == "février 2026"
    assert p["mois"] == {"recu": 91500, "depense": 285150, "reste": 91500 - 285150}
    assert p["mois_precedent"]["recu"] == 200000
    assert p["plus_grosses_depenses"][0] == {"type": "Loyer", "montant": 125000}
    assert [c["centre"] for c in p["centres"]] == ["Saaba", "Tampouy"]   # Tampouy : caisse seulement
    assert set(p["centres_sans_operation"]) >= {"Pissy", "Nagrin"}
    assert "disponible" in p and "a_verifier" in p
    html = str(rendu.tableau_de_bord(res.donnees))
    assert "Argent disponible" in html and "Saaba" in html


def test_a_verifier_regroupe_les_controles(ctx):
    _, p = moteur.a_verifier(ctx)
    points = {x["detail"]: x for x in p["points"]}
    assert points["dates_douteuses"]["nombre"] == 1         # la piece de 2006
    assert points["doublons"]["nombre"] == 3                # les trois paiements identiques de mars


def test_operations_desequilibrees():
    d = pd.DataFrame([
        {"id_piece": "A", "date_piece": "2026-03-01", "centre": "SAA", "libelle": "OK",
         "debit": 100.0, "credit": 0.0}, {"id_piece": "A", "date_piece": "2026-03-01", "centre": "SAA",
                                          "libelle": "OK", "debit": 0.0, "credit": 100.0},
        {"id_piece": "B", "date_piece": "2026-03-02", "centre": "SAA", "libelle": "FAUX",
         "debit": 100.0, "credit": 0.0}])
    x = moteur.desequilibres(d)
    assert [e["id_piece"] for e in x] == ["B"] and x[0]["ecart"] == 100


def test_mouvements_lisibles_du_plus_recent_au_plus_ancien(ctx):
    _, p = moteur.lister_ecritures(ctx, periode="mars 2026", centres="SAA", sens="payé")
    assert list(p["lignes"][0]) == ["date", "centre", "caisse", "type", "libelle", "recu", "paye"]
    assert p["lignes"][0]["date"] == "16/03/2026"
    assert all(l["paye"] > 0 for l in p["lignes"])
    assert p["total"]["paye"] == 285150                      # l'approvisionnement n'est pas une depense


def test_le_vocabulaire_reste_simple(ctx):
    res, _ = moteur.analyser(ctx, indicateurs="recettes, depenses", periode="mars 2026",
                             regrouper_par="centre")
    libelles = " ".join(l for _, l, _ in res.colonnes)
    for jargon in ("Encaissement", "Decaissement", "Flux", "Charges", "Produits", "471", "411"):
        assert jargon not in libelles
    from assistant.prompt import construire
    texte = construire(["Saaba"], (date(2026, 1, 1), date(2026, 3, 1)), AUJ, "M. le directeur")
    assert "directeur" in texte and "argent reçu" in texte

# ---------------------------------------------------------------------------
# Transferts internes entre centres (12/09/2026)
#
# Un centre remet des especes a un autre - le cas courant etant le depot au
# centre SIAO, qui paie ensuite pour le compte de tous. Compte SYSCOHADA
# 585000 "Virements de fonds", deja present dans le plan Sage de HAKILISSO.
#
# Ce que ces tests protegent :
#   1. un transfert n'est NI une recette NI une depense - pour aucun des deux
#      centres, ni pour Hakili Lab consolide ;
#   2. le sens se deduit de qui saisit, jamais d'un champ "sens" ;
#   3. le rapprochement distingue "en transit" (normal) de "anomalie" ;
#   4. le libelle est libre et n'entre JAMAIS dans le rapprochement ;
#   5. les centres s'affichent en toutes lettres, jamais par leur code.
# ---------------------------------------------------------------------------

import pandas as pd
import pytest

import logic.analyse as an
import logic.donnees as dl
import logic.modeles as md

CENTRES = [("PIS", "Pissy"), ("TAM", "Tampouy"), ("SAA", "Saaba"),
           ("SIA", "SIAO"), ("NAG", "Nagrin"), ("SIE", "Siege")]
VF = an.COMPTE_VIREMENTS_FONDS          # 585000


def _ref():
    comptes = pd.DataFrame([
        {"compte": "571100", "intitule": "Caisse Principale", "nature": "tresorerie"},
        {"compte": "571200", "intitule": "Caisse Menu Depense", "nature": "tresorerie"},
        {"compte": VF, "intitule": "Virements de fonds", "nature": "tresorerie"},
        {"compte": "411000", "intitule": "Clients", "nature": "tiers"},
        {"compte": "605200", "intitule": "Electricite", "nature": "charge"},
    ])
    journaux = pd.DataFrame([
        {"journal": "CP", "intitule": "Caisse principale", "compte_contrepartie": "571100",
         "type": "tresorerie", "solde_ouverture": 0.0, "caisse_physique": "oui", "actif": "oui"},
        {"journal": "CMD", "intitule": "Caisse menues depenses", "compte_contrepartie": "571200",
         "type": "tresorerie", "solde_ouverture": 0.0, "caisse_physique": "oui", "actif": "oui"},
    ])
    centres = pd.DataFrame([{"code_centre": c, "intitule": n, "actif": "oui"} for c, n in CENTRES])
    tiers = pd.DataFrame([{"code_tiers": "411E", "intitule": "Un eleve"}])
    soldes = pd.DataFrame([{"centre": c, "journal": j, "solde_ouverture": 0.0}
                           for c, _ in CENTRES for j in ("CP", "CMD")])
    return {"comptes": comptes, "journaux": journaux, "centres": centres,
            "tiers": tiers, "soldes_centre": soldes}


def _piece(id_piece, centre, date_piece, lignes, reference="", contrepartie="", journal="CP"):
    return [{"id_piece": id_piece, "centre": centre, "journal": journal,
             "date_piece": date_piece, "compte": c, "debit": float(d), "credit": float(cr),
             "code_tiers": "", "libelle": lib, "modele": "transfert_interne",
             "statut": "validee", "reference_transfert": reference,
             "centre_contrepartie": contrepartie}
            for c, d, cr, lib in lignes]


def _jour(recul):
    return (pd.Timestamp.now().normalize() - pd.Timedelta(days=recul)).strftime("%Y-%m-%d")


def _sortie(centre, vers, reference, montant=50000, recul=2, libelle="CONTRIBUTION SIAO"):
    return _piece(f"S-{reference}", centre, _jour(recul),
                  [(VF, montant, 0, libelle), ("571100", 0, montant, libelle)],
                  reference=reference, contrepartie=vers)


def _entree(centre, depuis, reference, montant=50000, recul=0, suffixe="", libelle="APPROV SIAO"):
    return _piece(f"E-{reference}{suffixe}", centre, _jour(recul),
                  [("571100", montant, 0, libelle), (VF, 0, montant, libelle)],
                  reference=reference, contrepartie=depuis)


def _activite(centre, montant=300000):
    """Un encaissement d'eleve, pour que le centre ait une activite reelle."""
    return [{"id_piece": f"ENC-{centre}", "centre": centre, "journal": "CP",
             "date_piece": _jour(5), "compte": c, "debit": float(d), "credit": float(cr),
             "code_tiers": t, "libelle": "FRAIS CA ELEVE", "modele": "encaissement",
             "statut": "validee", "reference_transfert": "", "centre_contrepartie": ""}
            for c, d, cr, t in [("571100", montant, 0, ""), ("411000", 0, montant, "411E")]]


@pytest.fixture
def ref():
    return _ref()


# =============================================================================
# 1. Un transfert n'est ni une recette ni une depense
# =============================================================================

def test_un_transfert_ne_cree_ni_recette_ni_depense(ref):
    """Le point comptable central. L'argent change de tiroir : ni le centre qui
    remet ni celui qui recoit n'a gagne ou depense quoi que ce soit."""
    d = pd.DataFrame(_activite("PIS") + _activite("SIA")
                     + _sortie("PIS", "SIA", "TRF-1") + _entree("SIA", "PIS", "TRF-1"))
    mois = pd.Timestamp(_jour(2)).strftime("%Y%m")
    assert an.recettes_centre_mois("SIA", mois, ref, d) == 300000
    assert an.depenses_centre_mois("PIS", mois, ref, d) == 0
    assert an.recettes_centre_mois("PIS", mois, ref, d) == 300000


def test_le_consolide_ignore_les_transferts(ref, monkeypatch):
    """Meme resultat consolide avec et sans transferts : pour Hakili Lab, il
    ne s'est rien passe."""
    sans = pd.DataFrame(_activite("PIS") + _activite("SIA"))
    avec = pd.DataFrame(_activite("PIS") + _activite("SIA")
                        + _sortie("PIS", "SIA", "TRF-1") + _entree("SIA", "PIS", "TRF-1"))
    mois = pd.Timestamp(_jour(2)).strftime("%Y%m")
    monkeypatch.setattr(an.dl, "lire_ecritures", lambda *a, **k: avec)
    r_avec = an.resultat_net_mois(mois, ref)
    monkeypatch.setattr(an.dl, "lire_ecritures", lambda *a, **k: sans)
    r_sans = an.resultat_net_mois(mois, ref)
    assert r_avec == r_sans


def test_une_piece_de_transfert_est_reconnue_comme_telle(ref):
    d = pd.DataFrame(_sortie("PIS", "SIA", "TRF-1"))
    assert an.pieces_transfert_interne(d, ref) == {"S-TRF-1"}


# =============================================================================
# 2. Le sens se deduit de qui saisit
# =============================================================================

def test_le_donateur_credite_sa_caisse(ref):
    lignes = md.construire_lignes("transfert_interne", {
        "mon_centre": "PIS", "centre_donateur": "PIS", "centre_destinataire": "SIA",
        "montant": 50000}, "CP", ref)
    assert lignes.loc[lignes["compte"] == VF, "debit"].iloc[0] == 50000
    assert lignes.loc[lignes["compte"] == "571100", "credit"].iloc[0] == 50000


def test_le_destinataire_debite_sa_caisse(ref):
    lignes = md.construire_lignes("transfert_interne", {
        "mon_centre": "SIA", "centre_donateur": "PIS", "centre_destinataire": "SIA",
        "montant": 50000}, "CP", ref)
    assert lignes.loc[lignes["compte"] == "571100", "debit"].iloc[0] == 50000
    assert lignes.loc[lignes["compte"] == VF, "credit"].iloc[0] == 50000


def test_la_meme_saisie_donne_deux_ecritures_inverses(ref):
    """Deux caissiers, la meme description de l'operation, deux ecritures
    opposees - sans qu'aucun des deux n'ait eu a choisir un "sens"."""
    base = {"centre_donateur": "PIS", "centre_destinataire": "SIA", "montant": 50000}
    a = md.construire_lignes("transfert_interne", {**base, "mon_centre": "PIS"}, "CP", ref)
    b = md.construire_lignes("transfert_interne", {**base, "mon_centre": "SIA"}, "CP", ref)
    assert a.loc[a["compte"] == VF, "debit"].iloc[0] == b.loc[b["compte"] == VF, "credit"].iloc[0]


def test_un_transfert_fonctionne_depuis_nimporte_quelle_caisse(ref):
    """Les brouillards reels montrent des remises au SIAO depuis la caisse
    principale comme depuis la caisse menues depenses."""
    for journal, caisse in [("CP", "571100"), ("CMD", "571200")]:
        lignes = md.construire_lignes("transfert_interne", {
            "mon_centre": "SAA", "centre_donateur": "SAA", "centre_destinataire": "SIA",
            "montant": 50000}, journal, ref)
        assert set(lignes["compte"]) == {VF, caisse}


# =============================================================================
# 3. Le rapprochement : trois statuts, pas deux
# =============================================================================

def test_un_transfert_complet_est_solde(ref):
    d = pd.DataFrame(_sortie("PIS", "SIA", "TRF-1") + _entree("SIA", "PIS", "TRF-1"))
    r = an.transferts_internes(None, ref, d)
    assert r["resume"] == {"soldes": 1, "en_transit": 0, "anomalies": 0, "sans_reference": 0}
    assert r["solde_compte_585000"] == 0
    assert r["soldes"][0]["ecart"] == 0


def test_une_remise_recente_est_en_transit_pas_une_anomalie(ref):
    """Le point qui decide si le comptable lira les alertes ou non. Une remise
    partie il y a trois jours et pas encore enregistree a l'arrivee est le
    fonctionnement normal - les brouillards montrent une remise de janvier
    enregistree le 20 fevrier."""
    d = pd.DataFrame(_sortie("PIS", "SIA", "TRF-1", recul=3))
    r = an.transferts_internes(None, ref, d)
    assert r["resume"]["en_transit"] == 1
    assert r["resume"]["anomalies"] == 0
    assert r["en_transit"][0]["centre_destinataire_nom"] == "SIAO"


def test_une_remise_trop_ancienne_devient_une_anomalie(ref):
    d = pd.DataFrame(_sortie("PIS", "SIA", "TRF-1", recul=45))
    r = an.transferts_internes(None, ref, d)
    assert r["resume"]["anomalies"] == 1
    assert "jamais recu" in r["anomalies"][0]["motif"]


def test_un_ecart_de_montant_est_signale(ref):
    """50 000 partis, 40 000 comptes a l'arrivee. Les deux faces doivent se
    rapprocher malgre l'ecart, sinon l'anomalie reelle - il manque de
    l'argent - deviendrait deux anomalies de forme."""
    d = pd.DataFrame(_sortie("NAG", "SIA", "TRF-9", montant=50000)
                     + _entree("SIA", "NAG", "TRF-9", montant=40000))
    r = an.transferts_internes(None, ref, d)
    assert r["resume"]["anomalies"] == 1
    a = r["anomalies"][0]
    assert a["ecart"] == 10000
    assert a["centre_donateur_nom"] == "Nagrin"


def test_une_remise_recue_deux_fois_est_signalee(ref):
    d = pd.DataFrame(_sortie("PIS", "SIA", "TRF-7")
                     + _entree("SIA", "PIS", "TRF-7")
                     + _entree("SIA", "PIS", "TRF-7", suffixe="-bis"))
    r = an.transferts_internes(None, ref, d)
    assert r["resume"]["anomalies"] == 1
    assert r["anomalies"][0]["motif"] == "recu plusieurs fois"


def test_une_entree_sans_sortie_est_signalee(ref):
    d = pd.DataFrame(_entree("SIA", "PIS", "TRF-ORPHELIN"))
    r = an.transferts_internes(None, ref, d)
    assert r["resume"]["anomalies"] == 1
    assert "sans sortie" in r["anomalies"][0]["motif"]


def test_lhistorique_sans_reference_a_son_propre_panier(ref):
    """Les 1 184 939 F deja saisis avant le mecanisme n'ont ni reference ni
    contrepartie. Sans ce panier, le premier ecran de rapprochement serait
    illisible."""
    d = pd.DataFrame(_piece("HIST-1", "TAM", "2026-01-10",
                            [("571100", 0, 50000, "CONTRIBUTION SIAO"),
                             (VF, 50000, 0, "CONTRIBUTION SIAO")]))
    d["modele"] = "libre"
    r = an.transferts_internes(None, ref, d)
    assert r["resume"]["sans_reference"] == 1
    assert r["sans_reference"][0]["centre_nom"] == "Tampouy"


def test_le_solde_du_compte_de_passage_est_le_filet(ref):
    """Le rapprochement par reference attrape les erreurs d'operation ; le
    solde global attrape ce qui lui a echappe."""
    d = pd.DataFrame(_sortie("PIS", "SIA", "TRF-1") + _entree("SIA", "PIS", "TRF-1"))
    assert an.transferts_internes(None, ref, d)["solde_compte_585000"] == 0
    d2 = pd.DataFrame(_sortie("PIS", "SIA", "TRF-1"))
    assert an.transferts_internes(None, ref, d2)["solde_compte_585000"] == 50000


# =============================================================================
# 4. Le verrou de cloture
# =============================================================================

def test_la_cloture_est_possible_quand_tout_est_solde(ref):
    d = pd.DataFrame(_sortie("PIS", "SIA", "TRF-1") + _entree("SIA", "PIS", "TRF-1"))
    assert an.transferts_non_soldes(ref, d)["cloture_possible"] is True


def test_la_cloture_est_bloquee_par_une_anomalie(ref):
    d = pd.DataFrame(_sortie("PIS", "SIA", "TRF-1", recul=60))
    etat = an.transferts_non_soldes(ref, d)
    assert etat["cloture_possible"] is False
    assert etat["anomalies"] == 1


# =============================================================================
# 5. Le libelle est libre, et n'entre jamais dans le rapprochement
# =============================================================================

def test_le_libelle_tape_par_le_caissier_est_conserve(ref):
    lignes = md.construire_lignes("transfert_interne", {
        "mon_centre": "TAM", "centre_donateur": "TAM", "centre_destinataire": "SIA",
        "montant": 50000, "libelle": "Contribution SIAO"}, "CP", ref)
    assert set(lignes["libelle"]) == {"CONTRIBUTION SIAO"}


def test_sans_libelle_un_libelle_par_defaut_est_compose(ref):
    lignes = md.construire_lignes("transfert_interne", {
        "mon_centre": "TAM", "centre_donateur": "TAM", "centre_destinataire": "SIA",
        "montant": 50000}, "CP", ref)
    assert set(lignes["libelle"]) == {"TRANSFERT TAM>SIA"}


def test_deux_libelles_differents_se_rapprochent_quand_meme(ref):
    """Tampouy ecrit "CONTRIBUTION SIAO", SIAO ecrit "APPROV SIAO" : c'est ce
    que montrent les brouillards reels. Le rapprochement travaille sur la
    reference et les centres, jamais sur le texte."""
    d = pd.DataFrame(_sortie("TAM", "SIA", "TRF-5", libelle="CONTRIBUTION SIAO")
                     + _entree("SIA", "TAM", "TRF-5", libelle="APPROV RECU DE TAMPOUY"))
    r = an.transferts_internes(None, ref, d)
    assert r["resume"]["soldes"] == 1


# =============================================================================
# 6. Les centres s'affichent en toutes lettres
# =============================================================================

def test_nom_centre_rend_le_nom_complet(ref):
    assert dl.nom_centre(ref, "SIA") == "SIAO"
    assert dl.nom_centre(ref, "PIS") == "Pissy"
    assert dl.nom_centre(ref, "INCONNU") == "INCONNU"


def test_les_classements_portent_le_nom_complet(ref, monkeypatch):
    d = pd.DataFrame(_activite("PIS") + _activite("SIA", 100000))
    monkeypatch.setattr(an.dl, "lire_ecritures", lambda *a, **k: d)
    mois = pd.Timestamp(_jour(5)).strftime("%Y%m")
    classement = an.classement_centres_recettes(mois, ref)
    assert "centre_nom" in classement.columns
    assert set(classement["centre_nom"]) >= {"Pissy", "SIAO", "Tampouy"}


def test_les_graphiques_etiquettent_en_toutes_lettres():
    import json
    import logic.graphiques as gr
    flux = "\n".join(json.dumps(x, indent=2) for x in [
        {"centre": "SIA", "centre_nom": "SIAO", "recettes": 100.0},
        {"centre": "PIS", "centre_nom": "Pissy", "recettes": 80.0}])
    assert gr.graphique_pour_outil("classement_centres_par_recettes", flux)

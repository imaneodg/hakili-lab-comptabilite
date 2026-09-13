# ---------------------------------------------------------------------------
# Tests de l'assistant IA, ancres sur la comptabilite REELLE de Hakili Lab.
#
# Pourquoi ce fichier existe (11/09/2026)
# ---------------------------------------
# tests/test_analyse.py decrit un plan comptable ideal : loyer en 622200,
# vacations en 632710, salaires en 422000. Aucune de ces trois imputations
# n'apparait dans les brouillards reels de Saaba et de Tampouy, ou tout est
# solde sur le collectif fournisseur 401000. Les treize tests de ce fichier
# passaient donc en validant le code contre l'hypothese qu'il faisait deja sur
# lui-meme, jamais contre la realite comptable de l'entreprise - ce qui
# explique que trois correctifs successifs (06/09, 10/09) aient porte sur le
# denominateur des pourcentages sans que personne ne voie que le numerateur
# etait vide.
#
# La fixture ci-dessous reprend donc les SCHEMAS D'ECRITURE reellement
# observes dans les quatre brouillards, un de chaque sorte :
#   - un encaissement d'eleve (571100 au debit, 411000 au credit, journal CP) ;
#   - un approvisionnement de la caisse menues depenses, en deux pieces
#     solidaires passant par le compte de virements de fonds 585000 ;
#   - un paiement de vacation regle directement par 401000 ;
#   - un paiement de loyer regle directement par 401000 ;
#   - un achat d'unites Cash Power impute a un vrai compte de charge ;
#   - un reglement fournisseur au libelle non reconnu ;
#   - trois encaissements identiques le meme jour au meme eleve ;
#   - une piece dont l'annee a ete saisie de travers.
#
# Aucun de ces tests n'ouvre de connexion Postgres : toutes les fonctions
# testees acceptent ref/d en parametres explicites.
# ---------------------------------------------------------------------------

import pandas as pd
import pytest

import logic.analyse as an
import logic.graphiques as gr

CENTRES = ["SAA", "TAM"]


def _ref():
    """Referentiel conforme a sql/seed.sql : memes natures, memes journaux,
    memes comptes de contrepartie que la base reelle."""
    comptes = pd.DataFrame([
        {"compte": "571100", "intitule": "Caisse principale (CP)", "nature": "tresorerie"},
        {"compte": "571200", "intitule": "Caisse menues depenses (CMD)", "nature": "tresorerie"},
        {"compte": "521100", "intitule": "Banques (CBI)", "nature": "tresorerie"},
        {"compte": "585000", "intitule": "Virements de fonds", "nature": "tresorerie"},
        {"compte": "411000", "intitule": "Clients (eleves et parents)", "nature": "tiers"},
        {"compte": "401000", "intitule": "Fournisseurs", "nature": "tiers"},
        {"compte": "422000", "intitule": "Personnel - remunerations", "nature": "tiers"},
        {"compte": "422300", "intitule": "Personnel - avances", "nature": "tiers"},
        {"compte": "632710", "intitule": "Honoraires et vacations", "nature": "charge"},
        {"compte": "622200", "intitule": "Location de batiment", "nature": "charge"},
        {"compte": "632720", "intitule": "Gardiennage bureau", "nature": "charge"},
        {"compte": "605100", "intitule": "Fournitures d'eau (ONEA)", "nature": "charge"},
        {"compte": "605200", "intitule": "Fournitures d'electricite", "nature": "charge"},
        {"compte": "605300", "intitule": "Carburant", "nature": "charge"},
        {"compte": "605500", "intitule": "Fournitures de bureau", "nature": "charge"},
        {"compte": "624330", "intitule": "Entretien et nettoyage", "nature": "charge"},
        {"compte": "628820", "intitule": "Frais d'internet", "nature": "charge"},
        {"compte": "471000", "intitule": "Compte d'attente", "nature": "bilan"},
    ])
    journaux = pd.DataFrame([
        {"journal": "CP", "intitule": "Caisse principale", "compte_contrepartie": "571100",
         "type": "tresorerie", "solde_ouverture": 0.0, "caisse_physique": "oui", "actif": "oui"},
        {"journal": "CMD", "intitule": "Caisse menues depenses", "compte_contrepartie": "571200",
         "type": "tresorerie", "solde_ouverture": 0.0, "caisse_physique": "oui", "actif": "oui"},
        {"journal": "Banque", "intitule": "CBI", "compte_contrepartie": "521100",
         "type": "tresorerie", "solde_ouverture": 0.0, "caisse_physique": "non", "actif": "oui"},
    ])
    centres = pd.DataFrame([{"code_centre": c, "intitule": c, "actif": "oui"} for c in CENTRES])
    tiers = pd.DataFrame([
        {"code_tiers": "411KAELY", "intitule": "BELEMTOUGRI KAELY"},
        {"code_tiers": "401RACHIDA", "intitule": "PALLO RASSIDATOU"},
        {"code_tiers": "401BAILLEURTPOUY", "intitule": "Bailleur Tampouy"},
        {"code_tiers": "401DIVERS", "intitule": "Fournisseur divers"},
    ])
    soldes_centre = pd.DataFrame([{"centre": c, "journal": j, "solde_ouverture": 0.0}
                                  for c in CENTRES for j in ("CP", "CMD")])
    return {"comptes": comptes, "journaux": journaux, "centres": centres,
            "tiers": tiers, "soldes_centre": soldes_centre}


def _piece(id_piece, centre, journal, date_piece, lignes, modele="libre"):
    """Une piece = plusieurs lignes equilibrees. `lignes` est une liste de
    (compte, debit, credit, code_tiers, libelle)."""
    return [{"id_piece": id_piece, "centre": centre, "journal": journal,
             "date_piece": date_piece, "compte": c, "debit": float(d), "credit": float(cr),
             "code_tiers": t, "libelle": lib, "modele": modele, "statut": "validee"}
            for c, d, cr, t, lib in lignes]


def _ecritures():
    lignes = []
    # --- encaissement d'un eleve : le tiers est du cote CREDIT --------------
    lignes += _piece("P-ENC-1", "SAA", "CP", "2026-03-03", [
        ("571100", 31500, 0, "", "FRAIS CA DAO BAGRE AQUIL WILLIAM/MARS"),
        ("411000", 0, 31500, "411KAELY", "FRAIS CA DAO BAGRE AQUIL WILLIAM/MARS")])
    # --- trois encaissements identiques le meme jour au meme eleve ----------
    for n in (1, 2, 3):
        lignes += _piece(f"P-DBL-{n}", "SAA", "CP", "2026-03-11", [
            ("571100", 20000, 0, "", "FRAIS CA BELEMTOUGRI KAELY/MARS"),
            ("411000", 0, 20000, "411KAELY", "FRAIS CA BELEMTOUGRI KAELY/MARS")])
    # --- approvisionnement de la CMD : deux pieces, via 585000 --------------
    lignes += _piece("P-APP-CP", "SAA", "CP", "2026-03-04", [
        ("571100", 0, 150000, "", "APPROV CMD"),
        ("585000", 150000, 0, "", "APPROV CMD")])
    lignes += _piece("P-APP-CMD", "SAA", "CMD", "2026-03-04", [
        ("571200", 150000, 0, "", "APPROV CMD"),
        ("585000", 0, 150000, "", "APPROV CMD")])
    # --- vacation reglee directement par le collectif fournisseur ----------
    lignes += _piece("P-VAC", "SAA", "CMD", "2026-03-05", [
        ("401000", 120000, 0, "401RACHIDA", "PAIEMENT VACATION/PALLO RASSIDATOU"),
        ("571200", 0, 120000, "", "PAIEMENT VACATION/PALLO RASSIDATOU")])
    # --- loyer regle directement par le collectif fournisseur --------------
    lignes += _piece("P-LOY", "SAA", "CMD", "2026-03-06", [
        ("401000", 125000, 0, "401BAILLEURTPOUY", "PAIEMENT LOYER FEVRIER"),
        ("571200", 0, 125000, "", "PAIEMENT LOYER FEVRIER")])
    # --- achat impute a un vrai compte de charge ---------------------------
    lignes += _piece("P-ELEC", "SAA", "CMD", "2026-03-07", [
        ("605200", 10150, 0, "", "ACHAT D'UNITES CASH POWER"),
        ("571200", 0, 10150, "", "ACHAT D'UNITES CASH POWER")])
    # --- reglement fournisseur au libelle non reconnu ----------------------
    lignes += _piece("P-DIV", "SAA", "CMD", "2026-03-16", [
        ("401000", 30000, 0, "401DIVERS", "INSTALLATION VENTILATEUR"),
        ("571200", 0, 30000, "", "INSTALLATION VENTILATEUR")])
    # --- piece dont l'annee a ete saisie de travers ------------------------
    lignes += _piece("P-DATE", "TAM", "CP", "2006-02-16", [
        ("571100", 0, 50000, "", "CONTRIBUTION SIAO"),
        ("401000", 50000, 0, "401DIVERS", "CONTRIBUTION SIAO")])
    # --- un mois anterieur, pour les moyennes et comparaisons --------------
    lignes += _piece("P-VAC-FEV", "SAA", "CMD", "2026-02-05", [
        ("401000", 100000, 0, "401RACHIDA", "PAIEMENT VACATION/PALLO RASSIDATOU"),
        ("571200", 0, 100000, "", "PAIEMENT VACATION/PALLO RASSIDATOU")])
    lignes += _piece("P-ENC-FEV", "SAA", "CP", "2026-02-03", [
        ("571100", 200000, 0, "", "FRAIS CA DIVERS/FEVRIER"),
        ("411000", 0, 200000, "411KAELY", "FRAIS CA DIVERS/FEVRIER")])
    return pd.DataFrame(lignes)


@pytest.fixture
def ref():
    return _ref()


@pytest.fixture
def d():
    return _ecritures()


# =============================================================================
# Transferts internes entre caisses
# =============================================================================

def test_approvisionnement_nest_ni_recette_ni_depense(ref, d):
    """Le defaut le plus couteux d'avant le 11/09/2026 : l'approvisionnement
    de la CMD comptait comme une recette du centre (entree dans la caisse
    d'arrivee) ET comme une depense (sortie de la caisse de depart). Sur les
    huit premiers mois de 2026, cela gonflait les recettes de 11,1 M F et les
    depenses de 12,3 M F."""
    recettes = an.recettes_centre_mois("SAA", "202603", ref, d)
    depenses = an.depenses_centre_mois("SAA", "202603", ref, d)
    # Encaissements reels : 31 500 + 3 x 20 000. Les 150 000 de
    # l'approvisionnement ne doivent apparaitre nulle part.
    assert recettes == 91500
    # Sorties reelles : 120 000 + 125 000 + 10 150 + 30 000.
    assert depenses == 285150


def test_le_filtre_ne_depend_pas_du_nom_du_modele(ref, d):
    """import_historique.py ecrit modele="libre" sur toutes les lignes reprises
    des brouillards : un filtre par nom de modele ne pouvait donc rien
    attraper. Le critere doit rester comptable."""
    assert (d["modele"] == "libre").all()
    transferts = an.pieces_transfert_interne(d, ref)
    assert transferts == {"P-APP-CP", "P-APP-CMD"}


def test_un_encaissement_simple_nest_jamais_pris_pour_un_transfert(ref, d):
    """Verification en sens inverse : le critere "deux comptes de tresorerie"
    ne doit pas mordre sur une piece ordinaire."""
    transferts = an.pieces_transfert_interne(d, ref)
    assert "P-ENC-1" not in transferts
    assert "P-VAC" not in transferts


# =============================================================================
# Reconstitution des charges reglees par le collectif fournisseur
# =============================================================================

def test_la_masse_salariale_voit_les_vacations_payees_par_401000(ref, d):
    """A Hakili Lab, la vacation est le mode de paiement dominant et passe par
    401000. Lue sur le compte brut, elle etait invisible : cet indicateur
    repondait 0 % sur des mois ou la masse salariale representait l'essentiel
    des sorties de caisse."""
    res = an.part_masse_salariale("202603", "SAA", ref, d)
    assert res["vacations"] == 120000
    assert res["masse_salariale"] == 120000
    # Total des charges du mois : 120 000 + 125 000 + 10 150 + 30 000.
    assert res["total_charges"] == 285150
    assert res["part_pct"] == pytest.approx(120000 / 285150 * 100)


def test_le_loyer_paye_par_401000_compte_dans_les_charges_fixes(ref, d):
    res = an.part_loyer_eau_electricite("202603", "SAA", ref, d)
    assert res["loyer_eau_electricite"] == 125000 + 10150
    assert res["total_charges"] == 285150


def test_le_poste_principal_est_la_vraie_premiere_depense(ref, d):
    """Avant correctif, seuls les comptes de nature 'charge' etaient vus : le
    poste principal de ce mois aurait ete l'electricite pour 10 150 F, alors
    que 120 000 F de vacations et 125 000 F de loyer avaient ete payes."""
    res = an.poste_depense_principal("202603", "SAA", ref, d)
    assert res["compte"] == "622200"
    assert res["montant"] == 125000


def test_un_reglement_au_libelle_inconnu_reste_visible(ref, d):
    """Le residu de la reconstitution ne doit jamais etre absorbe en silence :
    il compte dans le total, et il est listable tel quel."""
    res = an.charges_non_ventilees("202603", "SAA", ref, d)
    assert res["nombre_lignes"] == 1
    assert res["montant_total"] == 30000
    assert res["lignes"][0]["libelle"] == "INSTALLATION VENTILATEUR"


def test_pas_de_double_comptage_quand_la_facture_a_ete_comptabilisee(ref):
    """Quand une facture est passee au journal des achats (charge au debit,
    401000 au credit) puis reglee plus tard, la charge ne doit etre comptee
    qu'une fois - a la facture, pas au reglement."""
    lignes = []
    lignes += _piece("F-1", "SAA", "ACH", "2026-03-02", [
        ("632710", 80000, 0, "", "ETAT VACATION MARS"),
        ("401000", 0, 80000, "401RACHIDA", "ETAT VACATION MARS")])
    lignes += _piece("R-1", "SAA", "CMD", "2026-03-20", [
        ("401000", 80000, 0, "401RACHIDA", "PAIEMENT VACATION/PALLO RASSIDATOU"),
        ("571200", 0, 80000, "", "PAIEMENT VACATION/PALLO RASSIDATOU")])
    d2 = pd.DataFrame(lignes)
    res = an.part_masse_salariale("202603", "SAA", ref, d2)
    assert res["masse_salariale"] == 80000       # et non 160000
    assert res["total_charges"] == 80000


# =============================================================================
# Coherence entre outils
# =============================================================================

def test_repartition_recettes_se_rapproche_du_total(ref, d):
    """Deux outils ne doivent plus repondre deux chiffres differents a la meme
    question sans le signaler."""
    rep = an.repartition_recettes_mois("SAA", "202603", ref, d)
    total = an.recettes_centre_mois("SAA", "202603", ref, d)
    assert rep["total_recettes_encaissees"] == total
    assert rep["scolarite_encaissee"] + rep["autres_encaissements"] == total


# =============================================================================
# Doublons de saisie
# =============================================================================

def test_les_doublons_dencaissement_sont_detectes(ref, d):
    """L'ancienne version filtrait sur `debit > 0 et code_tiers non vide` :
    dans une piece de recette, la ligne qui porte le tiers est au CREDIT.
    Aucune recette ne franchissait le filtre, alors que c'est precisement le
    doublon de reglement d'eleve que le comptable cherche."""
    suspects = an.paiements_suspects("202603", d, ref)
    pieces = {s["id_piece"] for s in suspects}
    assert pieces == {"P-DBL-1", "P-DBL-2", "P-DBL-3"}
    assert all(s["sens"] == "encaissement" for s in suspects)
    assert all(s["montant"] == 20000 for s in suspects)


def test_les_transferts_ne_sont_pas_signales_comme_doublons(ref, d):
    """Approvisionner deux caisses du meme montant le meme jour est une
    routine, pas une anomalie."""
    suspects = an.paiements_suspects("202603", d, ref)
    assert not {s["id_piece"] for s in suspects} & {"P-APP-CP", "P-APP-CMD"}


# =============================================================================
# Qualite des dates
# =============================================================================

def test_une_ecriture_mal_datee_est_signalee(d):
    res = an.ecritures_date_douteuse(None, 2024, d)
    assert res["nombre_pieces"] == 1
    assert res["lignes"][0]["id_piece"] == "P-DATE"


def test_une_ecriture_bien_datee_ne_lest_pas(d):
    res = an.ecritures_date_douteuse("SAA", 2024, d)
    assert res["nombre_pieces"] == 0


# =============================================================================
# Periodes libres et annee academique
# =============================================================================

def test_resultat_periode_borne_bien_les_dates(ref, d, monkeypatch):
    monkeypatch.setattr(an.dl, "lire_ecritures", lambda *a, **k: d)
    res = an.resultat_periode("2026-03-01", "2026-03-31", "SAA", ref)
    assert res["recettes"] == 91500
    assert res["depenses"] == 285150
    assert res["resultat_net"] == 91500 - 285150
    assert [l["mois"] for l in res["detail_mensuel"]] == ["202603"]


def test_resultat_periode_accepte_des_dates_inversees(ref, d, monkeypatch):
    monkeypatch.setattr(an.dl, "lire_ecritures", lambda *a, **k: d)
    a_l_endroit = an.resultat_periode("2026-02-01", "2026-03-31", "SAA", ref)
    a_l_envers = an.resultat_periode("2026-03-31", "2026-02-01", "SAA", ref)
    assert a_l_endroit["recettes"] == a_l_envers["recettes"]


def test_annee_academique_bascule_en_septembre():
    assert an.annee_academique_de("2026-08-31")["libelle"] == "2025-2026"
    assert an.annee_academique_de("2026-09-01")["libelle"] == "2026-2027"
    assert an.annee_academique_de("2026-09-01")["date_debut"] == "2026-09-01"
    assert an.annee_academique_de("2026-08-31")["date_fin"] == "2026-08-31"


# =============================================================================
# Chaine des graphiques
# =============================================================================

def test_un_resultat_mcp_arrive_en_chaine_json_et_doit_etre_decode():
    """Le defaut qui empechait TOUT graphique de s'afficher : servi par MCP, un
    outil ne renvoie pas un dict a l'application mais une chaine JSON."""
    valeur = '{"mois": "202603", "recettes": 1691000.0, "depenses": 1406098.0}'
    assert gr.valeur_outil(valeur) == {"mois": "202603", "recettes": 1691000.0,
                                       "depenses": 1406098.0}


def test_une_liste_mcp_arrive_en_objets_colles_bout_a_bout():
    """Second piege : un outil qui renvoie une liste produit un fragment de
    texte PAR ELEMENT, que chatlas recolle avec des sauts de ligne. Le
    resultat n'est pas un document JSON valide, et comme il est indente, un
    decoupage ligne par ligne ne marche pas non plus."""
    flux = ('{\n  "mois": "202603",\n  "recettes": 1.0\n}\n'
            '{\n  "mois": "202604",\n  "recettes": 2.0\n}')
    decode = gr.valeur_outil(flux)
    assert isinstance(decode, list) and len(decode) == 2
    assert [l["mois"] for l in decode] == ["202603", "202604"]


def test_chaque_outil_avec_graphique_trace_depuis_une_chaine_json():
    """Garde-fou principal : le pipeline complet, avec la valeur telle que
    l'application la recoit reellement."""
    import json
    cas = {
        "evolution_six_mois": [{"mois": "202603", "recettes": 10.0, "depenses": 5.0},
                                {"mois": "202604", "recettes": 12.0, "depenses": 6.0}],
        "evolution_resultat_par_centre": [
            {"mois": "202603", "centre": "SAA", "resultat_net": 5.0},
            {"mois": "202603", "centre": "TAM", "resultat_net": 7.0}],
        "classement_centres_par_recettes": [{"centre": "SAA", "recettes": 10.0}],
        "classement_centres_par_recettes_trimestre": [{"centre": "SAA", "recettes_trimestre": 30.0}],
        "classement_rentabilite": [{"centre": "SAA", "marge_pct": 12.0}],
        "classement_structure_couts": [{"centre": "SAA", "ratio_couts_pct": 88.0}],
        "contribution_centres": [{"centre": "SAA", "part_pct": 60.0},
                                  {"centre": "TAM", "part_pct": 40.0}],
        "repartition_recettes": {"scolarite_encaissee": 8.0, "prestations_facturees": 2.0},
        "effectif_actif_evolution": [{"mois": "202603", "effectif_proxy": 20},
                                      {"mois": "202604", "effectif_proxy": 22}],
        "resultat_periode": {"date_debut": "2026-01-01", "date_fin": "2026-03-31",
                              "detail_mensuel": [{"mois": "202601", "recettes": 1.0, "depenses": 2.0},
                                                 {"mois": "202602", "recettes": 3.0, "depenses": 1.0}]},
        "resultat_annee_academique": {"annee_academique": "2025-2026", "recettes": 10.0,
                                       "depenses": 8.0, "annee_academique_precedente": "2024-2025",
                                       "recettes_annee_precedente": 9.0,
                                       "depenses_annee_precedente": 7.0},
    }
    assert set(cas) == set(gr.OUTILS_AVEC_GRAPHIQUE), (
        "Tout outil declare dans OUTILS_AVEC_GRAPHIQUE doit avoir un cas de test ici.")
    for nom, valeur in cas.items():
        if isinstance(valeur, list):
            flux = "\n".join(json.dumps(x, indent=2) for x in valeur)   # exactement MCP + chatlas
        else:
            flux = json.dumps(valeur, indent=2)
        image = gr.graphique_pour_outil(nom, flux)
        assert image, f"aucun graphique produit pour {nom}"
        assert image.startswith("iVBOR"), f"{nom} n'a pas produit un PNG"


def test_une_reponse_indisponible_ne_produit_pas_de_graphique():
    flux = '{"disponible": false, "message": "pas d\'echeancier par eleve"}'
    assert gr.graphique_pour_outil("repartition_recettes", flux) is None


def test_un_outil_sans_graphique_ne_plante_pas():
    assert gr.graphique_pour_outil("part_masse_salariale", '{"part_pct": 12}') is None
    assert gr.graphique_pour_outil("evolution_six_mois", "pas du json") is None
    assert gr.graphique_pour_outil("evolution_six_mois", "") is None
    assert gr.graphique_pour_outil("evolution_six_mois", None) is None


# =============================================================================
# Cloisonnement par centre
# =============================================================================

def test_la_portee_par_defaut_ne_restreint_rien(monkeypatch):
    from mcp_server import portee
    monkeypatch.delenv(portee.VARIABLE_ENVIRONNEMENT, raising=False)
    assert portee.resoudre("SAA") == "SAA"
    assert portee.resoudre(None) is None
    assert portee.restreindre_centres(CENTRES) == CENTRES


def test_une_session_limitee_ne_peut_pas_interroger_un_autre_centre(monkeypatch):
    from mcp_server import portee
    monkeypatch.setenv(portee.VARIABLE_ENVIRONNEMENT, "TAM")
    assert portee.resoudre(None) == "TAM"
    assert portee.resoudre("TAM") == "TAM"
    with pytest.raises(portee.PorteeRefusee):
        portee.resoudre("SAA")
    assert portee.restreindre_centres(CENTRES) == ["TAM"]

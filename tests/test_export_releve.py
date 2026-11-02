# ---------------------------------------------------------------------------
# Tests de l'export Excel du releve de caisse (logic/export_releve.py),
# ajoutes le 31/10/2026.
#
# Meme approche que tests/test_soldes_centre.py : toutes les fonctions
# testees ici acceptent ref/d en parametres explicites, aucun test n'ouvre
# de connexion Postgres (la seule requete du module, _maj_solde_officiel,
# est court-circuitee par le parametre maj_solde_officiel).
#
# Pieces datees en 2098-2099, jamais melees aux vraies donnees.
#
# Fichier volontairement autonome (fixtures dupliquees plutot
# qu'importees) : la fonctionnalite doit pouvoir etre retiree en supprimant
# ce fichier, sans qu'aucune autre suite n'en depende.
#
#   pytest tests/test_export_releve.py -v
# ---------------------------------------------------------------------------

import io
from datetime import date, datetime

import pandas as pd
from openpyxl import load_workbook

import logic.donnees as dl
import logic.export_releve as er

MAJ = datetime(2098, 9, 30, 8, 30)


def _ref(soldes_centre=None, solde_banque=0.0):
    comptes = pd.DataFrame([
        {"compte": "571100", "intitule": "Caisse principale", "nature": "tresorerie"},
        {"compte": "571200", "intitule": "Caisse menues depenses", "nature": "tresorerie"},
        {"compte": "521200", "intitule": "Banques (CBI)", "nature": "tresorerie"},
        {"compte": "601000", "intitule": "Achats", "nature": "charge"},
    ])
    journaux = pd.DataFrame([
        {"journal": "CP", "compte_contrepartie": "571100", "type": "tresorerie",
         "prefixe_piece": "CP", "solde_ouverture": 0.0, "caisse_physique": "oui", "actif": "oui"},
        {"journal": "CMD", "compte_contrepartie": "571200", "type": "tresorerie",
         "prefixe_piece": "CMD", "solde_ouverture": 0.0, "caisse_physique": "oui", "actif": "oui"},
        {"journal": "Banque", "compte_contrepartie": "521200", "type": "tresorerie",
         "prefixe_piece": "CBI", "solde_ouverture": solde_banque, "caisse_physique": "non",
         "actif": "oui"},
    ])
    centres = pd.DataFrame([{"code_centre": "SAA", "intitule": "Saaba"},
                            {"code_centre": "TAM", "intitule": "Tampouy"}])
    if soldes_centre is None:
        soldes_centre = pd.DataFrame(columns=["centre", "journal", "solde_ouverture"])
    return {"comptes": comptes, "journaux": journaux, "centres": centres,
            "tiers": pd.DataFrame(columns=["code_tiers", "intitule"]),
            "soldes_centre": soldes_centre}


def _ligne(centre, compte, date_piece, debit=0, credit=0, journal="CP", id_piece="P1",
           statut="validee", libelle="TEST", num_definitif="", num_provisoire="PROV"):
    return {"centre": centre, "compte": compte, "journal": journal, "debit": float(debit),
            "credit": float(credit), "date_piece": date_piece, "code_tiers": "", "modele": "",
            "id_piece": id_piece, "statut": statut, "num_definitif": num_definitif,
            "num_provisoire": num_provisoire, "libelle": libelle}


def _soldes(**paires):
    """_soldes(SAA=20000) -> table soldes_ouverture_centre pour le journal CP."""
    return pd.DataFrame([{"centre": c, "journal": "CP", "solde_ouverture": float(v)}
                         for c, v in paires.items()])


# --- 1. Equivalence stricte avec solde_caisse() ----------------------------

def test_total_du_releve_egale_solde_caisse_sur_tout_l_historique():
    """Exigence centrale : sur une periode couvrant tout l'historique, le
    dernier solde cumule du releve doit etre EXACTEMENT le solde affiche par
    l'application (dl.solde_caisse), sans reinventer le calcul."""
    ref = _ref(_soldes(SAA=20000))
    d = pd.DataFrame([
        _ligne("SAA", "571100", "2098-10-02", debit=50000, id_piece="P1"),
        _ligne("SAA", "571100", "2098-10-05", credit=12000, id_piece="P2"),
        _ligne("SAA", "571100", "2098-10-20", credit=8000, id_piece="P3"),
        _ligne("SAA", "601000", "2098-10-20", debit=8000, id_piece="P3"),
    ])
    releve = er.calculer_releve("CP", ref, date(2098, 1, 1), date(2099, 12, 31), d=d,
                                centre="SAA", maj_solde_officiel=MAJ)
    total = releve["point_depart"] + sum(l["debit"] - l["credit"] for l in releve["lignes"])
    assert total == dl.solde_caisse("CP", ref, d, centre="SAA")
    assert total == 50000.0


def test_equivalence_aussi_pour_la_banque_compte_partage():
    ref = _ref(solde_banque=100000.0)
    d = pd.DataFrame([
        _ligne("SAA", "521200", "2098-11-03", debit=30000, journal="Banque", id_piece="B1"),
        _ligne("TAM", "521200", "2098-11-04", credit=5000, journal="Banque", id_piece="B2"),
    ])
    # Un centre passe pour la banque est ignore, comme dans solde_caisse().
    releve = er.calculer_releve("Banque", ref, date(2098, 1, 1), date(2099, 12, 31), d=d,
                                centre="SAA", maj_solde_officiel=MAJ)
    total = releve["point_depart"] + sum(l["debit"] - l["credit"] for l in releve["lignes"])
    assert total == dl.solde_caisse("Banque", ref, d, centre="SAA") == 125000.0
    assert releve["centre"] is None
    assert len(releve["lignes"]) == 2  # les deux centres, un seul compte partage


# --- 2. Point de depart : solde officiel + mouvements anterieurs -----------

def test_point_de_depart_inclut_les_mouvements_avant_la_periode():
    """Ouverture officielle a 20 000, mouvements d'octobre, export du 19 au
    31/10 : la ligne de depart doit porter le solde calcule au 18/10 au soir,
    pas le solde officiel brut."""
    ref = _ref(_soldes(SAA=20000))
    d = pd.DataFrame([
        _ligne("SAA", "571100", "2098-10-02", debit=50000, id_piece="P1"),
        _ligne("SAA", "571100", "2098-10-18", credit=10000, id_piece="P2"),
        _ligne("SAA", "571100", "2098-10-25", credit=4000, id_piece="P3"),
    ])
    releve = er.calculer_releve("CP", ref, date(2098, 10, 19), date(2098, 10, 31), d=d,
                                centre="SAA", maj_solde_officiel=MAJ)
    assert releve["point_depart"] == 60000.0          # 20 000 + 50 000 - 10 000
    assert releve["date_point_depart"] == date(2098, 10, 18)
    assert [l["date"] for l in releve["lignes"]] == [date(2098, 10, 25)]


def test_point_de_depart_vaut_le_solde_officiel_si_aucun_mouvement_avant():
    ref = _ref(_soldes(SAA=20000))
    d = pd.DataFrame([_ligne("SAA", "571100", "2098-10-25", credit=4000)])
    releve = er.calculer_releve("CP", ref, date(2098, 10, 1), date(2098, 10, 31), d=d,
                                centre="SAA", maj_solde_officiel=MAJ)
    assert releve["point_depart"] == 20000.0


def test_releve_sans_aucune_ecriture_reste_coherent():
    ref = _ref(_soldes(SAA=7500))
    d = pd.DataFrame(columns=["centre", "compte", "journal", "debit", "credit", "date_piece",
                              "id_piece", "statut", "num_definitif", "num_provisoire", "libelle"])
    releve = er.calculer_releve("CP", ref, date(2098, 10, 1), date(2098, 10, 31), d=d,
                                centre="SAA", maj_solde_officiel=MAJ)
    assert releve["point_depart"] == 7500.0
    assert releve["lignes"] == []


# --- 3. Aucun filtre de statut dans le calcul ------------------------------

def test_toutes_les_pieces_quel_que_soit_leur_statut():
    """Une piece "saisie" ou "a_corriger" est deja de l'argent qui a bouge :
    l'exclure fausserait le solde reel de la caisse."""
    ref = _ref(_soldes(SAA=0))
    d = pd.DataFrame([
        _ligne("SAA", "571100", "2098-10-02", debit=10000, id_piece="P1", statut="saisie"),
        _ligne("SAA", "571100", "2098-10-03", debit=1000, id_piece="P2", statut="validee"),
        _ligne("SAA", "571100", "2098-10-04", credit=500, id_piece="P3", statut="exportee"),
        _ligne("SAA", "571100", "2098-10-05", credit=200, id_piece="P4", statut="a_corriger"),
    ])
    releve = er.calculer_releve("CP", ref, date(2098, 10, 1), date(2098, 10, 31), d=d,
                                centre="SAA", maj_solde_officiel=MAJ)
    assert len(releve["lignes"]) == 4
    assert [l["statut"] for l in releve["lignes"]] == ["Saisie", "Validée", "Exportée", "À corriger"]
    total = releve["point_depart"] + sum(l["debit"] - l["credit"] for l in releve["lignes"])
    assert total == dl.solde_caisse("CP", ref, d, centre="SAA") == 10300.0


# --- 4. Isolation par centre ----------------------------------------------

def test_un_centre_ne_voit_jamais_les_mouvements_d_un_autre():
    ref = _ref(_soldes(SAA=20000, TAM=5000))
    d = pd.DataFrame([
        _ligne("SAA", "571100", "2098-10-02", debit=10000, id_piece="P1"),
        _ligne("TAM", "571100", "2098-10-02", credit=3000, id_piece="P2"),
    ])
    saa = er.calculer_releve("CP", ref, date(2098, 10, 1), date(2098, 10, 31), d=d,
                             centre="SAA", maj_solde_officiel=MAJ)
    tam = er.calculer_releve("CP", ref, date(2098, 10, 1), date(2098, 10, 31), d=d,
                             centre="TAM", maj_solde_officiel=MAJ)
    assert len(saa["lignes"]) == len(tam["lignes"]) == 1
    assert saa["point_depart"] == 20000.0 and tam["point_depart"] == 5000.0
    assert saa["point_depart"] + 10000 == dl.solde_caisse("CP", ref, d, centre="SAA")
    assert tam["point_depart"] - 3000 == dl.solde_caisse("CP", ref, d, centre="TAM")


# --- 5. Contenu des lignes ------------------------------------------------

def test_lignes_triees_par_date_puis_piece_et_numero_definitif_prioritaire():
    ref = _ref(_soldes(SAA=0))
    d = pd.DataFrame([
        _ligne("SAA", "571100", "2098-10-10", debit=1, id_piece="P9", num_definitif="CP9810002"),
        _ligne("SAA", "571100", "2098-10-02", debit=2, id_piece="P2", num_definitif=""),
        _ligne("SAA", "571100", "2098-10-10", debit=3, id_piece="P1", num_definitif="CP9810001"),
    ])
    releve = er.calculer_releve("CP", ref, date(2098, 10, 1), date(2098, 10, 31), d=d,
                                centre="SAA", maj_solde_officiel=MAJ)
    assert [l["date"] for l in releve["lignes"]] == [date(2098, 10, 2), date(2098, 10, 10),
                                                      date(2098, 10, 10)]
    # Numero definitif quand il existe, numero provisoire sinon (dl.ou).
    assert [l["piece"] for l in releve["lignes"]] == ["PROV", "CP9810001", "CP9810002"]


def test_seules_les_lignes_du_compte_de_tresorerie_du_journal():
    """Une piece a plusieurs lignes ; seule celle qui touche le compte caisse
    du journal est un mouvement de caisse."""
    ref = _ref(_soldes(SAA=0))
    d = pd.DataFrame([
        _ligne("SAA", "571100", "2098-10-02", credit=8000, id_piece="P1", libelle="ACHAT CRAIES"),
        _ligne("SAA", "601000", "2098-10-02", debit=8000, id_piece="P1", libelle="ACHAT CRAIES"),
        _ligne("SAA", "571200", "2098-10-02", credit=500, id_piece="P2", journal="CMD"),
    ])
    releve = er.calculer_releve("CP", ref, date(2098, 10, 1), date(2098, 10, 31), d=d,
                                centre="SAA", maj_solde_officiel=MAJ)
    assert len(releve["lignes"]) == 1
    assert releve["lignes"][0]["credit"] == 8000.0
    assert releve["lignes"][0]["libelle"] == "ACHAT CRAIES"


# --- 6. Fichier Excel ------------------------------------------------------

def _classeur(releve, titre="Relevé de test"):
    return load_workbook(io.BytesIO(er.construire_fichier(releve, titre)))


def _releve_exemple():
    ref = _ref(_soldes(SAA=20000))
    d = pd.DataFrame([
        _ligne("SAA", "571100", "2098-10-20", debit=5000, id_piece="P1", libelle="APPROV"),
        _ligne("SAA", "571100", "2098-10-21", credit=40000, id_piece="P2", libelle="SALAIRES"),
    ])
    return er.calculer_releve("CP", ref, date(2098, 10, 19), date(2098, 10, 31), d=d,
                              centre="SAA", maj_solde_officiel=MAJ)


def test_fichier_structure_colonnes_et_ligne_de_depart():
    ws = _classeur(_releve_exemple()).active
    assert [ws.cell(row=4, column=c).value for c in range(1, 8)] == \
        ["DATE", "PIÈCE", "LIBELLÉ", "STATUT", "DEBIT", "CREDIT", "SOLDE"]
    # Ligne de depart : jamais "solde d'ouverture" tout court, pour ne pas la
    # confondre avec le solde officiel de soldes_ouverture_centre. Elle est
    # juste sous les en-tetes et juste au-dessus de la premiere piece : c'est
    # l'ancre de la chaine de formules.
    depart = ws.cell(row=5, column=1).value
    assert depart.startswith("SOLDE CALCULÉ AU 18/10/2098")
    assert "avant la période affichée" in depart
    assert "ouverture" not in depart.lower()
    assert ws.cell(row=5, column=7).value == 20000.0
    # Date de derniere mise a jour du solde officiel, en sous-titre.
    assert "30/09/2098" in ws.cell(row=2, column=1).value


def test_colonne_solde_est_une_formule_jamais_une_valeur_figee():
    ws = _classeur(_releve_exemple()).active
    # La premiere formule pointe sur la ligne de depart (G5), jamais sur
    # l'en-tete : une reference a l'en-tete donnerait #VALEUR! dans Excel.
    assert ws.cell(row=6, column=7).value == "=G5+E6-F6"
    assert ws.cell(row=7, column=7).value == "=G6+E7-F7"
    # La ligne de depart, elle, porte bien une valeur (ancre de la chaine).
    assert isinstance(ws.cell(row=5, column=7).value, (int, float))
    # Et la cellule juste au-dessus est bien l'en-tete, pas une autre formule.
    assert ws.cell(row=4, column=7).value == "SOLDE"


def test_mise_en_forme_conditionnelle_sur_les_soldes_negatifs():
    """Le solde devient negatif en ligne 7 (20 000 + 5 000 - 40 000) : la
    coloration passe par une regle conditionnelle, pas une couleur figee,
    pour rester juste si le comptable insere une ligne oubliee."""
    ws = _classeur(_releve_exemple()).active
    regles = [(str(cf.sqref), r) for cf in ws.conditional_formatting for r in cf.rules]
    assert regles, "aucune mise en forme conditionnelle sur la colonne SOLDE"
    plage, regle = regles[0]
    assert plage.startswith("G6")   # premiere ligne du tableau
    assert regle.operator == "lessThan" and regle.formula == ["0"]
    # Couleur de fond lue par Excel dans un dxf : bgColor (end_color).
    assert regle.dxf.fill.bgColor.rgb == "FFF8CBAD"


def test_entetes_et_valeurs_des_lignes_du_tableau():
    ws = _classeur(_releve_exemple()).active
    assert ws.cell(row=6, column=1).value.date() == date(2098, 10, 20)
    assert ws.cell(row=6, column=3).value == "APPROV"
    assert ws.cell(row=6, column=4).value == "Validée"
    assert ws.cell(row=6, column=5).value == 5000.0
    assert ws.cell(row=7, column=6).value == 40000.0
    # Montant nul : cellule vide, comme sur le brouillard papier (et une
    # cellule vide vaut zero dans la formule de la colonne SOLDE).
    assert ws.cell(row=6, column=6).value is None
    assert ws.cell(row=7, column=5).value is None


def test_excel_recalcule_a_l_ouverture():
    """Sans cela, Excel affiche une colonne SOLDE VIDE : openpyxl n'ecrit
    aucun resultat en cache et Excel ne recalcule pas de lui-meme un fichier
    produit par un autre programme (constate le 31/10/2026 sur le premier
    fichier d'exemple)."""
    wb = _classeur(_releve_exemple())
    assert wb.calculation.fullCalcOnLoad is True


def test_mise_en_page_impression_sur_une_seule_largeur():
    ws = _classeur(_releve_exemple()).active
    assert ws.page_setup.orientation == "landscape"
    assert ws.page_setup.fitToWidth == 1
    assert ws.print_title_rows == "$4:$4"    # en-tetes repetes a chaque page


def test_fichier_de_refus_ne_contient_aucun_chiffre():
    """Journal "Tous", centre non choisi, banque demandee par un role
    local... : le fichier ne doit porter que l'explication, jamais une ligne
    "SOLDE CALCULÉ AU ..." a zero qui se prendrait pour un solde."""
    ws = load_workbook(io.BytesIO(
        er.construire_fichier_message("Le relevé de la banque est réservé au comptable."))).active
    assert ws.cell(row=1, column=1).value == "Relevé non généré"
    assert ws.cell(row=2, column=1).value == "Le relevé de la banque est réservé au comptable."
    textes = [c.value for ligne in ws.iter_rows() for c in ligne if c.value is not None]
    assert not any(isinstance(v, (int, float)) for v in textes)
    assert not any("SOLDE CALCULÉ" in str(v) for v in textes)


def test_fichier_sans_aucune_ligne_reste_ouvrable():
    ref = _ref(_soldes(SAA=1000))
    d = pd.DataFrame(columns=["centre", "compte", "journal", "debit", "credit", "date_piece",
                              "id_piece", "statut", "num_definitif", "num_provisoire", "libelle"])
    releve = er.calculer_releve("CP", ref, date(2098, 10, 1), date(2098, 10, 31), d=d,
                                centre="SAA", maj_solde_officiel=MAJ)
    ws = _classeur(releve).active
    assert ws.cell(row=5, column=7).value == 1000.0
    assert ws.cell(row=6, column=1).value is None

# ---------------------------------------------------------------------------
# logic/export_releve.py
#
# Export Excel du releve de caisse (onglet Brouillard), demande le
# 31/10/2026 : le comptable veut pouvoir comparer son brouillard papier
# ligne par ligne a un relevé genere par l'appli, au lieu de ne voir qu'un
# solde global unique.
#
# MODULE ISOLE, par choix explicite (reversibilite) :
#   - importe logic.donnees en LECTURE SEULE (lire_ecritures,
#     _solde_ouverture_journal, est_caisse_physique, _lire_df, ou) ;
#   - n'est importe par AUCUNE fonction existante de logic/donnees.py ou
#     app.py au-dela du bloc d'export lui-meme ;
#   - ne cree aucune table, aucune colonne, aucun etat partage.
# Retirer cette fonctionnalite = supprimer ce fichier, tests/test_export_releve.py,
# et le bloc "DEBUT/FIN export releve Excel" dans app.py.
#
# Le calcul ci-dessous DUPLIQUE volontairement celui de
# logic.donnees.solde_caisse() (meme solde d'ouverture, meme compte de
# contrepartie, meme absence de filtre de statut - une piece "saisie" est
# deja de l'argent qui a physiquement bouge) plutot que de le reutiliser,
# pour pouvoir l'arreter a la veille du debut de periode au lieu de tout
# l'historique. Voir tests/test_export_releve.py pour la preuve que, sur
# une periode couvrant tout l'historique, les deux calculs donnent
# exactement le meme solde final.
# ---------------------------------------------------------------------------

import io
from datetime import datetime, timedelta

import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import logic.donnees as dl

# Libelles humains pour la colonne STATUT - informatifs seulement, cette
# colonne ne filtre rien dans le calcul du solde cumule (voir calculer_releve).
STATUT_LABEL = {"saisie": "Saisie", "validee": "Validée",
                "exportee": "Exportée", "a_corriger": "À corriger"}

COLONNES_TABLE = ["DATE", "PIÈCE", "LIBELLÉ", "STATUT", "DEBIT", "CREDIT", "SOLDE"]

# Marge de lignes supplementaires mises en forme sous le tableau, pour que
# la regle "solde negatif -> rouge" s'applique aussi si le comptable insere
# des lignes a la main plus bas (meme esprit que son brouillard papier).
MARGE_LIGNES_SUPPLEMENTAIRES = 500


def _compte_contrepartie(ref, journal):
    j = ref["journaux"]
    val = j.loc[j["journal"] == journal, "compte_contrepartie"]
    return val.iloc[0] if len(val) else None


def _maj_solde_officiel(journal, centre_effectif, physique):
    """Date de derniere mise a jour du solde d'ouverture officiel - lecture
    seule, hors de ref() qui ne la conserve pas (lire_referentiel() la
    retire volontairement de ce qui est garde en memoire de session)."""
    if physique:
        df = dl._lire_df(
            "SELECT updated_at FROM soldes_ouverture_centre WHERE centre = %s AND journal = %s",
            params=(centre_effectif, journal))
    else:
        df = dl._lire_df("SELECT updated_at FROM journaux WHERE journal = %s", params=(journal,))
    if len(df) == 0 or pd.isna(df["updated_at"].iloc[0]):
        return None
    return df["updated_at"].iloc[0]


def calculer_releve(journal, ref, debut, fin, d=None, centre=None, maj_solde_officiel=None):
    """Point de depart (solde calcule a la veille de `debut`) + lignes du
    relevé entre `debut` et `fin` inclus, pour journal/centre donnes.

    `d`, comme pour dl.solde_caisse(), permet de passer un jeu d'ecritures
    construit en test au lieu d'interroger Postgres - aucun test de
    tests/test_export_releve.py n'ouvre de connexion.
    `maj_solde_officiel`, de la meme facon, permet aux tests d'eviter
    l'unique requete de ce module qui, elle, touche la base
    (_maj_solde_officiel) ; en production (app.py) elle est toujours
    recalculee a la demande.
    """
    physique = dl.est_caisse_physique(ref, journal)
    centre_effectif = centre if physique else None
    cc = _compte_contrepartie(ref, journal)
    ouverture = dl._solde_ouverture_journal(ref, journal, centre_effectif)

    if d is None:
        d = dl.lire_ecritures(centre=centre_effectif)
    if centre_effectif is not None and len(d):
        d = d[d["centre"] == centre_effectif]
    if len(d):
        d = d[d["compte"] == cc].copy()
        d["_date"] = pd.to_datetime(d["date_piece"]).dt.date
    else:
        d = d.assign(_date=pd.Series(dtype="object"))

    veille = debut - timedelta(days=1)
    avant = d[d["_date"] <= veille] if len(d) else d
    point_depart = ouverture + (float(avant["debit"].sum() - avant["credit"].sum()) if len(avant) else 0.0)

    periode = d[(d["_date"] >= debut) & (d["_date"] <= fin)] if len(d) else d
    periode = periode.sort_values(["date_piece", "id_piece"], kind="mergesort")

    if maj_solde_officiel is None:
        maj_solde_officiel = _maj_solde_officiel(journal, centre_effectif, physique)

    lignes = []
    for _, row in periode.iterrows():
        date_piece = row["date_piece"]
        date_obj = date_piece if hasattr(date_piece, "strftime") else datetime.strptime(str(date_piece), "%Y-%m-%d").date()
        lignes.append({
            "date": date_obj,
            "piece": dl.ou(row["num_definitif"], row["num_provisoire"]),
            "libelle": row["libelle"],
            "statut": STATUT_LABEL.get(row["statut"], row["statut"]),
            "debit": float(row["debit"] or 0),
            "credit": float(row["credit"] or 0),
        })

    return {
        "journal": journal,
        "centre": centre_effectif,
        "debut": debut,
        "fin": fin,
        "point_depart": point_depart,
        "date_point_depart": veille,
        "maj_solde_officiel": maj_solde_officiel,
        "lignes": lignes,
    }


def construire_fichier(releve, titre_contexte):
    """Construit le classeur Excel a partir du resultat de calculer_releve().
    SOLDE est toujours une vraie formule Excel (=precedente+DEBIT-CREDIT),
    jamais une valeur figee, pour qu'une ligne inseree a la main par le
    comptable recalcule tout ce qui suit - exactement comme son brouillard
    papier. Renvoie les octets du fichier .xlsx."""
    wb = Workbook()
    # openpyxl ecrit les formules SANS resultat en cache. Excel, a l'ouverture
    # d'un fichier produit par un autre programme, n'affiche alors rien dans
    # ces cellules tant qu'il n'a pas recalcule - la colonne SOLDE apparaitrait
    # vide (LibreOffice, lui, recalcule toujours : le defaut ne se voit pas
    # dans un controle fait avec lui). fullCalcOnLoad demande explicitement a
    # Excel de tout recalculer a l'ouverture ; c'est ce qui rend la colonne
    # SOLDE lisible des le premier affichage.
    wb.calculation.fullCalcOnLoad = True
    ws = wb.active
    ws.title = "Relevé"

    gras = Font(bold=True)

    ws.cell(row=1, column=1, value=titre_contexte).font = Font(bold=True, size=13)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=7)

    maj = releve["maj_solde_officiel"]
    if maj is not None:
        sous_titre = f"Solde d'ouverture officiel mis à jour le {maj:%d/%m/%Y à %H:%M}."
    else:
        sous_titre = "Solde d'ouverture officiel : date de mise à jour inconnue."
    ws.cell(row=2, column=1, value=sous_titre).font = Font(italic=True, size=9, color="666666")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=7)

    ligne_entetes = 4
    for col, titre in enumerate(COLONNES_TABLE, start=1):
        c = ws.cell(row=ligne_entetes, column=col, value=titre)
        c.font = gras
        c.fill = PatternFill("solid", fgColor="E8E8E8")
        c.alignment = Alignment(horizontal="center")

    # Point de depart : premiere ligne du tableau, juste sous les en-tetes et
    # juste au-dessus de la premiere piece - c'est l'ancre de la chaine de
    # formules, qui doit donc etre la ligne immediatement precedente (sinon
    # la premiere formule pointerait sur l'en-tete "SOLDE", du texte).
    # Intitule "SOLDE CALCULÉ AU ..." et jamais "solde d'ouverture" : cette
    # valeur est calculee (solde officiel + mouvements anterieurs a la
    # periode), elle ne doit jamais etre confondue avec le solde officiel de
    # soldes_ouverture_centre / journaux.
    ligne_depart = ligne_entetes + 1
    libelle_depart = (f"SOLDE CALCULÉ AU {releve['date_point_depart']:%d/%m/%Y} "
                       "(avant la période affichée)")
    ws.cell(row=ligne_depart, column=1, value=libelle_depart).font = gras
    ws.merge_cells(start_row=ligne_depart, start_column=1, end_row=ligne_depart, end_column=6)
    solde_depart_cell = ws.cell(row=ligne_depart, column=7, value=round(releve["point_depart"], 2))
    solde_depart_cell.font = gras
    solde_depart_cell.number_format = "#,##0"

    premiere_ligne = ligne_depart + 1
    for i, ligne in enumerate(releve["lignes"]):
        r = premiere_ligne + i
        ws.cell(row=r, column=1, value=ligne["date"]).number_format = "dd/mm/yyyy"
        ws.cell(row=r, column=2, value=ligne["piece"])
        ws.cell(row=r, column=3, value=ligne["libelle"])
        ws.cell(row=r, column=4, value=ligne["statut"])
        # Cellule laissee vide plutot que "0" quand le montant est nul :
        # c'est ainsi que se presente le brouillard papier, et une cellule
        # vide vaut zero dans la formule de la colonne SOLDE.
        ws.cell(row=r, column=5,
                value=round(ligne["debit"], 2) or None).number_format = "#,##0"
        ws.cell(row=r, column=6,
                value=round(ligne["credit"], 2) or None).number_format = "#,##0"
        cellule_solde = ws.cell(row=r, column=7, value=f"=G{r - 1}+E{r}-F{r}")
        cellule_solde.number_format = "#,##0"

    nb_lignes = len(releve["lignes"])
    derniere_ligne_formatee = premiere_ligne + max(nb_lignes, 1) + MARGE_LIGNES_SUPPLEMENTAIRES
    plage = f"G{premiere_ligne}:G{derniere_ligne_formatee}"
    # start_color ET end_color : dans une mise en forme conditionnelle (un
    # "dxf"), Excel lit la couleur de fond dans end_color/bgColor - un fond
    # defini seulement par fgColor ne s'affiche pas.
    rouge = PatternFill("solid", start_color="FFF8CBAD", end_color="FFF8CBAD")
    ws.conditional_formatting.add(plage, CellIsRule(operator="lessThan", formula=["0"],
                                                     fill=rouge, font=Font(color="FF9C0006", bold=True)))

    largeurs = {1: 12, 2: 13, 3: 42, 4: 14, 5: 14, 6: 14, 7: 16}
    for col, largeur in largeurs.items():
        ws.column_dimensions[get_column_letter(col)].width = largeur
    ws.freeze_panes = f"A{premiere_ligne}"

    # Mise en page d'impression : le comptable compare souvent sur papier,
    # a cote de son brouillard - sans cela, les colonnes DEBIT/CREDIT/SOLDE
    # partent sur une seconde feuille, ce qui rend la comparaison illisible.
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{ligne_entetes}:{ligne_entetes}"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def construire_fichier_message(message):
    """Classeur d'une seule ligne, quand il manque un element pour generer le
    relevé (journal "Tous", centre non choisi, relevé de banque demande par un
    role local...). Pas de ligne "SOLDE CALCULÉ AU ..." ni de tableau vide :
    un chiffre dans un fichier de refus ne pourrait qu'induire en erreur. Le
    meme message est affiche a l'ecran a cote du bouton."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Relevé"
    ws.cell(row=1, column=1, value="Relevé non généré").font = Font(bold=True, size=13)
    ws.cell(row=2, column=1, value=message)
    ws.column_dimensions["A"].width = 80
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def exporter(journal, ref, debut, fin, centre=None, nom_centre=""):
    """Point d'entree unique pour app.py : calcule le relevé (en touchant la
    base, contrairement a calculer_releve() appelee seule dans les tests)
    et renvoie directement les octets du fichier .xlsx."""
    releve = calculer_releve(journal, ref, debut, fin, centre=centre)
    titre = f"Relevé de caisse — {journal}"
    if nom_centre:
        titre += f" — {nom_centre}"
    titre += f" — du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}"
    return construire_fichier(releve, titre)

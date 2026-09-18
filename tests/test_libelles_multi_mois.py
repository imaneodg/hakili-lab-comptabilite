# ---------------------------------------------------------------------------
# Libelles d'encaissement : plusieurs mois sur une seule ecriture (18/09/2026)
#
# Deux changements sont testes ici, parce qu'ils se tiennent :
#   - une ligne de repartition peut couvrir PLUSIEURS mois et ne produit
#     alors qu'UNE ecriture 411, dont le libelle les cite tous ;
#   - les lignes 411 ne citent plus le nom de l'eleve (son code tiers est
#     deja sur la ligne), ce qui libere la place necessaire pour les mois.
#
# Le point sensible est la limite de 60 caracteres imposee par Sage :
# ligne() tronque par la DROITE, donc un libelle trop long perdrait son
# dernier mois sans le moindre message. Les tests ci-dessous verifient la
# regle sur la totalite des combinaisons possibles, pas sur trois exemples.
#
# Aucune base, aucune session Shiny : logic.modeles est du calcul pur.
# ---------------------------------------------------------------------------

import itertools

import pytest

import logic.modeles as md

NATURES = ("frais", "avance", "solde")


def _combinaisons():
    """Toutes les selections de 1 a 6 mois (MAX_LIGNES_REPARTITION), pour
    chaque nature - 7 527 cas, calcules en une fraction de seconde."""
    for nature in NATURES:
        for n in range(1, 7):
            for combi in itertools.combinations(md.MOIS_FR, n):
                yield nature, list(combi)


def test_aucun_libelle_ne_depasse_la_limite_sage():
    trop_longs = [(n, c, lib) for n, c in _combinaisons()
                  for lib in [md._libelle_frais_ca(n, c)]
                  if len(lib) > md.LIBELLE_MAX]
    assert not trop_longs, (
        "Ces libelles depassent LIBELLE_MAX et seraient tronques par ligne(), "
        f"donc amputes de leur dernier mois : {trop_longs[:5]}")


def test_chaque_libelle_se_relit_sur_son_dernier_mois():
    """mois_depuis_libelle() sert a suggerer le mois suivant d'une avance.
    Si elle ne reconnait plus le libelle, la suggestion retombe en silence
    sur le mois du jour - une regression invisible, sans message d'erreur."""
    fautifs = []
    for nature, combi in _combinaisons():
        attendu = md.mois_tries(combi)[-1]
        lib = md._libelle_frais_ca(nature, combi)
        if md.mois_depuis_libelle(lib) != attendu:
            fautifs.append((lib, md.mois_depuis_libelle(lib), attendu))
    assert not fautifs, f"Libelles mal relus : {fautifs[:5]}"


def test_juin_et_juillet_ne_se_confondent_jamais():
    """Sur trois lettres, JUIN et JUILLET donnent tous deux "JUI". Et "MAI"
    comme "JUIN" sont a la fois un nom complet et leur propre abreviation :
    une relecture qui cherche les noms complets avant les abreviations
    s'arrete sur eux et ne voit jamais le mois suivant."""
    assert md.ABREVIATIONS_MOIS["JUIN"] != md.ABREVIATIONS_MOIS["JUILLET"]
    for lib, attendu in [("FRAIS CA JUIN-JUIL", "JUILLET"),
                         ("FRAIS DE COURS D'APPUI SEP-NOV-MAI-JUIL", "JUILLET"),
                         ("FRAIS DE COURS D'APPUI JAN-MAI-AOU", "AOUT")]:
        assert md.mois_depuis_libelle(lib) == attendu, lib


def test_les_mois_sortent_dans_l_ordre_de_l_annee_academique():
    """Septembre a aout, jamais l'ordre calendaire : un reglement qui couvre
    novembre, decembre et janvier traverse deux annees civiles."""
    assert md.mois_tries(["JANVIER", "NOVEMBRE", "DECEMBRE"]) == \
        ["NOVEMBRE", "DECEMBRE", "JANVIER"]
    assert md.mois_tries(["AOUT", "SEPTEMBRE"]) == ["SEPTEMBRE", "AOUT"]
    assert md.mois_tries(["MARS", "MARS"]) == ["MARS"]
    assert md.mois_tries(["", None, "PASUNMOIS", "MAI"]) == ["MAI"]


@pytest.mark.parametrize("mois", ["NOVEMBRE", ["NOVEMBRE"]])
def test_l_ancienne_forme_chaine_reste_acceptee(mois):
    """valeurs_json contient une chaine sur toutes les pieces enregistrees
    avant le 18/09/2026. Corriger l'une d'elles doit continuer a marcher."""
    assert md.mois_tries(mois) == ["NOVEMBRE"]
    assert md._libelle_frais_ca("frais", mois) == \
        "FRAIS DE COURS D'APPUI DE NOVEMBRE"


def _piece(repartition, montant):
    v = {"tiers": "411OUEDRAOGOAFIYA", "tiers_nom": "OUEDRAOGO AFIYA IMANE",
         "montant": montant, "lib": "FRAIS DE COURS D'APPUI - OUEDRAOGO AFIYA IMANE",
         "repartition": repartition}
    return md._lignes_encaissement(v, "571100")


def test_plusieurs_mois_sur_une_ligne_donnent_une_seule_ecriture():
    """90 000 F qui couvrent trois mois : une ligne de caisse, une seule
    ligne 411 citant les trois mois - la facon de faire du comptable."""
    L = _piece([{"mois": ["OCTOBRE", "NOVEMBRE", "DECEMBRE"],
                 "nature": "frais", "montant": 90000}], 90000)
    assert len(L) == 2
    assert L.iloc[1]["credit"] == 90000
    assert L.iloc[1]["libelle"] == \
        "FRAIS DE COURS D'APPUI D'OCTOBRE, NOVEMBRE ET DECEMBRE"
    assert L["debit"].sum() == L["credit"].sum()


def test_un_reliquat_se_saisit_sur_une_deuxieme_ligne():
    """80 000 F : deux mois entiers, puis le reliquat en avance sur le
    troisieme. Deux ecritures 411, une seule piece, un seul mouvement de
    caisse - l'eleve n'a donne l'argent qu'une fois."""
    L = _piece([{"mois": ["OCTOBRE", "NOVEMBRE"], "nature": "frais", "montant": 60000},
                {"mois": ["DECEMBRE"], "nature": "avance", "montant": 20000}], 80000)
    assert len(L) == 3
    assert L.iloc[1]["libelle"] == "FRAIS DE COURS D'APPUI D'OCTOBRE ET NOVEMBRE"
    assert L.iloc[2]["libelle"] == "AVANCE DE FRAIS DE COURS D'APPUI DE DECEMBRE"
    assert md.operation_equilibree([{"lignes": L, "journal": "CP"}])


def test_le_nom_reste_sur_la_caisse_et_disparait_des_lignes_411():
    """La ligne de caisse est la SEULE de la piece sans code tiers : sans le
    nom, le brouillard de caisse deviendrait une suite de lignes identiques
    ou plus personne ne sait qui a paye. Les lignes 411, elles, portent le
    code tiers - le nom y serait une redondance qui mange la place des mois."""
    L = _piece([{"mois": ["NOVEMBRE"], "nature": "frais", "montant": 30000}], 30000)
    caisse, quatre_cent_onze = L.iloc[0], L.iloc[1]
    assert caisse["code_tiers"] == ""
    assert "OUEDRAOGO" in caisse["libelle"]
    assert quatre_cent_onze["code_tiers"] == "411OUEDRAOGOAFIYA"
    assert "OUEDRAOGO" not in quatre_cent_onze["libelle"]


def test_une_ligne_sans_mois_est_ignoree():
    assert _piece([{"mois": [], "nature": "frais", "montant": 5000}], 5000) is None

# ---------------------------------------------------------------------------
# Libelles d'encaissement : nature abregee, mois abreges, nom de l'eleve
#
#     FRAIS CA OCT A DEC - OUEDRAOGO ABDOUL AZIZ
#
# Trois regles sont testees ici, et elles se tiennent :
#   - une ligne de repartition peut couvrir PLUSIEURS mois et ne produit
#     alors qu'UNE ecriture 411, dont le libelle les cite tous ;
#   - le libelle ne depasse JAMAIS les 60 caracteres de Sage ;
#   - quand il faut couper, c'est le NOM qui cede, jamais la nature ni les
#     mois - le code tiers est deja sur la ligne et identifie la personne,
#     alors que rien d'autre ne dit de quelle operation il s'agit.
#
# Le point sensible est la troncature : ligne() coupe par la DROITE, en
# silence. Un libelle trop long perdrait donc son dernier mois sans le
# moindre message. Les tests ci-dessous verifient la regle sur la totalite
# des combinaisons possibles, pas sur trois exemples choisis.
#
# Aucune base, aucune session Shiny : logic.modeles est du calcul pur.
# ---------------------------------------------------------------------------

import itertools

import pytest

import logic.modeles as md

NATURES = ("frais", "avance", "solde")

# Le nom le plus long du plan tiers Sage (35 caracteres, longueur maximale que
# l'export produit). C'est le pire cas reel, pas une valeur inventee.
NOM_LE_PLUS_LONG = "TIENDREBEOGO BENI DE DIEU M KENNETH"
NOM_COURANT = "OUEDRAOGO ABDOUL AZIZ"


def _combinaisons():
    """Toutes les selections de 1 a 6 mois (MAX_LIGNES_REPARTITION dans
    app.py), pour chaque nature - 7 527 cas."""
    for nature in NATURES:
        for n in range(1, 7):
            for combi in itertools.combinations(md.MOIS_FR, n):
                yield nature, list(combi)


def test_aucun_libelle_ne_depasse_la_limite_sage():
    trop_longs = [(n, c, lib) for n, c in _combinaisons()
                  for lib in [md._libelle_frais_ca(n, c, NOM_LE_PLUS_LONG)]
                  if len(lib) > md.LIBELLE_MAX]
    assert not trop_longs, (
        "Ces libelles depassent LIBELLE_MAX et seraient coupes par ligne() : "
        f"{trop_longs[:5]}")


def test_la_nature_et_les_mois_survivent_toujours():
    """C'est la garantie qui compte. Un nom ampute reste identifiable par le
    code tiers de la ligne ; un mois ampute, lui, est une information perdue."""
    fautifs = []
    for nature, combi in _combinaisons():
        liste = md.mois_tries(combi)
        tete = f"{md.LIBELLES_NATURE_CA[nature]} {md._mois_en_libelle(liste)}"
        lib = md._libelle_frais_ca(nature, combi, NOM_LE_PLUS_LONG)
        if not lib.startswith(tete):
            fautifs.append((lib, tete))
    assert not fautifs, f"Nature ou mois ampute : {fautifs[:5]}"


def test_aucune_troncature_jusqu_a_trois_mois():
    """Mesure faite sur le plan tiers reel : jusqu'a trois mois, meme le nom
    le plus long du referentiel passe en entier. C'est ce qui a decide du
    choix de la forme courte."""
    coupes = []
    for nature in NATURES:
        for n in range(1, 4):
            for combi in itertools.combinations(md.MOIS_FR, n):
                lib = md._libelle_frais_ca(nature, combi, NOM_LE_PLUS_LONG)
                if not lib.endswith(NOM_LE_PLUS_LONG):
                    coupes.append(lib)
    assert not coupes, f"Nom tronque alors qu'il ne devrait pas : {coupes[:5]}"


def test_la_plage_remplace_l_enumeration_sur_les_mois_qui_se_suivent():
    """"SEP A FEV" fait 9 caracteres la ou "SEP-OCT-NOV-DEC-JAN-FEV" en fait
    23. C'est ce qui sauve les reglements longs."""
    suite = ["SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DECEMBRE", "JANVIER", "FEVRIER"]
    assert md._mois_en_libelle(md.mois_tries(suite)) == "SEP A FEV"
    assert md._mois_en_libelle(md.mois_tries(["OCTOBRE", "NOVEMBRE", "DECEMBRE"])) == "OCT A DEC"
    # Deux mois : pas de plage, une plage de deux termes n'apporte rien.
    assert md._mois_en_libelle(md.mois_tries(["OCTOBRE", "NOVEMBRE"])) == "OCT-NOV"
    # Mois qui ne se suivent pas : enumeration, jamais de plage trompeuse.
    assert md._mois_en_libelle(md.mois_tries(["OCTOBRE", "DECEMBRE", "MARS"])) == "OCT-DEC-MAR"


def test_chaque_libelle_se_relit_sur_son_dernier_mois():
    """mois_depuis_libelle() sert a suggerer le mois suivant d'une avance. Si
    elle ne reconnait plus le libelle, la suggestion retombe en silence sur le
    mois du jour - une regression invisible, sans message d'erreur."""
    fautifs = []
    for nature, combi in _combinaisons():
        attendu = md.mois_tries(combi)[-1]
        lib = md._libelle_frais_ca(nature, combi, NOM_COURANT)
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
                         ("FRAIS CA SEP-NOV-MAI-JUIL", "JUILLET"),
                         ("FRAIS CA JAN-MAI-AOU", "AOUT")]:
        assert md.mois_depuis_libelle(lib) == attendu, lib


def test_le_nom_n_empeche_pas_de_relire_le_mois():
    """Un patronyme pourrait contenir un mot qui ressemble a un mois. Le nom
    suit " - ", et la relecture ne scanne que ce qui precede."""
    assert md.mois_depuis_libelle("FRAIS CA NOV - SAWADOGO MARS") == "NOVEMBRE"


def test_les_anciens_libelles_restent_lisibles():
    """Les pieces enregistrees avant le 18/09/2026 gardent leur forme longue,
    et celles d'avant le 10/09 leur suffixe "/MOIS". Corriger une piece
    ancienne doit continuer a fonctionner."""
    for lib, attendu in [
            ("FRAIS DE COURS D'APPUI DE NOVEMBRE - OUEDRAOGO ABDOUL AZIZ", "NOVEMBRE"),
            ("AVANCE DE FRAIS DE COURS D'APPUI D'AVRIL - SORE AWA", "AVRIL"),
            ("RATTRAPAGE DE FRAIS DE COURS D'APPUI DE MAI - ZIDA GILDAS", "MAI"),
            ("REMUNERATION MARS/KABORE BERNARD", "MARS"),
            ("AVANCE BADOLO DRISSA/AOUT", "AOUT"),
            ("VERSEMENT D'ESPECES EN BANQUE", None)]:
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
    avant la saisie multi-mois."""
    assert md.mois_tries(mois) == ["NOVEMBRE"]
    assert md._libelle_frais_ca("frais", mois, "OUATTARA ALISHA") == \
        "FRAIS CA NOV - OUATTARA ALISHA"


def _piece(repartition, montant, nom="OUEDRAOGO AFIYA IMANE"):
    v = {"tiers": "411OUEDRAOGOAFIYA", "tiers_nom": nom, "montant": montant,
         "lib": f"FRAIS CA - {nom}", "repartition": repartition}
    return md._lignes_encaissement(v, "571100")


def test_plusieurs_mois_sur_une_ligne_donnent_une_seule_ecriture():
    """90 000 F qui couvrent trois mois : une ligne de caisse, une seule
    ligne 411 citant les trois mois - la facon de faire du comptable."""
    L = _piece([{"mois": ["OCTOBRE", "NOVEMBRE", "DECEMBRE"],
                 "nature": "frais", "montant": 90000}], 90000)
    assert len(L) == 2
    assert L.iloc[1]["credit"] == 90000
    assert L.iloc[1]["libelle"] == "FRAIS CA OCT A DEC - OUEDRAOGO AFIYA IMANE"
    assert L["debit"].sum() == L["credit"].sum()


def test_un_reliquat_se_saisit_sur_une_deuxieme_ligne():
    """80 000 F : deux mois entiers, puis le reliquat en avance sur le
    troisieme. Deux ecritures 411, une seule piece, un seul mouvement de
    caisse - l'eleve n'a donne l'argent qu'une fois."""
    L = _piece([{"mois": ["OCTOBRE", "NOVEMBRE"], "nature": "frais", "montant": 60000},
                {"mois": ["DECEMBRE"], "nature": "avance", "montant": 20000}], 80000)
    assert len(L) == 3
    assert L.iloc[1]["libelle"] == "FRAIS CA OCT-NOV - OUEDRAOGO AFIYA IMANE"
    assert L.iloc[2]["libelle"] == "AVANCE CA DEC - OUEDRAOGO AFIYA IMANE"
    assert md.operation_equilibree([{"lignes": L, "journal": "CP"}])


def test_la_ligne_de_caisse_porte_le_nom_sans_les_mois():
    """Elle est la seule ligne de la piece sans code tiers : le nom y est la
    seule indication de qui a paye. Elle ne cite pas de mois - une ligne
    unique ne peut pas resumer plusieurs mois et natures a la fois."""
    L = _piece([{"mois": ["OCTOBRE"], "nature": "frais", "montant": 30000},
                {"mois": ["NOVEMBRE"], "nature": "avance", "montant": 20000}], 50000)
    caisse = L.iloc[0]
    assert caisse["code_tiers"] == ""
    assert caisse["libelle"] == "FRAIS CA - OUEDRAOGO AFIYA IMANE"
    assert all(L.iloc[i]["code_tiers"] == "411OUEDRAOGOAFIYA" for i in (1, 2))


def test_une_ligne_sans_mois_est_ignoree():
    assert _piece([{"mois": [], "nature": "frais", "montant": 5000}], 5000) is None

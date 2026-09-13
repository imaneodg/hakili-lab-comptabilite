# ---------------------------------------------------------------------------
# Tests de logic/modeles.py ajoutes le 10/09/2026 (groupe 4 des corrections
# de l'audit) : composition du libelle "PREFIXE NOM/MOIS" qui ne doit jamais
# couper le suffixe "/MOIS", et journalisation d'un modele qui leve une
# exception au lieu de l'avaler silencieusement.
# ---------------------------------------------------------------------------

import logging

import pandas as pd

import logic.modeles as md


# --- _libelle_avec_mois : le suffixe "/MOIS" ne doit jamais etre tronque ----

def test_libelle_avec_mois_ne_coupe_jamais_le_suffixe():
    # Nom de tiers volontairement long : avant le correctif, c'est le
    # libelle final deja compose qui etait tronque a 60 caracteres par
    # ligne(), coupant le plus souvent la fin "/MOIS" (la partie la plus a
    # droite, donc la plus exposee).
    nom_long = "OUEDRAOGO PENGDEWENDE MARIE CHRISTELLE ALIMATA"
    libelle = md._libelle_avec_mois("AVANCE FRAIS CA", nom_long, "SEPTEMBRE")
    assert libelle.endswith("/SEPTEMBRE")
    assert len(libelle) <= md.LIBELLE_MAX
    # Condition necessaire pour que la suggestion automatique du mois
    # suivant fonctionne : le mois doit rester reconnaissable apres coup.
    assert md.mois_depuis_libelle(libelle) == "SEPTEMBRE"


def test_libelle_avec_mois_ne_tronque_pas_un_nom_court():
    assert md._libelle_avec_mois("AVANCE", "KABORE", "MARS") == "AVANCE KABORE/MARS"


def test_libelle_avec_mois_tronque_seulement_le_nom_avec_prefixe_long():
    libelle = md._libelle_avec_mois("AVANCE FRAIS CA", "X" * 80, "OCTOBRE")
    assert libelle.endswith("/OCTOBRE")
    assert len(libelle) == md.LIBELLE_MAX


# --- construire_lignes : un modele casse doit laisser une trace ------------

def test_construire_lignes_journalise_au_lieu_d_avaler_une_exception(caplog):
    # Modele factice dont lignes() leve toujours une exception - simule un
    # bug reel dans un modele (faute de frappe dans une cle de dictionnaire,
    # division par une valeur non renseignee, etc.).
    m = {
        "id": "__test_modele_casse__",
        "libelle": lambda v: "TEST",
        "champs": [],
        "lignes": lambda v, cc: (_ for _ in ()).throw(KeyError("champ_absent")),
    }
    journaux_ref = {"journaux": pd.DataFrame(
        [{"journal": "CP", "compte_contrepartie": "571100", "type": "tresorerie"}])}
    md.MODELES.append(m)
    try:
        with caplog.at_level(logging.ERROR, logger="hakili.modeles"):
            res = md.construire_lignes("__test_modele_casse__", {"montant": 1000}, "CP", journaux_ref)
        # Le comportement fonctionnel ne change pas : toujours None.
        assert res is None
        # Mais desormais, l'incident est diagnosticable.
        assert any("Echec de construction des lignes" in r.message for r in caplog.records)
    finally:
        md.MODELES.remove(m)

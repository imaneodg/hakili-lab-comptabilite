# ---------------------------------------------------------------------------
# Tests dedies a l'isolation des donnees par centre, ajoutes le 11/09/2026
# suite a une faille decouverte par Afiya : un compte "validation" cree sur
# le centre SIA (SIAO) voyait l'ensemble des donnees de Hakili Lab (toutes
# les pieces, tous les centres, le solde de la banque) exactement comme le
# comptable du siege, alors qu'il aurait du rester strictement limite a SIA.
#
# Regle metier verifiee ici (voir aussi test_authorisation.py) :
#   - seul le comptable du siege (role "validation", centre "SIE") a une
#     vision globale de Hakili Lab ;
#   - tout autre utilisateur - saisie OU validation, quel que soit son
#     centre (SIA, PIS, SAA, TAM, NAG) - ne voit jamais que les donnees de
#     son propre centre : ses pieces, ses ecritures, le solde de sa caisse,
#     ses entrees/sorties, ses anomalies ;
#   - le compte bancaire partage (journal Banque) n'est jamais visible a un
#     non-comptable, meme indirectement via une anomalie.
#
# Deux angles, comme le reste de la suite :
#   1. Couche donnees (logic/donnees.py) : fonctions pures, testees ici en
#      reconstituant un jeu de donnees multi-centres explicite (SIA, SAA,
#      TAM) - aucune connexion Postgres necessaire.
#   2. Couche app.py : les fonctions qui decident QUEL centre transmettre a
#      la couche donnees (pieces_vue, attente, a_exporter, anomalies_vue)
#      sont des closures Shiny non invocables hors session reelle (voir
#      l'entete de test_authorisation.py) - verifiees ici par analyse du
#      code source (ast), sur le meme principe : chacune doit filtrer sur
#      le centre de l'utilisateur des qu'elle n'est pas le comptable.
# ---------------------------------------------------------------------------

import ast
from pathlib import Path

import pandas as pd

import logic.donnees as dl

APP_PY = Path(__file__).resolve().parent.parent / "app.py"

CENTRES = ["SIA", "SAA", "TAM"]


def _ref():
    comptes = pd.DataFrame([
        {"compte": "571100", "intitule": "Caisse principale", "nature": "tresorerie",
         "tiers_obligatoire": "non"},
        {"compte": "521200", "intitule": "Banques (CBI)", "nature": "tresorerie",
         "tiers_obligatoire": "non"},
    ])
    journaux = pd.DataFrame([
        {"journal": "CP", "compte_contrepartie": "571100", "type": "tresorerie",
         "prefixe_piece": "CP", "solde_ouverture": 0.0, "caisse_physique": "oui", "actif": "oui"},
        {"journal": "Banque", "compte_contrepartie": "521200", "type": "tresorerie",
         "prefixe_piece": "CBI", "solde_ouverture": 0.0, "caisse_physique": "non", "actif": "oui"},
    ])
    noms = {"SIA": "SIAO", "SAA": "Saaba", "TAM": "Tampouy"}
    centres = pd.DataFrame([{"code_centre": c, "intitule": noms[c]} for c in CENTRES])
    tiers = pd.DataFrame(columns=["code_tiers", "intitule"])
    soldes_centre = pd.DataFrame([
        {"centre": "SIA", "journal": "CP", "solde_ouverture": 15000.0},
        {"centre": "SAA", "journal": "CP", "solde_ouverture": 186825.0},
        {"centre": "TAM", "journal": "CP", "solde_ouverture": 19731.0},
    ])
    return {"comptes": comptes, "journaux": journaux, "centres": centres,
            "tiers": tiers, "soldes_centre": soldes_centre}


def _ligne(centre, compte, debit=0, credit=0, journal="CP", code_tiers="", modele="",
           id_piece=None, statut="validee"):
    return {"centre": centre, "compte": compte, "journal": journal, "debit": debit, "credit": credit,
            "date_piece": "2026-03-01", "code_tiers": code_tiers, "modele": modele,
            "id_piece": id_piece or f"P-{centre}", "statut": statut,
            "num_definitif": "", "num_provisoire": "P1", "libelle": "TEST"}


def _jeu_multi_centres():
    # SIA a bien ses propres ecritures reelles (contrairement au symptome
    # observe par Afiya, ou un compte SIA affichait 0 partout) : le test
    # ci-dessous prouve que SIA les voit, et qu'aucun autre centre ne les
    # voit a sa place.
    return pd.DataFrame([
        _ligne("SIA", "571100", debit=25000),
        _ligne("SAA", "571100", debit=50000),
        _ligne("TAM", "571100", credit=3000),
        _ligne("SIA", "521200", debit=10000, journal="Banque"),  # banque : jamais par centre
    ])


# --- couche donnees : chaque centre ne voit que le sien ---------------------

def test_solde_caisse_siao_ne_voit_que_ses_propres_ecritures():
    ref = _ref()
    d = _jeu_multi_centres()
    # SIA : son solde d'ouverture (15000) + sa seule ecriture (+25000).
    assert dl.solde_caisse("CP", ref, d, centre="SIA") == 40000.0
    # Jamais melange avec Saaba ou Tampouy.
    assert dl.solde_caisse("CP", ref, d, centre="SAA") == 186825.0 + 50000.0
    assert dl.solde_caisse("CP", ref, d, centre="TAM") == 19731.0 - 3000.0
    # Seul le comptable (centre=None) voit le total consolide des trois.
    total_attendu = (15000 + 25000) + (186825 + 50000) + (19731 - 3000)
    assert dl.solde_caisse("CP", ref, d, centre=None) == total_attendu


def test_anomalies_d_un_centre_n_incluent_jamais_les_autres_centres_ni_la_banque():
    ref = _ref()
    d = _jeu_multi_centres()
    # Provoque un decouvert cache a SAA uniquement, sur une piece identifiable.
    d = pd.concat([d, pd.DataFrame([_ligne("SAA", "571100", credit=999999, id_piece="P-SAA-decouvert")])],
                  ignore_index=True)
    ano_sia = dl.anomalies(d, ref, centre="SIA", inclure_banque=False)
    ano_saa = dl.anomalies(d, ref, centre="SAA", inclure_banque=False)
    # Peu importe que SIA ait par ailleurs ses propres anomalies de qualite
    # de donnees (pieces de test isolees, hors sujet ici) : le decouvert
    # provoque a SAA - ou meme le nom de ce centre - ne doit jamais
    # apparaitre dans le resultat calcule pour SIA.
    texte_sia = " ".join(ano_sia.astype(str).values.flatten()) if len(ano_sia) else ""
    assert "SAA" not in texte_sia and "Saaba" not in texte_sia and "P-SAA-decouvert" not in texte_sia
    # SAA, lui, voit bien son propre decouvert (sous une forme ou une autre).
    assert len(ano_saa) > len(ano_sia) or len(ano_saa) > 0
    # Un non-comptable (inclure_banque=False) ne voit jamais d'anomalie sur
    # le compte bancaire partage, meme s'il en avait une.
    assert "Banque" not in texte_sia


def test_anomalies_globales_reservees_au_comptable_incluent_tous_les_centres():
    ref = _ref()
    d = _jeu_multi_centres()
    d = pd.concat([d, pd.DataFrame([_ligne("SAA", "571100", credit=999999, id_piece="P-SAA-2")])],
                  ignore_index=True)
    # Le comptable (centre=None, inclure_banque=True) voit l'anomalie de SAA
    # meme sans etre lui-meme rattache a ce centre.
    ano_comptable = dl.anomalies(d, ref, centre=None, inclure_banque=True)
    assert len(ano_comptable) > 0


# --- couche app.py : chaque fonction qui expose des pieces/soldes doit ------
# --- filtrer par centre des qu'elle n'est pas le comptable ------------------

def _corps_source(nom_fonction, source, arbre):
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.FunctionDef) and noeud.name == nom_fonction:
            return ast.get_source_segment(source, noeud)
    return None


FONCTIONS_A_PERIMETRE_CENTRE = [
    # (nom de la fonction dans app.py, ce qu'elle expose)
    "pieces_vue",      # Brouillard
    "attente",         # Validation
    "a_exporter",      # Export Sage
    "anomalies_vue",   # Controles
    "b_stats",         # bandeau de soldes (Brouillard)
    "m_ruban",         # ruban de confirmation (Saisie)
]


def test_chaque_ecran_filtre_par_centre_pour_un_non_comptable():
    source = APP_PY.read_text(encoding="utf-8")
    arbre = ast.parse(source)
    manquants = []
    for nom in FONCTIONS_A_PERIMETRE_CENTRE:
        corps = _corps_source(nom, source, arbre)
        assert corps is not None, f"{nom}() introuvable dans app.py"
        appelle_est_comptable = "est_comptable()" in corps
        filtre_par_centre = "u[\"centre\"]" in corps or "u['centre']" in corps
        if not (appelle_est_comptable and filtre_par_centre):
            manquants.append(nom)
    assert not manquants, (
        "Ces fonctions n'appellent plus est_comptable() ET ne filtrent plus par "
        f"u['centre'] - un non-comptable pourrait revoir les donnees d'un autre "
        f"centre (ou la banque) : {manquants}"
    )


def test_onglets_valides_et_exportables_sont_bornes_au_centre_hors_comptable():
    # Verifie precisement la forme du filtre attendu dans attente()/
    # a_exporter() : "if not est_comptable(): ... centre" - pas seulement
    # la presence des deux mots quelque part dans la fonction (le test
    # precedent), pour eviter qu'un filtre place au mauvais endroit (par ex.
    # sur une variable jamais utilisee) passe a tort.
    source = APP_PY.read_text(encoding="utf-8")
    arbre = ast.parse(source)
    for nom in ("attente", "a_exporter", "pieces_vue"):
        corps = _corps_source(nom, source, arbre)
        idx_garde = corps.find("if not est_comptable():")
        assert idx_garde != -1, f"{nom}() n'a plus de branche 'if not est_comptable():'"
        apres_garde = corps[idx_garde:idx_garde + 200]
        assert "centre" in apres_garde, (
            f"{nom}() a une garde 'if not est_comptable():' qui ne filtre plus par centre juste apres"
        )

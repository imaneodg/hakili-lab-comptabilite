# ---------------------------------------------------------------------------
# Correctifs de l'audit du 07/10/2026 (livres le 08/10/2026).
#
# Un test par point corrige, contre une base PostgreSQL reelle (DATABASE_URL).
# Pieces datees de 2099 (jamais melees aux vraies), effacees a la fin, y
# compris les pieces exportees (echappatoire du trigger de protection) et les
# mois clotures de 2099.
# ---------------------------------------------------------------------------

import threading
from datetime import date

import pandas as pd
import pytest

import logic.donnees as dl
import logic.tableau_bord as tb


def _base_disponible():
    try:
        with dl._connexion() as c, c.cursor() as cur:
            cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'periodes_cloturees'")
            return cur.fetchone() is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _base_disponible(), reason="base PostgreSQL migree indisponible")

ANNEE = "2099"


def _nettoyer():
    with dl._connexion() as c, c.cursor() as cur:
        cur.execute("SET LOCAL hakili.autoriser_modif_protegee = 'oui'")
        cur.execute("DELETE FROM periodes_cloturees WHERE mois LIKE '2099-%'")
        cur.execute("DELETE FROM ecritures WHERE date_piece >= '2099-01-01'")
        cur.execute("DELETE FROM compteurs WHERE cle LIKE '%:2099%'")
        cur.execute("DELETE FROM suppressions_ecritures WHERE contenu->>'date_piece' >= '2099-01-01'")
        cur.execute("DELETE FROM tiers WHERE code_tiers LIKE '411ZZTEST%' OR code_tiers LIKE '411OUEDRAOGOPENG%'")
        cur.execute("DELETE FROM utilisateurs WHERE identifiant LIKE 'zz_test%'")


@pytest.fixture(autouse=True)
def propre():
    _nettoyer()
    yield
    _nettoyer()


def _op(montant=1000, libelle="TEST AUDIT", journal="CP"):
    compte = {"CP": "571100", "CMD": "571200"}[journal]
    lignes = pd.DataFrame([
        {"compte": compte, "code_tiers": "", "libelle": libelle, "debit": montant, "credit": 0.0},
        {"compte": "707810", "code_tiers": "", "libelle": libelle, "debit": 0.0, "credit": montant},
    ])
    return [{"journal": journal, "lignes": lignes}]


def _saisir(centre="SAA", jour="2099-05-03", **kw):
    dl.enregistrer_operation(_op(**kw), centre, jour, "libre", "test")
    with dl._connexion() as c, c.cursor() as cur:
        cur.execute("SELECT id_piece FROM ecritures WHERE date_piece >= '2099-01-01' "
                    "ORDER BY saisi_le DESC, id_piece DESC LIMIT 1")
        return cur.fetchone()[0]


def _statut(idp):
    with dl._connexion() as c, c.cursor() as cur:
        cur.execute("SELECT DISTINCT statut FROM ecritures WHERE id_piece = %s", (idp,))
        return cur.fetchone()[0]


# --- Valeur "!" : compte sans code utilisable (outils/definir_code.py) ----------------

def test_le_code_bloque_n_ouvre_rien():
    assert dl.verifier_code_acces("!", "!") is False
    assert dl.verifier_code_acces("", "!") is False
    assert dl.verifier_code_acces("9999", "!") is False


# --- C4 : codes tiers de 17 caracteres au plus ----------------------------------

def test_tiers_cree_par_la_saisie_tient_en_17_caracteres():
    code = dl.resoudre_tiers("Ouedraogo Pengdewende Afiya", "411", "411000")
    assert len(code) <= 17
    # Homonyme a la troncature : un code different, toujours <= 17.
    autre = dl.resoudre_tiers("Ouedraogo Pengdewende Afiyatou", "411", "411000")
    assert autre != code and len(autre) <= 17


def test_ajouter_tiers_refuse_un_code_trop_long():
    with pytest.raises(ValueError, match="17"):
        dl.ajouter_tiers("411ZZTESTWENDKOUNIABDOULAYE", "TEST", "411000")


def test_controle_bloque_un_tiers_trop_long():
    ref = dl.lire_referentiel()
    d = pd.DataFrame([{**{c: "" for c in dl.COLONNES}, "id_piece": "X", "id_ligne": "X-1",
                       "journal": "CP", "compte": "411000", "code_tiers": "411UNCODEBEAUCOUPTROPLONG",
                       "libelle": "L", "debit": 0.0, "credit": 10.0, "statut": "saisie"},
                      {**{c: "" for c in dl.COLONNES}, "id_piece": "X", "id_ligne": "X-2",
                       "journal": "CP", "compte": "571100", "libelle": "L", "debit": 10.0, "credit": 0.0,
                       "statut": "saisie"}])
    a = dl.controler(d, ref)
    assert a["anomalie"].str.contains("trop long pour Sage").any()


# --- Export Sage (ecran d'avant, retabli le 08/10/2026) -------------------------------

def test_marquer_exporte_ne_touche_que_les_pieces_validees():
    a, b = _saisir(), _saisir(jour="2099-05-04")
    dl.valider_pieces([a, b], "comptable")
    assert dl.marquer_exporte([a]) == 1
    assert _statut(a) == "exportee"
    assert _statut(b) == "validee"                                # pas dans la liste : reste a exporter
    assert dl.marquer_exporte([a]) == 0                           # deja exportee : rien ne change


def test_le_libelle_exporte_n_a_ni_point_virgule_ni_guillemet():
    a = _saisir(libelle='ACHAT CRAIE; STYLOS "BIC"')
    dl.valider_pieces([a], "comptable")
    d = dl.lire_ecritures(du="2099-01-01")
    texte = dl.texte_fichier_sage(dl.format_sage(d[d["id_piece"] == a], dl.lire_referentiel()))
    texte = texte.decode("cp1252")
    for ligne in texte.strip().split("\r\n"):
        assert ligne.count(";") == 8, ligne                       # 9 colonnes, pas une de plus
        assert '"' not in ligne


# --- M3 : protection en base, cloture, dates -----------------------------------------

def test_une_piece_exportee_ne_se_modifie_plus_en_base():
    a = _saisir()
    dl.valider_pieces([a], "comptable")
    dl.marquer_exporte([a])
    with pytest.raises(Exception, match="exportee"):
        with dl._connexion() as c, c.cursor() as cur:
            cur.execute("UPDATE ecritures SET libelle = 'X' WHERE id_piece = %s", (a,))
    with pytest.raises(Exception, match="exportee"):
        with dl._connexion() as c, c.cursor() as cur:
            cur.execute("DELETE FROM ecritures WHERE id_piece = %s", (a,))


def test_cloture_d_un_mois():
    a = _saisir(jour="2099-05-03")
    with pytest.raises(ValueError, match="pas encore exportees"):
        dl.cloturer_mois("2099-05", "comptable")
    dl.valider_pieces([a], "comptable")
    dl.marquer_exporte([a])
    dl.cloturer_mois("2099-05", "comptable")
    with pytest.raises(ValueError, match="cloture"):
        _saisir(jour="2099-05-20")
    # La base refuse aussi, sans passer par l'application.
    with pytest.raises(Exception, match="cloture"):
        with dl._connexion() as c, c.cursor() as cur:
            cur.execute("SET CONSTRAINTS ALL DEFERRED")
            cur.execute("INSERT INTO ecritures (id_ligne, id_piece, journal, centre, date_piece, compte, "
                        "debit, credit) VALUES ('Z1', 'Z', 'CP', 'SAA', '2099-05-21', '571100', 0, 0)")
    _saisir(jour="2099-06-01")                                    # le mois suivant reste ouvert
    dl.rouvrir_mois("2099-05", "comptable")
    _saisir(jour="2099-05-20")


def test_date_trop_loin_dans_le_futur():
    with dl._connexion() as c, c.cursor() as cur:
        dl.verifier_date_piece(cur, date(2026, 10, 15), aujourd_hui=date(2026, 10, 8))   # 7 jours : accepte
        with pytest.raises(ValueError, match="Verifiez l'annee"):
            dl.verifier_date_piece(cur, date(2026, 10, 16), aujourd_hui=date(2026, 10, 8))
        with pytest.raises(ValueError):
            dl.verifier_date_piece(cur, date(2062, 10, 8), aujourd_hui=date(2026, 10, 8))


# --- M2 : validation simultanee ----------------------------------------------------------

def test_deux_validations_simultanees_ne_perdent_aucun_numero():
    ids = [_saisir(jour=f"2099-07-{j:02d}") for j in (1, 2, 3)]
    resultats = []

    def valider(qui):
        try:
            resultats.append(dl.valider_pieces(ids, qui))
        except ValueError as e:
            resultats.append(str(e))

    fils = [threading.Thread(target=valider, args=(q,)) for q in ("comptable", "validateur")]
    [f.start() for f in fils]
    [f.join() for f in fils]
    validees = [r for r in resultats if isinstance(r, dict) and r["validees"]]
    assert len(validees) == 1, resultats                          # un seul a reellement valide
    with dl._connexion() as c, c.cursor() as cur:
        cur.execute("SELECT DISTINCT num_definitif FROM ecritures WHERE id_piece = ANY(%s)", (ids,))
        rangs = sorted(int(r[0][-3:]) for r in cur.fetchall())
        cur.execute("SELECT valeur FROM compteurs WHERE cle = 'def:CP:209907'")
        compteur = cur.fetchone()[0]
    assert rangs == [1, 2, 3] and compteur == 3                   # aucun trou


# --- M4 : dates impossibles -------------------------------------------------------------

def test_une_vieille_piece_n_est_pas_une_date_impossible():
    _saisir(centre="SAA", jour="2099-03-03")
    f = tb._fiabilite(date(2101, 1, 1), date(2101, 3, 31), ["SAA"], date(2101, 3, 31))
    assert f["SAA"]["controles"]["dates"]["nombre"] == 0


# --- M5 : motif d'un transfert entre centres -----------------------------------------------

def _transfert(centre, donateur, destinataire, motif, montant=5000):
    import logic.modeles as md
    v = {"centre_donateur": donateur, "centre_destinataire": destinataire, "motif": motif,
         "montant": montant, "libelle": "", "mon_centre": centre}
    op = md.construire_operation("transfert_interne", v, "CP", dl.lire_referentiel()["journaux"])
    return dl.enregistrer_operation(op, centre, "2099-08-02", "transfert_interne", "test", valeurs=v)


def test_le_destinataire_doit_reprendre_le_motif_du_donateur():
    _transfert("TAM", "TAM", "SIA", "pret")
    with pytest.raises(ValueError, match="Pret"):
        _transfert("SIA", "TAM", "SIA", "contribution")
    _transfert("SIA", "TAM", "SIA", "pret")


# --- M6 : l'assistant donne les chiffres du tableau de bord ----------------------------------

def test_l_assistant_et_le_tableau_de_bord_donnent_le_meme_resultat():
    from assistant import moteur
    _saisir(centre="SAA", jour="2099-09-03", montant=70000)
    _transfert("TAM", "TAM", "SIA", "contribution", montant=12000)
    _transfert("SIA", "TAM", "SIA", "contribution", montant=12000)
    centres = ["SAA", "TAM", "SIA"]
    r = tb.calculer(date(2099, 8, 1), date(2099, 9, 30), centres, date(2099, 12, 31))
    ctx = moteur.Contexte(portee=None)
    _, p = moteur.analyser(ctx, indicateurs="benefice, charges payees, argent recu de l activite",
                           du="2099-08-01", au="2099-09-30", centres="Saaba, Tampouy, SIAO")
    assert p["total"]["resultat_tableau"] == round(r["ensemble"]["resultat"])
    assert p["total"]["charges_exploitation"] == round(r["ensemble"]["charges"])
    _, p2 = moteur.analyser(ctx, indicateurs="benefice", du="2099-08-01", au="2099-09-30",
                            centres="Saaba, Tampouy, SIAO", regrouper_par="centre")
    par = {l["centre"]: l["resultat_tableau"] for l in p2["lignes"]}
    assert par["Tampouy"] == round(r["fiches"]["TAM"]["resultat"]) == -12000


# --- M7 : le Siege n'est pas un centre -------------------------------------------------------

def test_le_siege_n_est_jamais_propose_au_tableau_de_bord():
    _saisir(centre="SIE", jour="2099-04-01")
    assert "SIE" not in set(tb.centres_proposes()["code_centre"])
    assert "SIE" not in dl.centres_reels(dl.lire_referentiel())


# --- M8 : requete libre sous un role de lecture ------------------------------------------------

def test_la_requete_libre_ne_lit_que_les_tables_prevues():
    from assistant import moteur
    from assistant.comprehension import Incomprehension
    ctx = moteur.Contexte(portee=None)
    moteur.requete_sql(ctx, "select count(*) from comptes")
    for q in ("select * from comptes, ecritures", 'select * from "utilisateurs"',
              "select query_to_xml('select 1', true, true, '') from comptes"):
        with pytest.raises(Incomprehension):
            moteur.requete_sql(ctx, q)


# --- M9 : codes d'acces ---------------------------------------------------------------------------

def test_reinitialiser_puis_changer_son_code():
    dl.ajouter_utilisateur("zz_test_caisse", "Test", "saisie", "SAA", "ancien-code-1")
    dl.reinitialiser_code("zz_test_caisse", "provisoire-9", "comptable")
    statut, u, _ = dl.tenter_connexion("zz_test_caisse", "SAA", "provisoire-9")
    assert statut == "ok" and u["doit_changer_code"] is True
    with pytest.raises(ValueError):
        dl.changer_code("zz_test_caisse", "mauvais", "nouveau-code-7")
    with pytest.raises(ValueError, match="facile"):
        dl.changer_code("zz_test_caisse", "provisoire-9", "111111")
    dl.changer_code("zz_test_caisse", "provisoire-9", "nouveau-code-7")
    statut, u, _ = dl.tenter_connexion("zz_test_caisse", "SAA", "nouveau-code-7")
    assert statut == "ok" and u["doit_changer_code"] is False


def test_le_referentiel_ne_charge_plus_les_codes():
    assert "code_acces" not in dl.lire_referentiel()["utilisateurs"].columns


# --- M1 : une connexion ne fait plus tout recharger ------------------------------------------------

def test_une_connexion_ne_change_pas_les_revisions():
    dl.ajouter_utilisateur("zz_test_rev", "Test", "saisie", "SAA", "code-rev-123")
    avant = dl.revisions_bd()
    dl.tenter_connexion("zz_test_rev", "SAA", "mauvais")
    dl.tenter_connexion("zz_test_rev", "SAA", "code-rev-123")
    assert dl.revisions_bd() == avant


def test_les_soldes_portent_sur_tout_l_historique_meme_avec_la_fenetre():
    _saisir(centre="NAG", jour="2099-02-01", montant=3000)
    ref = dl.lire_referentiel()
    complet = dl.lire_ecritures()
    agrege = dl.mouvements_tresorerie()
    for centre in ("NAG", "SAA", None):
        assert dl.solde_caisse("CP", ref, complet, centre=centre) == \
            pytest.approx(dl.solde_caisse("CP", ref, agrege, centre=centre))

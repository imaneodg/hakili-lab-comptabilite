# ---------------------------------------------------------------------------
# Couche donnees - PostgreSQL
#
# Concue directement pour Postgres : ce n'est pas la version Excel adaptee a
# une base, c'est ce que la couche donnees aurait ete si l'application avait
# demarre sur Postgres. Consequences concretes par rapport a la version
# Excel :
#   - plus de verrou de repertoire : Postgres serialise les ecritures
#     concurrentes lui-meme (transactions, contraintes) ; seule la
#     numerotation (qui doit rester strictement croissante et sans trou pour
#     un meme centre/mois ou journal/mois) passe par un compteur en base,
#     incremente de facon atomique par UPSERT ;
#   - plus de "referentiel.xlsx" ni de "classeur par centre et par mois" :
#     six tables (comptes, tiers, journaux, centres, utilisateurs, ecritures)
#     et une table de compteurs ;
#   - la coherence (compte inconnu, journal inconnu...) est imposee par des
#     cles etrangeres, pas seulement verifiee a la lecture par controler().
#
# Interface publique inchangee : app.py et logic/modeles.py n'ont pas besoin
# de savoir que le stockage a change. lire_referentiel() et lire_ecritures()
# renvoient toujours des DataFrames pandas, dans les memes colonnes.
# ---------------------------------------------------------------------------

import contextlib
import json
import logging
import os
import random
import re
import unicodedata
import warnings
from datetime import datetime


import bcrypt
import pandas as pd
import psycopg2
import psycopg2.extensions
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

# Import necessaire a la garde d'equilibre d'enregistrer_operation() (M2 de
# l'audit du 18/09, corrige le 22/09/2026) : aucune boucle, logic/modeles.py
# n'importe jamais logic/donnees.py.
import logic.modeles as md

# pandas.read_sql sur une connexion psycopg2 brute (plutot qu'un moteur
# SQLAlchemy) fonctionne parfaitement mais le signale a chaque appel : on le
# fait exprès (pas de dependance SQLAlchemy supplementaire pour un usage
# aussi simple), donc l'avertissement est attendu et sans consequence.
warnings.filterwarnings("ignore", message=".*only supports SQLAlchemy connectable.*")

# Journal des operations financieres et des evenements d'authentification.
# Configure une seule fois par processus (App Shiny ou mcp_server) via
# logging.basicConfig au point d'entree - ce module se contente d'ecrire
# dessus, jamais de reconfigurer les handlers.
logger = logging.getLogger("hakili.donnees")

# --- connexion ---------------------------------------------------------------

_DSN = os.environ.get("DATABASE_URL") or None
_POOL = ThreadedConnectionPool(minconn=1, maxconn=20, dsn=_DSN)


# Une connexion peut mourir sans que personne ne la ferme : redemarrage du
# conteneur "db", coupure du reseau interne de Docker, connexion restee
# ouverte trop longtemps et fermee par Postgres. psycopg2 ne le decouvre qu'a
# la requete suivante.
def _est_cassee(conn):
    if conn.closed:
        return True
    try:
        return conn.info.transaction_status == psycopg2.extensions.TRANSACTION_STATUS_UNKNOWN
    except Exception:
        return True


@contextlib.contextmanager
def _connexion():
    """Preteun une connexion du pool, la rend a la sortie. Valide (commit) si
    le bloc se termine sans exception, annule (rollback) sinon - une piece
    ne peut jamais rester enregistree a moitie."""
    conn = _POOL.getconn()
    cassee = False
    try:
        yield conn
        conn.commit()
    except Exception:
        # Corrige le 18/09/2026 : conn.rollback() etait appele sans filet. Sur
        # une connexion deja coupee il leve a son tour, et son exception
        # remplacait la vraie cause de l'erreur - l'appelant recevait
        # "connection already closed" au lieu du probleme d'origine.
        cassee = _est_cassee(conn)
        if not cassee:
            try:
                conn.rollback()
            except Exception:
                cassee = True
        raise
    finally:
        # Une connexion morte rendue telle quelle au pool ressort au prochain
        # emprunt et echoue encore : une seule coupure empoisonne le pool pour
        # toute la duree de vie du processus. La fermer ici la fait remplacer
        # par une connexion neuve au prochain getconn().
        _POOL.putconn(conn, close=cassee)


def est_actif(identifiant):
    """Vrai si le compte existe et est actif. Sert a revalider une session
    Shiny deja ouverte (voir app.py, corrige le 22/09/2026, m2 de l'audit du
    18/09) : avant, seule la connexion verifiait 'actif' ; un compte
    desactive en cours de session restait pleinement utilisable jusqu'a ce
    que la personne ferme son navigateur."""
    if not identifiant:
        return False
    with _connexion() as c, c.cursor() as cur:
        cur.execute("SELECT actif FROM utilisateurs WHERE lower(identifiant) = lower(%s)", (identifiant,))
        r = cur.fetchone()
    return bool(r) and str(r[0]).lower() == "oui"


def _lire_df(sql, params=None, conn=None):
    if conn is not None:
        return pd.read_sql(sql, conn, params=params)
    with _connexion() as c:
        return pd.read_sql(sql, c, params=params)


COLONNES = [
    "id_ligne", "id_piece", "id_lien", "num_provisoire", "num_definitif",
    "journal", "centre", "date_piece", "compte", "code_tiers", "libelle",
    "debit", "credit", "modele", "saisi_par", "saisi_le",
    "statut", "valide_par", "valide_le", "exporte_le", "observation",
    "valeurs_json",
    # Transferts internes entre centres (voir
    # sql/migrations/2026-09-12_transferts_internes.sql) : vides sur toute
    # ecriture qui n'est pas un transfert.
    "reference_transfert", "centre_contrepartie",
]

# Compte SYSCOHADA 585 "Virements de fonds" : compte de passage de tout
# mouvement d'argent d'une caisse a une autre - approvisionnement de la CMD,
# versement en banque, et transfert d'un centre vers un autre.
COMPTE_VIREMENTS_FONDS = "585000"
MODELE_TRANSFERT_INTERNE = "transfert_interne"

# --- utilitaires (identiques a la version Excel : aucune dependance au stockage) --


def ou(x, defaut):
    if x is None:
        return defaut
    if isinstance(x, float) and pd.isna(x):
        return defaut
    if isinstance(x, str) and x.strip() == "":
        return defaut
    return x


def fcfa(x):
    try:
        v = round(float(x if x not in (None, "") else 0))
    except (TypeError, ValueError):
        v = 0
    return f"{v:,}".replace(",", " ")


# --- referentiel -------------------------------------------------------------


def lire_referentiel():
    with _connexion() as c:
        ref = {
            "comptes": _lire_df("SELECT * FROM comptes ORDER BY compte", conn=c),
            "tiers": _lire_df("SELECT * FROM tiers ORDER BY code_tiers", conn=c),
            "libelles": _lire_df("SELECT compte, libelle, frequence FROM libelles_types ORDER BY id", conn=c),
            "journaux": _lire_df("SELECT * FROM journaux ORDER BY journal", conn=c),
            "centres": _lire_df("SELECT * FROM centres ORDER BY code_centre", conn=c),
            "utilisateurs": _lire_df("SELECT * FROM utilisateurs ORDER BY identifiant", conn=c),
            # Solde d'ouverture des caisses physiques (CP, CMD), un par
            # centre : voir solde_caisse() plus bas, qui l'utilise a la place
            # de journaux.solde_ouverture pour ces deux journaux uniquement.
            "soldes_centre": _lire_df(
                "SELECT centre, journal, solde_ouverture FROM soldes_ouverture_centre", conn=c),
        }
    for cle in ("comptes", "journaux", "centres"):
        if "updated_at" in ref[cle].columns:
            ref[cle] = ref[cle].drop(columns=["updated_at"])
    if "updated_at" in ref["tiers"].columns:
        ref["tiers"] = ref["tiers"].drop(columns=["updated_at"])
    if "updated_at" in ref["utilisateurs"].columns:
        ref["utilisateurs"] = ref["utilisateurs"].drop(columns=["updated_at"])
    for col in ("solde_ouverture",):
        ref["journaux"][col] = ref["journaux"][col].astype(float)
    if len(ref["soldes_centre"]):
        ref["soldes_centre"]["solde_ouverture"] = ref["soldes_centre"]["solde_ouverture"].astype(float)
    return ref


def intitule_compte(ref, compte):
    comptes = ref["comptes"]
    mapping = dict(zip(comptes["compte"].astype(str), comptes["intitule"]))
    return mapping.get(str(compte), "compte inconnu")


def maj_solde_ouverture(journal, montant):
    with _connexion() as c, c.cursor() as cur:
        cur.execute("UPDATE journaux SET solde_ouverture = %s, updated_at = now() WHERE journal = %s",
                    (float(montant or 0), str(journal)))


def maj_solde_ouverture_centre(centre, journal, montant):
    """Meme role que maj_solde_ouverture(), mais pour une caisse physique
    (CP, CMD) : chaque centre a son propre solde d'ouverture, jamais un seul
    chiffre partage. UPSERT car la ligne (centre, journal) existe deja pour
    tout centre actif (seedee a 0 par sql/seed.sql ou la migration du
    11/09/2026) mais ne doit pas empecher un centre cree plus tard."""
    with _connexion() as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO soldes_ouverture_centre (centre, journal, solde_ouverture, updated_at) "
            "VALUES (%s, %s, %s, now()) "
            "ON CONFLICT (centre, journal) DO UPDATE SET "
            "solde_ouverture = EXCLUDED.solde_ouverture, updated_at = now()",
            (str(centre), str(journal), float(montant or 0)))


# --- reclassement depuis Controles --------------------------------------------
#
# Une piece "a_corriger" a deja sa ligne de caisse correcte ; seule sa
# contrepartie (souvent le compte d'attente) est en suspens. Plutot que de
# forcer une nouvelle saisie complete depuis Brouillard, le comptable peut
# directement, depuis Controles, attribuer le bon compte et le bon tiers a
# cette ligne precise, sans toucher au reste de la piece.
def reclasser_piece(id_piece, ancien_compte, nouveau_compte, code_tiers, utilisateur):
    nouveau_compte = str(nouveau_compte or "").strip()
    if not nouveau_compte:
        raise ValueError("Choisir un compte.")
    with _connexion() as c, c.cursor() as cur:
        cur.execute("SELECT DISTINCT statut FROM ecritures WHERE id_piece = %s", (id_piece,))
        statuts = {r[0] for r in cur.fetchall()}
        if not statuts:
            raise ValueError("Piece introuvable.")
        if statuts - {"saisie", "a_corriger"}:
            raise ValueError("Cette piece est deja validee ou exportee, elle ne peut plus etre reclassee ici.")
        cur.execute(
            "UPDATE ecritures SET compte = %s, code_tiers = %s "
            "WHERE id_piece = %s AND compte = %s",
            (nouveau_compte, str(code_tiers or "").strip(), id_piece, str(ancien_compte)))
        if cur.rowcount == 0:
            raise ValueError(f"Aucune ligne sur le compte {ancien_compte} trouvee sur cette piece.")
        cur.execute(
            "UPDATE ecritures SET statut = 'saisie', observation = %s WHERE id_piece = %s",
            (f"{utilisateur} : compte/tiers attribues depuis Controles", id_piece))
        return cur.rowcount


TYPES_COLLECTIF = {"411000": "client", "401000": "fournisseur", "422000": "personnel"}

NATURES_COMPTE = ["charge", "produit", "tresorerie", "bilan", "tiers"]


# Creation ouverte a tous les roles depuis le 23/09/2026 (decision d'Afiya :
# une caissiere doit pouvoir creer le compte ou le tiers qui lui manque sans
# attendre le comptable). Puisque la saisie n'est plus reservee a quelqu'un
# qui connait le plan SYSCOHADA, le format est verifie ici, cote base, et non
# plus seulement laisse au jugement de l'utilisateur. L'auteur est trace dans
# le journal de l'application (hakili.log).
def ajouter_compte(compte, intitule, nature, tiers_obligatoire="non", depense_courante="non", par=None):
    compte = str(compte).strip()
    if not compte:
        raise ValueError("Le numero de compte est obligatoire.")
    # Tout le plan comptable Hakili est sur 6 chiffres (1040 comptes, aucune
    # exception) : un numero a 5 ou 7 chiffres serait un compte que Sage ne
    # reconnaitrait pas a l'import. Classe 1 a 9 (SYSCOHADA).
    if not re.fullmatch(r"[1-9][0-9]{5}", compte):
        raise ValueError("Le numero de compte doit comporter exactement 6 chiffres "
                         "et commencer par la classe (1 a 9), ex. 605100.")
    if not intitule or not str(intitule).strip():
        raise ValueError("L'intitule est obligatoire.")
    if nature not in NATURES_COMPTE:
        raise ValueError("Nature de compte inconnue.")
    if tiers_obligatoire not in ("oui", "non") or depense_courante not in ("oui", "non"):
        raise ValueError("Parametre de compte invalide.")
    with _connexion() as c, c.cursor() as cur:
        cur.execute("SELECT 1 FROM comptes WHERE compte = %s", (compte,))
        if cur.fetchone():
            raise ValueError("Ce compte existe deja.")
        cur.execute(
            "INSERT INTO comptes (compte, intitule, nature, tiers_obligatoire, nb_2024_2025, depense_courante) "
            "VALUES (%s, %s, %s, %s, 0, %s)",
            (compte, str(intitule).strip(), nature, tiers_obligatoire, depense_courante))
    logger.info("Compte %s (%s) cree par %s.", compte, str(intitule).strip(), par or "?")


def ajouter_utilisateur(identifiant, nom, role, centre, code_acces):
    identifiant = str(identifiant).strip().lower()
    if not identifiant:
        raise ValueError("L'identifiant est obligatoire.")
    if not str(nom or "").strip():
        raise ValueError("Le nom est obligatoire.")
    code_acces = str(code_acces or "").strip()
    if not code_acces:
        raise ValueError("Le code d'acces est obligatoire.")
    # Releve de 4 a 6 caracteres (10/09/2026) : un code a 4 chiffres n'offre
    # que 10 000 combinaisons, cassable en quelques jours de tentatives
    # automatisees meme avec le verrouillage anti brute-force ci-dessous.
    # Ne s'applique qu'aux comptes crees a partir de maintenant - les codes
    # deja en base, meme a 4 caracteres, continuent de fonctionner
    # (verifier_code_acces ne relit jamais cette regle a la connexion) ; a
    # faire changer manuellement aux utilisateurs concernes si besoin.
    if len(code_acces) < 6:
        raise ValueError("Le code d'acces doit comporter au moins 6 caracteres.")
    with _connexion() as c, c.cursor() as cur:
        cur.execute("SELECT 1 FROM utilisateurs WHERE lower(identifiant) = %s", (identifiant,))
        if cur.fetchone():
            raise ValueError("Cet identifiant existe deja.")
        cur.execute(
            "INSERT INTO utilisateurs (identifiant, nom, role, centre, code_acces, actif) "
            "VALUES (%s, %s, %s, %s, %s, 'oui')",
            (identifiant, str(nom).strip(), role, centre, _hacher_code(code_acces)))


def desactiver_utilisateur(identifiant):
    with _connexion() as c, c.cursor() as cur:
        cur.execute(
            "UPDATE utilisateurs SET actif = 'non', updated_at = now() WHERE lower(identifiant) = lower(%s)",
            (str(identifiant).strip(),))
        if cur.rowcount == 0:
            raise ValueError("Utilisateur introuvable.")


# --- authentification -----------------------------------------------------------
#
# Les codes d'acces ne sont plus compares en clair : ils sont haches avec
# bcrypt a la creation (ajouter_utilisateur). Les comptes crees avant cette
# migration (05/09/2026) ont encore leur code_acces en clair en base -
# verifier_code_acces() le reconnait (un hash bcrypt commence toujours par
# $2a$/$2b$/$2y$, jamais un code personnel reel) et tenter_connexion() les
# met a niveau silencieusement des le premier login reussi. Aucune coupure
# de service, aucun reset de code a organiser centre par centre.

SEUIL_TENTATIVES = 5
DUREE_VERROUILLAGE_MINUTES = 15


def _hacher_code(code):
    return bcrypt.hashpw(str(code).encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _code_est_hache(valeur):
    return isinstance(valeur, str) and valeur.startswith(("$2a$", "$2b$", "$2y$"))


def verifier_code_acces(code_saisi, valeur_stockee):
    """Compare un code saisi a la valeur stockee, qu'elle soit deja un hash
    bcrypt ou encore un code en clair (compte pas encore migre)."""
    code_saisi = str(code_saisi or "")
    valeur_stockee = str(valeur_stockee or "")
    if _code_est_hache(valeur_stockee):
        try:
            return bcrypt.checkpw(code_saisi.encode("utf-8"), valeur_stockee.encode("utf-8"))
        except ValueError:
            return False
    return code_saisi.strip() == valeur_stockee.strip()


def tenter_connexion(identifiant, centre, code):
    """Verifie identifiant/centre/code directement en base (jamais via le
    referentiel mis en cache cote session, qui peut avoir jusqu'a 0.5s de
    retard) et applique le verrouillage anti brute-force.

    Retourne (statut, utilisateur, minutes) ou statut vaut :
      "ok"         - connexion autorisee ; utilisateur est le dict a stocker
      "code"       - identifiant/centre/code incorrect
      "inactif"    - compte desactive
      "verrouille" - trop de tentatives, reessayer dans `minutes` minutes
    """
    identifiant = str(identifiant or "").strip().lower()
    with _connexion() as c, c.cursor() as cur:
        # FOR UPDATE (10/09/2026) : sans lui, deux tentatives lancees en
        # parallele sur le meme compte lisent le meme "tentatives_echouees"
        # avant que l'une des deux n'ait ecrit la sienne, et le compteur
        # avance moins vite que le nombre reel d'essais - exactement le
        # scenario d'un script de brute-force, qui envoie ses tentatives en
        # parallele plutot qu'une par une. Le verrou porte sur cette seule
        # ligne (un identifiant+centre precis) : il serialise les tentatives
        # concurrentes sur UN compte, sans jamais bloquer la connexion d'un
        # autre utilisateur pendant ce temps.
        cur.execute(
            "SELECT identifiant, nom, role, centre, code_acces, actif, "
            "tentatives_echouees, verrouille_jusqu_a, now() FROM utilisateurs "
            "WHERE lower(identifiant) = %s AND centre = %s FOR UPDATE",
            (identifiant, centre))
        row = cur.fetchone()
        if row is None:
            return ("code", None, 0)
        (ident, nom, role, centre_u, code_stocke, actif,
         tentatives, verrouille_jusqu_a, maintenant) = row

        if verrouille_jusqu_a is not None and verrouille_jusqu_a > maintenant:
            minutes = max(1, int((verrouille_jusqu_a - maintenant).total_seconds() // 60) + 1)
            return ("verrouille", None, minutes)

        if not verifier_code_acces(code, code_stocke):
            tentatives = (tentatives or 0) + 1
            if tentatives >= SEUIL_TENTATIVES:
                cur.execute(
                    "UPDATE utilisateurs SET tentatives_echouees = 0, "
                    "verrouille_jusqu_a = now() + make_interval(mins => %s) WHERE identifiant = %s",
                    (DUREE_VERROUILLAGE_MINUTES, ident))
                logger.warning("Compte %s verrouille %s min apres %s echecs (centre %s).",
                                ident, DUREE_VERROUILLAGE_MINUTES, tentatives, centre)
                return ("verrouille", None, DUREE_VERROUILLAGE_MINUTES)
            cur.execute(
                "UPDATE utilisateurs SET tentatives_echouees = %s WHERE identifiant = %s",
                (tentatives, ident))
            logger.warning("Echec de connexion pour %s (centre %s, tentative %s/%s).",
                            ident, centre, tentatives, SEUIL_TENTATIVES)
            return ("code", None, 0)

        if str(actif) != "oui":
            logger.warning("Tentative de connexion sur le compte desactive %s.", ident)
            return ("inactif", None, 0)

        cur.execute(
            "UPDATE utilisateurs SET tentatives_echouees = 0, verrouille_jusqu_a = NULL "
            "WHERE identifiant = %s",
            (ident,))
        if not _code_est_hache(code_stocke):
            cur.execute("UPDATE utilisateurs SET code_acces = %s WHERE identifiant = %s",
                        (_hacher_code(code), ident))
            logger.info("Code d'acces de %s migre vers bcrypt.", ident)
        logger.info("Connexion de %s (centre %s, role %s).", ident, centre_u, role)
        return ("ok", {"identifiant": ident, "nom": nom, "role": role,
                        "centre": centre_u, "actif": "oui"}, 0)


def ajouter_tiers(code, intitule, collectif, par=None):
    """Cree un tiers, actif immediatement (pas de validation par le
    comptable, decision du 23/09/2026). Renvoie le code reellement cree.

    Convention du plan tiers Hakili, respectee par les 1450 tiers existants :
    le code commence par les 3 chiffres de son collectif (411KABORE,
    401SONABEL...). Si l'utilisateur tape seulement le nom (KABORE), le
    prefixe est ajoute pour lui ; s'il tape un autre prefixe que celui du
    collectif choisi (401... pour un eleve), c'est une erreur a signaler, pas
    a corriger en silence."""
    code = re.sub(r"\s+", "", str(code or "")).upper()
    intitule = str(intitule or "").strip().upper()
    if collectif not in TYPES_COLLECTIF:
        raise ValueError("Compte collectif inconnu.")
    if not code:
        raise ValueError("Le code tiers est obligatoire.")
    if not intitule:
        raise ValueError("L'intitule est obligatoire.")
    pref = str(collectif)[:3]
    if not code[:1].isdigit():
        code = pref + code
    elif not code.startswith(pref):
        raise ValueError(f"Un tiers rattache au collectif {collectif} doit avoir un code "
                         f"commencant par {pref} (ex. {pref}{_slug(intitule)}).")
    if len(code) <= 3:
        raise ValueError("Le code tiers doit contenir un nom apres le prefixe.")
    if not re.fullmatch(r"[0-9A-Z_-]+", code):
        raise ValueError("Le code tiers ne doit contenir que des lettres sans accent et des chiffres.")
    with _connexion() as c, c.cursor() as cur:
        cur.execute("SELECT 1 FROM tiers WHERE upper(code_tiers) = upper(%s)", (code,))
        if cur.fetchone():
            raise ValueError("Ce code tiers existe deja.")
        type_ = TYPES_COLLECTIF[collectif]
        cur.execute(
            "INSERT INTO tiers (code_tiers, intitule, compte_collectif, type, actif, actif_annee) "
            "VALUES (%s, %s, %s, %s, 'oui', 'oui')",
            (code, intitule, collectif, type_))
    logger.info("Tiers %s (%s) cree par %s.", code, intitule, par or "?")
    return code


# --- creation / reactivation a la volee (saisie libre d'un nom) ---------------
# Meme logique qu'en version Excel : un nom qui correspond deja a un code ou
# un intitule connu (actif ou non) sous le meme prefixe est repris tel quel,
# jamais duplique ; sinon un nouveau code est genere selon la convention.


def _slug(nom, longueur_max=18):
    nom = unicodedata.normalize("NFKD", str(nom)).encode("ascii", "ignore").decode("ascii")
    nom = re.sub(r"[^A-Za-z]", "", nom).upper()
    return nom[:longueur_max] or "TIERS"


def code_tiers_candidat(valeur, pref, ref):
    """Calcule, sans rien ecrire, le code qui serait utilise. Sert a
    l'apercu en direct ; la decision definitive revient a resoudre_tiers()."""
    valeur = str(valeur or "").strip()
    if not valeur:
        return ""
    tiers = ref["tiers"]
    sous = tiers[tiers["code_tiers"].str.startswith(pref)]
    m = sous[sous["code_tiers"].str.upper() == valeur.upper()]
    if len(m):
        return m.iloc[0]["code_tiers"]
    m = sous[sous["intitule"].str.upper() == valeur.upper()]
    if len(m):
        return m.iloc[0]["code_tiers"]
    base = pref + _slug(valeur)
    code = base
    existants = set(sous["code_tiers"].str.upper())
    n = 2
    while code.upper() in existants:
        code = f"{base}{n}"
        n += 1
    return code


def resoudre_tiers(valeur, pref, collectif):
    """Version autoritaire, appelee au moment de l'enregistrement reel d'une
    piece. Cree ou reactive le tiers si necessaire.

    Corrige le 22/09/2026 (m5 de l'audit du 18/09) : le FOR UPDATE portait
    avant sur TOUTES les lignes du prefixe (tous les eleves pour '411', par
    exemple) le temps de la resolution, ce qui serialisait chaque
    encaissement de chaque centre entre eux. Remplace par une lecture SANS
    verrou suivie d'un INSERT ... ON CONFLICT DO NOTHING : la cle primaire
    code_tiers reste l'unique garde-fou contre un doublon, exactement comme
    Postgres l'impose deja pour toute autre insertion concurrente. Si deux
    caisses creent EXACTEMENT le meme nouveau tiers au meme instant, l'une
    des deux insertions est rejetee par la cle primaire et la fonction relit
    une fois de plus pour reprendre le code qui vient d'etre cree - un cas
    rarissime, traite sans jamais bloquer la lecture des autres centres.

    Reste sur sa propre connexion, separee de celle d'enregistrer_operation()
    qui suit immediatement en pratique : un enregistrement qui echouerait
    ensuite peut donc laisser un tiers neuf orphelin en base (deuxieme moitie
    du point m5, non traitee ici - fusionner les deux transactions
    demanderait de faire remonter la resolution des tiers a l'interieur de
    enregistrer_operation() elle-meme, donc de deplacer une partie de ce que
    logic/modeles.py fait aujourd'hui ; changement plus large, a faire a part
    avec un environnement de test complet)."""
    valeur = str(valeur or "").strip()
    if not valeur:
        return ""
    with _connexion() as c, c.cursor() as cur:
        for _tentative in range(5):
            cur.execute(
                "SELECT code_tiers, intitule, actif_annee FROM tiers "
                "WHERE code_tiers ILIKE %s || '%%'",
                (pref,))
            lignes = cur.fetchall()
            for code, nom, actif_annee in lignes:
                if code.upper() == valeur.upper() or (nom or "").upper() == valeur.upper():
                    if str(actif_annee or "").lower() != "oui":
                        cur.execute(
                            "UPDATE tiers SET actif_annee = 'oui', updated_at = now() "
                            "WHERE code_tiers = %s", (code,))
                    return code

            existants = {code.upper() for code, _, _ in lignes}
            base = pref + _slug(valeur)
            code = base
            n = 2
            while code.upper() in existants:
                code = f"{base}{n}"
                n += 1
            type_ = TYPES_COLLECTIF.get(collectif, "client")
            cur.execute(
                "INSERT INTO tiers (code_tiers, intitule, compte_collectif, type, actif, actif_annee) "
                "VALUES (%s, %s, %s, %s, 'oui', 'oui') ON CONFLICT (code_tiers) DO NOTHING",
                (code, valeur.upper(), collectif, type_))
            if cur.rowcount == 1:
                return code
            # Conflit : une autre session a cree ce code entre notre lecture
            # et notre ecriture. On boucle : la ligne concurrente sera alors
            # visible et traitee soit comme le meme tiers (meme nom), soit un
            # code suivant sera calcule.
        raise RuntimeError(
            f"Impossible de resoudre le tiers '{valeur}' apres plusieurs tentatives "
            "(forte concurrence sur ce prefixe) : reessayer.")


# Dernieres lignes du compte 411000 d'un tiers, les plus recentes d'abord.
# Sert au bloc historique du formulaire d'encaissement (spec 2026, §3.2) :
# la caissiere y retrouve les derniers mouvements sans que le systeme ait
# besoin de connaitre un tarif ou un statut - l'humain decide, le systeme
# se contente d'afficher ce qu'il sait deja.
def dernieres_lignes_tiers(code_tiers, limite=12):
    if not code_tiers:
        return pd.DataFrame(columns=["date_piece", "libelle", "debit", "credit"])
    sql = ("SELECT date_piece, libelle, debit, credit FROM ecritures "
           "WHERE compte = '411000' AND code_tiers = %s "
           "ORDER BY date_piece DESC, id_ligne DESC LIMIT %s")
    return _lire_df(sql, params=(code_tiers, limite))


def nouvelle_annee_academique():
    """A utiliser a la rentree : les tiers de l'annee ecoulee disparaissent
    des menus de saisie (actif_annee='non'), sans qu'aucune ligne ne soit
    supprimee ni modifiee. Un tiers qui revient est reactive avec son code
    d'origine des qu'il est retape, via resoudre_tiers()."""
    with _connexion() as c, c.cursor() as cur:
        cur.execute("UPDATE tiers SET actif_annee = 'non', updated_at = now() WHERE actif_annee <> 'non'")
        return cur.rowcount


# --- ecritures -----------------------------------------------------------------


def _normaliser_lecture(df):
    if df is None or len(df) == 0:
        d = pd.DataFrame({c: pd.Series(dtype="object") for c in COLONNES})
        d["debit"] = pd.Series(dtype="float64")
        d["credit"] = pd.Series(dtype="float64")
        return d
    d = df.copy()
    d["date_piece"] = d["date_piece"].astype(str)
    for col in ("saisi_le", "valide_le", "exporte_le"):
        d[col] = d[col].apply(lambda x: "" if pd.isna(x) else str(x))
    for c in [c for c in COLONNES if c not in ("debit", "credit", "valeurs_json")]:
        d[c] = d[c].apply(lambda x: "" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x))
    d["valeurs_json"] = d["valeurs_json"].apply(
        lambda x: "" if x is None else (x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, default=str)))
    d["debit"] = pd.to_numeric(d["debit"], errors="coerce").fillna(0.0)
    d["credit"] = pd.to_numeric(d["credit"], errors="coerce").fillna(0.0)
    return d[COLONNES].reset_index(drop=True)


def lire_ecritures(centre=None, mois=None):
    where, params = [], []
    if centre:
        where.append("centre = %s")
        params.append(centre)
    if mois:
        where.append("to_char(date_piece, 'YYYYMM') = %s")
        params.append(mois)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"SELECT * FROM ecritures {clause} ORDER BY date_piece, id_piece"
    return _normaliser_lecture(_lire_df(sql, params=params or None))


def mois_de(date_piece):
    return pd.to_datetime(date_piece).strftime("%Y%m")


# --- numerotation --------------------------------------------------------------
#
# Incrementation atomique via UPSERT : deux pieces enregistrees au meme
# instant depuis deux centres differents ne peuvent jamais recevoir le meme
# numero, meme sans verrou explicite - c'est Postgres qui serialise les deux
# UPDATE sur la meme ligne de compteurs.


def _prochain_numero(cur, cle, pas=1):
    cur.execute(
        "INSERT INTO compteurs (cle, valeur) VALUES (%s, %s) "
        "ON CONFLICT (cle) DO UPDATE SET valeur = compteurs.valeur + %s "
        "RETURNING valeur",
        (cle, pas, pas))
    return cur.fetchone()[0]


def numero_provisoire(centre, date_piece):
    mois = mois_de(date_piece)
    with _connexion() as c, c.cursor() as cur:
        n = _prochain_numero(cur, f"prov:{centre}:{mois}")
    return f"{centre}-{mois[2:6]}-{n:03d}"


def prefixe_piece(journal, ref=None):
    if ref is None:
        ref = lire_referentiel()
    j = ref["journaux"]
    v = j.loc[j["journal"] == journal, "prefixe_piece"]
    if len(v) and str(ou(v.iloc[0], "")).strip():
        return str(v.iloc[0]).strip()
    return str(journal)


def numero_definitif(journal, date_piece):
    mois = mois_de(date_piece)
    with _connexion() as c, c.cursor() as cur:
        n = _prochain_numero(cur, f"def:{journal}:{mois}")
    return f"{prefixe_piece(journal)}{mois[2:6]}{n:03d}"


# --- enregistrement d'une piece --------------------------------------------------


def _nouvelle_reference_transfert(cur, date_piece):
    """TRF-AAAAMM-0001, numerotee par le meme compteur atomique que les numeros
    de piece : deux centres qui saisissent au meme instant ne peuvent pas
    obtenir la meme reference, sans aucun verrou applicatif."""
    mois = mois_de(date_piece)
    n = _prochain_numero(cur, f"trf:{mois}")
    return f"TRF-{mois}-{n:04d}"


def _sortie_a_apparier(cur, centre_donateur, centre_destinataire):
    """Reference de la plus ancienne sortie de `centre_donateur` vers
    `centre_destinataire` qui n'a pas encore d'entree en face.

    Appariement au premier entre, premier sorti, SANS tenir compte du montant :
    c'est volontaire. Si un centre remet 50 000 F et que le beneficiaire n'en
    compte que 40 000, les deux faces doivent se rapprocher pour que l'ecart de
    10 000 F apparaisse comme un ecart. Exiger l'egalite des montants les
    laisserait orphelines toutes les deux, et l'anomalie reelle - il manque de
    l'argent - deviendrait deux anomalies de forme.

    Renvoie "" si aucune sortie n'attend : l'entree est alors orpheline, ce que
    le rapprochement signale."""
    cur.execute(
        "SELECT s.reference_transfert FROM ecritures s "
        "WHERE s.modele = %s AND s.compte = %s AND s.debit > 0 "
        "  AND s.centre = %s AND s.centre_contrepartie = %s "
        "  AND s.reference_transfert <> '' "
        "  AND NOT EXISTS (SELECT 1 FROM ecritures e "
        "                  WHERE e.reference_transfert = s.reference_transfert "
        "                    AND e.compte = %s AND e.credit > 0) "
        "ORDER BY s.date_piece, s.id_piece LIMIT 1 FOR UPDATE OF s SKIP LOCKED",
        (MODELE_TRANSFERT_INTERNE, COMPTE_VIREMENTS_FONDS,
         centre_donateur, centre_destinataire, COMPTE_VIREMENTS_FONDS))
    r = cur.fetchone()
    return r[0] if r else ""


def _metadonnees_transfert(cur, centre, modele, valeurs, date_piece, ancienne=None):
    """(reference, centre_contrepartie) d'une piece de transfert interne.

    Le SENS n'est pas un champ du formulaire : il se deduit de qui saisit. Si
    le centre connecte est le donateur, il enregistre une sortie et recoit une
    reference neuve. S'il est le destinataire, il enregistre une entree et
    reprend la reference de la sortie qui l'attend. Un centre ne peut donc
    jamais saisir un transfert entre deux autres centres."""
    if modele != MODELE_TRANSFERT_INTERNE or not valeurs:
        return "", ""
    donateur = str(valeurs.get("centre_donateur") or "").strip()
    destinataire = str(valeurs.get("centre_destinataire") or "").strip()
    if not donateur or not destinataire:
        raise ValueError("Transfert interne : le centre donateur et le centre destinataire sont obligatoires.")
    if donateur == destinataire:
        raise ValueError("Transfert interne : le centre donateur et le centre destinataire doivent differer.")
    if centre not in (donateur, destinataire):
        raise ValueError(
            "Transfert interne : votre centre doit etre le donateur ou le destinataire. "
            "Un centre n'enregistre jamais un transfert entre deux autres centres.")
    if centre == donateur:
        # Correction d'une sortie (remplacer_piece) : on garde sa reference
        # si le destinataire n'a pas change - l'entree deja rapprochee en face
        # reste rapprochee, au lieu de pointer vers une reference disparue.
        if ancienne and ancienne[0] and ancienne[1] == destinataire:
            return ancienne[0], destinataire
        return _nouvelle_reference_transfert(cur, date_piece), destinataire
    return _sortie_a_apparier(cur, donateur, destinataire), donateur


def _inserer_operation(cur, pieces, centre, date_piece, modele, utilisateur, note, valeurs,
                       ancienne_ref=None, reserves=None):
    """Insere les lignes d'une operation dans la transaction du curseur recu,
    sans ouvrir ni fermer de connexion elle-meme. Factorisee le 22/09/2026
    (M3 de l'audit du 18/09) pour etre partagee par enregistrer_operation()
    (ecriture neuve, sa propre transaction) et remplacer_piece() (correction :
    ecriture neuve ET suppression de l'ancienne, dans LA MEME transaction)."""
    mois = mois_de(date_piece)
    horo = datetime.now().strftime("%Y%m%d%H%M%S")
    lien = f"L{horo}-{random.randint(100, 999)}" if len(pieces) > 1 else ""
    v_json = None
    if valeurs:
        try:
            v_json = json.dumps(valeurs, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            v_json = None
    nums = []
    reference, contrepartie = _metadonnees_transfert(cur, centre, modele, valeurs, date_piece,
                                                     ancienne=ancienne_ref)
    # reserves : {journal: [numeros]} gardes par une piece corrigee (voir
    # remplacer_piece). Chaque numero n'est rendu qu'une fois.
    reserves = {j: list(v) for j, v in (reserves or {}).items()}
    for i_p, p in enumerate(pieces):
        n = _prochain_numero(cur, f"prov:{centre}:{mois}")
        num = f"{centre}-{mois[2:6]}-{n:03d}"
        idp = f"{centre}-{horo}-{n}"
        dispo = reserves.get(p["journal"]) or []
        reserve = dispo.pop(0) if dispo else ""
        L = p["lignes"].reset_index(drop=True)
        for i, row in L.iterrows():
            cur.execute(
                "INSERT INTO ecritures (id_ligne, id_piece, id_lien, num_provisoire, num_definitif, "
                "num_reserve, journal, centre, date_piece, compte, code_tiers, libelle, debit, credit, "
                "modele, saisi_par, saisi_le, statut, observation, valeurs_json, "
                "reference_transfert, centre_contrepartie) VALUES "
                "(%s,%s,%s,%s,'',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),'saisie',%s,%s,%s,%s)",
                (f"{idp}-{i + 1}", idp, lien, num, reserve, p["journal"], centre, str(date_piece),
                 row["compte"], row["code_tiers"], row["libelle"], float(row["debit"]), float(row["credit"]),
                 modele, utilisateur, str(note or "").strip(), v_json,
                 reference, contrepartie))
        nums.append(num)
    return nums


def enregistrer_operation(pieces, centre, date_piece, modele, utilisateur, note="", valeurs=None):
    # Corrige le 22/09/2026 (M2 de l'audit du 18/09) : l'equilibre debit/
    # credit n'etait verifie que cote app.py, avant l'appel. Un appel direct
    # a cette fonction (import_historique.py, un futur script) ne passait par
    # aucun controle. La contrainte en base (sql/schema.sql, migration
    # 2026-09-22) reste le vrai filet ; celui-ci n'existe que pour renvoyer un
    # message lisible au lieu d'une violation de contrainte brute.
    if not md.operation_equilibree(pieces):
        raise ValueError(
            "Operation desequilibree ou incomplete : aucune ecriture n'a ete enregistree.")
    with _connexion() as c, c.cursor() as cur:
        nums = _inserer_operation(cur, pieces, centre, date_piece, modele, utilisateur, note, valeurs)
    logger.info("Piece(s) enregistree(s) par %s (centre %s, modele %s) : %s",
                utilisateur, centre, modele, ", ".join(nums))
    return nums


def remplacer_piece(ancien_id, pieces, centre, date_piece, modele, utilisateur, note="", valeurs=None):
    """Corrige une piece non validee ('saisie' ou 'a_corriger') : enregistre la nouvelle ET retire
    l'ancienne dans UNE SEULE transaction (corrige le 22/09/2026, M3 de
    l'audit du 18/09). Avant, app.py appelait enregistrer_operation() puis
    supprimer_piece() separement : si la seconde echouait (piece deja
    validee entre-temps par le comptable, connexion coupee), la nouvelle
    piece restait en base A COTE de l'ancienne, sans qu'aucun ecran ne
    permette de le rattraper.

    Revalide que l'ancienne piece est toujours non validee juste avant de la
    retirer : si elle a change de statut ou disparu entre-temps, toute la
    transaction est annulee (rien n'est enregistre) plutot que de creer la
    piece neuve a moitie.

    23/09/2026 : ouverte aussi aux pieces 'saisie' (bouton "Corriger la
    piece" du Brouillard et de la Validation). Deux consequences :
      - les lignes sont verrouillees (FOR UPDATE) le temps de la
        transaction : un validateur qui valide la meme piece au meme instant
        attend la fin de la correction, puis ne trouve plus rien a valider -
        jamais une piece validee effacee par une correction concurrente ;
      - la piece corrigee reste dans le centre de la piece d'origine, meme
        quand c'est le comptable du siege qui corrige : le parametre
        `centre` n'est plus qu'une valeur de repli."""
    if not md.operation_equilibree(pieces):
        raise ValueError(
            "Operation desequilibree ou incomplete : aucune ecriture n'a ete enregistree.")
    with _connexion() as c, c.cursor() as cur:
        ids = _ids_lies(cur, [ancien_id])
        cur.execute("SELECT id_piece, statut, centre, modele, reference_transfert, centre_contrepartie "
                    "FROM ecritures WHERE id_piece = ANY(%s) FOR UPDATE", (ids,))
        verrou = cur.fetchall()
        statuts = {r[1] for r in verrou}
        if not statuts:
            raise ValueError("Piece a corriger introuvable : elle a peut-etre deja ete traitee.")
        if statuts - {"saisie", "a_corriger"}:
            raise ValueError(
                "La piece a corriger a ete validee, supprimee ou exportee entre-temps : "
                "la correction est annulee, rien n'a ete enregistre. "
                "Rafraichir l'ecran et reessayer.")
        origine = next((r for r in verrou if r[0] == ancien_id), verrou[0])
        centre = origine[2] or centre
        ancienne_ref = None
        if origine[3] == MODELE_TRANSFERT_INTERNE and origine[2] and origine[4]:
            # Seule une SORTIE garde sa reference (voir _metadonnees_transfert) :
            # meme ligne distinctive que _sortie_a_apparier (585000 au debit).
            cur.execute("SELECT 1 FROM ecritures WHERE id_piece = %s AND compte = %s AND debit > 0",
                        (origine[0], COMPTE_VIREMENTS_FONDS))
            if cur.fetchone():
                ancienne_ref = (origine[4], origine[5])
        # L'ancienne piece est archivee puis retiree AVANT d'inserer la
        # nouvelle (toujours dans la meme transaction, donc sans risque de
        # perte) : pour un transfert interne, la sortie qu'elle rapprochait
        # redevient ainsi disponible pour la piece corrigee.
        # Numeros definitifs gardes par l'ancienne piece (renvoyee apres
        # validation) : transmis a la piece corrigee, par journal.
        cur.execute(
            "SELECT DISTINCT id_piece, journal, num_reserve FROM ecritures "
            "WHERE id_piece = ANY(%s) AND num_reserve <> '' ORDER BY id_piece", (ids,))
        reserves = {}
        for _, j, r in cur.fetchall():
            reserves.setdefault(j, []).append(r)
        cur.execute(
            "SELECT id_piece, row_to_json(ecritures) FROM ecritures WHERE id_piece = ANY(%s)", (ids,))
        lignes = cur.fetchall()
        cur.executemany(
            "INSERT INTO suppressions_ecritures (id_piece, contenu, supprime_par) VALUES (%s, %s, %s)",
            [(idp, psycopg2.extras.Json(contenu), utilisateur) for idp, contenu in lignes])
        cur.execute("DELETE FROM ecritures WHERE id_piece = ANY(%s)", (ids,))
        nums = _inserer_operation(cur, pieces, centre, date_piece, modele, utilisateur, note, valeurs,
                                  ancienne_ref=ancienne_ref, reserves=reserves)
    logger.info("Piece(s) %s : correction de %s par %s (ancienne piece retiree dans la meme transaction).",
                ", ".join(nums), ancien_id, utilisateur)
    return nums


def _ids_lies(cur, ids):
    """Version interne d'avec_liees(), reutilisant un curseur/une transaction
    deja ouverts par l'appelant. Corrige le 22/09/2026 (m1 de l'audit du
    18/09) : supprimer_piece, valider_pieces, rejeter_pieces et
    marquer_exporte appelaient toutes avec_liees() depuis l'INTERIEUR de leur
    propre transaction, ce qui empruntait deux connexions du pool au lieu
    d'une (maxconn=20 pouvait s'epuiser sous charge) et lisait sur une
    transaction separee, donc invisible aux ecritures non encore validees de
    la transaction appelante."""
    ids = list(ids)
    if not ids:
        return ids
    cur.execute(
        "SELECT DISTINCT id_piece FROM ecritures WHERE id_lien IN "
        "(SELECT DISTINCT id_lien FROM ecritures WHERE id_piece = ANY(%s) AND id_lien <> '')",
        (list(ids),))
    extra = [r[0] for r in cur.fetchall()]
    return list(dict.fromkeys(list(ids) + extra))


def avec_liees(ids, d=None):
    """Version publique : ouvre sa propre connexion. A n'utiliser que hors
    d'une transaction deja en cours ; depuis l'interieur d'une fonction de ce
    module, preferer _ids_lies(cur, ids)."""
    ids = list(ids)
    if not ids:
        return ids
    with _connexion() as c, c.cursor() as cur:
        return _ids_lies(cur, ids)


def supprimer_piece(id_piece, utilisateur="?"):
    """Supprime une ou plusieurs pieces non encore validees. Le contenu
    integral de chaque piece est conserve dans suppressions_ecritures avant
    le DELETE (avec l'auteur et l'horodatage) : contrairement a un simple
    DELETE, une piece supprimee reste donc retracable a posteriori - ce que
    l'ancienne version ne permettait pas."""
    if not isinstance(id_piece, (list, tuple, pd.Index)):
        id_piece = [id_piece]
    with _connexion() as c, c.cursor() as cur:
        ids = _ids_lies(cur, list(id_piece))
        cur.execute("SELECT DISTINCT statut FROM ecritures WHERE id_piece = ANY(%s)", (ids,))
        statuts = {r[0] for r in cur.fetchall()}
        if not statuts:
            raise ValueError("Piece introuvable.")
        if statuts - {"saisie", "a_corriger"}:
            raise ValueError("Une piece validee ou exportee ne peut plus etre supprimee.")
        cur.execute(
            "SELECT id_piece, row_to_json(ecritures) FROM ecritures WHERE id_piece = ANY(%s)",
            (ids,))
        lignes = cur.fetchall()
        cur.executemany(
            "INSERT INTO suppressions_ecritures (id_piece, contenu, supprime_par) VALUES (%s, %s, %s)",
            [(idp, psycopg2.extras.Json(contenu), utilisateur) for idp, contenu in lignes])
        cur.execute("SELECT DISTINCT num_reserve FROM ecritures "
                    "WHERE id_piece = ANY(%s) AND num_reserve <> ''", (ids,))
        perdus = [r[0] for r in cur.fetchall()]
        cur.execute("DELETE FROM ecritures WHERE id_piece = ANY(%s)", (ids,))
        logger.info("Piece(s) supprimee(s) par %s : %s", utilisateur, ", ".join(ids))
        if perdus:
            logger.warning("Numero(s) definitif(s) abandonne(s) par la suppression : %s", ", ".join(perdus))
        return len(ids)


def valider_pieces(ids, utilisateur, autoriser_attente=False):
    """Valide et numerote les pieces au statut 'saisie' parmi `ids`.

    Seule une piece 'saisie' peut etre validee : une piece renvoyee pour
    correction ('a_corriger') attend une resaisie par la caissiere, et ne
    doit surtout pas etre validee telle quelle. Cette regle ne change pas.

    Ce qui change (12/09/2026) : la fonction ne se contente plus de renvoyer
    un compteur. Elle rend compte de ce qu'elle a fait ET de ce qu'elle a
    ECARTE, avec le statut qui l'explique. L'ancienne version renvoyait le
    seul nombre de pieces validees ; l'appelant affichait "1 piece(s)
    validee(s)" apres une selection de cinq, et les quatre autres
    disparaissaient du resultat sans un mot - le validateur croyait son lot
    termine et n'avait aucune raison de relancer les caissieres concernees.

    23/09/2026 : une piece qui mouvemente encore le compte d'attente
    (471000) n'est plus validee - elle doit d'abord etre reclassee sur le bon
    compte (onglet Controles). Elle est ecartee sous la cle "compte_attente",
    avec sa jumelle si elle fait partie d'une operation liee (on ne valide
    jamais une paire a moitie). app.py bloque deja ce cas avant l'appel (via
    controler()) ; ce second filet protege tout autre appelant.
    autoriser_attente=True est reserve a import_historique.py, qui reprend
    des brouillards deja passes en comptabilite.

    Renvoie un dict :
        {"validees": [id_piece...], "ignorees": {statut: [id_piece...]}}
    """
    with _connexion() as c, c.cursor() as cur:
        ids = _ids_lies(cur, ids)
        # On lit TOUTES les pieces demandees, pas seulement les validables :
        # c'est ce qui permet de dire pourquoi les autres sont ecartees.
        # 25/09/2026 : les numeros suivent la DATE, puis le CENTRE (ordre
        # fixe de centres.ordre : SIAO, Tampouy, Saaba, Pissy, Nagrin), puis
        # l'heure de saisie. Dans Sage, ou le journal se lit par date, les
        # numeros d'un lot se suivent donc sans retour en arriere. Un centre
        # absent du lot est simplement saute. Une piece oubliee et validee
        # plus tard prend le numero suivant, comme dans Sage.
        cur.execute(
            "SELECT e.id_piece, e.journal, e.date_piece, e.statut, min(e.saisi_le) AS premiere_saisie, "
            "       max(e.num_reserve) AS reserve, coalesce(min(c.ordre), 99) AS ordre_centre "
            "FROM ecritures e LEFT JOIN centres c ON c.code_centre = e.centre "
            "WHERE e.id_piece = ANY(%s) "
            "GROUP BY e.id_piece, e.journal, e.date_piece, e.statut, e.centre "
            "ORDER BY e.date_piece, ordre_centre, e.centre, premiere_saisie, e.id_piece",
            (ids,))
        toutes = [(i, j, d, s, reserve) for i, j, d, s, _, reserve, _ in cur.fetchall()]
        if not toutes:
            raise ValueError("Aucune piece a valider.")
        en_attente = set()
        if not autoriser_attente:
            cur.execute(
                "SELECT DISTINCT e.id_piece FROM ecritures e WHERE e.id_lien <> '' AND e.id_lien IN "
                "(SELECT id_lien FROM ecritures WHERE id_piece = ANY(%s) AND compte = %s) "
                "UNION SELECT DISTINCT id_piece FROM ecritures WHERE id_piece = ANY(%s) AND compte = %s",
                (ids, md.COMPTE_ATTENTE, ids, md.COMPTE_ATTENTE))
            en_attente = {r[0] for r in cur.fetchall()}
        pieces = [(i, j, d, r) for i, j, d, s, r in toutes if s == "saisie" and i not in en_attente]
        ignorees = {}
        for i, _, _, s, _ in toutes:
            if s != "saisie":
                ignorees.setdefault(s, []).append(i)
            elif i in en_attente:
                ignorees.setdefault("compte_attente", []).append(i)
        if not pieces:
            detail = ", ".join(
                f"{len(v)} sur le compte d'attente {md.COMPTE_ATTENTE}, a reclasser avant validation"
                if k == "compte_attente" else f"{len(v)} au statut '{k}'"
                for k, v in sorted(ignorees.items()))
            raise ValueError(f"Aucune piece a valider ({detail}).")
        # Prefixes lus une fois, sur la transaction en cours (avant : tout le
        # referentiel relu pour chaque piece, sur une seconde connexion).
        cur.execute("SELECT journal, prefixe_piece FROM journaux")
        prefixes = {j: (str(p or "").strip() or j) for j, p in cur.fetchall()}
        validees = []
        for idp, journal, date_piece, reserve in pieces:
            mois = mois_de(date_piece)
            debut = f"{prefixes.get(journal, journal)}{mois[2:6]}"
            # Piece renvoyee puis revalidee : elle reprend son numero, s'il
            # appartient toujours au meme journal et au meme mois.
            if reserve and reserve.startswith(debut) and reserve[len(debut):].isdigit():
                num_def = reserve
            else:
                if reserve:
                    logger.warning("Numero %s abandonne par la piece %s (journal ou mois modifie).",
                                   reserve, idp)
                n = _prochain_numero(cur, f"def:{journal}:{mois}")
                num_def = f"{debut}{n:03d}"
            cur.execute(
                "UPDATE ecritures SET num_definitif = %s, num_reserve = '', statut = 'validee', "
                "valide_par = %s, valide_le = now() WHERE id_piece = %s",
                (num_def, utilisateur, idp))
            validees.append(idp)
    if ignorees:
        logger.info("%s piece(s) validee(s) par %s ; %s ecartee(s) : %s.",
                    len(validees), utilisateur, sum(len(v) for v in ignorees.values()),
                    ", ".join(f"{k}={len(v)}" for k, v in sorted(ignorees.items())))
    else:
        logger.info("%s piece(s) validee(s) par %s.", len(validees), utilisateur)
    return {"validees": validees, "ignorees": ignorees}


def rejeter_pieces(ids, motif, utilisateur):
    """Renvoie des pieces au centre pour correction.

    Une piece deja EXPORTEE ne peut plus etre renvoyee (corrige le
    15/09/2026). L'ancienne version ne regardait aucun statut : une piece
    figurant deja dans un fichier importe dans Sage repassait en
    'a_corriger', revenait dans le brouillard de la caissiere, etait
    corrigee et reenregistree - l'operation se retrouvait comptabilisee
    deux fois dans le livre officiel, sans le moindre message pour le
    signaler. Elle gardait au passage son num_definitif, son valide_par et
    son exporte_le, ce qui rendait la piste d'audit incoherente : une piece
    "exportee le..." et "a corriger" en meme temps.

    Une piece 'validee' reste renvoyable : le comptable a le droit de se
    raviser tant que l'export n'a pas eu lieu. Apres l'export, la correction
    passe par une ecriture d'extourne, jamais par une reprise de la piece.
    """
    with _connexion() as c, c.cursor() as cur:
        ids = _ids_lies(cur, ids)
        cur.execute("SELECT DISTINCT statut FROM ecritures WHERE id_piece = ANY(%s)", (ids,))
        statuts = {r[0] for r in cur.fetchall()}
        if not statuts:
            raise ValueError("Piece introuvable.")
        if "exportee" in statuts:
            raise ValueError(
                "Une piece deja exportee vers Sage ne peut plus etre renvoyee pour "
                "correction : elle est deja dans le livre officiel. Corriger par une "
                "ecriture d'extourne.")
        # 25/09/2026 : le numero definitif d'une piece validee est mis de cote
        # (num_reserve) et lui sera rendu a la revalidation - plus de trou.
        cur.execute(
            "UPDATE ecritures SET statut = 'a_corriger', observation = %s, "
            "num_reserve = CASE WHEN num_definitif <> '' THEN num_definitif ELSE num_reserve END, "
            "num_definitif = '', valide_par = '', valide_le = NULL "
            "WHERE id_piece = ANY(%s)",
            (f"{utilisateur} : {motif}", ids))
        cur.execute("SELECT count(DISTINCT id_piece) FROM ecritures WHERE id_piece = ANY(%s)", (ids,))
        n = cur.fetchone()[0]
    logger.info("%s piece(s) renvoyee(s) par %s (motif : %s).", n, utilisateur, motif)
    return n


def marquer_exporte(ids):
    """Marque 'exportee' les seules pieces reellement exportables.

    Le filtre "AND statut = 'validee'" est ajoute le 15/09/2026. Sans lui,
    n'importe quelle piece de la liste basculait a 'exportee' - y compris
    une piece encore 'saisie'. Le cas se produisait par avec_liees() : la
    jumelle d'une piece liee pouvait etre restee en attente pendant que
    l'autre etait validee. a_exporter() ne retenant que les pieces
    'validee', cette jumelle n'etait dans AUCUN fichier Sage, mais elle
    disparaissait quand meme de la file de validation. Plus personne ne la
    traitait, et elle n'existait nulle part ailleurs : la piece s'evaporait.

    Renvoie le nombre de pieces reellement marquees. L'ancienne version
    journalisait len(ids), donc un chiffre qui pouvait etre faux.
    """
    with _connexion() as c, c.cursor() as cur:
        ids = _ids_lies(cur, ids)
        cur.execute(
            "UPDATE ecritures SET statut = 'exportee', exporte_le = now() "
            "WHERE id_piece = ANY(%s) AND statut = 'validee' "
            "RETURNING id_piece",
            (ids,))
        marquees = {r[0] for r in cur.fetchall()}
    n = len(marquees)
    if n < len(ids):
        logger.warning(
            "%s piece(s) marquee(s) exportee(s) vers Sage sur %s demandee(s) : "
            "les autres n'etaient pas au statut 'validee'.", n, len(ids))
    else:
        logger.info("%s piece(s) marquee(s) exportee(s) vers Sage.", n)
    return n


# --- solde de caisse -------------------------------------------------------------
#
# Deux sortes de journaux de tresorerie, depuis la confirmation du comptable
# que chaque centre a sa propre caisse physique (10/09/2026, voir
# sql/migrations/2026-09-11_soldes_par_centre_et_banque_cbi.sql) :
#   - une caisse physique (CP, CMD) : cinq tiroirs-caisses reels, un par
#     centre - le solde d'ouverture ET les mouvements se ventilent par
#     centre (soldes_ouverture_centre, ecritures.centre) ;
#   - un compte partage (la banque) : un seul compte, utilise par tous les
#     centres indifferemment - un centre n'y a pas "sa part", le solde reste
#     global et un filtre centre n'a ici aucun sens comptable ; on l'ignore
#     donc volontairement pour ce type de journal, meme si on le recoit.


def est_caisse_physique(ref, journal):
    jx = ref["journaux"]
    if "caisse_physique" not in jx.columns:
        return False
    val = jx.loc[jx["journal"] == journal, "caisse_physique"]
    return bool(len(val)) and val.iloc[0] == "oui"


def _solde_ouverture_journal(ref, journal, centre=None):
    """Solde d'ouverture d'un journal : par centre (somme de tous les
    centres si centre=None) pour une caisse physique, sinon le solde global
    unique de journaux.solde_ouverture."""
    if est_caisse_physique(ref, journal):
        sc = ref.get("soldes_centre")
        if sc is None or len(sc) == 0:
            return 0.0
        sous = sc[sc["journal"] == journal]
        if centre is not None:
            sous = sous[sous["centre"] == centre]
        if len(sous) == 0:
            return 0.0
        return float(sous["solde_ouverture"].sum())
    jx = ref["journaux"]
    ouv_raw = jx.loc[jx["journal"] == journal, "solde_ouverture"]
    if len(ouv_raw) == 0 or pd.isna(ouv_raw.iloc[0]):
        return 0.0
    return float(ouv_raw.iloc[0])


def nom_centre(ref, code):
    """Nom complet d'un centre a partir de son code ("SIA" -> "SIAO").

    A utiliser PARTOUT ou un centre est montre a un utilisateur : ecrans,
    tableaux, graphiques, reponses de l'assistant. Le code a trois lettres est
    une cle technique, il n'a jamais a apparaitre a l'ecran. Renvoie le code
    tel quel si le centre est introuvable, pour ne jamais afficher un vide."""
    cx = ref["centres"]
    val = cx.loc[cx["code_centre"] == code, "intitule"]
    return val.iloc[0] if len(val) else code


# Ancien nom, conserve pour les appels existants.
_nom_centre = nom_centre


def solde_caisse(journal, ref, d=None, centre=None):
    j = ref["journaux"]
    cc = j.loc[j["journal"] == journal, "compte_contrepartie"].iloc[0]
    # Un compte partage (la banque) n'a pas de solde "par centre" : le filtre
    # centre eventuellement recu est ignore pour ce type de journal, aussi
    # bien pour le solde d'ouverture que pour les mouvements.
    centre_effectif = centre if est_caisse_physique(ref, journal) else None
    ouv = _solde_ouverture_journal(ref, journal, centre_effectif)
    if d is None:
        d = lire_ecritures(centre=centre_effectif)
    if len(d) == 0:
        return ouv
    if centre_effectif is not None:
        d = d[d["centre"] == centre_effectif]
    # Une piece "a_corriger" a deja un mouvement de caisse reel (l'argent a
    # physiquement bouge) : seul son compte de contrepartie est en attente
    # de reclassement. L'exclure du solde sous-estimerait la tresorerie
    # reelle - le solde de caisse doit toujours refleter l'encaisse
    # effective, y compris les pieces pas encore entierement classees.
    d = d[d["compte"] == cc]
    return ouv + d["debit"].sum() - d["credit"].sum()


def mouvements_caisse(d, ref):
    """Entrees et sorties REELLES de tresorerie sur les pieces `d`, plus les
    virements internes a part.

    Un virement interne (approvisionnement CMD depuis la CP, transfert entre
    centres, versement en banque) passe toujours par le 585000 : l'argent
    sort d'une caisse et entre dans une autre, sans quitter la maison. Le
    compter en entree ET en sortie gonflait les deux chiffres du meme
    montant. Toute piece qui touche le 585000 est donc sortie des entrees
    et sorties et totalisee dans `virements` (montant deplace, compte une
    seule fois meme si une seule des deux faces est deja saisie).

    Renvoie (entrees, sorties, virements)."""
    if d is None or len(d) == 0:
        return 0.0, 0.0, 0.0
    cc = set(ref["journaux"]["compte_contrepartie"].dropna())
    internes = set(d.loc[d["compte"] == COMPTE_VIREMENTS_FONDS, "id_piece"])
    tres = d[d["compte"].isin(cc)]
    reel = tres[~tres["id_piece"].isin(internes)]
    virt = tres[tres["id_piece"].isin(internes)]
    virements = max(float(virt["debit"].sum()), float(virt["credit"].sum()))
    return float(reel["debit"].sum()), float(reel["credit"].sum()), virements


# --- controles (logique identique a la version Excel, purement en memoire) -------
# Les DataFrames issus de lire_ecritures()/lire_referentiel() ont exactement
# les memes colonnes qu'avant : controler(), controler_soldes(), anomalies(),
# tiers_manquants() n'ont donc pas eu besoin de changer une seule ligne.


def controler(d, ref, d_complet=None):
    if d_complet is None:
        d_complet = d
    rows = []
    if len(d) == 0:
        return pd.DataFrame(columns=["gravite", "piece", "anomalie"])

    # Ces calculs ne dependent que du referentiel, jamais de la piece en
    # cours : les sortir de la boucle evite de les refaire une fois par
    # piece. Corrige le 13/09/2026 - mesure sur 992 pieces (hakili_verif) :
    # controler() passe de 2,8s a 0,35s, memes controles, memes messages,
    # meme ordre de sortie (groupby(sort=False) preserve l'ordre
    # d'apparition, comme le faisait id_piece.unique()).
    jx = ref["journaux"]
    tres = jx.loc[jx.get("type", "tresorerie").eq("tresorerie") if "type" in jx.columns
                  else jx["journal"].notna(), "compte_contrepartie"]
    tresorerie_par_journal = (jx.set_index("journal")["type"].eq("tresorerie")
                               if "type" in jx.columns else None)
    comptes_connus = set(ref["comptes"]["compte"])
    obl = set(ref["comptes"].loc[ref["comptes"]["tiers_obligatoire"] == "oui", "compte"])
    tiers_connus = set(ref["tiers"]["code_tiers"])
    prefixes = {j: prefixe_piece(j, ref) for j in jx["journal"]}

    for idp, p in d.groupby("id_piece", sort=False):
        num = ou(p["num_definitif"].iloc[0], p["num_provisoire"].iloc[0])
        if round(p["debit"].sum()) != round(p["credit"].sum()):
            rows.append(("bloquante", num,
                         f"Piece desequilibree : {fcfa(p['debit'].sum())} au debit contre "
                         f"{fcfa(p['credit'].sum())} au credit."))
        j_piece = p["journal"].iloc[0]
        est_tresorerie = tresorerie_par_journal is None or bool(tresorerie_par_journal.get(j_piece, False))
        if est_tresorerie and not p["compte"].isin(tres).any():
            rows.append(("bloquante", num, "Aucune ligne de caisse : la piece ne mouvemente pas la tresorerie."))
        inc = sorted(set(p["compte"]) - comptes_connus)
        if inc:
            rows.append(("bloquante", num, f"Compte absent du plan de comptes : {', '.join(inc)}."))
        manque = p[p["compte"].isin(obl) & (p["code_tiers"] == "")]
        if len(manque) > 0:
            rows.append(("bloquante", num,
                         f"Compte {', '.join(sorted(manque['compte'].unique()))} sans code tiers : "
                         "le lettrage sera impossible dans Sage."))
        cle = p["compte"] + "|" + p["code_tiers"]
        vide = sorted({x.split("|")[0] for x in
                       set(cle[p["debit"] > 0]) & set(cle[p["credit"] > 0])})
        if vide:
            rows.append(("bloquante", num,
                         f"Compte {', '.join(vide)} debite et credite pour le meme tiers : "
                         "les deux lignes s'annulent, la piece n'a aucun effet comptable."))
        tinc = sorted(set(p.loc[p["code_tiers"] != "", "code_tiers"]) - tiers_connus)
        if tinc:
            rows.append(("bloquante", num,
                         f"Tiers inconnu : {', '.join(tinc)}. A creer dans le referentiel avant l'export."))
        pref = prefixes.get(j_piece, str(j_piece))
        if p["num_definitif"].iloc[0] and not str(p["num_definitif"].iloc[0]).startswith(pref):
            rows.append(("a_verifier", num, f"Numero de piece incoherent avec le journal {j_piece}."))
        if (p["libelle"] == "").any():
            rows.append(("a_verifier", num, "Ligne sans libelle."))
        if md.COMPTE_ATTENTE in set(p["compte"]):
            # Bloquante tant que la piece n'est pas validee (23/09/2026) : on
            # ne valide plus une piece sur le compte d'attente, il faut
            # d'abord trouver le bon compte. Les pieces historiques deja
            # validees restent signalees, sans bloquer quoi que ce soit.
            non_validee = p["statut"].iloc[0] in ("saisie", "a_corriger") if "statut" in p.columns else True
            rows.append(("bloquante" if non_validee else "a_verifier", num,
                         f"Compte d'attente ({md.COMPTE_ATTENTE}) utilise : operation a reclasser "
                         "sur le bon compte avant validation (onglet Controles)."))

    ap = d[d["modele"] == "approvisionnement"]
    if len(ap) > 0:
        for idp, p in ap.groupby("id_piece", sort=False):
            num = ou(p["num_definitif"].iloc[0], p["num_provisoire"].iloc[0])
            lien = p["id_lien"].iloc[0]
            seule = (not lien) or (d_complet.loc[d_complet["id_lien"] == lien, "id_piece"].nunique() < 2)
            if seule:
                rows.append(("bloquante", num,
                             "Transfert entre caisses sans contrepartie : l'autre caisse n'a pas ete mouvementee."))

    return pd.DataFrame(rows, columns=["gravite", "piece", "anomalie"])


def tiers_manquants(d, ref):
    if d is None or len(d) == 0:
        return []
    utilises = {str(x).strip() for x in d["code_tiers"] if str(x).strip()}
    connus = set(ref["tiers"]["code_tiers"])
    return sorted(utilises - connus)


def reparer_tiers_manquants(d, ref):
    """Recree, sous forme de fiches minimales, les tiers cites par des
    ecritures mais absents de la table tiers - meme filet de securite qu'en
    version Excel, pour le cas ou tiers aurait ete restaure depuis une
    sauvegarde plus ancienne que ecritures."""
    manquants = tiers_manquants(d, ref)
    if not manquants:
        return []
    crees = []
    with _connexion() as c, c.cursor() as cur:
        for code in manquants:
            collectif = code[:3] + "000"
            if collectif not in TYPES_COLLECTIF:
                continue
            cur.execute("SELECT 1 FROM tiers WHERE upper(code_tiers) = upper(%s)", (code,))
            if cur.fetchone():
                continue
            cur.execute(
                "INSERT INTO tiers (code_tiers, intitule, compte_collectif, type, actif, actif_annee) "
                "VALUES (%s, %s, %s, %s, 'oui', 'oui')",
                (code, code[3:] or code, collectif, TYPES_COLLECTIF[collectif]))
            crees.append(code)
    return crees


def anomalies(d, ref, centre=None, inclure_banque=True):
    # controler_soldes recoit toujours l'ensemble des ecritures (d_complet),
    # jamais le sous-ensemble filtre par centre ci-dessous : le solde d'une
    # caisse physique doit sommer TOUS les mouvements de ce centre (pas
    # seulement ceux qu'on s'appretait a montrer dans Controles), et
    # inclure_banque=False doit pouvoir s'appliquer meme quand centre=None.
    d_complet = d
    if centre is not None and len(d):
        d = d[d["centre"] == centre]
    if d is None or len(d) == 0:
        return pd.DataFrame(columns=["gravite", "piece", "anomalie"])
    a = controler(d, ref, d)
    s = controler_soldes(ref, d_complet, centre=centre, inclure_banque=inclure_banque)
    return pd.concat([a, s], ignore_index=True)


def controler_soldes(ref, d=None, centre=None, inclure_banque=True):
    """Detecte les soldes de caisse negatifs (impossibles en realite : on ne
    peut pas sortir plus d'especes qu'on en a). Par caisse physique (CP,
    CMD), le controle porte sur CHAQUE centre independamment (centre=None
    verifie les six ; centre='PIS' ne verifie que Pissy) - sommer d'abord
    tous les centres, comme avant la confirmation du 10/09/2026 que chaque
    centre a sa propre caisse, pouvait masquer une caisse a sec dans un
    centre derriere l'excedent d'un autre. La banque (compte partage, jamais
    ventile par centre) n'est verifiee que si inclure_banque=True - c'est ce
    qui permet a app.py de ne jamais montrer une alerte sur le solde de la
    banque a un utilisateur qui n'a pas le droit d'en voir le chiffre."""
    if d is None:
        d = lire_ecritures()
    rows = []
    jx = ref["journaux"]
    if "type" in jx.columns:
        jx = jx[jx["type"].fillna("tresorerie") == "tresorerie"]
    if "actif" in jx.columns:
        jx = jx[jx["actif"].fillna("oui") == "oui"]
    centres_ref = list(ref["centres"]["code_centre"]) if "centres" in ref else []
    for j in jx["journal"]:
        physique = est_caisse_physique(ref, j)
        if not physique and not inclure_banque:
            continue
        if physique:
            a_verifier = [centre] if centre is not None else centres_ref
        else:
            a_verifier = [None]  # banque : un seul solde global, jamais par centre
        for c in a_verifier:
            s = solde_caisse(j, ref, d, centre=c)
            if s < 0:
                ouv = _solde_ouverture_journal(ref, j, c if physique else None)
                lieu = f"{j} ({_nom_centre(ref, c)})" if (physique and c is not None) else j
                if ouv == 0:
                    msg = (f"Solde de caisse negatif : {fcfa(s)} F. Le solde d'ouverture de {lieu} "
                           "est a zero dans le referentiel : renseignez l'encaisse reelle au "
                           "demarrage, onglet Referentiel.")
                else:
                    msg = (f"Solde de caisse negatif : {fcfa(s)} F pour {lieu}. Les sorties "
                           "depassent l'encaisse : une piece manque ou un montant est errone.")
                rows.append(("a_verifier", j, msg))
    return pd.DataFrame(rows, columns=["gravite", "piece", "anomalie"])


# --- export vers Sage ----------------------------------------------------------------


# Retire, uniquement pour l'export Sage, la ligne de caisse globale d'un
# encaissement qui regroupe plusieurs operations (frais du mois + avance,
# par exemple - voir logic.modeles._lignes_encaissement) : le compte 411
# porte deja une ligne detaillee par operation (son propre libelle complet,
# nature + mois), la ligne globale ("FRAIS DE COURS D'APPUI - NOM", sans mois) ferait doublon avec
# un libelle moins precis. Un encaissement a une seule operation n'est pas
# concerne : sa ligne de caisse porte deja le meme libelle complet que sa
# ligne 411 (spec 2026), rien a en retirer.
#
# Ne touche ni la base ni l'affichage dans l'application (Brouillard,
# Validation...) - uniquement la copie transformee pour le fichier Sage.
# Consequence acceptee (demande explicite) : le fichier Sage d'un tel
# encaissement n'est alors plus equilibre ligne a ligne (le total des
# credits 411 n'a plus de contrepartie en debit dans l'export).
def _retirer_ligne_globale_encaissement(d):
    if "modele" not in d.columns or "id_piece" not in d.columns:
        return d
    nb_credits = d[d["credit"] > 0].groupby("id_piece").size()
    multi = d["id_piece"].map(nb_credits).fillna(0) >= 2
    a_retirer = (d["modele"] == "encaissement") & (d["debit"] > 0) & multi
    return d[~a_retirer]


def _section_sage(d, ref):
    """Code de section analytique attendu par Sage, pour chaque ligne.

    Sage rapproche la section sur son CODE, pas sur son intitule, et impose a
    ce code une longueur fixe declaree dans le dossier. On envoie donc
    `centres.section_analytique` (PIS, TAM, SAA...), qui est justement la
    colonne prevue pour ca, et jamais l'intitule affiche a l'ecran - lequel
    varie (Saaba / SAAB), porte des accents et depasse la longueur permise.

    Corrige le 23/09/2026 : l'export envoyait l'intitule, d'ou des fichiers
    melangeant "Saaba" et "SAAB" selon l'anciennete de la piece, dont aucune
    forme ne correspondait aux sections creees dans Sage."""
    centres = ref.get("centres") if isinstance(ref, dict) else None
    if centres is not None and "section_analytique" in centres.columns:
        codes = dict(zip(centres["code_centre"], centres["section_analytique"]))
        col = d["centre"].map(codes)
        col = col.where(col.notna() & (col.astype(str).str.strip() != ""), d["centre"])
    else:
        col = d["centre"]
    return col.astype(str).str.strip().str.upper()


def format_sage(d, ref):
    if d is None or len(d) == 0:
        return None
    d = d.sort_values(["date_piece", "num_definitif", "id_ligne"])
    # La ligne de caisse globale des encaissements multi-operations n'est
    # PLUS retiree (23/09/2026). La retirer laissait la piece desequilibree
    # dans le fichier - credits 411 sans contrepartie au debit - et Sage
    # refuse d'importer une piece qui ne s'equilibre pas. Le doublon de
    # libelle qu'on voulait eviter est un desagrement d'affichage ; une piece
    # rejetee, ou pire, integree a moitie, est une erreur comptable.
    if len(d) == 0:
        return None
    return pd.DataFrame({
        "Journal": d["journal"],
        "Date": pd.to_datetime(d["date_piece"]).dt.strftime("%d%m%Y"),
        "Piece": d["num_definitif"],
        "Compte": d["compte"],
        "Tiers": d["code_tiers"],
        "Libelle": d["libelle"],
        "Debit": d["debit"].apply(lambda x: f"{x:.2f}".replace(".", ",")),
        "Credit": d["credit"].apply(lambda x: f"{x:.2f}".replace(".", ",")),
        "Section": _section_sage(d, ref),
    })


def ecrire_fichier_sage(x, chemin):
    # cp1252 plutot que latin1 (corrige le 10/09/2026) : sur-ensemble de
    # latin-1 qui couvre en plus "oe" (manoeuvre, soeur), les guillemets
    # typographiques et le tiret cadratin - des caracteres qu'un copier-coller
    # depuis Word peut introduire dans un libelle libre, et que c'est
    # generalement ce qu'attend un import Windows/Sage. errors="replace" en
    # filet de securite final : un caractere malgre tout hors cp1252 devient
    # "?" au lieu de faire planter l'ecriture du fichier entier.
    x.to_csv(chemin, sep=";", index=False, header=False, encoding="cp1252",
              errors="replace", na_rep="", lineterminator="\r\n")


# --- synchronisation entre postes -------------------------------------------------


def revision_bd():
    """Watermark unique, incremente par trigger a chaque INSERT/UPDATE/DELETE
    sur une table metier. Remplace la date de modification des fichiers
    Excel guettee par la version precedente : un reactive.poll cote app.py
    interroge cette seule valeur, tres bon marche, au lieu de parcourir un
    dossier entier sur le disque.

    Une seule nouvelle tentative en cas de connexion coupee : c'est la requete
    la plus frequente de l'application (une par session et par intervalle de
    sondage), donc celle qui tombe la premiere sur une connexion morte. La
    premiere tentative la retire du pool (_connexion), la seconde repart sur
    une connexion neuve. Deux echecs de suite signifient que la base est
    vraiment injoignable : l'appelant decide alors quoi en faire."""
    for tentative in (1, 2):
        try:
            with _connexion() as c, c.cursor() as cur:
                cur.execute("SELECT valeur FROM revision")
                return cur.fetchone()[0]
        except (psycopg2.InterfaceError, psycopg2.OperationalError):
            if tentative == 2:
                raise
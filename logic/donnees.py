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
import os
import random
import re
import unicodedata
import warnings
from datetime import datetime

import pandas as pd
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

# pandas.read_sql sur une connexion psycopg2 brute (plutot qu'un moteur
# SQLAlchemy) fonctionne parfaitement mais le signale a chaque appel : on le
# fait exprès (pas de dependance SQLAlchemy supplementaire pour un usage
# aussi simple), donc l'avertissement est attendu et sans consequence.
warnings.filterwarnings("ignore", message=".*only supports SQLAlchemy connectable.*")

# --- connexion ---------------------------------------------------------------
#
# DATABASE_URL (format postgresql://user:pass@hote:port/base) prime si
# defini ; sinon les variables PG* standard (PGHOST, PGPORT, PGUSER,
# PGPASSWORD, PGDATABASE), lues nativement par psycopg2/libpq. Rien en dur
# dans le code : c'est ce qui permet de deployer le meme code en local, sur
# le poste du comptable ou sur un serveur, en ne changeant que l'environnement.

_DSN = os.environ.get("DATABASE_URL") or None
_POOL = ThreadedConnectionPool(minconn=1, maxconn=10, dsn=_DSN)


@contextlib.contextmanager
def _connexion():
    """Preteun une connexion du pool, la rend a la sortie. Valide (commit) si
    le bloc se termine sans exception, annule (rollback) sinon - une piece
    ne peut jamais rester enregistree a moitie."""
    conn = _POOL.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _POOL.putconn(conn)


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
]

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
    return ref


def intitule_compte(ref, compte):
    comptes = ref["comptes"]
    mapping = dict(zip(comptes["compte"].astype(str), comptes["intitule"]))
    return mapping.get(str(compte), "compte inconnu")


def maj_solde_ouverture(journal, montant):
    with _connexion() as c, c.cursor() as cur:
        cur.execute("UPDATE journaux SET solde_ouverture = %s, updated_at = now() WHERE journal = %s",
                    (float(montant or 0), str(journal)))


TYPES_COLLECTIF = {"411000": "client", "401000": "fournisseur", "422000": "personnel"}

NATURES_COMPTE = ["charge", "produit", "tresorerie", "bilan", "tiers"]


def ajouter_compte(compte, intitule, nature, tiers_obligatoire="non", depense_courante="non"):
    compte = str(compte).strip()
    if not compte:
        raise ValueError("Le numero de compte est obligatoire.")
    if not intitule or not str(intitule).strip():
        raise ValueError("L'intitule est obligatoire.")
    with _connexion() as c, c.cursor() as cur:
        cur.execute("SELECT 1 FROM comptes WHERE compte = %s", (compte,))
        if cur.fetchone():
            raise ValueError("Ce compte existe deja.")
        cur.execute(
            "INSERT INTO comptes (compte, intitule, nature, tiers_obligatoire, nb_2024_2025, depense_courante) "
            "VALUES (%s, %s, %s, %s, 0, %s)",
            (compte, str(intitule).strip(), nature, tiers_obligatoire, depense_courante))


def ajouter_utilisateur(identifiant, nom, role, centre, code_acces):
    identifiant = str(identifiant).strip().lower()
    if not identifiant:
        raise ValueError("L'identifiant est obligatoire.")
    if not str(nom or "").strip():
        raise ValueError("Le nom est obligatoire.")
    code_acces = str(code_acces or "").strip()
    if not code_acces:
        raise ValueError("Le code d'acces est obligatoire.")
    with _connexion() as c, c.cursor() as cur:
        cur.execute("SELECT 1 FROM utilisateurs WHERE lower(identifiant) = %s", (identifiant,))
        if cur.fetchone():
            raise ValueError("Cet identifiant existe deja.")
        cur.execute(
            "INSERT INTO utilisateurs (identifiant, nom, role, centre, code_acces, actif) "
            "VALUES (%s, %s, %s, %s, %s, 'oui')",
            (identifiant, str(nom).strip(), role, centre, code_acces))


def desactiver_utilisateur(identifiant):
    with _connexion() as c, c.cursor() as cur:
        cur.execute(
            "UPDATE utilisateurs SET actif = 'non', updated_at = now() WHERE lower(identifiant) = lower(%s)",
            (str(identifiant).strip(),))
        if cur.rowcount == 0:
            raise ValueError("Utilisateur introuvable.")


def ajouter_tiers(code, intitule, collectif):
    with _connexion() as c, c.cursor() as cur:
        cur.execute("SELECT 1 FROM tiers WHERE upper(code_tiers) = upper(%s)", (str(code),))
        if cur.fetchone():
            raise ValueError("Ce code tiers existe deja.")
        type_ = TYPES_COLLECTIF.get(collectif, "client")
        cur.execute(
            "INSERT INTO tiers (code_tiers, intitule, compte_collectif, type, actif, actif_annee) "
            "VALUES (%s, %s, %s, %s, 'oui', 'oui')",
            (code, intitule, collectif, type_))


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
    piece. Cree ou reactive le tiers si necessaire, dans la meme transaction
    que la lecture qui la precede : deux caisses ne peuvent pas creer le
    meme nouveau tiers en double, la cle primaire code_tiers l'empeche."""
    valeur = str(valeur or "").strip()
    if not valeur:
        return ""
    with _connexion() as c, c.cursor() as cur:
        cur.execute(
            "SELECT code_tiers, intitule, actif_annee FROM tiers "
            "WHERE code_tiers ILIKE %s || '%%' FOR UPDATE",
            (pref,))
        lignes = cur.fetchall()
        for code, nom, actif_annee in lignes:
            if code.upper() == valeur.upper() or (nom or "").upper() == valeur.upper():
                if str(actif_annee or "").lower() != "oui":
                    cur.execute(
                        "UPDATE tiers SET actif_annee = 'oui', updated_at = now() WHERE code_tiers = %s",
                        (code,))
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
            "VALUES (%s, %s, %s, %s, 'oui', 'oui')",
            (code, valeur.upper(), collectif, type_))
        return code


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


def enregistrer_operation(pieces, centre, date_piece, modele, utilisateur, note="", valeurs=None):
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
    with _connexion() as c, c.cursor() as cur:
        for i_p, p in enumerate(pieces):
            n = _prochain_numero(cur, f"prov:{centre}:{mois}")
            num = f"{centre}-{mois[2:6]}-{n:03d}"
            idp = f"{centre}-{horo}-{n}"
            L = p["lignes"].reset_index(drop=True)
            for i, row in L.iterrows():
                cur.execute(
                    "INSERT INTO ecritures (id_ligne, id_piece, id_lien, num_provisoire, num_definitif, "
                    "journal, centre, date_piece, compte, code_tiers, libelle, debit, credit, modele, "
                    "saisi_par, saisi_le, statut, observation, valeurs_json) VALUES "
                    "(%s,%s,%s,%s,'',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),'saisie',%s,%s)",
                    (f"{idp}-{i + 1}", idp, lien, num, p["journal"], centre, str(date_piece),
                     row["compte"], row["code_tiers"], row["libelle"], float(row["debit"]), float(row["credit"]),
                     modele, utilisateur, str(note or "").strip(), v_json))
            nums.append(num)
    return nums


def avec_liees(ids, d=None):
    ids = list(ids)
    if not ids:
        return ids
    with _connexion() as c, c.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT id_piece FROM ecritures WHERE id_lien IN "
            "(SELECT DISTINCT id_lien FROM ecritures WHERE id_piece = ANY(%s) AND id_lien <> '')",
            (list(ids),))
        extra = [r[0] for r in cur.fetchall()]
    return list(dict.fromkeys(list(ids) + extra))


def supprimer_piece(id_piece):
    if not isinstance(id_piece, (list, tuple, pd.Index)):
        id_piece = [id_piece]
    with _connexion() as c, c.cursor() as cur:
        ids = avec_liees(list(id_piece))
        cur.execute("SELECT DISTINCT statut FROM ecritures WHERE id_piece = ANY(%s)", (ids,))
        statuts = {r[0] for r in cur.fetchall()}
        if not statuts:
            raise ValueError("Piece introuvable.")
        if statuts - {"saisie", "a_corriger"}:
            raise ValueError("Une piece validee ou exportee ne peut plus etre supprimee.")
        cur.execute("DELETE FROM ecritures WHERE id_piece = ANY(%s)", (ids,))
        return len(ids)


def valider_pieces(ids, utilisateur):
    with _connexion() as c, c.cursor() as cur:
        ids = avec_liees(ids)
        cur.execute(
            "SELECT id_piece, journal, date_piece FROM ecritures "
            "WHERE id_piece = ANY(%s) AND statut = 'saisie' GROUP BY id_piece, journal, date_piece",
            (ids,))
        pieces = cur.fetchall()
        if not pieces:
            raise ValueError("Aucune piece a valider.")
        for idp, journal, date_piece in pieces:
            mois = mois_de(date_piece)
            n = _prochain_numero(cur, f"def:{journal}:{mois}")
            num_def = f"{prefixe_piece(journal)}{mois[2:6]}{n:03d}"
            cur.execute(
                "UPDATE ecritures SET num_definitif = %s, statut = 'validee', "
                "valide_par = %s, valide_le = now() WHERE id_piece = %s",
                (num_def, utilisateur, idp))
        return len(pieces)


def rejeter_pieces(ids, motif, utilisateur):
    with _connexion() as c, c.cursor() as cur:
        ids = avec_liees(ids)
        cur.execute(
            "UPDATE ecritures SET statut = 'a_corriger', observation = %s WHERE id_piece = ANY(%s)",
            (f"{utilisateur} : {motif}", ids))
        cur.execute("SELECT count(DISTINCT id_piece) FROM ecritures WHERE id_piece = ANY(%s)", (ids,))
        return cur.fetchone()[0]


def marquer_exporte(ids):
    with _connexion() as c, c.cursor() as cur:
        ids = avec_liees(ids)
        cur.execute(
            "UPDATE ecritures SET statut = 'exportee', exporte_le = now() WHERE id_piece = ANY(%s)",
            (ids,))


# --- solde de caisse -------------------------------------------------------------


def solde_caisse(journal, ref, d=None, centre=None):
    j = ref["journaux"]
    cc = j.loc[j["journal"] == journal, "compte_contrepartie"].iloc[0]
    ouv_raw = j.loc[j["journal"] == journal, "solde_ouverture"].iloc[0]
    ouv = float(ouv_raw) if pd.notna(ouv_raw) else 0.0
    if d is None:
        d = lire_ecritures(centre=centre)
    if len(d) == 0:
        return ouv
    if centre is not None:
        d = d[d["centre"] == centre]
    d = d[(d["compte"] == cc) & (d["statut"] != "a_corriger")]
    return ouv + d["debit"].sum() - d["credit"].sum()


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
    for idp in d["id_piece"].unique():
        p = d[d["id_piece"] == idp]
        num = ou(p["num_definitif"].iloc[0], p["num_provisoire"].iloc[0])
        if round(p["debit"].sum()) != round(p["credit"].sum()):
            rows.append(("bloquante", num,
                         f"Piece desequilibree : {fcfa(p['debit'].sum())} au debit contre "
                         f"{fcfa(p['credit'].sum())} au credit."))
        jx = ref["journaux"]
        tres = jx.loc[jx.get("type", "tresorerie").eq("tresorerie") if "type" in jx.columns
                      else jx["journal"].notna(), "compte_contrepartie"]
        j_piece = p["journal"].iloc[0]
        est_tresorerie = ("type" not in jx.columns) or \
            (jx.loc[jx["journal"] == j_piece, "type"] == "tresorerie").any()
        if est_tresorerie and not p["compte"].isin(tres).any():
            rows.append(("bloquante", num, "Aucune ligne de caisse : la piece ne mouvemente pas la tresorerie."))
        inc = sorted(set(p["compte"]) - set(ref["comptes"]["compte"]))
        if inc:
            rows.append(("bloquante", num, f"Compte absent du plan de comptes : {', '.join(inc)}."))
        obl = set(ref["comptes"].loc[ref["comptes"]["tiers_obligatoire"] == "oui", "compte"])
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
        tinc = sorted(set(p.loc[p["code_tiers"] != "", "code_tiers"]) - set(ref["tiers"]["code_tiers"]))
        if tinc:
            rows.append(("bloquante", num,
                         f"Tiers inconnu : {', '.join(tinc)}. A creer dans le referentiel avant l'export."))
        pref = prefixe_piece(p["journal"].iloc[0], ref)
        if p["num_definitif"].iloc[0] and not str(p["num_definitif"].iloc[0]).startswith(pref):
            rows.append(("a_verifier", num, f"Numero de piece incoherent avec le journal {p['journal'].iloc[0]}."))
        if (p["libelle"] == "").any():
            rows.append(("a_verifier", num, "Ligne sans libelle."))
        if "471000" in set(p["compte"]):
            rows.append(("a_verifier", num,
                         "Compte d'attente (471000) utilise : operation a reclasser sur le bon compte."))

    ap = d[d["modele"] == "approvisionnement"]
    if len(ap) > 0:
        for idp in ap["id_piece"].unique():
            p = ap[ap["id_piece"] == idp]
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


def anomalies(d, ref, centre=None):
    if centre is not None and len(d):
        d = d[d["centre"] == centre]
    if d is None or len(d) == 0:
        return pd.DataFrame(columns=["gravite", "piece", "anomalie"])
    a = controler(d, ref, d)
    s = controler_soldes(ref, d)
    if centre is not None and len(s):
        s = s[s["piece"].isin(d["journal"].unique())]
    return pd.concat([a, s], ignore_index=True)


def controler_soldes(ref, d=None):
    if d is None:
        d = lire_ecritures()
    rows = []
    jx = ref["journaux"]
    if "type" in jx.columns:
        jx = jx[jx["type"].fillna("tresorerie") == "tresorerie"]
    for j in jx["journal"]:
        ouv_raw = ref["journaux"].loc[ref["journaux"]["journal"] == j, "solde_ouverture"].iloc[0]
        ouv = float(ouv_raw) if pd.notna(ouv_raw) else 0.0
        s = solde_caisse(j, ref, d)
        if s < 0:
            if ouv == 0:
                msg = (f"Solde de caisse negatif : {fcfa(s)} F. Le solde d'ouverture du journal {j} "
                       "est a zero dans le referentiel : renseignez l'encaisse reelle au demarrage, "
                       "onglet journaux.")
            else:
                msg = (f"Solde de caisse negatif : {fcfa(s)} F. Les sorties depassent l'encaisse : "
                       "une piece manque ou un montant est errone.")
            rows.append(("a_verifier", j, msg))
    return pd.DataFrame(rows, columns=["gravite", "piece", "anomalie"])


# --- export vers Sage ----------------------------------------------------------------


def format_sage(d, ref):
    if d is None or len(d) == 0:
        return None
    d = d.sort_values(["date_piece", "num_definitif", "id_ligne"])
    centres = ref.get("centres") if isinstance(ref, dict) else None
    if centres is not None and "section_analytique" in centres.columns:
        section = dict(zip(centres["code_centre"], centres["section_analytique"]))
        col_section = d["centre"].map(section).fillna(d["centre"])
    else:
        col_section = d["centre"]
    return pd.DataFrame({
        "Journal": d["journal"],
        "Date": pd.to_datetime(d["date_piece"]).dt.strftime("%d%m%Y"),
        "Piece": d["num_definitif"],
        "Compte": d["compte"],
        "Tiers": d["code_tiers"],
        "Libelle": d["libelle"],
        "Debit": d["debit"].apply(lambda x: f"{x:.2f}".replace(".", ",")),
        "Credit": d["credit"].apply(lambda x: f"{x:.2f}".replace(".", ",")),
        "Section": col_section,
    })


def ecrire_fichier_sage(x, chemin):
    x.to_csv(chemin, sep=";", index=False, header=False, encoding="latin1", na_rep="")


# --- synchronisation entre postes -------------------------------------------------


def revision_bd():
    """Watermark unique, incremente par trigger a chaque INSERT/UPDATE/DELETE
    sur une table metier. Remplace la date de modification des fichiers
    Excel guettee par la version precedente : un reactive.poll cote app.py
    interroge cette seule valeur, tres bon marche, au lieu de parcourir un
    dossier entier sur le disque."""
    with _connexion() as c, c.cursor() as cur:
        cur.execute("SELECT valeur FROM revision")
        return cur.fetchone()[0]

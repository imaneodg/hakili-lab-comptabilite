# ---------------------------------------------------------------------------
# Tableau de bord - calculs (02/10/2026, complete le 03/10/2026)
#
# Une seule fonction de calcul, calculer(), alimente les deux pages : la vue
# d'ensemble (bandeaux, compte de resultat mensuel, comparatif, alertes) et
# la fiche d'un centre (Resultat, Eleves, Caisse, Fiabilite). Les deux pages
# lisent le meme dictionnaire : elles ne peuvent pas se contredire.
#
# Base caisse : l'argent reellement entre et sorti des caisses et de la
# banque, a la date de la piece. L'agregation est faite par PostgreSQL
# (flux_tableau_bord, soldes_tableau_bord, soldes_fin_mois). Le classement
# des comptes vit dans rubriques_tableau et classement_comptes, les cibles
# dans parametres_centre : aucun numero de compte ici.
#
# Conventions de signe : la base renvoie montant > 0 quand l'argent entre.
# Une ligne d'encaissement s'affiche telle quelle ; une ligne de charge ou de
# sortie hors exploitation s'affiche en positif quand l'argent sort.
#
# Chiffres par centre et chiffres d'ensemble : un centre est toujours vu
# seul (sa contribution au SIAO est une charge, quels que soient les autres
# centres choisis). L'ensemble, lui, ne compte pas les flux entre deux
# centres choisis (contribution, pret) : ce serait la meme somme deux fois.
# ---------------------------------------------------------------------------

import math
import statistics
from datetime import date, timedelta

import pandas as pd

import logic.donnees as dl
from assistant.semantique import mois_du_libelle

ENCAISSEMENT, CHARGE, HORS = "encaissement", "charge", "hors_exploitation"
STATUTS_NON_VALIDES = ("saisie", "a_corriger")

# Rubriques qui ont un role dans les indicateurs (cles de rubriques_tableau).
COURS, CAMP, SALAIRES = "cours_appui", "camp", "vacations"
CONTRIBUTION, ATTENTE, NON_CLASSE = "contribution", "attente", "non_classe"

# Niveaux affiches avec un mot, jamais la couleur seule.
CORRECT, SURVEILLER, ATTENTION, NEUTRE = "correct", "surveiller", "attention", "neutre"
ORDRE_NIVEAU = {ATTENTION: 0, SURVEILLER: 1, NEUTRE: 2, CORRECT: 3}

PARAMETRES_DEFAUT = {"cible_marge": 0.15, "cible_tresorerie_mois": 2.0}
# Bornes acceptees a la saisie des cibles (onglet Tableau de bord). Au-dela,
# c'est une faute de frappe (150 au lieu de 15) plutot qu'un objectif.
MARGE_MAX, TRESORERIE_MOIS_MAX = 0.5, 12.0


def _nan(v):
    return v is None or (isinstance(v, float) and math.isnan(v))


def _div(a, b):
    return a / b if b else float("nan")


# --- periode et centres ----------------------------------------------------------

def periode_par_defaut(aujourd_hui=None):
    """Du 1er janvier de l'annee du dernier mouvement a la fin de ce dernier
    mois (borne a aujourd'hui) : la direction lit l'annee en cours."""
    aujourd_hui = aujourd_hui or date.today()
    df = dl._lire_df("SELECT max(date_piece) AS d FROM ecritures WHERE date_piece <= %s",
                     (aujourd_hui,))
    dernier = df["d"].iloc[0] if len(df) else None
    dernier = pd.Timestamp(dernier).date() if dernier is not None and not pd.isna(dernier) else aujourd_hui
    debut = dernier.replace(month=1, day=1)
    fin = min((pd.Timestamp(dernier) + pd.offsets.MonthEnd(0)).date(), aujourd_hui)
    return debut, fin


def centres_proposes():
    """Les centres qui tiennent une caisse : actifs, et ayant deja des
    ecritures ou un utilisateur de saisie. Le compte de connexion du
    comptable (le siege) n'en fait donc pas partie, sans etre nomme."""
    return dl._lire_df("""
        SELECT c.code_centre, c.intitule FROM centres c
        WHERE c.actif = 'oui'
          AND (EXISTS (SELECT 1 FROM ecritures e WHERE e.centre = c.code_centre)
               OR EXISTS (SELECT 1 FROM utilisateurs u WHERE u.centre = c.code_centre
                          AND u.role = 'saisie' AND u.actif = 'oui'))
        ORDER BY c.ordre, c.intitule""")


def mois_de(debut, fin):
    """['2026-01', '2026-02', ...] : tous les mois de la periode."""
    return [p.strftime("%Y-%m") for p in pd.period_range(debut, fin, freq="M")]


# --- lecture ----------------------------------------------------------------------

def _lire(debut, fin, centres):
    centres = list(centres)
    # Les flux, agreges par PostgreSQL. Les frais d'eleves et les vacations
    # gardent leur libelle : le mois du cours et le camp s'y lisent.
    flux = dl._lire_df("""
        SELECT centre, mois, rubrique, sens,
               coalesce(contrepartie = ANY(%s) AND contrepartie <> centre, false) AS interne,
               sum(montant)::float AS montant
        FROM flux_tableau_bord(%s, %s, %s)
        WHERE rubrique NOT IN (%s, %s, %s)
        GROUP BY 1, 2, 3, 4, 5""", (centres, debut, fin, centres, COURS, CAMP, SALAIRES))
    # camp : le libelle porte un des mots des regles du camp (« CAMP »,
    # FRAIS CV...), pour reconnaitre aussi les vacations du camp. Meme
    # comparaison que flux_tableau_bord() (espace ajoute en fin de libelle).
    detail = dl._lire_df("""
        SELECT centre, mois, rubrique, sens, false AS interne, date_piece, code_tiers, libelle,
               EXISTS (SELECT 1 FROM classement_comptes c, unnest(c.motifs) m
                       WHERE c.rubrique = %s
                         AND tb_normaliser(f.libelle) || ' ' LIKE '%%' || tb_normaliser(m) || '%%') AS camp,
               sum(montant)::float AS montant
        FROM flux_tableau_bord(%s, %s, %s) f
        WHERE rubrique IN (%s, %s, %s)
        GROUP BY centre, mois, rubrique, sens, date_piece, code_tiers, libelle""",
                         (CAMP, debut, fin, centres, COURS, CAMP, SALAIRES))
    pieces = dl._lire_df("""
        SELECT centre,
               count(DISTINCT id_piece) FILTER (WHERE statut IN %s) AS non_validees,
               count(DISTINCT compte) FILTER (WHERE rubrique = %s) AS non_classes
        FROM flux_tableau_bord(%s, %s, %s)
        GROUP BY GROUPING SETS ((centre), ())""",
                         (STATUTS_NON_VALIDES, NON_CLASSE, debut, fin, centres))
    soldes = dl._lire_df("SELECT * FROM soldes_tableau_bord(%s, %s)", (fin, centres))
    soldes_debut = dl._lire_df("SELECT * FROM soldes_tableau_bord(%s, %s)",
                               (debut - timedelta(days=1), centres))
    mensuels = dl._lire_df("SELECT centre, mois, solde::float AS solde FROM soldes_fin_mois(%s, %s, %s)",
                           (debut, fin, centres))
    # Mouvement de la banque passe par chaque centre (versements, retraits).
    banque = dl._lire_df("""
        SELECT e.centre, sum(e.debit - e.credit)::float AS mouvement
        FROM ecritures e JOIN journaux j ON j.compte_contrepartie = e.compte
        WHERE j.type = 'tresorerie' AND j.caisse_physique = 'non'
          AND e.centre = ANY(%s) AND e.date_piece BETWEEN %s AND %s
        GROUP BY e.centre""", (centres, debut, fin))
    rubriques = dl._lire_df("SELECT * FROM rubriques_tableau ORDER BY ordre")
    parametres = dl._lire_df("SELECT * FROM parametres_centre WHERE centre = ANY(%s)", (centres,))
    return flux, detail, pieces, soldes, soldes_debut, mensuels, banque, rubriques, parametres


def plafond_salarial(encaissements, charges, salaires, marge):
    """Le plafond salarial : ce qu'on peut payer en salaires en gardant la
    marge cible. Encaissements, moins les autres charges d'exploitation,
    moins la marge visee. Seule definition de l'application : la fiche, le
    graphique et le rouge du compte de resultat l'utilisent tous."""
    return encaissements - (charges - salaires) - marge * encaissements


def parametres_centres(centres):
    """{centre: {"cible_marge", "cible_tresorerie_mois"}}, valeurs par defaut
    pour un centre sans ligne dans parametres_centre."""
    centres = list(centres)
    return _parametres(dl._lire_df("SELECT * FROM parametres_centre WHERE centre = ANY(%s)", (centres,)),
                       centres)


def verifier_parametres(marge_pct, tresorerie_mois):
    """(marge, mois) prets a enregistrer, ou ValueError avec un message pour
    l'utilisateur. marge_pct : en pourcentage (15 pour 15 %)."""
    try:
        marge, mois = float(marge_pct) / 100, float(tresorerie_mois)
    except (TypeError, ValueError):
        raise ValueError("Indiquez une marge et un capital de base chiffrés.")
    if math.isnan(marge) or math.isnan(mois):
        raise ValueError("Indiquez une marge et un capital de base chiffrés.")
    if not 0 <= marge <= MARGE_MAX:
        raise ValueError(f"La marge visée doit être comprise entre 0 et {MARGE_MAX * 100:.0f} %.")
    if not 0 <= mois <= TRESORERIE_MOIS_MAX:
        raise ValueError(f"Le capital de base doit être compris entre 0 et {TRESORERIE_MOIS_MAX:.0f} mois.")
    return round(marge, 4), round(mois, 1)


def enregistrer_parametres(valeurs):
    """valeurs : {centre: (marge_pct, tresorerie_mois)}. Tout est verifie
    avant d'ecrire, puis ecrit dans une seule transaction : soit toutes les
    cibles changent, soit aucune. Le controle d'acces est fait par l'appelant."""
    propres = {}
    for centre, (marge_pct, mois) in valeurs.items():
        try:
            propres[centre] = verifier_parametres(marge_pct, mois)
        except ValueError as e:
            raise ValueError(f"{centre} : {e}") from None
    with dl._connexion() as c, c.cursor() as cur:
        for centre, (marge, mois) in propres.items():
            cur.execute("""
                INSERT INTO parametres_centre (centre, cible_marge, cible_tresorerie_mois, updated_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (centre) DO UPDATE
                SET cible_marge = EXCLUDED.cible_marge,
                    cible_tresorerie_mois = EXCLUDED.cible_tresorerie_mois, updated_at = now()""",
                        (centre, marge, mois))
    return propres


def _parametres(parametres, centres):
    p = {c: dict(PARAMETRES_DEFAUT) for c in centres}
    for r in parametres.itertuples():
        p[r.centre] = {"cible_marge": float(r.cible_marge),
                       "cible_tresorerie_mois": float(r.cible_tresorerie_mois)}
    return p


# --- mois du cours et camp ------------------------------------------------------

def _mois_cours(libelle, jour):
    """Les mois de cours cites dans le libelle, ['2026-03', ...]. Meme
    lecture que l'assistant (assistant.semantique.mois_du_libelle)."""
    return [f"{a:04d}-{m:02d}" for a, m in mois_du_libelle(libelle, jour)]


def _preparer_detail(detail):
    """Ajoute a chaque frais ou vacation ses mois de cours. Le camp de
    vacances n'est reconnu qu'au libelle (regles de classement_comptes),
    jamais au mois du paiement."""
    d = detail.copy()
    d["mois_cours"] = ([_mois_cours(l, j) for l, j in zip(d["libelle"], d["date_piece"])]
                       if len(d) else pd.Series(dtype=object))
    return d


def _flux_complets(flux, detail):
    """Les flux agreges + le detail (frais, vacations) remis au meme format."""
    if len(detail) == 0:
        return flux
    agrege = (detail.groupby(["centre", "mois", "rubrique", "sens", "interne"], as_index=False)
              ["montant"].sum())
    if len(flux) == 0:
        return agrege
    return pd.concat([flux, agrege], ignore_index=True)


# --- lignes du tableau ------------------------------------------------------------

def _lignes(rubriques):
    """Les lignes affichables : (rubrique, sens) -> libelle, bloc, ordre.
    sens None = la ligne recoit les deux sens (montant net)."""
    lignes = []
    for r in rubriques.itertuples():
        if r.bloc not in (ENCAISSEMENT, CHARGE, HORS):
            continue
        a_part = isinstance(r.libelle_entree, str) and r.libelle_entree
        lignes.append({"cle": (r.rubrique, "sortie" if a_part else None), "libelle": r.libelle,
                       "bloc": r.bloc, "ordre": r.ordre, "toujours": bool(r.toujours_affichee)})
        if a_part:
            lignes.append({"cle": (r.rubrique, "entree"), "libelle": r.libelle_entree,
                           "bloc": r.bloc_entree or r.bloc, "ordre": r.ordre + 0.5,
                           "toujours": False})
    return lignes


def _valeur_affichee(flux, bloc):
    """Encaissement : l'argent entre est positif. Charge et hors
    exploitation : l'argent sorti est positif."""
    return flux["montant"] if bloc == ENCAISSEMENT else -flux["montant"]


def _de_la_ligne(flux, ligne):
    rubrique, sens = ligne["cle"]
    f = flux[flux["rubrique"] == rubrique]
    return f[f["sens"] == sens] if sens else f


def _tableau(flux, lignes, mois):
    """DataFrame : une ligne par poste, une colonne par mois + 'Total'.
    NaN = aucune donnee (affiche « - »)."""
    colonnes = mois + ["Total"]
    rangs = []
    for l in sorted(lignes, key=lambda x: x["ordre"]):
        f = _de_la_ligne(flux, l)
        if len(f) == 0 and not l["toujours"]:
            continue
        v = _valeur_affichee(f, l["bloc"]).groupby(f["mois"]).sum()
        valeurs = [v.get(m, float("nan")) for m in mois]
        total = v.sum() if len(v) else float("nan")
        rangs.append({"libelle": l["libelle"], "rubrique": l["cle"][0], "bloc": l["bloc"],
                      **dict(zip(colonnes, valeurs + [total]))})
    return pd.DataFrame(rangs, columns=["libelle", "rubrique", "bloc"] + colonnes)


def _total_rubrique(tableau, rubrique, bloc):
    """Total de la periode d'une rubrique (0 si elle n'a aucun mouvement)."""
    t = tableau[(tableau["rubrique"] == rubrique) & (tableau["bloc"] == bloc)]["Total"]
    return float(t.sum()) if len(t) else 0.0


def _somme(tableau, bloc, colonnes):
    """Somme d'un bloc, colonne par colonne ; NaN si le bloc est vide ce mois."""
    return tableau[tableau["bloc"] == bloc][colonnes].sum(min_count=1)


def _totaux(tableau, mois):
    colonnes = mois + ["Total"]
    enc = _somme(tableau, ENCAISSEMENT, colonnes)
    cha = _somme(tableau, CHARGE, colonnes)
    resultat = enc.fillna(0) - cha.fillna(0)
    resultat[enc.isna() & cha.isna()] = float("nan")
    return {"encaissements": enc, "charges": cha, "resultat": resultat,
            "pct": resultat / enc.where(enc != 0),
            "hors_exploitation": _somme(tableau, HORS, colonnes)}


def _chiffres(flux, lignes):
    """Encaissements, charges, resultat, hors exploitation d'un ensemble de flux."""
    tot = {ENCAISSEMENT: 0.0, CHARGE: 0.0, HORS: 0.0}
    for l in lignes:
        tot[l["bloc"]] += float(_valeur_affichee(_de_la_ligne(flux, l), l["bloc"]).sum())
    return {"encaissements": tot[ENCAISSEMENT], "charges": tot[CHARGE],
            "resultat": tot[ENCAISSEMENT] - tot[CHARGE], "hors_exploitation": tot[HORS]}


# --- fiche d'un centre --------------------------------------------------------------

def _mensuel(flux, lignes, mois, cible_marge):
    """Par mois : argent recu, salaires, maximum de salaires, mois de camp."""
    lignes_salaires = [l for l in lignes if l["cle"][0] == SALAIRES]
    rangs = []
    for m in mois:
        fm = flux[flux["mois"] == m]
        if len(fm) == 0:
            rangs.append({"mois": m, "vide": True})
            continue
        c = _chiffres(fm, lignes)
        salaires = sum(float(_valeur_affichee(_de_la_ligne(fm, l), CHARGE).sum()) for l in lignes_salaires)
        camp = float(fm[(fm["rubrique"] == CAMP) & (fm["sens"] == "entree")]["montant"].sum())
        maximum = plafond_salarial(c["encaissements"], c["charges"], salaires, cible_marge)
        rangs.append({"mois": m, "vide": False, "encaissements": c["encaissements"],
                      "charges": c["charges"], "resultat": c["resultat"], "salaires": salaires,
                      "maximum": maximum, "camp": camp,
                      "mois_camp": c["encaissements"] > 0 and camp > c["encaissements"] / 2})
    return rangs


def _eleves(detail, mois, fin, mois_camp=()):
    """mois_camp : les mois ('AAAA-MM') ou le camp fait l'essentiel des recettes."""
    if len(detail):
        frais = detail[(detail["rubrique"] == COURS) & (detail["sens"] == "entree")]
        vac = detail[detail["rubrique"] == SALAIRES]
        eleves_enc = detail[detail["rubrique"].isin([COURS, CAMP]) & (detail["sens"] == "entree")]
    else:
        frais = vac = eleves_enc = detail
    sans_mois = 0.0
    lignes, retard = [], {"avance": 0.0, "0": 0.0, "1": 0.0, "2": 0.0, "3+": 0.0}
    for r in frais.itertuples():
        if not r.mois_cours:
            sans_mois += r.montant
            continue
        part = r.montant / len(r.mois_cours)
        for mc in r.mois_cours:
            lignes.append({"mois_cours": mc, "tiers": r.code_tiers, "montant": part})
            ecart = (pd.Period(r.mois, "M") - pd.Period(mc, "M")).n
            cle = "avance" if ecart < 0 else ("3+" if ecart >= 3 else str(ecart))
            retard[cle] += part
    par_mois = pd.DataFrame(lignes, columns=["mois_cours", "tiers", "montant"])
    vac_mois = {}
    for r in vac.itertuples():
        if r.camp:  # vacation du camp de vacances
            continue
        cibles = r.mois_cours or [r.mois]
        for mc in cibles:
            vac_mois[mc] = vac_mois.get(mc, 0.0) - r.montant / len(cibles)

    rangs = []
    for m in mois:
        pm = par_mois[par_mois["mois_cours"] == m]
        avec_tiers = pm[pm["tiers"] != ""]
        n = int(avec_tiers["tiers"].nunique())
        rangs.append({"mois": m, "frais": float(pm["montant"].sum()) if len(pm) else float("nan"),
                      "eleves": n if len(pm) else float("nan"),
                      "frais_moyen": _div(float(avec_tiers["montant"].sum()), n),
                      "vacations": vac_mois.get(m, float("nan"))})

    # Eleves payants : la mediane des mois scolaires (hors camp) qui ont eu
    # au moins un mois pour etre payes (plus de la moitie des familles paient
    # avec un mois de retard). La mediane resiste a un mois aux pages
    # manquantes. Periode d'un seul mois : ce mois-la.
    fin_mois = pd.Period(fin, "M")
    candidats = [x for x in rangs if not _nan(x["eleves"]) and x["eleves"] > 0
                 and (len(mois) == 1 or (pd.Period(x["mois"], "M") < fin_mois
                                         and x["mois"] not in mois_camp))]
    typique = statistics.median(x["eleves"] for x in candidats) if candidats else None
    total_retard = sum(retard.values())
    eleves_mois = sum(x["eleves"] for x in rangs if not _nan(x["eleves"]))
    total_frais = float(par_mois[par_mois["tiers"] != ""]["montant"].sum())
    return {
        "par_mois": rangs,
        "eleves_typiques": typique,
        "mois_scolaires": [x["mois"] for x in candidats],
        "frais_moyen": _div(total_frais, eleves_mois),
        "retard": {k: _div(v, total_retard) for k, v in retard.items()},
        "retard_un_mois_et_plus": _div(retard["1"] + retard["2"] + retard["3+"], total_retard),
        "sans_mois": sans_mois,
        "sans_tiers": int((eleves_enc["code_tiers"] == "").sum()) if len(eleves_enc) else 0,
        "nb_encaissements": len(eleves_enc),
    }


def _niveau_ratio(valeur, cible, tolerance):
    """Correct si au moins la cible ; a surveiller jusqu'a la tolerance ;
    attention en dessous."""
    if _nan(valeur):
        return NEUTRE
    if valeur >= cible:
        return CORRECT
    return SURVEILLER if valeur >= tolerance else ATTENTION


def _fiche(c, flux, detail, lignes, mois, fin, params, soldes, soldes_debut, mensuels, banque):
    """Tout ce qu'affiche la fiche d'un centre."""
    p = params[c]
    fc = flux[flux["centre"] == c]
    dc = detail[detail["centre"] == c] if len(detail) else detail
    chiffres = _chiffres(fc, lignes)
    mensuel = _mensuel(fc, lignes, mois, p["cible_marge"])
    pleins = [m for m in mensuel if not m["vide"]]
    salaires = sum(m["salaires"] for m in pleins)
    maximum = sum(m["maximum"] for m in pleins)
    enc = chiffres["encaissements"]
    marge = _div(chiffres["resultat"], enc)
    charges_mois = _div(chiffres["charges"], len(pleins))

    sc = soldes[(soldes["centre"] == c) & soldes["physique"]]
    sd = soldes_debut[(soldes_debut["centre"] == c) & soldes_debut["physique"]]
    disponible, debut_caisse = float(sc["solde"].sum()), float(sd["solde"].sum())
    cible_caisse = p["cible_tresorerie_mois"] * charges_mois if not _nan(charges_mois) else float("nan")
    couverture = _div(disponible, charges_mois)
    # Transferts : ce que le tableau ne montre pas (rubriques exclues, 585).
    affichees = {l["cle"][0] for l in lignes}
    transferts = float(fc[~fc["rubrique"].isin(affichees)]["montant"].sum())
    vers_banque = float(banque[banque["centre"] == c]["mouvement"].sum())
    attendu = debut_caisse + chiffres["resultat"] - chiffres["hors_exploitation"] + transferts - vers_banque

    eleves = _eleves(dc, mois, fin, {m["mois"] for m in pleins if m["mois_camp"]})
    fm = eleves["frais_moyen"]
    seuil = None if _nan(charges_mois) or _nan(fm) or not fm else math.ceil(charges_mois / fm)
    au_dessus = [m["mois"] for m in pleins if m["salaires"] > m["maximum"]]
    # Mois de suite au-dessus du plafond, en partant du dernier mois.
    de_suite = 0
    for m in reversed(pleins):
        if m["salaires"] <= m["maximum"]:
            break
        de_suite += 1
    typique = eleves["eleves_typiques"]
    rendement, rendement_cible = _div(enc, salaires), (_div(enc, maximum) if maximum > 0 else float("nan"))

    return {
        **chiffres,
        "parametres": p,
        "marge": marge,
        "salaires": salaires,
        "maximum_salaires": maximum,
        "mois_salaires_au_dessus": au_dessus,
        "mois_salaires_au_dessus_de_suite": de_suite,
        "nb_mois": len(pleins),
        "rendement_salaires": rendement,
        "rendement_cible": rendement_cible,
        "mensuel": mensuel,
        "charges_mois": charges_mois,
        "caisses": [(r.intitule, float(r.solde)) for r in sc.itertuples()],
        "argent_disponible": disponible,
        "cible_tresorerie": cible_caisse,
        "couverture_mois": couverture,
        "soldes_mois": [(r.mois, r.solde) for r in mensuels[mensuels["centre"] == c].itertuples()],
        "caisse_debut": debut_caisse,
        "transferts_nets": transferts,
        "vers_banque": vers_banque,
        "caisse_attendue": attendu,
        "ecart_caisse": disponible - attendu,
        # Forces 3 et 4 : le capital de base se constitue avant toute
        # distribution. Seul ce qui le depasse est disponible pour distribuer
        # ou investir.
        "reste_a_constituer": float("nan") if _nan(cible_caisse) else max(0.0, cible_caisse - disponible),
        "distribuable": float("nan") if _nan(cible_caisse) else max(0.0, disponible - cible_caisse),
        "eleves": eleves,
        "seuil_eleves": seuil,
        "niveaux": {
            "marge": NEUTRE if _nan(marge) else (CORRECT if marge >= p["cible_marge"]
                                                  else SURVEILLER if marge > 0 else ATTENTION),
            "salaires": NEUTRE if not pleins else (CORRECT if salaires <= maximum else
                                                    SURVEILLER if salaires <= maximum * 1.05 else ATTENTION),
            "rendement": NEUTRE if _nan(rendement_cible) else _niveau_ratio(
                rendement, rendement_cible, 0.95 * rendement_cible),
            "eleves": NEUTRE if not (typique and seuil) else _niveau_ratio(typique, seuil * 1.1, seuil),
            "caisse": NEUTRE if _nan(couverture) else _niveau_ratio(
                couverture, p["cible_tresorerie_mois"], min(1.0, p["cible_tresorerie_mois"])),
            "retard": NEUTRE if _nan(eleves["retard_un_mois_et_plus"]) else (
                CORRECT if eleves["retard_un_mois_et_plus"] <= 0.4 else
                SURVEILLER if eleves["retard_un_mois_et_plus"] <= 0.75 else ATTENTION),
        },
    }


# --- fiabilite -----------------------------------------------------------------------

def _ops(df):
    return [(r.date_piece, r.piece, r.libelle, r.montant) for r in df.itertuples()]


# Un trou : au moins une semaine de jours ouvres (6 jours, lundi a samedi)
# sans aucune ecriture. Un jour isole sans mouvement est normal.
JOURS_TROU = 6


def _trous(jours):
    """Les periodes sans ecriture d'au moins JOURS_TROU jours ouvres de suite."""
    trous, courant = [], []
    for j in jours:
        if courant and (j - courant[-1]).days > (2 if courant[-1].isoweekday() == 6 else 1):
            trous.append(courant)
            courant = []
        courant.append(j)
    if courant:
        trous.append(courant)
    trous = [t for t in trous if len(t) >= JOURS_TROU]
    return {"nombre": len(trous), "jours": sum(len(t) for t in trous),
            "lignes": [(t[0], "", f"Aucune écriture du {t[0]:%d/%m} au {t[-1]:%d/%m} ({len(t)} jours ouvrés)", None)
                       for t in trous]}


def _fiabilite(debut, fin, centres, aujourd_hui=None):
    """Les controles de fiabilite, par centre : nombre et operations."""
    aujourd_hui = aujourd_hui or date.today()
    centres = list(centres)
    pieces = dl._lire_df("""
        SELECT centre, count(DISTINCT id_piece) AS total,
               count(DISTINCT id_piece) FILTER (WHERE statut IN ('validee', 'exportee')) AS validees
        FROM ecritures WHERE centre = ANY(%s) AND date_piece BETWEEN %s AND %s
        GROUP BY centre""", (centres, debut, fin))
    # Jours ouvres (lundi a samedi) sans aucune ecriture.
    jours = dl._lire_df("""
        SELECT c AS centre, j::date AS jour
        FROM unnest(%s::text[]) c,
             generate_series(%s::date, least(%s::date, %s::date), interval '1 day') j
        WHERE extract(isodow FROM j) < 7
          AND NOT EXISTS (SELECT 1 FROM ecritures e WHERE e.centre = c AND e.date_piece = j::date)
        ORDER BY 1, 2""", (centres, debut, fin, aujourd_hui))
    # Dates aberrantes : dans le futur, ou plus d'un an avant l'annee de la
    # periode (2006 pour 2026, par exemple). Toutes periodes confondues :
    # ce sont justement les pieces qui sortent de toute periode.
    dates = dl._lire_df("""
        SELECT centre, date_piece, coalesce(nullif(max(num_definitif), ''), id_piece) AS piece,
               min(libelle) AS libelle, sum(debit)::float AS montant
        FROM ecritures
        WHERE centre = ANY(%s)
          AND (date_piece > %s OR extract(year FROM date_piece) < extract(year FROM %s::date) - 1)
        GROUP BY centre, date_piece, id_piece ORDER BY date_piece""", (centres, aujourd_hui, fin))
    lignes = dl._lire_df("""
        SELECT f.centre, f.rubrique, f.date_piece, f.statut,
               coalesce(nullif(n.num, ''), f.id_piece) AS piece, f.libelle,
               f.compte, f.code_tiers, abs(f.montant)::float AS montant, f.sens
        FROM flux_tableau_bord(%s, %s, %s) f
        LEFT JOIN LATERAL (SELECT max(num_definitif) AS num FROM ecritures x
                           WHERE x.id_piece = f.id_piece) n ON true
        WHERE f.rubrique IN (%s, %s, %s, %s) OR f.statut IN %s
        ORDER BY f.date_piece""",
                         (debut, fin, centres, ATTENTE, NON_CLASSE, COURS, CAMP, STATUTS_NON_VALIDES))
    out = {}
    for c in centres:
        p = pieces[pieces["centre"] == c]
        total, validees = int(p["total"].sum()), int(p["validees"].sum())
        l = lignes[lignes["centre"] == c]
        sans_tiers = l[l["rubrique"].isin([COURS, CAMP]) & (l["sens"] == "entree") & (l["code_tiers"] == "")]
        attente = l[l["rubrique"] == ATTENTE]
        non_classe = l[l["rubrique"] == NON_CLASSE]
        non_val = l[l["statut"].isin(STATUTS_NON_VALIDES)].drop_duplicates("piece")
        j, d = jours[jours["centre"] == c], dates[dates["centre"] == c]
        out[c] = {
            "pieces": total, "validees": validees, "part_validee": _div(validees, total),
            "controles": {
                "jours": _trous(list(j["jour"])),
                "sans_tiers": {"nombre": len(sans_tiers), "lignes": _ops(sans_tiers)},
                "dates": {"nombre": len(d), "lignes": _ops(d)},
                "attente": {"nombre": len(attente), "montant": float(attente["montant"].sum()),
                            "lignes": _ops(attente)},
                "non_classe": {"nombre": int(non_classe["compte"].nunique()),
                               "montant": float(non_classe["montant"].sum()), "lignes": _ops(non_classe)},
                "non_validees": {"nombre": len(non_val), "lignes": _ops(non_val)},
            },
        }
    return out


def _niveaux_fiabilite(f, fiche):
    """Le niveau de chaque controle, a partir de son nombre."""
    ctl = f["controles"]
    part_sans_tiers = ctl["sans_tiers"]["nombre"] / max(fiche["eleves"]["nb_encaissements"], 1)
    nj = ctl["jours"]["nombre"]  # nombre de trous
    part = f["part_validee"]
    return {
        "jours": CORRECT if nj == 0 else SURVEILLER if nj == 1 else ATTENTION,
        "sans_tiers": CORRECT if part_sans_tiers <= 0.05 else SURVEILLER if part_sans_tiers <= 0.25 else ATTENTION,
        "dates": CORRECT if ctl["dates"]["nombre"] == 0 else ATTENTION,
        "attente": CORRECT if ctl["attente"]["nombre"] == 0 else SURVEILLER,
        "non_classe": CORRECT if ctl["non_classe"]["nombre"] == 0 else SURVEILLER,
        "non_validees": CORRECT if ctl["non_validees"]["nombre"] == 0 else SURVEILLER,
        "ecart": CORRECT if abs(fiche["ecart_caisse"]) < 1 else ATTENTION,
        "global": NEUTRE if _nan(part) else (CORRECT if part >= 0.9 else SURVEILLER if part >= 0.7 else ATTENTION),
    }


# --- alertes --------------------------------------------------------------------

def pct(v, dec=1):
    return "-" if _nan(v) else f"{v * 100:.{dec}f} %".replace(".", ",")


def mois_txt(v):
    if _nan(v):
        return "-"
    return f"{v:.1f}".replace(".", ",").replace(",0", "") + " mois"


def nb(n, singulier, pluriel):
    return f"{n} {singulier if n == 1 else pluriel}"


MOIS_NOMS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
             "septembre", "octobre", "novembre", "décembre"]


def _nom_mois(aaaa_mm):
    return MOIS_NOMS[int(aaaa_mm[5:]) - 1]


def _alertes(c, fiche, fiab, mois):
    """Les alertes d'un centre, calculees a partir des chiffres."""
    a = []
    niv = fiche["niveaux"]
    n, total = len(fiche["mois_salaires_au_dessus"]), fiche["nb_mois"]
    if n and niv["salaires"] != CORRECT:
        serie = fiche["mois_salaires_au_dessus_de_suite"]
        quand = f"depuis {serie} mois ({n} mois sur {total})" if serie >= 2 else f"{n} mois sur {total}"
        camp = [m["mois"] for m in fiche["mensuel"] if not m["vide"] and m["mois_camp"]
                and m["salaires"] <= m["maximum"]]
        suite = " Seuls les mois de camp compensent." if camp and n == total - len(camp) else ""
        a.append((ATTENTION if n * 2 >= total else SURVEILLER, c,
                  f"Salaires au-dessus du plafond {quand}.{suite}"))
    if niv["marge"] == ATTENTION:
        a.append((ATTENTION, c, f"Marge négative : {pct(fiche['marge'])} de l'argent reçu."))
    elif niv["marge"] == SURVEILLER:
        a.append((SURVEILLER, c, f"Marge de {pct(fiche['marge'])}, sous la cible de "
                                 f"{pct(fiche['parametres']['cible_marge'], 0)}."))
    if niv["caisse"] == ATTENTION:
        a.append((ATTENTION, c, f"La caisse couvre {mois_txt(fiche['couverture_mois'])} de charges, pour un "
                                f"capital de base de {mois_txt(fiche['parametres']['cible_tresorerie_mois'])}."))
    versee = fiche.get("contribution_mois", [])
    dernier = [m for m in fiche["mensuel"] if not m["vide"]]
    if len(mois) > 1 and versee and mois[-1] not in versee and dernier and dernier[-1]["mois"] == mois[-1]:
        a.append((SURVEILLER, c, f"Contribution au siège de {_nom_mois(mois[-1])} pas encore envoyée."))
    ctl, nf = fiab["controles"], fiab["niveaux"]
    if nf["sans_tiers"] != CORRECT:
        a.append((nf["sans_tiers"], c,
                  f"{ctl['sans_tiers']['nombre']} encaissements sur {fiche['eleves']['nb_encaissements']} "
                  "n'ont pas d'élève rattaché : impossible de suivre les impayés élève par élève."))
    if ctl["attente"]["nombre"]:
        a.append((SURVEILLER, c, nb(ctl["attente"]["nombre"], "opération attend", "opérations attendent")
                  + " encore son compte définitif (compte d'attente)."))
    if ctl["jours"]["nombre"]:
        a.append((SURVEILLER, c, nb(ctl["jours"]["nombre"], "période", "périodes")
                  + f" d'au moins une semaine sans écriture ({ctl['jours']['jours']} jours ouvrés) : "
                  "des pages de brouillard manquent peut-être."))
    if ctl["dates"]["nombre"]:
        n_d = ctl["dates"]["nombre"]
        a.append((ATTENTION, c, nb(n_d, "pièce a une date impossible", "pièces ont une date impossible")
                  + (" : elle ne compte" if n_d == 1 else " : elles ne comptent") + " dans aucune période."))
    if niv["retard"] == ATTENTION:
        a.append((SURVEILLER, c, f"{pct(fiche['eleves']['retard_un_mois_et_plus'], 0)} des frais arrivent "
                                 "avec au moins un mois de retard."))
    return a


# --- calcul unique -----------------------------------------------------------------

def calculer(debut, fin, centres, aujourd_hui=None):
    """Tout ce que les deux pages affichent, pour une periode et des centres
    deja autorises (le controle d'acces est fait par l'appelant)."""
    centres = list(centres)
    mois = mois_de(debut, fin)
    flux, detail, pieces, soldes, soldes_debut, mensuels, banque, rubriques, parametres = _lire(debut, fin, centres)
    params = _parametres(parametres, centres)
    detail = _preparer_detail(detail)
    tous = _flux_complets(flux, detail)
    tous["interne"] = tous["interne"].astype(bool)
    lignes = _lignes(rubriques)

    # Vue consolidee : sans les flux entre deux centres choisis.
    consolide = tous[~tous["interne"]]
    tableau = _tableau(consolide, lignes, mois)
    totaux = _totaux(tableau, mois)

    caisses = soldes[soldes["physique"]]
    attente = tous[(tous["rubrique"] == ATTENTE) & (tous["sens"] == "entree")]
    fiab = _fiabilite(debut, fin, centres, aujourd_hui)
    fiches, alertes = {}, []
    for c in centres:
        fiche = _fiche(c, tous, detail, lignes, mois, fin, params, soldes, soldes_debut, mensuels, banque)
        fc = tous[tous["centre"] == c]
        fiche["contribution_mois"] = sorted(set(fc[(fc["rubrique"] == CONTRIBUTION) & (fc["sens"] == "sortie")]["mois"]))
        fiche["tableau"] = _tableau(fc, lignes, mois)
        fiche["totaux"] = _totaux(fiche["tableau"], mois)
        fiche["cours_appui"] = _total_rubrique(fiche["tableau"], COURS, ENCAISSEMENT)
        fiche["camp"] = _total_rubrique(fiche["tableau"], CAMP, ENCAISSEMENT)
        fiche["non_validees"] = int(pieces[pieces["centre"] == c]["non_validees"].sum())
        fiche["attente"] = float(attente[attente["centre"] == c]["montant"].sum())
        fiab[c]["niveaux"] = _niveaux_fiabilite(fiab[c], fiche)
        fiche["fiabilite"] = fiab[c]
        fiches[c] = fiche
        alertes += _alertes(c, fiche, fiab[c], mois)
    alertes.sort(key=lambda x: ORDRE_NIVEAU[x[0]])

    ensemble_pieces = pieces[pieces["centre"].isna()]
    ens = _chiffres(consolide, lignes)
    poids = sum(max(f["encaissements"], 0) for f in fiches.values())
    ens["cible_marge"] = (sum(f["parametres"]["cible_marge"] * max(f["encaissements"], 0)
                              for f in fiches.values()) / poids) if poids else PARAMETRES_DEFAUT["cible_marge"]
    ens["argent_disponible"] = float(caisses["solde"].sum())
    return {
        "debut": debut, "fin": fin, "mois": mois, "centres": centres,
        "tableau": tableau, "totaux": totaux,
        # par_centre et fiches : le meme dictionnaire (nom garde pour l'existant).
        "par_centre": fiches, "fiches": fiches,
        "ensemble": ens,
        "banque": [(x.intitule, float(x.solde)) for x in soldes[~soldes["physique"]].itertuples()],
        "non_validees": int(ensemble_pieces["non_validees"].sum()),
        "non_classes": int(ensemble_pieces["non_classes"].sum()),
        "attente": float(attente["montant"].sum()),
        "interne": float(tous[tous["interne"] & (tous["sens"] == "entree")]["montant"].sum()),
        "alertes": alertes,
        "vide": len(tous) == 0,
    }

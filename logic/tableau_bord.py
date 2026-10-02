# ---------------------------------------------------------------------------
# Tableau de bord - calculs (02/10/2026)
#
# Une seule fonction de calcul, calculer(), alimente les bandeaux ET le
# tableau « Compte de résultat mensuel en encaissements » : ils ne peuvent
# donc jamais se contredire.
#
# Base caisse : l'argent reellement entre et sorti des caisses et de la
# banque, a la date de la piece. L'agregation est faite par PostgreSQL
# (fonctions flux_tableau_bord et soldes_tableau_bord, migration
# sql/migrations/2026-10-02_tableau_bord.sql). Le classement des comptes vit
# dans les tables rubriques_tableau et classement_comptes : aucun numero de
# compte ici.
#
# Conventions de signe : la base renvoie montant > 0 quand l'argent entre.
# Une ligne d'encaissement s'affiche telle quelle ; une ligne de charge ou de
# sortie hors exploitation s'affiche en positif quand l'argent sort.
# ---------------------------------------------------------------------------

from datetime import date

import pandas as pd

import logic.donnees as dl

ENCAISSEMENT, CHARGE, HORS = "encaissement", "charge", "hors_exploitation"
STATUTS_NON_VALIDES = ("saisie", "a_corriger")


# --- periode et centres ----------------------------------------------------------

def periode_par_defaut(aujourd_hui=None):
    """Le dernier mois qui contient des ecritures (comme l'ancien tableau de
    bord) ; le mois en cours si la base est vide. La fin est bornee a
    aujourd'hui."""
    aujourd_hui = aujourd_hui or date.today()
    df = dl._lire_df("SELECT max(date_piece) AS d FROM ecritures WHERE date_piece <= %s",
                     (aujourd_hui,))
    dernier = df["d"].iloc[0] if len(df) else None
    dernier = pd.Timestamp(dernier).date() if dernier is not None and not pd.isna(dernier) else aujourd_hui
    debut = dernier.replace(day=1)
    fin = min((pd.Timestamp(debut) + pd.offsets.MonthEnd(0)).date(), aujourd_hui)
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
    flux = dl._lire_df("""
        SELECT centre, mois, rubrique, sens, sum(montant)::float AS montant
        FROM flux_tableau_bord(%s, %s, %s)
        GROUP BY centre, mois, rubrique, sens""", (debut, fin, list(centres)))
    pieces = dl._lire_df("""
        SELECT centre,
               count(DISTINCT id_piece) FILTER (WHERE statut IN %s) AS non_validees,
               count(DISTINCT compte) FILTER (WHERE rubrique = 'non_classe') AS non_classes
        FROM flux_tableau_bord(%s, %s, %s)
        GROUP BY GROUPING SETS ((centre), ())""",
                         (STATUTS_NON_VALIDES, debut, fin, list(centres)))
    soldes = dl._lire_df("SELECT * FROM soldes_tableau_bord(%s, %s)", (fin, list(centres)))
    rubriques = dl._lire_df("SELECT * FROM rubriques_tableau ORDER BY ordre")
    return flux, pieces, soldes, rubriques


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


def _tableau(flux, lignes, mois):
    """DataFrame : une ligne par poste, une colonne par mois + 'Total'.
    NaN = aucune donnee (affiche « - »)."""
    colonnes = mois + ["Total"]
    rangs = []
    for l in sorted(lignes, key=lambda x: x["ordre"]):
        rubrique, sens = l["cle"]
        f = flux[flux["rubrique"] == rubrique]
        if sens:
            f = f[f["sens"] == sens]
        if len(f) == 0 and not l["toujours"]:
            continue
        v = _valeur_affichee(f, l["bloc"]).groupby(f["mois"]).sum()
        valeurs = [v.get(m, float("nan")) for m in mois]
        total = v.sum() if len(v) else float("nan")
        rangs.append({"libelle": l["libelle"], "bloc": l["bloc"], **dict(zip(colonnes, valeurs + [total]))})
    return pd.DataFrame(rangs, columns=["libelle", "bloc"] + colonnes)


def _somme(tableau, bloc, colonnes):
    """Somme d'un bloc, colonne par colonne ; NaN si le bloc est vide ce mois."""
    sous = tableau[tableau["bloc"] == bloc][colonnes]
    return sous.sum(min_count=1)


def _chiffres(flux, lignes):
    """Les trois chiffres du bandeau, sur un sous-ensemble de flux."""
    tot = {ENCAISSEMENT: 0.0, CHARGE: 0.0, HORS: 0.0}
    for l in lignes:
        rubrique, sens = l["cle"]
        f = flux[flux["rubrique"] == rubrique]
        if sens:
            f = f[f["sens"] == sens]
        tot[l["bloc"]] += float(_valeur_affichee(f, l["bloc"]).sum())
    return {"encaissements": tot[ENCAISSEMENT], "charges": tot[CHARGE],
            "resultat": tot[ENCAISSEMENT] - tot[CHARGE], "hors_exploitation": tot[HORS]}


# --- calcul unique -----------------------------------------------------------------

def calculer(debut, fin, centres):
    """Tout ce que la page affiche, pour une periode et des centres deja
    autorises (le controle d'acces est fait par l'appelant)."""
    mois = mois_de(debut, fin)
    flux, pieces, soldes, rubriques = _lire(debut, fin, centres)
    lignes = _lignes(rubriques)

    tableau = _tableau(flux, lignes, mois)
    colonnes = mois + ["Total"]
    enc = _somme(tableau, ENCAISSEMENT, colonnes)
    cha = _somme(tableau, CHARGE, colonnes)
    resultat = enc.fillna(0) - cha.fillna(0)
    resultat[enc.isna() & cha.isna()] = float("nan")
    pct = resultat / enc.where(enc != 0)
    totaux = {"encaissements": enc, "charges": cha, "resultat": resultat, "pct": pct,
              "hors_exploitation": _somme(tableau, HORS, colonnes)}

    caisses = soldes[soldes["physique"]]
    attente = flux[(flux["rubrique"] == "attente") & (flux["sens"] == "entree")]
    par_centre = {}
    for c in centres:
        sc = caisses[caisses["centre"] == c]
        pc = pieces[pieces["centre"] == c]
        par_centre[c] = {
            **_chiffres(flux[flux["centre"] == c], lignes),
            "caisses": [(r.intitule, float(r.solde)) for r in sc.itertuples()],
            "argent_disponible": float(sc["solde"].sum()),
            "non_validees": int(pc["non_validees"].sum()),
            "attente": float(attente[attente["centre"] == c]["montant"].sum()),
        }
    ensemble = pieces[pieces["centre"].isna()]
    return {
        "debut": debut, "fin": fin, "mois": mois, "centres": list(centres),
        "tableau": tableau, "totaux": totaux, "par_centre": par_centre,
        "ensemble": {**_chiffres(flux, lignes),
                     "argent_disponible": float(caisses["solde"].sum())},
        "banque": [(r.intitule, float(r.solde)) for r in soldes[~soldes["physique"]].itertuples()],
        "non_validees": int(ensemble["non_validees"].sum()),
        "non_classes": int(ensemble["non_classes"].sum()),
        "attente": float(attente["montant"].sum()),
        "vide": len(flux) == 0,
    }

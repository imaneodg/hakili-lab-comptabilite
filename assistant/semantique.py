# ---------------------------------------------------------------------------
# Couche semantique : transforme les lignes d'ecriture en FAITS de gestion,
# avec une seule definition de chaque chiffre pour tout l'assistant.
#
#   flux     une ligne par mouvement reel de tresorerie (caisse ou banque),
#            hors transferts entre caisses / entre centres. sens = entree ou
#            sortie. `compte` y est la CONTREPARTIE de la piece (411000 pour
#            un reglement d'eleve, 401000 pour un fournisseur...), `code_tiers`
#            le tiers de la piece.
#   charges  une ligne par charge de gestion : comptes de charge (net des
#            avoirs), salaires 422000, et reglements passes directement par le
#            collectif fournisseur 401000 - rattaches a leur categorie par les
#            motifs de la table categories_charge.
#
# Les regles comptables reprises de logic/analyse.py (et deja testees la-bas)
# ne sont pas reecrites : pieces_transfert_interne, _comptes_caisse,
# _comptes_charge_elargi, COMPTE_*.
# ---------------------------------------------------------------------------

import re
from datetime import date

import pandas as pd

import logic.analyse as an
import logic.donnees as dl

STATUTS_VALIDES = {"validee", "exportee"}
STATUTS_NON_VALIDES = {"saisie", "a_corriger"}


# =============================================================================
# LECTURE
# =============================================================================

def lire_lignes(du=None, au=None, centres=None):
    """Lignes d'ecriture filtrees EN BASE (date, centres) - jamais tout
    l'historique quand une periode suffit."""
    where, params = [], []
    if du is not None:
        where.append("date_piece >= %s")
        params.append(du)
    if au is not None:
        where.append("date_piece <= %s")
        params.append(au)
    if centres:
        where.append("centre = ANY(%s)")
        params.append(list(centres))
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    df = dl._lire_df(f"SELECT * FROM ecritures {clause} ORDER BY date_piece, id_piece",
                     params=params or None)
    return dl._normaliser_lecture(df)


def fournisseurs_en_regime_facture(R):
    """Fournisseurs dont la charge est reconnue a la facture (piece qui credite
    401000 contre un compte de charge). Leurs reglements ne sont alors qu'un
    mouvement de tresorerie : les compter en charge serait un double comptage.
    Meme regle que logic.analyse.tiers_en_regime_facture, calculee en SQL sur
    tout l'historique (une facture de fevrier reglee en mars)."""
    charges = sorted(an._comptes_charge_elargi(R.ref))
    if not charges:
        return set()
    with dl._connexion() as c, c.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT e.code_tiers FROM ecritures e "
            "WHERE e.compte = %s AND e.credit > 0 AND e.code_tiers <> '' AND EXISTS ("
            "  SELECT 1 FROM ecritures x WHERE x.id_piece = e.id_piece AND x.debit > 0 "
            "  AND x.compte = ANY(%s))",
            (an.COMPTE_FOURNISSEUR, charges))
        return {r[0] for r in cur.fetchall()}


def plage_donnees():
    """(premiere date, derniere date) des ecritures plausibles. Les dates
    aberrantes (plus de deux ans en arriere, ou dans le futur) sont ignorees
    ici : elles ont leur propre controle (controles 'dates_douteuses')."""
    with dl._connexion() as c, c.cursor() as cur:
        cur.execute("SELECT min(date_piece), max(date_piece) FROM ecritures "
                    "WHERE date_piece >= make_date(extract(year FROM CURRENT_DATE)::int - %s, 1, 1) "
                    "AND date_piece <= CURRENT_DATE", (an.RECUL_ANNEES_DATE_PLAUSIBLE,))
        r = cur.fetchone()
    return (r[0], r[1]) if r else (None, None)


# =============================================================================
# CATEGORIES DE CHARGE
# =============================================================================

def categorie_du_compte(compte, R):
    """Categorie d'un compte de charge : prefixe le plus long de la table
    categories_charge, sinon la rubrique SYSCOHADA (classe_62, classe_63...)."""
    compte = str(compte)
    meilleure, longueur = None, 0
    for cat in R.categories:
        for p in cat.comptes:
            if compte.startswith(p) and len(p) > longueur:
                meilleure, longueur = cat.code, len(p)
    if meilleure:
        return meilleure
    if compte.startswith("6") and len(compte) >= 2:
        return f"classe_{compte[:2]}"
    return "non_ventile"


def categorie_du_libelle(libelle, R):
    """Categorie d'un reglement 401000 d'apres son libelle ; 'non_ventile'
    si aucun motif ne correspond (a traiter par la comptable)."""
    texte = str(libelle or "").upper()
    for cat in sorted(R.categories, key=lambda c: c.ordre):
        for motif in cat.motifs:
            if motif and motif in texte:
                return cat.code
    return "non_ventile"


def groupe_de(categorie, R):
    c = R.categorie(categorie)
    if c:
        return c.groupe
    if categorie == "classe_66":
        return "masse_salariale"
    return "autre"


# =============================================================================
# FAITS
# =============================================================================

COLONNES_FAITS = ["id_piece", "date", "centre", "journal", "statut", "compte", "code_tiers",
                  "libelle"]


def _tiers_par_piece(d):
    t = d[d["code_tiers"] != ""]
    return t.groupby("id_piece")["code_tiers"].first().to_dict() if len(t) else {}


def faits_flux(d, R):
    """Mouvements reels de tresorerie, hors transferts internes."""
    vide = pd.DataFrame(columns=COLONNES_FAITS + ["sens", "montant"])
    if d is None or len(d) == 0:
        return vide
    tresorerie_journaux = an._comptes_caisse(R.ref)
    tresorerie_toute = an._comptes_tresorerie(R.ref)
    transferts = an.pieces_transfert_interne(d, R.ref)
    if "modele" in d.columns:
        transferts |= set(d.loc[d["modele"].isin(an.MODELES_TRANSFERT_INTERNE), "id_piece"])
    lignes = d[d["compte"].isin(tresorerie_journaux) & ~d["id_piece"].isin(transferts)]
    lignes = lignes[(lignes["debit"] != 0) | (lignes["credit"] != 0)]
    if len(lignes) == 0:
        return vide
    # Contrepartie de chaque piece : la ligne hors tresorerie la plus forte.
    autres = d[d["id_piece"].isin(set(lignes["id_piece"])) & ~d["compte"].isin(tresorerie_toute)].copy()
    autres["poids"] = autres["debit"] + autres["credit"]
    contrepartie = (autres.sort_values("poids", ascending=False)
                          .groupby("id_piece")["compte"].first().to_dict()) if len(autres) else {}
    tiers = _tiers_par_piece(d[d["id_piece"].isin(set(lignes["id_piece"]))])
    f = pd.DataFrame({
        "id_piece": lignes["id_piece"].values,
        "date": pd.to_datetime(lignes["date_piece"]).dt.date.values,
        "centre": lignes["centre"].values,
        "journal": lignes["journal"].values,
        "statut": lignes["statut"].values,
        "compte": [contrepartie.get(p, "") for p in lignes["id_piece"]],
        "code_tiers": [tiers.get(p, "") for p in lignes["id_piece"]],
        "libelle": lignes["libelle"].values,
        "sens": ["entree" if x > 0 else "sortie" for x in lignes["debit"]],
        "montant": [float(x if x > 0 else c) for x, c in zip(lignes["debit"], lignes["credit"])],
    })
    # Type de chaque mouvement, dans les mots du directeur : d'ou vient
    # l'argent recu, a quoi a servi l'argent depense.
    comptes_charge = an._comptes_charge_elargi(R.ref)
    charge_de_piece = (d[d["id_piece"].isin(set(lignes["id_piece"])) & d["compte"].isin(comptes_charge)
                         & (d["debit"] > 0)].groupby("id_piece")["compte"].first().to_dict())
    f["categorie"] = [type_mouvement(sens, cp, charge_de_piece.get(p), lib, R)
                      for sens, cp, p, lib in zip(f["sens"], f["compte"], f["id_piece"], f["libelle"])]
    return f


def type_mouvement(sens, contrepartie, compte_charge, libelle, R):
    """Type d'une entree ou d'une sortie d'argent (cle de categorie)."""
    cp = str(contrepartie or "")
    lib = str(libelle or "").upper()
    if sens == "entree":
        if cp == "411000":
            return "cours"
        if cp.startswith("707"):
            return "documents"
        if cp.startswith("7"):
            return "autres_produits"
        if cp.startswith("2728") or cp.startswith("4223"):
            return "remboursement_pret_recu"
        if cp.startswith("16"):
            return "emprunt_recu"
        if cp.startswith("471"):
            return "a_classer"
        return "autres_entrees"
    if compte_charge:
        return categorie_du_compte(compte_charge, R)
    if cp == an.COMPTE_FOURNISSEUR:
        return categorie_du_libelle(lib, R)
    if cp == "422000":
        return "salaires"
    if cp.startswith("4223") or cp.startswith("2728"):
        return "avances_personnel"
    if cp.startswith("16"):
        return "remboursement_emprunt"
    if cp.startswith("2"):
        return "equipement"
    if cp == "411000":
        return "remboursement_parent" if "REMB" in lib else "mal_classe_eleves"
    if cp.startswith("471"):
        return "a_classer"
    if cp.startswith("44"):
        return "impots"
    if cp.startswith("6"):
        return categorie_du_compte(cp, R)
    return "autres_sorties"


def faits_charges(d, R, regime_facture=None):
    """Charges de gestion (voir l'en-tete du module)."""
    vide = pd.DataFrame(columns=COLONNES_FAITS + ["categorie", "groupe", "montant"])
    if d is None or len(d) == 0:
        return vide
    ref = R.ref
    comptes_charge = an._comptes_charge_elargi(ref)
    nature = dict(zip(ref["comptes"]["compte"], ref["comptes"]["nature"]))
    est_directe = d["compte"].isin(comptes_charge)
    directes = d[est_directe & ((d["debit"] > 0) | (d["credit"] > 0))].copy()
    # 422000 (dette envers le personnel) : seul le debit - le paiement - est une
    # charge, comme dans logic.analyse. Les vrais comptes de charge sont pris
    # nets (debit - credit) : un avoir ou une correction vient en deduction.
    if len(directes):
        est_charge = directes["compte"].map(lambda c: nature.get(c) == "charge")
        directes = directes[est_charge | (directes["debit"] > 0)]
        directes["montant"] = [float(dbt - cdt) if nature.get(c) == "charge" else float(dbt)
                               for c, dbt, cdt in zip(directes["compte"], directes["debit"],
                                                      directes["credit"])]
        directes["categorie"] = [categorie_du_compte(c, R) for c in directes["compte"]]
    pieces_avec_charge = set(d.loc[est_directe & (d["debit"] > 0), "id_piece"])
    reglements = d[(d["compte"] == an.COMPTE_FOURNISSEUR) & (d["debit"] > 0)
                   & ~d["id_piece"].isin(pieces_avec_charge)].copy()
    if regime_facture and len(reglements):
        reglements = reglements[~reglements["code_tiers"].isin(regime_facture)]
    if len(reglements):
        reglements["montant"] = reglements["debit"].astype(float)
        reglements["categorie"] = [categorie_du_libelle(l, R) for l in reglements["libelle"]]
        # Le compte affiche est celui de la charge reconstituee, 401000 sinon.
        premier_compte = {c.code: (c.comptes[0] if c.comptes else an.COMPTE_FOURNISSEUR)
                          for c in R.categories}
        reglements["compte"] = [premier_compte.get(cat, an.COMPTE_FOURNISSEUR)
                                for cat in reglements["categorie"]]
    toutes = pd.concat([x for x in (directes, reglements) if len(x)], ignore_index=True) \
        if (len(directes) or len(reglements)) else None
    if toutes is None or len(toutes) == 0:
        return vide
    tiers = _tiers_par_piece(d[d["id_piece"].isin(set(toutes["id_piece"]))])
    f = pd.DataFrame({
        "id_piece": toutes["id_piece"].values,
        "date": pd.to_datetime(toutes["date_piece"]).dt.date.values,
        "centre": toutes["centre"].values,
        "journal": toutes["journal"].values,
        "statut": toutes["statut"].values,
        "compte": toutes["compte"].values,
        "code_tiers": [t or tiers.get(p, "") for t, p in zip(toutes["code_tiers"], toutes["id_piece"])],
        "libelle": toutes["libelle"].values,
        "categorie": toutes["categorie"].values,
        "groupe": [groupe_de(c, R) for c in toutes["categorie"]],
        "montant": toutes["montant"].values,
    })
    f = f[f["montant"] != 0].reset_index(drop=True)
    return rattacher(f)


# =============================================================================
# RATTACHEMENT A LA PERIODE DE PRESTATION (principe SYSCOHADA de
# rattachement des produits et des charges a l'exercice / au mois qu'ils
# concernent)
#
# A Hakili Lab, le mois concerne est ecrit dans le libelle, par la caisse ou
# par les modeles de saisie : "FRAIS CA KABORE HADIDJATOU/MARS", "AVANCE CA
# JAN-JUIN-JUIL - ...", "PAIEMENT VACATION DECEMBRE", "PAIEMENT LOYER MAI".
# Un paiement de vacations de decembre fait en janvier est une charge de
# decembre ; des frais de cours d'avril payes en mars sont un produit d'avril.
# Sans mois dans le libelle, la date de la piece fait foi.
# =============================================================================

# Noms complets : reconnus aussi colles a un autre mot ("DECEMBRESOLDE").
# Abreviations : seulement en mot isole (sinon "MAIGA" deviendrait "mai").
_MOIS_LONGS = {"JANVIER": 1, "FEVRIER": 2, "AVRIL": 4, "JUILLET": 7, "AOUT": 8, "SEPTEMBRE": 9,
               "OCTOBRE": 10, "NOVEMBRE": 11, "DECEMBRE": 12}
_MOIS_EXACTS = {"JANV": 1, "JAN": 1, "FEV": 2, "FEVR": 2, "MARS": 3, "AVR": 4, "MAI": 5, "JUIN": 6,
                "JUIL": 7, "SEPT": 9, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}


def mois_du_libelle(libelle, date_piece):
    """Mois de prestation cites dans un libelle -> [(annee, mois)], dans l'ordre.
    L'annee est celle qui place le mois au plus pres de la date de la piece :
    'DEC' paye le 10/01/2026 -> decembre 2025 ; 'JUIN' paye le 15/03/2026 ->
    juin 2026 (avance)."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(libelle or "")).encode("ascii", "ignore").decode().upper()
    mots = [mot for mot in re.split(r"[^A-Z]+", t) if mot]
    lus = []
    for mot in mots:
        m = _MOIS_EXACTS.get(mot)
        if m is None:
            m = next((v for k, v in _MOIS_LONGS.items() if mot.startswith(k)), None)
        if m is None and mot.startswith("MARS") and len(mot) > 4 and mot[4:] in ("SOLDE", "AVANCE"):
            m = 3
        lus.append(m)
    trouves = []
    for i, m in enumerate(lus):
        # Plage "OCT A DEC" : forme ecrite par les encaissements du 18 au
        # 25/09/2026 pour trois mois consecutifs ou plus. Les mois du milieu
        # n'y sont pas cites mais sont bien couverts : sans cette lecture,
        # novembre etait oublie et son produit reparti sur octobre et
        # decembre. Ne s'applique qu'entre deux mois et dans l'ordre de
        # l'annee scolaire (septembre -> aout), jamais sur un "A" isole.
        if (m is None and mots[i] == "A" and 0 < i < len(lus) - 1
                and lus[i - 1] and lus[i + 1]):
            ordre = [9, 10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8]
            debut, fin = ordre.index(lus[i - 1]), ordre.index(lus[i + 1])
            for milieu in ordre[debut + 1:fin] if debut < fin else []:
                if milieu not in trouves:
                    trouves.append(milieu)
            continue
        if m and m not in trouves:
            trouves.append(m)
    if not trouves:
        return []
    d = date_(date_piece)
    res = []
    for m in trouves:
        candidats = [(a, m) for a in (d.year - 1, d.year, d.year + 1)]
        res.append(min(candidats, key=lambda am: abs((am[0] - d.year) * 12 + am[1] - d.month)))
    return res


def rattacher(f):
    """Repartit chaque fait sur son (ses) mois de prestation. Ajoute la colonne
    `date_paiement` et remplace `date` par la date d'effet : la date de la piece
    si elle tombe dans le mois concerne, le 1er du mois concerne sinon. Un
    paiement pour plusieurs mois est reparti a parts egales."""
    if f is None or len(f) == 0:
        f = f.copy() if f is not None else pd.DataFrame()
        f["date_paiement"] = pd.Series(dtype=object)
        f["rattache"] = pd.Series(dtype=bool)
        return f
    lignes = []
    for r in f.to_dict("records"):
        r["date_paiement"] = r["date"]
        mois = mois_du_libelle(r.get("libelle"), r["date"])
        if not mois or mois == [(r["date"].year, r["date"].month)]:
            r["rattache"] = False
            lignes.append(r)
            continue
        part = r["montant"] / len(mois)
        for a, m in mois:
            x = dict(r)
            x["montant"] = part
            x["date"] = r["date"] if (a, m) == (r["date"].year, r["date"].month) else date(a, m, 1)
            x["rattache"] = True
            lignes.append(x)
    return pd.DataFrame(lignes)


def clients_en_regime_facture(d, R):
    """Eleves factures au journal des ventes (411 au debit contre un produit de
    classe 7) : leur reglement sur 411 n'est qu'un encaissement, le produit a
    deja ete reconnu a la facture. Symetrique de fournisseurs_en_regime_facture."""
    if d is None or len(d) == 0:
        return set()
    pieces_produit = set(d.loc[d["compte"].astype(str).str.startswith("7") & (d["credit"] > 0), "id_piece"])
    f = d[(d["compte"] == "411000") & (d["debit"] > 0) & d["id_piece"].isin(pieces_produit)
          & (d["code_tiers"] != "")]
    return set(f["code_tiers"])


def faits_produits(d, R):
    """Produits de gestion (chiffre d'affaires) au sens SYSCOHADA :

    - prestations de soutien scolaire : a Hakili Lab, les frais de cours sont
      encaisses sans facture (571 au debit, 411000 au credit) ; le credit de
      411000 EST donc le produit, rattache au mois de cours cite dans le
      libelle (706 "services vendus" dans un plan SYSCOHADA strict) ;
    - remboursements aux parents (411000 au debit, libelle "REMBOURS...") :
      viennent en deduction ;
    - comptes de classe 7 (frais de dossier / documents 707810...) : nets
      (credit - debit), a la date de la piece.

    Les autres debits de 411000 (vacation ou contribution SIAO imputees par
    erreur sur le compte eleves) ne sont PAS des produits negatifs : ce sont
    des erreurs d'imputation, signalees par le controle 'imputations_411'."""
    colonnes = COLONNES_FAITS + ["categorie", "montant"]
    if d is None or len(d) == 0:
        return rattacher(pd.DataFrame(columns=colonnes))
    factures = clients_en_regime_facture(d, R)
    cours = d[(d["compte"] == "411000") & (d["credit"] > 0) & ~d["code_tiers"].isin(factures)].copy()
    cours["montant"] = cours["credit"].astype(float)
    cours["categorie"] = "cours"
    remb = d[(d["compte"] == "411000") & (d["debit"] > 0)
             & d["libelle"].str.upper().str.contains("REMBOURS|REMBROUS|REMBOURSEMENT PARENT", regex=True)].copy()
    remb["montant"] = -remb["debit"].astype(float)
    remb["categorie"] = "cours"
    cl7 = d[d["compte"].astype(str).str.startswith("7")].copy()
    cl7["montant"] = (cl7["credit"] - cl7["debit"]).astype(float)
    cl7["categorie"] = ["documents" if str(c).startswith("707") else "autres_produits" for c in cl7["compte"]]
    tout = pd.concat([x for x in (cours, remb, cl7) if len(x)], ignore_index=True) \
        if (len(cours) or len(remb) or len(cl7)) else pd.DataFrame(columns=list(d.columns) + ["montant", "categorie"])
    if len(tout) == 0:
        return rattacher(pd.DataFrame(columns=colonnes))
    f = pd.DataFrame({
        "id_piece": tout["id_piece"].values,
        "date": pd.to_datetime(tout["date_piece"]).dt.date.values,
        "centre": tout["centre"].values, "journal": tout["journal"].values,
        "statut": tout["statut"].values, "compte": tout["compte"].values,
        "code_tiers": tout["code_tiers"].values, "libelle": tout["libelle"].values,
        "categorie": tout["categorie"].values, "montant": tout["montant"].values,
    })
    f = f[f["montant"] != 0].reset_index(drop=True)
    # Seuls les frais de cours sont rattaches par le libelle ; un produit de
    # classe 7 est deja comptabilise a sa date.
    cours_f = rattacher(f[f["categorie"] == "cours"])
    autres = f[f["categorie"] != "cours"].copy()
    autres["date_paiement"] = autres["date"]
    autres["rattache"] = False
    return pd.concat([x for x in (cours_f, autres) if len(x)], ignore_index=True) if (len(cours_f) or len(autres)) \
        else rattacher(pd.DataFrame(columns=colonnes))


def imputations_411_a_verifier(d):
    """Debits de 411000 qui ne sont ni un remboursement de parent ni un
    reglement de facture : vacation, contribution SIAO... passees par erreur
    sur le compte eleves."""
    if d is None or len(d) == 0:
        return d
    x = d[(d["compte"] == "411000") & (d["debit"] > 0)]
    return x[~x["libelle"].str.upper().str.contains("REMBOURS|REMBROUS", regex=True)]


def faits_attente(d):
    """Lignes du compte d'attente 471000 (argent recu ou sorti dont le compte
    definitif reste a trouver). montant = debit - credit."""
    if d is None or len(d) == 0:
        return pd.DataFrame(columns=COLONNES_FAITS + ["montant"])
    l = d[d["compte"] == an.COMPTE_ATTENTE]
    return pd.DataFrame({
        "id_piece": l["id_piece"].values,
        "date": pd.to_datetime(l["date_piece"]).dt.date.values if len(l) else [],
        "centre": l["centre"].values, "journal": l["journal"].values,
        "statut": l["statut"].values, "compte": l["compte"].values,
        "code_tiers": l["code_tiers"].values, "libelle": l["libelle"].values,
        "montant": (l["debit"] - l["credit"]).astype(float).values,
    })


def date_(x):
    return x if isinstance(x, date) else pd.Timestamp(x).date()

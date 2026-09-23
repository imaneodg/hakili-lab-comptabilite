# ---------------------------------------------------------------------------
# Moteur d'analyse de l'assistant : toutes les questions chiffrees passent
# par ici. Aucune fonction ne renvoie un chiffre sans son perimetre (periode,
# centres, base, pieces non validees), et aucune ne confond "zero" et
# "aucune donnee".
#
# Chaque resultat est garde dans le contexte de la conversation sous un
# identifiant (r1, r2...) : c'est a partir de ce resultat EXACT que les
# graphiques sont traces, jamais a partir de chiffres recopies par le modele.
# ---------------------------------------------------------------------------

import calendar
import itertools
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import pandas as pd

import logic.analyse as an
import logic.donnees as dl
from assistant import config, referentiel, semantique as sem
from assistant.comprehension import (Incomprehension, Periode, chercher_tiers, resoudre_categories,
                                     resoudre_centres, resoudre_compte, resoudre_journaux,
                                     resoudre_periode, resoudre_tiers)
from assistant.indicateurs import (DEPENDANCES, DIMENSIONS, DIMENSIONS_TEMPS, INDICATEURS,
                                   resoudre_dimensions, resoudre_indicateurs)
from assistant.texte import (date_courte, libelle_periode, mois_lisible, montant, normaliser,
                             pourcentage)

LIBELLES_STATUT = {"saisie": "En attente de validation", "validee": "Validée",
                   "a_corriger": "Renvoyée pour correction", "exportee": "Envoyée à Sage"}


# =============================================================================
# CONTEXTE DE CONVERSATION ET RESULTATS
# =============================================================================

@dataclass
class Resultat:
    id: str
    type: str                      # analyse, comparaison, liste, soldes, controle, sql
    titre: str
    table: pd.DataFrame            # colonnes d'affichage deja libellees + valeurs brutes
    colonnes: list                 # [(colonne, libelle, unite)] dans l'ordre d'affichage
    cle_x: Optional[str] = None    # colonne qui sert d'axe pour un graphique
    cle_serie: Optional[str] = None
    valeurs: list = field(default_factory=list)   # colonnes numeriques tracables
    total: dict = field(default_factory=dict)
    perimetre: dict = field(default_factory=dict)
    temporel: bool = False
    graphique_suggere: Optional[str] = None


class Contexte:
    """Etat d'une conversation : portee de l'utilisateur et resultats deja
    calcules. Un par session Shiny, jamais partage."""

    def __init__(self, portee=None, aujourd_hui=None):
        self.portee = list(portee) if portee is not None else None   # None = tous les centres
        self._aujourd_hui = aujourd_hui
        self.resultats = {}
        self._compteur = itertools.count(1)

    @property
    def aujourd_hui(self):
        return self._aujourd_hui or date.today()

    @property
    def R(self):
        return referentiel.charger()

    @property
    def restreint(self):
        return self.portee is not None

    def garder(self, resultat):
        self.resultats[resultat.id] = resultat
        while len(self.resultats) > config.RESULTATS_EN_CACHE:
            self.resultats.pop(next(iter(self.resultats)))
        return resultat

    def nouvel_id(self):
        return f"r{next(self._compteur)}"

    def vider(self):
        self.resultats.clear()


def periode_par_defaut(ctx):
    """Periode d'une question qui n'en donne pas : le mois en cours. Si rien
    n'y est encore enregistre, le dernier mois qui a des operations - et on
    le dit."""
    auj = ctx.aujourd_hui
    debut = date(auj.year, auj.month, 1)
    fin_donnees = sem.plage_donnees()[1]
    if fin_donnees and fin_donnees < debut:
        d0 = date(fin_donnees.year, fin_donnees.month, 1)
        d1 = date(d0.year, d0.month, calendar.monthrange(d0.year, d0.month)[1])
        return Periode(du=d0, au=d1, libelle=libelle_periode(d0, d1, auj),
                       interpretation=f"rien n'est encore enregistré en "
                                      f"{mois_lisible(debut.strftime('%Y%m'))} : voici "
                                      f"{mois_lisible(d0.strftime('%Y%m'))}")
    return Periode(du=debut, au=auj, libelle=libelle_periode(debut, auj, auj), en_cours=True)


def _valeur_modele(v, unite):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if unite == "%":
        return round(float(v), 1)
    return int(round(float(v)))


def _libelle_centres(codes, R):
    if set(codes) == set(R.centres_actifs()) and len(codes) > 1:
        return "tous les centres"
    return ", ".join(R.nom_centre(c) for c in codes)


# =============================================================================
# BASE DE CALCUL : un tableau long, une ligne par fait, avec les mesures
# =============================================================================

_MESURES = ["enc", "dec", "scol", "chg", "ms", "cf", "att", "prd"]
MESURE_DE = {"encaissements": "enc", "decaissements": "dec", "frais_scolarite": "scol",
             "autres_encaissements": "enc", "charges": "chg", "masse_salariale": "ms",
             "charges_fixes": "cf", "en_attente_471": "att", "produits": "prd"}


def _sources(inds):
    s = set()
    for i in inds:
        for dep in [i] + DEPENDANCES.get(i, []):
            src = INDICATEURS[dep]["source"]
            if src != "derive":
                s.add(src)
    return s


def _base(d, R, sources, regime, d_etendu=None, per=None):
    """d : lignes de la periode (tresorerie, 471). d_etendu : lignes autour de
    la periode, pour les produits et charges rattaches a leur mois de
    prestation (un paiement de janvier peut etre une charge de decembre) ;
    ils sont ensuite bornes a la periode sur leur date d'effet."""
    morceaux = []
    source_rattachee = d if d_etendu is None else d_etendu

    def _borner(f):
        if per is None or len(f) == 0:
            return f
        dates = pd.to_datetime(f["date"]).dt.date
        return f[(dates >= per.du) & (dates <= per.au)]

    if "flux" in sources:
        f = sem.faits_flux(d, R)
        if len(f):
            f = f.copy()
            ent = f["sens"] == "entree"
            f["enc"] = f["montant"].where(ent, 0.0)
            f["dec"] = f["montant"].where(~ent, 0.0)
            f["scol"] = f["enc"].where(f["compte"] == "411000", 0.0)
            f["piece"] = f["id_piece"]
            f["eleve"] = f["code_tiers"].where(ent & (f["compte"] == "411000"), "")
            morceaux.append(f)
    if "produits" in sources:
        p = _borner(sem.faits_produits(source_rattachee, R))
        if len(p):
            p = p.copy()
            p["prd"] = p["montant"]
            p["piece"] = None
            p["eleve"] = ""
            morceaux.append(p)
    if "charges" in sources:
        c = _borner(sem.faits_charges(source_rattachee, R, regime))
        if len(c):
            c = c.copy()
            c["chg"] = c["montant"]
            c["ms"] = c["montant"].where(c["groupe"] == "masse_salariale", 0.0)
            c["cf"] = c["montant"].where(c["groupe"] == "charges_fixes", 0.0)
            c["piece"] = None
            c["eleve"] = ""
            morceaux.append(c)
    if "attente" in sources:
        a = sem.faits_attente(d)
        if len(a):
            a = a.copy()
            a["att"] = a["montant"]
            a["piece"] = None
            a["eleve"] = ""
            a["categorie"] = None
            morceaux.append(a)
    colonnes = ["id_piece", "date", "centre", "journal", "statut", "compte", "code_tiers",
                "libelle", "categorie", "piece", "eleve"] + _MESURES
    if not morceaux:
        return pd.DataFrame(columns=colonnes)
    b = pd.concat(morceaux, ignore_index=True)
    for m in _MESURES:
        b[m] = pd.to_numeric(b[m], errors="coerce").fillna(0.0) if m in b.columns else 0.0
    b = b[[c for c in colonnes if c in b.columns]]
    dt = pd.to_datetime(b["date"])
    b["mois"] = dt.dt.strftime("%Y%m")
    b["jour"] = dt.dt.strftime("%Y-%m-%d")
    b["semaine"] = (dt - pd.to_timedelta(dt.dt.weekday, unit="D")).dt.strftime("%Y-%m-%d")
    b["annee_scolaire"] = [f"{x.year}-{x.year + 1}" if x.month >= 9 else f"{x.year - 1}-{x.year}"
                           for x in dt]
    b["tiers"] = b["code_tiers"]
    return b


def _agreger(b, dims):
    if len(b) == 0:
        return pd.DataFrame(columns=dims + _MESURES + ["nb_pieces", "eleves_payants"])
    if dims:
        g = b.groupby(dims, dropna=False)
        s = g[_MESURES].sum()
        s["nb_pieces"] = g["piece"].nunique()
        s["eleves_payants"] = g["eleve"].agg(lambda x: x[x != ""].nunique())
        return s.reset_index()
    s = b[_MESURES].sum().to_dict()
    s["nb_pieces"] = b["piece"].dropna().nunique()
    s["eleves_payants"] = b.loc[b["eleve"] != "", "eleve"].nunique()
    return pd.DataFrame([s])


def _ratio(a, b):
    return (a / b * 100) if b else None


def _indicateurs_depuis(s, inds):
    """Une ligne agregee (dict de mesures) -> valeurs des indicateurs."""
    enc, dec = s.get("enc", 0.0), s.get("dec", 0.0)
    v = {
        "encaissements": enc, "decaissements": dec, "flux_net": enc - dec,
        "frais_scolarite": s.get("scol", 0.0), "autres_encaissements": enc - s.get("scol", 0.0),
        "charges": s.get("chg", 0.0), "masse_salariale": s.get("ms", 0.0),
        "produits": s.get("prd", 0.0), "resultat": s.get("prd", 0.0) - s.get("chg", 0.0),
        "marge_resultat_pct": _ratio(s.get("prd", 0.0) - s.get("chg", 0.0), s.get("prd", 0.0)),
        "charges_fixes": s.get("cf", 0.0), "en_attente_471": s.get("att", 0.0),
        "marge_pct": _ratio(enc - dec, enc),
        "part_masse_salariale_pct": _ratio(s.get("ms", 0.0), s.get("chg", 0.0)),
        "part_charges_fixes_pct": _ratio(s.get("cf", 0.0), s.get("chg", 0.0)),
        "eleves_payants": s.get("eleves_payants", 0), "nb_pieces": s.get("nb_pieces", 0),
        "encaissement_par_eleve": (s.get("scol", 0.0) / s["eleves_payants"])
        if s.get("eleves_payants") else None,
    }
    return {i: v.get(i) for i in inds if i != "part_pct"}


def _libelle_dim(dim, valeur, R):
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)) or valeur == "":
        return "(non renseigné)"
    if dim == "centre":
        return R.nom_centre(valeur)
    if dim == "mois":
        return mois_lisible(valeur)
    if dim == "semaine":
        return "semaine du " + date_courte(date.fromisoformat(valeur))
    if dim == "jour":
        return date_courte(date.fromisoformat(valeur))
    if dim == "categorie":
        return R.libelle_categorie(valeur)
    if dim == "compte":
        return f"{valeur} {R.intitule_compte(valeur)}"
    if dim == "tiers":
        return R.nom_tiers(valeur)
    if dim == "journal":
        jx = R.journaux()
        v = jx.loc[jx["journal"] == valeur, "intitule"]
        return {"CP": "Caisse principale", "CMD": "Petite caisse"}.get(
            str(valeur), "Banque" if not dl.est_caisse_physique(R.ref, valeur) else
            (str(v.iloc[0]) if len(v) else str(valeur)))
    if dim == "statut":
        return LIBELLES_STATUT.get(valeur, valeur)
    return str(valeur)


def _completer(table, dims, codes, per):
    """Ajoute les lignes a zero (centre sans activite, mois sans ecriture) :
    un classement ou une courbe ne doit pas faire disparaitre un centre."""
    if len(dims) != 1 or dims[0] not in ("centre", "mois"):
        return table
    dim = dims[0]
    attendus = codes if dim == "centre" else per.mois()
    manquants = [x for x in attendus if x not in set(table[dim])] if len(table) else attendus
    if not manquants:
        return table
    ajout = pd.DataFrame({dim: manquants})
    for m in _MESURES + ["nb_pieces", "eleves_payants"]:
        ajout[m] = 0
    return pd.concat([table, ajout], ignore_index=True)


# =============================================================================
# ANALYSER
# =============================================================================

@dataclass
class _Demande:
    inds: list
    dims: list
    per: Periode
    codes: list
    interpretation: list
    cats: Optional[list] = None
    compte: Optional[str] = None
    tiers: Optional[list] = None
    journaux: Optional[list] = None
    statut: str = "tous"


def _preparer(ctx, indicateurs, periode, du, au, centres, regrouper_par, categorie, compte, tiers,
              journal, statut, defaut_periode="dernier_mois"):
    R = ctx.R
    inds = resoudre_indicateurs(indicateurs)
    if inds == ["part_pct"]:
        inds = ["encaissements", "part_pct"]
    dims = resoudre_dimensions(regrouper_par)
    if not (periode or du or au) and defaut_periode == "dernier_mois":
        per = periode_par_defaut(ctx)
    else:
        per = resoudre_periode(periode, du, au, ctx.aujourd_hui, defaut=defaut_periode)
    codes, note_c = resoudre_centres(centres, R, ctx.portee)
    interp = [x for x in (note_c, per.interpretation) if x]
    dem = _Demande(inds=inds, dims=dims, per=per, codes=codes, interpretation=interp)
    if categorie:
        dem.cats = resoudre_categories(categorie, R)
        interp.append("categorie : " + ", ".join(R.libelle_categorie(c) for c in dem.cats))
    if compte:
        dem.compte = resoudre_compte(compte, R)
    if tiers:
        dem.tiers, note_t = resoudre_tiers(tiers, R)
        if note_t:
            interp.append(note_t)
    if journal:
        dem.journaux = resoudre_journaux(journal, R)
    st = normaliser(statut or "tous")
    dem.statut = "valide" if st.startswith("valid") else ("non_valide" if st.startswith("non") else "tous")
    sources = _sources(inds)
    return dem


def _calculer(ctx, dem, per=None):
    """Tableau agrege + informations de perimetre pour une demande."""
    R = ctx.R
    per = per or dem.per
    d = sem.lire_lignes(per.du, per.au, dem.codes)
    sources = _sources(dem.inds)
    regime = sem.fournisseurs_en_regime_facture(R) if "charges" in sources else set()
    d_etendu = None
    if sources & {"charges", "produits"}:
        # Six mois de part et d'autre : avances payees avant le mois de cours,
        # vacations et loyers regles apres.
        d_etendu = sem.lire_lignes(per.du - timedelta(days=186), per.au + timedelta(days=186), dem.codes)
    b = _base(d, R, sources, regime, d_etendu, per)
    if dem.cats:
        b = b[b["categorie"].isin(dem.cats)]
    if dem.compte:
        b = b[b["compte"].astype(str).str.startswith(dem.compte)]
    if dem.tiers:
        b = b[b["code_tiers"].isin(dem.tiers)]
    if dem.journaux:
        b = b[b["journal"].isin(dem.journaux)]
    non_valide = b[~b["statut"].isin(sem.STATUTS_VALIDES)]
    if dem.statut == "valide":
        b = b[b["statut"].isin(sem.STATUTS_VALIDES)]
    elif dem.statut == "non_valide":
        b = non_valide
    table = _agreger(b, dem.dims)
    table = _completer(table, dem.dims, dem.codes, per)
    total = _agreger(b, []).iloc[0].to_dict() if len(b) else {m: 0 for m in _MESURES + ["nb_pieces", "eleves_payants"]}
    mesure = MESURE_DE.get(dem.inds[0]) or MESURE_DE.get((DEPENDANCES.get(dem.inds[0]) or ["encaissements"])[0], "enc")
    nv = non_valide[non_valide[mesure] != 0] if len(non_valide) else non_valide
    info = {
        "nb_lignes_source": len(d) if d_etendu is None else max(len(d), len(b)),
        "centres_actifs": set(d["centre"]) if len(d) else set(),
        "non_valide": {"nb_pieces": int(nv["id_piece"].nunique()) if len(nv) else 0,
                       "montant": float(nv[mesure].sum()) if len(nv) else 0.0},
        "non_ventile": float(b.loc[b["categorie"] == "non_ventile", ["chg", "dec"]].sum().max())
        if len(b) else 0.0,
    }
    return table, total, info


def _avertissements(ctx, dem, per, info):
    av = []
    if info["nb_lignes_source"] == 0:
        debut, fin = sem.plage_donnees()
        if debut:
            av.append(f"Rien n'est enregistré sur cette période. Les données vont du "
                      f"{date_courte(debut)} au {date_courte(fin)}.")
        else:
            av.append("Aucune opération enregistrée pour l'instant.")
        return av
    if per.en_cours:
        av.append(f"Période en cours : chiffres au {date_courte(ctx.aujourd_hui)}.")
    fin_donnees = sem.plage_donnees()[1]
    if fin_donnees and per.au > fin_donnees:
        av.append(f"Dernière opération enregistrée le {date_courte(fin_donnees)}.")
    muets = [c for c in dem.codes if c not in info.get("centres_actifs", set())]
    if muets and len(dem.codes) > 1:
        av.append("Rien d'enregistré sur la période pour : "
                  + ", ".join(ctx.R.nom_centre(c) for c in muets) + ".")
    nv = info["non_valide"]
    if nv["nb_pieces"] and dem.statut == "tous":
        av.append(f"Dont {nv['nb_pieces']} opération(s) pas encore validée(s) par le comptable "
                  f"({montant(nv['montant'])}).")
    if info["non_ventile"] > 0 and any(INDICATEURS[i]["source"] == "charges" or i == "decaissements" or
                                       i in ("part_masse_salariale_pct", "part_charges_fixes_pct")
                                       for i in dem.inds):
        av.append(f"Dont {montant(info['non_ventile'])} de dépenses sans type (le comptable doit "
                  f"préciser à quoi elles correspondent).")
    if any(i in dem.inds for i in ("resultat", "marge_resultat_pct")) and "centre" in dem.dims:
        av.append("Les dépenses payées par le siège pour tous les centres ne sont pas réparties : "
                  "le bénéfice de chaque centre est calculé avant frais du siège.")
    if "eleves_payants" in dem.inds or "encaissement_par_eleve" in dem.inds:
        av.append("Seuls les élèves qui ont payé sont comptés : ce n'est pas le nombre d'inscrits.")
    return av


def _mettre_en_forme(ctx, dem, table, total):
    """Ajoute les libelles, calcule les indicateurs, trie. -> (DataFrame, colonnes, totaux)."""
    R = ctx.R
    lignes = []
    for _, row in table.iterrows():
        v = _indicateurs_depuis(row.to_dict(), dem.inds)
        l = {}
        for dim in dem.dims:
            l[f"_{dim}"] = row[dim]
            l[dim] = _libelle_dim(dim, row[dim], R)
        l.update(v)
        lignes.append(l)
    df = pd.DataFrame(lignes)
    tot = _indicateurs_depuis(total, dem.inds)
    if "part_pct" in dem.inds:
        base = next(i for i in dem.inds if i != "part_pct")
        t = tot.get(base) or 0
        df["part_pct"] = [(x / t * 100) if t and x is not None else None for x in df[base]] if len(df) else []
        tot["part_pct"] = 100.0 if t else None
    # Lignes entierement nulles (ex. comptes de charge quand on regroupe les
    # encaissements par contrepartie) : du bruit, sauf pour les centres et les
    # mois, completes expres pour qu'un centre sans activite reste visible.
    if len(df) and dem.dims and dem.dims[0] not in ("centre", "mois"):
        vals = [i for i in dem.inds if i != "part_pct"]
        garde = df[vals].apply(lambda r: any(v not in (0, None) and not pd.isna(v) for v in r), axis=1)
        df = df[garde]
    if len(df) and dem.dims:
        temps = [x for x in dem.dims if x in DIMENSIONS_TEMPS]
        if temps:
            df = df.sort_values([f"_{x}" for x in dem.dims]).reset_index(drop=True)
        else:
            cle = next((i for i in dem.inds if i != "part_pct"), dem.inds[0])
            df = df.sort_values(cle, ascending=False, na_position="last").reset_index(drop=True)
    colonnes = [(d_, DIMENSIONS[d_], "") for d_ in dem.dims]
    for i in dem.inds:
        colonnes.append((i, INDICATEURS[i]["libelle"], INDICATEURS[i]["unite"]))
    return df, colonnes, tot


def _payload(res, dem_interp, avertissements, donnees, limite=None):
    """Ce que le modele recoit : court, chiffre, deja interprete."""
    limite = limite or config.LIGNES_MODELE
    t = res.table
    unites = {c: u for c, _, u in res.colonnes}
    lignes = []
    for _, row in t.head(limite).iterrows():
        l = {}
        for c, _, u in res.colonnes:
            v = row.get(c)
            l[c] = _valeur_modele(v, u) if u in ("F", "%", "") and not isinstance(v, str) else v
        lignes.append(l)
    p = {
        "id_resultat": res.id,
        "perimetre": res.perimetre,
        "donnees_disponibles": donnees,
    }
    if dem_interp:
        p["interpretation"] = dem_interp
    if lignes and (len(res.colonnes) > 1 and any(u == "" and c in DIMENSIONS for c, _, u in res.colonnes)):
        p["lignes"] = lignes
        if len(t) > limite:
            p["lignes_affichees"] = f"{limite} sur {len(t)} (tableau complet a l'ecran)"
    if res.total:
        p["total"] = {k: _valeur_modele(v, unites.get(k, "F")) for k, v in res.total.items()}
    if avertissements:
        p["avertissements"] = avertissements
    if res.graphique_suggere:
        p["graphique_suggere"] = res.graphique_suggere
    return p


def analyser(ctx, indicateurs=None, periode=None, du=None, au=None, centres=None,
             regrouper_par=None, categorie=None, compte=None, tiers=None, journal=None,
             statut="tous", limite=None):
    dem = _preparer(ctx, indicateurs, periode, du, au, centres, regrouper_par, categorie, compte,
                    tiers, journal, statut)
    R = ctx.R
    table, total, info = _calculer(ctx, dem)
    df, colonnes, tot = _mettre_en_forme(ctx, dem, table, total)
    donnees = info["nb_lignes_source"] > 0
    av = _avertissements(ctx, dem, dem.per, info)
    temporel = any(x in DIMENSIONS_TEMPS for x in dem.dims)
    suggere = None
    if donnees and dem.dims:
        if temporel and len(df) >= 3:
            suggere = "courbe"
        elif not temporel and 2 <= len(df) <= 15:
            suggere = "barres"
    perimetre = {"periode": dem.per.libelle, "du": dem.per.du.isoformat(), "au": dem.per.au.isoformat(),
                 "centres": _libelle_centres(dem.codes, R),
                 "statut": {"tous": "toutes les opérations", "valide": "opérations validées seulement",
                            "non_valide": "opérations non validées seulement"}[dem.statut]}
    titre = " · ".join([", ".join(INDICATEURS[i]["libelle"] for i in dem.inds),
                        perimetre["centres"].capitalize() if perimetre["centres"] else "",
                        dem.per.libelle])
    res = Resultat(id=ctx.nouvel_id(), type="analyse", titre=titre, table=df, colonnes=colonnes,
                   cle_x=dem.dims[0] if dem.dims else None,
                   cle_serie=dem.dims[1] if len(dem.dims) > 1 else None,
                   valeurs=[i for i in dem.inds], total=tot, perimetre=perimetre,
                   temporel=temporel, graphique_suggere=suggere)
    ctx.garder(res)
    return res, _payload(res, dem.interpretation, av, donnees, limite)


# =============================================================================
# COMPARER
# =============================================================================

def _periode_reference(per, reference, auj):
    ref = normaliser(reference or "periode precedente")
    if ref in ("annee precedente", "l annee precedente", "annee derniere", "l an dernier",
               "an dernier", "meme periode l an dernier", "meme periode annee precedente", "n 1"):
        du = _moins_un_an(per.du)
        au = _moins_un_an(per.au)
        return Periode(du=du, au=au, libelle=libelle_periode(du, au, auj))
    if ref in ("periode precedente", "precedente", "mois precedent", "le mois precedent",
               "mois dernier", "avant", ""):
        mois_entiers = per.du.day == 1 and (per.au.day == calendar.monthrange(per.au.year, per.au.month)[1]
                                            or per.en_cours)
        if mois_entiers:
            n = len(per.mois())
            m0 = pd.Period(per.du.strftime("%Y-%m"), freq="M") - n
            du = m0.start_time.date()
            if per.en_cours and n == 1:
                # "ce mois-ci" (en cours) compare au meme nombre de jours du mois precedent
                fin_m = (m0 + (n - 1)).end_time.date()
                au = min(date(du.year, du.month, min(per.au.day, fin_m.day)), fin_m)
            else:
                au = (m0 + (n - 1)).end_time.date()
            return Periode(du=du, au=au, libelle=libelle_periode(du, au, auj))
        duree = (per.au - per.du).days + 1
        au = per.du - timedelta(days=1)
        du = au - timedelta(days=duree - 1)
        return Periode(du=du, au=au, libelle=libelle_periode(du, au, auj))
    return resoudre_periode(reference, auj=auj)


def _moins_un_an(d):
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def comparer(ctx, indicateurs=None, periode=None, du=None, au=None, reference=None,
             centres=None, regrouper_par=None, categorie=None, statut="tous"):
    dem = _preparer(ctx, indicateurs, periode, du, au, centres, regrouper_par, categorie, None,
                    None, None, statut)
    if any(x in DIMENSIONS_TEMPS for x in dem.dims):
        raise Incomprehension("regroupement_incompatible",
                              "Une comparaison de deux periodes ne se regroupe pas par mois : "
                              "utiliser analyser avec regrouper_par='mois' pour une evolution.")
    R = ctx.R
    per_b = _periode_reference(dem.per, reference, ctx.aujourd_hui)
    ta, tota, ia = _calculer(ctx, dem)
    tb, totb, ib = _calculer(ctx, dem, per=per_b)
    dfa, colonnes, ta_tot = _mettre_en_forme(ctx, dem, ta, tota)
    dfb, _, tb_tot = _mettre_en_forme(ctx, dem, tb, totb)
    inds = [i for i in dem.inds if i != "part_pct"]
    cles = [f"_{x}" for x in dem.dims]
    if dem.dims:
        fusion = dfa.merge(dfb[cles + inds], on=cles, how="outer", suffixes=("", "_ref"))
        for x in dem.dims:
            fusion[x] = [_libelle_dim(x, k, R) for k in fusion[f"_{x}"]]
    else:
        fusion = pd.DataFrame([{**{i: ta_tot.get(i) for i in inds},
                                **{f"{i}_ref": tb_tot.get(i) for i in inds}}])
    cols = [(x, DIMENSIONS[x], "") for x in dem.dims]
    total = {}
    for i in inds:
        u = INDICATEURS[i]["unite"]
        fusion[i] = fusion[i].astype(float) if i in fusion else 0.0
        fusion[f"{i}_ref"] = fusion[f"{i}_ref"].astype(float)
        fusion[f"{i}_ecart"] = fusion[i].fillna(0) - fusion[f"{i}_ref"].fillna(0)
        if u == "%":
            fusion[f"{i}_ecart_pct"] = None
        else:
            fusion[f"{i}_ecart_pct"] = [(e / r * 100) if r else None
                                        for e, r in zip(fusion[f"{i}_ecart"], fusion[f"{i}_ref"])]
        lib = INDICATEURS[i]["libelle"]
        cols += [(i, f"{lib} - {dem.per.libelle}", u), (f"{i}_ref", f"{lib} - {per_b.libelle}", u),
                 (f"{i}_ecart", "Écart" + (" (points)" if u == "%" else ""), u)]
        if u != "%":
            cols.append((f"{i}_ecart_pct", "Écart en %", "%"))
        a, b_ = ta_tot.get(i), tb_tot.get(i)
        total[i] = a
        total[f"{i}_ref"] = b_
        if a is not None and b_ is not None:
            total[f"{i}_ecart"] = a - b_
            if u != "%":
                total[f"{i}_ecart_pct"] = ((a - b_) / b_ * 100) if b_ else None
    if dem.dims:
        fusion = fusion.sort_values(inds[0], ascending=False, na_position="last").reset_index(drop=True)
    perimetre = {"periode": dem.per.libelle, "periode_reference": per_b.libelle,
                 "centres": _libelle_centres(dem.codes, R)}
    av = _avertissements(ctx, dem, dem.per, ia)
    if ib["nb_lignes_source"] == 0:
        av.append(f"Rien d'enregistré en {per_b.libelle} : comparaison "
                  f"impossible.")
    titre = f"{', '.join(INDICATEURS[i]['libelle'] for i in inds)} · {perimetre['centres'].capitalize()} · " \
            f"{dem.per.libelle} vs {per_b.libelle}"
    res = Resultat(id=ctx.nouvel_id(), type="comparaison", titre=titre, table=fusion, colonnes=cols,
                   cle_x=dem.dims[0] if dem.dims else None, valeurs=inds, total=total,
                   perimetre=perimetre, graphique_suggere="barres_groupees")
    res.libelles_periodes = (dem.per.libelle, per_b.libelle)
    ctx.garder(res)
    return res, _payload(res, dem.interpretation, av, ia["nb_lignes_source"] > 0)


# =============================================================================
# SOLDES
# =============================================================================

def soldes(ctx, date_arret=None, centres=None, journal=None, seuil=None):
    R = ctx.R
    ref = R.ref
    auj = ctx.aujourd_hui
    if date_arret:
        per = resoudre_periode(date_arret, auj=auj)
        arret = per.au
    else:
        arret = auj
    codes, note = resoudre_centres(centres, R, ctx.portee)
    journaux = resoudre_journaux(journal, R) if journal else resoudre_journaux("tout", R)
    d = sem.lire_lignes(au=arret)
    lignes = []
    banque_masquee = False
    for j in journaux:
        if dl.est_caisse_physique(ref, j):
            for c in codes:
                lignes.append({"_centre": c, "centre": R.nom_centre(c), "journal": _libelle_dim("journal", j, R),
                               "_journal": j, "solde": float(dl.solde_caisse(j, ref, d, centre=c))})
        else:
            if ctx.restreint:
                banque_masquee = True
                continue
            lignes.append({"_centre": "", "centre": "Tous les centres",
                           "journal": _libelle_dim("journal", j, R), "_journal": j,
                           "solde": float(dl.solde_caisse(j, ref, d, centre=None))})
    df = pd.DataFrame(lignes)
    caisses = df[df["_centre"] != ""]["solde"].sum() if len(df) else 0.0
    banque = df[df["_centre"] == ""]["solde"].sum() if len(df) else 0.0
    total = {"caisses": caisses}
    if (df["_centre"] == "").any() if len(df) else False:
        total["banque"] = banque
    colonnes = [("centre", "Centre", ""), ("journal", "Caisse", ""), ("solde", "Solde", "F")]
    av = []
    if seuil is not None:
        s = float(seuil)
        df["sous_le_seuil"] = df["solde"] < s
        colonnes.append(("sous_le_seuil", f"Sous {montant(s)}", "bool"))
        sous = df[df["sous_le_seuil"]]
        av.append(f"{len(sous)} caisse(s) sous {montant(s)}." if len(sous) else f"Aucune caisse sous {montant(s)}.")
    negatifs = df[df["solde"] < 0] if len(df) else df
    for _, r in negatifs.iterrows():
        av.append(f"Solde négatif : {r['journal']} de {r['centre']} ({montant(r['solde'])}). "
                  f"Une opération manque ou est mal saisie.")
    if banque_masquee:
        av.append("Le solde de la banque (commune à tous les centres) n'est pas visible depuis "
                  "ce compte.")
    perimetre = {"date": date_courte(arret), "centres": _libelle_centres(codes, R),
                 "note": "La banque est commune à tous les centres : son solde est donné à part."}
    res = Resultat(id=ctx.nouvel_id(), type="soldes",
                   titre=f"Argent disponible au {date_courte(arret)}",
                   table=df, colonnes=colonnes, cle_x="centre", cle_serie="journal",
                   valeurs=["solde"], total=total, perimetre=perimetre,
                   graphique_suggere="barres" if len(df) >= 2 else None)
    ctx.garder(res)
    p = {"id_resultat": res.id, "perimetre": perimetre,
         "lignes": [{"centre": r["centre"], "caisse": r["journal"], "solde": int(round(r["solde"])),
                     **({"sous_le_seuil": bool(r["sous_le_seuil"])} if seuil is not None else {})}
                    for _, r in df.iterrows()],
         "total": {k: int(round(v)) for k, v in total.items()}}
    if note:
        p["interpretation"] = [note]
    if av:
        p["avertissements"] = av
    return res, p


# =============================================================================
# LISTER DES ECRITURES
# =============================================================================

def lister_ecritures(ctx, periode=None, du=None, au=None, centres=None, compte=None, tiers=None,
                     journal=None, texte=None, montant_min=None, statut="tous", limite=None,
                     sens=None, vue="mouvements"):
    """Liste d'operations. vue='mouvements' (defaut) : une ligne par entree ou
    sortie d'argent, lisible par tous (date, centre, caisse, libelle, recu,
    paye), les plus recentes d'abord. vue='detail' : les lignes comptables."""
    R = ctx.R
    per = resoudre_periode(periode, du, au, ctx.aujourd_hui, defaut="annee_scolaire")
    codes, note_c = resoudre_centres(centres, R, ctx.portee)
    interp = [x for x in (note_c, per.interpretation) if x]
    d = sem.lire_lignes(per.du, per.au, codes)
    pieces = set(d["id_piece"])
    if compte:
        cp = resoudre_compte(compte, R)
        pieces &= set(d.loc[d["compte"].astype(str).str.startswith(cp), "id_piece"])
    if tiers:
        codes_t, note_t = resoudre_tiers(tiers, R)
        if note_t:
            interp.append(note_t)
        pieces &= set(d.loc[d["code_tiers"].isin(codes_t), "id_piece"])
    if texte:
        n = normaliser(texte)
        pieces &= set(d.loc[[n in normaliser(l) for l in d["libelle"]], "id_piece"]) if len(d) else set()
    st = normaliser(statut or "tous")
    if st.startswith("valid"):
        d = d[d["statut"].isin(sem.STATUTS_VALIDES)]
    elif st.startswith("non"):
        d = d[~d["statut"].isin(sem.STATUTS_VALIDES)]
    d = d[d["id_piece"].isin(pieces)]
    if journal:
        js = resoudre_journaux(journal, R)
    else:
        js = None
    detail = normaliser(vue or "").startswith("detail")
    sens_n = normaliser(sens or "")
    if detail:
        if js:
            d = d[d["journal"].isin(js)]
        if montant_min:
            d = d[(d["debit"] >= float(montant_min)) | (d["credit"] >= float(montant_min))]
        d = d.sort_values(["date_piece", "id_piece"], ascending=False)
        df = pd.DataFrame({
            "date": [date_courte(date.fromisoformat(x[:10])) for x in d["date_piece"]],
            "centre": [R.nom_centre(c) for c in d["centre"]],
            "compte": [f"{c} {R.intitule_compte(c)}" for c in d["compte"]],
            "tiers": [R.nom_tiers(t) for t in d["code_tiers"]],
            "libelle": d["libelle"].values,
            "debit": d["debit"].values, "credit": d["credit"].values,
            "statut": [LIBELLES_STATUT.get(x, x) for x in d["statut"]],
        })
        colonnes = [("date", "Date", ""), ("centre", "Centre", ""), ("compte", "Compte", ""),
                    ("tiers", "Élève / fournisseur", ""), ("libelle", "Libellé", ""),
                    ("debit", "Débit", "F"), ("credit", "Crédit", "F"), ("statut", "Statut", "")]
        total = {"debit": float(d["debit"].sum()), "credit": float(d["credit"].sum())}
        nb_ops = int(d["id_piece"].nunique())
    else:
        caisses = an._comptes_caisse(R.ref)
        m = d[d["compte"].isin(caisses) & ((d["debit"] != 0) | (d["credit"] != 0))]
        if js:
            m = m[m["journal"].isin(js)]
        types = dict(zip(*[sem.faits_flux(d, R)[c] for c in ("id_piece", "categorie")])) if len(d) else {}
        m = m.assign(recu=m["debit"].astype(float), paye=m["credit"].astype(float))
        if sens_n.startswith("rec") or sens_n.startswith("entr") or sens_n.startswith("encais"):
            m = m[m["recu"] > 0]
        elif sens_n.startswith("pay") or sens_n.startswith("sort") or sens_n.startswith("dep") \
                or sens_n.startswith("decais"):
            m = m[m["paye"] > 0]
        if montant_min:
            m = m[(m["recu"] >= float(montant_min)) | (m["paye"] >= float(montant_min))]
        if montant_min:
            m = m.assign(_tri=m[["recu", "paye"]].max(axis=1)).sort_values("_tri", ascending=False)
        else:
            m = m.sort_values(["date_piece", "id_piece"], ascending=False)
        df = pd.DataFrame({
            "date": [date_courte(date.fromisoformat(x[:10])) for x in m["date_piece"]],
            "centre": [R.nom_centre(c) for c in m["centre"]],
            "caisse": [_libelle_dim("journal", j, R) for j in m["journal"]],
            "type": [R.libelle_categorie(types[p]) if p in types else "Argent déplacé entre caisses"
                     for p in m["id_piece"]],
            "libelle": m["libelle"].values,
            "recu": m["recu"].values, "paye": m["paye"].values,
        })
        colonnes = [("date", "Date", ""), ("centre", "Centre", ""), ("caisse", "Caisse", ""),
                    ("type", "Type", ""), ("libelle", "Libellé", ""), ("recu", "Reçu", "F"),
                    ("paye", "Payé", "F")]
        reels = df["type"] != "Argent déplacé entre caisses"
        total = {"recu": float(df.loc[reels, "recu"].sum()), "paye": float(df.loc[reels, "paye"].sum())}
        if (~reels).any():
            total["deplace_entre_caisses"] = float(df.loc[~reels, "paye"].sum())
        nb_ops = int(m["id_piece"].nunique())
    perimetre = {"periode": per.libelle, "centres": _libelle_centres(codes, R), "nb_operations": nb_ops}
    res = Resultat(id=ctx.nouvel_id(), type="liste",
                   titre=f"Opérations · {perimetre['centres'].capitalize()} · {per.libelle}",
                   table=df, colonnes=colonnes, total=total, perimetre=perimetre)
    ctx.garder(res)
    limite = int(limite or 25)
    lignes = []
    for r in df.head(limite).to_dict("records"):
        lignes.append({k: (int(round(v)) if isinstance(v, float) else v) for k, v in r.items()})
    p = {"id_resultat": res.id, "perimetre": perimetre, "lignes": lignes,
         "total": {k: int(round(v)) for k, v in total.items()},
         "donnees_disponibles": len(df) > 0}
    if len(df) > limite:
        p["lignes_affichees"] = f"{limite} sur {len(df)} (liste complète à l'écran)"
    if interp:
        p["interpretation"] = interp
    return res, p


# =============================================================================
# CONTROLES
# =============================================================================

TYPES_CONTROLE = {
    "doublons": "Paiements en double possibles",
    "dates_douteuses": "Opérations avec une date erronée",
    "a_corriger": "Opérations renvoyées pour correction",
    "non_validees": "Opérations en attente de validation",
    "compte_attente": "Opérations à classer",
    "transferts_centres": "Argent envoyé entre centres",
    "non_ventile": "Dépenses sans type",
    "depenses_inhabituelles": "Dépenses inhabituelles",
    "imputations_411": "Paiements mal classés dans le compte des élèves",
    "desequilibrees": "Opérations déséquilibrées",
    "caisses_negatives": "Caisses au solde négatif",
    "envois_siao": "Envois au SIAO par centre",
}
_SYN_CONTROLE = {
    "doublon": "doublons", "suspects": "doublons", "paiements suspects": "doublons",
    "mal datees": "dates_douteuses", "dates": "dates_douteuses", "date": "dates_douteuses",
    "corriger": "a_corriger", "a corriger": "a_corriger", "rejetees": "a_corriger",
    "non validees": "non_validees", "en attente": "non_validees", "validation": "non_validees",
    "471": "compte_attente", "attente": "compte_attente", "reclassement": "compte_attente",
    "transferts": "transferts_centres", "transfert": "transferts_centres", "remises": "transferts_centres",
    "contributions": "envois_siao", "siao": "envois_siao",
    "non ventilees": "non_ventile", "non rattachees": "non_ventile",
    "anomalies": "depenses_inhabituelles", "inhabituelles": "depenses_inhabituelles",
    "anormales": "depenses_inhabituelles", "depenses anormales": "depenses_inhabituelles",
    "411": "imputations_411", "imputations": "imputations_411", "compte eleves": "imputations_411",
    "erreurs d imputation": "imputations_411", "mal classes": "imputations_411",
    "desequilibre": "desequilibrees", "desequilibrees": "desequilibrees", "equilibre": "desequilibrees",
    "negatif": "caisses_negatives", "caisse negative": "caisses_negatives",
    "envoi": "envois_siao", "envois": "envois_siao", "part au siao": "envois_siao",
    "versement siao": "envois_siao",
}


def _type_controle(t):
    n = normaliser(t).replace(" ", "_")
    if n in TYPES_CONTROLE:
        return n
    n2 = normaliser(t)
    if n2 in _SYN_CONTROLE:
        return _SYN_CONTROLE[n2]
    for k, v in _SYN_CONTROLE.items():
        if k in n2:
            return v
    raise Incomprehension("controle_inconnu", f"Controle non reconnu : « {t} ».", list(TYPES_CONTROLE))


def controles(ctx, type_controle, periode=None, du=None, au=None, centres=None):
    R = ctx.R
    ref = R.ref
    t = _type_controle(type_controle)
    codes, note_c = resoudre_centres(centres, R, ctx.portee)
    auj = ctx.aujourd_hui
    # Sans periode : tout l'historique pour les listes de travail en attente,
    # le dernier mois complet pour les controles qui comparent des montants.
    if periode or du or au:
        per = resoudre_periode(periode, du, au, auj)
    elif t in ("doublons", "depenses_inhabituelles"):
        per = periode_par_defaut(ctx)
    elif t == "non_ventile":
        per = resoudre_periode(None, auj=auj)
    else:
        per = None
    interp = [x for x in (note_c, per.interpretation if per else None) if x]
    lignes, colonnes, total, av = [], [], {}, []

    if t == "doublons":
        d = sem.lire_lignes(per.du, per.au, codes)
        for m in per.mois():
            lignes += an.paiements_suspects(m, d, ref)
        lignes = [{"date": date_courte(date.fromisoformat(str(x["date_piece"])[:10])),
                   "centre": R.nom_centre(x["centre"]), "tiers": R.nom_tiers(x["code_tiers"]),
                   "sens": x["sens"], "montant": x["montant"], "libelle": x.get("libelle", "")}
                  for x in lignes]
        colonnes = [("date", "Date", ""), ("centre", "Centre", ""), ("tiers", "Élève / fournisseur", ""),
                    ("sens", "Sens", ""), ("montant", "Montant", "F"), ("libelle", "Libellé", "")]
        for l in lignes:
            l["sens"] = "reçu" if l["sens"] == "encaissement" else "payé"
        av.append("Des paiements identiques ne sont pas forcément des doublons (plusieurs enfants "
                  "d'une même famille, par exemple) : à vérifier.")
    elif t == "dates_douteuses":
        d = sem.lire_lignes(centres=codes)
        r = an.ecritures_date_douteuse(None, None, d=d)
        lignes = [{"date": str(x["date_piece"])[:10], "centre": R.nom_centre(x["centre"]),
                   "compte": x["compte"], "libelle": x.get("libelle", ""),
                   "montant": max(float(x.get("debit", 0)), float(x.get("credit", 0)))}
                  for x in r["lignes"]]
        colonnes = [("date", "Date saisie", ""), ("centre", "Centre", ""), ("compte", "Compte", ""),
                    ("libelle", "Libellé", ""), ("montant", "Montant", "F")]
        av.append("Ces opérations ont une date impossible (année mal tapée) : elles n'apparaissent "
                  "dans aucun total mensuel tant qu'elles ne sont pas corrigées.")
        total = {"nb_pieces": r["nombre_pieces"], "montant": r["montant_total"]}
    elif t in ("a_corriger", "non_validees"):
        d = sem.lire_lignes(per.du if per else None, per.au if per else None, codes)
        statuts = {"a_corriger"} if t == "a_corriger" else {"saisie", "a_corriger"}
        d = d[d["statut"].isin(statuts)]
        g = d.groupby("id_piece").agg(date=("date_piece", "first"), centre=("centre", "first"),
                                      libelle=("libelle", "first"), montant=("debit", "sum"),
                                      statut=("statut", "first"), obs=("observation", "first")).reset_index()
        lignes = [{"date": date_courte(date.fromisoformat(r["date"][:10])), "centre": R.nom_centre(r["centre"]),
                   "libelle": r["libelle"], "montant": r["montant"],
                   "statut": LIBELLES_STATUT.get(r["statut"], r["statut"]), "observation": r["obs"]}
                  for _, r in g.sort_values("date").iterrows()]
        colonnes = [("date", "Date", ""), ("centre", "Centre", ""), ("libelle", "Libellé", ""),
                    ("montant", "Montant", "F"), ("statut", "Statut", ""), ("observation", "Motif", "")]
        total = {"nb_pieces": len(g), "montant": float(g["montant"].sum()) if len(g) else 0.0}
    elif t == "compte_attente":
        d = sem.lire_lignes(per.du if per else None, per.au if per else None, codes)
        a = sem.faits_attente(d)
        g = a.groupby("id_piece").agg(date=("date", "first"), centre=("centre", "first"),
                                      libelle=("libelle", "first"), montant=("montant", "sum")).reset_index()
        g = g[g["montant"].abs() > 0.5]
        lignes = [{"date": date_courte(r["date"]), "centre": R.nom_centre(r["centre"]),
                   "libelle": r["libelle"], "montant": r["montant"]} for _, r in g.sort_values("date").iterrows()]
        colonnes = [("date", "Date", ""), ("centre", "Centre", ""), ("libelle", "Libellé", ""),
                    ("montant", "Montant (+ reçu / - payé)", "F")]
        total = {"nb_pieces": len(g), "montant": float(g["montant"].sum()) if len(g) else 0.0}
        av.append("L'argent a bien été reçu ou payé ; seul le classement reste à faire par le "
                  "comptable. Ce n'est pas un manque d'argent.")
    elif t == "transferts_centres":
        d = sem.lire_lignes(per.du if per else None, per.au if per else None)
        mois = per.mois()[0] if per and len(per.mois()) == 1 else None
        r = an.transferts_internes(mois, ref, d)
        for panier, lib in (("anomalies", "Ne correspond pas"), ("en_transit", "Parti, pas encore reçu"),
                            ("sans_reference", "À régulariser"), ("soldes", "Reçu")):
            for x in r.get(panier, []):
                de = x.get("centre_donateur") or x.get("centre") or ""
                vers = x.get("centre_destinataire") or ""
                if ctx.restreint and not ({de, vers} & set(codes)):
                    continue
                lignes.append({"statut": lib, "de": R.nom_centre(de) if de else "",
                               "vers": R.nom_centre(vers) if vers else "",
                               "date": str(x.get("date_sortie") or x.get("date") or "")[:10],
                               "montant": float(x.get("montant_sorti") or x.get("montant") or 0),
                               "detail": x.get("motif") or x.get("libelle") or ""})
        colonnes = [("statut", "Situation", ""), ("de", "De", ""), ("vers", "Vers", ""), ("date", "Date", ""),
                    ("montant", "Montant", "F"), ("detail", "Detail", "")]
        total = dict(r.get("resume", {}))
        if not ctx.restreint:
            total["argent_en_route"] = r.get("solde_compte_585000", 0.0)
        av.append("L'argent envoyé entre centres ne change pas ce que possède Hakili. « Parti, pas "
                  "encore reçu » est normal les premiers jours.")
    elif t == "non_ventile":
        d = sem.lire_lignes(per.du, per.au, codes)
        c = sem.faits_charges(d, R, sem.fournisseurs_en_regime_facture(R))
        c = c[c["categorie"] == "non_ventile"]
        lignes = [{"date": date_courte(r["date"]), "centre": R.nom_centre(r["centre"]),
                   "tiers": R.nom_tiers(r["code_tiers"]), "libelle": r["libelle"], "montant": r["montant"]}
                  for _, r in c.sort_values("montant", ascending=False).iterrows()]
        colonnes = [("date", "Date", ""), ("centre", "Centre", ""), ("tiers", "Fournisseur", ""),
                    ("libelle", "Libellé", ""), ("montant", "Montant", "F")]
        total = {"nb_lignes": len(c), "montant": float(c["montant"].sum()) if len(c) else 0.0}
        av.append("Ces dépenses sont bien comptées dans le total, mais sans type : le comptable "
                  "doit préciser à quoi elles correspondent.")
    elif t == "imputations_411":
        d = sem.lire_lignes(per.du if per else None, per.au if per else None, codes)
        x = sem.imputations_411_a_verifier(d)
        lignes = [{"date": date_courte(date.fromisoformat(r["date_piece"][:10])),
                   "centre": R.nom_centre(r["centre"]), "libelle": r["libelle"],
                   "montant": float(r["debit"])} for _, r in x.iterrows()]
        colonnes = [("date", "Date", ""), ("centre", "Centre", ""), ("libelle", "Libellé", ""),
                    ("montant", "Montant", "F")]
        av.append("Ces paiements sont sortis de caisse mais ont été enregistrés comme des "
                  "opérations d'élèves : le comptable doit les reclasser.")
    elif t == "desequilibrees":
        d = sem.lire_lignes(per.du if per else None, per.au if per else None, codes)
        x = desequilibres(d)
        lignes = [{"date": date_courte(date.fromisoformat(r["date"][:10])), "centre": R.nom_centre(r["centre"]),
                   "libelle": r["libelle"], "ecart": r["ecart"]} for r in x]
        colonnes = [("date", "Date", ""), ("centre", "Centre", ""), ("libelle", "Libellé", ""),
                    ("ecart", "Écart débit / crédit", "F")]
        av.append("Une opération doit avoir autant au débit qu'au crédit : celles-ci sont à reprendre.")
    elif t == "caisses_negatives":
        lignes = caisses_negatives(ctx, codes)
        colonnes = [("centre", "Centre", ""), ("caisse", "Caisse", ""),
                    ("solde_actuel", "Solde actuel", "F"), ("plus_bas", "Point le plus bas", "F"),
                    ("jours_negatifs", "Jours en négatif", ""), ("premier_jour", "Premier jour négatif", "")]
        av.append("Une caisse ne peut pas descendre sous zéro : une entrée manque, une sortie est en "
                  "trop, ou le solde de départ est mal renseigné.")
    elif t == "envois_siao":
        if per is None:
            per = periode_par_defaut(ctx)
        lignes = envois_siao(ctx, per, codes)
        colonnes = [("centre", "Centre", ""), ("envoye", "Envoyé", "F"), ("nb", "Nombre d'envois", ""),
                    ("dernier", "Dernier envoi", "")]
        sans = [l["centre"] for l in lignes if not l["envoye"]]
        if sans:
            av.append("Pas d'envoi enregistré sur la période pour : " + ", ".join(sans) + ".")
    elif t == "depenses_inhabituelles":
        fin = per.au
        debut_hist = (pd.Period(fin.strftime("%Y-%m"), freq="M") - 12).start_time.date()
        d = sem.lire_lignes(debut_hist, fin, codes)
        c = sem.faits_charges(d, R, sem.fournisseurs_en_regime_facture(R))
        if len(c):
            c = c.copy()
            c["mois"] = pd.to_datetime(c["date"]).dt.strftime("%Y%m")
            mois_cible = set(per.mois())
            par = c.groupby(["centre", "categorie", "mois"])["montant"].sum().reset_index()
            for (centre, cat), g in par.groupby(["centre", "categorie"]):
                cible = g[g["mois"].isin(mois_cible)]["montant"].sum() / max(len(mois_cible), 1)
                hist = g[~g["mois"].isin(mois_cible) & (g["mois"] < min(mois_cible))]
                if len(hist) < 2:
                    continue
                moyenne = hist["montant"].mean()
                if cible > moyenne * an.SEUIL_DEPENSE_ANORMALE and cible > an.MONTANT_MIN_ANOMALIE:
                    lignes.append({"centre": R.nom_centre(centre), "categorie": R.libelle_categorie(cat),
                                   "montant": cible, "moyenne": moyenne,
                                   "ecart_pct": (cible / moyenne - 1) * 100 if moyenne else None})
        lignes.sort(key=lambda x: -x["montant"])
        colonnes = [("centre", "Centre", ""), ("categorie", "Type de dépense", ""),
                    ("montant", "Montant du mois", "F"), ("moyenne", "Moyenne habituelle", "F"),
                    ("ecart_pct", "Écart", "%")]
        av.append(f"Sont signalées les dépenses supérieures à {an.SEUIL_DEPENSE_ANORMALE:g} fois leur "
                  f"moyenne habituelle et à {montant(an.MONTANT_MIN_ANOMALIE)}.")

    df = pd.DataFrame(lignes, columns=[c for c, _, _ in colonnes]) if colonnes else pd.DataFrame(lignes)
    if "nb_pieces" not in total and "nb_lignes" not in total and "soldes" not in total:
        total["nb_elements"] = len(df)
        if "montant" in df.columns and len(df):
            total["montant"] = float(pd.to_numeric(df["montant"], errors="coerce").sum())
    perimetre = {"controle": TYPES_CONTROLE[t], "periode": per.libelle if per else "depuis le début",
                 "centres": _libelle_centres(codes, R)}
    res = Resultat(id=ctx.nouvel_id(), type="controle",
                   titre=f"{TYPES_CONTROLE[t]} · {perimetre['periode']}",
                   table=df, colonnes=colonnes, total=total, perimetre=perimetre)
    ctx.garder(res)
    limite = 25
    p = {"id_resultat": res.id, "perimetre": perimetre,
         "total": {k: (int(round(v)) if isinstance(v, (int, float)) and v is not None else v)
                   for k, v in total.items()},
         "lignes": [{k: (int(round(v)) if isinstance(v, float) and not pd.isna(v) else v)
                     for k, v in r.items()} for r in df.head(limite).to_dict("records")]}
    if len(df) > limite:
        p["lignes_affichees"] = f"{limite} sur {len(df)} (liste complete a l'ecran)"
    if interp:
        p["interpretation"] = interp
    if av:
        p["avertissements"] = av
    return res, p


# =============================================================================
# PERSONNEL
# =============================================================================

def personnel(ctx, type_demande="paiements", periode=None, du=None, au=None, centres=None, personne=None):
    R = ctx.R
    n = normaliser(type_demande or "paiements")
    if "multi" in n or "plusieurs" in n:
        t = "multi_centres"
    elif "avance" in n or "pret" in n or "acompte" in n:
        t = "avances"
    else:
        t = "paiements"
    codes, note_c = resoudre_centres(centres, R, ctx.portee)
    interp = [note_c] if note_c else []
    if t == "multi_centres" and ctx.restreint:
        raise Incomprehension("hors_portee", "Cette question croise plusieurs centres ; elle releve "
                                             "du comptable du siege.")
    codes_t = None
    if personne:
        codes_t, note_t = resoudre_tiers(personne, R)
        if note_t:
            interp.append(note_t)
    if t == "avances":
        d = sem.lire_lignes(centres=codes)
        d = d[d["compte"].astype(str).str.startswith(("4223", "2728")) & (d["code_tiers"] != "")]
        if codes_t:
            d = d[d["code_tiers"].isin(codes_t)]
        s = d.groupby("code_tiers").apply(lambda g: float(g["debit"].sum() - g["credit"].sum()),
                                          include_groups=False) if len(d) else pd.Series(dtype=float)
        s = s[s > 0.5].sort_values(ascending=False) if len(s) else s
        df = pd.DataFrame([{"personne": R.nom_tiers(c), "solde_du": v} for c, v in s.items()],
                          columns=["personne", "solde_du"])
        colonnes = [("personne", "Personne", ""), ("solde_du", "Reste à rembourser", "F")]
        per_lib = f"au {date_courte(ctx.aujourd_hui)}"
        total = {"solde_du": float(df["solde_du"].sum()) if len(df) else 0.0, "nb_personnes": len(df)}
        titre = "Avances et prêts au personnel non remboursés"
    else:
        per = resoudre_periode(periode, du, au, ctx.aujourd_hui)
        if per.interpretation:
            interp.append(per.interpretation)
        per_lib = per.libelle
        d = sem.lire_lignes(per.du, per.au, codes)
        c = sem.faits_charges(d, R, sem.fournisseurs_en_regime_facture(R))
        c = c[c["groupe"] == "masse_salariale"]
        if codes_t:
            c = c[c["code_tiers"].isin(codes_t)]
        if t == "multi_centres":
            g = c[c["code_tiers"] != ""].groupby("code_tiers")
            rows = []
            for code, grp in g:
                if grp["centre"].nunique() < 2:
                    continue
                par_c = grp.groupby("centre")["montant"].sum()
                rows.append({"personne": R.nom_tiers(code),
                             "centres": ", ".join(f"{R.nom_centre(k)} {montant(v)}" for k, v in par_c.items()),
                             "total": float(par_c.sum())})
            df = pd.DataFrame(rows, columns=["personne", "centres", "total"]).sort_values("total", ascending=False)
            colonnes = [("personne", "Personne", ""), ("centres", "Par centre", ""), ("total", "Total", "F")]
            titre = f"Enseignants payés sur plusieurs centres · {per_lib}"
        else:
            cle = c["code_tiers"].where(c["code_tiers"] != "", "(sans nom)")
            g = c.assign(cle=cle).groupby(["cle", "centre"]).agg(montant=("montant", "sum"),
                                                                  nb=("id_piece", "nunique")).reset_index()
            df = pd.DataFrame({
                "personne": [R.nom_tiers(x) if x != "(sans nom)" else x for x in g["cle"]],
                "centre": [R.nom_centre(x) for x in g["centre"]],
                "nb_paiements": g["nb"].values, "montant": g["montant"].values,
            }).sort_values("montant", ascending=False)
            colonnes = [("personne", "Personne", ""), ("centre", "Centre", ""),
                        ("nb_paiements", "Paiements", ""), ("montant", "Montant", "F")]
            titre = f"Salaires et vacations · {_libelle_centres(codes, R).capitalize()} · {per_lib}"
        total = {"montant": float(c["montant"].sum()) if len(c) else 0.0,
                 "nb_personnes": int(c["code_tiers"].replace("", pd.NA).nunique()) if len(c) else 0}
    df = df.reset_index(drop=True)
    perimetre = {"periode": per_lib, "centres": _libelle_centres(codes, R)}
    res = Resultat(id=ctx.nouvel_id(), type="liste", titre=titre, table=df, colonnes=colonnes,
                   cle_x="personne", valeurs=[c for c, _, u in colonnes if u == "F"][:1], total=total,
                   perimetre=perimetre, graphique_suggere=None)
    ctx.garder(res)
    limite = 30
    p = {"id_resultat": res.id, "perimetre": perimetre,
         "total": {k: int(round(v)) for k, v in total.items()},
         "lignes": [{k: (int(round(v)) if isinstance(v, float) else v) for k, v in r.items()}
                    for r in df.head(limite).to_dict("records")]}
    if len(df) > limite:
        p["lignes_affichees"] = f"{limite} sur {len(df)} (liste complete a l'ecran)"
    if interp:
        p["interpretation"] = interp
    return res, p


# =============================================================================
# CONTEXTE ET RECHERCHE
# =============================================================================

def contexte(ctx):
    R = ctx.R
    debut, fin = sem.plage_donnees()
    auj = ctx.aujourd_hui
    dernier_mois = (date(auj.year, auj.month, 1) - timedelta(days=1))
    centres = ctx.portee or R.centres_actifs()
    jx = R.journaux()
    treso = jx[(jx["type"].fillna("tresorerie") == "tresorerie") & (jx["actif"].fillna("oui") == "oui")]
    return {
        "aujourd_hui": auj.isoformat(),
        "donnees": {"du": debut.isoformat() if debut else None, "au": fin.isoformat() if fin else None},
        "dernier_mois_complet": dernier_mois.strftime("%Y%m"),
        "centres": [{"code": c, "nom": R.nom_centre(c)} for c in centres],
        "journaux": [{"code": j, "intitule": i} for j, i in zip(treso["journal"], treso["intitule"])],
        "categories_charge": [{"code": c.code, "libelle": c.libelle, "groupe": c.groupe}
                              for c in R.categories],
        "limites": [
            "Pas d'echeancier par eleve : impossible de chiffrer les impayes ni les retards.",
            "Pas de grille tarifaire : impossible de calculer les recettes attendues ni un seuil "
            "de rentabilite en nombre d'eleves.",
            "Pas de table d'inscriptions : l'effectif est approche par les eleves payants ; aucune "
            "prevision de recettes.",
            "Resultat de gestion = produits - charges rattaches au mois de prestation, avant "
            "amortissements, provisions et impot (le resultat officiel est arrete dans Sage).",
            "Les charges payees par le siege pour tous les centres ne sont pas reparties entre "
            "les centres.",
        ],
    }


def chercher(ctx, texte, type_recherche="tiers"):
    R = ctx.R
    t = normaliser(type_recherche or "tiers")
    if t.startswith("compte"):
        comptes = R.ref["comptes"]
        from rapidfuzz import fuzz, process
        r = process.extract(normaliser(texte), [normaliser(x) for x in comptes["intitule"]],
                            scorer=fuzz.WRatio, limit=8, score_cutoff=60)
        return {"comptes": [{"compte": str(comptes["compte"].iloc[i]),
                             "intitule": str(comptes["intitule"].iloc[i])} for _, _, i in r]}
    if t.startswith("categ"):
        return {"categories": [{"code": c.code, "libelle": c.libelle, "groupe": c.groupe}
                               for c in R.categories]}
    type_tiers = {"eleve": "client", "eleves": "client", "client": "client",
                  "fournisseur": "fournisseur", "personnel": "personnel"}.get(t)
    res = chercher_tiers(texte, R, limite=10, type_tiers=type_tiers)
    return {"tiers": [{"nom": x["nom"], "code": x["code"],
                       "type": {"client": "eleve"}.get(x["type"], x["type"]), "score": x["score"]}
                      for x in res]}


# =============================================================================
# REQUETE SQL LIBRE (lecture seule, comptable du siege)
# =============================================================================

TABLES_SQL = {"v_lignes", "centres", "comptes", "tiers", "journaux", "categories_charge",
              "centres_alias", "soldes_ouverture_centre"}
_SQL_INTERDIT = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|call|execute|prepare|"
    r"listen|notify|vacuum|comment|security|reset|lock|refresh|cluster|reindex|import)\b|"
    r"\bset\s|pg_|current_setting|set_config|dblink|\blo_|utilisateurs|journal_assistant|"
    r"suppressions_ecritures|information_schema|code_acces", re.IGNORECASE)


def verifier_sql(sql):
    """-> requete nettoyee, ou Incomprehension. Premier filet ; le second est
    la transaction READ ONLY (et, si configure, un role sans droit d'ecriture)."""
    s = (sql or "").strip().rstrip(";").strip()
    if not s:
        raise Incomprehension("sql_vide", "Requete vide.")
    if ";" in s:
        raise Incomprehension("sql_refuse", "Une seule instruction SELECT a la fois.")
    bas = re.sub(r"'[^']*'", "''", s.lower())          # les chaines ne comptent pas
    if not re.match(r"^\s*(select|with)\b", bas):
        raise Incomprehension("sql_refuse", "Seules les requetes SELECT sont autorisees.")
    if _SQL_INTERDIT.search(bas):
        raise Incomprehension("sql_refuse", "Requete refusee : instruction ou table non autorisee.")
    ctes = set(re.findall(r"\b([a-z_][a-z0-9_]*)\s+as\s*\(", bas))
    for t in re.findall(r"\b(?:from|join)\s+([a-z_][a-z0-9_\.]*)", bas):
        if t not in TABLES_SQL and t not in ctes:
            raise Incomprehension("sql_refuse", f"Table non autorisee : {t}. Tables disponibles : "
                                                f"{', '.join(sorted(TABLES_SQL))}.")
    return s


def requete_sql(ctx, sql):
    if ctx.restreint:
        raise Incomprehension("hors_portee", "Les requetes libres sont reservees au comptable du siege.")
    s = verifier_sql(sql)
    limite = config.SQL_LIGNES_MAX

    def _executer(conn):
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(f"SET LOCAL statement_timeout = {int(config.SQL_TIMEOUT_MS)}")
            cur.execute(f"SELECT * FROM ({s}) AS requete LIMIT {limite + 1}")
            noms = [c.name for c in cur.description]
            return noms, cur.fetchall()

    try:
        if config.DSN_LECTURE:
            import psycopg2
            conn = psycopg2.connect(config.DSN_LECTURE)
            try:
                noms, rows = _executer(conn)
                conn.rollback()
            finally:
                conn.close()
        else:
            with dl._connexion() as conn:
                noms, rows = _executer(conn)
    except Incomprehension:
        raise
    except Exception as e:
        raise Incomprehension("sql_erreur", f"La requete a echoue : {str(e).splitlines()[0]}")
    tronque = len(rows) > limite
    rows = rows[:limite]
    df = pd.DataFrame([[float(v) if hasattr(v, "is_finite") else v for v in r] for r in rows], columns=noms)
    colonnes = [(c, c, "") for c in noms]
    num = [c for c in noms if len(df) and pd.api.types.is_numeric_dtype(df[c])]
    texte_cols = [c for c in noms if c not in num]
    res = Resultat(id=ctx.nouvel_id(), type="sql", titre="Requete sur la base", table=df, colonnes=colonnes,
                   cle_x=texte_cols[0] if texte_cols else None, valeurs=num,
                   temporel=bool(texte_cols) and texte_cols[0] in ("mois", "jour", "date", "date_piece"),
                   perimetre={"requete": s})
    ctx.garder(res)
    p = {"id_resultat": res.id, "colonnes": noms,
         "lignes": [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()}
                    for r in df.head(config.LIGNES_MODELE).to_dict("records")],
         "nb_lignes": len(df)}
    if tronque:
        p["avertissements"] = [f"Resultat limite a {limite} lignes."]
    return res, p


# =============================================================================
# CONTROLES SUPPLEMENTAIRES, ENVOIS AU SIAO, POINTS A VERIFIER, POINT FINANCIER
# =============================================================================

def desequilibres(d):
    """Operations dont le total debit ne vaut pas le total credit."""
    if d is None or len(d) == 0:
        return []
    g = d.groupby("id_piece").agg(debit=("debit", "sum"), credit=("credit", "sum"),
                                  date=("date_piece", "first"), centre=("centre", "first"),
                                  libelle=("libelle", "first"))
    g = g[(g["debit"] - g["credit"]).abs() > 0.5]
    return [{"id_piece": i, "date": str(r["date"]), "centre": r["centre"], "libelle": r["libelle"],
             "ecart": float(r["debit"] - r["credit"])} for i, r in g.iterrows()]


def caisses_negatives(ctx, codes):
    """Caisses physiques (CP, CMD) dont le solde, jour apres jour, est passe
    sous zero : le signe d'une operation manquante ou mal saisie."""
    R = ctx.R
    ref = R.ref
    jx = R.journaux()
    physiques = [j for j in jx["journal"] if dl.est_caisse_physique(ref, j)]
    d = sem.lire_lignes(au=ctx.aujourd_hui, centres=codes)
    res = []
    for j in physiques:
        cc = jx.loc[jx["journal"] == j, "compte_contrepartie"].iloc[0]
        for c in codes:
            ouv = dl._solde_ouverture_journal(ref, j, c)
            x = d[(d["centre"] == c) & (d["compte"] == cc)]
            if len(x) == 0:
                continue
            par_jour = (x.assign(m=x["debit"] - x["credit"]).groupby("date_piece")["m"].sum()
                        .sort_index().cumsum() + ouv)
            negatifs = par_jour[par_jour < -0.5]
            actuel = float(par_jour.iloc[-1])
            if len(negatifs):
                res.append({"centre": R.nom_centre(c), "caisse": _libelle_dim("journal", j, R),
                            "solde_actuel": actuel, "plus_bas": float(par_jour.min()),
                            "jours_negatifs": int(len(negatifs)),
                            "premier_jour": date_courte(date.fromisoformat(str(negatifs.index[0])[:10]))})
    return res


CENTRE_SIAO = "SIA"


def envois_siao(ctx, per, codes):
    """Argent envoye au SIAO par chaque centre sur la periode (remises passees
    par le compte de virements 585000 dont le libelle ou le modele designe
    le SIAO / une contribution / un transfert entre centres)."""
    R = ctx.R
    d = sem.lire_lignes(per.du, per.au)
    caisses = an._comptes_caisse(R.ref)
    p585 = set(d.loc[d["compte"] == an.COMPTE_VIREMENTS_FONDS, "id_piece"])
    lib = d["libelle"].str.upper()
    vers_siao = set(d.loc[d["id_piece"].isin(p585) & (
        lib.str.contains("SIAO|CONTRIBUTION|TRANSFERT", regex=True)
        | (d.get("modele", pd.Series("", index=d.index)) == an.MODELE_TRANSFERT_INTERNE)), "id_piece"])
    sorties = d[d["id_piece"].isin(vers_siao) & d["compte"].isin(caisses) & (d["credit"] > 0)
                & (d["centre"] != CENTRE_SIAO)]
    res = []
    for c in [x for x in codes if x != CENTRE_SIAO]:
        x = sorties[sorties["centre"] == c]
        res.append({"centre": R.nom_centre(c), "envoye": float(x["credit"].sum()),
                    "nb": int(x["id_piece"].nunique()),
                    "dernier": date_courte(date.fromisoformat(max(x["date_piece"])[:10])) if len(x) else "-"})
    return res


def a_verifier(ctx, centres=None):
    """Tous les points de controle en une liste simple (seulement ceux qui ne
    sont pas a zero), avec le type de controle a demander pour le detail."""
    R = ctx.R
    codes, _ = resoudre_centres(centres, R, ctx.portee)
    d = sem.lire_lignes(centres=codes)
    points = []

    def ajouter(cle, nombre, montant_=None, texte=None):
        if nombre:
            points.append({"point": texte or TYPES_CONTROLE[cle], "nombre": int(nombre),
                           "montant": float(montant_) if montant_ is not None else None,
                           "detail": cle})

    pieces = d.groupby("id_piece").agg(statut=("statut", "first"), montant=("debit", "sum")) if len(d) else None
    if pieces is not None:
        x = pieces[pieces["statut"] == "saisie"]
        ajouter("non_validees", len(x), x["montant"].sum())
        x = pieces[pieces["statut"] == "a_corriger"]
        ajouter("a_corriger", len(x), x["montant"].sum())
    a = sem.faits_attente(d)
    if len(a):
        g = a.groupby("id_piece")["montant"].sum()
        g = g[g.abs() > 0.5]
        ajouter("compte_attente", len(g), g.sum())
    per = periode_par_defaut(ctx)
    dbl = []
    for m in {per.du.strftime("%Y%m"), (pd.Period(per.du.strftime("%Y-%m"), freq="M") - 1).strftime("%Y%m")}:
        dbl += an.paiements_suspects(m, d, R.ref)
    ajouter("doublons", len(dbl), sum(x["montant"] for x in dbl),
            "Paiements en double possibles (ce mois et le mois dernier)")
    dd = an.ecritures_date_douteuse(None, None, d=d)
    ajouter("dates_douteuses", dd["nombre_pieces"], dd["montant_total"])
    x = sem.imputations_411_a_verifier(d)
    ajouter("imputations_411", x["id_piece"].nunique() if len(x) else 0, x["debit"].sum() if len(x) else 0)
    ajouter("desequilibrees", len(desequilibres(d)))
    neg = caisses_negatives(ctx, codes)
    ajouter("caisses_negatives", len(neg), None,
            "Caisses passées sous zéro à un moment" if neg else None)
    tr = an.transferts_internes(None, R.ref, sem.lire_lignes())
    ajouter("transferts_centres", tr["resume"].get("anomalies", 0), None,
            "Envois entre centres qui ne correspondent pas")
    ajouter("transferts_centres", tr["resume"].get("sans_reference", 0), None,
            "Envois entre centres à régulariser")
    as_ = resoudre_periode("depuis la rentree", auj=ctx.aujourd_hui)
    c = sem.faits_charges(sem.lire_lignes(as_.du, as_.au, codes), R, sem.fournisseurs_en_regime_facture(R))
    c = c[c["categorie"] == "non_ventile"] if len(c) else c
    ajouter("non_ventile", len(c), c["montant"].sum() if len(c) else 0,
            "Dépenses sans type (depuis la rentrée)")
    df = pd.DataFrame(points, columns=["point", "nombre", "montant", "detail"])
    res = Resultat(id=ctx.nouvel_id(), type="controle", titre="Points à vérifier",
                   table=df, colonnes=[("point", "Point", ""), ("nombre", "Nombre", ""),
                                       ("montant", "Montant", "F")],
                   total={"nb_points": len(points)},
                   perimetre={"centres": _libelle_centres(codes, R)})
    ctx.garder(res)
    p = {"id_resultat": res.id, "points": [{k: (int(round(v)) if isinstance(v, float) else v)
                                            for k, v in pt.items()} for pt in points]}
    if not points:
        p["message"] = "Rien à signaler."
    return res, p


def point_financier(ctx, periode=None, centres=None):
    """La situation en un coup d'oeil : argent disponible, recu et depense du
    mois (et du mois precedent, et depuis la rentree), plus grosses depenses,
    situation de chaque centre, envois au SIAO, points a verifier."""
    R = ctx.R
    per = resoudre_periode(periode, auj=ctx.aujourd_hui) if periode else periode_par_defaut(ctx)
    codes, note = resoudre_centres(centres, R, ctx.portee)
    prec_d = (pd.Period(per.du.strftime("%Y-%m"), freq="M") - 1)
    per_prec = resoudre_periode(prec_d.strftime("%Y%m"), auj=ctx.aujourd_hui)
    if per.en_cours:
        # meme nombre de jours pour comparer ce qui est comparable
        fin = min(per_prec.au, per_prec.du + timedelta(days=(per.au - per.du).days))
        per_prec = Periode(du=per_prec.du, au=fin, libelle=libelle_periode(per_prec.du, fin, ctx.aujourd_hui))
    rentree = resoudre_periode("depuis la rentree", auj=ctx.aujourd_hui)
    if rentree.au < per.au or per.du < rentree.du:
        d0 = date(per.au.year if per.au.month >= 9 else per.au.year - 1, 9, 1)
        rentree = Periode(du=d0, au=per.au, libelle=libelle_periode(d0, per.au, ctx.aujourd_hui))

    def flux(p_, dims=None):
        dem = _Demande(inds=["encaissements", "decaissements", "flux_net"], dims=dims or [], per=p_,
                       codes=codes, interpretation=[])
        return _calculer(ctx, dem)

    t_mois, tot_mois, info = flux(per)
    _, tot_prec, _ = flux(per_prec)
    _, tot_as, _ = flux(rentree)
    v = lambda t: _indicateurs_depuis(t, ["encaissements", "decaissements", "flux_net"])
    m, mp, ma = v(tot_mois), v(tot_prec), v(tot_as)
    dem_types = _Demande(inds=["decaissements"], dims=["categorie"], per=per, codes=codes, interpretation=[])
    t_types, _, _ = _calculer(ctx, dem_types)
    top = sorted([(R.libelle_categorie(r["categorie"]), r["dec"]) for _, r in t_types.iterrows()
                  if r["dec"] > 0], key=lambda x: -x[1])[:3]
    _, sp = soldes(ctx, centres=centres)
    caisse_par_centre = {}
    for l in sp["lignes"]:
        if l["centre"] != "Tous les centres":
            caisse_par_centre[l["centre"]] = caisse_par_centre.get(l["centre"], 0) + l["solde"]
    dem_c = _Demande(inds=["encaissements", "decaissements"], dims=["centre"], per=per, codes=codes,
                     interpretation=[])
    t_c, _, _ = _calculer(ctx, dem_c)
    centres_l = []
    for _, r in t_c.iterrows():
        nom = R.nom_centre(r["centre"])
        centres_l.append({"centre": nom, "recu": r["enc"], "depense": r["dec"],
                          "caisse": caisse_par_centre.get(nom, 0)})
    sans_operation = [c["centre"] for c in centres_l if not c["recu"] and not c["depense"] and not c["caisse"]]
    centres_l = sorted([c for c in centres_l if c["centre"] not in sans_operation], key=lambda x: -x["recu"])
    envois = envois_siao(ctx, per, codes) if CENTRE_SIAO in R.centres_actifs() else []
    _, verif = a_verifier(ctx, centres)
    data = {
        "periode": per.libelle, "periode_precedente": per_prec.libelle, "rentree": rentree.libelle,
        "disponible": {"caisses": sp["total"].get("caisses", 0), "banque": sp["total"].get("banque"),
                       "total": sp["total"].get("caisses", 0) + (sp["total"].get("banque") or 0)},
        "mois": {"recu": m["encaissements"], "depense": m["decaissements"], "reste": m["flux_net"]},
        "mois_precedent": {"recu": mp["encaissements"], "depense": mp["decaissements"], "reste": mp["flux_net"]},
        "depuis_rentree": {"recu": ma["encaissements"], "depense": ma["decaissements"], "reste": ma["flux_net"]},
        "plus_grosses_depenses": [{"type": t, "montant": x} for t, x in top],
        "centres": centres_l,
        "centres_sans_operation": sans_operation,
        "envois_siao": [e for e in envois if e["centre"] not in sans_operation],
        "a_verifier": verif.get("points", []),
    }
    interp = [x for x in (note, per.interpretation) if x]
    res = Resultat(id=ctx.nouvel_id(), type="point", titre=f"Point financier · {per.libelle}",
                   table=pd.DataFrame(centres_l), colonnes=[("centre", "Centre", ""), ("recu", "Reçu", "F"),
                                                           ("depense", "Dépensé", "F"),
                                                           ("caisse", "En caisse", "F")],
                   cle_x="centre", valeurs=["recu", "depense"], total={}, perimetre={"periode": per.libelle},
                   graphique_suggere=None)
    res.donnees = data
    ctx.garder(res)

    def arrondir(x):
        if isinstance(x, dict):
            return {k: arrondir(v) for k, v in x.items()}
        if isinstance(x, list):
            return [arrondir(v) for v in x]
        return int(round(x)) if isinstance(x, float) else x

    p = {"id_resultat": res.id, **arrondir(data)}
    if interp:
        p["interpretation"] = interp
    if per.en_cours:
        p["note"] = (f"Mois en cours : comparé aux mêmes jours de {per_prec.libelle.split(' (')[0]}.")
    return res, p

# ---------------------------------------------------------------------------
# Instantane du referentiel utilise par l'assistant : centres (et leurs
# alias), journaux, comptes, tiers, categories de charge.
#
# Relu seulement quand la base a change (table `revision`, incrementee par
# trigger a chaque ecriture sur une table metier) : une question ne coute pas
# une relecture complete des 1 500 tiers.
# ---------------------------------------------------------------------------

import threading
from dataclasses import dataclass, field

import pandas as pd

import logic.donnees as dl

# Centre du siege : administratif, sans recettes propres. Exclu de "tous les
# centres" par defaut (il fausserait marges et classements), toujours
# interrogeable en le nommant.
CENTRE_SIEGE = "SIE"


@dataclass
class Categorie:
    code: str
    libelle: str
    groupe: str
    comptes: list
    motifs: list
    ordre: int


@dataclass
class Referentiel:
    ref: dict                       # le dict de logic.donnees.lire_referentiel()
    centres: pd.DataFrame           # code_centre, intitule, actif
    alias: dict                     # alias normalise -> code_centre
    categories: list = field(default_factory=list)

    # --- centres ---------------------------------------------------------
    def nom_centre(self, code):
        return dl.nom_centre(self.ref, code)

    def centres_actifs(self, avec_siege=False):
        c = self.centres[self.centres["actif"] == "oui"]
        codes = list(c["code_centre"])
        if not avec_siege:
            codes = [x for x in codes if x != CENTRE_SIEGE]
        return codes

    def tous_les_centres(self):
        return list(self.centres["code_centre"])

    # --- comptes / tiers / journaux ----------------------------------------
    def intitule_compte(self, compte):
        return dl.intitule_compte(self.ref, compte)

    def nom_tiers(self, code):
        if not code:
            return ""
        t = self.ref["tiers"]
        v = t.loc[t["code_tiers"] == code, "intitule"]
        return str(v.iloc[0]) if len(v) else str(code)

    def journaux(self):
        return self.ref["journaux"]

    # --- categories ----------------------------------------------------------
    def categorie(self, code):
        for c in self.categories:
            if c.code == code:
                return c
        return None

    def libelle_categorie(self, code):
        c = self.categorie(code)
        if c:
            return c.libelle
        return LIBELLES_HORS_TABLE.get(code, code)


# Categories implicites, quand un compte n'est rattache a aucune categorie de
# la table : on se replie sur la rubrique SYSCOHADA (deux premiers chiffres),
# jamais sur un fourre-tout "autres" qui ne dirait rien a la comptable.
LIBELLES_HORS_TABLE = {
    "non_ventile": "Dépenses sans type",
    "classe_60": "Achats divers",
    "classe_61": "Transports",
    "classe_62": "Services extérieurs",
    "classe_63": "Autres services extérieurs",
    "classe_64": "Impôts et taxes",
    "classe_65": "Autres dépenses",
    "classe_66": "Salaires et charges sociales",
    "classe_67": "Frais financiers",
    "classe_68": "Amortissements",
    "classe_69": "Provisions",
    # types d'entrees et de sorties d'argent (semantique.type_mouvement)
    "cours": "Frais de cours",
    "documents": "Frais de dossier et de documents",
    "autres_produits": "Autres recettes",
    "remboursement_pret_recu": "Remboursement de prêt reçu",
    "emprunt_recu": "Emprunt reçu",
    "a_classer": "Opérations à classer",
    "autres_entrees": "Autres entrées",
    "avances_personnel": "Avances et prêts au personnel",
    "remboursement_emprunt": "Remboursement d'emprunt",
    "equipement": "Équipement",
    "remboursement_parent": "Remboursements aux parents",
    "mal_classe_eleves": "Paiements mal classés (compte élèves)",
    "impots": "Impôts et taxes",
    "autres_sorties": "Autres sorties",
}

_verrou = threading.Lock()
_cache = {"revision": None, "valeur": None}


def _revision():
    try:
        with dl._connexion() as c, c.cursor() as cur:
            cur.execute("SELECT valeur FROM revision WHERE id")
            r = cur.fetchone()
        return r[0] if r else None
    except Exception:
        return None


def _lire_table(sql):
    try:
        return dl._lire_df(sql)
    except Exception:
        # Migration pas encore jouee (base de test, ancienne base) : l'assistant
        # fonctionne sans alias ni categories, en se repliant sur le plan.
        return pd.DataFrame()


def charger(forcer=False):
    """Referentiel courant, relu seulement si la base a change."""
    rev = _revision()
    with _verrou:
        if not forcer and _cache["valeur"] is not None and rev is not None and rev == _cache["revision"]:
            return _cache["valeur"]
    valeur = construire(dl.lire_referentiel(),
                        _lire_table("SELECT alias, code_centre FROM centres_alias"),
                        _lire_table("SELECT * FROM categories_charge ORDER BY ordre, categorie"))
    with _verrou:
        _cache["revision"], _cache["valeur"] = rev, valeur
    return valeur


def construire(ref, alias_df=None, categories_df=None):
    """Assemble un Referentiel a partir de tables deja lues. Separe de
    charger() pour que les tests puissent fournir leurs propres tables."""
    from assistant.texte import normaliser
    centres = ref["centres"].copy()
    if "actif" not in centres.columns:
        centres["actif"] = "oui"
    centres["actif"] = centres["actif"].fillna("oui")
    alias = {}
    if alias_df is not None and len(alias_df):
        for a, c in zip(alias_df["alias"], alias_df["code_centre"]):
            alias[normaliser(a)] = str(c)
    categories = []
    if categories_df is not None and len(categories_df):
        for _, r in categories_df.iterrows():
            categories.append(Categorie(
                code=str(r["categorie"]), libelle=str(r["libelle"]), groupe=str(r["groupe"]),
                comptes=[str(x) for x in (r["comptes"] or [])],
                motifs=[str(x).upper() for x in (r["motifs"] or [])],
                ordre=int(r["ordre"])))
    return Referentiel(ref=ref, centres=centres, alias=alias, categories=categories)

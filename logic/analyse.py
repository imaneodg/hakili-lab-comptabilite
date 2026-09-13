# ---------------------------------------------------------------------------
# Analyse financiere - fonctions deterministes
#
# Tout ce fichier repose sur logic.donnees (lire_ecritures, lire_referentiel),
# donc sur la meme base Postgres Hakili_compta que le reste de l'application.
# Aucune fonction ici ne fait appel a un modele de langage : chaque question
# posee par un directeur dans l'assistant IA correspond a une fonction
# precise ci-dessous, que le serveur MCP se contente d'appeler et de
# renvoyer telle quelle. Le LLM formule la phrase de reponse, jamais le
# calcul.
#
# Reglages a valider avec la comptable avant mise en production, marques
# ci-dessous : la liste des comptes de charges fixes n'est qu'une premiere
# approximation d'apres les modeles de saisie existants.
# ---------------------------------------------------------------------------

import pandas as pd

import logic.donnees as dl

# --- reglages ---------------------------------------------------------------

# Un centre qui approvisionne sa caisse secondaire ou verse des especes en
# banque ne "gagne" ni ne "depense" rien : c'est le meme argent qui change de
# tiroir.
#
# Corrige le 11/09/2026 : ce filtre par NOM DE MODELE ne suffit pas et ne
# suffisait deja plus. import_historique.py ecrit modele="libre" sur toutes
# les lignes reprises des brouillards Excel ; aucun approvisionnement
# historique ne portait donc le modele attendu, et les 197 virements de fonds
# des brouillards de Saaba et Tampouy comptaient a la fois comme recette du
# centre (entree dans la caisse d'arrivee) et comme depense (sortie de la
# caisse de depart) - soit 11,1 M F de recettes et 12,3 M F de depenses
# fictives sur les huit premiers mois de 2026. Le vrai critere est comptable,
# pas declaratif : voir pieces_transfert_interne() plus bas, qui reconnait un
# transfert au fait que la piece mouvemente DEUX comptes de tresorerie. Le
# filtre par modele est conserve en second filet, il ne coute rien.
MODELES_TRANSFERT_INTERNE = {"approvisionnement", "versement_banque"}

COMPTE_ATTENTE = "471000"
COMPTE_PERSONNEL = "422000"
COMPTE_FOURNISSEUR = "401000"

# Compte SYSCOHADA 585 "Virements de fonds" : compte de passage standard d'un
# transfert entre deux caisses tenues sur des journaux distincts. Utilise
# aussi bien par le modele "Approvisionnement de la CMD" de l'application que
# par les brouillards historiques (voir import_historique.py). Il est de
# nature 'tresorerie' au plan de comptes, ce qui suffit a le faire reconnaitre
# par pieces_transfert_interne() - la constante n'est la que pour la lisibilite.
COMPTE_VIREMENTS_FONDS = "585000"

# Compte de charge des etats de vacation (modele "vacation", journal ACH -
# voir logic/modeles.py:_lignes_vacation). Distinct de COMPTE_PERSONNEL :
# une vacation ne passe jamais par le collectif 422000, elle credite le
# fournisseur 401000 en contrepartie de la charge 632710. Confirme avec la
# direction (06/09/2026) : la masse salariale de Hakili Lab doit compter les
# deux, la majorite des professeurs etant payes a la vacation plutot que
# par le modele "remuneration".
COMPTE_VACATION = "632710"

# Intitules confirmes dans le plan comptable (sql/seed.sql) : 622200 est le
# loyer, 632720 le gardiennage. Les deux sont neanmoins regroupes dans
# COMPTES_CHARGES_FIXES ci-dessous (indicateur large "charges fixes",
# utilise par Q17/part_charges_fixes) - voir COMPTES_LOYER_EAU_ELECTRICITE
# pour le sous-ensemble plus precis demande par Q18 (loyer + eau +
# electricite seuls, sans le gardiennage).
COMPTES_CHARGES_FIXES = {
    "622200": "Location de batiment (loyer)",
    "632720": "Gardiennage bureau",
    "605100": "Fournitures d'eau (ONEA)",
    "605200": "Fournitures d'electricite (SONABEL / Cash Power)",
}

# Sous-ensemble de COMPTES_CHARGES_FIXES pour Q18 ("le loyer, l'electricite
# et l'eau representent quelle part des depenses ?") : le gardiennage n'en
# fait pas partie, la question ne le mentionne pas.
COMPTES_LOYER_EAU_ELECTRICITE = {
    "622200": "Location de batiment (loyer)",
    "605100": "Fournitures d'eau (ONEA)",
    "605200": "Fournitures d'electricite (SONABEL / Cash Power)",
}

# Compte des avances/acomptes au personnel (Q23). Nature 'tiers' dans le
# plan comptable : le solde se lit tiers par tiers, comme 411000 ou 401000.
COMPTE_AVANCES_PERSONNEL = "422300"

# Categories de depenses courantes demandees par Q20, mappees sur les
# comptes du plan (sql/seed.sql) les plus proches de chaque libelle. Un seul
# compte par categorie ici (pas de regroupement multi-comptes) pour rester
# simple et verifiable a l'oeil par la comptable.
CATEGORIES_DEPENSE_COURANTE = {
    "nettoyage": "624330",     # Entretien, nettoyage et enlevement des ordures
    "telecom": "628820",       # Frais d'internet (mega, fibre, Canal Box)
    "fournitures": "605500",   # Fournitures de bureau et pedagogiques
    "carburant": "605300",     # Carburant et lubrifiants
}

SEUIL_DEPENSE_ANORMALE = 1.5      # une depense est signalee au-dela de 1,5x sa moyenne
MONTANT_MIN_ANOMALIE = 20000      # F CFA - evite le bruit sur les petits comptes

# --- ventilation des reglements passes directement par le collectif 401000 ---
#
# Constate le 11/09/2026 sur les quatre brouillards reels (Saaba et Tampouy,
# janvier a aout 2026) : le loyer, les vacations et les factures ONEA ne sont
# jamais imputes a un compte de charge. Ils sont soldes directement sur le
# collectif fournisseur 401000, de nature 'tiers'. Les comptes 632710, 622200,
# 605100 et 422000 ne portent pas une seule ecriture. Resultat, avant ce
# correctif : 8,22 M F de charges reelles etaient invisibles pour toutes les
# analyses de depenses, qui n'en voyaient que 654 k F (7,4 %), et
# part_masse_salariale repondait 0 % alors que la masse salariale pese 6,1 M F.
#
# Deux facons de corriger. La bonne, a terme, est comptable : 401000 est un
# compte de DETTE, pas une imputation analytique ; un reglement doit passer par
# la charge, ou solder une dette nee d'une facture au journal ACH. Tant que la
# saisie n'a pas ete reprise avec la comptable, la table ci-dessous reconstitue
# la charge a partir du libelle normalise, de facon deterministe et
# verifiable a l'oeil. C'est une COUCHE DE LECTURE : elle ne modifie aucune
# ecriture, et tout ce qu'elle n'arrive pas a rattacher reste visible via
# charges_non_ventilees() plutot que d'etre absorbe silencieusement.
#
# L'ordre compte : le premier motif trouve dans le libelle gagne. Les motifs
# sont compares en majuscules, sur le libelle normalise deja stocke en base.
VENTILATION_REGLEMENTS_FOURNISSEUR = [
    ("VACATION", "632710"),        # PAIEMENT VACATION/<nom> - 153 lignes, 6,11 M F
    ("HONORAIRE", "632710"),
    ("LOYER", "622200"),           # PAIEMENT LOYER <mois> - 14 lignes, 1,90 M F
    ("BAIL", "622200"),
    ("ONEA", "605100"),            # PAIEMENT/FACTURE ONEA - 5 lignes
    ("SONABEL", "605200"),
    ("CASH POWER", "605200"),
    ("GARDIEN", "632720"),
    ("NETTOYAGE", "624330"),
    ("INTERNET", "628820"),
    ("CANAL", "628820"),
]

# Date la plus ancienne consideree comme plausible par ecritures_date_douteuse
# quand aucune borne n'est fournie : deux ans avant l'annee en cours.
RECUL_ANNEES_DATE_PLAUSIBLE = 2

# Mois de demarrage de l'annee academique (septembre). L'annee civile reste
# disponible via resultat_annee_vs_precedente ; voir
# resultat_annee_academique_vs_precedente pour la lecture scolaire, qui est
# celle dont parlent reellement la direction et les centres.
MOIS_DEBUT_ANNEE_ACADEMIQUE = 9


# --- utilitaires internes ----------------------------------------------------

def _filtrer_mois(d, mois_aaaa_mm):
    """mois_aaaa_mm au format '202603' (annee + mois sur 2 chiffres)."""
    if d is None or len(d) == 0:
        return d
    return d[pd.to_datetime(d["date_piece"]).dt.strftime("%Y%m") == str(mois_aaaa_mm)]


def _journaux_tresorerie(ref):
    # Volontairement PAS filtre sur actif : sert aussi a _comptes_caisse(),
    # qui identifie les comptes de tresorerie pour les rapports historiques
    # (recettes_centre_mois, depenses_centre_mois). Un journal retire (ex.
    # l'ancienne banque) doit continuer a compter dans les mois ou il etait
    # encore utilise - retirer un journal ne doit jamais reecrire l'histoire.
    # Seule tresorerie_disponible (photo de la caisse disponible maintenant)
    # exclut les journaux retires, localement - voir plus bas.
    j = ref["journaux"]
    if "type" not in j.columns:
        return list(j["journal"])
    return list(j.loc[j["type"].fillna("tresorerie") == "tresorerie", "journal"])


def _comptes_caisse(ref):
    """Les comptes de contrepartie (571100, 571200, compte bancaire...) de
    tous les journaux de tresorerie - c'est sur ces comptes que se voit une
    entree ou une sortie d'argent reelle."""
    j = ref["journaux"]
    return set(j.loc[j["journal"].isin(_journaux_tresorerie(ref)), "compte_contrepartie"].dropna())


def _comptes_charge(ref):
    return set(ref["comptes"].loc[ref["comptes"]["nature"] == "charge", "compte"])


def _comptes_charge_elargi(ref):
    """Les comptes que l'application traite comme une depense, qu'ils soient
    de nature 'charge' au plan comptable ou non.

    Trois apports au-dela de la nature 'charge' :
      - le compte 422000 (modele "remuneration"), de nature 'tiers' mais bien
        une depense. Corrige le 10/09/2026 : sans lui,
        poste_depense_principal() et depense_anormale() ne pouvaient jamais
        voir un salaire, meme quand il pesait plus lourd que tout le reste ;
      - les comptes que ce module suit nommement comme des charges (categories
        de depense courante, charges fixes, vacations). Ajoute le 11/09/2026 :
        un compte cite ici mais dont la nature n'a pas ete renseignee au plan
        de comptes disparaissait autrement de toutes les analyses, sans
        aucun signal - le genre d'oubli de referentiel qui arrive et qui ne se
        voit pas.
    """
    suivis = set(CATEGORIES_DEPENSE_COURANTE.values()) | set(COMPTES_CHARGES_FIXES) \
        | set(COMPTES_LOYER_EAU_ELECTRICITE) | {COMPTE_VACATION}
    return _comptes_charge(ref) | {COMPTE_PERSONNEL} | suivis


def _comptes_tresorerie(ref):
    """Tous les comptes de nature 'tresorerie' du plan : les caisses (571100,
    571200), la banque (521100) et le compte de passage 585000. Distinct de
    _comptes_caisse(), qui ne retient que les contreparties declarees des
    journaux - 585000 n'est la contrepartie d'aucun journal, mais c'est bien
    de l'argent qui bouge."""
    return set(ref["comptes"].loc[ref["comptes"]["nature"] == "tresorerie", "compte"])


def _avec_nom_centre(df, ref):
    """Ajoute la colonne `centre_nom` (nom complet) a cote de `centre` (code).

    Ajoute le 12/09/2026 : le code a trois lettres est une cle technique et
    n'a jamais a etre montre. Sans cette colonne, l'assistant IA et les
    graphiques annoncaient "SIA" et "TAM" au lieu de "SIAO" et "Tampouy"."""
    if df is None or len(df) == 0 or "centre" not in df.columns:
        return df
    df = df.copy()
    df["centre_nom"] = [dl.nom_centre(ref, c) for c in df["centre"]]
    return df


def _par_piece(d):
    """Colonne de regroupement par piece, tolerante : certains appels de test
    fournissent un DataFrame sans id_piece. Chaque ligne est alors sa propre
    piece, ce qui ne change rien pour une piece d'une seule ligne."""
    if "id_piece" in d.columns:
        return d["id_piece"]
    return pd.Series(d.index, index=d.index)


def pieces_transfert_interne(d, ref):
    """id_piece des pieces qui ne font que deplacer de l'argent d'une caisse a
    une autre : approvisionnement de la CMD, versement d'especes en banque,
    retrait bancaire pour alimenter la caisse.

    Critere comptable, et non declaratif : une piece est un transfert interne
    des lors qu'elle mouvemente DEUX comptes de tresorerie distincts (caisse,
    banque, ou compte de passage 585000). Un encaissement d'eleve ne touche
    qu'une caisse (571100 au debit, 411000 au credit) ; un reglement
    fournisseur non plus (401000 au debit, 571200 au credit). Un
    approvisionnement, lui, touche 571200 et 585000 - ou 571100 et 571200
    selon la facon dont la piece est construite.

    C'est ce critere qui remplace, depuis le 11/09/2026, le filtre par nom de
    modele : il est vrai pour la saisie applicative COMME pour l'historique
    importe, sans qu'il faille retoucher une seule ecriture en base."""
    if d is None or len(d) == 0:
        return set()
    tresorerie = _comptes_tresorerie(ref)
    mouvements = d[d["compte"].isin(tresorerie)]
    if len(mouvements) == 0:
        return set()
    comptes_par_piece = mouvements.groupby(_par_piece(mouvements))["compte"].nunique()
    return set(comptes_par_piece[comptes_par_piece >= 2].index)


def _hors_transferts(d, ref):
    """d prive de ses pieces de transfert interne, par les deux criteres :
    le critere comptable (pieces_transfert_interne) et, en second filet, le
    nom du modele quand il est renseigne par la saisie applicative."""
    if d is None or len(d) == 0:
        return d
    transferts = pieces_transfert_interne(d, ref)
    garde = ~d["modele"].isin(MODELES_TRANSFERT_INTERNE) if "modele" in d.columns else True
    if transferts:
        garde = garde & ~_par_piece(d).isin(transferts)
    return d[garde]


def compte_charge_effectif(compte, libelle):
    """Compte de charge reellement concerne par une ligne de depense.

    Pour tout compte autre que le collectif fournisseur, c'est le compte
    lui-meme. Pour un reglement passe directement par 401000 (voir
    VENTILATION_REGLEMENTS_FOURNISSEUR), c'est le compte de charge que le
    libelle normalise permet d'identifier - et 401000 lui-meme quand aucun
    motif ne correspond, auquel cas la ligne ressort dans
    charges_non_ventilees() pour que la comptable la traite a la main."""
    if compte != COMPTE_FOURNISSEUR:
        return compte
    texte = str(libelle or "").upper()
    for motif, compte_cible in VENTILATION_REGLEMENTS_FOURNISSEUR:
        if motif in texte:
            return compte_cible
    return COMPTE_FOURNISSEUR


def tiers_en_regime_facture(d_complet, ref):
    """Fournisseurs dont les charges sont deja comptabilisees a la facture.

    Un fournisseur est "en regime facture" des lors qu'au moins une piece
    credite le collectif 401000 en contrepartie d'un compte de charge - le
    schema du journal des achats : charge au debit, dette fournisseur au
    credit. Pour ces fournisseurs, la charge est reconnue a la facture, et le
    reglement qui suivra (401000 au debit, caisse au credit) n'est qu'un
    mouvement de tresorerie : le compter serait un double comptage.

    Les autres fournisseurs - a Hakili Lab, la quasi-totalite - sont regles
    directement, sans facture prealable : c'est alors le reglement lui-meme
    qui porte la charge, et lui seul.

    Limite assumee : un fournisseur qui melangerait les deux schemas verrait
    ses reglements directs ignores. Le calcul penche donc du cote de la
    sous-estimation plutot que du double comptage, ce qui est le bon sens
    d'erreur en comptabilite - et charges_non_ventilees reste la pour rendre
    l'ecart visible."""
    if d_complet is None or len(d_complet) == 0:
        return set()
    charges = _comptes_charge_elargi(ref)
    avec_charge = d_complet[d_complet["compte"].isin(charges) & (d_complet["debit"] > 0)]
    if len(avec_charge) == 0:
        return set()
    pieces_de_charge = set(_par_piece(avec_charge))
    credits = d_complet[(d_complet["compte"] == COMPTE_FOURNISSEUR) & (d_complet["credit"] > 0)]
    if len(credits) == 0:
        return set()
    credits = credits[_par_piece(credits).isin(pieces_de_charge)]
    return {t for t in credits.get("code_tiers", []) if t}


def lignes_depense(d, ref, d_complet=None):
    """Les lignes qui constituent une charge, avec une colonne supplementaire
    `compte_charge` : le compte auquel la depense doit reellement etre
    rattachee (voir compte_charge_effectif).

    Deux sources :
      1. les debits d'un compte de nature 'charge', plus le collectif 422000
         (modele "remuneration", de nature 'tiers' mais bien une depense) ;
      2. les debits du collectif fournisseur 401000 qui portent eux-memes la
         charge, faute de facture prealable - le cas courant a Hakili Lab.

    Deux garde-fous contre le double comptage, l'un dans la piece et l'autre
    entre pieces : un reglement est ignore s'il est deja adosse a une charge
    dans SA PROPRE piece, et s'il concerne un fournisseur en regime facture
    (voir tiers_en_regime_facture), dont la charge a ete reconnue dans une
    piece ANTERIEURE. Le second cas ne peut se voir qu'en regardant tout
    l'historique : d_complet sert a cela quand d est deja borne a un mois."""
    vide = pd.DataFrame(columns=list(d.columns) + ["compte_charge"]) if d is not None else pd.DataFrame()
    if d is None or len(d) == 0:
        return vide
    charges = _comptes_charge_elargi(ref)
    directes = d[d["compte"].isin(charges) & (d["debit"] > 0)]
    reglements = d[(d["compte"] == COMPTE_FOURNISSEUR) & (d["debit"] > 0)]
    if len(reglements):
        pieces_avec_charge = set(_par_piece(directes)) if len(directes) else set()
        if pieces_avec_charge:
            reglements = reglements[~_par_piece(reglements).isin(pieces_avec_charge)]
    if len(reglements):
        deja_facture = tiers_en_regime_facture(d if d_complet is None else d_complet, ref)
        if deja_facture:
            reglements = reglements[~reglements["code_tiers"].isin(deja_facture)]
    res = pd.concat([directes, reglements]) if len(reglements) else directes
    if len(res) == 0:
        return vide
    res = res.copy()
    res["compte_charge"] = [compte_charge_effectif(c, l)
                            for c, l in zip(res["compte"], res.get("libelle", pd.Series([""] * len(res))))]
    return res


def _depenses_du_mois(mois_aaaa_mm, d, ref):
    """lignes_depense() bornee a un mois - raccourci utilise par tous les
    indicateurs de depense, qui partagent ainsi exactement le meme perimetre.
    L'historique complet est transmis en second : une facture de fevrier
    reglee en mars doit rester visible quand on analyse mars."""
    return lignes_depense(_filtrer_mois(d, mois_aaaa_mm), ref, d_complet=d)


def _total_charges(mois_aaaa_mm, d, ref):
    """Total des charges du mois, au sens de lignes_depense : comptes de
    charge, salaires du modele "remuneration", et reglements fournisseurs
    directs reconstitues. Corrige le 11/09/2026 - auparavant fonde sur la
    seule nature 'charge' du plan de comptes, ce qui laissait 92,6 % des
    depenses reelles de Hakili Lab hors du perimetre."""
    return float(_depenses_du_mois(mois_aaaa_mm, d, ref)["debit"].sum())


def _total_charges_avec_salaires(mois_aaaa_mm, d, ref):
    """Conserve pour compatibilite : _total_charges inclut desormais les
    salaires (voir lignes_depense), cette fonction lui est identique. Les
    appels existants continuent de fonctionner a l'identique."""
    return _total_charges(mois_aaaa_mm, d, ref)


def mois_precedent(mois_aaaa_mm):
    return (pd.Period(str(mois_aaaa_mm), freq="M") - 1).strftime("%Y%m")


def mois_fin_ou_courant(mois_aaaa_mm):
    """mois_aaaa_mm s'il est fourni, sinon le mois courant du systeme
    (AAAAMM) - evite de dupliquer ce repli par defaut dans chaque fonction
    qui accepte un mois de fin optionnel."""
    return str(mois_aaaa_mm) if mois_aaaa_mm else pd.Timestamp.now().strftime("%Y%m")


def annee_de(mois_aaaa_mm):
    return str(mois_aaaa_mm)[:4]


# --- questions non couvertes par les donnees actuelles ----------------------
#
# Certaines questions de la liste validee avec la direction (06/09/2026)
# supposent une donnee que Hakili_compta ne contient pas encore : une
# grille tarifaire par centre/formule (pour calculer un montant "attendu"),
# un echeancier par eleve (pour distinguer un retard d'un simple "pas encore
# echu"), ou un mecanisme comptable d'inter-centres. Plutot que de laisser
# l'assistant deviner ou planter, chaque outil concerne renvoie cette
# reponse structuree : le modele de langage peut alors l'expliquer
# clairement au comptable, sans jamais inventer un chiffre a la place.
def _indisponible(question, prerequis_manquant):
    return {
        "disponible": False,
        "question": question,
        "prerequis_manquant": prerequis_manquant,
        "message": (
            f"Cette question ne peut pas encore recevoir de reponse fiable : "
            f"{prerequis_manquant}. Merci de le signaler tel quel au "
            f"comptable plutot que d'approximer un chiffre."
        ),
    }


# =============================================================================
# RECETTES
# =============================================================================

def recettes_centre_mois(centre, mois_aaaa_mm, ref=None, d=None):
    """Total encaisse par le centre sur le mois, tous journaux de tresorerie
    confondus.

    Definition retenue : toute entree d'argent en caisse compte comme une
    recette, meme si sa contrepartie est encore le compte d'attente 471000
    en attente de reclassement - l'argent est bel et bien rentre, seul son
    etiquetage comptable est provisoire. Les mouvements internes entre
    caisses du meme centre (approvisionnement CP -> CMD, versement en
    banque) sont exclus : ce sont des transferts d'argent deja compte
    ailleurs, pas de nouvelles recettes.
    """
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    d = d[d["centre"] == centre]
    d = _filtrer_mois(d, mois_aaaa_mm)
    if len(d) == 0:
        return 0.0
    d = _hors_transferts(d, ref)
    ccs = _comptes_caisse(ref)
    d = d[d["compte"].isin(ccs)]
    return float(d["debit"].sum())


def depenses_centre_mois(centre, mois_aaaa_mm, ref=None, d=None):
    """Symetrique de recettes_centre_mois : sorties de caisse reelles du
    centre sur le mois, hors transferts internes entre ses propres caisses."""
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    d = d[d["centre"] == centre]
    d = _filtrer_mois(d, mois_aaaa_mm)
    if len(d) == 0:
        return 0.0
    d = _hors_transferts(d, ref)
    ccs = _comptes_caisse(ref)
    d = d[d["compte"].isin(ccs)]
    return float(d["credit"].sum())


def repartition_recettes_mois(centre, mois_aaaa_mm, ref=None, d=None):
    """Repartit les recettes du mois entre frais de scolarite effectivement
    encaisses (compte 411000, journal CP) et prestations facturees (comptes
    706110/706120/706130, journal VTE).

    Attention, les deux montants ne sont pas sur la meme base comptable : le
    premier est un encaissement reel, le second une facturation qui n'est
    pas necessairement encore payee. Ils doivent toujours etre presentes
    separement, jamais additionnes comme une seule "recette".
    """
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    d = d[d["centre"] == centre]
    d = _filtrer_mois(d, mois_aaaa_mm)
    scolarite = float(d.loc[(d["compte"] == "411000") & (d["journal"] == "CP"), "credit"].sum())
    comptes_prestations = {"706110", "706120", "706130"}
    prestations = float(d.loc[d["compte"].isin(comptes_prestations) & (d["journal"] == "VTE"), "credit"].sum())
    # Rapprochement ajoute le 11/09/2026. Sans lui, cet outil et
    # recettes_du_mois repondaient deux montants differents a la meme question
    # sans que rien ne le signale : sur Saaba en mars 2026, 810 500 F ici
    # contre 1 649 500 F la-bas. Le modele de langage annoncait donc l'un ou
    # l'autre au comptable, avec la meme assurance, selon l'outil qu'il avait
    # choisi. L'ecart est desormais explicite et chiffre dans la reponse.
    total = recettes_centre_mois(centre, mois_aaaa_mm, ref, d)
    return {"scolarite_encaissee": scolarite, "prestations_facturees": prestations,
            "total_recettes_encaissees": total,
            "autres_encaissements": total - scolarite,
            "note": ("scolarite_encaissee et prestations_facturees ne sont pas sur la meme base "
                     "comptable (encaissement reel contre facturation) et ne doivent jamais etre "
                     "additionnees. autres_encaissements est la part du total encaisse qui ne vient "
                     "pas du compte 411000 au journal CP : frais de dossier, ventes diverses, "
                     "remboursements.")}


def montant_a_reclasser(centre, mois_aaaa_mm, d=None):
    """Solde encore ouvert sur le compte d'attente 471000 pour ce centre et
    ce mois : ce qu'il reste au comptable a reclasser sur le bon compte. Ne
    signale aucun manque d'argent - l'argent est deja dans la bonne caisse,
    seule son affectation comptable definitive reste a faire."""
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    d = d[d["centre"] == centre]
    d = _filtrer_mois(d, mois_aaaa_mm)
    d = d[d["compte"] == COMPTE_ATTENTE]
    solde = float(d["debit"].sum() - d["credit"].sum())
    return {"solde_a_reclasser": solde, "nombre_pieces": int(d["id_piece"].nunique())}


def classement_centres_recettes(mois_aaaa_mm, ref=None):
    """Classe tous les centres par recettes encaissees sur le mois, du plus
    au moins eleve.

"""
    ref = ref or dl.lire_referentiel()
    d = dl.lire_ecritures()
    lignes = [{"centre": c,
                "recettes": recettes_centre_mois(c, mois_aaaa_mm, ref, d)}
              for c in ref["centres"]["code_centre"]]
    return _avec_nom_centre(pd.DataFrame(lignes).sort_values("recettes", ascending=False)
                              .reset_index(drop=True), ref)


# =============================================================================
# DEPENSES
# =============================================================================

def poste_depense_principal(mois_aaaa_mm, centre=None, ref=None, d=None):
    """Le compte de charge (nature 'charge' au plan de comptes, plus 422000
    "remuneration" - voir _comptes_charge_elargi) qui a pese le plus lourd
    sur le mois. Se base sur la comptabilisation de la charge, pas sur la
    sortie de caisse : une facture d'achat peut etre comptabilisee sans que
    la caisse bouge le meme jour, et une seule sortie de caisse peut regler
    plusieurs comptes de charge a la fois."""
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    if centre:
        d = d[d["centre"] == centre]
    dep = _depenses_du_mois(mois_aaaa_mm, d, ref)
    if len(dep) == 0:
        return None
    par_compte = dep.groupby("compte_charge")["debit"].sum().sort_values(ascending=False)
    compte = par_compte.index[0]
    return {"compte": compte, "intitule": dl.intitule_compte(ref, compte),
            "montant": float(par_compte.iloc[0]),
            "total_charges": float(dep["debit"].sum())}


def part_masse_salariale(mois_aaaa_mm, centre=None, ref=None, d=None):
    """Part de la masse salariale dans le total des charges du mois.

    La masse salariale regroupe deux comptes distincts du plan comptable,
    confirme avec la direction le 06/09/2026 : le compte 422000 (modele
    "remuneration", salaries payes via la caisse CMD) et le compte 632710
    (modele "vacation", professeurs payes a la vacation via le journal ACH).
    Les compter separement sous-estimerait fortement la masse salariale
    reelle, la vacation etant le mode de paiement dominant a Hakili Lab.

    Point decouvert le 06/09/2026 : le modele "remuneration" (voir
    logic/modeles.py) ne credite jamais un compte de nature 'charge' - il
    debite directement le collectif tiers 422000 par la caisse, sans jamais
    toucher un compte de charge du plan comptable. _total_charges() (base
    sur la seule nature 'charge') ignore donc entierement ces salaires,
    alors que le modele "vacation" (compte 632710, nature 'charge') y est
    deja compte normalement. Additionner les salaires au numerateur sans
    les ajouter au denominateur donnerait un pourcentage incoherent
    (potentiellement superieur a 100 %) : _total_charges_avec_salaires()
    (voir plus haut) compense specifiquement ce cas. Corrige le 10/09/2026 :
    le meme angle mort affectait aussi poste_depense_principal,
    part_charges_fixes, part_loyer_eau_electricite et depense_anormale des
    que le modele "remuneration" etait utilise - les quatre fonctions
    reutilisent desormais _comptes_charge_elargi/_total_charges_avec_salaires
    plutot que de dupliquer ce raisonnement chacune a leur maniere.
    """
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    if centre:
        d = d[d["centre"] == centre]
    # Corrige le 11/09/2026 : la lecture se fait desormais sur compte_charge
    # et non sur compte. A Hakili Lab, les vacations sont reglees directement
    # par le collectif 401000 ; lues sur le compte brut, elles etaient
    # invisibles et cet indicateur repondait 0 % sur des mois ou la masse
    # salariale representait l'essentiel des sorties de caisse.
    dep = _depenses_du_mois(mois_aaaa_mm, d, ref)
    if len(dep) == 0:
        return {"masse_salariale": 0.0, "salaires": 0.0, "vacations": 0.0,
                "total_charges": 0.0, "part_pct": 0.0}
    salaires = float(dep.loc[dep["compte_charge"] == COMPTE_PERSONNEL, "debit"].sum())
    vacations = float(dep.loc[dep["compte_charge"] == COMPTE_VACATION, "debit"].sum())
    masse = salaires + vacations
    total = float(dep["debit"].sum())
    part = (masse / total * 100) if total else 0.0
    return {"masse_salariale": masse, "salaires": salaires, "vacations": vacations,
            "total_charges": total, "part_pct": part}


def part_charges_fixes(mois_aaaa_mm, centre=None, ref=None, d=None):
    """Part des charges fixes (loyer, eau, electricite - voir
    COMPTES_CHARGES_FIXES, a valider avec la comptable) dans le total des
    charges du mois, salaires du modele "remuneration" compris au
    denominateur (voir _total_charges_avec_salaires - corrige le
    10/09/2026 : ce pourcentage etait gonfle mecaniquement pour tout centre
    ayant du personnel paye par ce modele)."""
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    if centre:
        d = d[d["centre"] == centre]
    dep = _depenses_du_mois(mois_aaaa_mm, d, ref)
    total = float(dep["debit"].sum()) if len(dep) else 0.0
    fixes = float(dep.loc[dep["compte_charge"].isin(COMPTES_CHARGES_FIXES), "debit"].sum()) if len(dep) else 0.0
    part = (fixes / total * 100) if total else 0.0
    return {"charges_fixes": fixes, "total_charges": total, "part_pct": part}


def part_loyer_eau_electricite(mois_aaaa_mm, centre=None, ref=None, d=None):
    """Part du loyer, de l'eau (ONEA) et de l'electricite (SONABEL / Cash
    Power) dans le total des charges du mois - voir
    COMPTES_LOYER_EAU_ELECTRICITE. Plus etroit que part_charges_fixes, qui
    inclut aussi le gardiennage : celui-ci n'est volontairement pas compte
    ici, la question posee (Q18) ne portant que sur ces trois postes.
    Salaires compris au denominateur, memes raisons que part_charges_fixes."""
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    if centre:
        d = d[d["centre"] == centre]
    dep = _depenses_du_mois(mois_aaaa_mm, d, ref)
    total = float(dep["debit"].sum()) if len(dep) else 0.0
    montant = (float(dep.loc[dep["compte_charge"].isin(COMPTES_LOYER_EAU_ELECTRICITE), "debit"].sum())
               if len(dep) else 0.0)
    part = (montant / total * 100) if total else 0.0
    return {"loyer_eau_electricite": montant, "total_charges": total, "part_pct": part}


def depense_moyenne_categorie(centre=None, ref=None, d=None, nb_mois=6, mois_fin=None):
    """Depense moyenne mensuelle pour chacune des categories de
    CATEGORIES_DEPENSE_COURANTE (nettoyage, telecom, fournitures, carburant),
    calculee sur les nb_mois mois se terminant a mois_fin inclus (mois
    courant du systeme si omis - voir mois_fin_ou_courant)."""
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    if centre:
        d = d[d["centre"] == centre]
    if len(d) == 0:
        return {cat: 0.0 for cat in CATEGORIES_DEPENSE_COURANTE}
    fin = pd.Period(mois_fin_ou_courant(mois_fin), freq="M")
    mois_liste = {(fin - i).strftime("%Y%m") for i in range(nb_mois)}
    d = lignes_depense(d, ref)
    if len(d) == 0:
        return {cat: 0.0 for cat in CATEGORIES_DEPENSE_COURANTE}
    d = d.copy()
    d["mois"] = pd.to_datetime(d["date_piece"]).dt.strftime("%Y%m")
    d = d[d["mois"].isin(mois_liste)]
    resultat = {}
    for categorie, compte in CATEGORIES_DEPENSE_COURANTE.items():
        dc = d[d["compte_charge"] == compte]
        par_mois = dc.groupby("mois")["debit"].sum()
        # Moyenne sur les mois ou une depense existe reellement : un mois
        # sans facture de carburant ne doit pas artificiellement diluer la
        # moyenne vers zero, il doit juste ne pas compter.
        resultat[categorie] = float(par_mois.mean()) if len(par_mois) else 0.0
    return resultat


def depense_anormale(mois_aaaa_mm, centre=None, ref=None, d=None):
    """Compare, compte de charge par compte de charge, la depense du mois a
    la moyenne des mois precedents (meme compte, meme centre). Signale un
    compte quand le mois en cours depasse SEUIL_DEPENSE_ANORMALE fois cette
    moyenne, et seulement au-dessus de MONTANT_MIN_ANOMALIE pour eviter le
    bruit sur les petits comptes ponctuels. Comptes surveilles elargis a
    422000 "remuneration" (voir _comptes_charge_elargi - corrige le
    10/09/2026 : un salaire anormalement eleve un mois donne ne pouvait
    auparavant jamais etre signale, ce compte etant de nature 'tiers')."""
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    if centre:
        d = d[d["centre"] == centre]
    if len(d) == 0:
        return []
    d = lignes_depense(d, ref)
    if len(d) == 0:
        return []
    d = d.copy()
    d["mois"] = pd.to_datetime(d["date_piece"]).dt.strftime("%Y%m")
    par_mois_compte = d.groupby(["mois", "compte_charge"])["debit"].sum().reset_index()
    par_mois_compte = par_mois_compte.rename(columns={"compte_charge": "compte"})
    mois_courant = par_mois_compte[par_mois_compte["mois"] == str(mois_aaaa_mm)]
    historique = par_mois_compte[par_mois_compte["mois"] != str(mois_aaaa_mm)]
    moyennes = historique.groupby("compte")["debit"].mean()
    alertes = []
    for _, row in mois_courant.iterrows():
        moy = moyennes.get(row["compte"])
        if moy and row["debit"] > moy * SEUIL_DEPENSE_ANORMALE and row["debit"] > MONTANT_MIN_ANOMALIE:
            alertes.append({"compte": row["compte"], "intitule": dl.intitule_compte(ref, row["compte"]),
                             "montant_mois": float(row["debit"]), "moyenne_historique": float(moy)})
    return sorted(alertes, key=lambda x: x["montant_mois"], reverse=True)


# =============================================================================
# RENTABILITE PAR CENTRE
# =============================================================================

def effectif_actif_centre_mois(centre, mois_aaaa_mm, d=None):
    """Proxy du nombre d'eleves actifs : nombre de codes tiers distincts du
    collectif 411000 cites dans une ecriture qui touche ce compte pour ce
    centre sur le mois (encaissement CP ou facturation VTE).

    Ce n'est PAS un effectif reel : en l'absence d'une table d'inscriptions,
    un eleve inscrit mais qui n'a encore rien paye et n'a rien ete facture
    ce mois n'apparait pas ici. A remplacer par un vrai comptage
    d'inscriptions des que cette table existera dans Hakili_compta.
    """
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    d = d[d["centre"] == centre]
    d = _filtrer_mois(d, mois_aaaa_mm)
    d = d[(d["compte"] == "411000") & (d["code_tiers"] != "")]
    return int(d["code_tiers"].nunique())


def marge_centre_mois(centre, mois_aaaa_mm, ref=None, d=None):
    """Marge en pourcentage : (recettes - depenses) / recettes x 100.

    Formule retenue pour comparer des centres de tailles differentes sans
    favoriser artificiellement un petit centre a faible activite : une
    marge de 20 % sur 500 000 F et une marge de 20 % sur 5 000 000 F
    representent le meme niveau de gestion, ce qu'une simple soustraction
    recettes - depenses en valeur absolue ne permettrait pas de voir (elle
    designerait systematiquement le plus gros centre comme "le plus
    rentable", meme mal gere).
    """
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    rec = recettes_centre_mois(centre, mois_aaaa_mm, ref, d)
    dep = depenses_centre_mois(centre, mois_aaaa_mm, ref, d)
    marge_pct = ((rec - dep) / rec * 100) if rec else None
    return {"recettes": rec, "depenses": dep, "marge_pct": marge_pct}


def recette_par_eleve_centre_mois(centre, mois_aaaa_mm, ref=None, d=None):
    """Recette encaissee rapportee au nombre d'eleves actifs (proxy) :
    deuxieme lecture de la rentabilite, complementaire a la marge - utile
    quand deux centres ont une marge proche mais des tailles tres
    differentes."""
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    rec = recettes_centre_mois(centre, mois_aaaa_mm, ref, d)
    eff = effectif_actif_centre_mois(centre, mois_aaaa_mm, d)
    return {"recettes": rec, "effectif_proxy": eff,
            "recette_par_eleve": (rec / eff) if eff else None}


def classement_rentabilite_centres(mois_aaaa_mm, ref=None):
    """Classe les centres par marge en pourcentage (voir marge_centre_mois),
    jamais par recettes - depenses en valeur absolue : un centre a faible
    activite mais bien gere doit pouvoir ressortir devant un grand centre
    qui degage plus de francs avec une gestion moins efficace."""
    ref = ref or dl.lire_referentiel()
    d = dl.lire_ecritures()
    lignes = []
    for centre in ref["centres"]["code_centre"]:
        m = marge_centre_mois(centre, mois_aaaa_mm, ref, d)
        m["centre"] = centre
        lignes.append(m)
    return _avec_nom_centre(pd.DataFrame(lignes)
                              .sort_values("marge_pct", ascending=False, na_position="last")
                              .reset_index(drop=True), ref)


# =============================================================================
# COMPARAISON DE CENTRES
# =============================================================================

def recettes_centre_trimestre(centre, mois_fin_aaaa_mm, ref=None, d=None):
    """Somme des recettes des 3 mois se terminant a mois_fin_aaaa_mm inclus."""
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    fin = pd.Period(str(mois_fin_aaaa_mm), freq="M")
    mois_liste = [(fin - i).strftime("%Y%m") for i in range(3)]
    return float(sum(recettes_centre_mois(centre, m, ref, d) for m in mois_liste))


def structure_couts_centre_mois(centre, mois_aaaa_mm, ref=None, d=None):
    """Depenses rapportees aux recettes du centre, en pourcentage : plus ce
    ratio est bas, plus la structure de couts est legere. Lecture
    complementaire a la marge (100 - ce ratio = la marge en pourcentage)."""
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    rec = recettes_centre_mois(centre, mois_aaaa_mm, ref, d)
    dep = depenses_centre_mois(centre, mois_aaaa_mm, ref, d)
    ratio = (dep / rec * 100) if rec else None
    return {"recettes": rec, "depenses": dep, "ratio_couts_pct": ratio}


def contribution_centres_mois(mois_aaaa_mm, ref=None):
    """Part de chaque centre dans le total consolide des recettes du mois.

"""
    classement = classement_centres_recettes(mois_aaaa_mm, ref)
    total = classement["recettes"].sum()
    classement["part_pct"] = (classement["recettes"] / total * 100) if total else 0.0
    return _avec_nom_centre(classement, ref)


# =============================================================================
# SUIVI MENSUEL / TRESORERIE
# =============================================================================

def resultat_net_mois(mois_aaaa_mm, ref=None):
    """Recettes moins depenses, tous centres confondus, sur le mois."""
    ref = ref or dl.lire_referentiel()
    d = dl.lire_ecritures()
    centres = ref["centres"]["code_centre"]
    rec = sum(recettes_centre_mois(c, mois_aaaa_mm, ref, d) for c in centres)
    dep = sum(depenses_centre_mois(c, mois_aaaa_mm, ref, d) for c in centres)
    return {"recettes": rec, "depenses": dep, "resultat_net": rec - dep}


def evolution_6mois(mois_fin_aaaa_mm, ref=None):
    """Recettes et depenses consolidees, mois par mois, sur les 6 derniers
    mois se terminant a mois_fin_aaaa_mm inclus."""
    ref = ref or dl.lire_referentiel()
    d = dl.lire_ecritures()
    centres = ref["centres"]["code_centre"]
    fin = pd.Period(str(mois_fin_aaaa_mm), freq="M")
    lignes = []
    for i in range(5, -1, -1):
        m = (fin - i).strftime("%Y%m")
        rec = sum(recettes_centre_mois(c, m, ref, d) for c in centres)
        dep = sum(depenses_centre_mois(c, m, ref, d) for c in centres)
        lignes.append({"mois": m, "recettes": rec, "depenses": dep})
    return pd.DataFrame(lignes)


# =============================================================================
# CONTROLE / ANOMALIES
# =============================================================================

def paiements_suspects(mois_aaaa_mm, d=None, ref=None):
    """Pieces distinctes qui partagent exactement la meme date, le meme tiers
    et le meme montant de mouvement de caisse - un doublon probable de saisie,
    ou un paiement a verifier.

    Reecrit le 11/09/2026. L'ancienne version filtrait les LIGNES sur
    `debit > 0 et code_tiers non vide`, ce qui la rendait structurellement
    aveugle aux encaissements : dans une piece de recette, la ligne qui porte
    le tiers est celle du compte 411000, et elle est au CREDIT ; la ligne au
    debit est celle de la caisse, qui n'a pas de tiers. Aucune recette ne
    franchissait donc le filtre, alors que le doublon de saisie redoute est
    justement celui d'un reglement d'eleve. Sur les brouillards reels,
    l'outil renvoyait zero doublon sur huit mois alors que sept groupes
    existaient - dont trois reglements de 20 000 F au meme eleve le meme jour.

    La version actuelle raisonne par PIECE : le montant compare est le
    mouvement net de tresorerie de la piece, et le sens (encaissement ou
    decaissement) est conserve pour que deux operations inverses du meme
    montant ne soient jamais rapprochees a tort. Les transferts internes sont
    exclus : approvisionner deux caisses du meme montant le meme jour est une
    routine, pas une anomalie."""
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures()
    d = _filtrer_mois(d, mois_aaaa_mm)
    if d is None or len(d) == 0:
        return []
    d = _hors_transferts(d, ref)
    if len(d) == 0:
        return []
    tresorerie = _comptes_tresorerie(ref)
    lignes = []
    for id_piece, piece in d.groupby(_par_piece(d)):
        mouvement = piece[piece["compte"].isin(tresorerie)]
        montant = float(mouvement["debit"].sum() - mouvement["credit"].sum())
        if montant == 0:
            continue
        tiers = [t for t in piece["code_tiers"] if t]
        if not tiers:
            continue
        lignes.append({
            "id_piece": str(id_piece), "date_piece": piece["date_piece"].iloc[0],
            "code_tiers": tiers[0], "montant": abs(montant),
            "sens": "encaissement" if montant > 0 else "decaissement",
            "centre": piece["centre"].iloc[0], "journal": piece["journal"].iloc[0],
            "libelle": piece["libelle"].iloc[0] if "libelle" in piece.columns else "",
        })
    if not lignes:
        return []
    pieces = pd.DataFrame(lignes)
    cles = ["date_piece", "code_tiers", "montant", "sens"]
    doublons = pieces[pieces.duplicated(subset=cles, keep=False)]
    if len(doublons) == 0:
        return []
    return doublons.sort_values(["date_piece", "code_tiers", "montant"]).to_dict("records")


def evolution_montant_a_reclasser(mois_aaaa_mm, ref=None):
    """Compare, pour l'ensemble des centres, le solde encore ouvert sur le
    compte d'attente 471000 entre le mois donne et le mois precedent -
    indicateur de la charge de reclassement du comptable, en hausse ou en
    baisse."""
    ref = ref or dl.lire_referentiel()
    d = dl.lire_ecritures()
    centres = ref["centres"]["code_centre"]
    mois_prec = mois_precedent(mois_aaaa_mm)
    actuel = sum(montant_a_reclasser(c, mois_aaaa_mm, d)["solde_a_reclasser"] for c in centres)
    precedent = sum(montant_a_reclasser(c, mois_prec, d)["solde_a_reclasser"] for c in centres)
    return {"mois": mois_aaaa_mm, "mois_precedent": mois_prec,
            "solde_actuel": actuel, "solde_precedent": precedent}



# =============================================================================
# RENTABILITE PAR CENTRE - complements (Q25, Q26, Q28, Q29)
# =============================================================================

def classement_centres_recettes_trimestre(mois_fin_aaaa_mm, ref=None):
    """Classe tous les centres par recettes cumulees sur le trimestre se
    terminant a mois_fin_aaaa_mm inclus, du plus au moins eleve (Q25)."""
    ref = ref or dl.lire_referentiel()
    d = dl.lire_ecritures()
    lignes = [{"centre": c, "recettes_trimestre": recettes_centre_trimestre(c, mois_fin_aaaa_mm, ref, d)}
              for c in ref["centres"]["code_centre"]]
    return _avec_nom_centre(pd.DataFrame(lignes)
                              .sort_values("recettes_trimestre", ascending=False)
                              .reset_index(drop=True), ref)


def classement_structure_couts(mois_aaaa_mm, ref=None):
    """Classe les centres par ratio couts/recettes (voir
    structure_couts_centre_mois), du plus leger (ratio le plus bas, donc le
    meilleur) au plus lourd (Q26)."""
    ref = ref or dl.lire_referentiel()
    d = dl.lire_ecritures()
    lignes = []
    for centre in ref["centres"]["code_centre"]:
        s = structure_couts_centre_mois(centre, mois_aaaa_mm, ref, d)
        s["centre"] = centre
        lignes.append(s)
    return _avec_nom_centre(pd.DataFrame(lignes)
                              .sort_values("ratio_couts_pct", na_position="last")
                              .reset_index(drop=True), ref)


def effectif_actif_evolution(centre, mois_fin_aaaa_mm, nb_mois=6, d=None):
    """Evolution de l'effectif actif proxy (voir effectif_actif_centre_mois)
    d'un centre, mois par mois, sur les nb_mois se terminant a
    mois_fin_aaaa_mm inclus (Q28). Meme reserve que l'effectif ponctuel :
    proxy calcule sur les ecritures, pas un vrai comptage d'inscriptions."""
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    fin = pd.Period(str(mois_fin_aaaa_mm), freq="M")
    lignes = [{"mois": (fin - i).strftime("%Y%m"),
               "effectif_proxy": effectif_actif_centre_mois(centre, (fin - i).strftime("%Y%m"), d)}
              for i in range(nb_mois - 1, -1, -1)]
    return pd.DataFrame(lignes)


def evolution_resultat_par_centre(mois_fin_aaaa_mm, nb_mois=6, ref=None):
    """Resultat net (recettes - depenses), centre par centre et mois par
    mois, sur les nb_mois se terminant a mois_fin_aaaa_mm inclus (Q29).
    Complementaire a evolution_6mois, qui ne donne que le total consolide."""
    ref = ref or dl.lire_referentiel()
    d = dl.lire_ecritures()
    fin = pd.Period(str(mois_fin_aaaa_mm), freq="M")
    lignes = []
    for i in range(nb_mois - 1, -1, -1):
        m = (fin - i).strftime("%Y%m")
        for centre in ref["centres"]["code_centre"]:
            rec = recettes_centre_mois(centre, m, ref, d)
            dep = depenses_centre_mois(centre, m, ref, d)
            lignes.append({"mois": m, "centre": centre, "recettes": rec, "depenses": dep,
                            "resultat_net": rec - dep})
    return _avec_nom_centre(pd.DataFrame(lignes), ref)


# =============================================================================
# VUE D'ENSEMBLE - resultat annuel (Q11)
# =============================================================================

def resultat_annee_vs_precedente(mois_fin_aaaa_mm, ref=None):
    """Cumul recettes/depenses/resultat net depuis janvier jusqu'a
    mois_fin_aaaa_mm inclus, compare a la meme periode (janvier au meme mois
    calendaire) de l'annee precedente (Q11). Annee civile faute d'une date
    de debut d'annee academique stockee en base - hypothese a signaler dans
    la reponse si la question porte sur une annee academique au sens
    scolaire (septembre a juillet)."""
    ref = ref or dl.lire_referentiel()
    d = dl.lire_ecritures()
    fin = pd.Period(str(mois_fin_aaaa_mm), freq="M")

    def _cumul(annee, mois_max):
        total_rec = total_dep = 0.0
        for mois_num in range(1, mois_max + 1):
            m = f"{annee}{mois_num:02d}"
            centres = ref["centres"]["code_centre"]
            total_rec += sum(recettes_centre_mois(c, m, ref, d) for c in centres)
            total_dep += sum(depenses_centre_mois(c, m, ref, d) for c in centres)
        return total_rec, total_dep

    rec_actuel, dep_actuel = _cumul(fin.year, fin.month)
    rec_precedent, dep_precedent = _cumul(fin.year - 1, fin.month)
    return {
        "periode": f"janvier-{fin.strftime('%m')} {fin.year}",
        "periode_precedente": f"janvier-{fin.strftime('%m')} {fin.year - 1}",
        "recettes": rec_actuel, "depenses": dep_actuel, "resultat_net": rec_actuel - dep_actuel,
        "recettes_annee_precedente": rec_precedent, "depenses_annee_precedente": dep_precedent,
        "resultat_net_annee_precedente": rec_precedent - dep_precedent,
    }


# =============================================================================
# TRESORERIE ET PROJECTIONS (Q33, Q34, Q37)
# =============================================================================

def tresorerie_disponible(centre=None, ref=None, d=None):
    """Solde de tresorerie actuel (toutes caisses/banques de tresorerie
    confondues - voir _journaux_tresorerie), pour un centre donne ou pour
    l'ensemble des centres (Q33). C'est une photo a l'instant present : un
    solde de caisse n'a pas de sens "depuis le debut de l'annee", contrairement
    a un resultat (voir resultat_annee_vs_precedente pour un cumul annuel).

    CP et CMD sont de vraies caisses physiques, une par centre : leur solde
    est ajoute une fois par centre agrege. La banque est un compte unique
    partage par tous les centres (aucun centre n'a "sa part") : son solde
    n'est ajoute qu'une seule fois au total, jamais duplique par centre -
    sinon un total "tous centres" le compterait plusieurs fois."""
    ref = ref or dl.lire_referentiel()
    # Toujours les ecritures de TOUS les centres, meme pour une demande sur
    # un seul centre : la banque est un compte partage dont le solde global
    # a besoin des mouvements de tous les centres pour etre juste (voir
    # solde_caisse/est_caisse_physique) - seul le filtrage par journal plus
    # bas (physique ou non) decide, pour chaque journal, quel sous-ensemble
    # de d compte reellement dans le total.
    d = d if d is not None else dl.lire_ecritures()
    centres = [centre] if centre else list(ref["centres"]["code_centre"])
    jx = ref["journaux"]
    journaux = _journaux_tresorerie(ref)
    if "actif" in jx.columns:
        # Une caisse disponible "maintenant" ne peut pas inclure un journal
        # retire (ex. l'ancienne banque) : contrairement a un rapport
        # historique, cette photo instantanee ne doit refleter que ce qui
        # est reellement utilisable aujourd'hui.
        actifs = set(jx.loc[jx["actif"].fillna("oui") == "oui", "journal"])
        journaux = [j for j in journaux if j in actifs]
    detail = []
    for j in journaux:
        if dl.est_caisse_physique(ref, j):
            for c in centres:
                detail.append({"centre": c, "journal": j, "solde": dl.solde_caisse(j, ref, d, centre=c)})
        else:
            detail.append({"centre": None, "journal": j, "solde": dl.solde_caisse(j, ref, d, centre=None)})
    total = sum(x["solde"] for x in detail)
    return {"detail": detail, "total": total}


def caisse_sous_seuil(centre, journal, seuil, ref=None, d=None):
    """Compare le solde actuel d'une caisse donnee a un seuil fourni par le
    directeur (Q37). Aucun seuil "critique" n'est fixe en dur dans le code :
    ce n'est pas une decision technique, elle doit venir de la question
    posee (ex. "la caisse de Pissy est-elle sous 100000 F ?") ou, a defaut,
    etre demandee explicitement par l'assistant avant de repondre.

    Si journal est un compte partage (la banque, jamais ventile par centre),
    centre est ignore et c'est le solde global qui est compare au seuil."""
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    solde = float(dl.solde_caisse(journal, ref, d, centre=centre))
    return {"centre": centre, "journal": journal, "solde": solde, "seuil": float(seuil),
            "sous_le_seuil": bool(solde < float(seuil))}


def projection_depenses_fixes_mois_prochain(centre=None, ref=None, d=None, nb_mois_historique=3):
    """Projection naive des depenses fixes du mois prochain (masse
    salariale + charges fixes), a partir de la moyenne des
    nb_mois_historique derniers mois clos (Q34). Ce n'est pas un budget
    valide par la direction, seulement une extrapolation mecanique de
    l'historique recent - a presenter comme telle dans la reponse."""
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    if centre:
        d = d[d["centre"] == centre]
    mois_courant = pd.Timestamp.now().strftime("%Y%m")
    fin = pd.Period(mois_precedent(mois_courant), freq="M")
    mois_historique = [(fin - i).strftime("%Y%m") for i in range(nb_mois_historique)]
    masses, charges = [], []
    for m in mois_historique:
        masses.append(part_masse_salariale(m, centre, ref, d)["masse_salariale"])
        charges.append(part_charges_fixes(m, centre, ref, d)["charges_fixes"])
    proj_masse = float(pd.Series(masses).mean()) if masses else 0.0
    proj_charges = float(pd.Series(charges).mean()) if charges else 0.0
    return {
        "mois_historique_utilises": mois_historique,
        "masse_salariale_projetee": proj_masse,
        "charges_fixes_projetees": proj_charges,
        "total_projete": proj_masse + proj_charges,
    }


def recettes_attendues_vs_realisees(centre, mois_aaaa_mm):
    """Q1, Q3, Q4, Q5, Q6, Q7 : necessitent toutes un montant "attendu"
    (nb eleves inscrits x tarif applicable) et/ou un echeancier par eleve,
    qui n'existent pas dans Hakili_compta (pas de grille tarifaire ni de
    table d'inscriptions/echeances a ce jour). Voir recettes_du_mois pour le
    montant reellement encaisse, seule partie de la question qui reste
    repondable."""
    return _indisponible(
        "recettes attendues vs realisees, ecart, taux de recouvrement, retards de paiement",
        "il manque une grille tarifaire par centre/formule et un echeancier par eleve dans "
        "Hakili_compta pour calculer un montant 'attendu' fiable. Le montant reellement "
        "encaisse (sans comparaison a un attendu) reste disponible via recettes_du_mois.",
    )


# =============================================================================
# IMPAYES (Q12-Q15) - categorie marquee indisponible (decision du 06/09/2026)
# =============================================================================

def situation_impayes(centre=None):
    """Categorie marquee indisponible sur decision de la direction
    (06/09/2026) : un solde debiteur du compte 411000 par tiers aurait pu
    servir de proxy (comme effectif_actif_centre_mois l'est deja ailleurs),
    mais la direction a prefere que l'assistant dise clairement qu'il ne
    peut pas repondre plutot que de laisser croire a un chiffre d'impayes
    fiable sans echeancier reel."""
    return _indisponible(
        "impayes en cours, anciennete des retards, plus gros retard",
        "il n'existe pas d'echeancier par eleve dans Hakili_compta - sur decision de la "
        "direction, l'assistant ne doit pas approximer ce chiffre a partir du solde client, "
        "il doit signaler que la donnee n'est pas encore disponible.",
    )


def projection_recettes_mois_prochain(centre=None):
    """Q35 : bloquee par la meme absence de table d'inscriptions/echeances
    que recettes_attendues_vs_realisees - une projection de recettes ne
    peut pas se baser uniquement sur l'historique d'encaissements sans
    savoir qui est reellement inscrit le mois prochain."""
    return _indisponible(
        "projection des recettes du mois prochain",
        "il manque une table d'inscriptions/echeances par eleve pour projeter des recettes a "
        "partir de qui est reellement inscrit, plutot que de l'historique d'encaissements seul.",
    )


def seuil_rentabilite_centre(centre, mois_aaaa_mm=None):
    """Q36 : le seuil de rentabilite (nombre d'eleves payants necessaire
    pour couvrir les charges fixes) suppose un tarif moyen par eleve fiable,
    qui suppose lui-meme la grille tarifaire absente de Hakili_compta."""
    return _indisponible(
        "seuil de rentabilite (nombre d'eleves necessaire pour couvrir les charges fixes)",
        "il manque une grille tarifaire par centre/formule pour deduire un tarif moyen fiable "
        "par eleve ; sans elle, diviser les charges fixes par la 'recette par eleve' proxy "
        "donnerait un chiffre trompeur, pas une vraie grille tarifaire.",
    )


# =============================================================================
# PERSONNEL ET MASSE SALARIALE (Q21-Q24)
# =============================================================================

def vacations_du_mois(mois_aaaa_mm, centre=None, ref=None, d=None):
    """Detail des vacations/remunerations versees sur le mois, tiers par
    tiers (Q21) : regroupe les deux comptes de la masse salariale (voir
    part_masse_salariale) - 422000 (modele remuneration) et 632710 (modele
    vacation) - par code_tiers, avec le libelle du beneficiaire."""
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    if centre:
        d = d[d["centre"] == centre]
    # Lecture sur compte_charge (11/09/2026) : a Hakili Lab les vacations sont
    # reglees par le collectif 401000, jamais par 632710 en direct. Sans cette
    # normalisation, cet outil renvoyait une liste vide tous les mois.
    d = _depenses_du_mois(mois_aaaa_mm, d, ref)
    if len(d) == 0:
        return []
    d = d[d["compte_charge"].isin({COMPTE_PERSONNEL, COMPTE_VACATION}) & (d["code_tiers"] != "")]
    if len(d) == 0:
        return []
    tiers_map = dict(zip(ref["tiers"]["code_tiers"], ref["tiers"]["intitule"])) if len(ref["tiers"]) else {}
    par_tiers = d.groupby("code_tiers")["debit"].sum().sort_values(ascending=False)
    return [{"code_tiers": ct, "beneficiaire": tiers_map.get(ct, ct), "montant": float(m)}
            for ct, m in par_tiers.items()]


def personnel_multi_centres(mois_aaaa_mm=None, nb_mois=3, ref=None, d=None):
    """Tiers de la masse salariale (422000/632710) qui apparaissent sur
    plusieurs centres distincts sur les nb_mois derniers mois se terminant a
    mois_aaaa_mm inclus (Q22), avec leur remuneration cumulee par centre.
    S'appuie sur le fait qu'un tiers (code_tiers) est global au referentiel
    - c'est ecritures.centre, pas tiers, qui varie d'une ligne a l'autre."""
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures()
    fin = pd.Period(mois_fin_ou_courant(mois_aaaa_mm), freq="M")
    mois_liste = {(fin - i).strftime("%Y%m") for i in range(nb_mois)}
    d = lignes_depense(d, ref)
    if len(d) == 0:
        return []
    d = d.copy()
    d["mois"] = pd.to_datetime(d["date_piece"]).dt.strftime("%Y%m")
    d = d[d["mois"].isin(mois_liste) & d["compte_charge"].isin({COMPTE_PERSONNEL, COMPTE_VACATION})
          & (d["code_tiers"] != "")]
    if len(d) == 0:
        return []
    tiers_map = dict(zip(ref["tiers"]["code_tiers"], ref["tiers"]["intitule"])) if len(ref["tiers"]) else {}
    resultat = []
    for code_tiers, grp in d.groupby("code_tiers"):
        centres = grp["centre"].unique()
        if len(centres) < 2:
            continue
        par_centre = grp.groupby("centre")["debit"].sum()
        resultat.append({
            "code_tiers": code_tiers, "beneficiaire": tiers_map.get(code_tiers, code_tiers),
            "centres": sorted(centres.tolist()),
            "remuneration_par_centre": {c: float(m) for c, m in par_centre.items()},
            "remuneration_totale": float(par_centre.sum()),
        })
    return sorted(resultat, key=lambda x: x["remuneration_totale"], reverse=True)


def avances_personnel(centre=None, ref=None, d=None):
    """Solde restant du (debit - credit) sur le compte 422300, tiers par
    tiers : les avances/acomptes au personnel encore en cours (Q23). Un
    solde a zero ou negatif signifie une avance deja remboursee, elle n'est
    pas listee."""
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    if centre:
        d = d[d["centre"] == centre]
    d = d[(d["compte"] == COMPTE_AVANCES_PERSONNEL) & (d["code_tiers"] != "")]
    if len(d) == 0:
        return []
    tiers_map = dict(zip(ref["tiers"]["code_tiers"], ref["tiers"]["intitule"])) if len(ref["tiers"]) else {}
    soldes = d.groupby("code_tiers").apply(lambda g: float(g["debit"].sum() - g["credit"].sum()))
    soldes = soldes[soldes > 0].sort_values(ascending=False)
    return [{"code_tiers": ct, "beneficiaire": tiers_map.get(ct, ct), "solde_du": float(s)}
            for ct, s in soldes.items()]


def cout_vacation_par_eleve(mois_aaaa_mm, ref=None):
    """Masse salariale (voir part_masse_salariale) rapportee a l'effectif
    actif proxy, centre par centre - deuxieme lecture, complementaire au
    cout absolu, pour comparer des centres de tailles differentes (Q24)."""
    ref = ref or dl.lire_referentiel()
    d = dl.lire_ecritures()
    lignes = []
    for centre in ref["centres"]["code_centre"]:
        masse = part_masse_salariale(mois_aaaa_mm, centre, ref, d)["masse_salariale"]
        effectif = effectif_actif_centre_mois(centre, mois_aaaa_mm, d)
        lignes.append({"centre": centre, "masse_salariale": masse, "effectif_proxy": effectif,
                        "cout_par_eleve": (masse / effectif) if effectif else None})
    return _avec_nom_centre(pd.DataFrame(lignes), ref)


# =============================================================================
# CONTROLE - complement (Q40)
# =============================================================================

def ecritures_a_verifier(mois_aaaa_mm=None, centre=None, d=None):
    """Pieces qui restent du travail pour le comptable (Q40) : celles au
    statut 'a_corriger' (renvoyees par le comptable a la caisse, voir
    ecritures.statut) et celles encore sur le compte d'attente 471000 (voir
    montant_a_reclasser). Les deux sont distinctes - une piece 'a_corriger'
    peut ne toucher aucun compte d'attente, et inversement."""
    d = d if d is not None else dl.lire_ecritures(centre=centre, mois=mois_aaaa_mm)
    if centre:
        d = d[d["centre"] == centre]
    if mois_aaaa_mm:
        d = _filtrer_mois(d, mois_aaaa_mm)
    a_corriger = d[d["statut"] == "a_corriger"]["id_piece"].nunique() if "statut" in d.columns else 0
    en_attente = d[d["compte"] == COMPTE_ATTENTE]["id_piece"].nunique()
    return {"pieces_a_corriger": int(a_corriger), "pieces_en_attente_de_reclassement": int(en_attente),
            "total_pieces_a_verifier": int(a_corriger) + int(en_attente)}


# =============================================================================
# RECHERCHE LIBRE / AUDIT (Q42-Q45)
# =============================================================================

LIMITE_RECHERCHE_LIBRE = 200  # evite de renvoyer des milliers de lignes au modele de langage


def transactions_caisse_jour(centre, date_iso, d=None):
    """Toutes les lignes d'ecriture d'un centre pour une date precise
    (AAAA-MM-JJ), tous journaux confondus (Q42)."""
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    d = d[d["centre"] == centre]
    d = d[pd.to_datetime(d["date_piece"]).dt.strftime("%Y-%m-%d") == str(date_iso)]
    if len(d) == 0:
        return []
    cols = ["id_piece", "journal", "compte", "code_tiers", "libelle", "debit", "credit", "statut"]
    return d[cols].head(LIMITE_RECHERCHE_LIBRE).to_dict("records")


def transactions_tiers(code_ou_nom_tiers, mois_aaaa_mm=None, ref=None, d=None):
    """Toutes les lignes d'ecriture d'un tiers precis (eleve, fournisseur,
    enseignant...), identifie par son code exact ou par une recherche sur
    l'intitule (Q43). Si plusieurs tiers correspondent au nom fourni, les
    lignes des candidats sont regroupees mais chaque candidat reste
    identifiable par son code_tiers dans le resultat."""
    ref = ref or dl.lire_referentiel()
    tiers = ref["tiers"]
    valeur = str(code_ou_nom_tiers or "").strip().upper()
    exact = tiers[tiers["code_tiers"].str.upper() == valeur]
    if len(exact):
        codes = set(exact["code_tiers"])
    else:
        par_nom = tiers[tiers["intitule"].str.upper().str.contains(valeur, na=False)]
        codes = set(par_nom["code_tiers"])
    if not codes:
        return []
    d = d if d is not None else dl.lire_ecritures()
    if mois_aaaa_mm:
        d = _filtrer_mois(d, mois_aaaa_mm)
    d = d[d["code_tiers"].isin(codes)]
    if len(d) == 0:
        return []
    cols = ["id_piece", "centre", "date_piece", "journal", "compte", "code_tiers",
            "libelle", "debit", "credit", "statut"]
    return d[cols].sort_values("date_piece").head(LIMITE_RECHERCHE_LIBRE).to_dict("records")


def depenses_superieures_a(montant_min, mois_aaaa_mm=None, centre=None, ref=None, d=None):
    """Lignes de charge (compte de nature 'charge') dont le debit depasse
    montant_min, sur la periode et le centre donnes si precises (Q44)."""
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures(centre=centre, mois=mois_aaaa_mm)
    if centre:
        d = d[d["centre"] == centre]
    if mois_aaaa_mm:
        d = _filtrer_mois(d, mois_aaaa_mm)
    # Meme perimetre que tous les autres indicateurs de depense depuis le
    # 11/09/2026 : sans cela, cette recherche manquait les loyers et les
    # vacations, c'est-a-dire precisement les grosses depenses que la question
    # "montre-moi les depenses superieures a X" cherche a faire ressortir.
    d = lignes_depense(d, ref)
    if len(d) == 0:
        return []
    d = d[d["debit"] > float(montant_min)]
    if len(d) == 0:
        return []
    cols = ["id_piece", "centre", "date_piece", "compte", "compte_charge", "code_tiers",
            "libelle", "debit", "statut"]
    cols = [c for c in cols if c in d.columns]
    return d[cols].sort_values("debit", ascending=False).head(LIMITE_RECHERCHE_LIBRE).to_dict("records")


def detail_ecritures_mois(mois_aaaa_mm, centre=None, d=None):
    """Detail complet des ecritures d'un mois (et centre si precise), pour
    verification par le comptable (Q45). Renvoie les donnees dans le chat
    pour consultation - un export fichier (CSV/Excel) au sens strict reste
    a faire depuis l'onglet Export existant de l'application, pas depuis
    l'assistant conversationnel."""
    d = d if d is not None else dl.lire_ecritures(centre=centre, mois=mois_aaaa_mm)
    if centre:
        d = d[d["centre"] == centre]
    d = _filtrer_mois(d, mois_aaaa_mm)
    if len(d) == 0:
        return {"nombre_lignes": 0, "lignes": [],
                "note": "Aucune ecriture pour cette periode."}
    cols = ["id_piece", "centre", "date_piece", "journal", "compte", "code_tiers",
            "libelle", "debit", "credit", "statut"]
    tronque = len(d) > LIMITE_RECHERCHE_LIBRE
    return {
        "nombre_lignes": int(len(d)),
        "lignes": d[cols].sort_values("date_piece").head(LIMITE_RECHERCHE_LIBRE).to_dict("records"),
        "note": (f"Resultat limite aux {LIMITE_RECHERCHE_LIBRE} premieres lignes ; "
                 "utiliser l'onglet Export pour le detail complet.") if tronque else "",
    }


# =============================================================================
# QUALITE DES DONNEES (ajoute le 11/09/2026)
# =============================================================================

def charges_non_ventilees(mois_aaaa_mm=None, centre=None, ref=None, d=None):
    """Reglements passes par le collectif fournisseur 401000 que
    VENTILATION_REGLEMENTS_FOURNISSEUR n'a pas su rattacher a un compte de
    charge, faute de motif reconnu dans le libelle.

    C'est le residu assume de la reconstitution des charges : ces montants
    comptent bien dans le total des depenses, mais ne sont imputes a aucune
    categorie. Les exposer plutot que de les absorber en silence est ce qui
    rend la reconstitution honnete - la comptable voit exactement ce qui reste
    a arbitrer, et chaque libelle traite ici est un motif a ajouter a la table
    (ou, mieux, une saisie a corriger a la source)."""
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures(centre=centre, mois=mois_aaaa_mm)
    if centre:
        d = d[d["centre"] == centre]
    if mois_aaaa_mm:
        d = _filtrer_mois(d, mois_aaaa_mm)
    dep = lignes_depense(d, ref)
    if len(dep) == 0:
        return {"nombre_lignes": 0, "montant_total": 0.0, "lignes": [],
                "part_des_charges_pct": 0.0}
    total = float(dep["debit"].sum())
    reste = dep[dep["compte_charge"] == COMPTE_FOURNISSEUR]
    montant = float(reste["debit"].sum())
    cols = [c for c in ["id_piece", "centre", "date_piece", "code_tiers", "libelle", "debit"]
            if c in reste.columns]
    return {
        "nombre_lignes": int(len(reste)),
        "montant_total": montant,
        "part_des_charges_pct": (montant / total * 100) if total else 0.0,
        "lignes": reste[cols].sort_values("debit", ascending=False)
                             .head(LIMITE_RECHERCHE_LIBRE).to_dict("records"),
    }


def ecritures_date_douteuse(centre=None, annee_min=None, d=None):
    """Ecritures dont la date de piece est manifestement erronee : anterieure
    a annee_min (par defaut l'annee en cours moins RECUL_ANNEES_DATE_PLAUSIBLE)
    ou posterieure a aujourd'hui.

    Ajoute le 11/09/2026 apres avoir trouve six lignes de ce type dans les
    brouillards reels - dont une "CONTRIBUTION SIAO" de 50 000 F datee du
    16/02/2006 dans l'onglet Fevrier 2026, et 36 000 F de frais de scolarite
    dates du 01/03/2024 dans l'onglet Mars 2026. Ces ecritures ne sont pas
    perdues : elles sortent simplement de toutes les periodes interrogees, donc
    de tous les totaux mensuels, sans que rien ne le signale. Une erreur de
    frappe sur l'annee est silencieuse par nature, c'est ce qui la rend
    dangereuse."""
    d = d if d is not None else dl.lire_ecritures(centre=centre)
    if centre:
        d = d[d["centre"] == centre]
    if d is None or len(d) == 0:
        return {"nombre_pieces": 0, "montant_total": 0.0, "borne_basse": None, "lignes": []}
    aujourdhui = pd.Timestamp.now().normalize()
    borne = pd.Timestamp(year=int(annee_min), month=1, day=1) if annee_min else pd.Timestamp(
        year=aujourdhui.year - RECUL_ANNEES_DATE_PLAUSIBLE, month=1, day=1)
    dates = pd.to_datetime(d["date_piece"], errors="coerce")
    suspectes = d[(dates < borne) | (dates > aujourdhui) | dates.isna()]
    if len(suspectes) == 0:
        return {"nombre_pieces": 0, "montant_total": 0.0,
                "borne_basse": borne.strftime("%Y-%m-%d"), "lignes": []}
    # Une piece = deux lignes equilibrees : le montant de la piece est son
    # debit, pas la somme debit + credit, qui le compterait deux fois.
    cols = [c for c in ["id_piece", "centre", "date_piece", "journal", "compte",
                        "code_tiers", "libelle", "debit", "credit"] if c in suspectes.columns]
    return {
        "nombre_pieces": int(_par_piece(suspectes).nunique()),
        "montant_total": float(suspectes["debit"].sum()),
        "borne_basse": borne.strftime("%Y-%m-%d"),
        "lignes": suspectes[cols].sort_values("date_piece")
                                 .head(LIMITE_RECHERCHE_LIBRE).to_dict("records"),
    }


# =============================================================================
# TRANSFERTS INTERNES ENTRE CENTRES (ajoute le 12/09/2026)
# =============================================================================

COMPTE_VIREMENTS_FONDS = "585000"
MODELE_TRANSFERT_INTERNE = "transfert_interne"

# Au-dela de ce delai, un transfert dont une seule face est enregistree cesse
# d'etre "en transit" pour devenir une anomalie. Reglage de gestion, a fixer
# avec la comptable : les brouillards montrent une remise de janvier
# enregistree le 20 fevrier, donc un delai trop court noierait le comptable
# sous des alertes qui se resolvent seules - et il cesserait de les lire.
DELAI_TRANSIT_JOURS = 30


def transferts_internes(mois_aaaa_mm=None, ref=None, d=None, delai_jours=None):
    """Rapprochement des transferts d'argent entre centres.

    Pourquoi un rapprochement par REFERENCE et pas seulement par le solde du
    compte 585000 : plusieurs transferts peuvent se compenser entre eux. Si
    Pissy et Saaba remettent chacun 50 000 F et que SIAO enregistre deux fois
    la remise de Pissy sans jamais saisir celle de Saaba, le solde du 585000
    tombe juste et l'anomalie passe inapercue. Le solde global reste utile,
    mais comme filet - il attrape ce qui a echappe a la reference (ecriture
    libre, import historique) - jamais comme controle principal.

    Quatre paniers, et surtout TROIS statuts et non deux : "en transit" n'est
    pas une anomalie. Une remise partie il y a trois jours et pas encore
    enregistree a l'arrivee est le fonctionnement normal.
    """
    ref = ref or dl.lire_referentiel()
    d = d if d is not None else dl.lire_ecritures()
    delai = DELAI_TRANSIT_JOURS if delai_jours is None else int(delai_jours)
    vide = {"soldes": [], "en_transit": [], "anomalies": [], "sans_reference": [],
            "resume": {"soldes": 0, "en_transit": 0, "anomalies": 0, "sans_reference": 0},
            "solde_compte_585000": 0.0, "delai_transit_jours": delai}
    if d is None or len(d) == 0:
        return vide

    if "reference_transfert" not in d.columns:
        # Migration 2026-09-12 pas encore appliquee : plutot que de planter,
        # on considere que rien n'est reference. Tous les mouvements de
        # virement de fonds ressortent alors dans le panier "a regulariser",
        # ce qui est exactement leur statut reel.
        d = d.copy()
        d["reference_transfert"] = ""
        d["centre_contrepartie"] = ""
    mvt = d[d["compte"] == COMPTE_VIREMENTS_FONDS].copy()
    if len(mvt) == 0:
        return vide
    if mois_aaaa_mm:
        # Le filtre de periode porte sur la SORTIE : un transfert parti en
        # septembre et recu en octobre appartient a septembre, sinon il
        # paraitrait deseequilibre des deux cotes.
        refs_du_mois = set(_filtrer_mois(mvt[mvt["debit"] > 0], mois_aaaa_mm)["reference_transfert"])
        mvt = mvt[mvt["reference_transfert"].isin(refs_du_mois)]

    solde_global = float(mvt["debit"].sum() - mvt["credit"].sum())
    aujourdhui = pd.Timestamp.now().normalize()

    def _nom(code):
        return dl.nom_centre(ref, code) if code else ""

    # --- panier 4 : ce qui n'a aucune reference ------------------------------
    # L'historique importe et les approvisionnements CP/CMD internes a un
    # centre, qui ne sont pas des transferts entre centres.
    sans_ref = mvt[(mvt["reference_transfert"] == "")
                   & (mvt.get("modele", pd.Series([""] * len(mvt), index=mvt.index)) != MODELE_TRANSFERT_INTERNE)]
    inter_centres_sans_ref = sans_ref[sans_ref["libelle"].str.contains("SIAO|TRANSFERT", case=False, na=False)]
    panier_sans_reference = [{
        "centre": r["centre"], "centre_nom": _nom(r["centre"]),
        "date": str(r["date_piece"]), "libelle": r["libelle"],
        "montant": float(r["debit"] - r["credit"]), "id_piece": str(r["id_piece"]),
    } for _, r in inter_centres_sans_ref.iterrows()]

    # --- paniers 1 a 3 : les transferts references ---------------------------
    soldes, transit, anomalies = [], [], []
    avec_ref = mvt[mvt["reference_transfert"] != ""]
    for reference, lignes in avec_ref.groupby("reference_transfert"):
        sortie = lignes[lignes["debit"] > 0]
        entree = lignes[lignes["credit"] > 0]
        montant_sorti = float(sortie["debit"].sum())
        montant_entre = float(entree["credit"].sum())
        donateur = sortie["centre"].iloc[0] if len(sortie) else ""
        destinataire = (entree["centre"].iloc[0] if len(entree)
                        else (sortie["centre_contrepartie"].iloc[0] if len(sortie) else ""))
        date_sortie = str(sortie["date_piece"].min()) if len(sortie) else ""
        date_entree = str(entree["date_piece"].max()) if len(entree) else ""
        depuis = sortie["date_piece"].min() if len(sortie) else (
            entree["date_piece"].min() if len(entree) else None)
        age = int((aujourdhui - pd.Timestamp(str(depuis))).days) if depuis is not None else 0

        ligne_rap = {
            "reference": reference,
            "centre_donateur": donateur, "centre_donateur_nom": _nom(donateur),
            "centre_destinataire": destinataire, "centre_destinataire_nom": _nom(destinataire),
            "montant_sorti": montant_sorti, "montant_entre": montant_entre,
            "ecart": montant_sorti - montant_entre,
            "date_sortie": date_sortie, "date_entree": date_entree,
            "age_jours": age,
            "nombre_sorties": int(_par_piece(sortie).nunique()) if len(sortie) else 0,
            "nombre_entrees": int(_par_piece(entree).nunique()) if len(entree) else 0,
        }

        if len(sortie) and len(entree) and abs(ligne_rap["ecart"]) < 0.01 \
                and ligne_rap["nombre_sorties"] == 1 and ligne_rap["nombre_entrees"] == 1:
            ligne_rap["statut"] = "solde"
            soldes.append(ligne_rap)
            continue

        if ligne_rap["nombre_entrees"] > 1:
            ligne_rap["statut"] = "anomalie"
            ligne_rap["motif"] = "recu plusieurs fois"
        elif not len(sortie):
            ligne_rap["statut"] = "anomalie"
            ligne_rap["motif"] = "entree sans sortie correspondante"
        elif not len(entree):
            if age <= delai:
                ligne_rap["statut"] = "en_transit"
                ligne_rap["motif"] = f"parti il y a {age} jour(s), pas encore enregistre a l'arrivee"
                transit.append(ligne_rap)
                continue
            ligne_rap["statut"] = "anomalie"
            ligne_rap["motif"] = f"jamais recu apres {age} jours"
        else:
            ligne_rap["statut"] = "anomalie"
            ligne_rap["motif"] = "ecart entre le montant remis et le montant recu"
        anomalies.append(ligne_rap)

    cle = lambda x: (x.get("date_sortie") or "", x["reference"])
    return {
        "soldes": sorted(soldes, key=cle),
        "en_transit": sorted(transit, key=cle),
        "anomalies": sorted(anomalies, key=cle),
        "sans_reference": panier_sans_reference[:LIMITE_RECHERCHE_LIBRE],
        "resume": {"soldes": len(soldes), "en_transit": len(transit),
                    "anomalies": len(anomalies), "sans_reference": len(panier_sans_reference)},
        "solde_compte_585000": solde_global,
        "delai_transit_jours": delai,
        "note": ("Le solde du compte 585000 doit revenir a zero quand tous les transferts "
                 "sont termines. Un solde non nul avec zero anomalie signale un mouvement "
                 "de virement de fonds passe hors du formulaire de transfert."),
    }


def transferts_non_soldes(ref=None, d=None, delai_jours=None):
    """Raccourci pour les verrous : nombre de transferts qui empechent une
    cloture propre (anomalies, plus le solde residuel du compte de passage).
    Utilise par l'onglet Controles et par le blocage de fin d'annee."""
    r = transferts_internes(None, ref, d, delai_jours)
    return {
        "anomalies": r["resume"]["anomalies"],
        "en_transit": r["resume"]["en_transit"],
        "sans_reference": r["resume"]["sans_reference"],
        "solde_compte_585000": r["solde_compte_585000"],
        "cloture_possible": (r["resume"]["anomalies"] == 0
                             and abs(r["solde_compte_585000"]) < 0.01),
    }


# =============================================================================
# PERIODES LIBRES ET ANNEE ACADEMIQUE (ajoute le 11/09/2026)
# =============================================================================

def _mois_entre(date_debut, date_fin):
    debut = pd.Period(pd.Timestamp(str(date_debut)), freq="M")
    fin = pd.Period(pd.Timestamp(str(date_fin)), freq="M")
    if fin < debut:
        debut, fin = fin, debut
    mois, courant = [], debut
    while courant <= fin:
        mois.append(courant.strftime("%Y%m"))
        courant += 1
    return mois


def resultat_periode(date_debut, date_fin, centre=None, ref=None):
    """Recettes, depenses et resultat net entre deux dates (AAAA-MM-JJ
    incluses), pour un centre ou pour l'ensemble.

    Ajoute le 11/09/2026 : jusque-la, tous les outils raisonnaient en mois
    entiers (AAAAMM), en trimestre glissant ou en six mois. Une question aussi
    banale que "combien avons-nous encaisse entre la rentree et les vacances
    de Noel ?" n'avait aucun outil pour y repondre. Le detail mois par mois est
    renvoye en meme temps que le total, ce qui permet d'illustrer la reponse
    sans un second appel."""
    ref = ref or dl.lire_referentiel()
    d = dl.lire_ecritures()
    debut, fin = pd.Timestamp(str(date_debut)), pd.Timestamp(str(date_fin))
    if fin < debut:
        debut, fin = fin, debut
    dates = pd.to_datetime(d["date_piece"], errors="coerce")
    d = d[(dates >= debut) & (dates <= fin)]
    centres = [centre] if centre else list(ref["centres"]["code_centre"])
    detail = []
    for m in _mois_entre(debut, fin):
        rec = sum(recettes_centre_mois(c, m, ref, d) for c in centres)
        dep = sum(depenses_centre_mois(c, m, ref, d) for c in centres)
        detail.append({"mois": m, "recettes": rec, "depenses": dep, "resultat_net": rec - dep})
    total_rec = sum(x["recettes"] for x in detail)
    total_dep = sum(x["depenses"] for x in detail)
    return {
        "date_debut": debut.strftime("%Y-%m-%d"), "date_fin": fin.strftime("%Y-%m-%d"),
        "centre": centre, "recettes": total_rec, "depenses": total_dep,
        "resultat_net": total_rec - total_dep, "detail_mensuel": detail,
        "note": ("Les mois de debut et de fin sont bornes a la date exacte demandee ; "
                 "le detail mensuel les presente donc partiels."),
    }


def annee_academique_de(date_reference=None):
    """Bornes de l'annee academique qui contient la date donnee (aujourd'hui
    si omise) : du 1er septembre au 31 aout. Le mois de bascule est
    MOIS_DEBUT_ANNEE_ACADEMIQUE."""
    ref = pd.Timestamp(str(date_reference)) if date_reference else pd.Timestamp.now()
    annee_debut = ref.year if ref.month >= MOIS_DEBUT_ANNEE_ACADEMIQUE else ref.year - 1
    debut = pd.Timestamp(year=annee_debut, month=MOIS_DEBUT_ANNEE_ACADEMIQUE, day=1)
    fin = pd.Timestamp(year=annee_debut + 1, month=MOIS_DEBUT_ANNEE_ACADEMIQUE, day=1) - pd.Timedelta(days=1)
    return {"libelle": f"{annee_debut}-{annee_debut + 1}",
            "date_debut": debut.strftime("%Y-%m-%d"), "date_fin": fin.strftime("%Y-%m-%d")}


def resultat_annee_academique_vs_precedente(date_reference=None, centre=None, ref=None):
    """Cumul recettes/depenses/resultat de l'annee academique en cours a la
    date donnee, compare a la meme portion de l'annee academique precedente.

    Complement de resultat_annee_vs_precedente, qui raisonne en annee civile.
    L'activite de Hakili Lab suit l'annee scolaire : comparer janvier-aout 2026
    a janvier-aout 2025 melange deux rentrees differentes. Ici, la periode
    comparee va du 1er septembre a la meme date calendaire l'annee d'avant, ce
    qui met bien en regard deux rentrees comparables."""
    ref = ref or dl.lire_referentiel()
    reference = pd.Timestamp(str(date_reference)) if date_reference else pd.Timestamp.now()
    courante = annee_academique_de(reference)
    debut_courant = pd.Timestamp(courante["date_debut"])
    fin_courant = min(reference, pd.Timestamp(courante["date_fin"]))
    decalage = pd.DateOffset(years=1)
    precedente = annee_academique_de(debut_courant - pd.Timedelta(days=1))
    actuel = resultat_periode(debut_courant, fin_courant, centre, ref)
    passe = resultat_periode(debut_courant - decalage, fin_courant - decalage, centre, ref)
    return {
        "annee_academique": courante["libelle"], "periode": f"{actuel['date_debut']} au {actuel['date_fin']}",
        "recettes": actuel["recettes"], "depenses": actuel["depenses"],
        "resultat_net": actuel["resultat_net"],
        "annee_academique_precedente": precedente["libelle"],
        "periode_precedente": f"{passe['date_debut']} au {passe['date_fin']}",
        "recettes_annee_precedente": passe["recettes"],
        "depenses_annee_precedente": passe["depenses"],
        "resultat_net_annee_precedente": passe["resultat_net"],
    }

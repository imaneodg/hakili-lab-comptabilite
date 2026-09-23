# ---------------------------------------------------------------------------
# Dictionnaire des indicateurs : le seul endroit ou l'on dit ce que veut dire
# un chiffre de l'assistant. Cite dans le prompt (via contexte()) et utilise
# par le moteur. Vocabulaire SYSCOHADA : "flux net" est un solde de
# tresorerie, jamais un "resultat".
# ---------------------------------------------------------------------------

from assistant.comprehension import Incomprehension
from assistant.texte import normaliser

# source : flux (tresorerie), charges, attente (471000), ou derive (calcule
# a partir d'autres indicateurs apres agregation).
INDICATEURS = {
    "encaissements": {
        "libelle": "Argent reçu", "unite": "F", "source": "flux",
        "definition": "Argent entre en caisse ou en banque, hors transferts entre caisses et "
                      "entre centres. Inclut les sommes en attente de reclassement (471000)."},
    "decaissements": {
        "libelle": "Argent dépensé", "unite": "F", "source": "flux",
        "definition": "Argent sorti de caisse ou de banque, hors transferts. Inclut ce qui n'est "
                      "pas une charge : avances au personnel, remboursement d'emprunt, equipement."},
    "flux_net": {
        "libelle": "Reste (reçu moins dépensé)", "unite": "F", "source": "derive",
        "definition": "Encaissements - decaissements. C'est un solde de tresorerie, pas un "
                      "resultat comptable."},
    "frais_scolarite": {
        "libelle": "Frais de cours reçus", "unite": "F", "source": "flux",
        "definition": "Encaissements dont la contrepartie est le compte eleves 411000."},
    "autres_encaissements": {
        "libelle": "Autres entrées", "unite": "F", "source": "flux",
        "definition": "Encaissements hors frais de scolarite : frais de dossier, ventes, "
                      "remboursements, emprunts."},
    "produits": {
        "libelle": "Ce que la période a rapporté", "unite": "F", "source": "produits",
        "definition": "Chiffre d'affaires au sens SYSCOHADA : frais de cours (credits du compte "
                      "eleves 411000, encaisses sans facture, rattaches au mois de cours ecrit dans "
                      "le libelle ; avances reparties sur les mois concernes), moins les "
                      "remboursements aux parents, plus les produits de classe 7 (frais de "
                      "dossier et de documents 707810...)."},
    "resultat": {
        "libelle": "Bénéfice", "unite": "F", "source": "derive",
        "definition": "Produits - charges, rattaches au mois de prestation. Resultat avant "
                      "amortissements, provisions et impot ; le resultat officiel est celui arrete "
                      "dans Sage a la cloture."},
    "marge_resultat_pct": {
        "libelle": "Bénéfice pour 100 F rapportés", "unite": "%", "source": "derive",
        "definition": "Resultat de gestion / produits x 100 : la rentabilite d'un centre."},
    "charges": {
        "libelle": "Ce que la période a coûté", "unite": "F", "source": "charges",
        "definition": "Charges de gestion : comptes de classe 6 (nets des avoirs), salaires "
                      "422000, et reglements fournisseurs payes directement (vacations, loyers) "
                      "rattaches a leur categorie et au mois concerne (libelle)."},
    "masse_salariale": {
        "libelle": "Salaires et vacations", "unite": "F", "source": "charges",
        "definition": "Vacations + salaires."},
    "charges_fixes": {
        "libelle": "Dépenses fixes", "unite": "F", "source": "charges",
        "definition": "Loyer + eau + electricite + gardiennage."},
    "marge_pct": {
        "libelle": "Reste pour 100 F reçus", "unite": "%", "source": "derive",
        "definition": "Flux net / encaissements x 100 (base tresorerie). Pour la rentabilite, "
                      "preferer marge_resultat_pct."},
    "part_masse_salariale_pct": {
        "libelle": "Part des salaires et vacations", "unite": "%", "source": "derive",
        "definition": "Masse salariale / charges x 100."},
    "part_charges_fixes_pct": {
        "libelle": "Part des dépenses fixes", "unite": "%", "source": "derive",
        "definition": "Charges fixes / charges x 100."},
    "part_pct": {
        "libelle": "Part du total", "unite": "%", "source": "derive",
        "definition": "Part de chaque ligne dans le total du premier indicateur demande."},
    "eleves_payants": {
        "libelle": "Élèves ayant payé", "unite": "", "source": "flux",
        "definition": "Nombre d'eleves distincts ayant paye sur la periode. Approximation de "
                      "l'effectif : un eleve inscrit qui n'a rien paye n'y figure pas."},
    "encaissement_par_eleve": {
        "libelle": "Moyenne payée par élève", "unite": "F", "source": "derive",
        "definition": "Frais de scolarite / eleves payants."},
    "nb_pieces": {
        "libelle": "Nombre d'opérations", "unite": "", "source": "flux",
        "definition": "Pieces comptables qui portent un encaissement ou un decaissement."},
    "en_attente_471": {
        "libelle": "Opérations à classer", "unite": "F", "source": "attente",
        "definition": "Solde du compte d'attente sur la periode : argent bien recu ou sorti dont "
                      "le compte definitif reste a trouver. Ce n'est pas un manque d'argent."},
}

_SYNONYMES = {
    "recettes": "encaissements", "recette": "encaissements", "entrees": "encaissements",
    "encaisse": "encaissements", "encaissement": "encaissements", "rentrees": "encaissements",
    "revenus": "encaissements", "argent recu": "encaissements", "recu": "encaissements",
    "encaisse ce mois": "encaissements", "entrees d argent": "encaissements",
    "argent depense": "decaissements", "depense ce mois": "decaissements", "paye": "decaissements",
    "sorties d argent": "decaissements", "reste": "flux_net", "difference": "flux_net",
    "ce qu il reste": "flux_net", "rapporte": "produits", "ce que ca a rapporte": "produits",
    "cout": "charges", "ce que ca a coute": "charges", "vacations": "masse_salariale",
    "salaires et vacations": "masse_salariale", "depenses fixes": "charges_fixes",
    "a classer": "en_attente_471", "operations": "nb_pieces", "nombre d operations": "nb_pieces",
    "depenses": "decaissements", "depense": "decaissements", "sorties": "decaissements",
    "decaissement": "decaissements", "decaisse": "decaissements",
    "resultat net": "resultat", "benefice": "resultat", "perte": "resultat",
    "resultat de gestion": "resultat", "gain": "resultat", "rentabilite": "marge_resultat_pct",
    "produit": "produits", "chiffre d affaires": "produits", "ca": "produits",
    "flux net": "flux_net", "solde net": "flux_net", "excedent de tresorerie": "flux_net",
    "flux": "flux_net", "tresorerie nette": "flux_net",
    "scolarite": "frais_scolarite", "frais de scolarite": "frais_scolarite",
    "mensualites": "frais_scolarite", "paiements eleves": "frais_scolarite",
    "charge": "charges", "couts": "charges",
    "salaires": "masse_salariale", "masse salariale": "masse_salariale", "personnel": "masse_salariale",
    "marge": "marge_resultat_pct", "taux de marge": "marge_resultat_pct",
    "marge de tresorerie": "marge_pct",
    "effectif": "eleves_payants", "eleves": "eleves_payants", "nombre d eleves": "eleves_payants",
    "recette par eleve": "encaissement_par_eleve", "part": "part_pct", "contribution": "part_pct",
    "pieces": "nb_pieces", "nombre de pieces": "nb_pieces",
    "471": "en_attente_471", "compte d attente": "en_attente_471", "a reclasser": "en_attente_471",
    "attente": "en_attente_471",
}

# Ce dont chaque indicateur derive a besoin pour etre calcule.
DEPENDANCES = {
    "resultat": ["produits", "charges"],
    "marge_resultat_pct": ["produits", "charges"],
    "flux_net": ["encaissements", "decaissements"],
    "marge_pct": ["encaissements", "decaissements"],
    "part_masse_salariale_pct": ["masse_salariale", "charges"],
    "part_charges_fixes_pct": ["charges_fixes", "charges"],
    "encaissement_par_eleve": ["frais_scolarite", "eleves_payants"],
    "part_pct": [],
}

DIMENSIONS = {
    "centre": "Centre", "mois": "Mois", "semaine": "Semaine", "jour": "Jour",
    "annee_scolaire": "Année scolaire", "categorie": "Type", "compte": "Compte",
    "tiers": "Élève / fournisseur", "journal": "Caisse", "statut": "Statut",
}
DIMENSIONS_TEMPS = ("mois", "semaine", "jour", "annee_scolaire")
_SYNONYMES_DIM = {
    "centres": "centre", "par centre": "centre", "site": "centre",
    "mensuel": "mois", "par mois": "mois", "mois par mois": "mois", "mensuellement": "mois",
    "hebdomadaire": "semaine", "semaines": "semaine", "journalier": "jour", "jours": "jour",
    "date": "jour", "quotidien": "jour",
    "categories": "categorie", "poste": "categorie", "postes": "categorie", "nature": "categorie",
    "type": "categorie", "types": "categorie", "type de depense": "categorie",
    "type de recette": "categorie", "espece": "journal", "especes": "journal",
    "comptes": "compte", "eleve": "tiers", "eleves": "tiers", "fournisseur": "tiers",
    "beneficiaire": "tiers", "personne": "tiers", "enseignant": "tiers",
    "caisse": "journal", "journaux": "journal", "caisses": "journal",
    "annee": "annee_scolaire",
}


def resoudre_indicateurs(valeurs):
    """['recettes', 'depenses'] -> ['encaissements', 'decaissements']."""
    if valeurs is None or valeurs == "" or valeurs == []:
        return ["encaissements"]
    if isinstance(valeurs, str):
        valeurs = [v for v in valeurs.replace(";", ",").split(",")]
    res = []
    for v in valeurs:
        n = normaliser(v).replace(" pct", "_pct").replace(" ", "_")
        brut = normaliser(v)
        code = n if n in INDICATEURS else _SYNONYMES.get(brut)
        if code is None:
            from rapidfuzz import fuzz, process
            choix = list(INDICATEURS) + list(_SYNONYMES)
            r = process.extractOne(brut, choix, scorer=fuzz.WRatio, score_cutoff=85)
            code = (r[0] if r[0] in INDICATEURS else _SYNONYMES[r[0]]) if r else None
        if code is None:
            raise Incomprehension("indicateur_inconnu", f"Indicateur non reconnu : « {v} ».",
                                  list(INDICATEURS))
        if code not in res:
            res.append(code)
    return res


def resoudre_dimensions(valeurs):
    if not valeurs:
        return []
    if isinstance(valeurs, str):
        valeurs = [v for v in valeurs.replace(";", ",").split(",")]
    res = []
    for v in valeurs:
        n = normaliser(v)
        code = n if n in DIMENSIONS else _SYNONYMES_DIM.get(n)
        if code is None:
            raise Incomprehension("regroupement_inconnu", f"Regroupement non reconnu : « {v} ».",
                                  list(DIMENSIONS))
        if code not in res:
            res.append(code)
    if len(res) > 2:
        raise Incomprehension("trop_de_regroupements",
                              "Deux regroupements au maximum (ex. centre et mois).")
    return res


def resume_pour_modele():
    return {k: f"{v['libelle']} ({v['unite'] or 'nombre'}) : {v['definition']}"
            for k, v in INDICATEURS.items()}

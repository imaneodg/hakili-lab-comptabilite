# ---------------------------------------------------------------------------
# Modeles d'operation
#
# Un modele decrit une operation telle que la caisse la vit ("un eleve paie
# ses frais"), pas telle que la comptabilite l'ecrit. L'application se charge
# de la traduction en debit / credit.
#
# Pour ajouter un modele : copier un bloc, changer l'identifiant, les champs
# et la fonction lignes(). Rien d'autre a modifier dans l'application.
#
# Champs disponibles : "tiers", "compte", "libelle", "texte", "montant",
#                      "mois", "oui_non"
#
# Port Python (depuis R/modeles.R) : 13 modeles, memes comptes, meme
# traduction debit/credit.
# ---------------------------------------------------------------------------

import re

import pandas as pd

MOIS_FR = ["JANVIER", "FEVRIER", "MARS", "AVRIL", "MAI", "JUIN", "JUILLET",
           "AOUT", "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DECEMBRE"]


# Ramene une valeur d'entree a une seule valeur exploitable.
# Un champ Shiny non encore rendu vaut None, un selectize vide peut valoir
# une chaine vide, un input_numeric efface vaut None : les trois doivent
# donner la valeur par defaut, sinon la construction de la ligne echoue.
def un(x, defaut=""):
    if x is None:
        return defaut
    if isinstance(x, (list, tuple)):
        x = x[0] if len(x) else None
        if x is None:
            return defaut
    if isinstance(x, float) and pd.isna(x):
        return defaut
    if isinstance(x, str) and x == "":
        return defaut
    return x


# Fabrique une ligne d'ecriture.
def ligne(compte, libelle, debit=0, credit=0, code_tiers=""):
    return {
        "compte": str(un(compte)),
        "code_tiers": str(un(code_tiers)),
        "libelle": str(un(libelle))[:60].upper(),
        "debit": float(un(debit, 0) or 0),
        "credit": float(un(credit, 0) or 0),
    }


def _df(*lignes_):
    return pd.DataFrame(list(lignes_))


# Compte d'attente (SYSCOHADA) : pivot systematique de "Ecriture libre" sur
# les journaux de ventes/achats, exactement comme la caisse est le pivot
# systematique sur les journaux de tresorerie. Doit correspondre a la ligne
# ajoutee dans referentiel.xlsx (onglet comptes) et au controle de
# donnees.py qui signale toute piece qui le touche.
COMPTE_ATTENTE = "471000"


MODELES = [

    {
        "id": "encaissement",
        "titre": "Encaissement de frais de scolarite",
        "aide": "53 % des pieces de 2024-2025",
        "journal": "CP",
        "champs": [
            {"n": "tiers", "l": "Eleve (compte 411)", "t": "tiers", "pref": "411", "collectif": "411000"},
            {"n": "mois", "l": "Mois concerne", "t": "mois"},
            {"n": "montant", "l": "Montant recu", "t": "montant"},
        ],
        "libelle": lambda v: f"FRAIS CA {v.get('tiers_nom', '')}/{v.get('mois', '')}",
        "lignes": lambda v, cc: _df(
            ligne(cc, v["lib"], debit=v["montant"]),
            ligne("411000", v["lib"], credit=v["montant"], code_tiers=v.get("tiers", "")),
        ),
    },

    {
        "id": "document",
        "titre": "Frais de document",
        "aide": "Attestation, bulletin, dossier",
        "journal": "CP",
        "champs": [
            {"n": "eleve", "l": "Nom de l'eleve", "t": "texte"},
            {"n": "montant", "l": "Montant recu", "t": "montant"},
        ],
        "libelle": lambda v: f"FRAIS DE DOCUMENT {v.get('eleve', '')}",
        "lignes": lambda v, cc: _df(
            ligne(cc, v["lib"], debit=v["montant"]),
            ligne("707810", v["lib"], credit=v["montant"]),
        ),
    },

    {
        "id": "approvisionnement",
        "titre": "Approvisionnement de la CMD",
        "aide": "Sortie de la caisse principale, entree en menues depenses",
        "journal": "CP",
        # Operation liee : elle produit toujours les deux pieces, une par
        # journal. Une caisse ne peut pas s'approvisionner sans que l'autre
        # baisse. Le sens est toujours le meme : la principale alimente les
        # menues depenses (596 pieces dans l'historique, jamais l'inverse).
        "lie": "CMD",
        "champs": [
            {"n": "montant", "l": "Montant transfere", "t": "montant"},
        ],
        "libelle": lambda v: "APPROV CMD",
        "lignes": lambda v, cc: (
            _df(ligne("585000", v["lib"], debit=v["montant"]),
                ligne("571100", v["lib"], credit=v["montant"]))
            if cc == "571100" else
            _df(ligne("571200", v["lib"], debit=v["montant"]),
                ligne("585000", v["lib"], credit=v["montant"]))
        ),
    },

    {
        "id": "versement_banque",
        "titre": "Versement d'especes en banque",
        "aide": "Avec le droit de timbre",
        "journal": "CP",
        # L'argent sort de la caisse et entre en banque : les deux pieces sont
        # solidaires, exactement comme l'approvisionnement de la CMD. Le
        # comptable ecrivait deja les deux a la main (l'historique montre 257 M
        # sortis de CP contre 258 M entres en CMD + banque, a 0,4 % pres) ;
        # l'application les produit desormais ensemble, ce qui est la seule
        # facon pour le compte pivot 585000 de se solder a zero.
        "lie": "BDU-BF",
        "champs": [
            {"n": "montant", "l": "Montant verse", "t": "montant"},
            {"n": "timbre", "l": "Timbre (646200)", "t": "montant", "defaut": 50},
        ],
        "libelle": lambda v: "VERSEMENT D'ESPECES EN BANQUE",
        "lignes": lambda v, cc: (
            # Cote caisse : le timbre est paye en plus du montant verse.
            _df(ligne("585000", v["lib"], debit=v["montant"]),
                ligne("646200", f"TIMBR/{v['lib']}", debit=v["timbre"]),
                ligne(cc, v["lib"], credit=v["montant"] + v["timbre"]))
            if cc == "571100" else
            # Cote banque : seul le montant verse entre en compte.
            _df(ligne(cc, v["lib"], debit=v["montant"]),
                ligne("585000", v["lib"], credit=v["montant"]))
        ),
    },

    {
        "id": "depense",
        "titre": "Depense courante",
        "aide": "Carburant, impression, entretien, eau...",
        "journal": "CMD",
        "champs": [
            # "filtre": "depense_courante" -> seuls les comptes de charge
            # reellement recurrents (colonne dediee du referentiel) sont
            # proposes ici. Un compte a tiers obligatoire (411/401/422) n'y
            # figure jamais : ce modele n'a pas de champ pour le code tiers,
            # une depense courante n'en a jamais besoin. Un cas rare ou
            # different passe par "Ecriture libre", qui reste sans filtre.
            {"n": "compte", "l": "Nature de la depense", "t": "compte", "filtre": "depense_courante"},
            {"n": "libelle", "l": "Libelle de l'operation", "t": "libelle"},
            {"n": "montant", "l": "Montant paye", "t": "montant"},
        ],
        "libelle": lambda v: v.get("libelle", ""),
        "lignes": lambda v, cc: _df(
            ligne(v["compte"], v["lib"], debit=v["montant"]),
            ligne(cc, v["lib"], credit=v["montant"]),
        ),
    },

    {
        "id": "fournisseur",
        "titre": "Reglement d'un fournisseur",
        "aide": "Compte 401, timbre eventuel",
        "journal": "CMD",
        "champs": [
            {"n": "tiers", "l": "Fournisseur (compte 401)", "t": "tiers", "pref": "401", "collectif": "401000"},
            {"n": "libelle", "l": "Libelle de l'operation", "t": "libelle"},
            {"n": "montant", "l": "Montant paye", "t": "montant"},
            {"n": "timbre", "l": "Timbre (646200)", "t": "montant", "defaut": 0},
        ],
        "libelle": lambda v: v.get("libelle", ""),
        "lignes": lambda v, cc: _lignes_fournisseur(v, cc),
    },

    {
        "id": "remuneration",
        "titre": "Salaire ou vacation",
        "aide": "Un compte personnel par employe (comme les tiers 411/401)",
        "journal": "CMD",
        "champs": [
            # Meme mecanique que "tiers" : liste existante + saisie libre pour
            # un nouveau professeur ou une nouvelle vacation. Chaque personne
            # garde son propre code (422NOM), jamais regroupee avec les
            # autres sur un compte generique unique - c'est ce que montre le
            # vrai plan Sage (des comptes nominatifs existent deja : 422100,
            # 422200...). Le collectif 422000 les regroupe comptablement sans
            # les confondre, exactement comme 411000 pour les eleves.
            {"n": "personnel", "l": "Beneficiaire (professeur, vacataire, employe)",
             "t": "tiers", "pref": "422", "collectif": "422000"},
            {"n": "mois", "l": "Mois concerne", "t": "mois"},
            {"n": "montant", "l": "Montant paye", "t": "montant"},
        ],
        "libelle": lambda v: f"REMUNERATION {v.get('mois', '')}/{v.get('personnel_nom', '')}",
        "lignes": lambda v, cc: _df(
            ligne("422000", v["lib"], debit=v["montant"], code_tiers=v.get("personnel", "")),
            ligne(cc, v["lib"], credit=v["montant"]),
        ),
    },

    # --- journal BDU-BF (banque) ------------------------------------------
    # Les deux modeles ci-dessous reprennent ce que l'historique montre du
    # journal de banque : 52 % de reglements fournisseurs et 21 % de versements
    # d'especes (deja couverts par le modele precedent), puis les frais
    # bancaires et les reglements d'impots et de retenues.

    {
        "id": "fournisseur_banque",
        "titre": "Reglement d'un fournisseur par banque",
        "aide": "Virement ou cheque - 52 % des pieces de banque",
        "journal": "BDU-BF",
        "champs": [
            {"n": "tiers", "l": "Fournisseur (compte 401)", "t": "tiers", "pref": "401", "collectif": "401000"},
            {"n": "libelle", "l": "Libelle de l'operation", "t": "libelle"},
            {"n": "montant", "l": "Montant paye", "t": "montant"},
        ],
        "libelle": lambda v: v.get("libelle", ""),
        "lignes": lambda v, cc: _df(
            ligne("401000", v["lib"], debit=v["montant"], code_tiers=v.get("tiers", "")),
            ligne(cc, v["lib"], credit=v["montant"]),
        ),
    },

    {
        "id": "frais_bancaires",
        "titre": "Frais bancaires ou reglement d'impot",
        "aide": "Agios, commissions, IUTS, IRF, TPA",
        "journal": "BDU-BF",
        "champs": [
            # Liste courte et fermee : ce sont les seuls comptes que le journal
            # de banque utilise en dehors des fournisseurs et des versements.
            # Un cas different passe par "Ecriture libre".
            {"n": "compte", "l": "Nature", "t": "compte",
             "choix": ["631800", "447100", "447200", "447800", "447810"]},
            {"n": "libelle", "l": "Libelle de l'operation", "t": "libelle"},
            {"n": "montant", "l": "Montant", "t": "montant"},
        ],
        "libelle": lambda v: v.get("libelle", ""),
        "lignes": lambda v, cc: _df(
            ligne(v["compte"], v["lib"], debit=v["montant"]),
            ligne(cc, v["lib"], credit=v["montant"]),
        ),
    },

    # --- journal VTE (ventes) ---------------------------------------------
    # La facture cree la creance ; l'encaissement en caisse la solde plus tard.
    # C'est le deuxieme journal de la maison : 96 % de ses pieces tiennent dans
    # ce seul modele. Aucune ligne de tresorerie ici, c'est normal - une facture
    # n'encaisse rien.

    {
        "id": "facture",
        "titre": "Facture de cours d'appui",
        "aide": "96 % des pieces de vente",
        "journal": "VTE",
        "champs": [
            {"n": "tiers", "l": "Eleve (compte 411)", "t": "tiers", "pref": "411", "collectif": "411000"},
            # Les trois produits reellement utilises, repris du plan Sage.
            {"n": "compte", "l": "Prestation facturee", "t": "compte",
             "choix": ["706110", "706120", "706130"]},
            {"n": "numero", "l": "N* de la facture", "t": "texte"},
            {"n": "montant", "l": "Montant facture", "t": "montant"},
        ],
        # Reproduit exactement la forme utilisee depuis 2020 :
        # FACT N*057/NOV/21 ZABRE DALIA
        "libelle": lambda v: (
            f"FACT N*{str(v.get('numero', '')).strip()}/{str(v.get('_mois', ''))[:3]}/"
            f"{v.get('_annee', '')} {v.get('tiers_nom', '')}"),
        "lignes": lambda v, cc: _df(
            ligne("411000", v["lib"], debit=v["montant"], code_tiers=v.get("tiers", "")),
            ligne(v["compte"], v["lib"], credit=v["montant"]),
        ),
    },

    # --- journal ACH (achats) ---------------------------------------------
    # La facture cree la dette ; le reglement en caisse ou en banque la solde
    # plus tard. La moitie du journal est faite d'etats de vacation : c'est la
    # contrepartie comptable des 89 professeurs payes a la vacation.

    {
        "id": "vacation",
        "titre": "Etat de vacation",
        "aide": "50 % des pieces d'achat - retenue de 2 % automatique",
        "journal": "ACH",
        "champs": [
            {"n": "tiers", "l": "Vacataire (compte 401)", "t": "tiers", "pref": "401", "collectif": "401000"},
            {"n": "mois", "l": "Mois de la vacation", "t": "mois"},
            {"n": "montant", "l": "Montant brut de l'etat", "t": "montant"},
        ],
        # Forme dominante dans l'historique : ETAT VACATION AVRIL/ISSOUFOU
        # (1199 occurrences, contre 79 sans le nom du vacataire).
        "libelle": lambda v: f"ETAT VACATION {v.get('mois', '')}/{v.get('tiers_nom', '')}",
        "lignes": lambda v, cc: _lignes_vacation(v),
    },

    {
        "id": "achat",
        "titre": "Facture fournisseur",
        "aide": "Loyer, gardiennage, eau, electricite, internet",
        "journal": "ACH",
        "champs": [
            {"n": "tiers", "l": "Fournisseur (compte 401)", "t": "tiers", "pref": "401", "collectif": "401000"},
            {"n": "compte", "l": "Nature de la charge", "t": "compte",
             "choix": ["622200", "632720", "605100", "605200", "624330", "628820",
                       "633000", "627210", "604100", "605300", "605500"]},
            {"n": "libelle", "l": "Libelle de l'operation", "t": "libelle"},
            {"n": "montant", "l": "Montant brut de la facture", "t": "montant"},
            # Retenue laissee au montant plutot qu'a un taux : sur les loyers,
            # l'historique montre des taux qui varient (9,0 % a 9,9 % selon les
            # pieces), donc aucun calcul automatique ne serait fidele. Le
            # compte de retenue, lui, se deduit de la nature de la charge.
            {"n": "retenue", "l": "Retenue a la source (0 si aucune)", "t": "montant", "defaut": 0},
        ],
        "libelle": lambda v: v.get("libelle", ""),
        "lignes": lambda v, cc: _lignes_achat(v),
    },

    {
        # Soupape de securite unique : un seul item dans le menu, toujours au
        # meme endroit. Les questions posees dependent silencieusement du
        # journal deja choisi (voir resoudre_variante) - la caissiere n'a
        # jamais besoin de savoir qu'il existe deux variantes en dessous, et
        # jamais de mot technique (debit/credit) dans aucune des deux.
        #
        # Sur caisse/banque (CP, CMD, BDU-BF) : le compte de caisse est
        # calcule automatiquement via cc, exactement comme pour tous les
        # autres modeles de ces journaux - jamais choisi a la main.
        #
        # Sur ventes/achats (VTE, ACH) : aucune caisse ne bouge, donc pas de
        # cc naturel - mais on se donne le meme pivot que la caisse, le
        # compte d'attente 471000, systematiquement de l'autre cote. Deux
        # raisons a ce choix plutot que de laisser choisir les deux comptes
        # librement : (1) deux comptes libres permettent d'inverser le sens
        # d'une operation sans qu'aucun controle ne le detecte, l'ecriture
        # restant equilibree dans les deux cas ; (2) avec le pivot, toute
        # ecriture libre de ce type touche 471000 et se retrouve donc
        # automatiquement signalee "a reclasser" dans les Controles - avec
        # deux comptes reels librement choisis, une telle ecriture pouvait
        # passer inapercue. Un vrai reclassement entre deux comptes existants
        # deja identifies releve du comptable dans Sage, pas de cet ecran.
        "id": "libre",
        "titre": "Ecriture libre",
        "aide": "Pour un cas qu'aucun autre modele ne couvre - s'adapte au journal choisi",
        "journal": None,
        "champs_par_type": {
            "tresorerie": [
                {"n": "sens", "l": "Sens du mouvement", "t": "choix",
                 "options": {"entree": "Entree (la caisse recoit)", "sortie": "Sortie (la caisse paie)"}},
                {"n": "compte", "l": "Autre compte (471000 si vous ne savez pas encore)",
                 "t": "compte", "exclut": "tiers_obligatoire"},
                {"n": "libelle", "l": "Libelle de l'operation", "t": "libelle"},
                {"n": "montant", "l": "Montant", "t": "montant"},
            ],
            "operations": [
                {"n": "sens", "l": "Sens du mouvement", "t": "choix",
                 "options": {"entree": "Ce compte recoit la valeur", "sortie": "Ce compte donne la valeur"}},
                {"n": "compte", "l": "Compte concerne (471000 si vous ne savez pas encore)",
                 "t": "compte", "exclut": "tiers_obligatoire"},
                {"n": "libelle", "l": "Libelle de l'operation", "t": "libelle"},
                {"n": "montant", "l": "Montant", "t": "montant"},
            ],
        },
        "libelle": lambda v: v.get("libelle", ""),
        "lignes_par_type": {
            "tresorerie": lambda v, cc: _df(
                ligne(cc, v["lib"], debit=v["montant"]) if v["sens"] == "entree"
                else ligne(v["compte"], v["lib"], debit=v["montant"]),
                ligne(v["compte"], v["lib"], credit=v["montant"]) if v["sens"] == "entree"
                else ligne(cc, v["lib"], credit=v["montant"]),
            ),
            "operations": lambda v, cc: _df(
                ligne(v["compte"], v["lib"], debit=v["montant"]) if v["sens"] == "entree"
                else ligne(COMPTE_ATTENTE, v["lib"], debit=v["montant"]),
                ligne(COMPTE_ATTENTE, v["lib"], credit=v["montant"]) if v["sens"] == "entree"
                else ligne(v["compte"], v["lib"], credit=v["montant"]),
            ),
        },
    },
]


# Le compte de retenue se deduit de la nature de la charge : c'est ce que
# montre l'historique, une charge donnee va toujours avec la meme retenue.
# Vacations -> 2 %, gardiennage -> 5 %, loyers -> retenue IRF.
RETENUE_DE = {"632710": "447810", "632720": "447820", "622200": "447800"}

TAUX_VACATION = 0.02


# Un etat de vacation est un seul geste en deux ou trois lignes : la charge en
# brut, la retenue de 2 %, et le net qui reste du au vacataire. Le comptable
# ecrit toujours les deux libelles jumeles.
def _lignes_vacation(v):
    brut = float(v["montant"])
    retenue = round(brut * TAUX_VACATION)
    L = _df(ligne("632710", v["lib"], debit=brut))
    if retenue > 0:
        L = pd.concat([L, _df(ligne("447810", f"RETENUE 2%/{v['lib']}", credit=retenue))],
                      ignore_index=True)
    L = pd.concat([L, _df(ligne("401000", v["lib"], credit=brut - retenue,
                                code_tiers=v.get("tiers", "")))], ignore_index=True)
    return L


def _lignes_achat(v):
    brut = float(v["montant"])
    retenue = float(v.get("retenue") or 0)
    if retenue >= brut:
        return None
    compte = str(v["compte"])
    L = _df(ligne(compte, v["lib"], debit=brut))
    if retenue > 0:
        cpt_ret = RETENUE_DE.get(compte, "447800")
        L = pd.concat([L, _df(ligne(cpt_ret, f"RETENUE/{v['lib']}", credit=retenue))],
                      ignore_index=True)
    L = pd.concat([L, _df(ligne("401000", v["lib"], credit=brut - retenue,
                                code_tiers=v.get("tiers", "")))], ignore_index=True)
    return L


def _lignes_fournisseur(v, cc):
    L = _df(ligne("401000", v["lib"], debit=v["montant"], code_tiers=v.get("tiers", "")))
    if v["timbre"] > 0:
        L = pd.concat([L, _df(ligne("646200", f"TIMBR/{v['lib']}", debit=v["timbre"]))], ignore_index=True)
    L = pd.concat([L, _df(ligne(cc, v["lib"], credit=v["montant"] + v["timbre"]))], ignore_index=True)
    return L


def modele_par_id(id_):
    for m in MODELES:
        if m["id"] == id_:
            return m
    return None


# Un journal de tresorerie (caisse ou banque) a toujours un compte de
# contrepartie fixe dans le referentiel ; un journal d'operations (ventes,
# achats) n'en a pas - ses deux comptes sont "reels" et jamais automatiques.
# Fonction publique : app.py s'en sert aussi, pour savoir quelles questions
# poser dans le formulaire avant meme de tenter de construire l'ecriture.
def est_tresorerie(journal, journaux_ref):
    journaux = journaux_ref
    if isinstance(journaux_ref, dict) and "journaux" in journaux_ref:
        journaux = journaux_ref["journaux"]
    if "type" not in journaux.columns:
        return True
    t = journaux.loc[journaux["journal"] == journal, "type"]
    return (len(t) == 0) or (str(un(t.iloc[0], "tresorerie")) == "tresorerie")


# La plupart des modeles n'ont qu'une seule facon de se remplir (m["champs"],
# m["lignes"]). "Ecriture libre" est le seul a en avoir deux
# (champs_par_type / lignes_par_type) : le journal deja choisi decide
# laquelle s'applique, silencieusement - la caissiere n'a jamais a savoir
# que deux variantes existent, un seul modele lui suffit a retenir.
def resoudre_variante(m, journal, journaux_ref):
    if "champs_par_type" not in m:
        return m["champs"], m["lignes"]
    cle = "tresorerie" if est_tresorerie(journal, journaux_ref) else "operations"
    return m["champs_par_type"][cle], m["lignes_par_type"][cle]


# Construit les lignes d'ecriture d'un modele a partir des valeurs saisies.
# Renvoie None si l'operation n'est pas encore renseignee.
def construire_lignes(id_modele, valeurs, journal, journaux_ref):
    m = modele_par_id(id_modele)
    if m is None:
        return None

    # Tolere qu'on passe le referentiel complet plutot que le seul onglet des
    # journaux, comme la version R.
    journaux = journaux_ref
    if isinstance(journaux_ref, dict) and "journaux" in journaux_ref:
        journaux = journaux_ref["journaux"]
    if "compte_contrepartie" not in journaux.columns:
        raise ValueError("Referentiel des journaux invalide : colonne compte_contrepartie absente.")

    ligne_cc = journaux.loc[journaux["journal"] == journal, "compte_contrepartie"]
    if not len(ligne_cc):
        return None
    cc = un(ligne_cc.iloc[0])
    # Un journal de tresorerie a toujours un compte de contrepartie : sans lui,
    # l'ecriture n'est pas constructible. Un journal d'operations (ventes,
    # achats) n'en a pas, et ne doit pas en avoir - ses modeles ecrivent leurs
    # deux comptes eux-memes.
    tres = est_tresorerie(journal, journaux)
    if tres and not cc:
        return None
    champs, fn_lignes = resoudre_variante(m, journal, journaux)

    # Toutes les valeurs saisies sont ramenees a une valeur unique et du bon type.
    v = dict(valeurs)
    for ch in champs:
        if ch["t"] == "montant":
            v[ch["n"]] = float(un(v.get(ch["n"]), 0) or 0)
        else:
            v[ch["n"]] = str(un(v.get(ch["n"]), ""))

    # Un compte non encore choisi : l'ecriture n'est pas constructible.
    for ch in champs:
        if ch["t"] == "compte" and not v[ch["n"]]:
            return None

    # Nom d'affichage de chaque champ "tiers" (eleve, fournisseur, personnel...) :
    # repris de la valeur deja calculee par l'interface (nom reel trouve dans le
    # referentiel ou nom fraichement tape), sinon deduit du code en secours.
    for ch in champs:
        if ch["t"] == "tiers":
            cle = f"{ch['n']}_nom"
            v[cle] = str(un(v.get(cle), re.sub(r"^\d{3}", "", str(un(v.get(ch["n"]), "")))))
    v["lib"] = str(un(m["libelle"](v), "")).strip().upper()
    if not v["lib"]:
        return None
    if not (float(un(v.get("montant"), 0) or 0) > 0):
        return None

    try:
        L = fn_lignes(v, cc)
    except Exception:
        return None
    if L is None or len(L) == 0:
        return None
    L = L[(L["compte"] != "") & (L["compte"].notna())]
    if len(L) == 0:
        return None
    return L.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Une operation peut donner naissance a plusieurs pieces : c'est le cas du
# transfert entre les deux caisses, ou le debit de l'une n'a de sens qu'avec
# le credit de l'autre. Les deux pieces sont ensuite enregistrees, validees,
# exportees et supprimees ensemble.
# ---------------------------------------------------------------------------

def construire_operation(id_modele, valeurs, journal, journaux_ref):
    m = modele_par_id(id_modele)
    if m is None:
        return None
    journaux = journaux_ref
    if isinstance(journaux_ref, dict) and "journaux" in journaux_ref:
        journaux = journaux_ref["journaux"]

    L = construire_lignes(id_modele, valeurs, journal, journaux_ref)
    if L is None:
        return None
    op = [{"journal": journal, "lignes": L}]

    # "lie" nomme explicitement le journal de la contrepartie. Tant qu'il n'y
    # avait que deux caisses, "l'autre journal" suffisait ; des qu'un troisieme
    # journal existe (la banque), il faut dire lequel, sinon l'approvisionnement
    # de la CMD irait chercher la banque au hasard de l'ordre du referentiel.
    autre = m.get("lie")
    if autre:
        if autre == journal or autre not in set(journaux["journal"]):
            return None
        L2 = construire_lignes(id_modele, valeurs, autre, journaux_ref)
        if L2 is None:
            return None
        op.append({"journal": autre, "lignes": L2})
    return op


# Une piece qui debite et credite le meme compte AVEC LE MEME TIERS ne bouge
# rien : les deux lignes s'annulent. Le tiers fait partie du test, et ce n'est
# pas un detail : dans le vrai Sage, le comptable ecrit couramment plusieurs
# lignes sur 411000 dans une meme piece, avec un eleve different sur chacune
# (soldes d'eleves regroupes, parent qui regle pour un autre enfant). Comparer
# les seuls numeros de compte refuserait ces operations legitimes.
def comptes_annules(op):
    doubles = set()
    for p in op or []:
        L = p["lignes"]
        cle = L["compte"] + "|" + L["code_tiers"]
        d = set(cle[L["debit"] > 0])
        c = set(cle[L["credit"] > 0])
        doubles |= (d & c)
    return sorted(x.split("|")[0] for x in doubles)


# L'operation entiere est equilibree si chacune de ses pieces l'est.
def operation_equilibree(op):
    if not op:
        return False
    for p in op:
        L = p["lignes"]
        if len(L) == 0:
            return False
        if round(L["debit"].sum()) != round(L["credit"].sum()):
            return False
        if L["debit"].sum() <= 0:
            return False
    return True

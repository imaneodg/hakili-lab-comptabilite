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
#                      "mois", "oui_non", "choix", "repartition" (pas un
#                      widget simple : plusieurs lignes mois/nature/montant
#                      construites dynamiquement par l'interface, cf.
#                      "encaissement" et app.py/m_bloc_repartition)
#
# Port Python (depuis R/modeles.R) : 13 modeles, memes comptes, meme
# traduction debit/credit.
# ---------------------------------------------------------------------------

import logging
import re

import pandas as pd

# Journal des echecs de construction de ligne (voir construire_lignes,
# ajoute le 10/09/2026) - meme processus que logic.donnees, un seul
# logging.basicConfig au point d'entree (app.py / mcp_server) configure les
# handlers pour tous les loggers "hakili.*".
logger = logging.getLogger("hakili.modeles")

MOIS_FR = ["JANVIER", "FEVRIER", "MARS", "AVRIL", "MAI", "JUIN", "JUILLET",
           "AOUT", "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DECEMBRE"]

# Longueur maximale d'un libelle applique par ligne() ci-dessous - purement
# une convention applicative (ecritures.libelle est un `text` Postgres sans
# limite), reprise ici pour que les fonctions qui composent un libelle avec
# un suffixe "/MOIS" (voir _libelle_avec_mois) puissent reserver la place du
# suffixe sans dupliquer le nombre en dur.
LIBELLE_MAX = 60

# Libelle complet (spec 2026) selon la nature d'une ligne de reglement du
# formulaire "encaissement" - utilise par _libelle_frais_ca(), qui compose
# "BASE DE MOIS - NOM".
LIBELLES_NATURE_CA = {
    "frais": "FRAIS DE COURS D'APPUI",
    "avance": "AVANCE DE FRAIS DE COURS D'APPUI",
    "solde": "RATTRAPAGE DE FRAIS DE COURS D'APPUI",
}

# Mois dont le nom commence par une voyelle : elision ("D'AVRIL", jamais
# "DE AVRIL").
MOIS_AVEC_ELISION = ("AVRIL", "AOUT", "OCTOBRE")

# Ordre de l'annee academique (septembre -> aout). Un reglement qui couvre
# novembre, decembre et janvier doit se lire dans cet ordre ; l'ordre
# calendaire de MOIS_FR placerait janvier en tete et donnerait un libelle
# faux pour le comptable.
MOIS_ANNEE_ACADEMIQUE = MOIS_FR[8:] + MOIS_FR[:8]

# Abreviations de repli (voir _libelle_frais_ca). Trois lettres, sauf JUIN et
# JUILLET qui partageraient "JUI" : deux mois differents ne doivent jamais
# produire le meme libelle.
ABREVIATIONS_MOIS = {
    "JANVIER": "JAN", "FEVRIER": "FEV", "MARS": "MAR", "AVRIL": "AVR",
    "MAI": "MAI", "JUIN": "JUIN", "JUILLET": "JUIL", "AOUT": "AOU",
    "SEPTEMBRE": "SEP", "OCTOBRE": "OCT", "NOVEMBRE": "NOV", "DECEMBRE": "DEC",
}

# Forme courte de la nature, utilisee en dernier recours quand meme les
# abreviations ne tiennent pas dans LIBELLE_MAX.
BASES_COURTES_CA = {
    "frais": "FRAIS CA",
    "avance": "AVANCE CA",
    "solde": "RATTRAPAGE CA",
}


# Retrouve le mois cite dans un libelle, qu'il suive l'ancien format
# ("PREFIXE NOM/MOIS", suffixe teste en premier pour les pieces deja
# enregistrees) ou le nouveau ("BASE DE MOIS - NOM" / "BASE D'MOIS - NOM",
# voir _libelle_frais_ca). Sert a suggerer, jamais a imposer, le mois
# suivant d'une avance a partir du dernier mouvement connu d'un tiers -
# None si aucun des deux formats ne cite un mois reconnu (saisie libre,
# etc.), auquel cas l'appelant retombe sur un autre defaut.
def mois_depuis_libelle(libelle):
    s = str(libelle or "").upper()
    m = re.search(r"/([A-ZÀ-Ü]+)\s*$", s)
    if m and m.group(1) in MOIS_FR:
        return m.group(1)
    # Le nom du tiers, quand le libelle en porte un, suit " - " : on ne le
    # scanne pas, un patronyme pourrait contenir un mot qui ressemble a un
    # mois. Sur les libelles d'encaissement produits depuis le 18/09/2026 il
    # n'y a de toute facon plus de nom sur les lignes 411.
    tete = s.split(" - ")[0]
    # Tout mois cite, d'ou qu'il vienne : "DE NOVEMBRE", "D'OCTOBRE", un mois
    # nu au milieu d'une enumeration ("..., NOVEMBRE ET DECEMBRE"), ou une
    # abreviation de la forme de repli ("OCT-NOV-DEC"). On retient le DERNIER :
    # depuis la saisie multi-mois un libelle peut en citer plusieurs, et
    # _libelle_frais_ca les ecrit dans l'ordre de l'annee academique, donc le
    # dernier est bien le plus tardif - c'est lui qui sert a suggerer le mois
    # suivant d'une avance.
    #
    # Les deux formes sont reconnues dans la MEME passe, et c'est essentiel :
    # "MAI" et "JUIN" sont a la fois des noms complets et leur propre
    # abreviation. Chercher d'abord tous les noms complets, puis seulement
    # ensuite les abreviations, s'arretait sur eux et ne voyait jamais le
    # "JUIL" ou le "AOU" qui suivait ("SEP-NOV-MAI-JUIL" renvoyait MAI).
    inverse = {v: k for k, v in ABREVIATIONS_MOIS.items()}
    trouves = []
    for mot in re.findall(r"[A-ZÀ-Ü]+", tete):
        if mot in MOIS_FR:
            trouves.append(mot)
        elif mot in inverse:
            trouves.append(inverse[mot])
    return trouves[-1] if trouves else None


# Mois suivant dans le cycle calendaire (decembre boucle sur janvier).
def mois_suivant(mois):
    if mois not in MOIS_FR:
        return MOIS_FR[0]
    return MOIS_FR[(MOIS_FR.index(mois) + 1) % 12]


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
        "libelle": str(un(libelle))[:LIBELLE_MAX].upper(),
        "debit": float(un(debit, 0) or 0),
        "credit": float(un(credit, 0) or 0),
    }


# Compose "PREFIXE NOM/MOIS" en tronquant NOM (jamais le suffixe "/MOIS") si
# le total depasse LIBELLE_MAX - corrige le 10/09/2026 : avant, c'etait le
# libelle final deja compose qui etait tronque a 60 caracteres par ligne()
# ci-dessus, ce qui coupait le plus souvent la fin "/MOIS" (la partie la
# plus a droite, donc la plus exposee, notamment avec un nom d'eleve compose
# un peu long). mois_depuis_libelle() ne reconnaissant alors plus le mois,
# la suggestion automatique du mois suivant d'une avance redevenait
# silencieusement le mois du jour - un confort perdu sans aucune erreur pour
# le signaler.
def _libelle_avec_mois(prefixe, nom, mois):
    nom = str(un(nom, "")).strip()
    suffixe = f"/{mois}"
    place_pour_nom = max(0, LIBELLE_MAX - len(prefixe) - 1 - len(suffixe))
    return f"{prefixe} {nom[:place_pour_nom]}{suffixe}"


# "DE JANVIER" / "D'AVRIL" - elision devant un mois qui commence par une voyelle.
def _de_mois(mois):
    mois = str(un(mois, "")).strip().upper()
    if mois in MOIS_AVEC_ELISION:
        return f"D'{mois}"
    return f"DE {mois}"


# Libelle complet "BASE DE MOIS - NOM" d'une ligne de reglement du
# formulaire "encaissement" (spec 2026), partage a l'identique par la
# ligne de caisse et la ligne 411 d'un encaissement a une seule operation -
# voir _lignes_encaissement. Le mois se place avant le nom (jamais apres,
# contrairement a _libelle_avec_mois) : un nom de tiers long tronque par
# ligne() a LIBELLE_MAX n'ampute donc jamais la nature/le mois de
# l'operation, seulement la fin du nom.
def mois_tries(mois):
    """Mois reconnus, sans doublon, dans l'ordre de l'annee academique.

    Accepte une chaine (un seul mois - forme des pieces enregistrees avant le
    18/09/2026) aussi bien qu'une liste : les deux coexistent dans
    ecritures.valeurs_json, et corriger une piece ancienne doit continuer a
    fonctionner."""
    if mois is None:
        mois = []
    elif isinstance(mois, str):
        mois = [mois]
    vus = []
    for m in mois:
        m = str(un(m, "")).strip().upper()
        if m in MOIS_FR and m not in vus:
            vus.append(m)
    return sorted(vus, key=MOIS_ANNEE_ACADEMIQUE.index)


def _enumeration_mois(liste):
    """"DE NOVEMBRE", "DE NOVEMBRE ET DECEMBRE",
    "D'OCTOBRE, NOVEMBRE ET DECEMBRE"."""
    if len(liste) == 1:
        return _de_mois(liste[0])
    return ", ".join([_de_mois(liste[0])] + liste[1:-1]) + f" ET {liste[-1]}"


def _abreviation_mois(liste):
    return "-".join(ABREVIATIONS_MOIS[m] for m in liste)


def _libelle_frais_ca(nature, mois):
    """Libelle d'une ligne 411 du formulaire "encaissement".

    Ne cite plus le nom de l'eleve (18/09/2026) : la ligne porte deja son
    code tiers, qui l'identifie sans ambiguite dans Sage, et la place gagnee
    sert a citer TOUS les mois couverts par le reglement. Le nom reste sur la
    ligne de caisse, seule ligne de la piece sans code tiers (voir
    _lignes_encaissement).

    Trois formes essayees dans cet ordre, pour ne jamais depasser
    LIBELLE_MAX : ligne() tronque par la droite, donc un libelle trop long
    perdrait le dernier mois sans le moindre signal.
        FRAIS DE COURS D'APPUI D'OCTOBRE, NOVEMBRE ET DECEMBRE   (54)
        FRAIS DE COURS D'APPUI OCT-NOV-DEC                       (34)
        FRAIS CA OCT-NOV-DEC                                     (20)
    La troisieme tient toujours, meme pour six mois en "RATTRAPAGE"."""
    liste = mois_tries(mois)
    base = LIBELLES_NATURE_CA.get(nature, LIBELLES_NATURE_CA["frais"])
    if not liste:
        return base
    courte = BASES_COURTES_CA.get(nature, BASES_COURTES_CA["frais"])
    abrege = _abreviation_mois(liste)
    for candidat in (f"{base} {_enumeration_mois(liste)}",
                     f"{base} {abrege}",
                     f"{courte} {abrege}"):
        if len(candidat) <= LIBELLE_MAX:
            return candidat
    return f"{courte} {abrege}"


def _df(*lignes_):
    return pd.DataFrame(list(lignes_))


def _libelle_transfert(v):
    """Le libelle tape par le caissier s'il en a saisi un, sinon un libelle
    compose automatiquement.

    Le champ est facultatif et c'est voulu : la caissiere de Tampouy ecrit
    "CONTRIBUTION SIAO", celle de Saaba "APPROV SIAO", et les deux parlent de
    la meme remise - les brouillards 2026 le montrent. Lui imposer un libelle
    unique reviendrait a lui faire traduire son vocabulaire ; la laisser ecrire
    le sien ne coute rien, parce que le rapprochement ne lit JAMAIS le libelle.
    Il travaille sur la reference et sur les deux centres, qui sont des
    donnees, pas du texte libre.

    Le libelle compose par defaut ("TRANSFERT PIS>SIA") utilise les codes a
    trois lettres : c'est un libelle comptable destine a l'export Sage, ou la
    place est comptee (60 caracteres). Jamais un texte montre a l'ecran - les
    centres s'y affichent toujours en toutes lettres (voir
    donnees.nom_centre)."""
    saisi = str(un(v.get("libelle"), "")).strip()
    if saisi:
        return saisi
    donateur = str(un(v.get("centre_donateur"), "")).strip().upper()
    destinataire = str(un(v.get("centre_destinataire"), "")).strip().upper()
    return f"TRANSFERT {donateur}>{destinataire}"


def _lignes_transfert(v, cc):
    """Une seule face, celle du centre qui saisit - jamais les deux.

    `v["mon_centre"]` est pose par l'application a partir de l'utilisateur
    connecte. Sortie : la caisse est creditee, le compte de passage debite.
    Entree : l'inverse. Le compte de passage revient a zero quand les deux
    faces existent, ce qui est exactement la definition d'un transfert
    termine."""
    mien = str(un(v.get("mon_centre"), "")).strip()
    donateur = str(un(v.get("centre_donateur"), "")).strip()
    montant = v.get("montant")
    if not mien or not donateur or not montant:
        return None
    if mien == donateur:
        return _df(ligne(COMPTE_VIREMENTS_FONDS, v["lib"], debit=montant),
                   ligne(cc, v["lib"], credit=montant))
    return _df(ligne(cc, v["lib"], debit=montant),
               ligne(COMPTE_VIREMENTS_FONDS, v["lib"], credit=montant))


# Compte d'attente (SYSCOHADA) : pivot systematique de "Ecriture libre" sur
# les journaux de ventes/achats, exactement comme la caisse est le pivot
# systematique sur les journaux de tresorerie. Doit correspondre a la ligne
# ajoutee dans referentiel.xlsx (onglet comptes) et au controle de
# donnees.py qui signale toute piece qui le touche.
COMPTE_ATTENTE = "471000"

# --- transferts internes entre centres ---------------------------------------
#
# Compte SYSCOHADA 585 "Virements de fonds" : compte de passage de tout
# mouvement d'argent d'une caisse a une autre. Deja present dans le plan Sage
# de HAKILISSO et deja utilise par la comptable pour les remises au centre
# SIAO. Voir sql/migrations/2026-09-12_transferts_internes.sql pour le
# raisonnement complet et les comptes ecartes.
COMPTE_VIREMENTS_FONDS = "585000"

# Centre propose par defaut comme destinataire d'un transfert. C'est une regle
# de gestion actuelle, pas une contrainte : les deux centres restent
# selectionnables dans le formulaire, precisement pour que l'application
# survive a un changement de decision de la direction. La changer ici suffit.
CENTRE_DESTINATAIRE_PAR_DEFAUT = "SIA"


MODELES = [

    {
        # Fusionne l'ancien "Encaissement de frais" et l'ancienne "Avance de
        # paiement (plusieurs mois)" en un seul formulaire (spec 2026) : la
        # caissiere tape un montant total recu puis le repartit sur un ou
        # plusieurs mois (Frais / Avance / Solde-retard), champ "repartition"
        # rendu et gere dynamiquement par app.py (m_bloc_repartition). Le
        # mode simple (une seule ligne "Frais", mois en cours) se comporte
        # exactement comme l'ancien formulaire dedie.
        "id": "encaissement",
        "titre": "Encaissement de frais de scolarite",
        "aide": "Reglement eleve : frais du mois, avance, ou rattrapage d'un mois passe",
        "journal": "CP",
        "champs": [
            {"n": "tiers", "l": "Eleve (compte 411)", "t": "tiers", "pref": "411", "collectif": "411000",
             "historique": True},
            {"n": "montant", "l": "Montant total recu", "t": "montant"},
            {"n": "repartition", "l": "Repartition", "t": "repartition"},
        ],
        # Libelle de la ligne de caisse (voir _lignes_encaissement) : pas de
        # mois ici, une seule ligne ne peut pas resumer plusieurs mois et
        # natures a la fois - ils restent precises sur chaque ligne 411. Le
        # nom de l'eleve, lui, y reste : c'est la seule ligne de la piece qui
        # ne porte pas de code tiers, donc la seule ou le nom dit encore qui
        # a paye (18/09/2026).
        "libelle": lambda v: f"FRAIS DE COURS D'APPUI - {v.get('tiers_nom', '')}",
        "lignes": lambda v, cc: _lignes_encaissement(v, cc),
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
        # Remplace par le mode multi-lignes du modele "encaissement"
        # ci-dessus (spec 2026). "retire" le sort du selecteur de saisie
        # (voir _modeles_groupes dans app.py) sans le retirer de MODELES :
        # modele_par_id() continue de le resoudre pour les pieces deja
        # enregistrees sous cet identifiant (correction, historique).
        "id": "avance_paiement_multimois",
        "retire": True,
        "titre": "Avance de paiement (plusieurs mois) [retire, voir Encaissement]",
        "aide": "Un paiement recu en une fois qui couvre plusieurs mois de frais",
        "journal": "CP",
        "champs": [
            {"n": "tiers", "l": "Eleve (compte 411)", "t": "tiers", "pref": "411", "collectif": "411000"},
            {"n": "montant", "l": "Montant total recu", "t": "montant"},
            {"n": "mois", "l": "Premier mois couvert", "t": "mois"},
            {"n": "nb_mois", "l": "Nombre de mois couverts", "t": "choix",
             "options": {"2": "2 mois", "3": "3 mois", "4": "4 mois", "5": "5 mois", "6": "6 mois"}},
        ],
        "libelle": lambda v: f"FRAIS CA {v.get('tiers_nom', '')}",
        "lignes": lambda v, cc: _lignes_avance_paiement(v, cc),
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
        "lie": "Banque",
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
        # Un centre remet des especes a un autre centre - le cas courant etant
        # le depot au centre SIAO, qui paie ensuite pour le compte de tous.
        #
        # Il n'y a PAS de champ "sens", volontairement : le sens se deduit de
        # qui saisit (voir logic.donnees._metadonnees_transfert). Le caissier
        # designe simplement le centre donateur et le centre destinataire, l'un
        # des deux etant le sien. C'est plus proche de la facon dont il pense
        # l'operation ("Pissy remet a SIAO") qu'un choix Entree/Sortie, et cela
        # ferme la porte a l'erreur classique : enregistrer une entree alors
        # qu'on a fait une sortie.
        #
        # Il n'y a PAS non plus d'operation liee ("lie") : une piece liee est
        # produite par une seule saisie, dans un seul centre, ce qui ferait
        # ecrire un centre dans les livres d'un autre - exactement le
        # cloisonnement durci le 11/09/2026. Et l'argent met parfois des
        # semaines a arriver (les brouillards montrent une remise de janvier
        # enregistree le 20 fevrier) : chaque centre enregistre donc son propre
        # mouvement, le jour ou il a lieu, et le rapprochement verifie ensuite
        # que les deux faces se repondent (voir analyse.transferts_internes).
        #
        # "journal": None - un transfert peut partir de la caisse principale,
        # de la caisse menues depenses ou de la banque. Les brouillards reels
        # montrent des remises au SIAO depuis CP comme depuis CMD.
        "id": "transfert_interne",
        "titre": "Transfert entre centres",
        "aide": "Remise d'especes d'un centre a un autre - ni recette ni depense",
        "journal": None,
        "champs": [
            {"n": "centre_donateur", "l": "Centre qui remet l'argent", "t": "centre",
             "defaut_centre": "mien"},
            {"n": "centre_destinataire", "l": "Centre qui recoit l'argent", "t": "centre",
             "defaut_centre": CENTRE_DESTINATAIRE_PAR_DEFAUT},
            {"n": "montant", "l": "Montant", "t": "montant"},
            {"n": "libelle", "l": "Libelle (facultatif)", "t": "libelle"},
        ],
        "libelle": lambda v: _libelle_transfert(v),
        "lignes": lambda v, cc: _lignes_transfert(v, cc),
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

    # --- journal Banque (compte CBI) ---------------------------------------
    # Les deux modeles ci-dessous reprennent ce que l'historique de l'ancien
    # journal de banque (BDU-BF, retire le 11/09/2026 lors du changement
    # d'etablissement - voir sql/migrations/2026-09-11_*) montrait : 52 % de
    # reglements fournisseurs et 21 % de versements d'especes (deja couverts
    # par le modele precedent), puis les frais bancaires et les reglements
    # d'impots et de retenues. Le code de journal "Banque" est stable et ne
    # depend d'aucun etablissement en particulier (voir sql/schema.sql) :
    # seul intitule/prefixe_piece changeraient si la banque change encore.

    {
        "id": "fournisseur_banque",
        "titre": "Reglement d'un fournisseur par banque",
        "aide": "Virement ou cheque - 52 % des pieces de banque",
        "journal": "Banque",
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
        "journal": "Banque",
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
        # Sur caisse/banque (CP, CMD, Banque) : le compte de caisse est
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


# Genere la piece du formulaire "encaissement" (mode multi-mois) : une
# ligne de caisse (debit = montant total recu) et une ligne 411000 par
# entree de repartition (credit), libellee selon sa nature. Ne fait aucun
# controle d'equilibre lui-meme - si la somme des lignes ne vaut pas le
# montant total, la piece renvoyee est simplement desequilibree, et
# operation_equilibree() (deja generique) le signale comme pour tout autre
# modele : aucune logique de controle dupliquee ici.
#
# Libelle de la ligne de caisse (spec 2026) : identique au libelle complet
# de l'unique ligne 411 pour un encaissement a une seule operation (le cas
# le plus frequent - le comptable doit lire le meme texte des deux cotes).
# Quand plusieurs operations sont regroupees en un seul reglement (frais +
# avance, par exemple), aucun texte unique ne peut resumer plusieurs mois/
# natures a la fois : la ligne de caisse garde alors le libelle global
# "FRAIS DE COURS D'APPUI - NOM" (v["lib"], voir le modele "encaissement"
# ci-dessus), sans mois - il reste precise sur chaque ligne 411 de detail.
def _lignes_encaissement(v, cc):
    montant_total = float(un(v.get("montant"), 0) or 0)
    if montant_total <= 0:
        return None
    # "mois" est une LISTE depuis le 18/09/2026 : une ligne de repartition
    # peut couvrir plusieurs mois, et produit alors UNE seule ecriture 411
    # dont le libelle les cite tous - c'est la facon de faire du comptable.
    # mois_tries() accepte aussi l'ancienne forme (une chaine).
    repartition = [row for row in (v.get("repartition") or [])
                   if float(un(row.get("montant"), 0) or 0) > 0 and mois_tries(row.get("mois"))]
    lignes_411 = []
    for row in repartition:
        montant = float(un(row.get("montant"), 0) or 0)
        libelle = _libelle_frais_ca(row.get("nature"), row.get("mois"))
        lignes_411.append(ligne("411000", libelle, credit=montant, code_tiers=v.get("tiers", "")))
    if not lignes_411:
        return None
    # La ligne de caisse porte toujours le libelle global avec le nom, y
    # compris quand il n'y a qu'une seule ligne 411 (change le 18/09/2026) :
    # les lignes 411 ne citent plus le nom, donc reprendre leur libelle ici
    # laisserait le brouillard de caisse sans aucune indication de qui a paye.
    return _df(ligne(cc, v["lib"], debit=montant_total), *lignes_411)


def _lignes_avance_paiement(v, cc):
    montant_total = float(v["montant"])
    if montant_total <= 0:
        return None
    try:
        nb = int(v.get("nb_mois") or 2)
    except (TypeError, ValueError):
        nb = 2
    if nb < 1:
        return None

    mois_depart = v.get("mois") or MOIS_FR[0]
    idx_depart = MOIS_FR.index(mois_depart) if mois_depart in MOIS_FR else 0

    montant_mensuel = round(montant_total / nb)
    lignes_mensuelles = []
    reparti = 0
    for i in range(nb):
        dernier = (i == nb - 1)
        m = montant_total - reparti if dernier else montant_mensuel
        reparti += m
        mois_nom = MOIS_FR[(idx_depart + i) % 12]
        lignes_mensuelles.append(
            ligne("411000", _libelle_avec_mois("AVANCE", v["lib"], mois_nom),
                  credit=m, code_tiers=v.get("tiers", ""))
        )

    return _df(ligne(cc, v["lib"], debit=montant_total), *lignes_mensuelles)


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
        elif ch["t"] == "repartition":
            # Deja une liste de {"mois", "nature", "montant"} construite par
            # l'interface (une entree par mois reparti) : un() la reduirait
            # a tort a un seul element, ne pas l'y faire passer.
            v[ch["n"]] = v.get(ch["n"]) or []
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
        # Corrige le 10/09/2026 : cette exception etait totalement avalee -
        # l'utilisateur voyait juste "Renseignez l'operation", indiscernable
        # d'un formulaire simplement incomplet, et rien n'indiquait qu'un
        # modele etait casse. Le comportement fonctionnel ne change pas
        # (toujours None), mais l'incident devient diagnosticable.
        logger.exception("Echec de construction des lignes (modele=%s, journal=%s)", id_modele, journal)
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
# ---------------------------------------------------------------------------
# Questions suggerees de l'onglet Assistant : un tableau de bord du
# directeur. Ce sont les premieres choses qu'il veut savoir, dans ses mots.
#
# Les six premieres s'affichent en pastilles cliquables a l'ouverture de la
# conversation ; la liste complete est dans le menu "Questions frequentes".
# Un clic remplit la zone de saisie : on peut modifier avant d'envoyer.
# ---------------------------------------------------------------------------

ESSENTIELLES = [
    "Fais-moi le point financier",
    "Combien avons-nous en caisse et en banque ?",
    "Combien avons-nous reçu ce mois-ci ?",
    "Combien avons-nous dépensé ce mois-ci ?",
    "Situation de chaque centre ce mois-ci",
    "Y a-t-il quelque chose à vérifier ?",
]

TABLEAU_DE_BORD = {
    "L'essentiel": [
        "Fais-moi le point financier",
        "Combien avons-nous en caisse et en banque ?",
        "Combien avons-nous reçu ce mois-ci ?",
        "Combien avons-nous dépensé ce mois-ci ?",
        "Ce mois-ci par rapport au mois dernier ?",
        "Évolution de l'argent reçu et dépensé depuis la rentrée",
    ],
    "Les centres": [
        "Situation de chaque centre ce mois-ci",
        "Quel centre a reçu le plus depuis la rentrée ?",
        "Les centres ont-ils envoyé leur part au SIAO ce mois-ci ?",
        "Quel centre est le plus rentable depuis la rentrée ?",
    ],
    "Recettes et dépenses": [
        "Nos plus grosses dépenses du mois",
        "Combien avons-nous payé en salaires et vacations ce mois-ci ?",
        "D'où vient l'argent reçu ce mois-ci ?",
        "Quel bénéfice avons-nous fait depuis la rentrée ?",
    ],
    "À surveiller": [
        "Y a-t-il quelque chose à vérifier ?",
        "Combien d'opérations attendent d'être validées ?",
        "Y a-t-il des paiements en double ce mois-ci ?",
        "Quels sont les derniers mouvements dans les caisses ?",
    ],
}


def exemples():
    """-> {groupe: [questions]} pour le menu."""
    return TABLEAU_DE_BORD

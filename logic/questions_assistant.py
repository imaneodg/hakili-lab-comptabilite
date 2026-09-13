# ---------------------------------------------------------------------------
# Questions suggerees pour l'assistant IA - regroupees par categorie.
#
# Ce fichier ne fait aucun calcul : c'est une liste statique consommee par
# l'onglet Shiny de l'assistant (voir app.py::onglet_assistant) pour
# afficher des boutons cliquables. Chaque libelle est ecrit tel qu'un
# directeur le poserait en langage naturel - c'est le modele de langage,
# cote MCP, qui choisit ensuite le ou les bons outils de mcp_server.tools
# pour y repondre, pas ce fichier.
#
# Catalogue valide avec la direction le 06/09/2026, complete le 11/09/2026
# (voir plus bas les cinq questions ajoutees : annee scolaire, periode libre,
# ecritures mal datees, charges non rattachees). A l'origine 45 questions + les
# indicateurs de l'ancien tableau de bord Finova, repris comme questions
# suggerees ci-dessous plutot que comme graphiques permanents). Deux choix
# assumes, a relire si le perimetre de Hakili_compta evolue :
#   - Impayes/arrieres : categorie gardee ICI (les questions restent
#     posables), mais l'outil correspondant repond "indisponible" tant que
#     l'echeancier par eleve n'existe pas - voir mcp_server/tools/impayes.py.
#   - Mouvements inter-centres (contribution au SIAO) : categorie
#     deliberement absente. Aucun compte de liaison inter-centres n'existe
#     dans le plan comptable actuel ; la direction a choisi de ne pas
#     suggerer ces questions plutot que de proposer un outil "indisponible"
#     sur un sujet qui n'a pas encore de traduction comptable.
#
# Ajouter une question : l'ajouter dans la bonne categorie ci-dessous. Rien
# d'autre a modifier tant que l'outil MCP correspondant existe deja.
# ---------------------------------------------------------------------------

QUESTIONS_PAR_CATEGORIE = {
    "Recettes": [
        "Quel est le total encaisse par [centre] ce mois-ci, et comment se compare-t-il au mois precedent ?",
        "Quelle est la repartition des recettes du mois entre frais de scolarite et prestations facturees pour [centre] ?",
        "Quel montant reste encore a reclasser depuis le compte d'attente pour [centre] ce mois-ci ?",
        "Quel centre a encaisse le plus ce mois-ci, et lequel le moins ?",
        "Combien aurions-nous du encaisser en frais de scolarite ce mois-ci si tous les eleves inscrits avaient paye ?",
        "Quels eleves inscrits n'ont encore rien paye ce mois-ci ?",
    ],
    "Depenses": [
        "Quel est le poste de depense le plus important ce mois pour [centre] ?",
        "Quelle part de nos depenses represente la masse salariale ce mois-ci ?",
        "Le loyer, l'eau et l'electricite representent quelle part de nos depenses du mois pour [centre] ?",
        "Y a-t-il une depense anormalement elevee ce mois par rapport a d'habitude ?",
        "Quelle est notre depense moyenne mensuelle en nettoyage, telecom, fournitures et carburant ?",
    ],
    "Rentabilite par centre": [
        "Quel centre a la meilleure marge ce mois-ci ?",
        "Quelle est la recette par eleve de [centre] ce mois-ci ?",
        "Classe les centres du plus rentable au moins rentable ce mois-ci.",
        "Combien d'eleves actifs a [centre] ce mois-ci, et comment cet effectif evolue-t-il ?",
        "Quel est le seuil de rentabilite de [centre] (nombre d'eleves necessaire pour couvrir ses charges fixes) ?",
    ],
    "Impayes et arrieres": [
        "Quel est le montant total des impayes en cours pour [centre] ?",
        "Quels sont les impayes les plus anciens qui meritent une relance prioritaire ?",
        "Quel eleve ou quelle famille a le retard de paiement le plus important ?",
    ],
    "Personnel": [
        "Combien [centre] a-t-il verse en vacations et remunerations ce mois-ci, et a qui ?",
        "Quels enseignants ou employes interviennent sur plusieurs centres, et leur remuneration cumulee est-elle coherente ?",
        "Quels prets ou avances au personnel sont en cours, et quel solde reste du ?",
        "Le cout des vacations par eleve evolue-t-il d'un centre a l'autre ?",
    ],
    "Comparaison de centres": [
        "Quel centre a genere le plus de recettes ce trimestre ?",
        "Quel centre a la structure de couts la plus legere ?",
        "Comment se repartit la contribution de chaque centre au total du mois ?",
        "Quel centre a le meilleur taux de recouvrement ce mois-ci ?",
    ],
    "Suivi mensuel": [
        "Quel est le resultat net du mois, et comment se compare-t-il au mois precedent ?",
        "Montre-moi l'evolution des recettes et des depenses sur les six derniers mois.",
        "Quel est le solde actuel de la caisse principale de [centre] ?",
        "Compare le resultat net des centres mois par mois sur les six derniers mois.",
        "Quel est notre resultat depuis le debut de l'annee, compare a la meme periode l'an dernier ?",
        "Ou en sommes-nous depuis la rentree, compare a la meme periode de l'annee scolaire precedente ?",
        "Combien avons-nous encaisse entre [date de debut] et [date de fin] ?",
    ],
    "Tresorerie et projections": [
        "Quelle est la tresorerie disponible pour [centre], et au global ?",
        "Peut-on projeter les depenses fixes (vacations, loyer, charges) attendues le mois prochain ?",
        "Peut-on projeter les recettes attendues le mois prochain a partir des inscriptions connues ?",
        "La caisse de [centre] est-elle sous 100000 F CFA aujourd'hui ?",
    ],
    "Controle": [
        "Y a-t-il des paiements suspects ce mois-ci (meme montant, meme jour, meme beneficiaire) ?",
        "Le montant en attente de reclassement est-il en hausse ou en baisse par rapport au mois dernier ?",
        "Combien de pieces restent a corriger ou a reclasser ce mois-ci ?",
        "Y a-t-il des ecritures mal datees qui echappent silencieusement a nos totaux mensuels ?",
        "Quelles depenses ne sont rattachees a aucune categorie de charge ?",
        "Ou en sont les transferts d'argent entre centres ce mois-ci ?",
        "Y a-t-il des remises parties d'un centre et jamais enregistrees a l'arrivee ?",
    ],
    "Recherche libre": [
        "Que s'est-il passe sur la caisse de [centre] le [date] ?",
        "Montre-moi toutes les transactions liees a [eleve, fournisseur ou enseignant].",
        "Montre-moi toutes les depenses superieures a [montant] sur [periode].",
        "Montre-moi le detail des ecritures du mois pour [centre].",
    ],
}

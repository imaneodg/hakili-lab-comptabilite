# ---------------------------------------------------------------------------
# Assistant IA de Hakili Lab (reconstruit le 24/09/2026).
#
# Organisation par couches, de la question a la reponse :
#
#   comprehension.py   texte libre -> centre, periode, tiers, categorie exacts
#   semantique.py      ecritures -> faits (encaissements, decaissements,
#                      charges) avec UNE seule definition de chaque chiffre
#   moteur.py          analyser / comparer / soldes / lister / controles
#   outils.py          les 10 outils exposes au modele (portee de la session)
#   rendu.py           tableaux et graphiques affiches dans le chat
#   prompt.py          prompt systeme, reconstruit a chaque question
#   session.py         une conversation par utilisateur (client, historique,
#                      verrou, journal)
#   questions.py       exemples de questions, generes sur les vraies donnees
#
# Le modele ne calcule rien : il choisit un outil, lit un resultat deja
# calcule et le formule. Voir claude/reconstruction-assistant-ia-2026-09-23.md.
# ---------------------------------------------------------------------------

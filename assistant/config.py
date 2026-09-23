# ---------------------------------------------------------------------------
# Reglages de l'assistant IA. Tout ce qui peut changer sans toucher au code
# se lit dans l'environnement (.env).
# ---------------------------------------------------------------------------

import os

# Modele Anthropic. En variable pour pouvoir en changer sans redeployer le code.
MODELE = os.environ.get("HAKILI_MODELE_IA", "claude-sonnet-5")

# Longueur maximale d'une reponse (jetons). Les reponses doivent etre courtes :
# cette borne est un garde-fou de cout, pas un objectif.
MAX_TOKENS = int(os.environ.get("HAKILI_IA_MAX_TOKENS", "2000"))

# Nombre d'echanges (question + reponse) gardes en memoire dans une
# conversation. Au-dela, les plus anciens sont oublies : le cout de chaque
# question reste stable et la conversation ne depasse jamais la fenetre du
# modele.
HISTORIQUE_MAX_ECHANGES = int(os.environ.get("HAKILI_IA_HISTORIQUE", "8"))

# Lignes renvoyees au modele par un resultat. Le total, lui, est toujours
# calcule sur tout le perimetre. Le tableau affiche a l'ecran va plus loin.
LIGNES_MODELE = 40
LIGNES_ECRAN = 300

# Outil requete_sql : bornes de securite.
SQL_TIMEOUT_MS = 10000
SQL_LIGNES_MAX = 300
# Connexion dediee (role en lecture seule), optionnelle. Absente : la
# connexion de l'application est utilisee, dans une transaction READ ONLY.
DSN_LECTURE = os.environ.get("HAKILI_ASSISTANT_DATABASE_URL") or None

# Nombre de resultats gardes en memoire par conversation (pour les graphiques).
RESULTATS_EN_CACHE = 40

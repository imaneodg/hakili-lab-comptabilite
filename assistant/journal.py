# ---------------------------------------------------------------------------
# Journal de l'assistant : qui a demande quoi, quels outils ont ete appeles
# avec quels parametres, combien de temps et combien de jetons. Sert au
# controle (outil financier) et a ameliorer les exemples de questions a partir
# des vraies questions posees.
#
# Best effort : un echec d'ecriture du journal ne doit jamais empecher de
# repondre - il est seulement signale dans hakili.log.
# ---------------------------------------------------------------------------

import json
import logging

import logic.donnees as dl

logger = logging.getLogger("hakili.assistant")


def enregistrer(utilisateur="", centre="", question="", outils=None, reponse="", duree_ms=None,
                jetons_entree=None, jetons_sortie=None, erreur=""):
    try:
        with dl._connexion() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO journal_assistant (utilisateur, centre, question, outils, reponse, "
                "duree_ms, jetons_entree, jetons_sortie, erreur) "
                "VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)",
                (utilisateur or "", centre or "", (question or "")[:4000],
                 json.dumps(outils or [], ensure_ascii=False, default=str),
                 (reponse or "")[:8000], duree_ms, jetons_entree, jetons_sortie, (erreur or "")[:2000]))
    except Exception as e:
        logger.warning("Journal de l'assistant non ecrit : %s", e)
    logger.info("Assistant IA - %s : %s | outils=%s | %s ms%s", utilisateur, (question or "")[:120],
                [o.get("outil") for o in (outils or [])], duree_ms, f" | ERREUR {erreur}" if erreur else "")

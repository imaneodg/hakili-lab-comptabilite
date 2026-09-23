# ---------------------------------------------------------------------------
# Une conversation avec l'assistant, pour UN utilisateur connecte.
#
# Remplace le branchement MCP de l'ancien app.py : les outils sont enregistres
# directement dans le client Claude, avec la portee de l'utilisateur, avant la
# premiere question - plus de sous-processus, plus de course au demarrage,
# plus de question traitee sans outils.
#
# Responsabilites :
#   - creer le client (modele, cle, outils) au premier besoin ;
#   - reconstruire le prompt systeme a chaque question (date du jour) ;
#   - borner l'historique (cout stable, jamais de depassement de contexte) ;
#   - un seul flux a la fois (verrou) ;
#   - journaliser chaque echange (table journal_assistant) ;
#   - traduire les pannes du service en messages lisibles.
# ---------------------------------------------------------------------------

import logging
import os
import time

from assistant import config, journal, prompt, semantique as sem
from assistant.moteur import Contexte
from assistant.outils import creer_outils

logger = logging.getLogger("hakili.assistant")


class AssistantIndisponible(Exception):
    """Configuration manquante (cle API, paquet) : message pour l'utilisateur."""


def message_erreur(e):
    """Panne du service d'IA -> phrase comprehensible par un comptable."""
    nom = type(e).__name__
    texte = str(e).lower()
    if "overloaded" in texte or "529" in texte or nom in ("RateLimitError", "OverloadedError") \
            or "rate limit" in texte or "429" in texte:
        return "L'assistant est momentanément surchargé. Réessayez dans une minute."
    if nom in ("AuthenticationError", "PermissionDeniedError") or "401" in texte or "api key" in texte:
        return ("La clé d'accès au service d'IA est refusée. Prévenir l'administrateur "
                "(ANTHROPIC_API_KEY).")
    if nom in ("APIConnectionError", "APITimeoutError", "ConnectError", "ReadTimeout") \
            or "connection" in texte or "timeout" in texte:
        return "Le service d'IA est injoignable pour le moment. Vérifiez la connexion et réessayez."
    if nom == "NotFoundError" or "model" in texte and "not found" in texte:
        return "Le modèle d'IA configuré est introuvable. Prévenir l'administrateur (HAKILI_MODELE_IA)."
    return "Une erreur est survenue pendant la réponse. Réessayez ; si elle persiste, prévenir l'administrateur."


class SessionAssistant:

    def __init__(self, utilisateur=None, portee=None, aujourd_hui=None):
        """utilisateur : dict de session (identifiant, nom, centre) ;
        portee : liste des centres accessibles, None = tous (comptable du siege)."""
        self.utilisateur = utilisateur or {}
        self.ctx = Contexte(portee=portee, aujourd_hui=aujourd_hui)
        self._client = None
        self._appels = []
        self.occupe = False

    # --- client --------------------------------------------------------------
    def _prompt(self):
        R = self.ctx.R
        codes = self.ctx.portee if self.ctx.portee is not None else R.centres_actifs()
        limite = ", ".join(R.nom_centre(c) for c in self.ctx.portee) if self.ctx.portee else None
        return prompt.construire([R.nom_centre(c) for c in codes], sem.plage_donnees(),
                                 self.ctx.aujourd_hui, self.utilisateur.get("nom"), limite)

    def client(self):
        if self._client is None:
            cle = os.environ.get("ANTHROPIC_API_KEY")
            if not cle:
                raise AssistantIndisponible("Assistant IA non configuré : clé ANTHROPIC_API_KEY absente "
                                            "du fichier .env. Prévenir l'administrateur.")
            try:
                from chatlas import ChatAnthropic
            except ImportError as e:
                raise AssistantIndisponible("Assistant IA indisponible : une dépendance manque dans "
                                            "l'installation du serveur.") from e
            client = ChatAnthropic(model=config.MODELE, api_key=cle, max_tokens=config.MAX_TOKENS,
                                   system_prompt=self._prompt())
            for f in creer_outils(self.ctx, self._appels):
                client.register_tool(f)
            self._client = client
        return self._client

    # --- historique ---------------------------------------------------------------
    def _elaguer(self):
        """Garde les N derniers echanges. On coupe toujours juste avant une
        question de l'utilisateur, jamais entre une demande d'outil et son
        resultat (le modele refuserait un historique incoherent)."""
        client = self._client
        if client is None:
            return
        tours = client.get_turns()
        debuts = [i for i, t in enumerate(tours)
                  if t.role == "user" and any(type(c).__name__ == "ContentText" for c in t.contents)]
        if len(debuts) >= config.HISTORIQUE_MAX_ECHANGES:
            coupe = debuts[-(config.HISTORIQUE_MAX_ECHANGES - 1)]
            client.set_turns(tours[coupe:])

    def reinitialiser(self):
        if self._client is not None:
            self._client.set_turns([])
        self.ctx.vider()

    # --- question -------------------------------------------------------------
    def repondre(self, question):
        """Generateur asynchrone a passer a chat.append_message_stream :
        texte de la reponse et cartes d'outils, dans l'ordre. Le verrou est
        pose ICI, avant tout await : deux envois rapproches ne peuvent pas
        lancer deux flux sur la meme conversation."""
        self.occupe = True
        return self._flux((question or "").strip())

    async def _flux(self, question):
        debut = time.perf_counter()
        morceaux, erreur = [], ""
        nb_tours_avant = 0
        try:
            client = self.client()
            client.system_prompt = self._prompt()
            self._elaguer()
            nb_tours_avant = len(client.get_turns())
            self._appels.clear()
            flux = await client.stream_async(question, content="all")
            async for m in flux:
                if isinstance(m, str):
                    morceaux.append(m)
                yield m
        except AssistantIndisponible as e:
            erreur = str(e)
            yield str(e)
        except Exception as e:
            logger.exception("Assistant IA : echec de la reponse")
            erreur = f"{type(e).__name__}: {str(e)[:300]}"
            yield ("\n\n" if morceaux else "") + message_erreur(e)
        finally:
            self.occupe = False
            entree = sortie = None
            if self._client is not None:
                try:
                    nouveaux = self._client.get_turns()[nb_tours_avant:]
                    jetons = [t.tokens for t in nouveaux if getattr(t, "tokens", None)]
                    if jetons:
                        entree = sum(int(j[0]) + int(j[2] if len(j) > 2 else 0) for j in jetons)
                        sortie = sum(int(j[1]) for j in jetons)
                except Exception:
                    pass
            journal.enregistrer(
                utilisateur=self.utilisateur.get("identifiant", ""),
                centre=self.utilisateur.get("centre", ""), question=question,
                outils=list(self._appels), reponse="".join(morceaux),
                duree_ms=int((time.perf_counter() - debut) * 1000),
                jetons_entree=entree, jetons_sortie=sortie, erreur=erreur)

    # --- exemples -------------------------------------------------------------
    def exemples(self):
        """Questions du tableau de bord, pour le menu de l'onglet."""
        from assistant import questions
        return questions.exemples()

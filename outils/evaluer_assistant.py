"""
evaluer_assistant.py - pose de vraies questions a l'assistant IA (vrai modele,
vraie base) et affiche, pour chacune : les outils appeles avec leurs
parametres, la reponse, sa longueur et la duree.

A lancer avant chaque mise en production, et apres toute modification du
prompt (assistant/prompt.py) ou des outils. Les questions sont ecrites comme
les utilisateurs les ecrivent : fautes, abreviations, dates approximatives.

Usage (racine du projet, meme venv que l'app, .env avec ANTHROPIC_API_KEY) :
    python -m outils.evaluer_assistant
    python -m outils.evaluer_assistant "combien saab a encaisse en fevirer"

Cout indicatif : quelques centimes d'euro par question.
"""

import asyncio
import sys
import time

from dotenv import load_dotenv

load_dotenv()

from assistant.session import SessionAssistant  # noqa: E402

QUESTIONS = [
    "fais moi le point financier",
    "combien on a en caisse et en banque",
    "combien on a recu ce mois ci",
    "combien on a depenser en aout",
    "ce mois par rapport au mois dernier",
    "evolution des recettes et depenses depuis la rentre en graphique",
    "situation de chaque centre",
    "combien saab a encaisser en fevirer",
    "nos plus grosse depenses du mois",
    "combien on a payer en vacation ce mois",
    "les centres ont ils envoyer leur part au siao ce mois",
    "est ce qu'il y a quelque chose a verifier",
    "quel benefice depuis la rentree",
    "combien les eleves nous doivent",
    "derniers mouvements dans les caisses de tampouy",
]


async def poser(question):
    s = SessionAssistant(utilisateur={"identifiant": "evaluation", "nom": "Evaluation", "centre": "SIE"})
    debut = time.perf_counter()
    texte = []
    async for m in s.repondre(question):
        if isinstance(m, str):
            texte.append(m)
    duree = time.perf_counter() - debut
    reponse = "".join(texte).strip()
    print("=" * 90)
    print(f"Q : {question}")
    for a in s._appels:
        print(f"   -> {a.get('outil')} {a.get('parametres', '')}"
              + (f"  [{a['incomprehension']}]" if a.get("incomprehension") else "")
              + (f"  [ERREUR {a['erreur']}]" if a.get("erreur") else ""))
    print(f"R ({len(reponse.split())} mots, {duree:.1f} s) :\n{reponse}")


async def main():
    questions = sys.argv[1:] or QUESTIONS
    for q in questions:
        await poser(q)


if __name__ == "__main__":
    asyncio.run(main())

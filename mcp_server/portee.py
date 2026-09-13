# ---------------------------------------------------------------------------
# Portee des outils MCP : quel centre l'utilisateur connecte a-t-il le droit
# d'interroger ?
#
# Ajoute le 11/09/2026. Jusque-la, aucun outil MCP n'appliquait de
# cloisonnement : le parametre `centre` venait de la QUESTION posee, jamais de
# la session. Le probleme etait masque par app.py, qui reserve l'onglet
# Assistant au comptable du siege (voir peut_voir_assistant), mais il n'aurait
# tenu qu'a l'ouverture aux directeurs de centre - deja annoncee dans le
# commentaire de peut_voir_assistant et deja supposee par le prompt systeme,
# qui s'adresse "au comptable et aux directeurs de centre". Un directeur de
# Tampouy aurait alors pu demander le classement de rentabilite de tous les
# centres, ou les vacations de Saaba nom par nom.
#
# Le meme angle mort avait deja mordu une fois cote Shiny, corrige le
# 11/09/2026 sur est_comptable() : un validateur local etait traite comme le
# comptable du siege. On ne refait pas l'erreur cote MCP.
#
# Comment la portee arrive ici : app.py demarre UN sous-processus MCP PAR
# SESSION Shiny (register_mcp_tools_stdio_async), et lui passe la variable
# d'environnement HAKILI_PORTEE_CENTRE. L'isolation est donc bien par session,
# pas par serveur - deux utilisateurs connectes en meme temps ont chacun leur
# sous-processus, avec leur propre portee.
#
# Variable absente ou vide = aucune restriction : c'est le cas du comptable du
# siege, et c'est le comportement actuel de l'application, inchange.
# ---------------------------------------------------------------------------

import os

VARIABLE_ENVIRONNEMENT = "HAKILI_PORTEE_CENTRE"


class PorteeRefusee(Exception):
    """Levee quand la question porte sur un centre que l'utilisateur n'a pas
    le droit de consulter. Le message est redige pour etre lu tel quel par le
    modele de langage, puis reformule au directeur."""


def centre_impose():
    """Code du centre auquel cette session est limitee, ou None si elle voit
    l'ensemble de Hakili Lab (comptable du siege)."""
    valeur = (os.environ.get(VARIABLE_ENVIRONNEMENT) or "").strip()
    return valeur or None


def resoudre(centre=None):
    """Centre effectif d'un appel d'outil.

    - Session sans restriction : le centre demande est renvoye tel quel
      (y compris None, qui signifie "tous les centres").
    - Session limitee a un centre : un appel sans centre est ramene a ce
      centre, et un appel sur un AUTRE centre est refuse - jamais renvoye
      silencieusement vide, ce qui laisserait croire a une absence de donnees
      plutot qu'a un refus.
    """
    impose = centre_impose()
    if impose is None:
        return centre
    if centre and str(centre).strip().upper() != impose.upper():
        raise PorteeRefusee(
            f"Cette session ne donne acces qu'aux donnees du centre {impose}. "
            f"La question porte sur le centre {centre} : impossible d'y repondre. "
            f"Indiquer clairement cette limite plutot que de repondre pour {impose} a la place."
        )
    return impose


def restreindre_centres(centres):
    """Filtre une liste de centres (classements, comparaisons) a la portee de
    la session. Un classement inter-centres n'a pas de sens pour un directeur
    qui n'en voit qu'un : la liste renvoyee se reduit alors au sien."""
    impose = centre_impose()
    if impose is None:
        return list(centres)
    return [c for c in centres if str(c).upper() == impose.upper()]

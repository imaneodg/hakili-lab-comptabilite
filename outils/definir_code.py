# ---------------------------------------------------------------------------
# Pose le code d'acces d'un utilisateur, depuis le serveur (08/10/2026).
#
# Sert a reprendre la main si plus personne ne connait le code du
# comptable (il n'existe pas d'ecran pour cela : seul le comptable
# reinitialise les codes des autres). Le code est demande au clavier,
# sans echo, et n'apparait ni dans l'historique du shell ni dans le depot.
#
#   docker compose exec app python outils/definir_code.py comptable
# ---------------------------------------------------------------------------

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import logic.donnees as dl  # noqa: E402


def main():
    if len(sys.argv) != 2:
        print("Usage : python outils/definir_code.py <identifiant>")
        return 2
    ident = sys.argv[1].strip().lower()
    code = getpass.getpass(f"Nouveau code pour {ident} : ")
    if code != getpass.getpass("Retapez le code : "):
        print("Les deux saisies different : rien n'a ete change.")
        return 1
    try:
        dl.definir_code(ident, code)
    except ValueError as e:
        print(f"Refuse : {e}")
        return 1
    print(f"Code de {ident} enregistre.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

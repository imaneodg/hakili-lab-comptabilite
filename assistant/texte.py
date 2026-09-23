# ---------------------------------------------------------------------------
# Petits outils de texte partages : normalisation pour les comparaisons
# floues, et mise en forme des montants et des periodes pour l'affichage.
# ---------------------------------------------------------------------------

import re
import unicodedata
from datetime import date

MOIS_FR = ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
           "aout", "septembre", "octobre", "novembre", "decembre"]
MOIS_AFFICHAGE = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
                  "août", "septembre", "octobre", "novembre", "décembre"]
MOIS_COURTS = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
               "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def normaliser(texte):
    """Minuscules, sans accents, ponctuation remplacee par des espaces.
    'Tampouy !' -> 'tampouy' ; 'Févr.' -> 'fevr'."""
    if texte is None:
        return ""
    t = unicodedata.normalize("NFKD", str(texte))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def montant(valeur):
    """2150000 -> '2 150 000 F CFA'. Arrondi au franc, espace insecable fine
    evitee pour rester lisible partout (mails, Excel)."""
    if valeur is None:
        return "-"
    n = int(round(float(valeur)))
    signe = "-" if n < 0 else ""
    return f"{signe}{abs(n):,}".replace(",", " ") + " F CFA"


def nombre(valeur):
    if valeur is None:
        return "-"
    return f"{int(round(float(valeur))):,}".replace(",", " ")


def pourcentage(valeur):
    if valeur is None:
        return "-"
    return f"{float(valeur):.1f}".replace(".", ",") + " %"


def date_longue(d):
    """date(2026, 2, 3) -> '3 février 2026'."""
    jour = "1er" if d.day == 1 else str(d.day)
    return f"{jour} {MOIS_AFFICHAGE[d.month - 1]} {d.year}"


def date_courte(d):
    return d.strftime("%d/%m/%Y")


def mois_lisible(aaaamm):
    """'202603' -> 'mars 2026'. Toute autre valeur est rendue telle quelle."""
    s = str(aaaamm)
    if len(s) == 6 and s.isdigit() and 1 <= int(s[4:]) <= 12:
        return f"{MOIS_AFFICHAGE[int(s[4:]) - 1]} {s[:4]}"
    return s


def mois_court(aaaamm):
    s = str(aaaamm)
    if len(s) == 6 and s.isdigit() and 1 <= int(s[4:]) <= 12:
        return f"{MOIS_COURTS[int(s[4:]) - 1]} {s[2:4]}"
    return s


def libelle_periode(du, au, aujourd_hui=None):
    """Libelle humain d'une periode : 'février 2026', '1er trimestre 2026',
    'du 15/03/2026 au 15/04/2026', 'année scolaire 2025-2026'."""
    import calendar
    if du == au:
        return date_longue(du)
    fin_mois = calendar.monthrange(au.year, au.month)[1]
    if du.day == 1 and du.year == au.year and du.month == au.month:
        partiel = au.day != fin_mois
        return f"{MOIS_AFFICHAGE[du.month - 1]} {du.year}" + (" (en cours)" if partiel else "")
    if du.day == 1 and au.day == fin_mois:
        if du.month == 9 and au.month == 8 and au.year == du.year + 1:
            return f"année scolaire {du.year}-{au.year}"
        if du.month == 1 and au.month == 12 and du.year == au.year:
            return f"année {du.year}"
        if du.year == au.year and du.month in (1, 4, 7, 10) and au.month == du.month + 2:
            t = (du.month - 1) // 3 + 1
            return f"{'1er' if t == 1 else str(t) + 'e'} trimestre {du.year}"
        return f"de {mois_lisible(du.strftime('%Y%m'))} à {mois_lisible(au.strftime('%Y%m'))}"
    if du.day == 1 and du.month == 9 and aujourd_hui and au == aujourd_hui:
        return f"année scolaire {du.year}-{du.year + 1} (depuis la rentrée)"
    return f"du {date_courte(du)} au {date_courte(au)}"


def aujourd_hui():
    return date.today()

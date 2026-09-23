# ---------------------------------------------------------------------------
# Comprehension : du texte ecrit par l'utilisateur (ou transmis par le modele)
# aux valeurs exactes attendues par le moteur.
#
# Principe : le modele interprete deja la question (il connait la date du
# jour et la liste des centres), mais chaque outil accepte AUSSI le texte tel
# que l'utilisateur l'a ecrit et le resout ici, de facon deterministe. Chaque
# resolution non evidente produit une phrase d'interpretation ("« saab »
# compris comme Saaba") que le modele restitue.
#
# Quand deux lectures sont possibles, on ne devine pas : Incomprehension est
# levee avec la liste des candidats, et le modele pose la question.
# ---------------------------------------------------------------------------

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from rapidfuzz import fuzz, process

from assistant.referentiel import CENTRE_SIEGE
from assistant.texte import MOIS_FR, libelle_periode, normaliser


class Incomprehension(Exception):
    """Levee quand une valeur ne peut pas etre resolue sans risque d'erreur.

    code : 'centre_ambigu', 'centre_inconnu', 'hors_portee', 'periode_invalide',
           'tiers_ambigu', 'tiers_inconnu', 'categorie_inconnue',
           'journal_inconnu', 'compte_inconnu', 'indicateur_inconnu', ...
    Le message est redige pour etre lu par le modele puis reformule."""

    def __init__(self, code, message, candidats=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.candidats = candidats or []

    def en_dict(self):
        d = {"erreur": self.code, "message": self.message}
        if self.candidats:
            d["candidats"] = self.candidats
        return d


_MOTS_VIDES = {"le", "la", "les", "l", "de", "du", "des", "d", "centre", "centres", "antenne",
               "site", "caisse", "a", "au", "aux", "pour", "sur", "chez", "en", "hakili", "lab"}
_MOTS_TOUS = {"tous", "tout", "toutes", "ensemble", "global", "globalement", "consolide",
              "tous les centres", "l ensemble", "hakili", "hakili lab", "reseau", "total", "partout"}


# =============================================================================
# CENTRES
# =============================================================================

def _cles_centres(R):
    """Toutes les ecritures connues d'un centre -> code."""
    cles = {}
    for code, nom in zip(R.centres["code_centre"], R.centres["intitule"]):
        cles[normaliser(code)] = code
        cles[normaliser(nom)] = code
    for a, code in R.alias.items():
        cles[a] = code
    return cles


def _un_centre(texte, R):
    n = normaliser(texte)
    if not n:
        return None
    cles = _cles_centres(R)
    if n in cles:
        return cles[n]
    reduit = " ".join(m for m in n.split() if m not in _MOTS_VIDES)
    if reduit in cles:
        return cles[reduit]
    n = reduit or n
    # Prefixe (au moins 3 lettres) : "tam" -> Tampouy, "nag" -> Nagrin.
    if len(n) >= 3:
        par_prefixe = {code for cle, code in cles.items() if cle.startswith(n)}
        if len(par_prefixe) == 1:
            return par_prefixe.pop()
        if len(par_prefixe) > 1:
            raise Incomprehension(
                "centre_ambigu", f"« {texte} » peut designer plusieurs centres.",
                sorted(R.nom_centre(c) for c in par_prefixe))
    elif len(n) < 3:
        par_prefixe = {code for cle, code in cles.items() if cle.startswith(n)}
        if len(par_prefixe) > 1:
            raise Incomprehension(
                "centre_ambigu", f"« {texte} » peut designer plusieurs centres.",
                sorted(R.nom_centre(c) for c in par_prefixe))
    # Ressemblance : fautes de frappe ("sabaa", "tampuy", "pisi").
    trouves = process.extract(n, list(cles.keys()), scorer=fuzz.ratio, limit=10, score_cutoff=70)
    meilleur_par_code = {}
    for cle, score, _ in trouves:
        code = cles[cle]
        meilleur_par_code[code] = max(score, meilleur_par_code.get(code, 0))
    if not meilleur_par_code:
        return None
    classes = sorted(meilleur_par_code.items(), key=lambda x: -x[1])
    if len(classes) == 1 or classes[0][1] - classes[1][1] >= 8:
        return classes[0][0]
    raise Incomprehension(
        "centre_ambigu", f"« {texte} » peut designer plusieurs centres.",
        [R.nom_centre(c) for c, _ in classes[:4]])


def resoudre_centres(valeur, R, portee=None):
    """-> (liste de codes, interpretation ou None).

    valeur : None, "", "tous" -> tous les centres de la portee (siege exclu) ;
             "saab", "Saaba et Tampouy", ["SAA", "tam"]...
    portee : liste des centres autorises pour la session, None = tous."""
    autorises = list(portee) if portee is not None else None
    if autorises is not None and not autorises:
        raise Incomprehension("hors_portee", "Cette session n'a acces a aucun centre.")
    if isinstance(valeur, (list, tuple)):
        morceaux = [str(v) for v in valeur if str(v).strip()]
    else:
        texte = str(valeur or "").strip()
        morceaux = [m for m in re.split(r"\s*(?:,|;|/|\+|&|\bet\b)\s*", texte) if m.strip()] if texte else []
    if not morceaux or any(normaliser(m) in _MOTS_TOUS for m in morceaux):
        codes = autorises or R.centres_actifs()
        return codes, None
    codes, notes = [], []
    for m in morceaux:
        code = _un_centre(m, R)
        if code is None:
            raise Incomprehension(
                "centre_inconnu",
                f"Aucun centre ne correspond a « {m} ».",
                [R.nom_centre(c) for c in R.centres_actifs(avec_siege=True)])
        if autorises is not None and code not in autorises:
            raise Incomprehension(
                "hors_portee",
                f"Cette session n'a acces qu'aux donnees de "
                f"{', '.join(R.nom_centre(c) for c in autorises)}. "
                f"{R.nom_centre(code)} releve du comptable du siege.")
        if code not in codes:
            codes.append(code)
        n = normaliser(m)
        if n not in (normaliser(code), normaliser(R.nom_centre(code))):
            notes.append(f"« {m} » = {R.nom_centre(code)}")
    return codes, ("; ".join(notes) or None)


# =============================================================================
# PERIODES
# =============================================================================

@dataclass
class Periode:
    du: date
    au: date
    libelle: str
    en_cours: bool = False           # la periode n'est pas terminee
    interpretation: Optional[str] = None

    def mois(self):
        """Mois AAAAMM couverts, du premier au dernier."""
        res, a, m = [], self.du.year, self.du.month
        while (a, m) <= (self.au.year, self.au.month):
            res.append(f"{a}{m:02d}")
            m += 1
            if m == 13:
                a, m = a + 1, 1
        return res

    def en_dict(self):
        return {"du": self.du.isoformat(), "au": self.au.isoformat(), "libelle": self.libelle,
                "en_cours": self.en_cours}


_MOIS_VARIANTES = {
    "janvier": 1, "janv": 1, "jan": 1,
    "fevrier": 2, "fevr": 2, "fev": 2, "fevrie": 2,
    "mars": 3, "mar": 3,
    "avril": 4, "avr": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7, "juil": 7,
    "aout": 8, "aou": 8,
    "septembre": 9, "sept": 9, "sep": 9,
    "octobre": 10, "oct": 10,
    "novembre": 11, "nov": 11,
    "decembre": 12, "dec": 12,
}
_ORDINAUX = {"premier": 1, "1er": 1, "1ere": 1, "premiere": 1, "1": 1,
             "deuxieme": 2, "second": 2, "seconde": 2, "2e": 2, "2eme": 2, "2": 2,
             "troisieme": 3, "3e": 3, "3eme": 3, "3": 3,
             "quatrieme": 4, "dernier": 4, "4e": 4, "4eme": 4, "4": 4}


def _mois_du_mot(mot):
    """'fevirer' -> 2, 'aout' -> 8, 'mois' -> None."""
    if not mot or mot.isdigit() or len(mot) < 3:
        return None
    if mot in _MOIS_VARIANTES:
        return _MOIS_VARIANTES[mot]
    if len(mot) < 4:
        return None
    r = process.extractOne(mot, MOIS_FR, scorer=fuzz.ratio, score_cutoff=72)
    return MOIS_FR.index(r[0]) + 1 if r else None


def _fin_mois(a, m):
    return date(a, m, calendar.monthrange(a, m)[1])


def _annee_passee(mois, jour_ref):
    """Annee de l'occurrence passee la plus proche d'un mois donne sans annee."""
    return jour_ref.year if mois <= jour_ref.month else jour_ref.year - 1


def _annee(txt):
    a = int(txt)
    return 2000 + a if a < 100 else a


def _debut_annee_scolaire(j):
    return date(j.year if j.month >= 9 else j.year - 1, 9, 1)


def _intervalle(expr, auj):
    """Une expression simple -> (debut, fin). None si non reconnue."""
    brut = expr.strip().lower()
    n = normaliser(expr)
    if not n:
        return None

    # --- formats numeriques ------------------------------------------------
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", brut)
    if m:
        d = date(int(m[1]), int(m[2]), int(m[3]))
        return d, d
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})", brut)
    if m:
        d = date(_annee(m[3]), int(m[2]), int(m[1]))
        return d, d
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{4})", brut)            # 03/2026
    if m and 1 <= int(m[1]) <= 12:
        a, mo = int(m[2]), int(m[1])
        return date(a, mo, 1), _fin_mois(a, mo)
    m = re.fullmatch(r"(\d{4})[/.\-]?(\d{2})", brut)              # 202603, 2026-03
    if m and 1 <= int(m[2]) <= 12 and 1990 < int(m[1]) < 2100:
        a, mo = int(m[1]), int(m[2])
        return date(a, mo, 1), _fin_mois(a, mo)
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})", brut)            # 15/03 (jour/mois)
    if m and 1 <= int(m[2]) <= 12:
        mo = int(m[2])
        a = _annee_passee(mo, auj)
        d = date(a, mo, int(m[1]))
        return d, d
    m = re.fullmatch(r"(\d{4})\s*[-/ ]\s*(\d{4})", brut)           # 2025-2026 : annee scolaire
    if m and int(m[2]) == int(m[1]) + 1:
        return date(int(m[1]), 9, 1), date(int(m[2]), 8, 31)
    m = re.fullmatch(r"(?:annee civile |annee )?(\d{4})", n)       # 2026 : annee civile
    if m and 1990 < int(m[1]) < 2100:
        a = int(m[1])
        return date(a, 1, 1), date(a, 12, 31)

    # --- expressions relatives --------------------------------------------
    if n in ("aujourd hui", "auj", "ce jour", "aujourdhui"):
        return auj, auj
    if n == "hier":
        return auj - timedelta(days=1), auj - timedelta(days=1)
    if n in ("avant hier", "avant-hier"):
        return auj - timedelta(days=2), auj - timedelta(days=2)
    if n in ("cette semaine", "semaine en cours"):
        return auj - timedelta(days=auj.weekday()), auj
    if n in ("la semaine derniere", "semaine derniere", "semaine passee", "la semaine passee"):
        lundi = auj - timedelta(days=auj.weekday() + 7)
        return lundi, lundi + timedelta(days=6)
    if n in ("ce mois", "ce mois ci", "mois en cours", "le mois en cours", "mois courant", "ce moi"):
        return date(auj.year, auj.month, 1), auj
    if n in ("le mois dernier", "mois dernier", "mois precedent", "le mois precedent",
             "mois passe", "le mois passe"):
        p = date(auj.year, auj.month, 1) - timedelta(days=1)
        return date(p.year, p.month, 1), p
    if n in ("ce trimestre", "trimestre en cours"):
        t0 = 3 * ((auj.month - 1) // 3) + 1
        return date(auj.year, t0, 1), auj
    if n in ("le trimestre dernier", "trimestre dernier", "trimestre precedent"):
        t0 = 3 * ((auj.month - 1) // 3) + 1
        fin = date(auj.year, t0, 1) - timedelta(days=1)
        return date(fin.year, fin.month - 2, 1), fin
    if n in ("cette annee scolaire", "annee scolaire en cours", "l annee scolaire en cours",
             "cette annee", "annee en cours", "l annee en cours", "rentree", "la rentree",
             "cette rentree", "annee scolaire", "l annee scolaire", "cette annee academique",
             "annee academique en cours"):
        return _debut_annee_scolaire(auj), auj
    if n in ("l annee scolaire derniere", "annee scolaire derniere", "annee scolaire precedente",
             "l annee scolaire precedente", "l annee derniere", "annee derniere",
             "l an dernier", "an dernier", "annee precedente", "l annee precedente",
             "annee academique precedente", "l annee academique derniere"):
        d0 = _debut_annee_scolaire(auj)
        return date(d0.year - 1, 9, 1), date(d0.year, 8, 31)
    if n in ("cette annee civile", "annee civile", "l annee civile", "annee civile en cours"):
        return date(auj.year, 1, 1), auj
    if n in ("l annee civile derniere", "annee civile derniere", "annee civile precedente"):
        return date(auj.year - 1, 1, 1), date(auj.year - 1, 12, 31)

    mots = n.split()
    # --- trimestres et semestres -----------------------------------------
    m = re.fullmatch(r"t([1-4])(?: (\d{2}|\d{4}))?", n)
    if m:
        t = int(m[1])
        a = _annee(m[2]) if m[2] else (auj.year if 3 * (t - 1) + 1 <= auj.month else auj.year - 1)
        return date(a, 3 * (t - 1) + 1, 1), _fin_mois(a, 3 * t)
    if "trimestre" in mots:
        t = next((_ORDINAUX[x] for x in mots if x in _ORDINAUX), None)
        annees = [x for x in mots if x.isdigit() and len(x) in (2, 4) and x not in _ORDINAUX]
        if t:
            a = _annee(annees[0]) if annees else (auj.year if 3 * (t - 1) + 1 <= auj.month else auj.year - 1)
            return date(a, 3 * (t - 1) + 1, 1), _fin_mois(a, 3 * t)
    if "semestre" in mots:
        s = next((_ORDINAUX[x] for x in mots if x in _ORDINAUX), None)
        annees = [x for x in mots if x.isdigit() and len(x) in (2, 4) and x not in _ORDINAUX]
        if s in (1, 2):
            a = _annee(annees[0]) if annees else (auj.year if 6 * (s - 1) + 1 <= auj.month else auj.year - 1)
            return date(a, 6 * (s - 1) + 1, 1), _fin_mois(a, 6 * s)
    if "annee" in mots and "scolaire" in mots or "academique" in mots:
        annees = [int(x) for x in mots if x.isdigit() and len(x) == 4]
        if annees:
            a0 = annees[0] if len(annees) == 1 or annees[1] == annees[0] + 1 else annees[0]
            return date(a0, 9, 1), date(a0 + 1, 8, 31)

    # --- "15 mars 2026", "mars 26", "fevirer", "le 3 mars" ------------------
    mots = [x for x in mots if x not in ("le", "la", "l", "en", "de", "du", "mois", "d", "au", "a")]
    mois_idx = [(i, _mois_du_mot(x)) for i, x in enumerate(mots)]
    mois_idx = [(i, mo) for i, mo in mois_idx if mo]
    if len(mois_idx) == 1:
        i, mo = mois_idx[0]
        autres = [x for j, x in enumerate(mots) if j != i]
        if all(x.isdigit() for x in autres) and len(autres) <= 2:
            jour, annee = None, None
            for j, x in enumerate(mots):
                if j == i or not x.isdigit():
                    continue
                if j < i and len(x) <= 2 and jour is None:
                    jour = int(x)
                elif j > i and len(x) in (2, 4):
                    annee = _annee(x)
                else:
                    return None
            if annee is None:
                annee = _annee_passee(mo, auj)
            if jour:
                return date(annee, mo, jour), date(annee, mo, jour)
            return date(annee, mo, 1), _fin_mois(annee, mo)
    return None


_SEPARATEURS = [
    r"^(?:du|de|depuis le|entre le|entre)\s+(.+?)\s+(?:au|a|et|jusqu au|jusqu a|jusqu'au|jusqu'a|->)\s+(.+)$",
    r"^(.+?)\s+(?:au|a|->|-)\s+(.+)$",
]


def resoudre_periode(periode=None, du=None, au=None, auj=None, defaut="dernier_mois"):
    """-> Periode. Accepte :
      - du / au au format ISO (ou tout format reconnu par _intervalle) ;
      - periode en texte libre : "fevirer", "mars 26", "T1", "depuis la rentree",
        "du 15/03 au 15/04", "entre janvier et mars", "2025-2026"...
    Sans rien : le dernier mois complet (defaut="dernier_mois")."""
    auj = auj or date.today()
    note = None
    try:
        if du or au:
            i_du = _intervalle(str(du), auj) if du else None
            i_au = _intervalle(str(au), auj) if au else None
            if du and not i_du or au and not i_au:
                raise ValueError
            debut = i_du[0] if i_du else None
            fin = i_au[1] if i_au else auj
            if debut is None:
                raise ValueError
        elif periode and str(periode).strip():
            texte = str(periode).strip()
            brut = normaliser(texte) if not re.search(r"\d[/\-.]\d", texte) else texte.lower().strip()
            intervalle = _intervalle(texte, auj)
            if intervalle is None:
                for motif in _SEPARATEURS:
                    m = re.match(motif, brut)
                    if m:
                        a, b = _intervalle(m[1], auj), _intervalle(m[2], auj)
                        if a and b:
                            intervalle = (a[0], b[1])
                            # "de novembre a fevrier" : le debut est dans l'annee precedente
                            if intervalle[0] > intervalle[1] and not re.search(r"\d{4}", m[1]):
                                d0 = a[0]
                                intervalle = (date(d0.year - 1, d0.month, d0.day), b[1])
                            break
            if intervalle is None:
                m = re.match(r"^(?:depuis|a partir de|a partir du|depuis le|depuis la|depuis l)\s+(.+)$",
                             normaliser(texte))
                if m:
                    a = _intervalle(m[1], auj)
                    if a:
                        intervalle = (a[0], auj)
            if intervalle is None:
                m = re.match(r"^(?:jusqu au|jusqu a|avant le|avant)\s+(.+)$", normaliser(texte))
                if m:
                    b = _intervalle(m[1], auj)
                    if b:
                        intervalle = (_debut_annee_scolaire(b[1]), b[1])
                        note = "debut fixe a la rentree scolaire"
            if intervalle is None:
                raise ValueError
            debut, fin = intervalle
            n = normaliser(texte)
            if n in ("cette annee", "annee en cours", "l annee en cours"):
                note = "« cette annee » lu comme l'annee scolaire (septembre-aout)"
            elif n in ("l annee derniere", "annee derniere", "l an dernier", "an dernier",
                       "annee precedente", "l annee precedente"):
                note = "« l'annee derniere » lu comme l'annee scolaire precedente"
        else:
            if defaut == "annee_scolaire":
                debut, fin = _debut_annee_scolaire(auj), auj
            else:
                p = date(auj.year, auj.month, 1) - timedelta(days=1)
                debut, fin = date(p.year, p.month, 1), p
            note = "aucune periode precisee"
    except (ValueError, TypeError, IndexError):
        raise Incomprehension(
            "periode_invalide",
            f"Periode non comprise : « {periode or ''}{' ' if periode else ''}{du or ''} {au or ''} »."
            .replace("  ", " ") + " Formats acceptes : 'mars 2026', '202603', '2026-03-15', "
            "'T1', 'du 15/03/2026 au 15/04/2026', 'depuis la rentree', 'l'annee scolaire derniere'.")
    if debut > fin:
        debut, fin = fin, debut
    return Periode(du=debut, au=fin, libelle=libelle_periode(debut, fin, auj),
                   en_cours=fin >= auj, interpretation=note)


# =============================================================================
# TIERS
# =============================================================================

def chercher_tiers(texte, R, limite=8, type_tiers=None):
    """Candidats pour un nom ou un code de tiers, du plus au moins probable.
    -> [{"code", "nom", "type", "score"}]"""
    t = R.ref["tiers"]
    if type_tiers:
        t = t[t["type"] == type_tiers]
    if len(t) == 0 or not str(texte or "").strip():
        return []
    n = normaliser(texte)
    codes = list(t["code_tiers"].astype(str))
    noms = list(t["intitule"].astype(str))
    types = list(t["type"].astype(str))
    exacts = [i for i, c in enumerate(codes) if c.upper() == str(texte).strip().upper()]
    if exacts:
        i = exacts[0]
        return [{"code": codes[i], "nom": noms[i], "type": types[i], "score": 100}]
    normes = [normaliser(x) for x in noms]
    resultats = {}
    mots = n.split()
    for i, nom in enumerate(normes):
        if nom == n:
            resultats[i] = 100
        elif all(m in nom.split() for m in mots):
            resultats[i] = 95
        elif n in nom:
            resultats[i] = 90
    for nom, score, i in process.extract(n, normes, scorer=fuzz.token_sort_ratio, limit=limite * 2,
                                         score_cutoff=60):
        resultats[i] = max(resultats.get(i, 0), score)
    for nom, score, i in process.extract(n, normes, scorer=fuzz.partial_token_set_ratio,
                                         limit=limite * 2, score_cutoff=85):
        resultats[i] = max(resultats.get(i, 0), min(score, 88))
    classes = sorted(resultats.items(), key=lambda x: (-x[1], noms[x[0]]))[:limite]
    return [{"code": codes[i], "nom": noms[i], "type": types[i], "score": int(s)} for i, s in classes]


def resoudre_tiers(texte, R):
    """-> (liste de codes, interpretation). Un seul candidat clair est retenu ;
    plusieurs noms proches -> Incomprehension avec la liste."""
    candidats = chercher_tiers(texte, R, limite=12)
    if not candidats:
        raise Incomprehension("tiers_inconnu", f"Aucun eleve, fournisseur ou membre du personnel "
                                               f"ne correspond a « {texte} ».")
    top = candidats[0]
    if top["score"] == 100 and (len(candidats) == 1 or candidats[1]["score"] < 100):
        codes = [top["code"]]
    else:
        forts = [c for c in candidats if c["score"] >= 90]
        if len(forts) == 1:
            codes = [forts[0]["code"]]
        elif not forts and top["score"] >= 75 and (len(candidats) == 1 or top["score"] - candidats[1]["score"] >= 10):
            codes = [top["code"]]
        else:
            raise Incomprehension(
                "tiers_ambigu", f"Plusieurs tiers correspondent a « {texte} ».",
                [f"{c['nom']} ({c['type']}, {c['code']})" for c in (forts or candidats)[:8]])
    nom = R.nom_tiers(codes[0])
    note = None if normaliser(nom) == normaliser(texte) else f"« {texte} » = {nom}"
    return codes, note


# =============================================================================
# CATEGORIES, JOURNAUX, COMPTES
# =============================================================================

_SYNONYMES_CATEGORIE = {
    "vacation": "vacations", "vacations": "vacations", "vacataire": "vacations",
    "vacataires": "vacations", "enseignant": "vacations", "enseignants": "vacations",
    "prof": "vacations", "profs": "vacations", "professeur": "vacations",
    "professeurs": "vacations", "honoraires": "vacations",
    "salaire": "salaires", "salaires": "salaires", "paie": "salaires", "remuneration": "salaires",
    "loyer": "loyer", "loyers": "loyer", "location": "loyer", "bail": "loyer",
    "eau": "eau", "onea": "eau",
    "electricite": "electricite", "courant": "electricite", "sonabel": "electricite",
    "cash power": "electricite", "lumiere": "electricite",
    "gardien": "gardiennage", "gardiennage": "gardiennage", "securite": "gardiennage",
    "internet": "internet_telephone", "telephone": "internet_telephone", "wifi": "internet_telephone",
    "credit": "internet_telephone", "communication": "internet_telephone", "canal": "internet_telephone",
    "nettoyage": "nettoyage", "entretien": "nettoyage", "menage": "nettoyage",
    "fourniture": "fournitures", "fournitures": "fournitures", "bureau": "fournitures",
    "carburant": "carburant", "essence": "carburant", "gasoil": "carburant", "transport": "carburant",
    "impression": "impressions", "impressions": "impressions", "photocopie": "impressions",
    "photocopies": "impressions", "tirage": "impressions",
    "maintenance": "maintenance", "reparation": "maintenance", "equipement": "maintenance",
    "eau minerale": "eau_minerale", "reception": "eau_minerale", "restauration": "eau_minerale",
    "frais bancaires": "frais_bancaires", "banque": "frais_bancaires", "mobile money": "frais_bancaires",
    "non ventile": "non_ventile", "non ventilees": "non_ventile", "non rattache": "non_ventile",
    "non rattachees": "non_ventile",
}
_GROUPES = {
    "masse salariale": "masse_salariale", "personnel": "masse_salariale",
    "charges de personnel": "masse_salariale",
    "charges fixes": "charges_fixes", "frais fixes": "charges_fixes", "fixes": "charges_fixes",
}


def resoudre_categories(texte, R):
    """-> liste de codes de categorie. 'masse salariale' -> [vacations, salaires]."""
    n = normaliser(texte)
    if not n:
        return []
    if n in _GROUPES:
        g = _GROUPES[n]
        return [c.code for c in R.categories if c.groupe == g]
    codes = {c.code: c.code for c in R.categories}
    for c in R.categories:
        codes[normaliser(c.libelle)] = c.code
        codes[normaliser(c.code)] = c.code
    if n in codes:
        return [codes[n]]
    if n in _SYNONYMES_CATEGORIE:
        return [_SYNONYMES_CATEGORIE[n]]
    if n.startswith("classe") or n.startswith("6"):
        chiffres = re.sub(r"\D", "", n)
        if len(chiffres) >= 2:
            return [f"classe_{chiffres[:2]}"]
    choix = list(codes.keys()) + list(_SYNONYMES_CATEGORIE.keys())
    r = process.extractOne(n, choix, scorer=fuzz.WRatio, score_cutoff=82)
    if r:
        return [codes.get(r[0]) or _SYNONYMES_CATEGORIE[r[0]]]
    raise Incomprehension("categorie_inconnue", f"Categorie de charge non reconnue : « {texte} ».",
                          [c.libelle for c in R.categories])


def resoudre_journaux(texte, R):
    """-> liste de codes journal de tresorerie. 'caisse principale' -> [CP] ;
    'caisses' -> [CP, CMD] ; 'banque' -> [Banque]."""
    jx = R.journaux()
    treso = jx[jx["type"].fillna("tresorerie") == "tresorerie"]
    physiques = list(treso.loc[treso["caisse_physique"] == "oui", "journal"]) \
        if "caisse_physique" in treso.columns else []
    actifs = treso[treso["actif"].fillna("oui") == "oui"] if "actif" in treso.columns else treso
    banques = [j for j in actifs["journal"] if j not in physiques]
    n = normaliser(texte)
    if not n or n in ("tout", "tous", "toutes", "tresorerie", "toutes les caisses et la banque"):
        return list(actifs["journal"])
    if n in ("caisse", "caisses", "les caisses", "especes", "liquide", "cash"):
        return physiques
    table = {}
    for j, intitule in zip(treso["journal"], treso["intitule"]):
        table[normaliser(j)] = j
        table[normaliser(intitule)] = j
    for j in physiques:
        if j.upper() == "CP":
            for s in ("caisse principale", "grande caisse", "principale", "cp", "caisse cp"):
                table[s] = j
        if j.upper() == "CMD":
            for s in ("caisse menues depenses", "menues depenses", "petite caisse", "menue depense",
                      "menues", "cmd", "caisse cmd", "petites depenses"):
                table[s] = j
    for j in banques:
        for s in ("banque", "compte bancaire", "compte en banque", "bank", "cbi", "la banque"):
            table.setdefault(s, j)
    if n in table:
        return [table[n]]
    r = process.extractOne(n, list(table.keys()), scorer=fuzz.WRatio, score_cutoff=80)
    if r:
        return [table[r[0]]]
    raise Incomprehension("journal_inconnu", f"Caisse ou journal non reconnu : « {texte} ».",
                          [f"{j} ({i})" for j, i in zip(actifs["journal"], actifs["intitule"])])


def resoudre_compte(texte, R):
    """-> prefixe de compte (chaine de chiffres). '6' -> toutes les charges ;
    '411000' -> ce compte ; 'frais de dossier' -> 707810 (intitule le plus proche)."""
    t = str(texte or "").strip()
    chiffres = re.sub(r"\s", "", t)
    if chiffres.isdigit():
        return chiffres
    comptes = R.ref["comptes"]
    normes = [normaliser(x) for x in comptes["intitule"]]
    r = process.extractOne(normaliser(t), normes, scorer=fuzz.WRatio, score_cutoff=80)
    if r:
        return str(comptes["compte"].iloc[r[2]])
    raise Incomprehension("compte_inconnu", f"Compte non reconnu : « {texte} ».")

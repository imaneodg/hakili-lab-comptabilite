# ---------------------------------------------------------------------------
# Les 10 outils exposes au modele.
#
# Ils tournent DANS l'application (plus de sous-processus MCP) : ils recoivent
# le contexte de la conversation par fermeture - donc la portee de
# l'utilisateur connecte - et renvoient un ContentToolResult avec :
#   - value   : ce que lit le modele (court, chiffre, deja interprete) ;
#   - display : la carte montree a l'utilisateur (tableau replie, ou
#               graphique ouvert), jamais le JSON brut.
#
# Une valeur incomprise (centre ambigu, periode illisible...) n'est pas une
# erreur technique : l'outil renvoie {"erreur": ..., "candidats": [...]} pour
# que le modele pose la bonne question.
# ---------------------------------------------------------------------------

import json
import logging
import time
from typing import Optional

from chatlas import ContentToolResult
from htmltools import tags

from assistant import moteur, rendu
from assistant.comprehension import Incomprehension

logger = logging.getLogger("hakili.assistant")

_ICONES = {"analyse": "bar-chart-line", "comparaison": "arrow-left-right", "soldes": "wallet2",
           "liste": "list-ul", "controle": "shield-check", "sql": "database", "graphique": "graph-up",
           "contexte": "info-circle", "point": "speedometer2", "recherche": "search", "precision": "question-circle",
           "erreur": "exclamation-triangle"}


def _icone(nom):
    return tags.i(class_=f"bi bi-{_ICONES.get(nom, 'dot')}")


def _json(valeur):
    return json.dumps(valeur, ensure_ascii=False, default=str, separators=(",", ":"))


def _carte(valeur, titre, html=None, texte=None, ouverte=False, icone="analyse"):
    display = {"title": titre, "icon": _icone(icone), "show_request": False, "open": ouverte}
    if html is not None:
        display["html"] = html
        display["full_screen"] = True
    elif texte is not None:
        display["text"] = texte
    return ContentToolResult(value=_json(valeur), model_format="as_is", extra={"display": display})


def _executer(nom, trace, fonction, *args, **kwargs):
    """Appelle une fonction du moteur et habille le resultat. Tout echec est
    rendu lisible pour le modele ; le detail technique va au journal."""
    debut = time.perf_counter()
    appel = {"outil": nom, "parametres": {k: v for k, v in kwargs.items() if v not in (None, "", [])}}
    try:
        res, payload = fonction(*args, **kwargs)
        appel["resultat"] = res.id
        if res.type == "point":
            return _carte(payload, res.titre, html=rendu.tableau_de_bord(res.donnees), ouverte=True,
                          icone="point")
        return _carte(payload, res.titre, html=rendu.tableau(res),
                      icone=res.type if res.type in _ICONES else "analyse")
    except Incomprehension as e:
        appel["incomprehension"] = e.code
        return _carte(e.en_dict(), "Précision nécessaire", texte=e.message, icone="precision")
    except Exception as e:
        logger.exception("Outil %s en echec", nom)
        appel["erreur"] = str(e)[:300]
        return _carte({"erreur": "technique",
                       "message": "Le calcul a échoué pour une raison technique. Le dire "
                                  "simplement, sans donner de chiffre."},
                      "Calcul impossible", texte="Le calcul a échoué (détail dans le journal de l'application).",
                      icone="erreur")
    finally:
        appel["duree_ms"] = int((time.perf_counter() - debut) * 1000)
        trace.append(appel)


def creer_outils(ctx, journal):
    """Fonctions-outils liees a une conversation. `journal` (liste) recoit la
    trace de chaque appel pour la table journal_assistant."""

    def contexte() -> ContentToolResult:
        """Date du jour, periode couverte par les donnees, dernier mois complet, centres
        accessibles, caisses, categories de charge et limites connues des donnees. A appeler
        si un de ces elements manque pour interpreter la question."""
        journal.append({"outil": "contexte"})
        try:
            v = moteur.contexte(ctx)
        except Exception:
            logger.exception("Outil contexte en echec")
            return _carte({"erreur": "technique"}, "Erreur technique", texte="Contexte indisponible.",
                          icone="erreur")
        return _carte(v, "Contexte des donnees", texte=f"Donnees du {v['donnees']['du']} au "
                                                       f"{v['donnees']['au']}.", icone="contexte")

    def analyser(indicateurs: Optional[list[str]] = None, periode: Optional[str] = None,
                 du: Optional[str] = None, au: Optional[str] = None, centres: Optional[str] = None,
                 regrouper_par: Optional[list[str]] = None, categorie: Optional[str] = None,
                 compte: Optional[str] = None, tiers: Optional[str] = None,
                 journal_caisse: Optional[str] = None, statut: str = "tous") -> ContentToolResult:
        """Calcule un ou plusieurs chiffres sur une periode, pour un ou plusieurs centres,
        eventuellement detailles. Outil principal pour toute question chiffree.

        indicateurs - argent reel (defaut, ce que le directeur appelle recettes et depenses) :
          encaissements (argent recu), decaissements (argent depense), flux_net (reste = recu -
          depense), frais_scolarite, autres_encaissements, marge_pct ;
          rentabilite (rattachee au mois concerne, pour "benefice", "ce que ca a rapporte /
          coute") : produits, charges, resultat, marge_resultat_pct, masse_salariale,
          charges_fixes, part_masse_salariale_pct, part_charges_fixes_pct ;
          autres : part_pct, eleves_payants, encaissement_par_eleve, nb_pieces, en_attente_471.
          Les mots courants sont compris ("recettes", "depenses", "benefice", "vacations").
        periode : texte libre tel qu'ecrit ("fevrier", "mars 26", "ce mois-ci", "depuis la
          rentree", "du 15/03 au 15/04"), ou du/au en AAAA-MM-JJ. Rien = mois en cours (ou le
          dernier mois qui a des operations).
        centres : texte libre ("saab", "Saaba et Tampouy", "tous"). Rien = tous les centres.
        regrouper_par : 0 a 2 parmi centre, mois, semaine, jour, annee_scolaire, type (type de
          recette ou de depense), compte, tiers, caisse, statut.
        categorie : filtre par type ("loyer", "vacations", "frais de cours", "depenses fixes").
        compte : numero ou prefixe de compte. tiers : nom d'un eleve, fournisseur, enseignant.
        journal_caisse : "caisse principale", "petite caisse", "banque", "caisses" (especes).
        statut : tous (defaut), valide, non_valide."""
        return _executer("analyser", journal, moteur.analyser, ctx, indicateurs=indicateurs,
                         periode=periode, du=du, au=au, centres=centres, regrouper_par=regrouper_par,
                         categorie=categorie, compte=compte, tiers=tiers, journal=journal_caisse,
                         statut=statut)

    def comparer(indicateurs: Optional[list[str]] = None, periode: Optional[str] = None,
                 du: Optional[str] = None, au: Optional[str] = None,
                 reference: Optional[str] = None, centres: Optional[str] = None,
                 regrouper_par: Optional[list[str]] = None,
                 categorie: Optional[str] = None) -> ContentToolResult:
        """Compare des indicateurs entre une periode et une periode de reference, avec l'ecart
        en valeur et en %. reference : "periode precedente" (defaut : mois precedent pour un
        mois, periode de meme duree juste avant sinon), "annee precedente" (memes dates un an
        plus tot), ou une periode en texte libre. regrouper_par : centre, categorie, compte,
        tiers, journal (pas de regroupement par mois ici : utiliser analyser)."""
        return _executer("comparer", journal, moteur.comparer, ctx, indicateurs=indicateurs,
                         periode=periode, du=du, au=au, reference=reference, centres=centres,
                         regrouper_par=regrouper_par, categorie=categorie)

    def soldes(date_arret: Optional[str] = None, centres: Optional[str] = None,
               journal_caisse: Optional[str] = None, seuil: Optional[float] = None) -> ContentToolResult:
        """Solde des caisses (CP, CMD, une par centre) et de la banque (compte unique commun a
        tous les centres, donne a part) a une date (aujourd'hui par defaut). seuil : signale
        les caisses sous ce montant, uniquement si l'utilisateur en donne un."""
        return _executer("soldes", journal, moteur.soldes, ctx, date_arret=date_arret,
                         centres=centres, journal=journal_caisse, seuil=seuil)

    def lister_ecritures(periode: Optional[str] = None, du: Optional[str] = None,
                         au: Optional[str] = None, centres: Optional[str] = None,
                         compte: Optional[str] = None, tiers: Optional[str] = None,
                         journal_caisse: Optional[str] = None, texte: Optional[str] = None,
                         montant_min: Optional[float] = None, statut: str = "tous",
                         sens: Optional[str] = None, vue: str = "mouvements",
                         limite: int = 25) -> ContentToolResult:
        """Liste des operations, les plus recentes d'abord : mouvements du jour, derniers
        encaissements (sens="recu") ou paiements (sens="paye"), grosses depenses (montant_min),
        historique d'un eleve ou d'un fournisseur (tiers), recherche dans les libelles (texte).
        vue="mouvements" (defaut : date, centre, caisse, type, libelle, recu, paye) ou
        "detail" (lignes comptables, si on le demande). Rien = annee scolaire en cours.
        Pour un total, utiliser analyser."""
        return _executer("lister_ecritures", journal, moteur.lister_ecritures, ctx, periode=periode,
                         du=du, au=au, centres=centres, compte=compte, tiers=tiers,
                         journal=journal_caisse, texte=texte, montant_min=montant_min, statut=statut,
                         sens=sens, vue=vue, limite=limite)

    def chercher(texte: str, type_recherche: str = "tiers") -> ContentToolResult:
        """Recherche approximative (fautes tolerees) d'un eleve, fournisseur ou membre du
        personnel (type_recherche : tiers, eleve, fournisseur, personnel), d'un compte (compte)
        ou des categories de charge (categorie). A utiliser quand un nom est ambigu."""
        journal.append({"outil": "chercher", "parametres": {"texte": texte, "type": type_recherche}})
        try:
            v = moteur.chercher(ctx, texte, type_recherche)
        except Exception:
            logger.exception("Outil chercher en echec")
            return _carte({"erreur": "technique"}, "Erreur technique", texte="Recherche impossible.",
                          icone="erreur")
        cle = next(iter(v))
        lignes = [" - ".join(str(x) for x in e.values() if x != e.get("score")) for e in v[cle]]
        return _carte(v, f"Recherche : {texte}", texte="\n".join(lignes) or "Aucun resultat.",
                      icone="recherche")

    def controles(type_controle: str, periode: Optional[str] = None, du: Optional[str] = None,
                  au: Optional[str] = None, centres: Optional[str] = None) -> ContentToolResult:
        """Detail d'un point de controle. type_controle : doublons (paiements en double
        possibles), dates_douteuses (dates erronees), a_corriger, non_validees, compte_attente
        (operations a classer), transferts_centres (argent envoye entre centres : recu, parti,
        a regulariser), envois_siao (combien chaque centre a envoye au SIAO sur la periode),
        non_ventile (depenses sans type), depenses_inhabituelles, imputations_411 (paiements
        mal classes dans le compte des eleves), desequilibrees, caisses_negatives.
        Pour une vue d'ensemble, utiliser a_verifier."""
        return _executer("controles", journal, moteur.controles, ctx, type_controle=type_controle,
                         periode=periode, du=du, au=au, centres=centres)

    def personnel(type_demande: str = "paiements", periode: Optional[str] = None,
                  du: Optional[str] = None, au: Optional[str] = None, centres: Optional[str] = None,
                  personne: Optional[str] = None) -> ContentToolResult:
        """Personnel. type_demande : paiements (vacations et salaires verses, par personne),
        multi_centres (personnes payees sur plusieurs centres), avances (avances et prets au
        personnel non rembourses). personne : nom approximatif accepte."""
        return _executer("personnel", journal, moteur.personnel, ctx, type_demande=type_demande,
                         periode=periode, du=du, au=au, centres=centres, personne=personne)

    def point_financier(periode: Optional[str] = None,
                        centres: Optional[str] = None) -> ContentToolResult:
        """La situation en un coup d'oeil : argent disponible (caisses et banque), argent recu
        et depense sur le mois (compare au mois precedent) et depuis la rentree, plus grosses
        depenses, situation de chaque centre, envois au SIAO, points a verifier. A utiliser
        pour "fais-moi le point", "situation financiere", "resume du mois", "ou en est-on".
        periode : rien = mois en cours (ou dernier mois avec des operations)."""
        return _executer("point_financier", journal, moteur.point_financier, ctx, periode=periode,
                         centres=centres)

    def a_verifier(centres: Optional[str] = None) -> ContentToolResult:
        """Tous les points a verifier en une liste (operations en attente de validation ou a
        corriger, a classer, paiements en double possibles, dates erronees, paiements mal
        classes, caisses passees sous zero, envois entre centres a regulariser, depenses sans
        type). Chaque point indique le controle a demander pour le detail."""
        return _executer("a_verifier", journal, moteur.a_verifier, ctx, centres=centres)

    def graphique(id_resultat: str, type_graphique: str = "auto", indicateur: Optional[str] = None,
                  titre: Optional[str] = None) -> ContentToolResult:
        """Affiche un graphique a partir d'un resultat deja calcule (id_resultat, ex. "r3").
        type_graphique : auto (defaut), courbe, barres, barres_horizontales, barres_groupees,
        barres_empilees. indicateur : colonne a tracer si le resultat en a plusieurs d'unites
        differentes. Ne jamais fournir de chiffres : ils viennent du resultat."""
        debut = time.perf_counter()
        appel = {"outil": "graphique", "parametres": {"id_resultat": id_resultat, "type": type_graphique}}
        try:
            res = ctx.resultats.get(str(id_resultat).strip())
            if res is None:
                raise Incomprehension("resultat_introuvable",
                                      f"Resultat {id_resultat} introuvable : recalculer d'abord avec "
                                      f"analyser (ou un autre outil) puis utiliser son id_resultat.")
            img, description = rendu.graphique(res, type_graphique, indicateur, titre)
            return _carte({"graphique": "affiche a l'utilisateur", "description": description},
                          titre or res.titre, html=img, ouverte=True, icone="graphique")
        except Incomprehension as e:
            appel["incomprehension"] = e.code
            return _carte(e.en_dict(), "Graphique impossible", texte=e.message, icone="precision")
        except Exception as e:
            logger.exception("Graphique en echec")
            appel["erreur"] = str(e)[:300]
            return _carte({"erreur": "technique", "message": "Le graphique n'a pas pu etre trace."},
                          "Graphique indisponible", texte="Le graphique n'a pas pu etre trace.",
                          icone="erreur")
        finally:
            appel["duree_ms"] = int((time.perf_counter() - debut) * 1000)
            journal.append(appel)

    def requete_sql(sql: str) -> ContentToolResult:
        """Dernier recours, pour une question qu'aucun autre outil ne couvre. Une seule requete
        SELECT (PostgreSQL) sur la vue v_lignes (une ligne d'ecriture : id_piece, num_definitif,
        date_piece, mois AAAAMM, annee_scolaire, centre, centre_nom, journal, compte,
        compte_intitule, compte_nature, classe, code_tiers, tiers_nom, tiers_type, libelle,
        debit, credit, statut, modele, est_transfert) et les tables centres, comptes, tiers,
        journaux, categories_charge. Lecture seule, 10 s max, 300 lignes max. Exclure
        est_transfert pour des encaissements/decaissements reels."""
        return _executer("requete_sql", journal, moteur.requete_sql, ctx, sql=sql)

    outils = [contexte, point_financier, analyser, comparer, soldes, lister_ecritures, a_verifier,
              chercher, controles,
              personnel, graphique]
    if not ctx.restreint:
        outils.append(requete_sql)
    return outils

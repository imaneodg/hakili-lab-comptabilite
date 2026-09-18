# ---------------------------------------------------------------------------
# HAKILI LAB - Saisie des operations de caisse
#
# Les centres saisissent, le comptable valide, l'application produit le
# fichier a importer dans Sage 100. Sage reste le livre officiel.
#
# Stockage : PostgreSQL (voir sql/schema.sql), connexion via DATABASE_URL ou
# les variables PG* (voir .env.example). Aucun fichier Excel n'est lu ni
# ecrit par l'application.
#
# Lancement :  shiny run --reload app.py   (depuis un venv avec les
#              dependances de requirements.txt installees, et .env rempli)
# ---------------------------------------------------------------------------
import io
import json
import logging
import os
import re
import sys
from datetime import date
from pathlib import Path
import base64
import uuid

import pandas as pd
from dotenv import load_dotenv
from shiny import App, reactive, render, req, ui

load_dotenv()  # avant l'import de logic.donnees : c'est la que le pool de
                # connexions Postgres est cree, il a besoin de DATABASE_URL.

# Journalisation applicative : un seul appel a basicConfig par processus,
# ici (le point d'entree), jamais dans logic/donnees.py qui ne fait
# qu'ecrire sur le logger deja configure - sinon un import de logic.donnees
# depuis un autre script (import_historique.py, un shell interactif...)
# reconfigurerait les handlers a chaque fois.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(os.environ.get("HAKILI_LOG_FILE", "hakili.log"), encoding="utf-8"),
              logging.StreamHandler()],
)

import logic.donnees as dl
import logic.modeles as md
import logic.questions_assistant as qa
import logic.graphiques as gr
from chat_config import get_chat_client
from chatlas import ContentToolResult
from composants import titre_page, carte_bandeau, hk_info, filtre, filtres, stat

AUCUNE_SUGGESTION = "Choisissez une catégorie ci-dessus"

STATUTS = {"saisie": "En attente de validation", "validee": "Validée",
           "a_corriger": "À corriger", "exportee": "Exportée vers Sage"}

# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

# Le CSS de l'application vit desormais dans www/app.css (etape 1 de la
# refonte visuelle : extraction des tokens de design hors de app.py,
# voir ce fichier pour le detail des variables --hk-*), charge plus bas
# via ui.include_css() dans app_ui.

# Memorise le dernier centre choisi sur ce poste (localStorage, cote
# navigateur - jamais transmis au serveur ni au referentiel). Le formulaire
# de connexion ("page") est re-rendu par le serveur a chaque fois - "l_centre"
# n'existe donc pas encore au chargement de la page elle-meme : on ecoute
# l'evenement shiny:value sur la sortie "page" plutot qu'un DOMContentLoaded,
# pour retrouver le menu a chaque fois qu'il reapparait. Repose sur le
# comportement natif de l'input select de Shiny (ecoute des evenements
# "change") plutot que sur Shiny.setInputValue, pour ne rien court-circuiter
# du cote reactif normal.
JS_DERNIER_CENTRE = """
document.addEventListener("change", function (e) {
  if (e.target && e.target.id === "l_centre") {
    try { localStorage.setItem("hakili_dernier_centre", e.target.value); } catch (err) {}
  }
});

document.addEventListener("shiny:value", function (e) {
  if (!e.target || e.target.id !== "page") return;
  var sel = document.getElementById("l_centre");
  if (!sel) return;
  var dernier;
  try { dernier = localStorage.getItem("hakili_dernier_centre"); } catch (err) { return; }
  if (!dernier || sel.value === dernier) return;
  var option_existe = sel.querySelector('option[value="' + dernier.replace(/"/g, '\\\\"') + '"]');
  if (!option_existe) return;
  sel.value = dernier;
  sel.dispatchEvent(new Event("change", { bubbles: true }));
});
"""

# Bouton "afficher le code" sur les deux champs de code d'acces : celui de la
# connexion (l_code) et celui de la creation d'utilisateur
# (r_code_utilisateur). Shiny n'a pas de bascule native sur input_password.
#
# L'input n'est JAMAIS deplace dans le DOM : seul son conteneur recoit une
# classe, et le bouton s'y pose en absolu (meme technique que le suffixe
# "F CFA" des champs de montant, cf. www/app.css). Deplacer l'element
# casserait la liaison Shiny de l'input.
#
# Delegation sur "shiny:value" comme JS_DERNIER_CENTRE, parce que l'ecran de
# connexion est re-rendu par le serveur a chaque affichage de page() : un
# simple DOMContentLoaded ne verrait le champ qu'une fois. Le MutationObserver
# couvre le panneau de creation d'utilisateur, rendu par render.ui.
#
# Le code se remasque tout seul apres 5 secondes et des que le champ perd le
# focus : sur un poste de caisse partage, un code laisse lisible a l'ecran est
# un code divulgue.
JS_OEIL_CODE = """
(function () {
  var CIBLES = ["l_code", "r_code_utilisateur"];

  function decorer(champ) {
    if (!champ || champ.dataset.hkOeil === "1") return;
    var boite = champ.parentNode;
    if (!boite) return;
    champ.dataset.hkOeil = "1";
    boite.classList.add("hk-champ-code");

    var bouton = document.createElement("button");
    bouton.type = "button";
    bouton.className = "hk-oeil";
    bouton.tabIndex = -1;
    boite.appendChild(bouton);

    var minuteur = null;

    function masquer() {
      champ.type = "password";
      bouton.innerHTML = '<i class="bi bi-eye"></i>';
      bouton.setAttribute("aria-label", "Afficher le code");
      if (minuteur) { clearTimeout(minuteur); minuteur = null; }
    }

    function afficher() {
      champ.type = "text";
      bouton.innerHTML = '<i class="bi bi-eye-slash"></i>';
      bouton.setAttribute("aria-label", "Masquer le code");
      if (minuteur) clearTimeout(minuteur);
      minuteur = setTimeout(masquer, 5000);
    }

    masquer();
    bouton.addEventListener("click", function (e) {
      e.preventDefault();
      if (champ.type === "password") { afficher(); } else { masquer(); }
    });
    champ.addEventListener("blur", masquer);
  }

  function balayer() {
    for (var i = 0; i < CIBLES.length; i++) {
      decorer(document.getElementById(CIBLES[i]));
    }
  }

  document.addEventListener("DOMContentLoaded", balayer);
  document.addEventListener("shiny:value", balayer);
  if (window.MutationObserver) {
    new MutationObserver(balayer).observe(document.documentElement,
                                          { childList: true, subtree: true });
  }
})();
"""

# Forme decorative en fond de sidebar (refonte visuelle, etape 2 - coquille) :
# une seule courbe pleine, tres transparente, purement ornementale - voir
# .hk-vague dans www/app.css pour son positionnement (pointer-events:none,
# toujours derriere le contenu de la sidebar).
SVG_VAGUE = (
    '<svg viewBox="0 0 280 220" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M0,130 C70,190 210,70 280,150 L280,220 L0,220 Z" fill="rgba(255,255,255,.06)"/>'
    "</svg>"
)

app_ui = ui.page_fluid(
    ui.tags.head(ui.include_css(Path(__file__).parent / "www" / "app.css"),
                 ui.tags.title("HAKILI LAB"),
                 ui.tags.link(rel="icon", type="image/x-icon", href="favicon.ico"),
                 ui.tags.link(rel="apple-touch-icon", href="apple-touch-icon.png"),
                 # Icones simples de la sidebar (refonte 11/09/2026) : hebergees
                 # localement (www/bootstrap-icons/) plutot que via CDN - l'appli
                 # tourne sur des postes de caisse qui peuvent perdre l'acces
                 # reseau, hors ligne toute la navigation deviendrait du texte nu.
                 ui.tags.link(rel="stylesheet", href="bootstrap-icons/bootstrap-icons.min.css"),
                 ui.tags.script(ui.HTML(JS_DERNIER_CENTRE)),
                 ui.tags.script(ui.HTML(JS_OEIL_CODE))),
    ui.output_ui("page"),
)


# ---------------------------------------------------------------------------
# Serveur
# ---------------------------------------------------------------------------

def server(input, output, session):

    maj = reactive.value(0)              # declencheur de relecture des donnees

    # Plusieurs postes travaillent en meme temps sur la meme base. Un objet
    # reactif ne peut pas deviner qu'un autre poste vient d'ecrire en base :
    # on interroge donc, deux fois par seconde, le watermark tenu par
    # Postgres (table revision, incrementee par trigger a chaque ecriture
    # metier) ; tant qu'il ne bouge pas, rien n'est relu.
    #
    # Sans cela, le comptable garde la copie du referentiel chargee a sa
    # connexion : un eleve cree a l'instant par la caisse de Pissy lui reste
    # invisible, et son onglet Controles annonce "Tiers inconnu" pour un tiers
    # qui existe bel et bien en base.
    @reactive.poll(dl.revision_bd, 0.5)
    def _disque():
        return dl.revision_bd()

    @reactive.calc
    def ref():
        _disque()
        return dl.lire_referentiel()

    util = reactive.value(None)          # utilisateur connecte
    login_msg = reactive.value(None)
    dernier_msg = reactive.value(None)
    # Piece en cours de correction : None, ou {"id_piece","modele","journal",
    # "valeurs"}. Rempli quand on clique "Corriger" dans le Brouillard,
    # consomme et efface a l'enregistrement de la piece corrigee.
    correction = reactive.value(None)

    # ---------------- assistant IA : etat et connexion MCP -------------------
    #
    # Un client Chatlas par session (jamais partage entre deux utilisateurs
    # connectes en meme temps), cree paresseusement au premier besoin plutot
    # qu'au demarrage de la session : une caissiere qui n'a jamais acces a
    # cet onglet ne doit jamais ouvrir de sous-processus MCP pour rien.
    chat = ui.Chat(id="chat_assistant")
    chat_client_val = reactive.value(None)
    mcp_connecte = reactive.value(False)

    def chat_client():
        # La lecture est isolee : sans cela, appeler chat_client() depuis un effet
        # reactif (_connecter_mcp) cree une dependance sur chat_client_val, que le
        # .set() juste en dessous invalide aussitot - l'effet repart alors pendant
        # que son premier await est encore en cours.
        with reactive.isolate():
            if chat_client_val() is None:
                chat_client_val.set(get_chat_client())
            return chat_client_val()

    def rafraichir():
        maj.set(maj() + 1)

    @reactive.calc
    def donnees():
        maj()       # nos propres actions, effet immediat
        _disque()   # les ecritures d'un autre poste
        return dl.lire_ecritures()

    # Corrige le 11/09/2026 : "validation" existe desormais a deux niveaux -
    # le comptable du siege (centre SIE), qui voit et administre l'ensemble
    # de Hakili Lab, et un validateur local (n'importe quel autre centre),
    # qui valide/renvoie uniquement les pieces de son propre centre (voir
    # est_validateur() ci-dessous). Avant ce correctif, cette fonction ne
    # testait que le role : un validateur local etait alors traite comme le
    # comptable du siege partout (banque visible, toutes les pieces de tous
    # les centres, administration du referentiel) - faille decouverte par
    # Afiya en testant avec un compte "validation" sur le centre SIA.
    @reactive.calc
    def est_comptable():
        u = util()
        return u is not None and u.get("role") == "validation" and u.get("centre") == "SIE"

    # Role "validation", quel que soit le centre (siege ou local) : donne
    # acces aux onglets Validation/Export et au bouton "Valider"/"Renvoyer",
    # mais jamais a lui seul une visibilite sur un autre centre - c'est
    # est_comptable() (siege uniquement) qui decide de la portee des
    # donnees, pas est_validateur(). Voir _valider()/_rejeter()/attente().
    @reactive.calc
    def est_validateur():
        u = util()
        return u is not None and u.get("role") == "validation"

    # Un validateur local ne doit jamais pouvoir agir sur les pieces d'un
    # autre centre que le sien, meme si l'ecran (Brouillard/Validation) ne
    # lui en presente normalement aucune : masquer une ligne cote client
    # n'est pas un controle d'acces, voir _valider()/_rejeter() ci-dessous.
    def _hors_centre(ids, d, u):
        if not ids:
            return False
        return bool(len(d[d["id_piece"].isin(ids) & (d["centre"] != u["centre"])]))

    # Pas encore de role "directeur" distinct dans le referentiel des
    # utilisateurs (seuls "saisie" et "validation" existent) : l'assistant
    # est donc reserve au comptable du siege pour cette premiere version. Si
    # un role directeur est ajoute plus tard, remplacer cette fonction par
    # un test sur ce nouveau role en plus de est_comptable().
    @reactive.calc
    def peut_voir_assistant():
        return est_comptable()

    # Lecture tolerante d'un input dynamique (ch_*, sold_*) : peut ne pas
    # encore exister cote client, comme un input$xxx NULL en R.
    def get_input(id_, default=None):
        try:
            val = input[id_]()
        except Exception:
            return default
        return default if val is None else val

    # ---------------- construction des onglets --------------------------------

    # Le comptable travaille par lots, journal par journal, comme Sage l'impose.
    # Avec onze modeles, une liste plate devient illisible : on les regroupe donc
    # sous le journal auquel ils appartiennent. Les operations qui touchent deux
    # journaux (approvisionnement, versement en banque) apparaissent sous celui
    # ou elles commencent. Les modeles sans journal fixe ferment la liste.
    def _modeles_groupes(r):
        intitules = dict(zip(r["journaux"]["journal"], r["journaux"]["intitule"]))
        groupes, libres = {}, {}
        for m in md.MODELES:
            if m.get("retire"):
                continue
            j = m.get("journal")
            if not j:
                libres[m["id"]] = m["titre"]
                continue
            titre = f"{j} - {intitules.get(j, j)}"
            groupes.setdefault(titre, {})[m["id"]] = m["titre"]
        if libres:
            groupes["Autres"] = libres
        return groupes

    # Corrige le 11/09/2026 : le <select> "m_journal" plus bas etait cree
    # sans "selected=", donc sa valeur de depart cote client etait toujours
    # le premier journal de la liste (ordre de la table), qui ne correspond
    # pas forcement au journal impose par le modele affiche par defaut
    # ("Encaissement" -> CP). _modele_journal()/_garde_journal() corrigeaient
    # bien la valeur ensuite, mais _garde_journal() affichait au passage
    # l'avertissement "n'existe que sur le journal ..." - une fausse alerte,
    # puisque rien n'avait ete choisi. Le correctif du 10/09/2026 (ignore_init
    # sur cet effet) ne supprime que le tout premier declenchement de toute
    # la session Shiny (la connexion websocket) : des que l'ecran de Saisie
    # est reconstruit une deuxieme fois dans la MEME session (reconnexion
    # apres "Fermer la session", par exemple), le meme ecart se represente et
    # l'avertissement revient, cette fois pour de bon. La bonne correction
    # est de ne plus jamais creer ce <select> avec un ecart au depart, plutot
    # que de continuer a rattraper une valeur de depart fausse.
    def _journal_par_defaut(jx_actifs):
        # Le journal retenu doit exister dans la liste reellement proposee :
        # un modele actif peut viser un journal desactive depuis (ancienne banque).
        actifs = set(jx_actifs["journal"])
        for m in md.MODELES:
            if not m.get("retire") and m.get("journal") in actifs:
                return m["journal"]
        return jx_actifs["journal"].iloc[0] if len(jx_actifs) else None

    def onglet_saisie(r):
        # Un journal retire (actif = 'non', ex. l'ancienne banque apres
        # changement d'etablissement) reste consultable dans Brouillard/
        # Export mais ne doit plus pouvoir recevoir de nouvelle piece ici.
        jx_actifs = r["journaux"]
        if "actif" in jx_actifs.columns:
            jx_actifs = jx_actifs[jx_actifs["actif"].fillna("oui") == "oui"]
        return ui.nav_panel(
            "Saisie",
            titre_page("pencil-square", "Saisie",
                       "Enregistrez une opération de caisse et générez son écriture."),
            ui.output_ui("m_correction_bandeau"),
            # Deux colonnes independantes du point de vue du layout (cf.
            # .grille-saisie, corrige le 10/09/2026 quater) - pas un
            # ui.row()/ui.column(6) : voir le commentaire CSS pour la
            # raison. Le contenu de chaque carte est inchange.
            ui.div(
                {"class": "grille-saisie"},
                ui.div(
                    {"class": "carte carte-compacte"},
                    carte_bandeau("file-earmark-text", "Informations sur l'opération"),
                    ui.row(
                        ui.column(8, ui.input_select("m_modele", "Modele d'operation",
                                                       choices=_modeles_groupes(r))),
                        ui.column(4, ui.input_date("m_date", "Date de l'operation",
                                                    value=date.today(), format="dd/mm/yyyy")),
                    ),
                    # Le journal est impose par le modele dans presque tous
                    # les cas (cf. _modele_journal/_garde_journal plus bas,
                    # qui le remettent en place et avertissent si on le
                    # force) : un selecteur en permanence a l'ecran
                    # inviterait a le changer pour rien. panel_conditional
                    # ne fait que le masquer cote client, jamais cote
                    # serveur - la valeur reste lue normalement par
                    # input.m_journal(), aucun autre code n'a besoin de
                    # changer. Seule "Ecriture libre" a vraiment besoin du
                    # choix.
                    ui.panel_conditional(
                        "input.m_modele == 'libre'",
                        ui.row(ui.column(6, ui.input_select(
                            "m_journal", "Journal",
                            choices={j: f"{j} - {i}" for j, i in
                                     zip(jx_actifs["journal"], jx_actifs["intitule"])},
                            selected=_journal_par_defaut(jx_actifs)))),
                    ),
                    ui.panel_conditional(
                        "input.m_modele != 'libre'",
                        ui.output_ui("m_journal_texte"),
                    ),
                    ui.output_ui("m_champs"),
                    ui.output_ui("m_note_wrap"),
                ),
                ui.div(
                    {"class": "carte carte-compacte"},
                    carte_bandeau("file-earmark-text", "Écriture générée"),
                    ui.output_ui("m_apercu"),
                    ui.output_ui("m_ruban"),
                    ui.div(
                        {"class": "barre-actions"},
                        ui.input_action_button("m_enregistrer", "Enregistrer la pièce",
                                                icon=ui.tags.i({"class": "bi bi-check2"}),
                                                class_="hk-btn-primaire"),
                        ui.input_action_button("m_vider", "Vider",
                                                icon=ui.tags.i({"class": "bi bi-trash"}),
                                                class_="hk-btn-secondaire"),
                    ),
                    ui.output_ui("m_dernier"),
                ),
            ),
            value="saisie", icon=ui.tags.i({"class": "bi bi-pencil-square"}),
        )

    def onglet_brouillard(r):
        return ui.nav_panel(
            "Brouillard",
            titre_page("file-earmark-text", "Brouillard",
                       "Consultez et corrigez les pièces saisies."),
            ui.div(
                {"class": "carte"},
                carte_bandeau("file-earmark-text", "Pièces saisies"),
                # Ligne 1 : les filtres, qui decident ce qui s'affiche -
                # panneau teinte avec separateurs verticaux (refonte
                # visuelle, etape 5 : composants.py::filtres()/filtre()).
                filtres(
                    filtre(ui.input_select(
                        "b_statut", "Statut", choices=["Tous"] + list(STATUTS.values()))),
                    filtre(ui.input_select(
                        "b_journal", "Journal", choices=["Tous"] + list(r["journaux"]["journal"]))),
                    filtre(ui.input_date_range(
                        "b_periode", "Période", start=date.today().replace(day=1), end=date.today(),
                        format="dd/mm/yyyy", separator=" au ")),
                ),
                # Ligne 2 : un bandeau d'indicateurs compact - une seule
                # bordure d'ensemble avec des separateurs fins entre chaque
                # chiffre, jamais six cartes independantes qui gaspillent de
                # la hauteur pour un seul nombre chacune. Le nombre exact
                # d'indicateurs varie avec le role (voir b_stats()) : la
                # maquette en montrait 4, l'appli en a 5 ou 6 selon le
                # role connecte - tous conserves.
                ui.div({"class": "bandeau-indicateurs"}, ui.output_ui("b_stats")),
                # Ligne 3 : les actions sur la piece selectionnee, juste
                # au-dessus du tableau qu'elles concernent.
                ui.div(
                    {"class": "barre-actions"},
                    ui.input_action_button("b_corriger", "Corriger la pièce",
                                            icon=ui.tags.i({"class": "bi bi-pencil"}),
                                            class_="hk-btn-primaire"),
                    ui.input_action_button("b_supprimer", "Supprimer",
                                            icon=ui.tags.i({"class": "bi bi-trash"}),
                                            class_="hk-btn-danger"),
                    ui.span({"class": "aide"}, "Sélectionnez une ligne dans le tableau ci-dessous."),
                ),
                ui.output_data_frame("b_table"),
            ),
            value="brouillard", icon=ui.tags.i({"class": "bi bi-file-earmark-text"}),
        )

    def onglet_validation(r):
        # Filtre "Centre" ajoute le 18/09/2026 a la demande du comptable : il
        # valide centre par centre et voyait jusqu'ici les six melanges.
        # Rendu au SEUL comptable du siege - un validateur local ne voit deja
        # que son propre centre (voir attente()), le filtre n'aurait rien a
        # filtrer chez lui.
        #
        # C'est un filtre d'AFFICHAGE, jamais un controle d'acces : _valider
        # et _rejeter gardent leur _hors_centre, qui reste la seule barriere
        # reelle. Masquer une ligne cote client n'a jamais protege personne.
        #
        # Les autres filtres de la maquette (Periode, Journal, case "non
        # validees") n'ont toujours aucune contrepartie serveur et ne sont
        # pas inventes ici.
        barre = None
        if est_comptable():
            cx = r["centres"]
            if "actif" in cx.columns:
                cx = cx[cx["actif"].fillna("oui") == "oui"]
            choix = {"Tous": "Tous les centres"}
            for _, c in cx.iterrows():
                choix[c["code_centre"]] = c["intitule"]
            barre = filtres(filtre(ui.input_select("v_centre", "Centre", choices=choix)))
        return ui.nav_panel(
            "Validation",
            titre_page("shield-check", "Validation",
                       "Validez les pièces en attente ou renvoyez-les pour correction."),
            ui.div(
                {"class": "carte"},
                carte_bandeau("shield-check", "Pièces en attente"),
                barre,
                ui.output_data_frame("v_table"), ui.br(),
                # Le motif est place au-dessus des boutons (pas a cote) :
                # il concerne uniquement le renvoi, mais reste toujours
                # visible - cf. _rejeter() qui le rend obligatoire.
                ui.div({"style": "max-width:420px"},
                       ui.input_text("v_motif", "Motif du renvoi")),
                ui.div(
                    {"class": "barre-actions"},
                    ui.input_action_button("v_valider", "Valider les pièces choisies",
                                            icon=ui.tags.i({"class": "bi bi-check2-circle"}),
                                            class_="hk-btn-primaire"),
                    ui.input_action_button("v_rejeter", "Renvoyer pour correction",
                                            icon=ui.tags.i({"class": "bi bi-arrow-counterclockwise"}),
                                            class_="hk-btn-secondaire"),
                    # Compteur de selection : seul moyen pour la validatrice
                    # de voir qu'un clic simple a remplace sa selection, ou
                    # qu'un filtre de colonne vient de l'amputer (la grille
                    # retire de la selection toute ligne qu'un filtre masque,
                    # sans le signaler). Voir v_selection().
                    # class_ sur le conteneur de sortie, pas sur son contenu :
                    # c'est ce <div> qui est l'element flex de .barre-actions,
                    # donc lui seul que ".barre-actions .aide { margin-left:auto }"
                    # peut pousser a droite.
                    ui.output_ui("v_selection", class_="aide"),
                ),
                hk_info([
                    "Valider une pièce liée à une autre (ex. versement en banque) valide aussi sa jumelle.",
                    "Une pièce comportant une anomalie bloquante ne peut pas être validée.",
                    "Le motif du renvoi est obligatoire pour renvoyer une pièce pour correction.",
                    "Un validateur local n'agit que sur les pièces de son propre centre.",
                ]),
            ),
            value="validation", icon=ui.tags.i({"class": "bi bi-shield-check"}),
        )

    def onglet_export(r):
        return ui.nav_panel(
            "Export Sage",
            titre_page("download", "Export Sage",
                       "Générez le fichier d'import pour Sage 100."),
            ui.div(
                {"class": "carte"},
                carte_bandeau("download", "Fichier d'import Sage"),
                filtres(
                    filtre(ui.input_date_range(
                        "e_periode", "Période", start=date.today().replace(day=1), end=date.today(),
                        format="dd/mm/yyyy", separator=" au ")),
                    filtre(ui.input_select(
                        "e_journal", "Journal", choices=["Tous"] + list(r["journaux"]["journal"]))),
                    filtre(ui.input_checkbox("e_deja", "Inclure les pièces déjà exportées", False)),
                ),
                # e_resume() est un resume dynamique calcule (nombre de
                # pieces/lignes/montant du filtre en cours), pas une liste
                # de regles statiques : reste en .ruban (deja restyle aux
                # etapes precedentes), le composant hk_info() ne convient
                # qu'a du texte fixe.
                ui.output_ui("e_resume"),
                ui.div(
                    {"class": "barre-actions"},
                    ui.download_button("e_txt", "Télécharger le fichier Sage (.txt)",
                                        icon=ui.tags.i({"class": "bi bi-download"}),
                                        class_="hk-btn-primaire"),
                    ui.download_button("e_xlsx", "Télécharger en Excel",
                                        icon=ui.tags.i({"class": "bi bi-file-earmark-spreadsheet"}),
                                        class_="hk-btn-secondaire"),
                    ui.input_action_button("e_marquer", "Marquer comme exportées",
                                            icon=ui.tags.i({"class": "bi bi-check2-square"}),
                                            class_="hk-btn-secondaire"),
                ),
                ui.output_data_frame("e_table"),
            ),
            value="export", icon=ui.tags.i({"class": "bi bi-download"}),
        )

    def onglet_controles():
        return ui.nav_panel(
            "Contrôles",
            titre_page("search", "Contrôles",
                       "Anomalies détectées sur les pièces saisies."),
            ui.div({"class": "carte"},
                   carte_bandeau("search", "Anomalies détectées"),
                   ui.output_ui("c_reparation"),
                   ui.output_data_frame("c_table"),
                   ui.output_ui("c_reclassement")),
            value="controles", icon=ui.tags.i({"class": "bi bi-search"}),
        )

    # Onglet reserve au comptable (voir peut_voir_assistant) : suggestions de
    # questions regroupees par categorie a gauche, conversation libre a
    # droite, connectee au serveur MCP maison (mcp_server/server.py) qui
    # interroge Hakili_compta en direct.
    def onglet_assistant():
        categories = ["Poser ma propre question..."] + list(qa.QUESTIONS_PAR_CATEGORIE.keys())
        # Avatar de l'assistant : le trait de marque Hakili Lab plutot que
        # l'icone robot generique livree par defaut avec le composant chat -
        # coherent avec le reste de l'appli, jamais un signe visuel qui
        # signale "ceci est un chatbot IA generique".
        avatar = ui.tags.img(src="hakili_mark.png", alt="",
                              style="width:24px;height:24px;border-radius:50%;object-fit:cover")
        return ui.nav_panel(
            "Assistant IA",
            titre_page("stars", "Assistant IA",
                       "Interrogez l'assistant financier sur vos données."),
            ui.div(
                {"style": "display:flex; gap:20px; align-items:flex-start; flex-wrap:wrap"},
                ui.div(
                    {"class": "carte", "style": "flex:1 1 280px; max-width:320px"},
                    carte_bandeau("tags", "Catégories"),
                    ui.input_select("categorie_suggestion", None, choices=categories),
                    # Cree une seule fois, avec un choix de depart : ne
                    # jamais recreer ce selecteur via render.ui plus tard
                    # (meme id recree = widget JS qui ne se reinitialise pas
                    # toujours proprement cote client). Ses choix se mettent
                    # a jour via ui.update_select() dans un reactive.effect,
                    # jamais en le redeclarant.
                    ui.input_select("question_suggeree", "Suggestions",
                                     choices=[AUCUNE_SUGGESTION]),
                    ui.input_action_button("envoyer_suggestion", "Envoyer cette suggestion",
                                            icon=ui.tags.i({"class": "bi bi-send"}),
                                            class_="hk-btn-primaire", style="margin-top:10px; width:100%"),
                ),
                ui.div(
                    {"class": "carte", "style": "flex:2 1 420px"},
                    carte_bandeau("stars", "Assistant financier"),
                    ui.chat_ui(
                        "chat_assistant",
                        placeholder="Ecrivez votre question...",
                        icon_assistant=avatar,
                        messages=[
                            "Bonjour. Je suis l'assistant financier de Hakili Lab. "
                            "Posez votre question librement, ou choisissez une catégorie "
                            "à gauche pour des suggestions."
                        ],
                    ),
                ),
            ),
            value="assistant", icon=ui.tags.i({"class": "bi bi-stars"}),
        )

    # Shiny n'accepte que lettres, chiffres et souligne dans un identifiant de
    # champ. Un code journal peut contenir autre chose - l'ancien "BDU-BF"
    # venait tel quel du plan Sage et son tiret faisait planter la page. On le
    # transpose donc, toujours par la meme fonction des deux cotes (creation
    # et lecture).
    def _id_journal(j):
        return "sold_" + re.sub(r"[^A-Za-z0-9_]", "_", str(j))

    # Meme transposition, pour un solde d'ouverture par centre (CP, CMD) :
    # un identifiant par couple centre/journal, jamais partage entre eux.
    def _id_solde_centre(centre, journal):
        return "sold_c_" + re.sub(r"[^A-Za-z0-9_]", "_", f"{centre}_{journal}")

    # Quel formulaire de creation est ouvert dans Referentiel : None ou une
    # cle ("compte", "tiers", "utilisateur", "soldes", "annee"). Un seul a la
    # fois, rendu par le serveur - jamais par une bibliotheque cote
    # navigateur qui peut cloner son contenu sans le retirer. C'est ce qui
    # garantit, structurellement, qu'un champ ne peut jamais apparaitre deux
    # fois dans la page.
    panneau_ouvert = reactive.value(None)

    # Disclosure progressif des listes longues du Referentiel : repliees par
    # defaut a la hauteur de LIGNES_APERCU lignes, un lien les deplie/replie.
    #
    # Corrige le 12/09/2026. La premiere version tronquait cote SERVEUR
    # (d.head(8)) : le navigateur ne recevait que huit lignes, et la rangee
    # de filtres ajoutee a la refonte ne pouvait donc chercher que dans ces
    # huit-la. Un comptable qui cherchait un tiers parmi trois cents tapait
    # son code dans le filtre et obtenait "aucun resultat" alors que la
    # fiche existait - le referentiel paraissait incomplet. Meme probleme
    # pour selectionner un utilisateur au-dela de la huitieme ligne.
    # On envoie donc desormais la liste ENTIERE et on se contente de limiter
    # la HAUTEUR de la grille : le repliement redevient ce qu'il pretend
    # etre, un reglage d'affichage, et le filtre porte sur tout le
    # referentiel. Le volume le permet sans discussion (quelques centaines
    # de lignes), exactement comme pour le Brouillard et la Validation qui
    # envoient deja tout.
    LIGNES_APERCU = 8
    # En-tete + rangee de filtres + LIGNES_APERCU lignes, au pas de padding
    # defini dans www/app.css (.shiny-data-grid tbody td { padding:14px 16px }).
    HAUTEUR_APERCU = f"{85 + LIGNES_APERCU * 45}px"
    etendu_comptes = reactive.value(False)
    etendu_tiers = reactive.value(False)
    etendu_utilisateurs = reactive.value(False)

    def _bouton_toggle(cle, libelle="+", classe="btn-icone", **kwargs):
        return ui.input_action_button(f"toggle_{cle}", libelle, class_=classe, **kwargs)

    def _declencheur_flottant(cle, id_panneau, libelle="+", classe="btn-icone", cote="a-droite", **kwargs):
        # Bouton + panneau dans le meme conteneur positionne : c'est ce qui
        # fait flotter le panneau juste sous le bouton au lieu de pousser le
        # reste de la carte vers le bas. **kwargs (ex. icon=, width=) passe
        # directement a input_action_button, pour les variantes hk-btn-*
        # (refonte visuelle - etape 8) sans dupliquer ce conteneur flottant.
        return ui.div(
            {"class": f"flottant-conteneur {cote}"},
            _bouton_toggle(cle, libelle, classe, **kwargs),
            ui.output_ui(id_panneau),
        )

    def onglet_referentiel(u, r):
        # est_comptable() (siege uniquement), jamais le role brut : un
        # validateur local n'administre pas le referentiel de toute la
        # maison (comptes, tiers, utilisateurs, soldes d'ouverture, nouvelle
        # annee) - voir le commentaire de est_comptable().
        comptable = est_comptable()

        def entete(icone, titre, cle=None, id_panneau=None):
            # Bouton "+" en 36px (refonte visuelle - etape 8 : classe
            # btn-icone-grand, distincte de btn-icone/27px utilisee
            # ailleurs, ex. Saisie) plutot que le petit carre Bootstrap
            # non stylise d'avant.
            extra = _declencheur_flottant(cle, id_panneau, classe="btn-icone-grand") \
                if cle is not None else None
            return carte_bandeau(icone, titre, extra=extra)

        blocs = [ui.row(
            ui.column(6, ui.div(
                {"class": "carte"},
                entete("journal-text", "Plan de comptes", "compte" if comptable else None, "panneau_compte"),
                ui.output_data_frame("r_comptes"),
                ui.output_ui("lien_comptes"))),
            ui.column(6, ui.div(
                {"class": "carte"},
                entete("person-badge", "Comptes de tiers", "tiers" if comptable else None, "panneau_tiers"),
                ui.output_data_frame("r_tiers"),
                ui.output_ui("lien_tiers"))),
        )]

        if comptable:
            blocs.append(ui.div(
                {"class": "carte"},
                entete("people", "Utilisateurs", "utilisateur", "panneau_utilisateur"),
                ui.p({"class": "aide"},
                     "Un identifiant par personne, pas par centre : c'est ce qui permet de savoir "
                     "qui a fait quoi. Désactiver ne supprime rien, l'historique reste intact."),
                ui.output_data_frame("r_utilisateurs"),
                ui.output_ui("lien_utilisateurs"),
                ui.input_action_button("r_desactiver_utilisateur", "Désactiver l'utilisateur choisi",
                                        icon=ui.tags.i({"class": "bi bi-person-dash"}),
                                        class_="hk-btn-secondaire"),
            ))
            blocs.append(ui.div(
                {"class": "carte"},
                carte_bandeau("sliders", "Paramètres"),
                ui.row(
                    ui.column(6, ui.div(
                        {"class": "param-item"},
                        _declencheur_flottant(
                            "soldes", "panneau_soldes",
                            ui.TagList(ui.tags.i({"class": "bi bi-cash-coin"}),
                                       " Soldes d'ouverture des caisses"),
                            "hk-btn-secondaire", "a-gauche", width="100%"),
                        ui.p({"class": "aide"}, "Encaisse réelle à la mise en service."))),
                    ui.column(6, ui.div(
                        {"class": "param-item"},
                        _declencheur_flottant(
                            "annee", "panneau_annee",
                            ui.TagList(ui.tags.i({"class": "bi bi-calendar-plus"}),
                                       " Nouvelle année académique"),
                            "hk-btn-secondaire", "a-gauche", width="100%"),
                        ui.p({"class": "aide"}, "Une fois par an, à la rentrée."))),
                ),
            ))

        return ui.nav_panel(
            "Référentiel",
            titre_page("book", "Référentiel",
                       "Plan de comptes, tiers, utilisateurs et paramètres."),
            *blocs, value="referentiel",
            icon=ui.tags.i({"class": "bi bi-book"}))

    for _cle in ("compte", "tiers", "utilisateur", "soldes", "annee"):
        def _fabrique_toggle(cle):
            @reactive.effect
            @reactive.event(input[f"toggle_{cle}"])
            def _toggle():
                panneau_ouvert.set(None if panneau_ouvert() == cle else cle)
            return _toggle
        _fabrique_toggle(_cle)

    @render.ui
    def panneau_compte():
        if panneau_ouvert() != "compte":
            return None
        return ui.div(
            {"class": "popover-form panneau-flottant"},
            ui.input_text("r_num_compte", "Numéro"),
            ui.input_text("r_intitule_compte", "Intitulé"),
            ui.input_select("r_nature_compte", "Nature",
                             choices={"charge": "Charge", "produit": "Produit",
                                      "bilan": "Bilan", "tresorerie": "Trésorerie",
                                      "tiers": "Tiers"}),
            ui.input_checkbox("r_compte_courante", "Proposer dans « Dépense courante »", value=False),
            ui.input_checkbox("r_tiers_obligatoire", "Code tiers obligatoire sur ce compte", value=False),
            ui.input_action_button("r_ajouter_compte", "Créer", class_="hk-btn-primaire"),
        )

    @render.ui
    def panneau_tiers():
        if panneau_ouvert() != "tiers":
            return None
        return ui.div(
            {"class": "popover-form panneau-flottant"},
            ui.input_text("r_code", "Code tiers"),
            ui.input_text("r_nom", "Intitulé"),
            ui.input_select("r_collectif", "Collectif",
                             choices={"411000": "411000 - Élève", "401000": "401000 - Fournisseur",
                                      "422000": "422000 - Personnel"}),
            ui.input_action_button("r_ajouter", "Créer", class_="hk-btn-primaire"),
        )

    @render.ui
    def panneau_utilisateur():
        if panneau_ouvert() != "utilisateur":
            return None
        r = ref()
        return ui.div(
            {"class": "popover-form panneau-flottant"},
            ui.input_text("r_id_utilisateur", "Identifiant"),
            ui.input_text("r_nom_utilisateur", "Nom complet"),
            ui.input_select("r_role_utilisateur", "Rôle",
                             choices={"saisie": "Saisie", "validation": "Validation"}),
            ui.input_select("r_centre_utilisateur", "Centre",
                             choices=dict(zip(r["centres"]["code_centre"], r["centres"]["intitule"]))),
            ui.input_password("r_code_utilisateur", "Code d'accès"),
            # La regle des 6 caracteres (voir dl.ajouter_utilisateur) n'etait
            # annoncee qu'en message d'erreur, apres le clic et une fois tout
            # le reste tape (18/09/2026).
            ui.p({"class": "aide", "style": "margin:-6px 0 10px"},
                 "Six caractères minimum. L'œil permet de relire le code avant de créer."),
            ui.input_action_button("r_ajouter_utilisateur", "Créer", class_="hk-btn-primaire"),
        )

    @render.ui
    def panneau_soldes():
        if panneau_ouvert() != "soldes":
            return None
        r = ref()
        jx = r["journaux"]
        if "type" in jx.columns:
            jx = jx[jx["type"].fillna("tresorerie") == "tresorerie"]
        if "actif" in jx.columns:
            jx = jx[jx["actif"].fillna("oui") == "oui"]
        centres_actifs = r["centres"]
        if "actif" in centres_actifs.columns:
            centres_actifs = centres_actifs[centres_actifs["actif"].fillna("oui") == "oui"]
        sc = r.get("soldes_centre")
        blocs = []
        for j in jx["journal"]:
            intitule_j = jx.loc[jx["journal"] == j, "intitule"].iloc[0]
            physique = "caisse_physique" in jx.columns and \
                (jx.loc[jx["journal"] == j, "caisse_physique"] == "oui").iloc[0]
            if physique:
                # Une caisse physique par centre : un champ par centre, pas
                # un seul chiffre partage - voir logic/donnees.py::solde_caisse.
                champs = []
                for _, c in centres_actifs.iterrows():
                    code = c["code_centre"]
                    val = 0.0
                    if sc is not None and len(sc):
                        v = sc.loc[(sc["journal"] == j) & (sc["centre"] == code), "solde_ouverture"]
                        if len(v):
                            val = float(v.iloc[0])
                    champs.append(ui.input_numeric(_id_solde_centre(code, j), c["intitule"],
                                                     value=val, min=0, step=1000))
                blocs.append(ui.div(
                    {"class": "param-item"},
                    ui.p({"class": "param-aide", "style": "margin-bottom:4px"},
                         f"{j} - {intitule_j} (par centre)"),
                    *champs,
                ))
            else:
                # Compte partage entre tous les centres (la banque) : un seul
                # champ, comme avant.
                brut = jx.loc[jx["journal"] == j, "solde_ouverture"]
                val = float(brut.iloc[0]) if len(brut) and pd.notna(brut.iloc[0]) else 0.0
                blocs.append(ui.input_numeric(_id_journal(j), f"{j} - {intitule_j}",
                                               value=val, min=0, step=1000))
        return ui.div({"class": "popover-form panneau-flottant"}, *blocs,
                       ui.input_action_button("r_soldes", "Enregistrer", class_="hk-btn-primaire"))

    @render.ui
    def panneau_annee():
        if panneau_ouvert() != "annee":
            return None
        return ui.div(
            {"class": "popover-form panneau-flottant"},
            ui.input_action_button("r_nouvelle_annee", "Démarrer", class_="hk-btn-primaire"),
        )

    def onglets(u):
        r = ref()
        tabs = [onglet_saisie(r), onglet_brouillard(r)]
        if u.get("role") == "validation":
            tabs += [onglet_validation(r), onglet_export(r)]
        tabs.append(onglet_controles())
        if peut_voir_assistant():
            tabs.append(onglet_assistant())
        tabs.append(onglet_referentiel(u, r))
        return tabs

    # ---------------- connexion ----------------------------------------------
    #
    # Un seul formulaire : centre + identifiant + code personnel, tous
    # renseignes ensemble. Pas de mot de passe de centre distinct : le code
    # personnel de chacun est la seule barriere, exactement comme le code
    # d'un badge individuel. La tracabilite nominative (saisi_par/valide_par)
    # vient de ce meme code, qui reste propre a chaque personne.

    @render.ui
    def page():
        u = util()
        if u is not None:
            role_txt = "validation et export" if u.get("role") == "validation" else "saisie"
            return ui.TagList(
                # Sidebar : logo en tete (fixe) - memes informations qu'avant
                # (nom, centre, role, deconnexion), simplement deplacees du
                # bandeau horizontal vers le pied de la sidebar verticale.
                ui.div(
                    {"class": "barre-logo"},
                    ui.tags.img({"class": "logo-bandeau", "src": "hakili_logo_header.png", "alt": "Hakili Lab"}),
                    ui.div({"class": "texte"}, ui.tags.b("HAKILI LAB"), ui.tags.span("Gestion Comptable")),
                ),
                # Forme decorative en fond de sidebar (refonte visuelle,
                # etape 2 - coquille) : purement visuelle, .hk-vague est en
                # pointer-events:none et ne recoit jamais le clic.
                ui.div({"class": "hk-vague", "aria-hidden": "true"}, ui.HTML(SVG_VAGUE)),
                ui.div(
                    {"class": "barre-utilisateur"},
                    # Carte "Centre" (refonte visuelle, etape 2) : rappel
                    # visuel de la valeur deja affichee juste en dessous
                    # ("Centre {u.get('centre')} - ..."), pas un filtre - u
                    # n'existe aucune entree "centre" cote serveur en dehors
                    # de l_centre sur l'ecran de connexion, donc pas de clic
                    # actif ici (cf. rapport d'audit, "centre selector").
                    ui.div(
                        {"class": "hk-centre-carte"},
                        ui.tags.i({"class": "bi bi-building"}),
                        ui.div(
                            {"class": "hk-centre-carte-texte"},
                            ui.span({"class": "hk-centre-carte-label"}, "Centre"),
                            ui.span({"class": "hk-centre-carte-valeur"}, u.get("centre")),
                        ),
                    ),
                    ui.tags.b(u.get("nom")),
                    f"Centre {u.get('centre')} - {role_txt}",
                    ui.input_action_link("deconnexion", "Fermer la session",
                                          style="display:block")),
                # En-tete blanc (refonte visuelle, etape 2 - coquille) :
                # n'existait pas avant. Chevron et engrenage sont decoratifs
                # (aucun menu profil ni page de parametres cote serveur) ;
                # le centre reste vide - jamais de deuxieme navigation, la
                # sidebar reste la seule (cf. www/app.css, commentaire
                # .hk-entete).
                ui.div(
                    {"class": "hk-entete"},
                    ui.div(
                        {"class": "hk-entete-compte"},
                        ui.div({"class": "hk-entete-avatar"}, (u.get("nom") or "?")[:1].upper()),
                        ui.span(u.get("nom")),
                    ),
                ),
                ui.div({"class": "corps-page"}, ui.output_ui("corps")),
            )

        entete = ui.div({"style": "text-align:center;margin-bottom:18px"},
                         ui.tags.img({"class": "logo-connexion", "src": "hakili_logo_full.png",
                                      "alt": "Hakili Lab"}),
                         ui.tags.div({"style": "font-size:12.5px;color:var(--hk-texte-doux);margin-top:2px"},
                                     "Gestion de caisse"))

        r = ref()
        centres_actifs = r["centres"][r["centres"]["actif"] == "oui"]
        choix = dict(zip(centres_actifs["code_centre"], centres_actifs["intitule"]))
        return ui.div(
            {"class": "connexion"}, entete,
            ui.div(
                {"class": "carte"},
                ui.h4("Connexion"),
                ui.input_select("l_centre", "Centre", choices=choix),
                ui.input_text("l_id", "Nom d'utilisateur"),
                ui.input_password("l_code", "Code personnel"),
                ui.input_action_button("l_ok", "Se connecter", class_="btn-primary"),
                ui.output_ui("l_msg"),
            ),
        )

    # Corrige le 10/09/2026 : page() appelait onglets(u) directement, qui lit
    # ref() -> _disque() (sondage 0,5 s sur les ecritures des 5 centres,
    # cf. plus haut). Consequence : chaque piece enregistree n'importe ou
    # invalidait page() entierement - tous les onglets recrees, m_modele et
    # m_journal remis a leur valeur par defaut, formulaire de Saisie en
    # cours efface (c'est ce qui donnait l'impression que l'ecran
    # "tremblait" et rendait la saisie difficile). La structure des onglets
    # ne depend en realite que du role, fixe pour toute la session : on la
    # construit donc une seule fois par connexion, dans une sortie separee
    # (corps), avec reactive.isolate() pour que la lecture de ref() a
    # l'interieur d'onglets(u) ne cree pas de dependance a _disque(). page()
    # ne depend plus que de util() (connexion/deconnexion). Les donnees
    # affichees a l'interieur des onglets (tableaux, soldes...) restent
    # dans leurs propres sorties (b_table, v_table, m_apercu...), deja
    # correctement isolees plus bas dans ce fichier, et continuent de se
    # rafraichir normalement.
    @render.ui
    def corps():
        u = req(util())
        with reactive.isolate():
            tabs = onglets(u)
        # navset_pill_list rend les memes ui.nav_panel(...) (memes value=,
        # meme contenu, meme id="onglets" donc meme input.onglets()/
        # update_navs("onglets", ...) qu'avant) mais empile la liste
        # verticalement au lieu d'une rangee d'onglets horizontale - voir
        # le CSS "#corps > .row > div:first-child" qui la transforme
        # en sidebar. well=False : pas de encadre gris Bootstrap derriere,
        # le fond sombre vient entierement du CSS ci-dessus.
        return ui.navset_pill_list(*tabs, id="onglets", well=False)

    @render.ui
    def l_msg():
        if login_msg() is None:
            return None
        return ui.div({"class": "ruban ko"}, login_msg())

    @reactive.effect
    @reactive.event(input.l_ok)
    def _connexion():
        r = ref()
        cs = r["centres"]
        idx_c = cs.index[cs["code_centre"] == input.l_centre()]
        if len(idx_c) and str(cs.loc[idx_c[0], "actif"]) != "oui":
            login_msg.set("Ce centre a ete desactive.")
            return
        # Le nom d'utilisateur n'est pas sensible a la casse : AFIYA, Afiya et
        # afiya designent la meme personne. La comparaison se fait toujours
        # dans le centre choisi dans le formulaire - un identifiant valide
        # mais d'un autre centre est refuse ici, pas seulement absent d'une
        # liste qui n'existe plus.
        #
        # Verifie directement en base (dl.tenter_connexion), jamais via le
        # referentiel mis en cache cote session : la verification du code,
        # le verrouillage anti brute-force et la mise a niveau bcrypt d'un
        # code encore en clair doivent toujours porter sur l'etat le plus
        # recent, pas sur une copie potentiellement vieille de 0.5s.
        saisi = str(input.l_id() or "").strip().lower()
        statut, u, minutes = dl.tenter_connexion(saisi, input.l_centre(), input.l_code())
        if statut == "ok":
            util.set(u)
            login_msg.set(None)
        elif statut == "inactif":
            login_msg.set("Ce compte a ete desactive.")
        elif statut == "verrouille":
            login_msg.set(f"Trop de tentatives incorrectes. Reessayer dans {minutes} min.")
        else:
            login_msg.set("Centre, nom d'utilisateur ou code incorrect.")

    @reactive.effect
    @reactive.event(input.deconnexion)
    def _deconnexion():
        util.set(None)

    # ---------------- formulaire "encaissement" : lignes de repartition ------
    #
    # Un reglement peut couvrir plusieurs mois (frais du mois, avance, ou
    # rattrapage d'un mois passe) : le champ "repartition" du modele
    # "encaissement" (cf. logic.modeles) n'est pas un widget simple mais un
    # petit tableau dont le nombre de lignes varie. Chaque ligne a un
    # identifiant stable qui ne change jamais tant qu'elle existe
    # (m_rep_mois_<id>, m_rep_nature_<id>, m_rep_montant_<id>) : la premiere
    # ligne porte toujours l'identifiant 1 et ne peut pas etre retiree, les
    # suivantes sont ajoutees par "+ Ajouter un mois" (max 6, spec 2026).
    MAX_LIGNES_REPARTITION = 6
    rep_ids = reactive.value([1])
    rep_prochain_id = reactive.value(2)
    # etendu_historique_tiers / _toggle_historique_tiers reviendront avec
    # m_bloc_historique() (neutralisee depuis le 7 septembre, cf. plus bas) :
    # retires ici car m_lien_historique n'est cree nulle part.
    # Chaque "Vider" repart sur un identifiant neuf (jamais reutilise, cf.
    # reinitialiser()) : cet ensemble evite de re-enregistrer un effet
    # deja cree pour ce meme identifiant. Jamais purge - sans consequence,
    # l'effet ne fait rien de plus la seconde fois qu'il s'applique.
    rep_effets_crees = set()

    # Suggestion de mois selon la nature choisie (spec §4) : "Frais" propose
    # le mois calendaire en cours, "Avance" le mois suivant le dernier
    # mouvement connu du tiers sur son compte 411 (ou le mois en cours si
    # aucun historique), "Solde" ne propose rien - deviner un mauvais mois
    # de rattrapage serait pire que ne rien suggerer. Toujours modifiable
    # ensuite a la main : une suggestion de confort, jamais une validation
    # automatique.
    def _mois_suggere(nature, code_tiers):
        if nature == "avance" and code_tiers:
            hist = dl.dernieres_lignes_tiers(code_tiers, limite=1)
            if len(hist):
                dernier = md.mois_depuis_libelle(hist.iloc[0]["libelle"])
                if dernier:
                    return md.mois_suivant(dernier)
        if nature == "solde":
            return ""
        return md.MOIS_FR[date.today().month - 1]

    def _code_tiers_saisi():
        brut = get_input("ch_tiers")
        if not brut:
            return ""
        return dl.code_tiers_candidat(brut, "411", ref())

    # Lit les lignes actuellement affichees (une par mois reparti) pour en
    # faire la valeur du champ "repartition" - le rendu generique de
    # m_champs ignore ce type de champ, valeurs() vient les lire ici.
    # "mois" est une LISTE depuis le 18/09/2026 : un meme reglement peut
    # couvrir plusieurs mois sur une seule ecriture. Le selectize multiple
    # renvoie un tuple ; md.mois_tries() cote modeles accepte aussi l'ancienne
    # forme (une chaine), pour les pieces deja enregistrees.
    def _lire_repartition():
        return [
            {"mois": list(get_input(f"m_rep_mois_{rid}", []) or []),
             "nature": get_input(f"m_rep_nature_{rid}", "frais"),
             "montant": get_input(f"m_rep_montant_{rid}", 0)}
            for rid in rep_ids()
        ]

    # Enregistre, pour une ligne donnee, l'effet qui rafraichit sa
    # suggestion de mois quand sa nature change, et (sauf pour la premiere
    # ligne, jamais retirable) le lien qui la supprime. Appelee une seule
    # fois a la creation de chaque ligne, cf. rep_effets_crees.
    def _fabrique_effets_repartition(rid):
        if rid in rep_effets_crees:
            return
        rep_effets_crees.add(rid)

        @reactive.effect
        @reactive.event(input[f"m_rep_nature_{rid}"])
        def _maj_mois_suggere():
            if req(input.m_modele()) != "encaissement":
                return
            nature = get_input(f"m_rep_nature_{rid}", "frais")
            propose = _mois_suggere(nature, _code_tiers_saisi())
            ui.update_selectize(f"m_rep_mois_{rid}", selected=[propose] if propose else [])

        if rid != 1:
            @reactive.effect
            @reactive.event(input[f"m_rep_suppr_{rid}"])
            def _retirer_ligne():
                rep_ids.set([x for x in rep_ids() if x != rid])

    _fabrique_effets_repartition(1)

    @reactive.effect
    @reactive.event(input.m_rep_ajouter)
    def _ajouter_ligne_repartition():
        if req(input.m_modele()) != "encaissement":
            return
        ids = rep_ids()
        if len(ids) >= MAX_LIGNES_REPARTITION:
            return
        nouveau = rep_prochain_id()
        rep_prochain_id.set(nouveau + 1)
        _fabrique_effets_repartition(nouveau)
        rep_ids.set(ids + [nouveau])

    def _ligne_repartition_ui(rid, premiere):
        # Corrige le 10/09/2026 (quater) : ces trois get_input() (donc
        # input[id]()) etaient lus sans isolate(), alors que cette fonction
        # est appelee depuis m_bloc_repartition() - un @render.ui qui DEFINIT
        # ces memes widgets. Consequence : m_bloc_repartition() dependait
        # reactivement de m_rep_mois_*/m_rep_nature_*/m_rep_montant_* de
        # TOUTES les lignes, donc modifier une seule ligne (meme apres
        # update_on="blur" ci-dessus) reconstruisait tout le tableau,
        # detruisant et recreant les <input> des AUTRES lignes non touchees -
        # confirme par un test Playwright (marqueur JS pose sur la ligne 1,
        # perdu apres avoir seulement modifie la ligne 2). Isoler ces
        # lectures les rend "lecture de la valeur actuelle a la construction"
        # plutot que "dependance reactive" : m_bloc_repartition() ne se
        # reconstruit plus que pour une vraie raison structurelle (ajout/
        # suppression de ligne, changement de modele), jamais parce qu'une
        # valeur a change dans une ligne existante.
        with reactive.isolate():
            nature_val = get_input(f"m_rep_nature_{rid}", "frais")
            mois_defaut = get_input(f"m_rep_mois_{rid}", None)
            montant_val = get_input(f"m_rep_montant_{rid}", 0)
            # _code_tiers_saisi() lit aussi ch_tiers et ref() sans isolate() -
            # reste dans le meme bloc isole, sinon choisir un eleve
            # reconstruirait le tableau de repartition en entier pour la
            # meme raison que ci-dessus.
            # Selection multiple : la valeur est une liste, jamais une chaine.
            if mois_defaut is None:
                propose = _mois_suggere(nature_val, _code_tiers_saisi())
                mois_defaut = [propose] if propose else []
            else:
                mois_defaut = list(mois_defaut)
        suppr = ui.tags.td() if premiere else ui.tags.td(
            ui.input_action_link(f"m_rep_suppr_{rid}", "Retirer", class_="lien-etendre"))
        return ui.tags.tr(
            # Selection MULTIPLE (18/09/2026) : un reglement qui couvre
            # plusieurs mois tient sur une seule ligne, et produit donc une
            # seule ecriture 411 dont le libelle cite tous les mois - c'est la
            # facon de faire du comptable. Rien d'autre ne change : une ligne
            # reste un montant et une nature.
            ui.tags.td(ui.input_selectize(
                f"m_rep_mois_{rid}", None, choices=md.MOIS_FR,
                selected=mois_defaut, multiple=True,
                options={"placeholder": "Mois..."})),
            ui.tags.td(ui.input_select(f"m_rep_nature_{rid}", None,
                                        choices={"frais": "Frais", "avance": "Avance",
                                                 "solde": "Solde / Retard"},
                                        selected=nature_val)),
            # update_on="blur" (10/09/2026, ter) : par defaut Shiny renvoie la
            # valeur au serveur a chaque frappe, ce qui reconstruisait tout le
            # panneau "Ecriture generee" (m_apercu/m_ruban, cf. plus bas) a
            # chaque chiffre tape - signale par Afiya comme "ca bouge" pendant
            # la saisie du montant. Avec "blur", la valeur n'est envoyee que
            # lorsqu'on quitte le champ (tabulation ou clic ailleurs) : aucune
            # perte fonctionnelle, juste un apercu qui se met a jour une fois
            # le montant termine plutot qu'a chaque caractere.
            ui.tags.td(ui.input_numeric(f"m_rep_montant_{rid}", None, value=float(montant_val or 0),
                                         min=0, step=500, update_on="blur")),
            suppr,
        )

    @render.ui
    def m_bloc_repartition():
        if req(input.m_modele()) != "encaissement":
            return None
        ids = rep_ids()
        table = ui.tags.table(
            {"class": "apercu apercu-repartition"},
            ui.tags.thead(ui.tags.tr(ui.tags.th("Mois"), ui.tags.th("Nature"),
                                      ui.tags.th("Montant"), ui.tags.th())),
            ui.tags.tbody(*[_ligne_repartition_ui(rid, rid == ids[0]) for rid in ids]),
        )
        if len(ids) < MAX_LIGNES_REPARTITION:
            pied = ui.input_action_link(
                "m_rep_ajouter",
                ui.TagList(ui.tags.i({"class": "bi bi-plus-circle"}), " Ajouter un mois"),
                class_="lien-etendre lien-ajouter")
        else:
            pied = ui.div({"class": "ruban att", "style": "font-size:12px"},
                           "Six mois par piece au maximum : au-dela, traiter la creance ancienne "
                           "separement plutot que de tout regrouper ici.")
        return ui.div(table, pied)

    # Bloc historique (spec §3.2) : un resume compact toujours visible des
    # qu'un tiers est choisi, jamais calcule a partir d'un tarif ou d'un
    # statut - seulement ce que la base sait deja des dernieres lignes 411
    # de ce tiers.
    #
    # NOTE (7 sept., Claude) : le corps original de cette fonction a ete
    # perdu lors d'une erreur de manipulation de fichier et n'a pas pu etre
    # recupere avec certitude. Desactivee sans risque en attendant (elle ne
    # casse rien : cette seule vignette ne s'affiche pas) plutot que
    # reecrite au hasard - a refaire quand vous aurez confirme le
    # comportement voulu.
    @render.ui
    def m_bloc_historique():
        return None

    # ---------------- saisie --------------------------------------------------

    # Le modele impose son journal quand il n'en accepte qu'un ; aucun des
    # modeles actuels n'a besoin de restreindre la liste des journaux -
    # "Ecriture libre" fonctionne sur tous, ses champs s'adaptent tout seuls
    # (cf. m_champs) au journal deja choisi.
    @reactive.effect
    @reactive.event(input.m_modele)
    def _modele_journal():
        m = md.modele_par_id(input.m_modele())
        if m is not None and m.get("journal"):
            ui.update_select("m_journal", selected=m["journal"])

    # Le selecteur de journal reste modifiable a la main (utile pour
    # "Ecriture libre"), mais rien n'empeche alors de choisir une combinaison
    # impossible pour un modele a journal fixe (ex. "Encaissement" + VTE) -
    # l'apercu restait vide sans dire pourquoi. On remet le journal correct
    # et on explique, plutot que de laisser deviner.
    #
    # Corrige le 10/09/2026 (bis) : ui.input_select("m_journal", ...) plus
    # haut est cree sans "selected=" - sa valeur de depart est donc le
    # premier journal de la liste, qui ne correspond pas forcement au
    # journal impose par le modele affiche par defaut (ex. "Encaissement"
    # impose CP, mais si CP n'est pas premier dans la liste, m_journal
    # demarre sur un autre journal). Or @reactive.event() s'execute par
    # defaut des le demarrage de la session (ignore_init=False, verifie
    # dans le code source de Shiny installe : "If False, the event
    # triggers on the first run") - donc _garde_journal() se declenchait
    # une fois a chaque connexion avec cette valeur de depart incorrecte,
    # et affichait l'avertissement alors que l'utilisateur n'avait rien
    # choisi. ignore_init=True le fait ignorer ce tout premier declenchement
    # : _modele_journal() ci-dessus (qui garde son comportement par defaut)
    # corrige quand meme silencieusement m_journal vers le bon journal des
    # la connexion, et _garde_journal() ne reagit plus qu'aux vrais
    # changements ulterieurs (utilisateur qui force manuellement un journal
    # incompatible, ce qui reste signale comme avant).
    @reactive.effect
    @reactive.event(input.m_journal, ignore_init=True)
    def _garde_journal():
        m = md.modele_par_id(input.m_modele())
        if m is not None and m.get("journal") and input.m_journal() != m["journal"]:
            ui.update_select("m_journal", selected=m["journal"])
            ui.notification_show(
                f"Le modele \u00ab {m['titre']} \u00bb n'existe que sur le journal {m['journal']}.",
                type="warning")

    # Determine, pour le modele en cours, quels libelles proposer.
    # "Reglement fournisseur" propose les libelles rattaches au compte 401000,
    # les memes pour tous les fournisseurs : pas de dependance au fournisseur
    # choisi, volontairement, pour que le formulaire reste simple et
    # previsible. "Depense courante" propose ceux du compte de charge deja
    # choisi. "Ecriture libre" n'est pas filtre.
    #
    # La lecture d'un champ deja affiche par ce meme formulaire est isolee :
    # m_champs ne doit jamais reagir a un changement de ces champs, sinon le
    # formulaire entier se redessine et efface la selection qu'on vient de
    # faire.
    def _libelles_pour_champ(m, r):
        base = r["libelles"]
        if m["id"] == "fournisseur":
            return base[base["compte"] == "401000"]
        if m["id"] == "depense":
            with reactive.isolate():
                compte_choisi = get_input("ch_compte")
            if compte_choisi:
                return base[base["compte"] == compte_choisi]
            return base[base["compte"].isin(
                r["comptes"].loc[r["comptes"]["depense_courante"] == "oui", "compte"])]
        return base

    @render.ui
    def m_journal_texte():
        m = md.modele_par_id(input.m_modele()) if input.m_modele() else None
        if m is None or not m.get("journal"):
            return None
        r = ref()
        lig = r["journaux"].loc[r["journaux"]["journal"] == m["journal"], "intitule"]
        intitule = lig.iloc[0] if len(lig) else m["journal"]
        return ui.p({"class": "aide", "style": "margin-top:-2px; margin-bottom:12px"},
                    f"Journal : {m['journal']} - {intitule}")

    @render.ui
    def m_champs():
        m = md.modele_par_id(req(input.m_modele()))
        # Corrige le 10/09/2026 : ref() etait lu directement ici, donc ce
        # bloc (les champs Eleve/Compte/Montant... du formulaire de Saisie)
        # se reconstruisait a chaque ecriture comptable ailleurs (meme
        # cause que le correctif de page()/corps() ci-dessus) et effacait ce
        # que l'utilisateur etait en train de taper ou de choisir - c'etait
        # notamment le cas visible sur le champ "Eleve" en plein milieu
        # d'une recherche. Isoler cette lecture est sans perte
        # fonctionnelle : un tiers tape librement mais absent de la liste
        # reste gere normalement a l'enregistrement (resoudre_tiers,
        # cf. create=True plus bas) ; seule la fraicheur immediate de la
        # liste proposee change, pas la possibilite de saisir.
        with reactive.isolate():
            r = ref()
        # "Ecriture libre" a deux jeux de champs possibles ; les autres
        # modeles n'en ont qu'un. resoudre_variante() choisit le bon selon le
        # journal deja affiche dans le selecteur au-dessus - lire
        # input.m_journal() ici rend ce bloc reactif au journal, pas
        # seulement au modele : changer de journal met a jour les champs
        # sans que la caissiere ait rien d'autre a faire.
        champs, _ = md.resoudre_variante(m, req(input.m_journal()), r)
        # Une correction en cours pre-remplit chaque champ avec sa valeur
        # d'origine, mais seulement tant que le modele et le journal affiches
        # correspondent encore a la piece qu'on corrige : si l'utilisateur
        # change d'avis et choisit un autre modele, les valeurs de l'ancienne
        # piece n'ont plus de raison de s'imposer.
        cor = correction()
        pre = {}
        if cor and cor["modele"] == input.m_modele() and cor["journal"] == input.m_journal():
            pre = cor["valeurs"]
        widgets = []
        for ch in champs:
            id_ = f"ch_{ch['n']}"
            t = ch["t"]
            defaut = pre.get(ch["n"])
            if t == "tiers":
                # Seuls les tiers actifs pour l'annee academique en cours sont
                # proposes, pour ne pas polluer la liste avec des annees
                # revolues. "create=True" laisse taper un nom absent de la
                # liste (nouvel eleve, nouveau professeur, ancien tiers
                # revenu) : le code definitif n'est genere/reactive qu'au
                # moment de l'enregistrement (resoudre_tiers), jamais pendant
                # la frappe.
                sous = r["tiers"][
                    r["tiers"]["code_tiers"].str.startswith(ch["pref"])
                    & (r["tiers"]["actif_annee"] == "oui")
                ]
                choix = {"": ""}
                for _, row in sous.iterrows():
                    choix[row["code_tiers"]] = f"{row['intitule']}  ({row['code_tiers']})"
                if defaut and defaut not in choix:
                    choix[defaut] = defaut
                widgets.append(ui.input_selectize(
                    id_, ch["l"], choices=choix, selected=defaut or "",
                    options={"create": True, "placeholder": "Rechercher..."}))
                if ch.get("historique"):
                    widgets.append(ui.output_ui("m_bloc_historique"))
            elif t == "compte":
                # "filtre" restreint la liste a une colonne oui/non du
                # referentiel (ex. depense_courante) : "Depense courante" ne
                # propose ainsi que des comptes de charge reellement
                # recurrents, jamais un compte a tiers obligatoire. Sans
                # filtre (ex. "Ecriture libre"), la liste complete reste
                # disponible pour les cas rares.
                comptes = r["comptes"]
                if ch.get("filtre"):
                    comptes = comptes[comptes[ch["filtre"]] == "oui"]
                # "exclut" retire au contraire les comptes marques "oui" dans
                # la colonne citee.
                if ch.get("exclut") and ch["exclut"] in comptes.columns:
                    comptes = comptes[comptes[ch["exclut"]] != "oui"]
                # "choix" fige une liste courte ecrite dans le modele lui-meme,
                # quand les comptes possibles se comptent sur les doigts d'une
                # main et ne meritent pas une colonne du referentiel.
                if ch.get("choix"):
                    comptes = comptes[comptes["compte"].isin(ch["choix"])]
                choix = {"": ""}
                for _, row in comptes.iterrows():
                    choix[row["compte"]] = f"{row['compte']} - {row['intitule']}"
                widgets.append(ui.input_selectize(
                    id_, ch["l"], choices=choix, selected=defaut or "",
                    options={"placeholder": "Rechercher..."}))
            elif t == "libelle":
                # Si le filtrage ne laisse aucune suggestion, on retombe sur
                # la liste complete plutot que de laisser un champ vide et
                # bloque : create=True permet de toute facon de taper
                # n'importe quoi, la liste n'est qu'une aide, jamais une
                # obligation.
                base = _libelles_pour_champ(m, r)
                if len(base) == 0:
                    base = r["libelles"]
                choix = {"": ""}
                for lib in base["libelle"].dropna().unique():
                    choix[lib] = lib
                if defaut and defaut not in choix:
                    choix[defaut] = defaut
                widgets.append(ui.input_selectize(
                    id_, ch["l"], choices=choix, selected=defaut or "",
                    options={"create": True, "placeholder": "Rechercher..."}))
            elif t == "mois":
                widgets.append(ui.input_select(id_, ch["l"], choices=md.MOIS_FR,
                                                selected=defaut or md.MOIS_FR[date.today().month - 1]))
            elif t == "montant":
                valeur = defaut if defaut not in (None, "") else ch.get("defaut") or 0
                # update_on="blur" : meme raison que m_rep_montant_* plus bas
                # (repartition) - sans ca, chaque chiffre tape ici reconstruit
                # tout l'apercu "Ecriture generee".
                widgets.append(ui.input_numeric(id_, ch["l"], value=float(valeur), min=0, step=500,
                                                 update_on="blur"))
            elif t == "oui_non":
                widgets.append(ui.input_select(id_, ch["l"], choices={"oui": "Oui", "non": "Non"},
                                                selected=defaut or "non"))
            elif t == "choix":
                widgets.append(ui.input_select(id_, ch["l"], choices=ch["options"],
                                                selected=defaut or next(iter(ch["options"]))))
            elif t == "centre":
                # Liste tiree du referentiel, jamais ecrite en dur : un centre
                # ajoute ou desactive plus tard apparait ou disparait tout
                # seul. Tous les centres actifs restent selectionnables, y
                # compris le sien : une regle de gestion change, l'application
                # doit y survivre sans qu'on touche au code.
                #
                # Les centres s'affichent en TOUTES LETTRES ("SIAO", "Pissy").
                # Le code a trois lettres est une cle technique, il reste la
                # valeur stockee mais n'apparait jamais a l'ecran.
                cx = r["centres"]
                if "actif" in cx.columns:
                    cx = cx[cx["actif"] == "oui"]
                choix = {row["code_centre"]: row["intitule"] for _, row in cx.iterrows()}
                # "mien" = le centre de l'utilisateur connecte ; sinon un code
                # de centre ecrit dans le modele (voir CENTRE_DESTINATAIRE_PAR_DEFAUT).
                souhaite = ch.get("defaut_centre")
                if souhaite == "mien":
                    with reactive.isolate():
                        souhaite = (util() or {}).get("centre")
                # `presel`, pas `pre` : `pre` est deja le dictionnaire des
                # valeurs de la piece en cours de correction, utilise par tous
                # les champs suivants de la boucle.
                presel = defaut or (souhaite if souhaite in choix else None)
                widgets.append(ui.input_select(id_, ch["l"], choices=choix or {"": "Aucun centre actif"},
                                                selected=presel or (next(iter(choix)) if choix else "")))
            elif t == "repartition":
                widgets.append(ui.output_ui("m_bloc_repartition"))
            else:
                widgets.append(ui.input_text(id_, ch["l"], value=defaut or ""))
        return ui.TagList(*widgets)

    # La note n'a de sens que pour "Ecriture libre" : c'est le seul modele ou
    # une operation peut vraiment avoir besoin d'un mot d'explication pour le
    # comptable (compte a creer, contexte du 471000). Sur les 12 autres
    # modeles, l'operation est deja entierement decrite par ses champs -
    # ajouter une note partout serait juste du remplissage visuel.
    @render.ui
    def m_note_wrap():
        if req(input.m_modele()) != "libre":
            return None
        return ui.input_text_area(
            "m_note", "Note pour le comptable (facultatif)", rows=2)

    @reactive.calc
    def valeurs():
        m = md.modele_par_id(req(input.m_modele()))
        # Corrige le 10/09/2026 (ter) : ref() etait lu directement ici. Comme
        # operation()/m_apercu()/m_ruban() dependent tous de valeurs(), toute
        # ecriture enregistree ailleurs (sondage _disque(), 0,5 s) reconstruisait
        # l'apercu "Ecriture generee" en entier meme sans rien y toucher - Afiya
        # l'a signale comme "ca bouge" a l'ouverture et pendant la saisie du
        # montant. Meme traitement que pour m_champs() (Groupe 6) : la lecture
        # du referentiel est isolee, valeurs() reste reactif aux vrais
        # changements (modele, journal, champs tapes).
        with reactive.isolate():
            r = ref()
        champs, _ = md.resoudre_variante(m, req(input.m_journal()), r)
        v = {}
        # Centre de l'utilisateur connecte. Le modele "transfert_interne" en a
        # besoin pour savoir de quel cote de l'operation il se trouve : le sens
        # n'est pas un champ du formulaire, il se deduit de qui saisit.
        with reactive.isolate():
            u_courant = util()
        v["mon_centre"] = (u_courant or {}).get("centre", "")
        for ch in champs:
            v[ch["n"]] = get_input(f"ch_{ch['n']}")
        for ch in champs:
            if ch["t"] == "repartition":
                v[ch["n"]] = _lire_repartition()
        # Pour chaque champ tiers (eleve, fournisseur, personnel...), calcule
        # seulement le nom a afficher dans le libelle - jamais le code, qui
        # ne doit etre fige qu'a l'enregistrement (_enregistrer). La valeur
        # brute (code existant choisi, ou nom tape librement) reste dans
        # v[ch["n"]] telle quelle : c'est elle que resoudre_tiers() traitera.
        for ch in champs:
            if ch["t"] == "tiers" and v.get(ch["n"]):
                brut = v[ch["n"]]
                code = dl.code_tiers_candidat(brut, ch["pref"], r)
                tiers = r["tiers"]
                m_existant = tiers[tiers["code_tiers"] == code]
                v[f"{ch['n']}_nom"] = m_existant.iloc[0]["intitule"] if len(m_existant) else str(brut).upper()
        # La date de la piece est mise a disposition des libelles. Elle evite un
        # champ : dans l'historique, le mois ecrit dans un libelle de facture est
        # celui de la piece dans 966 cas sur 966. Le demander serait faire retaper
        # une information deja saisie juste au-dessus.
        try:
            d = input.m_date()
            v["_mois"] = md.MOIS_FR[d.month - 1]
            v["_annee"] = f"{d.year % 100:02d}"
        except Exception:
            v["_mois"] = ""
            v["_annee"] = ""
        return v

    # Une saisie en cours est presque toujours incomplete : operation() renvoie
    # None tant que l'ecriture n'est pas constructible, jamais une erreur.
    # Une operation contient une piece, ou deux quand les deux caisses bougent
    # ensemble (transfert de la caisse principale vers les menues depenses).
    @reactive.calc
    def operation():
        req(input.m_modele(), input.m_journal())
        try:
            with reactive.isolate():
                journaux = ref()["journaux"]
            return md.construire_operation(input.m_modele(), valeurs(), input.m_journal(), journaux)
        except Exception:
            return None

    def table_ecriture(L, r):
        tr = set(r["journaux"]["compte_contrepartie"])
        lignes_html = []
        for _, x in L.iterrows():
            cls = "tresorerie" if x["compte"] in tr else ""
            lignes_html.append(
                f"<tr class='{cls}'>"
                f"<td class='num'>{x['compte']}<br><span style='font-size:10px;color:var(--hk-texte-doux)'>"
                f"{dl.intitule_compte(r, x['compte'])}</span></td>"
                f"<td class='num' style='font-size:11px'>{x['code_tiers']}</td>"
                f"<td>{x['libelle']}</td>"
                f"<td class='m'>{dl.fcfa(x['debit']) if float(x['debit']) > 0 else ''}</td>"
                f"<td class='m'>{dl.fcfa(x['credit']) if float(x['credit']) > 0 else ''}</td></tr>"
            )
        return (
            "<table class='apercu'><thead><tr><th>Compte</th><th>Tiers</th><th>Libelle</th>"
            "<th class='m'>Debit</th><th class='m'>Credit</th></tr></thead><tbody>"
            + "".join(lignes_html) +
            f"</tbody><tfoot><tr><td colspan='3'>Totaux</td><td class='m'>{dl.fcfa(L['debit'].sum())}"
            f"</td><td class='m'>{dl.fcfa(L['credit'].sum())}</td></tr></tfoot></table>"
        )

    @render.ui
    def m_apercu():
        op = operation()
        if op is None:
            return ui.div({"class": "ruban att"}, "Renseignez l'operation : l'ecriture se construit ici.")
        # Meme correctif que valeurs() ci-dessus : ne pas rendre m_apercu()
        # dependant de _disque() (0,5 s), sinon tout l'apercu "Ecriture
        # generee" se reconstruit en boucle pendant que la piece se remplit.
        with reactive.isolate():
            r = ref()
        morceaux = []
        for i, p in enumerate(op):
            ligne_j = r["journaux"].loc[r["journaux"]["journal"] == p["journal"], "intitule"]
            intitule = ligne_j.iloc[0] if len(ligne_j) else p["journal"]
            if len(op) > 1:
                marge = "0" if i == 0 else "18px"
                morceaux.append(
                    f"<div style='font-size:11px;text-transform:uppercase;letter-spacing:.06em;"
                    f"color:var(--hk-texte-doux);font-weight:600;margin:{marge} 0 6px'>Piece {i + 1} sur {len(op)} - "
                    f"journal {p['journal']}, {intitule}</div>")
            morceaux.append(table_ecriture(p["lignes"], r))
        return ui.HTML("".join(morceaux))

    @reactive.calc
    def equilibree():
        return md.operation_equilibree(operation())

    # Effet de l'operation sur chaque caisse, avant enregistrement.
    def effet_caisses(op, r):
        res = {}
        for j in r["journaux"]["journal"]:
            cc_s = r["journaux"].loc[r["journaux"]["journal"] == j, "compte_contrepartie"]
            cc = cc_s.iloc[0] if len(cc_s) else None
            d = 0.0
            for p in op:
                L = p["lignes"]
                d += L.loc[L["compte"] == cc, "debit"].sum() - L.loc[L["compte"] == cc, "credit"].sum()
            if round(d) != 0:
                res[j] = d
        return res

    @render.ui
    def m_ruban():
        op = operation()
        if op is None:
            return None
        # Meme correctif que m_apercu()/valeurs() : r et donnees() ne doivent
        # pas rendre ce ruban dependant de _disque() (0,5 s) ni du sondage
        # d'ecritures - seul un vrai changement de la piece en cours (modele,
        # journal, champs) doit le reconstruire.
        with reactive.isolate():
            r = ref()
            u = util()
        if not equilibree():
            return ui.div({"class": "ruban ko"},
                           "L'operation n'est pas equilibree : elle ne peut pas etre enregistree.")
        doubles = md.comptes_annules(op)
        if doubles:
            return ui.div({"class": "ruban ko"},
                           f"Le compte {', '.join(doubles)} est debite et credite pour le meme tiers : "
                           "l'ecriture s'annule d'elle-meme. Choisissez deux comptes differents.")
        eff = effet_caisses(op, r)
        comptable = est_comptable()
        morceaux = []
        with reactive.isolate():
            d = donnees()
        for j, val in eff.items():
            physique = "caisse_physique" in r["journaux"].columns and (
                r["journaux"].loc[r["journaux"]["journal"] == j, "caisse_physique"] == "oui").iloc[0]
            if not physique and not comptable:
                # La banque est un compte partage reserve au comptable : une
                # caissiere qui fait un versement en banque voit l'effet sur
                # sa propre caisse (ci-dessous), jamais le solde de la banque.
                continue
            centre_c = u["centre"] if physique else None
            apres = dl.solde_caisse(j, r, d, centre=centre_c) + val
            sens = "diminue" if val < 0 else "augmente"
            morceaux.append(f"caisse {j} {sens} de <span class='num'>{dl.fcfa(abs(val))}</span> F, "
                             f"solde <span class='num'>{dl.fcfa(apres)}</span> F")
        prefixe = (f"Operation liee, {len(op)} pieces enregistrees ensemble. "
                   if len(op) > 1 else "Piece equilibree. ")
        if not morceaux:
            # Tous les journaux touches etaient la banque, masquee pour ce
            # role : confirmer quand meme que l'operation est prete.
            return ui.div({"class": "ruban ok"}, ui.HTML(prefixe + "Prete a etre enregistree."))
        return ui.div({"class": "ruban ok"}, ui.HTML(prefixe + " ; ".join(morceaux) + "."))

    # Le bouton est desactive pendant tout le traitement (15/09/2026) : sur un
    # poste de caisse lent, un double-clic enregistrait DEUX pieces completes,
    # avec deux numeros et deux mouvements de caisse. Rien ne permettait de
    # les rattraper ensuite - prises une a une, les deux pieces sont
    # irreprochables, et controler() ne detecte pas un doublon exact. Le solde
    # restait faux jusqu'a ce que quelqu'un s'en apercoive. _ajouter_compte et
    # _ajouter_utilisateur avaient deja ce filet, pour des operations pourtant
    # bien moins sensibles.
    @reactive.effect
    @reactive.event(input.m_enregistrer)
    def _enregistrer():
        ui.update_action_button("m_enregistrer", disabled=True)
        try:
            _enregistrer_piece()
        finally:
            ui.update_action_button("m_enregistrer", disabled=False)

    def _enregistrer_piece():
        if not equilibree():
            ui.notification_show("Opération déséquilibrée ou incomplète.", type="error")
            return
        u = util()
        m = md.modele_par_id(input.m_modele())

        # Resolution definitive des champs tiers : un nom nouveau devient un
        # tiers reellement cree dans le referentiel a cet instant precis, un
        # ancien tiers retape est reactive avec son code d'origine. C'est le
        # seul moment ou le referentiel est modifie par la saisie - jamais
        # pendant la frappe (valeurs()/operation() ne font qu'un apercu).
        v_resolues = dict(valeurs())
        try:
            champs, _ = md.resoudre_variante(m, input.m_journal(), ref())
            for ch in champs:
                if ch["t"] == "tiers" and v_resolues.get(ch["n"]):
                    v_resolues[ch["n"]] = dl.resoudre_tiers(
                        v_resolues[ch["n"]], ch["pref"], ch["collectif"])
        except Exception as e:
            ui.notification_show(f"Impossible de resoudre le tiers : {e}", type="error")
            return

        op = md.construire_operation(input.m_modele(), v_resolues, input.m_journal(), ref()["journaux"])
        if op is None or not md.operation_equilibree(op):
            ui.notification_show("Opération déséquilibrée ou incomplète.", type="error")
            return
        doubles = md.comptes_annules(op)
        if doubles:
            ui.notification_show(f"Compte {', '.join(doubles)} debite et credite pour le meme tiers : "
                                 "l'ecriture n'aurait aucun effet.", type="error")
            return

        try:
            note = get_input("m_note", "") if input.m_modele() == "libre" else ""
            res = dl.enregistrer_operation(op, u["centre"], input.m_date(), input.m_modele(),
                                            u["identifiant"], note=note, valeurs=v_resolues)
        except Exception as e:
            ui.notification_show(str(e), type="error")
            return

        # Si on venait de "Corriger" : la nouvelle piece est enregistree,
        # l'ancienne (a_corriger) n'a plus de raison d'exister. Une erreur ici
        # (piece deja supprimee entre-temps par le comptable, par exemple)
        # n'annule pas l'enregistrement qui vient de reussir - elle est juste
        # signalee a part.
        cor = correction()
        if cor is not None:
            try:
                dl.supprimer_piece(cor["id_piece"], u["identifiant"])
            except Exception as e:
                ui.notification_show(f"Piece corrigee, mais l'ancienne n'a pas pu etre retiree : {e}",
                                      type="warning")
            correction.set(None)
            ui.notification_show(f"Correction enregistree : {', '.join(res)} remplace {cor['id_piece']}",
                                  type="message")
        elif len(res) > 1:
            ui.notification_show(f"Operation enregistree : pieces {' et '.join(res)}, une par caisse",
                                  type="message")
        else:
            ui.notification_show(f"Piece {res[0]} enregistree", type="message")
        dernier_msg.set("Derniere operation : " + ", ".join(res))
        ui.update_text_area("m_note", value="")
        reinitialiser()
        rafraichir()

    @render.ui
    def m_dernier():
        if dernier_msg() is None:
            return None
        return ui.tags.span({"style": "margin-left:12px;color:var(--hk-texte-doux)"}, dernier_msg())

    @render.ui
    def m_correction_bandeau():
        cor = correction()
        if cor is None:
            return None
        if cor.get("restaure", True):
            texte = (f"Correction de la piece {cor['id_piece']} : les informations d'origine sont "
                     "reprises ci-dessous. Modifiez puis enregistrez. ")
        else:
            texte = (f"Correction de la piece {cor['id_piece']} : piece anterieure a la sauvegarde "
                      "des valeurs, les champs sont vides. Ressaisissez puis enregistrez. ")
        return ui.div(
            {"class": "ruban info"}, texte,
            ui.input_action_link("m_annuler_correction", "Annuler la correction"),
        )

    @reactive.effect
    @reactive.event(input.m_annuler_correction)
    def _annuler_correction():
        correction.set(None)
        ui.notification_show("Correction annulee, rien n'a ete modifie.", type="message")

    def reinitialiser():
        m = md.modele_par_id(input.m_modele())
        if m is None:
            return
        champs, _ = md.resoudre_variante(m, input.m_journal(), ref())
        for ch in champs:
            id_ = f"ch_{ch['n']}"
            if ch["t"] == "montant":
                ui.update_numeric(id_, value=float(ch.get("defaut") or 0))
            elif ch["t"] in ("tiers", "compte", "libelle"):
                ui.update_selectize(id_, selected="")
            elif ch["t"] == "texte":
                ui.update_text(id_, value="")
            elif ch["t"] == "choix" and ch.get("options"):
                ui.update_select(id_, selected=next(iter(ch["options"])))
            elif ch["t"] == "centre":
                # Rien a remettre a zero : la liste est reconstruite par
                # m_champs a chaque changement de modele, et son premier
                # element est deja selectionne.
                pass

        # Repartition : on repart sur une ligne NEUVE (identifiant jamais utilise)
        # plutot que de remettre a zero la ligne existante. _ligne_repartition_ui()
        # lit les valeurs actuelles avec reactive.isolate() au moment de construire
        # le widget : sur un identifiant neuf, get_input() ne trouve rien et retombe
        # sur les valeurs par defaut. Cela evite la course entre ui.update_numeric()
        # (message asynchrone vers le client) et le re-rendu de m_bloc_repartition,
        # qui relirait sinon l'ancien montant cote serveur et le reafficherait.
        nouveau = rep_prochain_id()
        rep_prochain_id.set(nouveau + 1)
        _fabrique_effets_repartition(nouveau)
        rep_ids.set([nouveau])

    @reactive.effect
    @reactive.event(input.m_vider)
    def _vider():
        reinitialiser()

    # ---------------- brouillard ---------------------------------------------

    @reactive.calc
    def pieces_vue():
        d = donnees()
        u = req(util())  # tab inatteignable avant connexion, garde defensive quand meme
        if len(d) == 0:
            return d
        if not est_comptable():
            d = d[d["centre"] == u["centre"]]
        if input.b_journal() and input.b_journal() != "Tous":
            d = d[d["journal"] == input.b_journal()]
        if input.b_statut() and input.b_statut() != "Tous":
            code = [k for k, v in STATUTS.items() if v == input.b_statut()]
            if code:
                d = d[d["statut"] == code[0]]
        periode = input.b_periode()
        if periode and periode[0] and periode[1]:
            dts = pd.to_datetime(d["date_piece"])
            d = d[(dts >= pd.Timestamp(periode[0])) & (dts <= pd.Timestamp(periode[1]))]
        return d

    def table_pieces(d, centres):
        if len(d) == 0:
            return pd.DataFrame({"Message": ["Aucune pièce pour ce filtre."]})
        # File d'attente, pas registre comptable : la piece la plus recemment
        # saisie remonte en tete, quelle que soit sa date d'operation. Une
        # depense datee du 17 mais saisie aujourd'hui doit apparaitre avant
        # les pieces du 20 saisies hier - c'est l'ordre de saisie (saisi_le)
        # qui classe, jamais la date comptable (date_piece), qui elle ne
        # bouge pas et reste la seule utilisee pour l'export Sage.
        d = d.sort_values("saisi_le", ascending=False, kind="mergesort")
        # Nom complet du centre plutot que son abreviation (SAA -> Saaba) :
        # la comptable et les caissieres lisent ce tableau, pas Sage - Sage,
        # lui, garde sa section analytique abregee (cf. format_sage), qui
        # n'est pas ce tableau-ci.
        noms_centres = dict(zip(centres["code_centre"], centres["intitule"]))
        lignes = []
        ids = []
        # groupby(sort=False) plutot que "unique() puis filtrer" : memes
        # groupes, meme ordre (premiere apparition dans d, deja trie par
        # saisi_le ci-dessus), mais sans rescanner tout le tableau a chaque
        # piece - decisif des que le nombre de pieces grandit (corrige le
        # 13/09/2026, meme optimisation que logic.donnees.controler()).
        for idp, p in d.groupby("id_piece", sort=False):
            code_centre = p["centre"].iloc[0]
            lignes.append({
                "Date": pd.to_datetime(p["date_piece"].iloc[0]).strftime("%d/%m/%Y"),
                "Piece": dl.ou(p["num_definitif"].iloc[0], p["num_provisoire"].iloc[0]),
                "Journal": p["journal"].iloc[0],
                "Centre": noms_centres.get(code_centre, code_centre),
                "Libelle": p["libelle"].iloc[0],
                "Montant": dl.fcfa(p["debit"].sum()),
                "Statut": STATUTS.get(p["statut"].iloc[0], p["statut"].iloc[0]),
                "Saisi_par": p["saisi_par"].iloc[0],
                "Observation": p["observation"].iloc[0],
            })
            ids.append(idp)
        out = pd.DataFrame(lignes)
        out.index = ids
        return out

    # filters=True (rangee de filtres sous les en-tetes, native a
    # render.DataGrid) plutot qu'une dependance externe : quelques centaines
    # de pieces par an, une poignee d'utilisateurs simultanes, aucun besoin
    # de tri/filtre serveur cote base. Le filtrage entierement cote
    # navigateur suffit tant que ces volumes restent d'un ordre de grandeur
    # "annee scolaire", et evite d'ajouter une librairie pour ce que Shiny
    # fait deja nativement.
    # Classe CSS par valeur affichee dans la colonne "Statut" (cf. CSS
    # .cell-statut-*) : un code technique ("a_corriger") devient une classe
    # CSS valide en remplacant les underscores, le texte humain reste ce que
    # STATUTS affiche deja dans la colonne.
    _CLASSE_PAR_STATUT = {texte: f"cell-statut-{code}" for code, texte in STATUTS.items()}

    def styles_statut(d):
        if "Statut" not in d.columns:
            return []
        styles = []
        for texte, classe in _CLASSE_PAR_STATUT.items():
            lignes = [i for i, v in enumerate(d["Statut"]) if v == texte]
            if lignes:
                styles.append({"rows": lignes, "cols": ["Statut"], "class": classe})
        return styles

    def grille_pieces(d, selection_mode):
        if "Message" in d.columns:
            return render.DataGrid(d, selection_mode="none", width="100%")
        return render.DataGrid(d, selection_mode=selection_mode, width="100%", filters=True,
                                styles=styles_statut(d))

    # Le Referentiel et les Controles affichent le resultat brut d'un
    # SELECT * : des colonnes avec des None/NaN non uniformises, contrairement
    # aux tableaux ci-dessus qui passent par une fonction de mise en forme.
    # C'est ce qui empechait filters=True de fonctionner (l'inference de type
    # cote navigateur se perd sur une colonne au contenu heterogene). On
    # nettoie donc avant d'envoyer au navigateur : index par defaut, valeurs
    # manquantes remplacees par une chaine vide, colonnes textuelles casees en
    # str pur.
    def _pour_grille(d):
        d = d.reset_index(drop=True).copy()
        for col in d.columns:
            if d[col].dtype == "object":
                d[col] = d[col].fillna("").astype(str)
        return d

    # Les trois premiers indicateurs suivent le filtre affiche ; les soldes de
    # caisse portent toujours sur la totalite des ecritures (sinon ce ne
    # seraient pas des soldes), et couvrent tous les journaux de tresorerie
    # actifs du referentiel - CP et CMD hier, la banque aujourd'hui, un
    # quatrieme demain sans qu'il faille toucher ce code.
    #
    # Le solde de la banque (compte partage, jamais ventile par centre) n'est
    # jamais affiche a un utilisateur qui n'est pas comptable, meme quand son
    # action touche ce journal (ex. "Versement d'especes en banque") : seul
    # le comptable, qui suit la tresorerie de toute la maison, doit voir ce
    # chiffre. Une caisse physique (CP, CMD), a l'inverse, montre au
    # comptable le total consolide de tous les centres, et a chaque autre
    # utilisateur le solde de son seul centre.
    @render.ui
    def b_stats():
        d = pieces_vue()
        r = ref()
        u = util()
        comptable = est_comptable()
        cc = set(r["journaux"]["compte_contrepartie"])
        entrees = d.loc[d["compte"].isin(cc), "debit"].sum() if len(d) else 0
        sorties = d.loc[d["compte"].isin(cc), "credit"].sum() if len(d) else 0
        jx = r["journaux"]
        if "type" in jx.columns:
            jx = jx[jx["type"].fillna("tresorerie") == "tresorerie"]
        if "actif" in jx.columns:
            jx = jx[jx["actif"].fillna("oui") == "oui"]
        # Refonte visuelle - etape 5 : pastille icone via composants.py::
        # stat(). Le nombre d'indicateurs reste variable (role connecte,
        # cf. boucle ci-dessous) - la maquette en montrait 4 fixes, ici il
        # y en a 3 + un par caisse visible (5 pour un role local, 6 pour
        # le comptable siege) : tous conserves, aucun retire.
        cartes = [
            stat("Pièces affichées", str(d["id_piece"].nunique()) if len(d) else "0",
                 icone="file-earmark-text"),
            stat("Entrées en caisse", dl.fcfa(entrees), icone="arrow-down-circle"),
            stat("Sorties de caisse", dl.fcfa(sorties), icone="arrow-up-circle"),
        ]
        dtot = donnees()
        for j in jx["journal"]:
            physique = "caisse_physique" in jx.columns and \
                (jx.loc[jx["journal"] == j, "caisse_physique"] == "oui").iloc[0]
            if not physique and not comptable:
                continue
            centre_c = None if (comptable or not physique) else u["centre"]
            libelle = f"Solde {j}" if centre_c is None else f"Solde {j} ({u['centre']})"
            cartes.append(stat(libelle, dl.fcfa(dl.solde_caisse(j, r, dtot, centre=centre_c)),
                                icone="wallet2"))
        return ui.TagList(
            *cartes,
            ui.div({"style": "font-size:11px;color:var(--hk-texte-doux);grid-column:1/-1;margin-top:2px"},
                   "Soldes toujours calculés sur l'ensemble des pièces, filtré ou non."),
        )

    @render.data_frame
    def b_table():
        return grille_pieces(table_pieces(pieces_vue(), ref()["centres"]), "row")

    @reactive.effect
    @reactive.event(input.b_supprimer)
    def _supprimer():
        # Controle de centre cote serveur, ajoute le 15/09/2026. Cette
        # fonction n'en avait aucun, alors que _valider et _rejeter en ont un
        # depuis le 11/09 : b_table ne montre que les pieces du centre
        # connecte, mais masquer une ligne cote client n'est pas un controle
        # d'acces (voir _hors_centre()).
        #
        # Le point sensible est supprimer_piece(), qui elargit aux pieces
        # liees : un approvisionnement relie deux pieces qui appartiennent a
        # deux centres differents. Supprimer sa moitie emportait donc celle de
        # l'autre centre. La selection est pour cette raison elargie ICI,
        # avant le controle, jamais apres - meme ordre que dans _valider.
        u = util()
        if u is None:
            return
        sel = b_table.data_view(selected=True)
        if len(sel) == 0 or "Message" in sel.columns:
            ui.notification_show("Choisir d'abord une pièce.", type="warning")
            return
        d = donnees()
        ids = dl.avec_liees(list(sel.index), d)
        if not est_comptable() and _hors_centre(ids, d, u):
            ui.notification_show("Ces pieces appartiennent a un autre centre.", type="error")
            return
        try:
            dl.supprimer_piece(ids, u["identifiant"])
        except Exception as e:
            ui.notification_show(str(e), type="error")
        else:
            ui.notification_show("Pièce supprimée", type="message")
        rafraichir()

    # "Corriger" ne construit aucun ecran : elle recharge Saisie avec le
    # modele, le journal, la date et les valeurs d'origine de la piece
    # (conservees dans valeurs_json a l'enregistrement), pret a etre modifie
    # et renvoye. L'ancienne piece n'est retiree qu'a l'enregistrement de la
    # nouvelle (_enregistrer), jamais avant : abandonner une correction en
    # cours de route ne doit rien casser.
    @reactive.effect
    @reactive.event(input.b_corriger)
    def _corriger():
        sel = b_table.data_view(selected=True)
        if len(sel) == 0 or "Message" in sel.columns:
            ui.notification_show("Choisir d'abord une pièce.", type="warning")
            return
        if len(sel) > 1:
            ui.notification_show("Choisir une seule piece a corriger.", type="warning")
            return
        idp = sel.index[0]
        d = donnees()
        p = d[d["id_piece"] == idp]
        if len(p) == 0:
            ui.notification_show("Pièce introuvable.", type="error")
            return
        if p["statut"].iloc[0] != "a_corriger":
            ui.notification_show("Seule une piece renvoyee pour correction peut etre corrigee ainsi.",
                                  type="warning")
            return
        modele = p["modele"].iloc[0]
        journal = p["journal"].iloc[0]
        if md.modele_par_id(modele) is None:
            ui.notification_show("Modèle d'origine introuvable, correction impossible ici.", type="error")
            return
        brut = p["valeurs_json"].iloc[0]
        try:
            vals = json.loads(brut) if brut else {}
        except (TypeError, ValueError):
            vals = {}
        restaure = bool(vals)
        try:
            date_piece = pd.to_datetime(p["date_piece"].iloc[0]).date()
        except Exception:
            date_piece = date.today()
        correction.set({"id_piece": idp, "modele": modele, "journal": journal,
                         "valeurs": vals, "restaure": restaure})
        ui.update_select("m_modele", selected=modele)
        ui.update_select("m_journal", selected=journal)
        ui.update_date("m_date", value=date_piece)
        ui.update_navs("onglets", selected="saisie")
        if not restaure:
            ui.notification_show(
                "Piece anterieure a la sauvegarde des valeurs de saisie : modele, journal et date "
                "sont repris, mais les champs du formulaire sont a ressaisir.", type="warning")

    # ---------------- validation ---------------------------------------------

    @reactive.calc
    def attente():
        # Corrige le 11/09/2026 : ne filtrait par aucun centre - un
        # validateur local voyait les pieces en attente de tous les centres,
        # pas seulement les siennes. Seul le comptable du siege voit
        # l'ensemble ; meme regle que pieces_vue()/anomalies_vue().
        u = req(util())
        d = donnees()
        d = d[d["statut"].isin(["saisie", "a_corriger"])]
        if not est_comptable():
            return d[d["centre"] == u["centre"]]
        # Comptable du siege : filtre d'affichage facultatif (18/09/2026, voir
        # onglet_validation). get_input tolere l'absence de l'input - la
        # premiere lecture peut preceder son arrivee cote client, et un
        # validateur local n'a jamais ce selecteur.
        choix = get_input("v_centre", "Tous")
        if choix and choix != "Tous":
            d = d[d["centre"] == choix]
        return d

    @render.data_frame
    def v_table():
        return grille_pieces(table_pieces(attente(), ref()["centres"]), "rows")

    # Compte en clair les pieces reellement retenues, a cote des boutons qui
    # vont agir dessus.
    #
    # Deux comportements de la grille, invisibles autrement, le rendent
    # necessaire :
    #   - en selection multiple, un clic SIMPLE remplace la selection ; seuls
    #     Ctrl+clic (ajouter une ligne) et Maj+clic (une plage) l'etendent.
    #     Une validatrice qui cliquait cinq lignes de suite n'en avait qu'une
    #     de retenue - la derniere - et rien ne le lui disait ;
    #   - la rangee de filtres ajoutee a la refonte retire de la selection
    #     toute ligne qu'un filtre vient de masquer (le composant ne renvoie
    #     que les lignes presentes dans la vue filtree), egalement en
    #     silence.
    # Le compteur ne change rien a ce qui est traite : il rend visible ce qui
    # l'est deja, avant le clic sur "Valider".
    @render.ui
    def v_selection():
        try:
            sel = v_table.data_view(selected=True)
        except Exception:
            return None
        n = 0 if "Message" in getattr(sel, "columns", []) else len(sel)
        if n == 0:
            return ("Aucune pièce choisie — Ctrl+clic pour en choisir plusieurs, "
                    "Maj+clic pour une plage.")
        return f"{n} pièce choisie." if n == 1 else f"{n} pièces choisies."

    # Pourquoi une piece selectionnee n'a pas pu etre validee. Le texte doit
    # dire au validateur ce qu'il lui reste a faire, pas seulement nommer un
    # statut technique : "a_corriger" ne lui apprend rien, "en attente de
    # resaisie par la caissiere" lui rappelle qu'il a une relance a passer.
    RAISON_NON_VALIDABLE = {
        "a_corriger": "à corriger — en attente de resaisie par la caissière",
        "validee": "déjà validée",
        "exportee": "déjà exportée vers Sage",
    }

    def _message_validation(res):
        """Rend compte honnetement du lot : ce qui a ete valide, et ce qui a
        ete ecarte avec la raison.

        Corrige le 12/09/2026. La regle metier ne bouge pas - une piece
        renvoyee pour correction reste bloquee tant qu'elle n'a pas ete
        resaisie, c'est bien ce qu'on veut. Ce qui bouge, c'est ce que
        l'application DIT : elle affichait "1 piece(s) validee(s)" apres une
        selection de cinq, laissant croire que le lot etait traite. Les
        quatre pieces ecartees sont desormais annoncees, avec leur statut et
        ce qu'il implique."""
        n = len(res["validees"])
        phrases = [f"{n} pièce validée et numérotée." if n == 1
                   else f"{n} pièces validées et numérotées."]
        for statut, pieces in sorted(res["ignorees"].items()):
            raison = RAISON_NON_VALIDABLE.get(statut, f"statut « {statut} »")
            phrases.append(f"{len(pieces)} pièce ignorée (statut : {raison})." if len(pieces) == 1
                           else f"{len(pieces)} pièces ignorées (statut : {raison}).")
        return " ".join(phrases)

    @reactive.effect
    @reactive.event(input.v_valider)
    def _valider():
        # Filet de securite cote serveur : v_valider n'est boutonne qu'a
        # l'ecran pour un role de validation (comptable du siege ou
        # validateur local), mais un input Shiny reste positionnable par
        # n'importe quel client de la session (masquer un widget n'est pas
        # un controle d'acces) - la verification du role doit donc etre
        # refaite ici, jamais seulement dans onglets()/onglet_validation().
        if not est_validateur():
            ui.notification_show("Action réservée à la validation.", type="error")
            return
        sel = v_table.data_view(selected=True)
        if len(sel) == 0 or "Message" in sel.columns:
            ui.notification_show("Aucune pièce choisie.", type="warning")
            return
        d = donnees()
        # Une piece liee entraine sa jumelle : on controle et on valide la paire.
        ids = dl.avec_liees(list(sel.index), d)
        # Corrige le 11/09/2026, meme faille qu'attente() : un validateur
        # local ne peut valider que les pieces de son propre centre, jamais
        # celles d'un autre - v_table les filtre deja a l'ecran, mais ce
        # n'est pas un controle d'acces (voir _hors_centre()).
        if not est_comptable() and _hors_centre(ids, d, util()):
            ui.notification_show("Ces pieces appartiennent a un autre centre.", type="error")
            return
        ano = dl.controler(d[d["id_piece"].isin(ids)], ref(), d)
        bloquantes = ano[ano["gravite"] == "bloquante"]
        if len(bloquantes) > 0:
            items = [ui.tags.li(f"{row['piece']} : {row['anomalie']}") for _, row in bloquantes.iterrows()]
            ui.modal_show(ui.modal(
                ui.p("Ces pieces comportent des anomalies bloquantes :"),
                ui.tags.ul(*items),
                title="Validation impossible", easy_close=True))
            return
        try:
            res = dl.valider_pieces(ids, util()["identifiant"])
        except Exception as e:
            ui.notification_show(str(e), type="error")
        else:
            ui.notification_show(_message_validation(res),
                                  type="warning" if res["ignorees"] else "message",
                                  duration=None if res["ignorees"] else 5)
        rafraichir()

    @reactive.effect
    @reactive.event(input.v_rejeter)
    def _rejeter():
        # Meme filet de securite que _valider (voir son commentaire) :
        # v_rejeter est aussi un bouton reserve a la validation a l'ecran.
        if not est_validateur():
            ui.notification_show("Action réservée à la validation.", type="error")
            return
        sel = v_table.data_view(selected=True)
        if len(sel) == 0 or "Message" in sel.columns:
            ui.notification_show("Aucune pièce choisie.", type="warning")
            return
        motif = input.v_motif()
        if not motif or not str(motif).strip():
            ui.notification_show("Indiquer le motif du renvoi.", type="warning")
            return
        # avec_liees() AVANT le controle de centre (corrige le 15/09/2026).
        # _valider le faisait deja ; ici, la liste brute etait controlee puis
        # transmise a rejeter_pieces(), qui elargit aux pieces liees en
        # interne - donc APRES le controle. Un validateur local pouvait ainsi
        # selectionner une piece de son centre liee a une piece d'un autre
        # centre : _hors_centre ne voyait que la sienne et laissait passer,
        # puis la piece de l'autre centre repassait en 'a_corriger'. Le
        # cloisonnement corrige le 11/09 etait contourne par la porte de
        # service, et le test d'autorisation ne le voyait pas (il verifie que
        # _hors_centre est appelee, pas sur quoi).
        ids = dl.avec_liees(list(sel.index), donnees())
        if not est_comptable() and _hors_centre(ids, donnees(), util()):
            ui.notification_show("Ces pieces appartiennent a un autre centre.", type="error")
            return
        try:
            dl.rejeter_pieces(ids, motif, util()["identifiant"])
        except Exception as e:
            ui.notification_show(str(e), type="error")
            return
        ui.notification_show("Pieces renvoyees au centre", type="message")
        rafraichir()

    # ---------------- export --------------------------------------------------

    @reactive.calc
    def a_exporter():
        # Corrige le 11/09/2026 : meme faille qu'attente() - ne filtrait par
        # aucun centre. L'export vers Sage reste une action reservee au
        # comptable du siege (_marquer, inchange), mais un validateur local
        # ne doit meme pas voir dans cet onglet les pieces validees d'un
        # autre centre que le sien.
        u = req(util())
        d = donnees()
        if len(d) == 0:
            return d
        if not est_comptable():
            d = d[d["centre"] == u["centre"]]
        statuts = ["validee", "exportee"] if input.e_deja() else ["validee"]
        d = d[d["statut"].isin(statuts)]
        if input.e_journal() and input.e_journal() != "Tous":
            d = d[d["journal"] == input.e_journal()]
        periode = input.e_periode()
        if periode and periode[0] and periode[1]:
            dts = pd.to_datetime(d["date_piece"])
            d = d[(dts >= pd.Timestamp(periode[0])) & (dts <= pd.Timestamp(periode[1]))]
        return d

    @render.ui
    def e_resume():
        d = a_exporter()
        if len(d) == 0:
            return ui.div({"class": "ruban att"}, "Aucune pièce validée sur cette période.")
        return ui.div({"class": "ruban ok"},
                       f"{d['id_piece'].nunique()} piece(s), {len(d)} ligne(s), "
                       f"{dl.fcfa(d['debit'].sum())} F au debit. Le fichier suit l'ordre de colonnes "
                       "declare dans Sage.")

    @render.data_frame
    def e_table():
        d = a_exporter()
        x = dl.format_sage(d, ref())
        if x is None:
            return render.DataGrid(pd.DataFrame({"Message": ["Rien à exporter."]}), selection_mode="none")
        # L'index porte l'id_piece de chaque ligne affichee. Invisible a
        # l'ecran et sans effet sur les fichiers telecharges (to_csv/to_excel
        # sont appeles avec index=False sur le resultat brut de format_sage),
        # mais c'est ce qui permet a _marquer() de savoir EXACTEMENT quelles
        # pieces sont sous les yeux du comptable une fois la rangee de
        # filtres utilisee - voir son commentaire. format_sage ne fait que
        # trier et reprendre des colonnes de d : le resultat garde donc
        # l'index de d, qui est unique (_normaliser_lecture reindexe).
        x = x.set_axis(d.loc[x.index, "id_piece"].to_numpy(), axis=0)
        return render.DataGrid(x, selection_mode="none", width="100%", filters=True)

    @render.download_button(filename=lambda: f"sage_{date.today().strftime('%Y%m%d')}.txt", encoding="cp1252")
    def e_txt():
        x = dl.format_sage(a_exporter(), ref())
        if x is None:
            yield ""
            return
        texte = x.to_csv(sep=";", index=False, header=False, lineterminator="\n", na_rep="")
        # Corrige le 10/09/2026 : cp1252 (au lieu de latin1) couvre en plus
        # "oe", les guillemets typographiques et le tiret cadratin ; et on
        # encode nous-memes avec errors="replace" plutot que de laisser
        # @render.download_button faire chunk.encode(encoding) sans filet -
        # Shiny transmet un chunk deja en bytes tel quel, sans le reencoder,
        # donc un caractere malgre tout hors cp1252 devient "?" au lieu de
        # faire planter (UnicodeEncodeError) le telechargement de tout le lot
        # de pieces selectionne.
        yield texte.encode("cp1252", errors="replace")

    @render.download_button(
        filename=lambda: f"sage_{date.today().strftime('%Y%m%d')}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    def e_xlsx():
        x = dl.format_sage(a_exporter(), ref())
        if x is None:
            x = pd.DataFrame()
        buf = io.BytesIO()
        x.to_excel(buf, index=False, engine="openpyxl")
        yield buf.getvalue()

    # Pieces reellement visibles dans e_table apres utilisation de la rangee
    # de filtres du navigateur. Renvoie None si le tableau n'a pas encore
    # envoye sa vue (onglet jamais ouvert, grille en cours de rendu) : c'est
    # une information d'affichage, jamais une source de verite pour agir.
    def _pieces_affichees_export():
        try:
            vue = e_table.data_view()
        except Exception:
            return None
        if len(vue) == 0 or "Message" in getattr(vue, "columns", []):
            return None
        return list(dict.fromkeys(vue.index))

    @reactive.effect
    @reactive.event(input.e_marquer)
    def _marquer():
        # Meme filet de securite que _valider : l'export vers Sage est
        # reserve au comptable a l'ecran (onglet_export), a reverifier ici.
        if not est_comptable():
            ui.notification_show("Action réservée au comptable.", type="error")
            return
        d = a_exporter()
        if len(d) == 0:
            return
        # Corrige le 12/09/2026. La rangee de filtres ajoutee sur e_table est
        # entierement cote navigateur : elle ne touche ni a_exporter(), ni le
        # fichier telecharge, ni cet UPDATE. Un comptable qui filtrait la
        # colonne Journal sur "BQ", voyait trois lignes et cliquait ici
        # faisait donc passer a "exportee" TOUTES les pieces validees de la
        # periode - sans les avoir vues et sans qu'elles soient dans aucun
        # fichier. Le perimetre reste volontairement celui de a_exporter()
        # (sinon le fichier Sage et les statuts divergeraient), mais il n'est
        # plus applique en silence : on annonce le nombre exact, on signale
        # explicitement l'ecart avec ce qui est affiche, et on attend une
        # confirmation.
        ids = list(dict.fromkeys(d["id_piece"]))
        affichees = _pieces_affichees_export()
        avertissement = None
        if affichees is not None and len(affichees) < len(ids):
            avertissement = ui.div(
                {"class": "ruban att", "style": "margin-top:10px"},
                f"Un filtre est actif sur le tableau : il n'affiche que {len(affichees)} "
                f"piece(s) sur les {len(ids)} concernees. Le marquage porte sur la totalite "
                "de la periode, comme le fichier telecharge - jamais sur le seul filtre "
                "d'affichage.")
        ui.modal_show(ui.modal(
            ui.p(f"{len(ids)} piece(s) vont passer au statut « exportée » et sortir de la "
                 "file d'export."),
            ui.p({"style": "font-size:13px;color:var(--hk-texte-doux)"},
                 "À ne faire qu'une fois le fichier téléchargé et importé dans Sage."),
            avertissement,
            ui.input_action_button("e_marquer_confirmer", "Confirmer le marquage",
                                    icon=ui.tags.i({"class": "bi bi-check2-square"}),
                                    class_="hk-btn-primaire"),
            title="Marquer comme exportées", easy_close=True))

    @reactive.effect
    @reactive.event(input.e_marquer_confirmer)
    def _marquer_confirme():
        # Le bouton de confirmation vit dans une fenetre modale : meme filet
        # de securite que _marquer, rejoue ici.
        if not est_comptable():
            ui.notification_show("Action réservée au comptable.", type="error")
            return
        ui.modal_remove()
        d = a_exporter()
        if len(d) == 0:
            return
        ids = list(dict.fromkeys(d["id_piece"]))
        try:
            n = dl.marquer_exporte(ids)
        except Exception as e:
            ui.notification_show(str(e), type="error")
            return
        # marquer_exporte ne marque que les pieces 'validee' et renvoie le
        # nombre reel : on annonce ce chiffre, pas len(ids), et on signale
        # l'ecart plutot que de le passer sous silence.
        if n < len(ids):
            ui.notification_show(
                f"{n} piece(s) marquee(s) comme exportee(s) sur {len(ids)} : les autres "
                "n'etaient pas validees et restent en attente.", type="warning", duration=None)
        else:
            ui.notification_show(f"{n} piece(s) marquee(s) comme exportee(s)", type="message")
        rafraichir()

    # ---------------- controles et referentiel --------------------------------

    # Les anomalies suivent le meme perimetre que le brouillard : une caisse ne
    # voit que ses propres pieces. Montrer a Pissy un tiers manquant sur une
    # piece de Tampouy n'a aucun sens - elle ne peut rien y faire, et le bruit
    # finit par rendre l'onglet illisible, donc inutilise. Seul le comptable,
    # qui valide et exporte pour toute la maison, voit l'ensemble.
    #
    # Les soldes de caisse suivent la meme logique : un journal n'est affiche
    # que si le poste a des ecritures dedans.
    @reactive.calc
    def anomalies_vue():
        u = req(util())
        # inclure_banque=False pour un non-comptable : un solde de banque
        # negatif ne doit jamais lui etre signale, meme indirectement via une
        # anomalie de Controles - seul le comptable voit ce compte partage.
        return dl.anomalies(donnees(), ref(),
                            centre=None if est_comptable() else u["centre"],
                            inclure_banque=est_comptable())

    # Quand des pieces citent un tiers absent du referentiel, il n'y a rien a
    # ressaisir : le code est deja dans les ecritures, il suffit de recreer la
    # fiche. On le propose au comptable plutot que de le faire en douce, parce
    # que l'intitule reconstruit depuis le code merite d'etre relu.
    @render.ui
    def c_reparation():
        if not est_comptable():
            return None
        manquants = dl.tiers_manquants(donnees(), ref())
        if not manquants:
            return None
        return ui.div(
            {"class": "ruban", "style": "background:var(--hk-alerte-clair);border-left-color:var(--hk-alerte);"
                      "padding:14px 16px;margin-bottom:16px"},
            ui.tags.b(f"{len(manquants)} tiers cite par des pieces mais absent du referentiel."),
            ui.p({"style": "margin:8px 0"},
                 "Ces codes ont ete crees a la saisie puis perdus, en general parce que le "
                 "referentiel a ete remplace par une copie plus ancienne. Les recreer debloque "
                 "l'export ; l'intitule sera reconstruit depuis le code et reste modifiable "
                 "dans l'onglet Referentiel."),
            ui.p({"style": "margin:8px 0;font-size:12px;color:var(--hk-texte-doux)"}, ", ".join(manquants[:12])
                 + (" ..." if len(manquants) > 12 else "")),
            ui.input_action_button("c_reparer", "Recréer ces tiers",
                                    icon=ui.tags.i({"class": "bi bi-arrow-repeat"}),
                                    class_="hk-btn-primaire"),
        )

    @reactive.effect
    @reactive.event(input.c_reparer)
    def _reparer():
        # c_reparation() ne rend le bouton c_reparer que pour le comptable ;
        # meme filet de securite cote serveur que _valider.
        if not est_comptable():
            ui.notification_show("Action réservée au comptable.", type="error")
            return
        crees = dl.reparer_tiers_manquants(donnees(), ref())
        ui.notification_show(
            f"{len(crees)} tiers recree(s)" if crees else "Aucun tiers a recreer",
            type="message")
        rafraichir()

    # Retrouve l'id_piece reel derriere le numero affiche dans la colonne
    # "piece" des anomalies (num_definitif si la piece en a un, sinon son
    # numero provisoire) - c'est ce qui permet de selectionner une ligne
    # d'anomalie et d'agir sur la piece qu'elle designe.
    def _num_vers_id_piece(d):
        m = {}
        for _, row in d.drop_duplicates("id_piece").iterrows():
            for num in (row.get("num_definitif"), row.get("num_provisoire")):
                if num and num not in m:
                    m[num] = row["id_piece"]
        return m

    @render.data_frame
    def c_table():
        a = anomalies_vue()
        if len(a) == 0:
            a = pd.DataFrame([{"gravite": "", "piece": "",
                                "anomalie": "Aucune anomalie sur les pièces enregistrées."}])
            return render.DataGrid(_pour_grille(a), selection_mode="none", width="100%", filters=True)
        mapping = _num_vers_id_piece(donnees())
        grille = _pour_grille(a)
        grille.index = [mapping.get(p) for p in a["piece"]]
        return render.DataGrid(grille, selection_mode="row", width="100%", filters=True)

    # Reclassement direct depuis Controles : la comptable choisit une ligne
    # d'anomalie, voit la piece concernee (date, libelle, montant), et peut
    # lui attribuer le bon compte et le bon tiers sans repasser par une
    # nouvelle saisie complete. Se replie tout seul (rien affiche) tant
    # qu'aucune piece corrigeable n'est selectionnee - disclosure progressif,
    # pas un formulaire permanent qui alourdirait l'onglet.
    @render.ui
    def c_reclassement():
        sel = c_table.data_view(selected=True)
        if len(sel) == 0 or sel.index[0] is None:
            return None
        idp = sel.index[0]
        d = donnees()
        p = d[d["id_piece"] == idp]
        if len(p) == 0:
            return None
        statut = p["statut"].iloc[0]
        if statut not in ("saisie", "a_corriger"):
            return ui.div({"class": "ruban att"},
                           f"Piece {dl.ou(p['num_definitif'].iloc[0], p['num_provisoire'].iloc[0])} : "
                           "deja validee ou exportee, non modifiable ici.")
        r = ref()
        ligne_attente = p[p["compte"] == md.COMPTE_ATTENTE]
        montant = p["debit"].sum()
        comptes = r["comptes"][r["comptes"]["compte"] != md.COMPTE_ATTENTE]
        choix_comptes = {"": ""}
        for _, row in comptes.iterrows():
            choix_comptes[row["compte"]] = f"{row['compte']} - {row['intitule']}"
        return ui.div(
            {"class": "carte", "style": "margin-top:14px;background:var(--hk-fond)"},
            ui.h4("Attribuer le compte et le tiers"),
            ui.p({"style": "font-size:13px;color:var(--hk-texte-doux);margin:-6px 0 12px 0"},
                 f"{pd.to_datetime(p['date_piece'].iloc[0]).strftime('%d/%m/%Y')} - "
                 f"{p['journal'].iloc[0]} - {p['libelle'].iloc[0]} - {dl.fcfa(montant)} F"
                 + ("" if len(ligne_attente) else " (compte d'attente deja reclasse sur cette piece)")),
            ui.row(
                ui.column(6, ui.input_selectize(
                    "c_compte", "Compte comptable", choices=choix_comptes,
                    options={"placeholder": "Rechercher..."})),
                ui.column(6, ui.output_ui("c_tiers_wrap")),
            ),
            ui.input_action_button("c_attribuer", "Attribuer et remettre en file d'attente",
                                    icon=ui.tags.i({"class": "bi bi-check2"}),
                                    class_="hk-btn-primaire"),
        )

    # Le champ tiers ne s'affiche que si le compte choisi l'exige (meme
    # logique que le formulaire de Saisie) - jamais impose pour un compte de
    # charge qui n'en a pas besoin.
    @render.ui
    def c_tiers_wrap():
        compte = get_input("c_compte")
        if not compte:
            return None
        r = ref()
        ligne_compte = r["comptes"][r["comptes"]["compte"] == compte]
        if not len(ligne_compte) or ligne_compte.iloc[0]["tiers_obligatoire"] != "oui":
            return None
        pref = str(compte)[:3]
        sous = r["tiers"][r["tiers"]["code_tiers"].str.startswith(pref) & (r["tiers"]["actif_annee"] == "oui")]
        choix = {"": ""}
        for _, row in sous.iterrows():
            choix[row["code_tiers"]] = f"{row['intitule']}  ({row['code_tiers']})"
        return ui.input_selectize(
            "c_tiers", "Tiers", choices=choix,
            options={"create": True, "placeholder": "Rechercher..."})

    @reactive.effect
    @reactive.event(input.c_attribuer)
    def _attribuer():
        # PAS de garde de role ici, et c'est delibere : decision metier
        # confirmee le 10/09/2026 (voir l'en-tete de
        # tests/test_authorisation.py). L'onglet Controles est accessible aux
        # caissieres, et le compte d'attente 471000 sert justement aux
        # encaissements qu'on n'a pas su classer sur le moment - c'est la
        # caissiere qui sait a quoi l'argent correspondait. Exiger un
        # validateur l'obligerait a rappeler le comptable pour chaque cas.
        #
        # En revanche le CENTRE est controle (ajoute le 15/09/2026) : c_table
        # ne montre que les anomalies du centre connecte, mais masquer une
        # ligne cote client n'est pas un controle d'acces - meme raisonnement
        # que _valider, _rejeter et _supprimer. Reclasser reste donc libre
        # dans son propre centre, et impossible dans celui d'un autre.
        u = util()
        if u is None:
            return
        sel = c_table.data_view(selected=True)
        if len(sel) == 0 or sel.index[0] is None:
            return
        idp = sel.index[0]
        if not est_comptable() and _hors_centre([idp], donnees(), u):
            ui.notification_show("Cette piece appartient a un autre centre.", type="error")
            return
        compte = get_input("c_compte")
        if not compte:
            ui.notification_show("Choisir un compte.", type="warning")
            return
        r = ref()
        tiers_brut = get_input("c_tiers", "")
        ligne_compte = r["comptes"][r["comptes"]["compte"] == compte]
        code_tiers = ""
        if len(ligne_compte) and ligne_compte.iloc[0]["tiers_obligatoire"] == "oui":
            if not tiers_brut:
                ui.notification_show("Ce compte exige un tiers.", type="warning")
                return
            try:
                code_tiers = dl.resoudre_tiers(tiers_brut, str(compte)[:3], compte)
            except Exception as e:
                ui.notification_show(f"Impossible de resoudre le tiers : {e}", type="error")
                return
        try:
            dl.reclasser_piece(idp, md.COMPTE_ATTENTE, compte, code_tiers, util()["identifiant"])
        except Exception as e:
            ui.notification_show(str(e), type="error")
            return
        ui.notification_show(
            "Compte attribue - la piece repasse en file d'attente normale (onglet Validation).",
            type="message")
        ui.update_selectize("c_compte", selected="")
        rafraichir()

    # Lien "Afficher tout (N) / Reduire" : n'existe que si la liste depasse
    # LIGNES_APERCU lignes, pour ne jamais surcharger un referentiel qui
    # tient deja sur un seul ecran.
    def _lien_toggle(id_bouton, etendu, total):
        if total <= LIGNES_APERCU:
            return None
        libelle = "Reduire" if etendu else f"Afficher tout ({total})"
        return ui.input_action_link(id_bouton, libelle, class_="lien-etendre")

    # Hauteur de la grille selon l'etat du repliement. None = hauteur
    # naturelle (toutes les lignes visibles sans ascenseur interne). La
    # grille recoit TOUJOURS la liste complete : voir HAUTEUR_APERCU.
    def _hauteur(etendu, total):
        if etendu or total <= LIGNES_APERCU:
            return None
        return HAUTEUR_APERCU

    @render.data_frame
    def r_comptes():
        d = _pour_grille(ref()["comptes"])
        return render.DataGrid(d, selection_mode="none", width="100%", filters=True,
                                height=_hauteur(etendu_comptes(), len(d)))

    @render.ui
    def lien_comptes():
        return _lien_toggle("toggle_etendu_comptes", etendu_comptes(), len(ref()["comptes"]))

    @reactive.effect
    @reactive.event(input.toggle_etendu_comptes)
    def _toggle_etendu_comptes():
        etendu_comptes.set(not etendu_comptes())

    @render.data_frame
    def r_tiers():
        d = _pour_grille(ref()["tiers"])
        return render.DataGrid(d, selection_mode="none", width="100%", filters=True,
                                height=_hauteur(etendu_tiers(), len(d)))

    @render.ui
    def lien_tiers():
        return _lien_toggle("toggle_etendu_tiers", etendu_tiers(), len(ref()["tiers"]))

    @reactive.effect
    @reactive.event(input.toggle_etendu_tiers)
    def _toggle_etendu_tiers():
        etendu_tiers.set(not etendu_tiers())

    @render.data_frame
    def r_utilisateurs():
        u_aff = _pour_grille(ref()["utilisateurs"][["identifiant", "nom", "role", "centre", "actif"]])
        return render.DataGrid(u_aff, selection_mode="row", width="100%", filters=True,
                                height=_hauteur(etendu_utilisateurs(), len(u_aff)))

    @render.ui
    def lien_utilisateurs():
        return _lien_toggle("toggle_etendu_utilisateurs", etendu_utilisateurs(),
                             len(ref()["utilisateurs"]))

    @reactive.effect
    @reactive.event(input.toggle_etendu_utilisateurs)
    def _toggle_etendu_utilisateurs():
        etendu_utilisateurs.set(not etendu_utilisateurs())

    @reactive.effect
    @reactive.event(input.r_ajouter_utilisateur)
    def _ajouter_utilisateur():
        # Le panneau de creation d'utilisateur n'est rendu qu'au comptable
        # (onglet_referentiel) ; meme filet de securite cote serveur que
        # _valider - sans lui, n'importe quel compte "saisie" pourrait se
        # creer un acces "validation" sur n'importe quel centre.
        if not est_comptable():
            ui.notification_show("Action réservée au comptable.", type="error")
            return
        # Un clic sur un formulaire deja vide (par exemple un deuxieme clic
        # apres une creation reussie, le formulaire n'ayant pas encore ete
        # retape) ne doit produire aucun message : ce n'est pas une erreur de
        # l'utilisateur, juste un clic qui n'a plus rien a faire.
        if not str(input.r_id_utilisateur() or "").strip():
            return
        # Desactive le bouton des le premier clic : un double-clic (souris ou
        # geste involontaire) ne doit jamais declencher une deuxieme tentative
        # de creation avant que la premiere ait fini d'ecrire le fichier.
        ui.update_action_button("r_ajouter_utilisateur", disabled=True)
        try:
            dl.ajouter_utilisateur(
                input.r_id_utilisateur(), input.r_nom_utilisateur(), input.r_role_utilisateur(),
                input.r_centre_utilisateur(), input.r_code_utilisateur())
        except Exception as e:
            ui.notification_show(str(e), type="error")
        else:
            ui.notification_show("Utilisateur créé", type="message")
            panneau_ouvert.set(None)
            rafraichir()
        finally:
            ui.update_action_button("r_ajouter_utilisateur", disabled=False)

    @reactive.effect
    @reactive.event(input.r_desactiver_utilisateur)
    def _desactiver_utilisateur():
        # Meme filet de securite que _ajouter_utilisateur.
        if not est_comptable():
            ui.notification_show("Action réservée au comptable.", type="error")
            return
        sel = r_utilisateurs.data_view(selected=True)
        if len(sel) == 0:
            ui.notification_show("Choisir d'abord un utilisateur.", type="warning")
            return
        if util() is not None and sel["identifiant"].iloc[0] == util().get("identifiant"):
            ui.notification_show("Impossible de desactiver le compte actuellement connecte.", type="error")
            return
        try:
            dl.desactiver_utilisateur(sel["identifiant"].iloc[0])
        except Exception as e:
            ui.notification_show(str(e), type="error")
        else:
            ui.notification_show("Utilisateur desactive", type="message")
            rafraichir()

    @reactive.effect
    @reactive.event(input.r_ajouter)
    def _ajouter_tiers():
        # Le panneau "Comptes de tiers" n'est rendu qu'au comptable ; meme
        # filet de securite cote serveur que _valider.
        if not est_comptable():
            ui.notification_show("Action réservée au comptable.", type="error")
            return
        if not str(input.r_code() or "").strip():
            return
        ui.update_action_button("r_ajouter", disabled=True)
        try:
            dl.ajouter_tiers(str(input.r_code() or "").strip().upper(),
                              str(input.r_nom() or "").strip().upper(),
                              input.r_collectif())
        except Exception as e:
            ui.notification_show(str(e), type="error")
        else:
            ui.notification_show("Tiers créé", type="message")
            panneau_ouvert.set(None)
            rafraichir()
        finally:
            ui.update_action_button("r_ajouter", disabled=False)

    @reactive.effect
    @reactive.event(input.r_ajouter_compte)
    def _ajouter_compte():
        # Le panneau "Plan de comptes" n'est rendu qu'au comptable ; meme
        # filet de securite cote serveur que _valider.
        if not est_comptable():
            ui.notification_show("Action réservée au comptable.", type="error")
            return
        if not str(input.r_num_compte() or "").strip():
            return
        ui.update_action_button("r_ajouter_compte", disabled=True)
        try:
            dl.ajouter_compte(str(input.r_num_compte() or "").strip(),
                               str(input.r_intitule_compte() or "").strip(),
                               input.r_nature_compte(),
                               tiers_obligatoire="oui" if input.r_tiers_obligatoire() else "non",
                               depense_courante="oui" if input.r_compte_courante() else "non")
        except Exception as e:
            ui.notification_show(str(e), type="error")
        else:
            ui.notification_show("Compte créé", type="message")
            panneau_ouvert.set(None)
            rafraichir()
        finally:
            ui.update_action_button("r_ajouter_compte", disabled=False)

    @reactive.effect
    @reactive.event(input.r_soldes)
    def _soldes():
        # Le panneau "Soldes d'ouverture" n'est rendu qu'au comptable ; meme
        # filet de securite cote serveur que _valider.
        if not est_comptable():
            ui.notification_show("Action réservée au comptable.", type="error")
            return
        r = ref()
        jx = r["journaux"]
        centres_actifs = r["centres"]
        if "actif" in centres_actifs.columns:
            centres_actifs = centres_actifs[centres_actifs["actif"].fillna("oui") == "oui"]
        echecs = []
        for j in jx["journal"]:
            physique = "caisse_physique" in jx.columns and \
                (jx.loc[jx["journal"] == j, "caisse_physique"] == "oui").iloc[0]
            if physique:
                for _, c in centres_actifs.iterrows():
                    code = c["code_centre"]
                    v = get_input(_id_solde_centre(code, j))
                    if v is not None:
                        try:
                            dl.maj_solde_ouverture_centre(code, j, v)
                        except Exception as e:
                            dl.logger.error(
                                "Echec de mise a jour du solde d'ouverture (centre %s, journal %s) : %s",
                                code, j, e)
                            echecs.append(f"{j}/{code}")
            else:
                v = get_input(_id_journal(j))
                if v is not None:
                    try:
                        dl.maj_solde_ouverture(j, v)
                    except Exception as e:
                        dl.logger.error("Echec de mise a jour du solde d'ouverture (journal %s) : %s", j, e)
                        echecs.append(j)
        # Corrige le 10/09/2026 : l'echec etait avale (`except Exception:
        # pass`) et "Soldes d'ouverture enregistres" s'affichait quand meme,
        # meme si aucun solde n'avait ete ecrit - le comptable croyait avoir
        # corrige un solde reste faux, avec un effet direct sur les controles
        # de solde de caisse (controler_soldes) qui en dependent. Desormais
        # un echec est nomme et ne peut plus etre confondu avec un succes.
        if echecs:
            ui.notification_show(
                "Echec sur : " + ", ".join(echecs) + ". Les autres soldes ont ete "
                "enregistres ; corrigez et reessayez pour ceux en echec.", type="error")
        else:
            ui.notification_show("Soldes d'ouverture enregistrés", type="message")
        panneau_ouvert.set(None)
        rafraichir()

    @reactive.effect
    @reactive.event(input.r_nouvelle_annee)
    def _nouvelle_annee():
        # Le panneau "Nouvelle annee academique" n'est rendu qu'au
        # comptable ; meme filet de securite cote serveur que _valider.
        if not est_comptable():
            ui.notification_show("Action réservée au comptable.", type="error")
            return
        n = dl.nouvelle_annee_academique()
        panneau_ouvert.set(None)
        ui.notification_show(
            f"Nouvelle annee academique demarree : {n} tiers retires des listes de saisie "
            "(rien n'est supprime, l'historique reste intact).", type="message")

    # ---------------- assistant IA --------------------------------------------
    #
    # Pas de zone_chat()/chat.ui() ici : en Shiny Core (par opposition a
    # Shiny Express), la methode .ui() de ui.Chat() n'existe plus depuis la
    # 1.3 - l'affichage se fait directement via ui.chat_ui(...) place dans
    # le layout (voir onglet_assistant ci-dessus). L'objet `chat` cree plus
    # haut ne sert plus qu'a la logique serveur (.on_user_submit,
    # .append_message, .append_message_stream, .user_input()).

    # Se connecte au serveur MCP maison (mcp_server/server.py) une seule fois
    # par session, seulement si l'onglet est accessible a cet utilisateur -
    # inutile d'ouvrir un sous-processus MCP pour une caissiere qui ne verra
    # jamais cet onglet.
    @reactive.effect
    async def _connecter_mcp():
        if not peut_voir_assistant():
            return
        # Lecture ISOLEE de mcp_connecte (corrige le 15/09/2026). Avant, cet
        # effet DEPENDAIT de mcp_connecte, et la branche d'erreur le remettait
        # a False "pour rouvrir la porte" - ce qui invalidait sa propre
        # dependance et le relancait. Il echouait de nouveau, remettait False,
        # repartait : boucle infinie. Observe le 15/09, quand le paquet
        # anthropic manquait dans l'image : un bandeau rouge par tour, et
        # surtout un sous-processus MCP lance a chaque tentative, aucun jamais
        # arrete. Le serveur accumulait processus et connexions Postgres tant
        # que l'onglet restait ouvert.
        #
        # Isoler la lecture supprime la dependance : le .set() ci-dessous ne
        # peut plus declencher quoi que ce soit. Le verrou est pose AVANT
        # l'await, pour qu'une seconde execution pendant la connexion sorte
        # immediatement.
        with reactive.isolate():
            if mcp_connecte():
                return
            mcp_connecte.set(True)
        try:
            # Portee de la session, transmise au sous-processus MCP (voir
            # mcp_server/portee.py). Un sous-processus par session Shiny :
            # l'isolation est donc bien par utilisateur connecte, pas par
            # serveur. Vide = aucune restriction, ce qui est le cas du
            # comptable du siege - seul a voir l'onglet aujourd'hui, d'ou un
            # comportement strictement inchange. Le jour ou l'assistant
            # s'ouvrira aux directeurs de centre (voir peut_voir_assistant),
            # le cloisonnement s'appliquera sans autre modification.
            u = util()
            environnement = dict(os.environ)
            environnement["HAKILI_PORTEE_CENTRE"] = (
                "" if est_comptable() or u is None else str(u.get("centre") or ""))
            await chat_client().register_mcp_tools_stdio_async(
                command=sys.executable,
                args=["-m", "mcp_server.server"],
                transport_kwargs={"env": environnement},
            )
        except Exception as e:
            # Echec typiquement du au sous-processus mcp_server (module
            # absent de l'image de deploiement, ANTHROPIC_API_KEY manquante,
            # DATABASE_URL non lue par ce sous-processus...) : journalise
            # pour le diagnostic, et signale a l'utilisateur au lieu de
            # laisser planter silencieusement l'onglet Assistant.
            # On ne remet PAS mcp_connecte a False : une seule tentative par
            # session (voir le commentaire de la boucle plus haut). L'onglet
            # reste utilisable, l'assistant seul est indisponible.
            dl.logger.error("Echec de connexion au serveur MCP : %s", e)
            # Le message distingue une dependance absente d'une vraie panne
            # reseau. Le 15/09, "connexion au serveur d'analyse impossible"
            # s'affichait alors que le paquet anthropic manquait simplement
            # dans l'image : impossible de deviner sans lire le journal.
            if isinstance(e, ImportError) or "install" in str(e).lower():
                message = ("Assistant IA indisponible : une dépendance manque dans "
                           "l'installation du serveur. Prévenir l'administrateur "
                           "(le détail est dans le journal de l'application).")
            else:
                message = ("Assistant IA indisponible pour le moment "
                           "(connexion au serveur d'analyse impossible).")
            ui.notification_show(message, type="error")

    # Le sous-processus MCP lancé par _connecter_mcp n'était jamais arrêté
    # (15/09/2026) : chaque connexion du comptable laissait derrière elle un
    # processus Python vivant, avec son propre pool de connexions Postgres.
    # Sur une journée, autant de processus et de pools que de connexions
    # successives - le serveur atteignait max_connections avant de manquer de
    # mémoire.
    @session.on_ended
    async def _fermer_mcp():
        with reactive.isolate():
            client = chat_client_val()
        if client is None:
            return
        try:
            await client.cleanup_mcp_tools()
        except Exception as e:
            dl.logger.warning("Fermeture du serveur MCP en fin de session : %s", e)

    # ContentToolResult.name est une propriete calculee qui LEVE une
    # ValueError tant que le resultat n'est pas rattache a sa requete d'outil
    # (chatlas/_content.py). Un getattr(..., defaut) ne rattrape que les
    # AttributeError : il faut donc un try/except explicite, sous peine de
    # faire planter tout le flux de reponse pour un nom d'outil manquant.
    def _nom_outil(contenu):
        try:
            return contenu.name
        except Exception:
            return None

    def _markdown_graphique(resultats):
        """Construit l'image a partir du resultat BRUT (deja calcule par
        logic.analyse) du premier outil MCP graphable de l'echange, et
        renvoie le markdown qui la reference - jamais a partir du texte que
        Claude vient de generer.

        Un seul graphique par reponse au maximum (le premier outil
        "graphable" trouve) : le but est d'illustrer la reponse, pas de la
        noyer sous plusieurs images.

        Corrige le 12/09/2026 : un data-URI base64 dans le markdown du chat
        ne s'affichait jamais, meme quand l'image etait correctement generee
        - le composant chat de Shiny sanitize le HTML issu du markdown et
        n'autorise que les schemas http/https pour un <img src=...>, jamais
        "data:". On ecrit donc le PNG comme un vrai fichier statique sous
        www/graphiques/ (deja servi via static_assets, voir la fin de ce
        fichier) et on reference son URL relative, qui passe la
        sanitization sans probleme."""
        if not resultats:
            dl.logger.info("[diag graphique] Aucun resultat d'outil dans ce tour")
            return None
        for contenu in resultats:
            nom_outil = _nom_outil(contenu)
            if not nom_outil:
                continue
            # contenu.value est une CHAINE (JSON) et non un dict des lors que
            # l'outil vient d'un serveur MCP : le decodage est fait par
            # logic.graphiques.valeur_outil, appele par graphique_pour_outil.
            image_b64 = gr.graphique_pour_outil(nom_outil, contenu.value)
            if not image_b64:
                dl.logger.info("[diag graphique] Outil %s : pas de graphique associe "
                               "ou valeur non tracable", nom_outil)
                continue
            dossier = Path(__file__).parent / "www" / "graphiques"
            dossier.mkdir(parents=True, exist_ok=True)
            nom_fichier = f"{uuid.uuid4().hex}.png"
            (dossier / nom_fichier).write_bytes(base64.b64decode(image_b64))
            dl.logger.info("[diag graphique] Graphique pour %s : OK (%s)", nom_outil, nom_fichier)
            return f"\n\n![graphique](graphiques/{nom_fichier})"
        return None

    def _flux_avec_graphique(source):
        """Enveloppe le flux de chatlas et y ajoute le graphique, une fois le
        flux epuise.

        Corrige le 12/09/2026. Le graphique etait construit APRES
        `await chat.append_message_stream(stream)`, en relisant l'historique
        via `get_last_turn(role="user")`. Or append_message_stream ne bloque
        pas : elle lance la consommation du flux dans une reactive.extended_task
        et rend la main aussitot (voir shinychat/_chat.py, "Run the stream in
        the background to get non-blocking behavior"). Le graphique etait donc
        lu AVANT que chatlas ait appele l'outil MCP et empile le tour
        contenant son resultat - les journaux le montraient noir sur blanc,
        le diagnostic tombant une seconde avant le premier appel a l'API.
        Consequence : aucun graphique sur la premiere question, puis celui de
        la question PRECEDENTE colle sous chaque reponse suivante.

        On ne depend plus du tout de l'historique des tours : avec
        content="all", chatlas fait deja transiter les ContentToolResult dans
        le flux lui-meme. On les capture au passage, et on n'emet l'image
        qu'une fois le flux reellement termine - donc forcement apres l'appel
        d'outil, sans aucune course possible."""
        async def _flux():
            resultats = []
            async for morceau in source:
                if isinstance(morceau, ContentToolResult):
                    if getattr(morceau, "error", None) is None:
                        resultats.append(morceau)
                    else:
                        # l'outil a echoue : rien de fiable a tracer
                        dl.logger.info("[diag graphique] Outil %s en echec, ignore",
                                       _nom_outil(morceau) or "?")
                yield morceau
            markdown = _markdown_graphique(resultats)
            if markdown:
                yield markdown
        return _flux()

    @chat.on_user_submit
    async def _repondre():
        # chat.user_input() renvoie un objet avec un champ .text, jamais une
        # chaine brute directement - chatlas plante sinon en essayant
        # d'iterer sur l'objet complet.
        message = chat.user_input()
        texte = message.text if message is not None else ""
        stream = await chat_client().stream_async(texte, content="all")
        await chat.append_message_stream(_flux_avec_graphique(stream))

    @reactive.effect
    @reactive.event(input.categorie_suggestion)
    def _maj_suggestions():
        categorie = input.categorie_suggestion()
        nouveaux_choix = qa.QUESTIONS_PAR_CATEGORIE.get(categorie, [AUCUNE_SUGGESTION])
        ui.update_select("question_suggeree", choices=nouveaux_choix)

    @reactive.effect
    @reactive.event(input.envoyer_suggestion)
    async def _envoyer_suggestion():
        question = input.question_suggeree()
        if not question or question == AUCUNE_SUGGESTION:
            return
        try:
            await chat.append_message({"role": "user", "content": question})
            stream = await chat_client().stream_async(question, content="all")
            await chat.append_message_stream(_flux_avec_graphique(stream))
        except Exception as e:
            await chat.append_message(f"Erreur : {e}")


# "www" contient le logo/favicon ; static_assets exige un chemin absolu,
# jamais mis en correspondance automatiquement par Shiny.
app = App(app_ui, server, static_assets={"/": Path(__file__).resolve().parent / "www"})
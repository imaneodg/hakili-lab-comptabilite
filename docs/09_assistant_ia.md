# 9. L'assistant IA

Dossier `assistant/`, onglet « Assistant IA » (réservé au comptable). Reconstruit entièrement le 24/09/2026, réorienté vers le directeur le 25/09.

## 9.1 Le principe : le modèle ne calcule rien

Les nombres viennent toujours de fonctions Python ou SQL déterministes. Le modèle de langage (Claude, par l'API Anthropic) fait trois choses seulement : comprendre la question, choisir l'outil et ses paramètres, puis formuler la réponse avec le résultat. C'est ce qui rend les réponses vérifiables : la même question donne le même chiffre que le tableau de bord ou qu'une requête SQL.

```
question ──► session.py ──► modèle Claude ──► outil choisi (outils.py)
                                                  │
                                    comprehension.py : « saab », « fevirer » → SAA, 2026-02
                                                  │
                                    moteur.py + semantique.py (+ flux_tableau_bord)
                                                  │
                         résultat chiffré ──► modèle ──► réponse courte
                                         └──► carte sous la réponse (tableau, graphique)
```

## 9.2 Les outils

| Outil | Ce qu'il fait |
|---|---|
| `contexte` | date du jour, période couverte par les données, centres |
| `point_financier` | la situation en un coup d'œil (argent disponible, reçu et dépensé du mois, comparaison, point à vérifier) |
| `soldes` | caisses par centre et banque à une date |
| `analyser` | un ou plusieurs indicateurs sur une période, regroupés par centre, mois, type… |
| `comparer` | deux périodes, avec l'écart |
| `lister_ecritures` | derniers mouvements |
| `chercher` | recherche approximative d'un élève, fournisseur, enseignant ou catégorie |
| `controles` | doublons, compte d'attente, transferts, etc. |
| `a_verifier` | tous les points à vérifier en une liste |
| `personnel` | vacations et salaires par personne, avances |
| `graphique` | graphique tracé à partir d'un résultat déjà calculé (jamais de chiffres fournis par le modèle) |
| `requete_sql` | dernier recours : une requête `SELECT` en lecture seule, sous le rôle `hakili_lecture`, limitée à 10 s et 300 lignes |

Une valeur mal comprise (centre ambigu, période illisible) n'est pas une erreur : l'outil renvoie les candidats et le modèle pose la question.

**Mêmes chiffres que le tableau de bord** (décision du 08/10/2026) : pour « bénéfice, résultat, marge, charges », l'assistant utilise les indicateurs `resultat_tableau`, `charges_exploitation`, `encaissements_exploitation`, `marge_tableau_pct`, `hors_exploitation`, calculés par `flux_tableau_bord`. Les indicateurs « rattachés au mois du cours » existent encore mais ne servent que si on les demande explicitement.

## 9.3 Les consignes au modèle

`assistant/prompt.py`, reconstruit à chaque question (la date change). Points principaux : répondre au directeur, qui n'est pas comptable ; le chiffre d'abord, en une ou deux phrases, avec un repère ; jamais de numéro de compte ni de code de centre ; vocabulaire simple (« argent reçu » plutôt qu'« encaissements », « bénéfice » plutôt que « résultat ») ; pas de formules de politesse ni d'emoji. Lisez-le avant de modifier quoi que ce soit : chaque phrase corrige un défaut observé.

## 9.4 Sécurité et coûts

- **Portée** : le comptable voit tous les centres. Le code prévoit une portée limitée à un centre pour un futur utilisateur non comptable.
- **Requête SQL libre** : exécutée sous le rôle PostgreSQL `hakili_lecture` (lecture de `v_lignes`, `centres`, `comptes`, `tiers`, `journaux`, `categories_charge`, `centres_alias`, `soldes_ouverture_centre` seulement), en transaction lecture seule, avec un filtre supplémentaire contre `query_to_xml` et consorts. Si le rôle n'a pas pu être créé, l'outil refuse de s'exécuter.
- **Historique** : 8 échanges gardés par conversation (`HAKILI_IA_HISTORIQUE`), pour un coût stable.
- **Réponse** : 2 000 jetons au plus (`HAKILI_IA_MAX_TOKENS`).
- **Traçabilité** : chaque question est enregistrée dans `journal_assistant` (utilisateur, question, outils, réponse, durée, jetons, erreur).

## 9.5 Configuration

Dans `.env` :

| Variable | Obligatoire | Rôle |
|---|---|---|
| `ANTHROPIC_API_KEY` | oui | clé de l'API Anthropic (compte à préciser par Afiya, voir chapitre 0) |
| `HAKILI_MODELE_IA` | non | nom du modèle (défaut dans `assistant/config.py`). Si l'assistant répond « Le modèle d'IA configuré est introuvable », c'est ce nom qu'il faut mettre à jour avec un modèle actuel de la documentation Anthropic |
| `HAKILI_IA_MAX_TOKENS`, `HAKILI_IA_HISTORIQUE` | non | voir ci-dessus |
| `HAKILI_ASSISTANT_DATABASE_URL` | non | connexion dédiée en lecture seule ; sinon la connexion de l'application, en transaction READ ONLY |

Les pannes de l'API (clé refusée, surcharge, réseau) sont traduites en phrases lisibles dans `session.py::message_erreur`.

## 9.6 Tester l'assistant

- Tests sans appel au modèle : `tests/test_assistant_ia.py`, `tests/test_assistant_hakili.py`.
- Avec le vrai modèle et la vraie base (coûte quelques centimes) : `python -m outils.evaluer_assistant`, ou avec une question précise : `python -m outils.evaluer_assistant "combien saab a encaisse en fevirer"`. À lancer après toute modification de `prompt.py` ou des outils.

## 9.7 Compléter sans toucher au code

- Une nouvelle façon d'écrire un centre : `INSERT INTO centres_alias (alias, code_centre) VALUES ('tampy', 'TAM');`
- Une nouvelle catégorie de dépense, ou un mot-clé : table `categories_charge`.

Faites-le par une migration, pour que la production et votre base locale restent identiques.

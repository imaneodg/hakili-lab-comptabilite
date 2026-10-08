# 12. Développer sur votre poste

## 12.1 Installer

Prérequis : Python 3.14 (3.12+ fonctionne en principe, la production est en 3.14), PostgreSQL 16 (avec pgAdmin sous Windows), Git, un éditeur (VS Code).

```bash
git clone https://github.com/imaneodg/hakili-lab-comptabilite.git
cd hakili-lab-comptabilite
git checkout tableau-bord-v2         # voir 12.5 : c'est la branche la plus récente
python -m venv .venv
# Windows : .\.venv\Scripts\Activate.ps1      Linux/macOS : source .venv/bin/activate
pip install -r requirements.txt
```

Dans pgAdmin (ou `psql`), créez trois bases **vides, encodage UTF8** :

| Base | Usage |
|---|---|
| `hakilisso` (ou le nom de votre choix) | votre base de travail |
| `hakili_test` | effacée et recréée par `verifier.py` à chaque lancement |
| `hakili_verif` | base de vérification de `verifier_donnees.py` (facultative) |

Sous Windows, forcez **Encoding: UTF8** à la création : la valeur proposée par défaut (WIN1252) provoque des erreurs d'encodage.

Initialisez votre base de travail :

```bash
psql -d hakilisso -f sql/schema.sql
psql -d hakilisso -f sql/seed.sql
```

Les migrations se joueront au premier lancement.

Copiez `.env.example` en `.env` et remplissez au minimum :

```
DATABASE_URL=postgresql://utilisateur:motdepasse@localhost:5432/hakilisso
ANTHROPIC_API_KEY=sk-ant-...      # seulement pour l'onglet Assistant IA
```

## 12.2 Lancer

```bash
shiny run --reload app.py
```

Puis ouvrez `http://127.0.0.1:8000`. Connectez-vous avec le centre **Siège**, l'identifiant **`comptable`** et le code initial défini dans `sql/seed.sql` ; changez-le aussitôt dans Référentiel > Mon code d'accès. Créez ensuite une caissière pour un centre (Référentiel > Utilisateurs) et saisissez des opérations sous ce compte pour voir les deux points de vue.

Pensez à saisir des soldes d'ouverture (Référentiel > Paramètres), sinon les caisses passent vite en négatif.

**Avoir des données réalistes** : `python import_historique.py --dry-run` puis `python import_historique.py` importe les brouillards 2026 de Tampouy et Saaba (fichiers Excel locaux, non versionnés, à demander à Afiya) dans la base de `DATABASE_URL`. **Uniquement sur une base locale.** C'est ainsi qu'a été construite la base de démonstration du tableau de bord.

Le serveur MCP facultatif : `python -m mcp_server.server`.

On peut aussi lancer l'ensemble avec Docker comme en production : créer d'abord le volume (`docker volume create hakili_gestion_caisse_pgdata`), mettre `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` dans `.env`, puis `docker compose up -d --build` et ouvrir `http://127.0.0.1:8022`.

## 12.3 Les tests

Environ 300 tests pytest, qui tournent **contre une vraie base PostgreSQL**. Les pièces de test sont datées de 2098-2099 pour ne jamais se mélanger à de vraies données, et `conftest.py` fixe pour elles la date du jour au 01/01/2100.

La façon sûre de tout lancer :

```bash
python verifier.py
```

Ce script recrée `hakili_test` depuis `schema.sql` + `seed.sql`, joue les migrations et lance pytest dessus. Il ne touche jamais votre base de travail ni la production. Au 08/10/2026 : **299 tests, tous réussis.**

Pour un seul fichier : `python -m pytest tests/test_modeles.py -v` (attention, il utilise alors le `DATABASE_URL` de votre `.env`).

| Fichier de test | Ce qu'il protège |
|---|---|
| `test_modeles.py` | construction des écritures |
| `test_libelles_multi_mois.py` | libellés des encaissements multi-mois, coupe à 60 caractères |
| `test_reglement_fournisseur.py` | répartition par mois des règlements fournisseurs |
| `test_transferts_internes.py` | transferts entre centres, rapprochement, motif |
| `test_soldes_centre.py` | soldes par centre et banque |
| `test_numerotation_date_centre.py` | ordre et continuité des numéros définitifs |
| `test_isolation_centres.py`, `test_authorisation.py`, `test_autorisation_exhaustive.py` | cloisonnement des centres et droits côté serveur |
| `test_auth.py` | codes d'accès, verrouillage |
| `test_reactivite_saisie.py` | que le formulaire ne se reconstruit pas pendant la saisie |
| `test_analyse.py` | fonctions d'analyse |
| `test_assistant_ia.py`, `test_assistant_hakili.py` | outils et compréhension de l'assistant (sans appel au modèle) |
| `test_tableau_bord.py`, `test_camp_cibles_forces.py` | calculs du tableau de bord |
| `test_correctifs_audit_2026_10_08.py` | export Sage (marquage, libellés), clôtures, protection, dates, codes, 17 caractères… |
| `test_utils.py` | petites fonctions |
| `test_ocr_client.py` | vide (OCR abandonné) |

Règle de travail : **tout correctif vient avec un test** qui échoue avant et passe après. C'est ce qui a permis de modifier un code de cette taille sans régression.

## 12.4 Conventions de code

- Code, commentaires, messages et commits **en français**. Les commentaires expliquent **pourquoi**, souvent avec la date et l'audit d'origine (« corrigé le 22/09/2026, M3 de l'audit du 18/09 »). Gardez cette habitude : c'est ce qui rend le code compréhensible des mois plus tard.
- Pas d'accents dans les identifiants Python ni dans les commentaires de code (héritage) ; accents dans tout ce que voit l'utilisateur.
- Jamais un code de centre à l'écran : toujours `dl.nom_centre(ref, code)`.
- Montants : `dl.fcfa()` (espace comme séparateur de milliers, pas de décimale).
- Requêtes SQL toujours paramétrées.
- Un changement de présentation ne touche ni la logique métier, ni les `id` des champs, ni les appels serveur.
- Garder le code simple : pas d'abstraction tant qu'un seul endroit en a besoin.

## 12.5 Git : l'état des branches au 08/10/2026

| Branche | Contenu |
|---|---|
| `main` (local et GitHub) | jusqu'au commit `a7236c9` (25/09 : règlement fournisseur réparti par mois, validation en lot). C'est ce que la production suit |
| `tableau-bord-v2` (local et GitHub, identiques) | `main` + 6 commits du tableau de bord, du camp de vacances et du motif des transferts (dernier : `4948fc5`, 07/10) |
| copie de travail d'Afiya | `tableau-bord-v2` + **les correctifs de l'audit du 07/10, non commités** (20 fichiers, dont 2 migrations, 2 scripts de sauvegarde, `outils/definir_code.py`, un fichier de test) |
| `sauvegarde-tableau-bord-v1`, `origin/sauvegarde-ancienne-version` | archives, ne pas utiliser |

Le chapitre 13 décrit comment remettre tout cela d'aplomb.

## 12.6 Le dépôt est public

Au moment de la rédaction, le dépôt GitHub est **public**. Aucune donnée personnelle ni aucun secret n'y est (le `.gitignore` y veille), mais l'adresse du serveur et le code initial du comptable dans `seed.sql` y figurent. Recommandation : le passer en **privé** (Settings > General > Change visibility), puis ajouter le repreneur comme collaborateur.

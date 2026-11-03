# 16. Guide de reprise : travailler sur le projet sans risque

*Rédigé le 3 novembre 2026. Complète les chapitres 00 à 15 : ceux-ci expliquent **le projet** ; ce chapitre explique **comment s'y mettre**, pas à pas, quand on le reprend.*

Il s'adresse à toute personne qui arrive sur le projet, même sans grande expérience de Git ou de la comptabilité. Il contient :

1. les notions à comprendre avant de toucher à quoi que ce soit ;
2. la manière de proposer des modifications avec Git et GitHub ;
3. un plan pour comprendre le code dans un ordre logique ;
4. les règles d'or pour modifier sans risque ;
5. un aide-mémoire des commandes.

---

## 16.1 Notions à comprendre d'abord

### Votre poste et le serveur sont deux mondes séparés

| | Votre poste | Le serveur (chapitre 11) |
|---|---|---|
| Rôle | Développer, tester | Faire tourner la vraie application |
| Données | Base locale de test ou de démonstration | **Vraie comptabilité** (`Hakili_compta`) |
| Sauvegardes | Facultatives | **Indispensables** |

- Les **données** que vous modifiez dans votre base locale ne vont **jamais** sur le serveur.
- Seul le **code** peut y arriver, et uniquement par une démarche volontaire : `git push` → Pull Request acceptée → `git pull` sur le serveur → redémarrage.
- Les changements de **structure** de la base (nouvelle table, nouvelle colonne) passent par un fichier dans `sql/migrations/`, exécuté automatiquement au redémarrage de l'application.

> **Vérification à faire dès le premier jour :** dans votre `.env`, la ligne `DATABASE_URL` doit contenir `localhost` et le nom de **votre base locale**. Attention si un « tunnel SSH » vers le serveur est ouvert : `localhost` peut alors pointer vers la vraie base.

### Les sauvegardes de la base

Il s'agit de sauvegarder les **données comptables**, pas le code (le code est déjà dans Git). L'outil `pg_dump` « photographie » la base dans un fichier.

- **En production :** `backup/sauvegarde.sh`, lancé sur le serveur. Il exécute `pg_dump` **dans le conteneur** `db` (le serveur n'a pas `pg_dump` et le compte n'a pas les droits administrateur), vérifie le fichier produit et garde 30 jours de sauvegardes. `backup/restauration_essai.sh` permet de vérifier qu'une sauvegarde se restaure bien.
- **En local uniquement :** `backup/pg_backup.py`, sur un poste où `pg_dump` est installé. Pour une sauvegarde ponctuelle, pgAdmin (clic droit sur la base → *Backup…*) suffit.

> **La sauvegarde automatique n'est pas encore en place.** Au 03/11/2026, `sauvegarde.sh` n'est toujours pas programmé (cron) sur le serveur (voir aussi le chapitre 11). Tant que ce n'est pas fait, la base de production n'a aucune sauvegarde automatique : c'est le risque n° 1 du projet et la première tâche à traiter. Une fois la sauvegarde en place, mettez ce paragraphe à jour.

### Ce qui ne va jamais sur GitHub

Le `.gitignore` exclut volontairement :

- `.env` (mots de passe, clé Anthropic) ;
- les environnements Python (`.venv/`, `.venv_nouveau/`) et les caches (`__pycache__/`, `.pytest_cache/`) ;
- les classeurs Excel et certains scripts SQL (noms réels d'élèves et de tiers) ;
- les sauvegardes de base (`backup/sauvegardes/`) et les copies de sécurité locales (`backup/avant_*/`…).

Règle générale : **aucun fichier contenant un mot de passe, une clé ou des données personnelles ne doit être versionné**, ni envoyé par e-mail. Les informations sensibles se transmettent en main propre (voir le tableau à la fin du chapitre 00).

### Copies de sécurité et fichiers `.avant`

Vous trouverez peut-être, sur un ancien poste, des copies comme `backup/avant_tableau_bord_2026-09-28/` ou `app.py.avant` : ce sont des copies faites à la main avant une grosse modification. **Inutile d'en faire** : Git garde chaque version à chaque commit, et permet de revenir en arrière à tout moment.

---

## 16.2 Proposer des modifications avec Git et GitHub

Le dépôt est `imaneodg/hakili-lab-comptabilite`. On ne modifie **jamais** directement la branche `main` : on travaille sur une branche, puis on propose ses modifications par une **Pull Request** que l'équipe relit avant de les accepter.

### Les mots à connaître

| Mot | Ce que ça veut dire | Image |
|---|---|---|
| Dépôt (*repository*) | Le projet et tout son historique | Le classeur du projet |
| Branche | Une copie de travail à part ; `main` est la version officielle | Une photocopie du cahier officiel |
| Commit | Une étape enregistrée, avec un message, l'auteur et la date | Une photo datée avec légende |
| Push | Envoyer ses commits sur GitHub | Poster le courrier |
| Pull | Récupérer les nouveautés de GitHub | Relever la boîte aux lettres |
| Pull Request (PR) | Demande d'intégrer sa branche dans `main` | Rendre un devoir à corriger |
| Merge | Acceptation de la PR : les changements entrent dans `main` | Le devoir validé |
| Diff | Vue des changements : rouge (`-`) supprimé, vert (`+`) ajouté | Les corrections au stylo |

### Pourquoi une branche par modification

- **Sécurité :** une erreur ne touche ni la version officielle ni le serveur.
- **Relecture :** l'équipe voit exactement ce qui change avant de l'accepter.
- **Pas de mélange :** plusieurs personnes peuvent travailler en parallèle.
- **Lisibilité :** une branche = un sujet.

### Le circuit complet

**1. Se placer dans un dossier de travail.** Dans Git Bash, `C:\` s'écrit `/c/` et les `\` deviennent des `/`. Plus simple : clic droit dans le dossier → *Open Git Bash here*.

```bash
cd "/c/Users/<vous>/Desktop/<dossier>"
pwd
```

**2. Récupérer le projet** (une seule fois) :

```bash
git clone https://github.com/imaneodg/hakili-lab-comptabilite.git
cd hakili-lab-comptabilite
```

> Ne travaillez jamais sur une vieille copie du dossier récupérée sur un autre poste : elle peut avoir des semaines de retard sur GitHub. Repartez toujours d'un `git clone` ou d'un `git pull`.

**3. Se présenter à Git** (une seule fois par poste) :

```bash
git config --global user.name "Prénom Nom"
git config --global user.email "vous@exemple.com"
```

**4. Au début de chaque séance : se mettre à jour, puis créer une branche.**

```bash
git checkout main
git pull
git checkout -b nom-du-sujet
```

**5. Modifier, puis tester** (`python verifier.py`, voir chapitre 12).

**6. Préparer, vérifier, enregistrer :**

```bash
git add -A
git status          # relire la liste : aucun .env, aucun Excel, aucun .venv
git commit -m "Message clair qui explique le changement"
```

Pour supprimer un fichier suivi par Git : `git rm chemin/du/fichier`.

**7. Envoyer sa branche sur GitHub :**

```bash
git push -u origin nom-du-sujet
```

Un refus « Permission denied » ou « 403 » signifie que votre compte n'est pas encore collaborateur du dépôt (Settings → Collaborators).

**8. Ouvrir la Pull Request** sur GitHub (bouton *Compare & pull request*) : un titre clair, une description qui dit **quoi** et **pourquoi**, puis *Create pull request*. Après relecture, l'équipe clique sur *Merge*.

**9. Après acceptation :**

```bash
git checkout main
git pull
git branch -d nom-du-sujet
```

### Le `.gitignore`

| On écrit | Ce qui est ignoré |
|---|---|
| `notes.txt` | tous les fichiers `notes.txt`, où qu'ils soient |
| `/notes.txt` | seulement celui de la racine du projet |
| `brouillons/` | tout le dossier `brouillons` |
| `*.xlsx` | tous les fichiers Excel |
| `# texte` | un commentaire |

```bash
cat .gitignore                       # afficher le contenu
git check-ignore -v fichier.txt      # vérifier qu'un fichier est bien ignoré
git rm --cached fichier.txt          # arrêter de suivre un fichier déjà versionné (sans l'effacer du poste)
```

> **Piège :** le `.gitignore` ne s'applique qu'aux fichiers **pas encore suivis**. Pour un fichier déjà sur GitHub, il faut aussi `git rm --cached`, puis un commit. Et un fichier supprimé de GitHub reste dans l'historique : un mot de passe versionné par erreur doit être **changé**.

### Erreurs fréquentes

| Message | Cause | Solution |
|---|---|---|
| `Unable to read current working directory` | Le dossier où se trouve Git Bash a été renommé ou supprimé | `cd` vers un dossier existant, puis `ls` |
| `cd: ...: No such file or directory` | Le dossier n'existe pas (clone non fait, autre nom) | `ls` pour voir le contenu |
| `git status` n'affiche que des `deleted:` | Les fichiers modifiés n'ont pas été ajoutés | `git add -A`, puis `git status` |
| Un éditeur s'ouvre au moment du commit | Oubli de `-m "message"` | Quitter Vim avec `:q!`, relancer avec `-m` |
| `Permission denied` / `403` au push | Pas collaborateur du dépôt | Demander l'accès (Settings → Collaborators) |

---

## 16.3 Plan pour comprendre le projet

Principe : **le métier d'abord, puis l'architecture, puis le code**, toujours sur une base locale.

### Phase 0 — Un terrain d'entraînement sûr (1 à 2 jours)

1. Cloner le dépôt à jour (16.2).
2. Créer une base PostgreSQL **locale** en UTF8 avec `sql/schema.sql` et `sql/seed.sql` (chapitre 12).
3. Vérifier que `DATABASE_URL` pointe vers `localhost`.
4. Lancer l'application : `shiny run app.py`.
5. Lancer `python verifier.py` : tous les tests doivent passer. **C'est la référence de départ** : si un test échoue après une modification, c'est elle qui a cassé quelque chose.

### Phase 1 — Le métier (2 à 3 jours)

- **À lire :** chapitres 00, 01, 02 et 15.
- **Notions clés :** journaux (CP, CMD…), comptes (571 caisse, 411 clients, 707 produits…), tiers, pièce, équilibre débit/crédit, validation, export Sage.
- **Exercice :** dans l'application locale, jouer les deux rôles : saisir un encaissement (centre), le valider (comptable), l'exporter vers Sage. Circuit : **Saisie → Contrôle → Validation → Export**.

### Phase 2 — L'architecture (2 jours)

- **À lire :** chapitres 05, 06 et 07.

| Couche | Fichier(s) | Rôle |
|---|---|---|
| Interface | `app.py`, `composants.py`, `tableau_bord.py`, `www/` | Ce que l'utilisateur voit |
| Règles comptables | `logic/modeles.py` | Formulaire → lignes d'écriture (sans base de données) |
| Accès aux données | `logic/donnees.py` | Enregistrer, valider, numéroter, exporter |
| Base | `sql/schema.sql` + `sql/migrations/` | Structure des tables |
| Assistant IA | `assistant/` | Réponses en langage naturel sur les données |

- **Exercice :** redessiner ce schéma sur papier et l'expliquer à quelqu'un.

### Phase 3 — Le code, du plus simple au plus gros (1 à 2 semaines)

1. `composants.py` : petit, pour découvrir le style du projet.
2. `logic/modeles.py` avec le chapitre 04 : le cœur métier, facile à tester.
3. `logic/donnees.py` (~2 000 lignes) : par sections (connexion, enregistrement, validation, numérotation, export).
4. `app.py` (~3 750 lignes) : onglet par onglet.
5. Selon le besoin : tableau de bord (chapitre 08), assistant IA (09), export Sage (10).

> **Méthode recommandée :** suivre **une seule opération** de bout en bout, par exemple « Encaissement de frais de scolarité » : formulaire dans `app.py` → règle dans `modeles.py` → enregistrement dans `donnees.py` → table en base → ligne dans l'export Sage. Tout le reste suit le même schéma.

### Phase 4 — Les tests comme mode d'emploi

Lire la partie tests du chapitre 12, puis les tests liés à ce que l'on étudie (par exemple `tests/test_modeles.py` avec `logic/modeles.py`). Un test montre, avec des exemples concrets, comment une fonction doit se comporter.

### Phase 5 — Premières modifications, du moins risqué au plus risqué

1. Texte ou apparence (un libellé, une couleur dans `www/app.css`).
2. Documentation (`docs/`).
3. Petite règle métier dans `logic/modeles.py`, avec un test.
4. Changement de base de données, une fois à l'aise.

Pour choisir des tâches utiles : la liste des chantiers du chapitre 13.

---

## 16.4 Les règles d'or pour modifier sans risque

1. **Une branche par modification**, puis une Pull Request. Jamais directement sur `main`.
2. **`git pull` sur `main` au début de chaque séance**, avant de créer sa branche.
3. **Tests avant et après :** `python verifier.py` doit passer avant de commencer, et encore après.
4. **Tout correctif vient avec un test** qui échoue avant et passe après.
5. **Base de données :** ne jamais modifier `schema.sql` pour une base existante ; ajouter un fichier dans `sql/migrations/`.
6. **Ne jamais lancer** `production_reset.sql`, `purge_avant_mise_en_service.sql`, `schema.sql`, `seed.sql` ou `import_historique.py` sur `Hakili_compta`, ni `docker compose down -v` sur le serveur.
7. **Avant de changer un comportement,** vérifier dans le chapitre 14 s'il n'a pas été choisi exprès.
8. **Des petites Pull Requests,** faciles à relire.
9. **Aucun secret dans le dépôt** (mot de passe, clé, données personnelles).
10. **En cas de doute, demander** avant de toucher au serveur.

---

## 16.5 Aide-mémoire des commandes

| Commande | Ce qu'elle fait |
|---|---|
| `pwd` | Afficher le dossier courant |
| `ls` | Lister le contenu du dossier |
| `cd "/c/chemin/du/dossier"` | Aller dans un dossier |
| `git clone URL` | Télécharger un dépôt GitHub |
| `git pull` | Récupérer les nouveautés de GitHub |
| `git checkout main` | Revenir sur la version officielle |
| `git checkout -b nom` | Créer une branche et s'y placer |
| `git status` | Voir ce qui a changé et ce qui est prêt à être enregistré |
| `git add -A` | Préparer toutes les modifications |
| `git rm fichier` | Supprimer un fichier et préparer sa suppression |
| `git commit -m "message"` | Enregistrer une étape (en local) |
| `git push -u origin nom` | Envoyer sa branche sur GitHub (première fois) |
| `git log --oneline -5` | Voir les 5 derniers commits |
| `git diff fichier` | Voir les lignes modifiées |
| `git ls-files ...` | Vérifier quels fichiers sont suivis par Git |
| `git remote -v` | Voir à quel dépôt GitHub le dossier est relié |
| `git branch -d nom` | Supprimer une branche locale devenue inutile |
| `python verifier.py` | Lancer toute la suite de tests sur une base jetable |
| `shiny run app.py` | Lancer l'application en local |

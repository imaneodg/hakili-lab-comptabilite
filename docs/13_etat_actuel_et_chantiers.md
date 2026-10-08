# 13. État au 8 octobre 2026 et chantiers à mener

## 13.1 Où en est le projet

**En production** (serveur `167.233.234.219`) :
- l'application tourne depuis le 15/09/2026 ; dernier déploiement documenté : commit `aa7028e` (assistant IA reconstruit), le 23/09/2026. `main` sur GitHub est un peu plus loin (`a7236c9`, 25/09) : vérifiez sur le serveur avec `git log -1 --oneline` si ce dernier commit a été déployé ;
- la base contient le plan comptable (1 040 comptes) et le plan tiers (1 454 tiers) chargés depuis Sage le 18/09, et les pièces saisies depuis la mise en service (base nettoyée le 23/09 pour ne garder que les 39 pièces de référence du 01 au 04/04/2026, puis la saisie réelle). Depuis le 07/10/2026, **toutes les saisies doivent se faire dans l'application** (plus de brouillards Excel) ;
- aucune sauvegarde automatique ne tourne ;
- l'état du HTTPS n'a pas pu être vérifié.

**Prêt mais pas en production** :
- le **tableau de bord** complet, le **camp de vacances** séparé et le **motif des transferts** : branche `tableau-bord-v2`, poussée sur GitHub, non fusionnée dans `main` ;
- les **correctifs de l'audit du 07/10** (sauvegardes, clôture des mois, protection des pièces exportées, alerte et double confirmation avant de renvoyer à Sage une pièce déjà exportée, codes tiers à 17 caractères, verrou de validation, rapidité, centre concerné pour le comptable, gestion des codes d'accès, rôle de lecture pour l'assistant) : dans la copie de travail d'Afiya, **non commités**. 299 tests réussis, parcours vérifiés dans le navigateur, base neuve et base migrée testées.

**Dans Sage** : le dossier « HAKILI LAB SARL COMPTABILITE DEFINITIF 2026 » a été paramétré le 23/09 (format `HAKILI_ECRITURES`, sections, dates), mais le dernier blocage noté était la **longueur des comptes tiers** (le dossier devait être recréé avec 17). Le premier import réel n'est pas documenté : **à vérifier avec Afiya ou le comptable** avant tout export.

## 13.2 À faire en premier (dans l'ordre)

### 1. Mettre le code au propre et le déployer

Sur le poste qui a la copie de travail d'Afiya (ou en récupérant ses fichiers) :

```bash
git status                                  # 13 fichiers modifiés, 7 nouveaux
python verifier.py                          # 299 tests attendus
git add -A && git status                    # relire : aucun .xlsx, .env, .log, dump
git commit -m "Correctifs de l'audit du 07/10/2026 : export Sage protege, sauvegardes, clotures, codes"
git push origin tableau-bord-v2
git checkout main
git merge tableau-bord-v2                   # avance rapide attendue
python verifier.py
git push origin main
```

Puis déployer (chapitre 11.4). Au démarrage, quatre migrations doivent se jouer en production : `2026-10-07_camp_de_vacances`, `2026-10-07b_motif_transfert` et celle du 08/10 (`2026-10-08_correctifs_audit`), plus celles du tableau de bord (`2026-10-02`, `2026-10-03`, `2026-10-03b`) si elles n'y sont pas encore. Vérifiez dans `schema_migrations`.

Après le déploiement :
- si le journal signale « Des codes tiers dépassent 17 caractères » : `outils/tiers_trop_longs.sql`, renommer avant le prochain export, puis rejouer le bloc de contrainte ;
- vérifier les pièces saisies par le comptable sur le Siège : `SELECT DISTINCT id_piece, date_piece FROM ecritures WHERE centre = 'SIE';` et les corriger vers le bon centre si elles ne sont pas exportées ;
- prévenir le comptable : l'écran Export Sage est le même, mais une pièce déjà exportée ne repart plus sans les deux cases de confirmation (chapitre 10.4).

### 2. Mettre en route les sauvegardes

`backup/sauvegarde.sh` dans le crontab, une restauration d'essai, une copie hors du serveur (chapitre 11.5 et 11.6). Tant que ce n'est pas fait, toute la comptabilité tient sur un seul disque.

### 3. Sécurité

- Avec l'administrateur : **HTTPS** sur l'adresse de l'application, compte SSH pour le repreneur.
- Changer le **mot de passe SSH** de `imane` et le **mot de passe de la base** (ils sont apparus en clair pendant le travail ; le second est aussi dans `Claude outputs/env` sur le poste d'Afiya, fichier à supprimer).
- Le **code du compte `comptable`** : le seed crée ce compte avec un code connu, présent dans un dépôt public. Afiya a décidé le 08/10/2026 de le laisser tel quel (seed et production). Le risque est réel tant que le dépôt est public : à rediscuter avec la direction, et au minimum passer le dépôt en privé. Le comptable peut changer son code à tout moment dans Référentiel > Mon code d'accès.
- Passer le **dépôt GitHub en privé**.

### 4. Vérifier les données de départ

- **Soldes d'ouverture** de chaque caisse (CP et CMD par centre) et de la banque : signalés manquants le 23/09 (« CP Saaba, Pissy, Tampouy sont négatifs sans eux »). Les saisir avec le comptable, à la date de mise en service.
- Les **33 tiers douteux** écartés au chargement du plan tiers : à trancher avec le comptable.
- Le centre « SIA » : vérifier qu'il n'existe pas en double avec un « SIAO » dans la base de production.

### 5. Trancher les décisions en attente

| Sujet | Options | Qui décide |
|---|---|---|
| Impôts et taxes (64) | rester hors exploitation, ou passer en charges d'exploitation comme le veut SYSCOHADA (une ligne SQL) | direction + comptable |
| Accès du directeur | rôle `directeur` qui voit tableau de bord et assistant en lecture | direction |
| Longueur du libellé Sage | mesurer dans Sage, couper à l'export si < 60 | comptable |

## 13.3 Chantiers, par priorité

### Priorité haute (ce mois-ci)

1. **Numéros de pièce sur 4 chiffres.** Le compteur définitif est par journal et par mois, **tous centres confondus**. Avec cinq centres qui saisissent tout dans l'application, la caisse principale peut dépasser 999 pièces dans un mois (rentrée). Au-delà, le numéro passe à 4 chiffres et le tri de l'export se dérègle (`CP26101000` avant `CP2610999`). Passer à `{n:04d}` dans `valider_pieces` et `numero_definitif`, après avoir vérifié la longueur du numéro de pièce dans Sage (13 caractères : `CP26100001` en fait 10, `CMD26100001` 11).
2. **Classement du tableau de bord par mot entier** (`flux_tableau_bord` : `~ ('\m' || motif || '\M')`), et revoir l'ordre « motif sur préfixe court » qui fait passer des vacations en dossiers de conseil (chapitre 8.5). Par une nouvelle migration, avec les chiffres de référence du 8.6 pour contrôler.
3. **Champ « Nature » dans le règlement fournisseur** (vacation, loyer, eau/électricité, internet, entretien, équipement, dossier de conseil, autre), pour ne plus deviner la charge au libellé.
4. **`sql/seed.sql`** : journal `Banque` sur 521200 (et compte 521200 « Banques (CBI) »), journal `BDU-BF` inactif, pour qu'une base neuve ressemble à la production.
5. **`resoudre_tiers` dans la transaction de l'enregistrement** : aujourd'hui un tiers est créé sur sa propre connexion juste avant l'enregistrement ; si celui-ci échoue, le tiers reste en base, orphelin. Sans gravité, mais à faire proprement.
6. **Journaux Docker** : ne garder que la sortie standard et ajouter une rotation dans `docker-compose.yml` (`logging: {driver: json-file, options: {max-size: "10m", max-file: "5"}}`).
7. **Supervision** : une sonde externe gratuite sur l'adresse de l'application, qui prévient si elle tombe.

### Priorité moyenne

8. **Formulaires** (demandes du 03/10) : compte 706 dédié au camp (à créer aussi dans Sage) ; avance au personnel séparée du salaire (421000 plutôt que 422300) ; `632800` trop large dans « Dépense courante » (transport/parking, droits et quittances à séparer, avec le comptable).
9. **Tableau de bord** : choix « pièces validées seulement » pour les chiffres présentés à la direction ; version directeur ; prévision de trésorerie sur 3 mois ; corriger le texte du contrôle « Dates aberrantes ».
10. **Interface** : accents manquants dans le formulaire de saisie et les notifications (« MODELE D'OPERATION », « ELEVE »…), montants préremplis « 0.0 », texte anglais de la grille (« Viewing rows… »), colonne Libellé du Brouillard qui montre une ligne quelconque de la pièce (trier les lignes dans `table_pieces`).
11. **Intégration continue** : une action GitHub avec un service PostgreSQL qui lance la suite de tests à chaque push.
12. **Image Docker** : utilisateur non root, `pytest` et `httpx` dans un `requirements-dev.txt` séparé.
13. **Performance** : si l'application ralentit (un seul processus), déporter le tableau de bord avec `reactive.extended_task`, ou plusieurs workers avec sessions collantes côté nginx.

### Ménage

14. Supprimer les fichiers vides (`demo_manuel.py`, `mock_ocr_server.py`, `services/ocr_client.py`, `tests/test_ocr_client.py`), `nettoyer_operations.py`, `backup/donnees_avant_correctifs_sage_2026-09-23.py`, `backup/pg_backup.py` et `backup/cron_sauvegarde_host.sh` une fois `sauvegarde.sh` en place.
15. Ajouter un `.gitattributes` (`* text=auto eol=lf`).
16. Remplacer le `README.md` par un court texte qui renvoie à `docs/`.
17. Découper `app.py` (~3 750 lignes) en modules par onglet (saisie, brouillard, validation, export, contrôles, référentiel), comme l'a été le tableau de bord. À faire avec les tests de réactivité et d'autorisation comme filet.

### Idées abandonnées ou en sommeil

- **OCR des factures** : un projet de lecture automatique des factures pour préremplir les formulaires (consignes détaillées dans le document « prompt » du projet claude.ai). Un client et un faux serveur avaient été écrits puis vidés ; rien n'est actif. À reprendre seulement si la direction le redemande, en respectant le principe : préremplir, jamais enregistrer sans contrôle humain.
- **Pièces justificatives numériques** (photo du reçu attachée à la pièce) : demandé au début, jamais commencé.
- **Import des brouillards historiques en production** : écarté le 16/09/2026. Si la direction change d'avis, la liste des corrections à faire d'abord sur les fichiers est dans `qualite-donnees-et-formulaires-2026-10-03.md` (projet claude.ai) : dates fausses, soldes d'ouverture, reports, approvisionnements qui ne collent pas, motifs des remises au SIAO, comptes à contre-emploi, camp, tiers, pages manquantes.

## 13.4 Ce qui a été vérifié et qui tient

Pour savoir sur quoi s'appuyer sans tout revérifier (audit du 07/10/2026) :

- installation neuve et migrations complètes et rejouables ;
- équilibre par pièce, signe des montants, unicité des numéros et des rapprochements de transferts, imposés par la base ;
- cloisonnement des centres sur toutes les actions, refusé côté serveur ;
- correction d'une pièce en une seule transaction, avec verrou ;
- une pièce renvoyée puis revalidée reprend son numéro ;
- tableau de bord réservé au comptable côté serveur, cibles enregistrées en une transaction.

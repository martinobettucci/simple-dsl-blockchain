# Spécifications TDD / Stratégie de Tests Professionnelle

**Projet :** Blockchain Programmable Pédagogique (Python)
**Version cible du protocole :** v5
**Audience :** Test Engineers / SDET / QA Automation Senior
**Objectif :** Industrialiser la qualité pédagogique – garantir que chaque invariant protocolaire documenté dans la spécification v5 est capturé dans des tests automatisés reproductibles, exécutables en CI, pilotant le développement (Red→Green→Refactor).

---

## 0. Principes Directeurs

* **Spec-as-code :** Chaque règle fonctionnelle ou contrainte protocolaire du document v5 doit être référencée au moins par un test (unit, component, scenario ou property-based).
* **TDD first-class :** Les tests sont écrits *avant* ou *conjointement* au code. Un test échouant = backlog de dev.
* **Déterminisme pédagogique :** Réduire la non‑déterminisme réseau/horloge/PoW pour obtenir des tests stables. Mock ou seed contrôlé.
* **Isolation modulaire, puis orchestration bout‑en‑bout :** pyramide de tests (80% unit, 15% intégration ciblée, 5% scénarios bout‑à‑bout multi‑process).
* **Assert invariants métier, pas l’implémentation interne :** valider les effets visibles (JSON sérialisé, récompenses calculées, quorum atteint, etc.).
* **Données test lisibles :** JSON courts, clés hex fictives, partageables en formation.
* **Observabilité testable :** Hooks / logs machine‑parsables pour extraire preuves (ex : compteur signatures, quorum threshold, latence handshake).

---

## 1. Portée de la Campagne de Tests

Les tests couvrent **trois axes** :

1. **Pure Python units** (fonctions / classes pures) : hashage, signatures, parsing DSL, calcul quorum, distribution récompenses.
2. **Composants avec effets I/O** : mempool, persistance blocs, lecture/écriture JSON canonique, réseau simulé en mémoire.
3. **Scénarios protocole multi‑nœuds** : mineur + N validateurs, quorum, signatures tardives, forks concurrents, anti‑censure premiums.

Hors scope v5 : sécurité réseau avancée, performance à l’échelle >10 validateurs, attaques réseau byzantines sophistiquées (peuvent être mockées minimalement).

---

## 2. Cadre Outils & Standards Qualité

| Item             | Recommandation                                                                             | Statut / Action                             |
| ---------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------- |
| Framework test   | **pytest**                                                                                 | Obligatoire                                 |
| Property-based   | **hypothesis**                                                                             | Fortement recommandé (DSL, random premiums) |
| Couverture       | `coverage.py` + fail < 85% global; 100% lignes sur algos critiques (hash, quorum, rewards) | À configurer en CI                          |
| Lint             | flake8 / ruff                                                                              | Gate pre‑commit                             |
| Typage           | mypy strict (ou pyright)                                                                   | Info / alerte                               |
| Style assertions | pytest style + helpers custom (`assert_block`, `assert_tx_valid`)                          | À implémenter                               |
| CI               | GitHub Actions (matrix py3.10/3.11/3.12)                                                   | Pipeline à livrer                           |

---

## 3. Taxonomie des Niveaux de Tests

### 3.1 Niveaux

| Niveau | Nom             | Description                                         | Exemple                                         |
| ------ | --------------- | --------------------------------------------------- | ----------------------------------------------- |
| U      | Unit            | Fonction pure / méthode de classe isolée            | `calc_quorum()`, `dsl_eval()`                   |
| C      | Component       | Module + dépendances légères mockées                | `Mempool.add_tx()` avec mock solde              |
| I      | Integration     | Plusieurs modules réels interagissent               | Mineur + validateur via boucle évènement locale |
| S      | System Scenario | Processus séparés / sockets réels / JSON sur disque | 3 validateurs, quorum, fork                     |

### 3.2 Priorisation RAG

* **P0 (Must Pass)** : invariants protocole critiques (séparation balances/state, quorum freeze, anti‑censure premium).
* **P1 (Should Pass)** : observabilité, CLI dev tools, TTL bloc candidat.
* **P2 (Nice)** : métriques latence, explorer UX, dégradés réseau.

---

## 4. Matrice Traçabilité Spécification ↔ Tests

> But : assurer une couverture bidirectionnelle. Chaque règle de la spec v5 reçoit un ID `SPEC-XXX`; chaque test porte `TEST-YYY` et référence les IDs concernés.

Extrait initial (à compléter dans `tests/specmatrix.yaml`) :

| Spec § | Description courte                                | ID Spec             | Type Test | Test ID(s)           |
| ------ | ------------------------------------------------- | ------------------- | --------- | -------------------- |
| §5.1   | DSL ne modifie jamais balances                    | SPEC-STATE-IMMUT    | U,C,I     | TEST-DSL-IMMUT-001…  |
| §5.2   | Tri mempool par premium desc                      | SPEC-ANTICENS-ORDER | U,C,S     | TEST-MPOOL-SORT-001… |
| §5.7   | Quorum freeze signers\_frozen à 1er quorum        | SPEC-QUORUM-FREEZE  | I,S       | TEST-QUORUM-002…     |
| §5.7   | Premiums partagés égalitairement + reste → mineur | SPEC-ECON-DIST      | U,I,S     | TEST-REWARDS-003…    |
| §7     | Découverte rôle challenge‑signature               | SPEC-ROLE-CHAL      | C,I,S     | TEST-ROLE-001…       |
| §14    | Fork: longest‑finalized‑chain wins                | SPEC-FORK-LONGEST   | I,S       | TEST-FORK-001…       |

Maintenir la matrice sous contrôle de version ; test failing ⇒ pointer vers Spec ID.

---

## 5. Jeux de Données & Fixtures

Concevoir un répertoire `tests/fixtures/` versionné.

### 5.1 Clés & Wallets Factices

* Générer 5 paires ECDSA (hex) : `MINER_A`, `VAL_A`, `VAL_B`, `VAL_C`, `USER_X`.
* Fichiers JSON wallet alignés sur format runtime.
* Script `make-fixtures.py` régénérable (idempotent) → ne jamais commiter clés prod.

### 5.2 Genesis Standard

* Hash zéro, height=0, finalized=true.
* Balances initiales : mineur=0, validateurs=0, étudiants pré‑alloués variable.
* State initial : `{"counter": 0}`.

### 5.3 Configs Paramétriques

Créer plusieurs configs pour param tests :

| Nom           | Quorum    | Diff PoW    | Tx Cap | Usage                         |
| ------------- | --------- | ----------- | ------ | ----------------------------- |
| `cfg_fast3`   | 51% (2/3) | très faible | 3      | tests rapides                 |
| `cfg_strict5` | 80% (4/5) | moyenne     | 3      | quorum stress                 |
| `cfg_fifo`    | 51%       | faible      | 3      | anti‑censure comparaison FIFO |

### 5.4 DSL Scripts Canon

\| Nom | Script | Effet attendu sur state |
\| INC1 | `let counter = counter + 1;` | counter++ |
\| INC2\_TEMP | `let counter = counter + 1; let temperature = counter - 2;` | 2 mutations |
\| BAD\_VAR | `let unknown = x + 1;` | Erreur -> tx rejetée |

### 5.5 Premium Patterns

Listes de tx avec premiums variés \[0,1,2,5,10] pour anti‑censure.

---

## 6. Spécifications TDD par Module

Chaque sous‑section : **Objectif**, **Cas Nominal**, **Cas Limite/Erreur**, **Mocks/Stubs nécessaires**, **Critères d’acceptation**.

### 6.1 `config.py`

**Objectif :** Charger paramètres protocole, fallback défauts, override CLI/env.

**Tests**

* TEST-CONFIG-LOAD-001 (P0): Charger fichier complet → attributs accessibles.
* TEST-CONFIG-DEFAULT-002 (P0): Champs absents → valeurs défaut documentées.
* TEST-CONFIG-VALIDATE-003 (P1): Erreur si quorum\_percent ∉ \[1,100].
* TEST-CONFIG-PATHS-004 (P1): Création automatique dossiers (blocks/, pending/) si absent (ou raise contrôlé selon design).

**Acceptation** : Tous paramètres critiques exposés; échec clair sur valeurs invalides.

---

### 6.2 `wallet.py`

**Objectif :** Gestion clés ECDSA, signatures tx, solde local utilitaire.

**Tests**

* TEST-WALLET-GEN-001 (P0): Générer paire → pub hex ≠ priv, longueur attendue.
* TEST-WALLET-SIGN-002 (P0): Signer payload; verify\_sig ok.
* TEST-WALLET-BADSIG-003 (P0): Mutation payload invalide verify\_sig.
* TEST-WALLET-NONCE-004 (P1): Incrément nonce persisté.

**Edge** : Clé non présente, format JSON corrompu.

---

### 6.3 `dsl.py`

**Objectif :** Parser + évaluer scripts sur snapshot `state`.

**Tests**

* TEST-DSL-PARSE-001 (P0): Script simple valide.
* TEST-DSL-PARSE-ERR-002 (P0): Syntax error → exception.
* TEST-DSL-EVAL-INC-003 (P0): counter++ applique valeur correcte.
* TEST-DSL-EVAL-SEQ-004 (P0): Ordre séquentiel sur variables dépendantes.
* TEST-DSL-UNKNOWN-005 (P0): Variable inconnue → erreur (config défaut).
* TEST-DSL-TOLERANT-006 (P2): Mode tolérant (si activé) substitue 0.

**Property‑Based**

* TEST-DSL-PROP-ARITH-007 (P1): Hypothesis sur expressions +/‑ entiers bornés → évaluation Python équivalente.

---

### 6.4 `transaction.py`

**Objectif :** Modèle transaction, hash canonique, validation signatures & nonces.

**Tests**

* TEST-TX-CANON-001 (P0): JSON canonique trié → hash stable.
* TEST-TX-SIGNATURE-002 (P0): Signature valide acceptée; tamper champ → rejet.
* TEST-TX-NONCE-MONO-003 (P0): Nonce doit être strictement croissant par adresse.
* TEST-TX-PREMIUM-MIN-004 (P0): premium >= MIN\_PREMIUM.
* TEST-TX-BALANCE-CHECK-005 (P0): rejet si solde < premium.
* TEST-TX-DSL-VALID-006 (P0): rejet si DSL invalide.

---

### 6.5 `mempool.py`

**Objectif :** Admission et ordonnancement.

**Tests**

* TEST-MPOOL-ADMIT-001 (P0): tx valide admise.
* TEST-MPOOL-REJECT-BADSIG-002 (P0).
* TEST-MPOOL-REJECT-NONCE-003 (P0).
* TEST-MPOOL-REJECT-BAL-004 (P0).
* TEST-MPOOL-SORT-PREMIUM-005 (P0): tri desc stable par premium puis FIFO arrivée.
* TEST-MPOOL-MODE-FIFO-006 (P1): config FIFO respecte ordre arrivée.
* TEST-MPOOL-DUP-007 (P1): même tx\_hash ignorée ou remplacée (définir comportement).

---

### 6.6 `block.py`

**Objectif :** Construction bloc candidat, hash sans signatures, PoW, finalisation.

**Tests**

* TEST-BLOCK-HASH-001 (P0): `block_hash` invariant sous permutation signatures.
* TEST-BLOCK-POW-002 (P0): `nonce` trouvé satisfait `DIFFICULTY_BITS`.
* TEST-BLOCK-POW-FAIL-003 (P0): bloc muté échoue vérification.
* TEST-BLOCK-FINALIZE-004 (P0): distribution rewards & premiums selon spec, freeze signers.
* TEST-BLOCK-LATE-SIG-005 (P0): signature ajoutée après finalisation n’affecte pas balances.
* TEST-BLOCK-SERIALIZE-006 (P1): JSON canonique stable round‑trip.

Mock : injecter `hashlib` patched pour PoW rapide ou définir difficulté basse.

---

### 6.7 `network.py`

**Objectif :** Découverte pairs, challenge rôle, routage messages.

**Tests**

* TEST-ROLE-CHAL-001 (P0): Peer signe nonce; validateur reconnu si pubkey ∈ validators.json.
* TEST-ROLE-CHAL-NONVAL-002 (P0): Peer signe mais non listé → `is_validator=False`.
* TEST-ROLE-CHAL-BADSIG-003 (P0): signature invalide → False.
* TEST-NET-BCAST-TX-004 (P1): broadcast tx à tous.
* TEST-NET-BCAST-PROPOSAL-005 (P1): bloc candidat envoyé uniquement aux validateurs authentifiés (ou fallback broadcast si 0, spec §7.5).

Simuler réseau en mémoire (bus d’événements) pour vitesse.

---

### 6.8 `node.py`

**Objectif :** Orchestration rôle local (miner/validator/both/full), cycle mine‑collect‑finalize, persistance blocs.

**Tests**

* TEST-NODE-STARTUP-ROLE-001 (P0): nœud démarre avec rôle CLI.
* TEST-NODE-MINER-BUILD-002 (P0): mineur construit bloc candidat avec tri premium.
* TEST-NODE-VALIDATE-SIGN-003 (P0): validateur signe bloc valide.
* TEST-NODE-QUORUM-FINALIZE-004 (P0): 2/3 validateurs → bloc finalisé + rewards.
* TEST-NODE-TTL-EXPIRE-005 (P1): quorum non atteint dans TTL → bloc abandonné / reproposé.
* TEST-NODE-RESTART-RESYNC-006 (P1): redémarrage lit fichiers blocs et reconstruit tip.

---

### 6.9 `explorer.py`

**Objectif :** API REST lecture‑seule cohérente avec état local.

**Tests (via client HTTP de test)**

* TEST-EXP-CHAIN-001 (P0): `/chain` renvoie séquence finalisée ordonnée.
* TEST-EXP-BLOCK-002 (P0): `/block/<hash>` champs attendus.
* TEST-EXP-PENDING-003 (P1): expose blocs candidats + count signatures.
* TEST-EXP-VALIDATORS-004 (P1): stats signatures/quorum correctes.
* TEST-EXP-DIFF-005 (P2): calcul delta vs parent fiable.

---

### 6.10 CLI Dev Tools

**Objectif :** UX dev; non critique consensus mais pédagogique.

Tests de fumée (smoke) P2 : commandes retournent code 0, produisent fichiers attendus.

---

## 7. Scénarios Intégrés Multi‑Nœuds (System)

Ces scénarios orchestrent plusieurs nœuds réels (process séparés ou threads isolés + ports distincts). Utiliser `pytest-xdist` ou harness custom.

### S-01 Quorum Basique (P0)

**Setup :** 1 mineur, 3 validateurs (ValA, ValB, ValC), quorum=51% (2). 3 tx premiums mixtes.
**Attendu :** Bloc finalisé après signatures ValA+ValB. Rewards : mineur + (ValA, ValB). ValC tardif non payé.
**Vérifier :** `signers_frozen == {ValA, ValB}`, `validator_signatures` contient ValC après coup, balances conformes.

### S-02 Anti‑Censure Premium vs FIFO (P0)

**Setup :** 5 tx premiums \[10,0,5,2,2]; exécuter run1 mode premium, run2 mode FIFO.
**Attendu :** Ordre d’inclusion différent; tx premium=10 en tête run1; en FIFO run2 respect arrivée.
**Vérifier :** Explorer /chain montre ordres divergents.

### S-03 Bloc Expire Sans Quorum (P1)

**Setup :** Isoler 1 validateur offline; quorum=80% (4/5) impossible; TTL=5s.
**Attendu :** Bloc candidat abandonné; mempool réinclus; nouveau bloc peut être proposé quand quorum possible.

### S-04 Fork Convergent (P0)

**Setup :** Partition réseau → deux tips concurrents même height. Réunification.
**Attendu :** Chaîne la plus longue (nombre blocs finalisés) retenue; tie‑breaker PoW > hash > timestamp.

### S-05 Redémarrage / Reindex (P1)

**Setup :** Créer 5 blocs; tuer tous nœuds; redémarrer en lisant `blocks/`.
**Attendu :** Tip reconstruit, state/balances recalculés.

### S-06 Challenge Échoué (P0)

**Setup :** Peer malicieux revendique pubkey ValA mais ne peut signer nonce.
**Attendu :** is\_validator=False; signatures rejetées pour quorum.

---

## 8. Invariants à Asserter Globalement

Les invariants suivants doivent être vérifiés soit par tests dédiés soit via assertions cross‑scenario.

| ID Invariant        | Description                                                   | Méthode Vérif                                      |
| ------------------- | ------------------------------------------------------------- | -------------------------------------------------- |
| INV-STATE-READONLY  | DSL ne modifie pas balances                                   | Snapshot balances avant/après exécution DSL isolée |
| INV-BAL-NONNEG      | Balances jamais négatives (sauf si design contraire)          | Post‑bloc loop                                     |
| INV-TX-HASH-UNIQ    | tx\_hash unique par bloc                                      | Parser bloc                                        |
| INV-BLOCK-CHAINED   | header.prev\_hash match hash parent                           | Walk chaîne                                        |
| INV-QUORUM          | `finalized` ⇒ signatures ≥ quorum                             | Calcul croisé                                      |
| INV-PREMIUM-CONSERV | Somme premiums débitée = somme distribuée + reste mineur/burn | Agrégation bloc                                    |

---

## 9. Mocks, Stubs & Test Utilities

Créer paquet `tests/utils/`.

### 9.1 Crypto

* `sign_dummy(priv, msg)` → hexsig.
* `force_sig(pub)` pour simuler signatures invalides.

### 9.2 PoW Accelerator

* Mode difficulté=1 bit pour unit tests.
* Ou patch fonction `meets_difficulty()`.

### 9.3 Clock Control

* Fixture `frozen_time` (freezegun) pour timestamps reproductibles.
* Simuler drift.

### 9.4 Ephemeral Network Bus

* Bus en mémoire (pub/sub Python) remplaçant sockets pour tests rapides C/I.
* Induire pertes (%drop) & latence.

---

## 10. Gestion des Données Temporaire / Sandbox

Chaque test crée un dossier temporaire (`tmp_path`) avec sous‑dirs `blocks/`, `pending/`, copies isolées de config & fixtures. Jamais de collision entre tests parallèles.

---

## 11. Stratégie de Données Paramétriques & Hypothesis

Utiliser Hypothesis pour générer :

* Suites de transactions avec premiums entiers \[0..MAX] + nonces monotones.
* Scripts DSL aléatoires valides (grammaire restreinte) → fuzzer parser.
* Topologies réseau (N validateurs, quorum%) pour tester limites.

**Propriétés cibles** :

1. Toute suite tx valide mène à un state déterministe donné un ordre d’inclusion figé.
2. Permuter signatures n’affecte pas `block_hash` ni `balances` finalisés.
3. Le quorum calculé mathématiquement correspond à l’état finalisé.

---

## 12. Modèle de Nomination Tests & Marqueurs Pytest

Adopter un schéma lisible :

```
tests/
  unit/
    test_dsl_parse.py
    test_transaction_model.py
  component/
    test_mempool.py
    test_network_role.py
  integration/
    test_quorum_flow.py
  system/
    test_scenario_fork.py
```

Marqueurs :

* `@pytest.mark.p0`, `p1`, `p2`
* `@pytest.mark.slow` (scénarios multi‑process)
* `@pytest.mark.network` (tests sockets réels)

CI peut exécuter `-m "p0 and not slow"` en gating rapide.

---

## 13. Critères de Sortie Qualité (Definition of Done QA)

Un incrément est **livrable** quand :

1. Tous tests P0 passent sur matrix Python supportée.
2. Couverture lignes ≥85% global; modules consensus ≥95%.
3. Mutation testing (optionnel) score ≥70% sur modules consensus.
4. Aucune régression sur scénarios S-01 à S-04.
5. Lint & type checks verts.

---

## 14. Guides d’Écriture pour le Testeur

* **Toujours fixer la difficulté PoW très basse en test**; sinon flaky.
* **Ne jamais asserter un timestamp exact** sauf si horloge mockée; préférer ranges.
* **Comparer JSON canonisé** (`sort_keys=True`, `separators=(",",":")`).
* **Utiliser helpers d’assertion riches** : diff state/balances, check signatures in/out.
* **Documenter la logique économique** dans les tests (why vs what) – pédagogique.

---

## 15. Exemples de Cas TDD Concrets

### 15.1 Exemple TDD Unitaire : Calcul du Quorum

**Spec :** quorum numérique = `ceil(N * quorum_percent / 100)`.

**Test (rouge)**

```python
def test_calc_quorum_rounds_up():
    assert calc_quorum(n=3, percent=51) == 2  # 1.53 -> 2
```

**Implémenter → vert → refactor.** Ajouter cas limites percent=100, n=0.

---

### 15.2 Exemple TDD Intégration : Freeze signers

**Spec :** Au 1er quorum atteint, la liste des validateurs signataires est figée; signatures tardives loggées mais non payées.

**Test (pseudo)**

```python
def test_freeze_signers_post_quorum(network_3vals):
    # mine bloc, recevoir signatures ValA+ValB
    blk = wait_for_finalized(...)
    assert blk.signers_frozen == {ValA, ValB}
    balA, balB = get_balances(vals=[ValA, ValB])
    # Inject signature tardive ValC
    send_signature(blk.hash, ValC)
    blk2 = get_block(blk.hash)
    assert ValC in blk2.validator_signatures
    assert blk2.signers_frozen == {ValA, ValB}  # inchangé
    assert get_balance(ValC) == 0  # pas payé
```

---

### 15.3 Exemple Système : Anti‑Censure Premium

**Spec :** mempool tri premium desc; blocs remplis par ordre premium.

**Test (pseudo)**

```python
def test_anticensure_premium_vs_fifo(cluster_factory):
    cluster = cluster_factory(mode="premium")
    txs = submit_premium_burst(cluster.miner, premiums=[10,0,5])
    blk = wait_for_finalized(cluster)
    assert [tx.premium for tx in blk.transactions] == [10,5,0]
    # Rejouer en FIFO
    cluster2 = cluster_factory(mode="fifo")
    txs2 = submit_premium_burst(cluster2.miner, premiums=[10,0,5])
    blk2 = wait_for_finalized(cluster2)
    assert [tx.premium for tx in blk2.transactions] == [10,0,5]  # arrivée
```

---

## 16. Données de Performance & Scalabilité (Tests Optionnels)

Même si non objectif prod, quelques bornes :

* Temps moyen finalisation bloc (N=3 validateurs, diff faible) <2s sur laptop.
* Charge mempool 1k tx → tri <100ms.
* Persist 1k blocs → reindex <5s.
  Ces mesures peuvent être marquées `perf` et non gating.

---

## 17. Sécurité Minimale (Tests Négatifs)

* Signature ECDSA invalide sur tx → rejet admission.
* Bloc PoW invalide → validateur refuse signature.
* Peer revendique rôle validateur sans preuve → n’est pas compté au quorum.
* DSL tentant de muter `balances` (si injection) → rejet.

---

## 18. Artefacts de Test & Rapport

Générer artefacts après run CI :

* Rapport couverture HTML.
* Graph dépendances test vs spec (généré depuis `specmatrix.yaml`).
* Archives JSON blocs produits par scénarios système (pour relecture en cours magistral).

---

## 19. Checklist Pour Le Testeur Avant Merge

* [ ] Nouvelles règles protocole mappées à ID Spec.
* [ ] Tests unitaires ajoutés.
* [ ] Tests intégration adaptés si impact.
* [ ] Fixtures mises à jour (validators, config, genesis).
* [ ] Docs test (`README_tests.md`) rafraîchies.

---

## 20. Annexes

* **Annexe A :** Mapping complet Spec v5 → Tests (fichier YAML séparé, auto‑générable).
* **Annexe B :** Gabarits Hypothesis stratégies DSL.
* **Annexe C :** Exemple cluster harness (threaded) pour scénarios système.

---

### Fin Spécifications TDD v1 (alignée sur protocole v5)

Veuillez réviser, commenter et prioriser les cas P0 afin de lancer la phase de squelettisation des tests.

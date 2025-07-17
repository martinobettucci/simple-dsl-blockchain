# Blockchain Programmable Pédagogique (Python)

**Version :** v5
**Statut :** Alpha pédagogique robuste (non orienté production)
**Public cible :** Développeurs Python confirmés, enseignants/TD L2→M1, ateliers Web3/IA.

> Cette blockchain minimaliste sert de *bac à sable pédagogique* pour explorer l’intégrité par hash, un consensus hybride **Preuve de Travail (PoW) + Quorum de validateurs (≥51 %)**, des incitations économiques simples (prime anti-censure), et un DSL transactionnel modifiant un *state global* distinct des *balances* monétaires. Elle privilégie la lisibilité, la hackabilité et l’expérimentation rapide.
Pour une vue complète de l'implémentation et de la stratégie de tests, consultez respectivement [SPECIFICATIONS.md](SPECIFICATIONS.md) et [TEST_SPECIFICATIONS.md](TEST_SPECIFICATIONS.md).

---

## ⚡ TL;DR / Elevator Pitch

Construisez, minez, signez et visualisez une mini‑blockchain en Python :

* Chaîne de blocs hashés immuables.
* PoW + quorum numérique de validateurs statiques.
* Anti‑censure démonstrative via **ordonnancement par premium** (payez → passez en priorité).
* Transactions signées ECDSA + DSL embarqué pour muter un *state global JSON*.
* **Séparation stricte** *state* vs *balances* (le DSL ne touche jamais à l’argent).
* Signatures de validateurs **non ordonnées**, agrégées a posteriori.
* Récompenses distribuées au mineur + validateurs présents dans le **signers\_frozen** (snapshot au 1er quorum atteint).
* Rôles réseau (mineur/validateur/both/full) **découverts dynamiquement à runtime via challenge‑signature** — aucun rôle n’est stocké dans `peers.json`.
* Gestion explicite des forks (stockage fichier par bloc, règle *longest‑finalized‑chain wins*).
* Explorer Web intégré pour visualiser transactions, blocs, forks, signatures & incitations.

---

## Table des Matières

* [1. Pourquoi ce projet ?](#1-pourquoi-ce-projet-)
* [2. Cas d’usage pédagogiques](#2-cas-dusage-pédagogiques)
* [3. Fonctionnalités Clés](#3-fonctionnalités-clés)
* [4. Architecture Globale](#4-architecture-globale)

  * [4.1 Vue Macro](#41-vue-macro)
  * [4.2 Flux Consensus](#42-flux-consensus)
* [5. Démarrage Rapide](#5-démarrage-rapide)

  * [5.1 Pré‑requis](#51-pré-requis)
  * [5.2 Installation](#52-installation)
  * [5.3 Configuration initiale](#53-configuration-initiale)
  * [5.4 Lancer un nœud](#54-lancer-un-nœud)
  * [5.5 Envoyer une transaction](#55-envoyer-une-transaction)
* [6. Arborescence du Projet](#6-arborescence-du-projet)
* [7. Paramètres Protocole](#7-paramètres-protocole)
* [8. Modèles de Données (JSON Schemas)](#8-modèles-de-données-json-schemas)
* [9. Règles Métier & Consensus Détail](#9-règles-métier--consensus-détail)
* [10. DSL Transactionnel](#10-dsl-transactionnel)
* [11. Réseau & Découverte de Rôle](#11-réseau--découverte-de-rôle)
* [12. Explorer Web](#12-explorer-web)
* [13. Flux Économiques & Incitations](#13-flux-économiques--incitations)
* [14. Forks & Sélection de Chaîne](#14-forks--sélection-de-chaîne)
* [15. Journalisation & Observabilité](#15-journalisation--observabilité)
* [16. Tests & Exercices TP](#16-tests--exercices-tp)
* [17. Roadmap / Backlog](#17-roadmap--backlog)
* [18. Licence & Responsabilités](#18-licence--responsabilités)
* [Annexe A : Spécification Fonctionnelle & Technique Complète](#annexe-a--spécification-fonctionnelle--technique-complète)

---

## 1. Pourquoi ce projet ?

Les étudiants apprennent mieux quand ils peuvent *voir* et *casser* le système. Les stacks blockchain industrielles sont complexes : réseau P2P évolué, VM complète, cryptographie avancée, sécurité de prod… Ici nous extrayons le *noyau conceptuel* : blocs, hash, PoW, quorum de validateurs, signatures, incitations économiques basiques, priorisation économique anti‑censure, forks et finalité.

Objectifs opérationnels :

* Démystifier les mécanismes essentiels d’une blockchain.
* Offrir un terrain de jeu modifiable en quelques minutes (scripts Python courts, JSON lisibles).
* Illustrer comment les incitations économiques altèrent l’ordonnancement des transactions.
* Montrer la différence entre *signatures totales* vs *signers gelés rémunérés*.
* Mettre en évidence la découverte de rôle au réseau (pas de confiance dans la config partagée).

---

## 2. Cas d’usage pédagogiques

| Niveau         | Atelier / TP                                                                | Concepts cibles                                |
| -------------- | --------------------------------------------------------------------------- | ---------------------------------------------- |
| L2             | Mise en place, hash chain, minage basique                                   | Hash, PoW, immutabilité                        |
| L3             | Transactions signées, mempool premium vs FIFO                               | Anti‑censure, signatures ECDSA                 |
| M1             | Quorum validateurs, agrégation signatures, forks                            | Finalité probabiliste vs quorum, incitations   |
| Pro / Bootcamp | Expériences incitatives, attaques offline validateurs, recomposition chaîne | Tolérance aux fautes, gouvernance protocolaire |

---

## 3. Fonctionnalités Clés

* **Consensus hybride :** PoW + quorum numérique (≥51 %) sur un *validator set statique* défini dans `validators.json`.
* **Anti‑censure par prime :** tri des transactions par `premium` décroissant dans le mempool (mode pédagogique). Option `FIFO`.
* **Séparation State / Balances :** le DSL n’interagit qu’avec le *state* applicatif ; les *balances* ne sont mises à jour que par le protocole (rewards + premiums).
* **Signatures validateurs non ordonnées :** agrégation possible dans n’importe quel ordre ; union des signatures connues.
* **Finalisation par quorum :** congèle la liste `signers_frozen` et déclenche la distribution économique.
* **Rôle réseau dynamique :** aucun rôle dans `peers.json` — handshake + challenge‑signature runtime pour authentifier les validateurs.
* **Gestion forks pédagogique :** stockage fichier par bloc, reconstruction graphe parent/enfant, règle *longest‑finalized‑chain wins*.
* **Explorer Web intégré :** inspection blocs, transactions, state, balances, signatures, forks, incitations.

---

## 4. Architecture Globale

### 4.1 Vue Macro

```text
+-------------+             +-------------------+             +--------------------+
|  Wallet(s)  | --RPC-->    |    Miner Node     | --P2P-->    |   Validator Nodes  |
+-------------+             |  - Mempool        |<--P2P-->    | (sign blocks)      |
                            |  - Build Block    |             +--------------------+
                            |  - PoW            |                     |
                            +-------------------+                     v
                                    |                           Block Finalisé
                                    v
                               Explorer Web
```

### 4.2 Flux Consensus

1. Les utilisateurs soumettent des transactions signées (avec premium) → mempool.
2. Le mineur trie par premium décroissant, sélectionne jusqu’à `BLOCK_TX_CAP` transactions, exécute le DSL sur un snapshot parent, puis calcule le PoW du bloc candidat.
3. Le bloc candidat est diffusé aux pairs identifiés comme validateurs (découverts runtime).
4. Chaque validateur rejoue et vérifie : PoW, signatures tx, exécution DSL, cohérence rewards mineur.
5. Si valide, il signe le `block_hash` (identique pour tous, signatures non ordonnées) et renvoie sa signature.
6. Les signatures sont agrégées. Lorsque le **quorum numérique** est atteint (ceil(N \* %quorum)), on gèle la liste des signataires actuels (`signers_frozen`).
7. Répartition des premiums + reward bloc → mineur + validateurs dans `signers_frozen`. Bloc marqué `finalized=true`, écrit sur disque, diffusé globalement.
8. Signatures tardives reçues après finalisation sont stockées mais **non rémunérées** et ne modifient pas `signers_frozen`.

---

## 5. Démarrage Rapide

### 5.1 Pré‑requis

* Python ≥3.10 (testé sur 3.11+ recommandé).
* OpenSSL / lib cryptographique supportée par la lib ECDSA Python utilisée.
* Accès disque lecture/écriture (stockage blocs JSON).

### 5.2 Installation

```bash
git clone <repo> blockchain_demo
cd blockchain_demo
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 5.3 Configuration initiale

1. Exécutez `python genesys.py` une fois pour générer les wallets des trois validateurs,
   créer `validators.json`, `balances.json`, `state.json` et le bloc genesis signé.
2. Renseignez `peers.json` avec les endpoints bootstrap **sans indiquer de rôle**.
3. Ajustez `config.py` (difficulté PoW, quorum, récompenses, ports…).

### 5.4 Lancer un nœud

```bash
python node.py --config config.py --local-role miner
# ou
python node.py --config config.py --local-role validator
# ou nœud mixte
python node.py --config config.py --local-role both
```

Au démarrage, le nœud lit `peers.json`, initie un *handshake /status* puis un *challenge /role\_challenge* pour authentifier les validateurs.

### 5.5 Envoyer une transaction

```bash
python wallet.py send-tx \
  --wallet wallets/alice.json \
  --script "let counter = counter + 1" \
  --premium 2
```

La transaction est signée ECDSA, envoyée aux pairs, et rejoindra le mempool du mineur.

---

## 6. Arborescence du Projet

```text
blockchain_demo/
├── blocks/                  # 1 fichier JSON par bloc finalisé (hash.json)
│   └── 000...0.json         # genesis block (prev_hash = zeros)
├── pending/                 # Blocs candidats en attente de signatures (non finalisés)
├── node.py                  # Orchestration complète (mineur / validateur / both, param runtime)
├── wallet.py                # Clés, signature, vérification, utilitaires solde
├── dsl.py                   # Parser + exécution DSL sur state global
├── transaction.py           # Classe Transaction + validations
├── block.py                 # Classe Block + PoW + signatures validateurs + (de)sérialisation
├── mempool.py               # Tri premium des tx en attente (mode FIFO optionnel)
├── network.py               # Broadcast naïf, challenge rôles, collecte signatures, sync, forks
├── explorer.py              # API REST + vues HTML (blocks, forks, signatures, incitations)
├── static/
│   ├── index.html           # UI explorer minimaliste
│   ├── style.css
│   └── script.js
├── config.py                # Paramètres protocole (rewards, difficulté, quorum, chemins…)
├── state.json               # Snapshot quick-start du state courant (branche active)
├── balances.json            # Snapshot quick-start balances courantes (branche active)
├── validators.json          # Registre des validateurs statiques (pubkeys, quorum)
├── peers.json               # Liste d'endpoints réseau *sans rôle* (host/port seulement)
├── requirements.txt
└── README.md                # Documentation (incl. extrait des specs)
```

---

## 7. Paramètres Protocole

Les valeurs par défaut sont définies dans `config.py`. Tableau de référence :

| Paramètre                  | Défaut    | Description                             |
| -------------------------- | --------- | --------------------------------------- |
| `BLOCK_TX_CAP`             | 3         | Nb max de tx par bloc                   |
| `BLOCK_REWARD`             | 5         | \$COIN au mineur                        |
| `MIN_PREMIUM`              | 0         | Prime mini par tx                       |
| `TX_QUEUE_MODE`            | "premium" | Politique mempool ("premium" ou "fifo") |
| `QUORUM_PERCENT`           | 51        | % validateurs requis                    |
| `DIFFICULTY_BITS`          | 20        | Cible PoW                               |
| `BLOCK_CANDIDATE_TTL`      | 120       | Expiration bloc candidat (s)            |
| `PREMIUM_REMAINDER_TARGET` | "miner"   | Reste premium → mineur ou burn          |
| ...                        | ...       | Voir `config.py`                        |

---

## 8. Modèles de Données (JSON Schemas)

Les formats JSON sont volontairement compacts et lisibles. Extraits :

### `validators.json`

```json
{
  "validators": [
    {"pubkey": "0xVAL1", "name": "Val-A"},
    {"pubkey": "0xVAL2", "name": "Val-B"},
    {"pubkey": "0xVAL3", "name": "Val-C"}
  ],
  "quorum_percent": 51
}
```

### `peers.json` (aucun rôle)

```json
{
  "peers": [
    {"host": "127.0.0.1", "port": 9001},
    {"host": "127.0.0.1", "port": 9002}
  ]
}
```

### Transaction canonique

```json
{
  "from": "0xPUB1",
  "script": "let counter = counter + 1; let temp = counter - 2;",
  "premium": 2,
  "nonce": 42,
  "signature": "hexsig"
}
```

### Bloc finalisé

```json
{
  "hash": "<block_hash>",
  "header": {
    "prev_hash": "<parent_hash>",
    "height": 12,
    "nonce": 998877,
    "timestamp": 1731862123,
    "miner": "0xPUB_MINER"
  },
  "transactions": [ /* ... ≤3 ... */ ],
  "state": { /* snapshot post-exec */ },
  "balances": { /* snapshot post-rewards */ },
  "validator_signatures": {
    "0xVAL1": "hexsig",
    "0xVAL3": "hexsig"
  },
  "finalized": true,
  "signers_frozen": ["0xVAL1", "0xVAL3"]
}
```

---

## 9. Règles Métier & Consensus Détail

Principes structurants :

### 9.1 Séparation *State* / *Balances*

* Le DSL modifie uniquement le *state applicatif*.
* Les *balances* sont gérées par protocole : reward mineur + distribution premiums.

### 9.2 Mempool & Anti‑Censure

* Tri par premium décroissant (pédagogie incitations). Option FIFO.
* Filtrage : signature ECDSA valide, nonce monotone, solde ≥ premium, DSL parsable.

### 9.3 Construction Bloc Candidat

* Sélectionne jusqu’à `BLOCK_TX_CAP` tx.
* Re‑validation solde & nonce.
* Exécute DSL séquentiel sur snapshot parent.
* Ajoute reward mineur provisoire (premiums pas encore partagés).
* Calcule PoW sur contenu **sans signatures validateurs**.

### 9.4 Validation côté Validateur

* Vérifie challenge‑rôle si nécessaire.
* Recalcule PoW.
* Rejoue DSL & cohérence reward.
* Signe `block_hash` si pubkey ∈ validator set statique et nœud lancé avec rôle validateur.

### 9.5 Quorum & Finalisation

* `QUORUM = ceil(N_validateurs * QUORUM_PERCENT/100)`.
* À l’atteinte du quorum : gèle `signers_frozen`, distribue premiums, crédite rewards, marque `finalized=true`, écrit sur disque, broadcast global.
* Signatures tardives visibles mais non rémunérées.

---

## 10. DSL Transactionnel

Grammaire minimale inspirée pseudo‑C :

```ebnf
SCRIPT   := STMT (';' STMT)* ';'?
STMT     := 'let' IDENT '=' EXPR
EXPR     := TERM (('+'|'-') TERM)*
TERM     := IDENT | INT
IDENT    := [a-zA-Z_][a-zA-Z0-9_]*
INT      := [0-9]+
```

Règles :

* Variables = clés dans `state`.
* Assignation séquentielle (ordre des tx dans bloc).
* Variable inconnue ⇒ *erreur* (tx rejetée) par défaut.
* Mode alternatif (tolérance =0) activable (TODO).

---

## 11. Réseau & Découverte de Rôle

`peers.json` ne contient que des endpoints. La confiance s’établit au runtime :

### 11.1 Handshake `/status`

Renvoie pubkey déclarée + capacités (mining / validation) + hauteur & tip.

### 11.2 Challenge `/role_challenge`

Le demandeur envoie un nonce aléatoire (32o). Le pair signe le nonce et renvoie sa pubkey + signature. Si la pubkey match `validators.json` et la signature est valide → ce peer est un **validateur économique authentifié**.

### 11.3 Routage Messages (résumé)

| Message            | Cible                       | Objet               |
| ------------------ | --------------------------- | ------------------- |
| `tx_broadcast`     | Tous                        | Propagation tx      |
| `block_proposal`   | Validateurs authentifiés    | Collecte signatures |
| `block_sig_update` | Validateurs + mineur source | Agrégation          |
| `block_finalized`  | Tous                        | Chaîne globale      |

---

## 12. Explorer Web

L’outil `explorer.py` expose une API REST + UI statique minimaliste.

### Endpoints REST Principaux

| Méthode | Route               | Description                                                     |
| ------- | ------------------- | --------------------------------------------------------------- |
| GET     | `/chain`            | Chaîne active finalisée ordonnée                                |
| GET     | `/branches`         | Liste branches finalisées                                       |
| GET     | `/pending`          | Blocs candidats + compte signatures                             |
| GET     | `/block/<hash>`     | Détails bloc (tx, state, balances, signatures, signers\_frozen) |
| GET     | `/state`            | State courant (tip chaîne active)                               |
| GET     | `/balances`         | Balances courantes                                              |
| GET     | `/tx/<hash>`        | Détail transaction                                              |
| GET     | `/address/<pubkey>` | Solde + historique                                              |
| GET     | `/validators`       | Registre validateurs + stats signatures/quorum                  |
| GET     | `/diff/<hash>`      | Delta state/balances vs parent                                  |
| GET     | `/peers`            | Peers détectés + statut preuve                                  |

---

## 13. Flux Économiques & Incitations

* `BLOCK_REWARD` crédité au mineur à la finalisation.
* Somme des `premium` des tx incluses : part égale à chaque validateur dans `signers_frozen`.
* Reste de division entière → mineur (ou burn selon config).
* *Premium débité à la finalisation* (mode par défaut). Option refund si tx rejetée au build bloc (`PREMIUM_REFUND_ON_FAIL`).

---

## 14. Forks & Sélection de Chaîne

* Seuls blocs `finalized=true` participent à la chaîne canonique.
* Reconstruction graphe à partir des fichiers `blocks/*.json`.
* Règle principale : **longest‑finalized‑chain wins**.
* Égalité : total PoW > hash lexicographique > timestamp.
* State & balances actifs dérivent du tip canonique.

---

## 15. Journalisation & Observabilité

Le projet logge intentionnellement des événements didactiques :

* Résultats handshake rôle (peer, pubkey, validateur? OK/KO, latence).
* Signatures reçues par bloc (compteur/nécessaire, quorum atteint?).
* Finalisation bloc (signers\_frozen, rewards distribués).
* Blocs rejetés (PoW invalide, DSL fail, quorum expiré, signature invalide…).
* Ordre inclusion tx + premium (visualisation anti‑censure).

---

## 16. Roadmap / Backlog

**Court terme**

* Scripts d’orchestration multi‑process (launcher N nœuds locaux).
* Visualisation interactive du graphe de forks dans l’Explorer.

**Moyen terme**

* Support TLS optionnel (didactique sur authentification transport).
* Mode simulateur latence/réseau partitionné.
* Paramétrage dynamique difficulté PoW.

**Long terme / stretch**

* Plugin VM WASM pédagogique.
* Migration vers protocole gossip + NAT traversal simplifié.
* Hooks IA/NLP pour analyser scripts DSL générés automatiquement (lien pédagogie IA‑Web3).

---

## 17. Licence & Responsabilités

Projet éducatif. Aucun engagement de sécurité, de confidentialité, ni de valeur économique. À n’utiliser que dans des environnements de test / démo. Recommandation : licence permissive type MIT ou Apache‑2.0 (à confirmer avant publication publique).

---

### Contact & Support

Pour retours pédagogiques, tickets et PR : ouvrez une *issue* GitHub ou contactez-moi sur LinkedIn.

---

Merci d’utiliser la Blockchain Programmable Pédagogique ! Amusez‑vous, cassez‑la, réparez‑la, apprenez.

# Spécification Fonctionnelle & Technique Complète

**Projet :** Blockchain Programmable Pédagogique (Python)

> Version : **v5**
> Changements clés v5 : Découverte dynamique des rôles réseau (miner / validator / both) au lancement, **peers.json sans rôles** (endpoints uniquement), **preuve de rôle par challenge-signature** pour les validateurs, validator set statique connu d’avance (validators.json), intégration complète avec PoW + quorum, anti-censure par premium, signatures agrégées non ordonnées, stockage par bloc / forks.
> Public cible : Développeur senior Python (implémentation pédagogique robuste).

---

## 0. Vision produit & pédagogie

Blockchain minimaliste destinée à des cours/TP en informatique (L2/L3, M1) démontrant :

* Chaîne de blocs chaînés par hash (intégrité immuable).
* Consensus hybride **PoW + quorum de validateurs (≥51 %)**.
* Résilience pédagogique à la censure via **ordonnancement par prime (premium)** : *si tu paies plus, tu passes*, les validateurs sont incités à signer les blocs qui les rémunèrent.
* Transactions signées via wallets ECDSA.
* Mempool & minage par lots fixes (3 transactions/bloc).
* Récompense de bloc + partage des primes (premiums) de transactions **entre validateurs signataires du bloc finalisé** (freeze au quorum).
* DSL minimal embarqué dans chaque transaction pour modifier un **state global** partagé.
* **Séparation stricte** entre state (données applicatives) et balances (avoirs wallets).
* Gestion explicite des forks avec stockage par bloc (`/blocks/<hash>.json`), genesis hash zéro.
* **Signatures de validateurs non ordonnées, agrégées par block\_hash.**
* **Découverte de rôle réseau à runtime via challenge cryptographique** (pas d’info de rôle dans peers.json).
* Explorer web intégré (inspection blocks, tx, state, balances, signatures validateurs, forks, incitations).

Objectif : lisibilité, hackabilité, expérimentation en atelier. **Non orienté production.**

---

## 1. Périmètre fonctionnel

| Domaine      | Inclus                                                    | Exclus                                      |
| ------------ | --------------------------------------------------------- | ------------------------------------------- |
| Consensus    | PoW + quorum validateurs (51 %+)                          | PoS, slashing, BFT complet                  |
| Anti-censure | Mempool trié par premium décroissant                      | Politique réputationnelle                   |
| Signatures   | Agrégation non ordonnée, quorum numérique, preuve de rôle | Séquençage ordonné, multi-round BFT         |
| Transactions | Script DSL + premium + signature                          | Smart contracts persistants                 |
| State        | Global JSON modifiable DSL                                | États privés, VM avancée                    |
| Balances     | Comptabilité interne \$COIN                               | Multi-actifs, DEX                           |
| Réseau       | Peers statiques (endpoints), rôle découvert à runtime     | Gossip multi-hop avancé, NAT traversal      |
| Sécurité     | Signatures ECDSA, nonces, quorum, challenge rôles         | Anti-DoS durci, chiffrement TLS obligatoire |
| Explorer     | Lecture forks, signatures, incitations                    | Authentification, analytics temps-réel      |

---

## 2. Architecture globale

### 2.1 Vue macro

```
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

### 2.2 Flux consensus (haut niveau)

1. **Users** broadcastent des transactions signées (premium) → mempool.
2. **Mineur** sélectionne tx (tri premium desc), construit bloc candidat, calcule PoW.
3. Bloc candidat broadcast aux **peers** → validateurs identifiés signent si valides.
4. Chaque validateur vérifie PoW, tx, state, balances → signe `block_hash` (ordre indifférent) et renvoie signature.
5. Signatures sont **agrégées** par union ; propagation incrémentale.
6. Quand **quorum ≥51 %** des validateurs statiques connus est atteint → bloc finalisé, récompenses figées aux signataires du quorum (signers\_frozen).
7. Bloc finalisé broadcast globalement, stocké, intégré à la chaîne active (fork rules).

---

## 3. Arborescence projet

```
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

## 4. Modèle de données & schémas JSON

### 4.1 Registre des validateurs statiques (`validators.json`)

Les validateurs économiques (ceux qui comptent pour le quorum et reçoivent des primes) sont connus à l’avance et fixes pour la démo.

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

> Le quorum numérique = ceil(N \* quorum\_percent/100).

### 4.2 Table des peers réseau (`peers.json`)

**Aucun rôle stocké.** Endpoints nus ; les rôles (miner / validator / both / full) sont **découverts à runtime** via handshake cryptographique.

```json
{
  "peers": [
    {"host": "127.0.0.1", "port": 9001},
    {"host": "127.0.0.1", "port": 9002},
    {"host": "127.0.0.1", "port": 9003},
    {"host": "127.0.0.1", "port": 9004}
  ]
}
```

> Un endpoint peut appartenir à un mineur, un validateur, les deux, ou un observateur.

### 4.3 Wallet local (config instance)

Le rôle local est choisi **au lancement du client** (CLI ou config) ; il n’est pas fiable pour les autres nœuds et ne figure pas dans peers.json.

```json
{
  "public_key": "hex",
  "private_key": "hex",      
  "address": "hex",           
  "last_nonce": 41,
  "local_role": "miner"        
}
```

`local_role` ∈ {"miner", "validator", "both", "full"}.

> Si `local_role` contient `validator` mais la clé n’est pas dans `validators.json`, le nœud peut signer mais ne comptera pas dans le quorum.

### 4.4 Balances (snapshot)

```json
{"balances": {"0xPUB1": 100, "0xPUB2": 87}}
```

### 4.5 State global (snapshot)

```json
{"state": {"counter": 17, "temperature": 42}}
```

### 4.6 Transaction JSON canonique

```json
{
  "from": "0xPUB1",
  "script": "let counter = counter + 1; let temp = counter - 2;",
  "premium": 2,
  "nonce": 42,
  "signature": "hexsig"
}
```

### 4.7 Bloc JSON canonique (/blocks/<hash>.json)

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
  "transactions": [ ... up to 3 ... ],
  "state": { ... snapshot post-exec ... },
  "balances": { ... snapshot post-rewards ... },
  "validator_signatures": {
    "0xVAL1": "hexsig",
    "0xVAL3": "hexsig"
  },
  "finalized": true,
  "signers_frozen": ["0xVAL1", "0xVAL3"]
}
```

* `validator_signatures` = map agrégée (toutes signatures connues, y compris tardives).
* `signers_frozen` = liste ordonnée des validateurs comptés pour rémunération (snapshot au quorum).

---

## 5. Règles métier détaillées

### 5.1 Séparation State vs Balances (règle d’or)

Le DSL ne touche jamais aux balances. Les balances ne sont modifiées que par le protocole (premiums, rewards mineur, primes validateurs).

### 5.2 Ordonnancement mempool & anti-censure

* Mode par défaut : **tri par premium décroissant** (pay more → mine sooner) pour illustrer résistance à la censure par comportement greedy.
* Mode alternatif pédagogique : FIFO (config `TX_QUEUE_MODE`).
* Tri stable recommandé (premium desc, puis ordre d’arrivée).

### 5.3 Admission mempool

1. Vérif signature ECDSA.
2. Vérif nonce monotone.
3. Vérif solde >= premium.
4. Pre-parse DSL (syntaxe, identifiants).
5. Ajouter à mempool.

> Débit premium appliqué **au moment de finalisation du bloc** (mode protocolaire par défaut). Option mempool-lock en config.

### 5.4 Sélection tx pour bloc candidat

* Extraire jusqu’à `BLOCK_TX_CAP` tx selon politique.
* Re-vérifier solde & nonce.
* Exécuter DSL séquentiellement (sandbox state\_parent).
* Tx échouées → exclues (refund premium si lock).

### 5.5 Création bloc *candidat* (mineur)

1. Header prev\_hash = tip active.
2. TX list choisie.
3. State\_post = exécution DSL.
4. Balances provisoires = balances\_parent + block\_reward\_miner (premiums pas encore répartis).
5. Flags init : `finalized=false`; `validator_signatures={}`; `signers_frozen=[]`.
6. PoW calculé sur contenu sans signatures.
7. Broadcast `block_proposal` à tous les peers (réseau filtrera).

### 5.6 Validation bloc candidat (validateur) — preuves & signatures non ordonnées

Pour chaque bloc candidat reçu :

* Vérifier preuve de rôle (voir §7.5) pour l’émetteur *si nécessaire* (facultatif debug).
* Recalcul PoW.
* Vérifier tx, signatures wallets.
* Rejouer DSL.
* Vérifier cohérence balances provisoires (reward mineur).
* Signer `block_hash` avec clé locale si (a) clé ∈ validator\_set statique & (b) node lancé avec rôle validateur ou both.
* Broadcast `block_sig_update` (inclut pubkey + signature + éventuellement signatures agrégées reçues).

### 5.7 Quorum & finalisation (freeze récompenses au 1er quorum)

* Quorum numérique = ceil(N\_validateurs \* quorum\_percent/100).
* Agréger signatures uniques tant que `finalized=false`.
* Lors quorum atteint :

  * `signers_frozen = tri(pubkeys_signataires_actuels)`.
  * Calcul primes : sum premiums / len(signers\_frozen). Reste → mineur (défaut) ou burn.
  * Crédit block\_reward au mineur.
  * Crédit part premium à chaque validateur de signers\_frozen.
  * Balances\_post = balances\_parent + reward + premiums\_distribution.
  * `finalized=true`.
  * Écrire bloc dans `/blocks/<hash>.json`.
  * Broadcast `block_finalized`.
* Signatures tardives ajoutées à `validator_signatures` mais **non rémunérées** et **non ajoutées à signers\_frozen**.

### 5.8 Ajout bloc finalisé à la chaîne

* Seuls blocs `finalized=true` participent à la chaîne canonique.
* Validation réception : PoW + quorum + replay DSL + cohérence balances\_post.

### 5.9 Gestion des forks

* Graph parent->children à partir des fichiers dans `/blocks/`.
* Sélection **longest-finalized-chain wins**.
* Tie-breakers : total PoW > hash lexicographique > timestamp.
* State & balances actifs dérivent du tip chaîne canonique.

### 5.10 Blocs signés différemment (séquences divergentes)

* Identité bloc = `block_hash` (contenu sans signatures).
* Toutes signatures valides reçues pour ce hash → union dans `validator_signatures`.
* Finalisation se produit une seule fois (1er quorum) → freeze `signers_frozen` et récompenses.
* Explorateur affiche signatures complètes vs signers\_frozen rémunérés.

---

## 6. Explorer Web

### 6.1 Objectifs

* Visualiser branches, blocs candidats, signatures, incitations économiques.
* Montrer différence signatures totales vs signers\_frozen (payants).

### 6.2 Endpoints REST

| Méthode | Route               | Description                                                      |
| ------- | ------------------- | ---------------------------------------------------------------- |
| GET     | `/chain`            | Branche active (finalisée) ordonnée.                             |
| GET     | `/branches`         | Liste de toutes les branches finalisées.                         |
| GET     | `/pending`          | Blocs candidats en attente de quorum.                            |
| GET     | `/block/<hash>`     | Détails bloc (tx, state, balances, signatures, signers\_frozen). |
| GET     | `/state`            | State courant (branche active).                                  |
| GET     | `/balances`         | Balances courantes (branche active).                             |
| GET     | `/tx/<hash>`        | Détail tx (finalisé + pending).                                  |
| GET     | `/address/<pubkey>` | Solde + tx impliquant pubkey.                                    |
| GET     | `/validators`       | Registre validateurs + stats signatures/quorum.                  |
| GET     | `/diff/<hash>`      | Delta state/balances vs parent.                                  |
| GET     | `/peers`            | Peers détectés + rôle runtime + statut preuve.                   |

---

## 7. Réseau & synchronisation

### 7.1 Principes

* Fichier **peers.json** = endpoints cibles bootstrap (pas de rôle).
* Chaque node tente un **handshake runtime** avec chaque peer pour découvrir son pubkey et ses capacités (miner? validator?).
* Les validateurs économiques sont connus statiquement (validators.json). Un peer se déclarant validateur doit **prouver** qu’il contrôle la clé listée.

### 7.2 Handshake `/status` (découverte initiale)

Client → `GET /status`
Réponse attendue :

```json
{
  "pubkey": "0xNODEPUB",
  "supports_mining": true,
  "supports_validation": true,
  "height": 37,
  "tip_hash": "abc123..."
}
```

> Cette déclaration est auto-reportée et **non fiable**. Passer par challenge pour valider.

### 7.3 Challenge de rôle `/role_challenge`

**But :** prouver que le peer contrôle la clé privée associée à sa pubkey, et qu’il peut signer comme validateur si sa pubkey ∈ validator\_set.

Flux :

1. Local génère nonce 32 octets aléatoire.
2. POST `/role_challenge` → `{ "nonce": "hex", "expect_validator": true }`.
3. Peer répond :

```json
{
  "pubkey": "0xNODEPUB",
  "signature": "hexsig_over_nonce"
}
```

4. Local vérifie signature ECDSA(pubkey, nonce).
5. Si pubkey ∈ validator\_set ⇒ peer authentifié comme **validator actif**.
6. Sinon peer traité comme mineur/full selon ses annonces (informelles) ou usage observé.

### 7.4 Cache des pairs identifiés

Le node maintient en mémoire :

```python
PeerInfo = {
  "host": str,
  "port": int,
  "pubkey": str | None,
  "is_validator": bool,
  "last_seen": timestamp,
  "latency_ms": float
}
```

### 7.5 Routage des messages

| Message                         | Ciblage runtime                                     | Notes                        |
| ------------------------------- | --------------------------------------------------- | ---------------------------- |
| tx\_broadcast                   | Tous peers                                          | Tx doivent atteindre mineurs |
| block\_proposal                 | Peers `is_validator==True`; fallback broadcast si 0 | Collecte signatures          |
| block\_sig\_update              | Tous validateurs authentifiés + mineur source       | Agrégation                   |
| block\_finalized                | Tous peers                                          | Chaîne globale               |
| chain\_request / block\_request | Tous peers                                          | Sync                         |

### 7.6 Gestion pairs injoignables

* Timeout configurable.
* Si quorum impossible car validateurs offline → bloc expire (TTL), mineur peut re-proposer un bloc (même contenu ou nouveau).

---

## 8. Paramètres protocole (config.py)

| Paramètre                  | Type | Défaut            | Description                                |
| -------------------------- | ---- | ----------------- | ------------------------------------------ |
| BLOCK\_TX\_CAP             | int  | 3                 | Nb max de tx par bloc                      |
| BLOCK\_REWARD              | int  | 5                 | \$COIN au mineur                           |
| MIN\_PREMIUM               | int  | 0                 | Prime min par tx                           |
| TX\_QUEUE\_MODE            | str  | "premium"         | "premium" ou "fifo"                        |
| QUORUM\_PERCENT            | int  | 51                | % validateurs requis                       |
| DIFFICULTY\_BITS           | int  | 20                | cibles PoW                                 |
| DATA\_DIR                  | str  | "./"              | Racine données                             |
| BLOCKS\_DIR                | str  | "./blocks"        | Blocs finalisés                            |
| PENDING\_DIR               | str  | "./pending"       | Blocs candidats                            |
| STATE\_FILE                | str  | "state.json"      | Snapshot state actif                       |
| BAL\_FILE                  | str  | "balances.json"   | Snapshot balances actives                  |
| VALIDATORS\_FILE           | str  | "validators.json" | Registre validateurs                       |
| PEERS\_FILE                | str  | "peers.json"      | Endpoints bootstrap                        |
| API\_PORT                  | int  | 8545              | Port HTTP                                  |
| LOCAL\_ROLE                | str  | "miner"           | miner / validator / both / full            |
| BLOCK\_CANDIDATE\_TTL      | int  | 120               | Durée (s) avant abandon bloc candidat      |
| PREMIUM\_REFUND\_ON\_FAIL  | bool | true              | Rendre premium si tx rejetée en build bloc |
| PREMIUM\_REMAINDER\_TARGET | str  | "miner"           | "miner" ou "burn"                          |

---

## 9. Genesis Block

* Fichier `/blocks/000...0.json` (hash plein de zéros, longueur hash PoW).
* `prev_hash` = hash de zéros.
* `finalized = true` (par définition, pas de signatures nécessaires).
* `signers_frozen = []`.
* Allocation initiale balances (faucet, comptes étudiants) définie en config ou genesis builder.

---

## 10. Normes de sérialisation, hashing, signature

### 10.1 JSON canonique

UTF-8, clés triées, séparateurs compacts `(",", ":")`.

### 10.2 Champs signés transaction

Signer concat JSON canonique des champs : `from`, `script`, `premium`, `nonce`.

### 10.3 Hash tx

`tx_hash = sha256(canonical_tx_json_bytes)`.

### 10.4 Hash bloc (base pour PoW & signatures validateurs)

Construire objet bloc **sans** `validator_signatures`, `finalized`, `signers_frozen` puis double SHA-256.

> Tous les validateurs signent ce même `block_hash`.

### 10.5 Signature validateur bloc (ordre indifférent)

Chaque validateur signe `block_hash`. Map `validator_signatures` agrège pubkey→sig.

### 10.6 Application récompenses après quorum (freeze)

Balances finales = balances\_parent + block\_reward\_miner + premiums\_partagés(*signers\_frozen*). Reste premium selon `PREMIUM_REMAINDER_TARGET`.

### 10.7 Signatures tardives

Enregistrées dans `validator_signatures` (transparence) mais ignorées pour rémunération et quorum rétroactif.

---

## 11. Algorithmes clés

### 11.1 Calcul quorum

```python
import math
QUORUM = math.ceil(len(VALIDATOR_SET) * cfg.QUORUM_PERCENT / 100)
```

### 11.2 Handshake + preuve de rôle

```python
def probe_peer(peer, cfg, validator_set):
    # 1. status auto-reporté (non fiable)
    status = http_get(peer, "/status")
    pubkey_claim = status.get("pubkey")

    # 2. challenge
    nonce = os.urandom(32).hex()
    resp = http_post(peer, "/role_challenge", {"nonce": nonce, "expect_validator": True})
    pubkey = resp.get("pubkey", pubkey_claim)
    sig = resp.get("signature")

    # 3. vérifier signature
    if sig and verify_sig(pubkey, nonce, sig):
        is_validator = pubkey in validator_set
    else:
        is_validator = False

    return PeerInfo(host=peer.host, port=peer.port, pubkey=pubkey, is_validator=is_validator)
```

### 11.3 Ajout signature validateur (agrégation)

```python
def add_validator_sig(block_candidate, val_pub, val_sig):
    if val_pub not in VALIDATOR_SET:  # ne compte pas pour quorum
        return False
    if not verify_sig(val_pub, block_candidate.hash, val_sig):
        return False
    block_candidate.validator_signatures[val_pub] = val_sig
    return True
```

### 11.4 Vérifier finalisation

```python
def is_finalized(block_candidate, validator_set, quorum):
    count = sum(1 for v in validator_set if v in block_candidate.validator_signatures)
    return count >= quorum
```

### 11.5 Promotion bloc candidat → bloc finalisé (freeze set & rewards)

```python
def finalize_block(block_cand, validator_set, balances_parent, cfg):
    signers = [v for v in validator_set if v in block_cand.validator_signatures]
    if not signers:
        raise ValueError("no validator signatures")
    premiums_total = sum(tx.premium for tx in block_cand.transactions)
    share = premiums_total // len(signers)
    remainder = premiums_total % len(signers)
    balances = balances_parent.copy()
    # reward mineur
    balances[block_cand.header.miner] = balances.get(block_cand.header.miner,0) + cfg.BLOCK_REWARD
    # répartir premiums
    for v in signers:
        balances[v] = balances.get(v,0) + share
    if remainder and cfg.PREMIUM_REMAINDER_TARGET == "miner":
        balances[block_cand.header.miner] += remainder
    block_cand.balances = balances
    block_cand.signers_frozen = sorted(signers)
    block_cand.finalized = True
    return block_cand
```

### 11.6 Gestion signatures multiples / double validation

```python
def merge_signatures(local_block, incoming_sigs):
    for pub, sig in incoming_sigs.items():
        if pub not in local_block.validator_signatures:
            if verify_sig(pub, local_block.hash, sig):
                local_block.validator_signatures[pub] = sig
    return local_block
```

> Si `local_block.finalized` est déjà True, ne pas recalculer récompenses.

### 11.7 Reconstruction des branches (finalized)

Identique v4 : graph parent->children à partir de `/blocks/`.

---

## 12. API RPC Node (soumission, discovery & consensus)

| Méthode | Route              | Body                         | Retour                                               | Description               |
| ------- | ------------------ | ---------------------------- | ---------------------------------------------------- | ------------------------- |
| GET     | `/status`          | –                            | {pubkey, supports\_mining, supports\_validation,...} | Découverte soft           |
| POST    | `/role_challenge`  | {nonce, expect\_validator?}  | {pubkey, signature}                                  | Preuve de rôle            |
| POST    | `/tx`              | tx JSON                      | {status, tx\_hash}                                   | Soumettre une transaction |
| POST    | `/block_proposal`  | bloc candidat JSON           | {status}                                             | Reçu par validateurs      |
| POST    | `/block_signature` | {block\_hash, val\_pub, sig} | {status, sig\_count}                                 | Ajout signature           |
| POST    | `/block_finalized` | bloc finalisé JSON           | {status}                                             | Acceptation réseau        |
| GET     | `/pending`         | –                            | blocs candidats + sig count                          | Debug                     |

---

## 13. CLI Dev Tools

* `create-wallet --local-role miner|validator|both|full`
* `send-tx --wallet WALLET --script "let x=x+1" --premium 2`
* `propose-block` (mineur) → build + PoW + broadcast proposal
* `validator-sign --block HASH --wallet VALWALLET`
* `discover-peers` → lit peers.json, fait handshake, affiche rôles détectés
* `list-pending`
* `show-state`
* `reindex`

---

## 14. Journalisation & observabilité

* Log handshake rôle : peer, pubkey, validator? (y/n), signature OK/KO.
* Log signatures reçues (val\_pub, count/needed, quorum reached?).
* Log quorum atteint & finalisation (signers\_frozen list).
* Log blocs rejetés (PoW invalide, DSL fail, quorum insuffisant TTL, signature invalide...).
* Log ordre inclusion tx + premium pour illustrer anti-censure.

---

## 15. Tests (quorum, agrégation, preuve de rôle)

* Handshake valideur OK → node marque is\_validator True.
* Handshake peer non validateur → is\_validator False.
* Bloc candidat sans quorum → pas finalisé.
* Bloc finalisé avec signatures {A,B} → récompenses figées ; signature tardive C affichée seulement.
* Fork finalisé double → longest-finalized-chain wins.
* Anti-censure : tx premium haute vs basse, vérifier inclusion.

---

## 16. Sécurité minimale

* Signatures ECDSA obligatoires pour tx & validateurs.
* Preuve de rôle : challenge-signature avant d’accepter signature de bloc comme valideur comptant pour quorum.
* Quorum obligatoire avant finalisation.
* PoW vérifié avant signature validateur.
* Recalcul complet state/balances avant signature.
* Aucune modification balances via DSL.

---

## 17. Performance & limites

* ≤10 validateurs recommandé.
* \~1000 blocs acceptable.
* Tri premium O(n log n) OK.
* Handshake léger (nonce 32 octets) négligeable.

---

## 18. Paramètres pédagogiques recommandés

* 3 validateurs statiques.
* quorum 51 % → 2 signatures nécessaires.
* difficulté faible CPU.
* premiums visibles (explorer) pour incitations.

---

## 19. Checklist implémentation (ordre conseillé)

1. config.py + validators.json + peers.json
2. wallet.py (clés + signatures)
3. transaction.py (struct + hash + sig verify)
4. dsl.py (parse + exec + tests)
5. block.py (hash base, PoW, sigs validateurs, finalized)
6. mempool.py (tri premium / FIFO)
7. network.py (handshake rôle + broadcast + signature agrégation)
8. node.py (rôles miner/validator/both, state/balances mgmt, consensus)
9. explorer.py (forks, signatures, incitations)
10. tests intégrés (handshake, quorum, anti-censure, forks)

---

## 20. Grammaire DSL (rappel)

```
SCRIPT   := STMT (';' STMT)* ';'?
STMT     := 'let' IDENT '=' EXPR
EXPR     := TERM (('+'|'-') TERM)*
TERM     := IDENT | INT
IDENT    := [a-zA-Z_][a-zA-Z0-9_]*
INT      := [0-9]+
```

Erreur si variable inconnue (défaut = erreur → tx rejetée). Configurable.

---

## 21. Points d’arbitrage (figés v5)

| Sujet                      | Options                              | Reco                    | Décision            |
| -------------------------- | ------------------------------------ | ----------------------- | ------------------- |
| Address format             | pubkey hex / hash160                 | **pubkey hex**          | pubkey hex          |
| Premium lock               | mempool lock / **block deduct**      | **block deduct**        | block deduct        |
| Var inconnue DSL           | =0 / **erreur**                      | **erreur**              | erreur              |
| Refund DSL fail            | oui / non                            | **oui**                 | oui                 |
| Tri des tx                 | FIFO / **premium**                   | **premium**             | premium             |
| Part premium reste         | mineur / burn                        | **mineur**              | mineur              |
| TTL bloc candidat          | secs / inf                           | **120s**                | 120s                |
| Signatures ordre           | ordonné / **non-ordonné**            | **non-ordonné**         | non-ordonné         |
| Signatures tardives payées | oui / **non**                        | **non**                 | non                 |
| Peers contiennent rôles    | oui / **non**                        | **non**                 | non                 |
| Preuve de rôle             | facultatif / **challenge-signature** | **challenge-signature** | challenge-signature |

---

## 22. Résumé exécutif (README)

Blockchain éducative Python combinant **Preuve de Travail + Quorum de Validateurs** avec signatures agrégées non ordonnées et **preuve cryptographique de rôle validateur à runtime**. Résilience à la censure via ordonnancement par prime, DSL global state, balances protégées, récompenses incitatives (mineur + validateurs signataires), forks gérés par stockage par bloc et règle longest-finalized-chain. Explorer web intégré.

---

### Fin du document (v5)

Pour toute évolution, incrémenter version et documenter les changements.

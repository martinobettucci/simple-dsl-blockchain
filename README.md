# Blockchain Programmable Pédagogique

Ce projet propose une **blockchain simplifiée programmable** par mini-DSL, pensée pour la pédagogie (cours, TP, démo) autour des concepts fondamentaux : minage PoW, wallets, state global, récompenses, propagation réseau, explorer web, etc.

## 🚀 Fonctionnalités principales

- **Programmabilité** : chaque transaction embarque un script DSL qui modifie un état global partagé
- **Mining PoW** : consensus par preuve de travail (difficulté paramétrable)
- **Wallets** : chaque utilisateur possède une clé publique/privée ECDSA
- **Balances** : gestion isolée des soldes individuels (premium, reward, validation)
- **State global** : modifié uniquement par les scripts, totalement séparé des balances
- **Mempool** : transactions en attente de minage
- **Validation/réseau** : propagation, validation blocks, gestion forks (longest chain wins)
- **Explorer web** : visualisation de la chaîne, des blocks, du state, des balances, des transactions

## 🛠️ Structure du projet

```

blockchain\_demo/
├── node.py         # Node principal (mempool, mining, RPC, explorer)
├── wallet.py       # Wallets, signature, balances
├── dsl.py          # DSL parser et exécution sur le state global
├── transaction.py  # Structure, validation des transactions
├── block.py        # Structure, validation, PoW des blocks
├── mempool.py      # File de transactions en attente
├── network.py      # Propagation blocks/tx, gestion peers
├── explorer.py     # API web + UI explorer (Flask/Jinja2)
├── static/         # Fichiers frontend explorer (HTML, CSS, JS)
├── state.json      # Snapshot du state global
└── balances.json   # Snapshot balances wallets

````

## 🧩 Architecture fonctionnelle

- **Node** : gère toute la logique, l’état, l’API, le minage, la validation, l’exécution des scripts et l’explorer web.
- **Mempool** : conserve les transactions valides non minées.
- **Mining** : chaque bloc regroupe 3 transactions, exécute leurs scripts, met à jour l’état, récompense le mineur, puis diffuse le block.
- **Validation** : les validateurs vérifient PoW, signatures, cohérence du state et des balances, se partagent les premiums.
- **Explorer** : interface web permettant de naviguer dans la blockchain, d’afficher le state, les soldes, l’historique.

## 📄 Structures de données

### Transactions
```json
{
  "from": "public_key_hex",
  "script": "let x = x + 1; let y = x - 2;",
  "premium": 2,
  "signature": "hex...",
  "nonce": 42
}
````

### Blocks

```json
{
  "header": {
    "prev_hash": "...",
    "nonce": ...,
    "timestamp": ...,
    "miner": "public_key_hex"
  },
  "transactions": [ ... ],      // 3 tx max
  "state": {...},               // State global post-exécution
  "balances": {...}             // Balances post-exécution
}
```

### State & Balances

```json
{
  "state": {
    "counter": 42,
    "flag": 1
  },
  "balances": {
    "0xABC...": 100,
    "0xDEF...": 78
  }
}
```

## 📝 Règles de gestion

* **DSL** : instructions d’affectation globale (`let x = ...;`) et opérations arithmétiques de base (+, -). **Aucune interaction avec les balances.**
* **Balances** : seules les récompenses, premiums, et validations modifient les soldes. Les scripts ne peuvent pas le faire.
* **Minage** : 3 transactions par bloc, exécution séquentielle, state snapshot, reward au mineur, premiums partagés validateurs.
* **Validation** : PoW, signature, exécution DSL, cohérence du state et des balances.
* **Gestion des forks** : chaque node conserve la plus longue chaîne (“longest chain wins”).

## 🔒 Sécurité

* Signature ECDSA obligatoire pour toute transaction.
* Solde du wallet vérifié avant entrée dans le mempool (premium payé d’avance).
* Rollback complet si une erreur d’exécution DSL se produit lors du minage.
* Vérification systématique des premiums pour éviter toute double dépense.
* Aucun script ne peut modifier les soldes.

## 🌍 API & Explorer Web

### Routes minimales

* `/chain` : liste des blocks
* `/block/<hash>` : détails d’un block
* `/state` : état global courant
* `/tx/<hash>` : détail d’une transaction
* `/address/<pubkey>` : solde et historique
* `/explorer` : interface web

## ⚡ Installation & lancement

1. **Cloner le projet**

   ```
   git clone https://github.com/martinobettucci/simple-dsl-blockchain.git
   cd blockchain_demo
   ```

2. **Installer les dépendances**

   ```
   pip install flask ecdsa
   ```

3. **Démarrer un node**

   ```
   python node.py
   ```

4. **Accéder à l’explorer**

   * Aller sur [http://localhost:5000/explorer](http://localhost:5000/explorer)

## 👥 Contribuer

* Forkez ce repo, proposez vos PRs !
* Lisez la spec (README et fichiers `.py`)
* Respectez l’isolation state/balances et la simplicité du DSL

## 📚 Auteurs / Contact

* [Martino Bettucci](https://www.linkedin.com/in/martinobettucci/)
* Projet pédagogique P2Enjoy SAS

## TODO

* [ ] Implémenter chaque module (voir commentaires TODO dans chaque fichier)
* [ ] Finaliser la logique du mempool et du minage séquentiel
* [ ] Finaliser l’API explorer web
* [ ] Rédiger des tests unitaires
* [ ] Ajouter des exemples de scripts DSL et d’utilisation

---

*Ce projet est un démonstrateur open source, conçu pour l’enseignement et l’expérimentation.*

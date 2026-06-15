# CLAUDE.md — Conventions du projet

## RÈGLE DE LIVRAISON (obligatoire) : test unitaire **+** preuve vidéo

Tout **développement ou correctif** (feature *ou* fix), dans **tous les dépôts de la session**,
n'est considéré **terminé** que s'il est accompagné des **deux** livrables suivants :

1. **Un test unitaire / automatisé** (pytest) qui couvre la fonctionnalité ajoutée ou le bug
   corrigé (test de non-régression). Il doit passer : `python -m pytest -q`.
2. **Un test enregistré en vidéo** (Playwright) qui **démontre la fonctionnalité ou le fix dans
   l'application réelle**, puis est **envoyé à l'utilisateur** (outil `SendUserFile`).

Ne jamais clore une tâche de dev/fix sans **ces deux preuves**. Pour un *fix*, la vidéo doit montrer
le comportement corrigé (idéalement le scénario qui échouait auparavant, désormais fonctionnel).

## Comment produire la preuve vidéo

Playwright est installé :

```bash
pip install playwright && python -m playwright install chromium
```

Démarrer la démo complète (archive, mineur, validateurs, nœud RPC, explorer, wallet) :

```bash
python genesys.py
```

Enregistrer le **panorama** de toutes les fonctionnalités (sort un `.webm`, chemin imprimé) :

```bash
python tools/record_panorama.py            # explorer -> monitor du nœud -> wallet
```

Pour un **fix ciblé**, écrire un court script Playwright sous `tools/` (réutiliser `caption()` et
`scroll_through()` de `tools/record_panorama.py`) qui reproduit le scénario et démontre la
correction, puis envoyer le `.webm` à l'utilisateur.

> Les vidéos sont des **livrables envoyés à l'utilisateur**, pas des artefacts versionnés : elles
> sont ignorées par git (voir `.gitignore`). Ne pas committer de `.webm`.

## Repères techniques

- Tests offline déterministes par défaut ; les tests qui ouvrent des sockets sont marqués
  `network` / `slow` (voir `pytest.ini`).
- Le navigateur Playwright tourne en **headless**, la vidéo est au format **WebM**.
- URLs de la démo : explorer `http://127.0.0.1:8600`, wallet `http://127.0.0.1:8700`,
  monitoring par nœud `http://127.0.0.1:<port>/monitor`, nœud RPC `:9006`.
- genesys imprime la clé privée du *user* de démo (à coller dans la wallet) ; le recorder la lit
  depuis `runtime/wallets/user.json`.

## Commandes utiles

| Action            | Commande                                   |
| ----------------- | ------------------------------------------ |
| Tests             | `python -m pytest -q`                       |
| Démo (mesh)       | `python genesys.py`  (arrêt : `Ctrl-C`)    |
| Vidéo panorama    | `python tools/record_panorama.py`          |

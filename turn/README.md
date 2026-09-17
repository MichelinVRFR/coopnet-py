# Simple TURN server (Go + Pion)

Petit serveur TURN minimal pour accompagner le serveur CoopNet Python.

## Prérequis

- Go 1.21+ (déjà installé chez toi)

## Lancer le serveur

```bash
cd turn

# Première fois seulement
go mod tidy

# Lancer (remplace 203.0.113.10 par l'IP publique de ta machine / VPS)
go run . --public-ip 203.0.113.10 --port 3478 --user coopnet --pass coopnetpass
```

Ou compiler un binaire :

```bash
go build -o turnserver .
./turnserver --public-ip TON_IP_PUBLIQUE
```

## Options

| Flag          | Défaut       | Description                          |
|---------------|--------------|--------------------------------------|
| `--public-ip` | (vide)       | **IP publique** de ton serveur       |
| `--port`      | 3478         | Port UDP                             |
| `--realm`     | coopnet      | Realm TURN                           |
| `--user`      | coopnet      | Nom d'utilisateur                    |
| `--pass`      | coopnetpass  | Mot de passe                         |

## Relier au serveur Python (coopnet-py)

Crée un fichier `turn-servers.cfg` à la racine du projet Python :

```
# host:username:password:port
TON_IP_PUBLIQUE:coopnet:coopnetpass:3478
```

Exemple :

```
203.0.113.10:coopnet:coopnetpass:3478
```

Puis lance le serveur Python normalement. Il enverra automatiquement ce TURN aux clients.

## Ports à ouvrir

- UDP 3478 (et éventuellement une plage de ports de relay si tu en configures plus tard)

## Notes

- Ce serveur est volontairement simple (long-term credentials).
- Pour de la vraie prod, Coturn reste plus complet, mais celui-ci est largement suffisant pour tester et pour un usage perso / amis.

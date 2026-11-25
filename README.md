# MCP Rmes

A [Model Context Protocol](https://modelcontextprotocol.io) server that puts INSEE's **RMeS** ontology — statistical metadata: definitions, nomenclatures, quality reports — in front of an LLM, over the same SPARQL endpoint a human would query by hand.

<!-- ─── BETA BADGE ───────────────────────────────────────────────────────── -->
![Status: BETA](https://img.shields.io/badge/status-BETA-yellow?style=for-the-badge)
[![CI](https://github.com/Mirlon382/McpRmes/actions/workflows/ci.yml/badge.svg)](https://github.com/Mirlon382/McpRmes/actions/workflows/ci.yml)
[![License: Etalab 2.0](https://img.shields.io/badge/licence-Etalab%202.0-blue)](LICENSE)

> **⚠️ BETA — NOT PRODUCTION READY**
> This project is still in beta. It should not be considered a finished or officially supported product from INSEE.

[Version française ci-dessous](#en-français).

**It holds no figures.** RMeS describes what the statistics *mean* (what "Extraction de houille" is, which CPF products match a NAF division, which quality report covers which operation), not what they *measure*. A model that needs a number is looking in the wrong store.

## What it gives a model

Three tools, all read-only:

| Tool | Question it answers | Costs |
| --- | --- | --- |
| `search_rmes_graphs` | Which named graphs exist, grouped into 12 families plus a catch-all, with triple counts | One cached listing of the whole store |
| `describe_rmes_resource` | Every property attached to one resource URI, in both directions | One query, bounded by its own budget |
| `run_rmes_sparql` | Anything else, as free SPARQL | A query the model writes |

One run of the listing, for scale: **711 graphs, 4,476,969 triples**, of which 645 are quality reports (163,220 triples) and 42 are nomenclatures (1,119,890 triples — NAF, CPF, PCS, COICOP, EAP/EMB, plus the correspondence tables between versions).

Refusals are decided before anything is sent to INSEE: `INSERT`, `DELETE`, `LOAD`, `CLEAR`, `DROP`, `CREATE`, `ADD`, `MOVE`, `COPY` and federated `SERVICE` calls are rejected, and a query with no `LIMIT` gets one appended (200 rows by default, reported back as `limit_added`).

## Why: five things it is actually good at

Every example below was run against the live endpoint while writing this file; the outputs are the ones the server returned.

**1. "Which graph should I even be querying?"** — the store has 711 named graphs, so the model asks first:

```json
{"graph_category": "nomenclatures"}
```

```text
graph names from that call (42 graphs):
cj, coicop1998, coicop2016, coicop2018, cpfr1, cpfr2, cpfr21, eap2017 … eap2025,
emb2018 … emb2026, na08, na2008, na73, naf, naf2025, nafr1, nafr2, nafr2-cpfr21,
nes1994, nes1994-nafr1, pcs1982, pcs2003, pcs2020, pcsese1982 … pcsese2017
```

**2. "What does code 05 mean?"** — one resource, every property, both directions:

```json
{"resource_uri": "http://id.insee.fr/codes/naf2025/division/05",
 "graph_uri": "http://rdf.insee.fr/graphes/codes/naf2025"}
```

```text
14 properties, among them:
  outgoing  prefLabel   Extraction de houille et de lignite
  outgoing  prefLabel   Mining of coal and lignite
  outgoing  notation    05
  outgoing  inScheme    http://id.insee.fr/codes/naf2025/naf
  outgoing  narrower    http://id.insee.fr/codes/naf2025/groupe/05.1
```

**3. "Find the codes whose label mentions a word."** — free SPARQL, restricted to one graph:

```sparql
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?code ?label WHERE {
  GRAPH <http://rdf.insee.fr/graphes/codes/naf2025> {
    ?code skos:prefLabel ?label .
    FILTER(lang(?label) = "fr")
    FILTER(CONTAINS(LCASE(STR(?label)), "extraction"))
  }
} LIMIT 5
```

```text
http://id.insee.fr/codes/naf2025/division/05 | Extraction de houille et de lignite
http://id.insee.fr/codes/naf2025/division/06 | Extraction d’hydrocarbures
http://id.insee.fr/codes/naf2025/division/07 | Extraction de minerais métalliques
http://id.insee.fr/codes/naf2025/groupe/05.1   | Extraction de houille
http://id.insee.fr/codes/naf2025/groupe/05.2   | Extraction de lignite
```

**4. "Which product classification matches this activity?"** — the cross-classification tables are themselves graphs (`nafr2-cpfr21`, `pcsese1982-pcsese2003`, …), joined through `xkos:sourceConcept` / `xkos:targetConcept`:

```sparql
PREFIX xkos: <http://rdf-vocabulary.ddialliance.org/xkos#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?cpf ?label WHERE {
  GRAPH <http://rdf.insee.fr/graphes/codes/nafr2-cpfr21> {
    ?a xkos:sourceConcept <http://id.insee.fr/codes/nafr2/division/05> ;
       xkos:targetConcept ?cpf
  }
  GRAPH <http://rdf.insee.fr/graphes/codes/cpfr21> {
    ?cpf skos:prefLabel ?label . FILTER(lang(?label) = "fr")
  }
}
```

```text
05 | Houille et lignite
```

**5. "Is this operation's quality documented, and where?"** — quality reports are one graph each, linked to the operation they cover:

```sparql
PREFIX sdmx-mm: <http://www.w3.org/ns/sdmx-mm#>
SELECT ?report ?operation WHERE {
  GRAPH <http://rdf.insee.fr/graphes/qualite/rapport/2278> {
    ?report sdmx-mm:target ?operation
  }
}
```

```text
http://id.insee.fr/qualite/rapport/2278 -> http://id.insee.fr/operations/operation/s2277
```

And when a model tries to write:

```text
[INVALID_QUERY] Operation de mise a jour SPARQL refusee (DELETE) : ce serveur est en
lecture seule. Utilise SELECT, ASK, CONSTRUCT ou DESCRIBE.
```

## How to run it

### Locally

You need [uv](https://docs.astral.sh/uv/) — it installs the right Python (3.12) itself:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```bash
git clone https://github.com/Mirlon382/McpRmes.git
cd McpRmes
uv sync
uv run mcpserver
```

It listens on `http://0.0.0.0:8000`, MCP endpoint at `/mcp`. Startup prints:

```text
INFO | mcpserver.lifespan.rmes | SPARQL client initialized
INFO | mcp.server.streamable_http_manager | StreamableHTTP session manager started
INFO | uvicorn.error | Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

Check it is alive without a model or a browser — this lists the tools the server publishes:

```bash
npx -y @modelcontextprotocol/inspector --cli http://127.0.0.1:8000/mcp --method tools/list
```

Drop `--cli` and the same command opens the Inspector's web UI, where you can call the tools by hand.

### In a container

```bash
docker build -t mcprmes .
docker run --rm -p 8000:8000 mcprmes
```

With podman, add `--format docker`: the OCI image format it defaults to cannot store a `HEALTHCHECK`, and the build silently drops the one in the Dockerfile.

```bash
podman build --format docker -t mcprmes .
podman run --rm -p 8000:8000 mcprmes
podman inspect --format '{{.State.Health.Status}}' <container>   # → healthy
```

The image runs as uid 1000, installs no dev dependencies, and its healthcheck opens a TCP connection rather than sending an HTTP request — the MCP endpoint answers `400` without a session handshake, so an HTTP probe would report a healthy server as broken.

`k8s/manifest.yaml` has a Service, a Deployment and an Ingress, and it is a template rather than a deployment: the hostname (`mcprmes.example.com`) and the image (`ghcr.io/<owner>/mcprmes:latest`) are placeholders, and the hostname has to match `ALLOWED_HOSTS` in the Deployment. `ALLOWED_HOSTS` is the one setting that cannot be left at its code default: the manifest narrows it to a single hostname while the code ships `["*"]`. `TRUSTED_PROXY_HOSTS` is the second: it decides whose `X-Forwarded-For` is believed, so pointing it at the Ingress controller's pod network keeps the rate limiter identifying callers individually without trusting anything that can reach the pod directly.

### Configuration

Copy `.env.example` to `.env`; every variable is optional and the file carries the shipped default. Lists are JSON, never comma-separated: `ALLOWED_HOSTS=["a.example.com","b.example.com"]`.

| Variable | Default | What it does |
| --- | --- | --- |
| `MCP_HOST` / `MCP_PORT` | `0.0.0.0` / `8000` | Where uvicorn binds |
| `ALLOWED_HOSTS` | `["*"]` | Hostnames checked against the `Host` header — `*` disables the check |
| `ALLOWED_ORIGINS` | `[]` | Browser origins; empty rejects every cross-origin call |
| `TRUSTED_PROXY_HOSTS` | `["127.0.0.1"]` | Peers whose `X-Forwarded-For` is believed, for rate-limit identity |
| `RMES_SPARQL_ENDPOINT_URL` | `https://rdf.insee.fr/sparql` | The store being queried |
| `RMES_GRAPH_CACHE_TTL_SECONDS` | `3600.0` | How long the (expensive) graph listing is reused |
| `RMES_QUERY_DEFAULT_MAX_ROWS` / `RMES_QUERY_MAX_ROWS` | `200` / `2000` | Rows appended when a query has no `LIMIT`, and the ceiling the model may ask for |
| `RMES_QUERY_DEFAULT_TIMEOUT_SECONDS` / `RMES_QUERY_MAX_TIMEOUT_SECONDS` | `20.0` / `60.0` | Same pair, for query timeouts |
| `RATE_LIMIT_MAX_REQUESTS` / `RATE_LIMIT_WINDOW_MINUTES` | `100` / `1` | Per-client sliding window |
| `LOG_LEVEL` | `INFO` | Root logger level |

The rest (`RMES_GRAPH_LISTING_*`, `RMES_RESOURCE_QUERY_*`, `SERVER_NAME`, `INSTRUCTIONS`) are in `.env.example` with the same defaults. The four `RMES_QUERY_*` budgets are what the tool schema advertises, so changing one changes what the model sees, after a restart. A default above its maximum is refused at startup.

### Development

```bash
uv run pytest -q          # 82 tests
uv run ruff check .       # lint
uv run ruff format .      # format
```

The suite never calls INSEE: `test_graph_store_service.py` runs the service against an `httpx.MockTransport`, so timeouts, `400`, `503` and malformed answers are exercised without the network. `test_query_shaping.py` pins what is refused, what limit is forced, and which `PREFIX`/`BASE` forms still parse; `test_graph_taxonomy.py` pins the family rules; `test_tools.py` reads back the schema a client actually receives.

`.github/workflows/ci.yml` runs those three commands on every push and pull request, against a `uv.lock` it refuses to re-resolve (`uv sync --locked`), plus a container build that proves the Dockerfile still works. Nothing in CI reaches the network on purpose.

### What it deliberately does not do

- **No figures.** RMES has no data series; a model after numbers needs another source.
- **No authentication.** Anyone who can reach the port can query. `ALLOWED_HOSTS=["*"]` and an empty `ALLOWED_ORIGINS` are development defaults: set both before exposing this beyond localhost.
- **No persistence.** The graph listing cache and the rate limiter live in the process; restarting forgets them, and several replicas each keep their own.
- **No writes.** The endpoint is public and read-only, and the server refuses update operations itself rather than trusting that.

### Licence

Released under the [Licence Ouverte / Open Licence 2.0](LICENSE) (Etalab), the French licence for public information. It grants reuse — commercial included — on condition of attribution and of not suggesting official endorsement. The full text in [`LICENSE`](LICENSE) is authoritative.

This repository is not an INSEE product: it is an independent client of INSEE's public RDF store, and the licence above covers the code here, not the RMeS data, which stays under INSEE's own terms.

---

# En français

Un serveur [Model Context Protocol](https://modelcontextprotocol.io) qui place l'ontologie **RMeS** de l'INSEE — métadonnées statistiques : définitions, nomenclatures, rapports qualité — devant un LLM, sur le même endpoint SPARQL qu'un humain interrogerait à la main.

> **⚠️ BÊTA — PAS PRÊT POUR LA PRODUCTION**
> Ce projet est encore en bêta et ne doit pas être considéré comme un produit fini ou officiellement supporté par l'INSEE.

**Il ne contient aucun chiffre.** RMeS décrit ce que les statistiques *veulent dire* (ce qu'est « Extraction de houille », quels produits CPF correspondent à une division NAF, quel rapport qualité couvre quelle opération), pas ce qu'elles *mesurent*. Un modèle qui cherche un chiffre se trompe d'entrepôt.

## Ce que le serveur donne à un modèle

Trois tools, tous en lecture seule :

| Tool | Question à laquelle il répond | Coût |
| --- | --- | --- |
| `search_rmes_graphs` | Quels graphes nommés existent, groupés en 12 familles plus une catégorie « autre », avec le nombre de triplets | Une liste du store entier, mise en cache |
| `describe_rmes_resource` | Toutes les propriétés d'une URI de ressource, dans les deux sens | Une requête, avec son propre budget |
| `run_rmes_sparql` | Tout le reste, en SPARQL libre | Une requête écrite par le modèle |

Un appel du listing, pour l'échelle : **711 graphes, 4 476 969 triplets**, dont 645 rapports qualité (163 220 triplets) et 42 nomenclatures (1 119 890 triplets — NAF, CPF, PCS, COICOP, EAP/EMB, plus les tables de correspondance entre versions).

Les refus sont décidés avant tout envoi à l'INSEE : `INSERT`, `DELETE`, `LOAD`, `CLEAR`, `DROP`, `CREATE`, `ADD`, `MOVE`, `COPY` et les requêtes fédérées `SERVICE` sont rejetés, et une requête sans `LIMIT` en reçoit un (200 lignes par défaut, signalé dans la réponse par `limit_added`).

## Pourquoi : cinq cas d'usage concrets

Tous les exemples ci-dessous ont été exécutés contre l'endpoint réel au moment d'écrire ce fichier ; les sorties sont celles renvoyées par le serveur.

**1. « Quel graphe dois-je interroger ? »** — le store contient 711 graphes nommés, le modèle demande donc d'abord :

```json
{"graph_category": "nomenclatures"}
```

```text
noms de graphes renvoyés par cet appel (42 graphes) :
cj, coicop1998, coicop2016, coicop2018, cpfr1, cpfr2, cpfr21, eap2017 … eap2025,
emb2018 … emb2026, na08, na2008, na73, naf, naf2025, nafr1, nafr2, nafr2-cpfr21,
nes1994, nes1994-nafr1, pcs1982, pcs2003, pcs2020, pcsese1982 … pcsese2017
```

**2. « Que signifie le code 05 ? »** — une ressource, toutes ses propriétés, dans les deux sens :

```json
{"resource_uri": "http://id.insee.fr/codes/naf2025/division/05",
 "graph_uri": "http://rdf.insee.fr/graphes/codes/naf2025"}
```

```text
14 properties, among them:
  outgoing  prefLabel   Extraction de houille et de lignite
  outgoing  prefLabel   Mining of coal and lignite
  outgoing  notation    05
  outgoing  inScheme    http://id.insee.fr/codes/naf2025/naf
  outgoing  narrower    http://id.insee.fr/codes/naf2025/groupe/05.1
```

**3. « Quels codes ont un libellé contenant un mot ? »** — SPARQL libre, restreint à un graphe :

```sparql
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?code ?label WHERE {
  GRAPH <http://rdf.insee.fr/graphes/codes/naf2025> {
    ?code skos:prefLabel ?label .
    FILTER(lang(?label) = "fr")
    FILTER(CONTAINS(LCASE(STR(?label)), "extraction"))
  }
} LIMIT 5
```

```text
http://id.insee.fr/codes/naf2025/division/05 | Extraction de houille et de lignite
http://id.insee.fr/codes/naf2025/division/06 | Extraction d’hydrocarbures
http://id.insee.fr/codes/naf2025/division/07 | Extraction de minerais métalliques
http://id.insee.fr/codes/naf2025/groupe/05.1   | Extraction de houille
http://id.insee.fr/codes/naf2025/groupe/05.2   | Extraction de lignite
```

**4. « Quelle classification de produits correspond à cette activité ? »** — les tables de correspondance sont elles-mêmes des graphes (`nafr2-cpfr21`, `pcsese1982-pcsese2003`, …), reliés par `xkos:sourceConcept` / `xkos:targetConcept` :

```sparql
PREFIX xkos: <http://rdf-vocabulary.ddialliance.org/xkos#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?cpf ?label WHERE {
  GRAPH <http://rdf.insee.fr/graphes/codes/nafr2-cpfr21> {
    ?a xkos:sourceConcept <http://id.insee.fr/codes/nafr2/division/05> ;
       xkos:targetConcept ?cpf
  }
  GRAPH <http://rdf.insee.fr/graphes/codes/cpfr21> {
    ?cpf skos:prefLabel ?label . FILTER(lang(?label) = "fr")
  }
}
```

```text
05 | Houille et lignite
```

**5. « La qualité de cette opération est-elle documentée, et où ? »** — chaque rapport qualité est un graphe, relié à l'opération qu'il couvre :

```sparql
PREFIX sdmx-mm: <http://www.w3.org/ns/sdmx-mm#>
SELECT ?report ?operation WHERE {
  GRAPH <http://rdf.insee.fr/graphes/qualite/rapport/2278> {
    ?report sdmx-mm:target ?operation
  }
}
```

```text
http://id.insee.fr/qualite/rapport/2278 -> http://id.insee.fr/operations/operation/s2277
```

Et quand un modèle tente d'écrire :

```text
[INVALID_QUERY] Operation de mise a jour SPARQL refusee (DELETE) : ce serveur est en
lecture seule. Utilise SELECT, ASK, CONSTRUCT ou DESCRIBE.
```

## Comment le lancer

### En local

Il faut [uv](https://docs.astral.sh/uv/) — il installe lui-même la bonne version de Python (3.12) :

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```bash
git clone https://github.com/Mirlon382/McpRmes.git
cd McpRmes
uv sync
uv run mcpserver
```

Le serveur écoute sur `http://0.0.0.0:8000`, endpoint MCP sur `/mcp`. Au démarrage :

```text
INFO | mcpserver.lifespan.rmes | SPARQL client initialized
INFO | mcp.server.streamable_http_manager | StreamableHTTP session manager started
INFO | uvicorn.error | Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

Pour vérifier qu'il répond, sans modèle ni navigateur — la commande liste les tools publiés :

```bash
npx -y @modelcontextprotocol/inspector --cli http://127.0.0.1:8000/mcp --method tools/list
```

Sans `--cli`, la même commande ouvre l'interface web de l'Inspector, où les tools s'appellent à la main.

### En conteneur

```bash
docker build -t mcprmes .
docker run --rm -p 8000:8000 mcprmes
```

Avec podman, ajoutez `--format docker` : le format d'image OCI qu'il utilise par défaut ne sait pas stocker de `HEALTHCHECK`, et le build abandonne silencieusement celui du Dockerfile.

```bash
podman build --format docker -t mcprmes .
podman run --rm -p 8000:8000 mcprmes
podman inspect --format '{{.State.Health.Status}}' <container>   # → healthy
```

L'image tourne avec l'uid 1000, n'installe aucune dépendance de développement, et son healthcheck ouvre une connexion TCP plutôt que d'envoyer une requête HTTP — l'endpoint MCP répond `400` sans poignée de main de session, donc une sonde HTTP déclarerait cassé un serveur sain.

`k8s/manifest.yaml` fournit un Service, un Deployment et un Ingress, sous forme de gabarit et non de déploiement : le nom d'hôte (`mcprmes.example.com`) et l'image (`ghcr.io/<owner>/mcprmes:latest`) sont des valeurs à remplacer, et le nom d'hôte doit correspondre à `ALLOWED_HOSTS` dans le Deployment. `ALLOWED_HOSTS` est le réglage qu'on ne peut pas laisser à sa valeur par défaut : le manifeste le restreint à un seul nom d'hôte là où le code livre `["*"]`. `TRUSTED_PROXY_HOSTS` est le second : il décide de quel `X-Forwarded-For` on croit l'en-tête, donc le pointer sur le réseau de pods du contrôleur d'Ingress permet au rate limiter d'identifier chaque appelant sans faire confiance à ce qui atteint le pod directement.

### Configuration

Copiez `.env.example` en `.env` ; toutes les variables sont optionnelles et le fichier porte les valeurs par défaut livrées. Les listes sont du JSON, jamais séparé par des virgules : `ALLOWED_HOSTS=["a.example.com","b.example.com"]`.

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `MCP_HOST` / `MCP_PORT` | `0.0.0.0` / `8000` | Adresse et port d'écoute |
| `ALLOWED_HOSTS` | `["*"]` | Noms d'hôtes comparés à l'en-tête `Host` — `*` désactive le contrôle |
| `ALLOWED_ORIGINS` | `[]` | Origines navigateur ; vide refuse tout appel cross-origin |
| `TRUSTED_PROXY_HOSTS` | `["127.0.0.1"]` | Pairs dont le `X-Forwarded-For` est cru, pour identifier le client du rate limit |
| `RMES_SPARQL_ENDPOINT_URL` | `https://rdf.insee.fr/sparql` | Le store interrogé |
| `RMES_GRAPH_CACHE_TTL_SECONDS` | `3600.0` | Durée de réutilisation du listing des graphes (coûteux) |
| `RMES_QUERY_DEFAULT_MAX_ROWS` / `RMES_QUERY_MAX_ROWS` | `200` / `2000` | Lignes ajoutées quand la requête n'a pas de `LIMIT`, et plafond demandable par le modèle |
| `RMES_QUERY_DEFAULT_TIMEOUT_SECONDS` / `RMES_QUERY_MAX_TIMEOUT_SECONDS` | `20.0` / `60.0` | Même couple, pour les timeouts |
| `RATE_LIMIT_MAX_REQUESTS` / `RATE_LIMIT_WINDOW_MINUTES` | `100` / `1` | Fenêtre glissante par client |
| `LOG_LEVEL` | `INFO` | Niveau du logger racine |

Les autres (`RMES_GRAPH_LISTING_*`, `RMES_RESOURCE_QUERY_*`, `SERVER_NAME`, `INSTRUCTIONS`) sont dans `.env.example` avec les mêmes défauts. Les quatre budgets `RMES_QUERY_*` sont ceux que le schéma des tools annonce : en changer un change ce que le modèle voit, après redémarrage. Un défaut supérieur à son maximum empêche le démarrage.

### Développement

```bash
uv run pytest -q          # 82 tests
uv run ruff check .       # lint
uv run ruff format .      # format
```

La suite n'appelle jamais l'INSEE : `test_graph_store_service.py` exécute le service contre un `httpx.MockTransport`, donc timeouts, `400`, `503` et réponses malformées sont couverts sans réseau. `test_query_shaping.py` fige ce qui est refusé, la limite ajoutée et les formes `PREFIX`/`BASE` qui restent analysables ; `test_graph_taxonomy.py` fige les règles de familles ; `test_tools.py` relit le schéma que reçoit réellement un client.

`.github/workflows/ci.yml` lance ces trois commandes à chaque push et pull request, contre un `uv.lock` qu'il refuse de résoudre à nouveau (`uv sync --locked`), plus un build de conteneur qui vérifie que le Dockerfile fonctionne encore. Rien dans la CI n'atteint le réseau volontairement.

### Ce qu'il ne fait volontairement pas

- **Aucun chiffre.** RMeS n'a pas de séries ; un modèle qui cherche des nombres doit s'adresser ailleurs.
- **Aucune authentification.** Quiconque atteint le port peut interroger. `ALLOWED_HOSTS=["*"]` et `ALLOWED_ORIGINS=[]` sont des défauts de développement : à changer tous les deux avant d'exposer le serveur au-delà de localhost.
- **Aucune persistance.** Le cache du listing et le rate limiter vivent dans le processus ; un redémarrage les oublie, et plusieurs replicas gardent chacun le leur.
- **Aucune écriture.** L'endpoint est public et en lecture seule, et le serveur refuse lui-même les opérations de mise à jour plutôt que de compter dessus.

### Licence

Publié sous [Licence Ouverte / Open Licence 2.0](LICENSE) (Etalab), la licence française pour l'information publique. Elle autorise la réutilisation — y compris commerciale — à condition de mentionner la source et de ne pas suggérer une caution officielle. Le texte intégral dans [`LICENSE`](LICENSE) fait foi.

Ce dépôt n'est pas un produit de l'INSEE : c'est un client indépendant de son entrepôt RDF public, et la licence ci-dessus couvre le code présent ici, pas les données RMeS, qui restent soumises aux conditions de l'INSEE.

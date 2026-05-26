# RESTful Advanced RAG

Context-first RAG experiments split into three independent stacks:

- `docker-compose.lightrag.yml` - ready-made LightRAG server with its own pgvector.
- `docker-compose.ragflow.yml` - ready-made RAGFlow sandbox.
- `docker-compose.haystack.yml` - custom MVP on Haystack + Hayhooks + pgvector.

The Haystack service does not generate final answers. It indexes documents and returns retrieved
context chunks through Hayhooks REST endpoints.

## Haystack MVP

Hayhooks auto-loads pipeline wrappers from `haystack/pipelines/` and exposes each folder as
`/{pipeline_name}/run`.

```bash
cp .env.haystack.example .env.haystack
docker compose --env-file .env.haystack -f docker-compose.haystack.yml up -d --build --wait
```

Open Hayhooks at `http://localhost:1416`.

The Docker image installs through PDM from `pyproject.toml` and `pdm.lock`; there is no separate
`requirements.txt`.

Available endpoints:

```text
POST /indexing/run
POST /retrieve/run
POST /documents/run
```

Index text. Because the same endpoint also supports file uploads, Hayhooks exposes it as
`multipart/form-data`:

```bash
curl -X POST http://localhost:1416/indexing/run \
  -F 'shop_id=shop_a' \
  -F 'document_id=delivery_policy' \
  -F 'text=We deliver to Russia by courier.'
```

Retrieve context:

```bash
curl -X POST http://localhost:1416/retrieve/run \
  -H 'Content-Type: application/json' \
  -d '{
    "shop_id": "shop_a",
    "query": "Есть доставка в Россию?",
    "top_k": 5,
    "mode": "vector"
  }'
```

Delete a document:

```bash
curl -X POST http://localhost:1416/documents/run \
  -H 'Content-Type: application/json' \
  -d '{
    "shop_id": "shop_a",
    "document_id": "delivery_policy",
    "action": "delete"
  }'
```

For local development with only pgvector in Docker and Hayhooks in the PDM environment:

```bash
pdm sync -G dev
pdm dev
```

`pdm dev` starts only `haystack-pgvector` in Docker and then runs Hayhooks locally. Settings are
loaded from `.env.haystack` by the pipeline wrappers, so direct debugging through the PDM
environment uses the same config shape as the container.

## Haystack Data Model

Each shop gets its own pgvector table and therefore its own HNSW index. The external `shop_id`
is converted to a safe deterministic table name using `HAYSTACK_PGVECTOR_TABLE_PREFIX`, a short
slug, and a hash. Chunks still keep `shop_id` and `document_id` in metadata for audit/debugging,
but vector retrieval does not rely on filtering a shared HNSW graph by `meta.shop_id`.

Default local settings use:

```text
PostgreSQL:          localhost:5433
pgvector table prefix: public.haystack_documents
keyword FTS config:  simple
vector type:          halfvec
embedding model:      text-embedding-3-large
embedding dimension:  3072
```

PostgreSQL connection strings are assembled from `HAYSTACK_POSTGRES_HOST`,
`HAYSTACK_POSTGRES_PORT`, `HAYSTACK_POSTGRES_USER`, `HAYSTACK_POSTGRES_PASSWORD`, and
`HAYSTACK_POSTGRES_DATABASE`. `PG_CONN_STR` can still be used as an explicit override for
non-standard deployments.

`HAYSTACK_PGVECTOR_LANGUAGE` is a PostgreSQL full-text search config used only by keyword
retrieval and keyword indexes. It does not affect vector retrieval or embeddings. The default is
`simple` because shops can contain documents in multiple languages.

Use explicit `document_id` for updates. The indexing endpoint deletes old chunks for the same
`shop_id + document_id` before writing the new version.

## LightRAG Stack

```bash
cp .env.lightrag.example .env.lightrag
docker compose --env-file .env.lightrag -f docker-compose.lightrag.yml up -d --wait
```

Open LightRAG WebUI at `http://localhost:9621/webui`.

This stack has no custom backend wrapper. LightRAG owns ingestion, document status, vector storage,
graph storage, WebUI, and its direct API. For `text-embedding-3-large` with 3072 dimensions, keep
`POSTGRES_VECTOR_INDEX_TYPE=HNSW_HALFVEC`.

## RAGFlow Stack

```bash
cp .env.ragflow.example .env.ragflow
docker compose --env-file .env.ragflow -f docker-compose.ragflow.yml up -d --wait
```

Open RAGFlow at `http://localhost:8088`.

The RAGFlow stack keeps Web/API/admin ports published according to `RAGFLOW_BIND_HOST`.
MySQL, MinIO, Redis, and Infinity stay internal to the Compose network.
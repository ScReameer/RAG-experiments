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

## Haystack API

Base URL: `http://localhost:1416`.

Hayhooks wraps each response into `result`:

```json
{
  "result": {}
}
```

The service never generates a final LLM answer. It indexes documents, manages chunks, and returns
retrieved context.

Common rules:

- `shop_id` is required everywhere. Each shop maps to its own pgvector table and HNSW index.
- `document_id` identifies one logical source document; one source document can produce many chunks.
- `shop_id` and `document_id` may contain letters, digits, `_`, `-`, `.`, `:` and must start
  with a letter or digit.
- `filters` use Haystack metadata filter syntax, for example
  `{"field":"meta.category","operator":"==","value":"delivery"}`.
- `table_exists: false` means read-only endpoints found no table and returned an empty result
  without creating one.
- Chunk payloads are always shaped as:

```json
{
  "id": "chunk-id",
  "content": "chunk text",
  "score": 0.83,
  "metadata": {}
}
```

### `POST /indexing/run`

Indexes text or files. Content type: `multipart/form-data`.

Request fields:

| Field | Type | Required | Default | Description |
|---|---:|---:|---:|---|
| `shop_id` | string | yes | - | Shop knowledge base id. |
| `document_id` | string/null | no | generated | Logical document id. Allowed only for one text input or one file. |
| `text` | string/null | no | `null` | Raw text. Either `text` or `files` is required. |
| `files` | file[]/null | no | `null` | Supported MIME types: `text/plain`, `text/markdown`, `application/pdf`. |
| `metadata` | object/null | no | `null` | Extra metadata merged into every source document. Reserved keys are overwritten by the service. |
| `replace_existing` | boolean | no | `true` | Delete old chunks with the same `document_id` before writing the new version. |

Reserved metadata keys: `shop_id`, `document_id`, `source_name`, `ingestion_type`, `mime_type`,
`file_name`.

For curl multipart requests, prefer omitting `metadata`; structured clients can send it.

Pipeline: file conversion -> cleaner -> splitter -> external embedding API -> pgvector writer.

Response contains: `status`, `shop_id`, `document_ids`, `documents_received`, `chunks_deleted`,
`chunks_written`, `table_name`, `table_exists`, `embedding_model`, `embedding_dimension`,
`vector_type`.

Index raw text:

```bash
curl -sS -X POST http://localhost:1416/indexing/run \
  -F 'shop_id=shop_a' \
  -F 'document_id=delivery_policy' \
  -F 'replace_existing=true' \
  -F 'text=We deliver to Russia by courier.'
```

Index a file:

```bash
curl -sS -X POST http://localhost:1416/indexing/run \
  -F 'shop_id=shop_a' \
  -F 'document_id=delivery_policy' \
  -F 'replace_existing=true' \
  -F 'files=@Bloom_info.md;type=text/markdown'
```

For multiple files, omit `document_id`; ids are generated from filenames.

### `POST /retrieve/run`

Returns context chunks for a query. Content type: `application/json`.

Request fields:

| Field | Type | Required | Default | Description |
|---|---:|---:|---:|---|
| `shop_id` | string | yes | - | Shop knowledge base id. |
| `query` | string | yes | - | User query to retrieve context for. |
| `top_k` | integer/null | no | `HAYSTACK_DEFAULT_TOP_K` | Maximum number of chunks to return. |
| `document_id` | string/null | no | `null` | Restrict retrieval to one logical document. |
| `filters` | object/null | no | `null` | Additional Haystack metadata filters. |
| `mode` | `vector`/`keyword`/`hybrid` | no | `vector` | Retrieval strategy. |
| `context_strategy` | `chunks`/`window` | no | `chunks` | `chunks` returns matched chunks; `window` also returns neighboring chunks. |
| `context_window_size` | integer/null | no | `HAYSTACK_CONTEXT_WINDOW_SIZE` | Neighbor count on each side for `context_strategy=window`. |

Modes:

- `vector`: semantic pgvector search using the configured external embedding API.
- `keyword`: PostgreSQL full-text search. `HAYSTACK_PGVECTOR_LANGUAGE` controls only this mode.
- `hybrid`: vector + keyword, fused with Haystack RRF (`DocumentJoiner`).

Response contains: `status`, `shop_id`, `mode`, `context_strategy`, `context_window_size`,
`query`, `top_k`, `filters`, `table_name`, `table_exists`, `chunks`, `contexts`,
`context_chunks`, `embedding_model`.

Vector retrieval scoped to one document:

```bash
curl -sS -X POST http://localhost:1416/retrieve/run \
  -H 'Content-Type: application/json' \
  -d '{
    "shop_id": "shop_a",
    "document_id": "delivery_policy",
    "query": "Какие есть варианты доставки?",
    "top_k": 3,
    "mode": "vector"
  }'
```

Hybrid retrieval with expanded context:

```bash
curl -sS -X POST http://localhost:1416/retrieve/run \
  -H 'Content-Type: application/json' \
  -d '{
    "shop_id": "shop_a",
    "query": "Какие есть варианты доставки?",
    "top_k": 3,
    "mode": "hybrid",
    "context_strategy": "window",
    "context_window_size": 1
  }'
```

Metadata filter example:

```bash
curl -sS -X POST http://localhost:1416/retrieve/run \
  -H 'Content-Type: application/json' \
  -d '{
    "shop_id": "shop_a",
    "query": "return policy",
    "filters": {
      "field": "meta.category",
      "operator": "==",
      "value": "returns"
    }
  }'
```

### `POST /documents/run`

Counts, lists, or deletes indexed chunks/documents. Content type: `application/json`.

Request fields:

| Field | Type | Required | Default | Description |
|---|---:|---:|---:|---|
| `shop_id` | string | yes | - | Shop knowledge base id. |
| `action` | `count`/`list`/`delete` | no | `count` | Operation to perform. |
| `document_id` | string/null | no | `null` | Restrict operation to one logical document. |
| `filters` | object/null | no | `null` | Additional Haystack metadata filters. |
| `limit` | integer | no | `50` | Max chunks to inspect for `list`. |
| `include_chunks` | boolean | no | `false` | Include raw chunk payloads in `list` responses. |

Actions:

- `count`: returns chunk count and does not create empty tables.
- `list`: returns grouped document summaries and optionally raw chunks.
- `delete`: deletes matching chunks; drops the shop table when it becomes empty.

Response fields depend on action. Common fields: `status`, `shop_id`, `document_id`, `filters`,
`table_name`, `table_exists`. `count`/`list` add `chunks_count`; `delete` adds
`chunks_deleted`; `list` can also return `documents` and `chunks`.

Count chunks in a shop:

```bash
curl -sS -X POST http://localhost:1416/documents/run \
  -H 'Content-Type: application/json' \
  -d '{
    "shop_id": "shop_a",
    "action": "count"
  }'
```

List document summaries with chunks:

```bash
curl -sS -X POST http://localhost:1416/documents/run \
  -H 'Content-Type: application/json' \
  -d '{
    "shop_id": "shop_a",
    "action": "list",
    "include_chunks": true,
    "limit": 5
  }'
```

Delete one document or the whole shop:

```bash
curl -sS -X POST http://localhost:1416/documents/run \
  -H 'Content-Type: application/json' \
  -d '{
    "shop_id": "shop_a",
    "document_id": "delivery_policy",
    "action": "delete"
  }'
```

Omit `document_id` in the same request to delete the whole shop knowledge base.

For local development with only pgvector in Docker and Hayhooks in the PDM environment:

```bash
pdm sync -G dev
pdm dev
```

`pdm dev` starts only `haystack-pgvector` in Docker and then runs Hayhooks locally. Settings are
loaded from `.env.haystack` by the pipeline wrappers, so direct debugging through the PDM
environment uses the same config shape as the container.

## Haystack Notes

Each shop gets its own pgvector table and HNSW index. Chunks still keep `shop_id` and
`document_id` in metadata, but vector search does not filter one shared HNSW graph by `shop_id`.

Default local settings use:

```text
PostgreSQL:          localhost:5433
pgvector table prefix: public.haystack_documents
keyword FTS config:  simple
vector type:          halfvec
embedding model:      text-embedding-3-large
embedding dimension:  3072
context window size:  1
```

PostgreSQL DSN is assembled from `HAYSTACK_POSTGRES_*`; `PG_CONN_STR` is still supported as an
override. `HAYSTACK_PGVECTOR_LANGUAGE` affects only keyword full-text search. Use explicit
`document_id` for updates: indexing deletes old chunks for the same document before writing the
new version.

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

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

Base URL:

```text
http://localhost:1416
```

Hayhooks wraps every pipeline response into a top-level `result` object:

```json
{
  "result": {
    "status": "retrieved"
  }
}
```

The service never generates a final LLM answer. It only indexes documents, manages indexed chunks,
and returns retrieved context chunks.

Common rules:

- `shop_id` is required on every endpoint. Each shop gets an independent pgvector table and HNSW
  index.
- `shop_id` and `document_id` must start with a letter or digit and may contain letters, digits,
  `_`, `-`, `.`, `:`.
- `document_id` scopes operations to one logical source document. A document can produce many
  chunks.
- `filters` use Haystack metadata filter syntax and are applied inside the current shop table.
  Example: `{"field":"meta.category","operator":"==","value":"delivery"}`.
- `table_exists: false` means the shop table does not exist yet. Read-only endpoints return empty
  results in this case and do not create an empty table.

Chunk payload shape:

```json
{
  "id": "haystack-document-id",
  "content": "chunk text",
  "score": 0.83,
  "metadata": {
    "shop_id": "shop_a",
    "document_id": "delivery_policy",
    "source_name": "delivery_policy",
    "ingestion_type": "text"
  }
}
```

### `POST /indexing/run`

Indexes text or files for one shop.

Content type: `multipart/form-data`.

Pipeline internals:

```text
file conversion -> DocumentCleaner -> DocumentSplitter -> external embedding API -> pgvector writer
```

Supported file MIME types:

```text
text/plain
text/markdown
application/pdf
```

Request fields:

| Field | Type | Required | Default | Description |
|---|---:|---:|---:|---|
| `shop_id` | string | yes | - | Shop knowledge base id. Determines the pgvector table. |
| `document_id` | string/null | no | generated | Logical document id. Can be provided only when indexing one text input or one file. |
| `text` | string/null | no | `null` | Raw text to index. Either `text` or at least one `files` item is required. |
| `files` | file[]/null | no | `null` | One or more uploaded files. |
| `metadata` | object/null | no | `null` | Extra metadata merged into every source document. Reserved keys are overwritten by the service. |
| `replace_existing` | boolean | no | `true` | Before writing new chunks, delete old chunks with the same `document_id`. |

Reserved metadata keys written by the service:

```text
shop_id
document_id
source_name
ingestion_type
mime_type
file_name
```

`metadata` is part of the OpenAPI schema, but plain curl cannot reliably send a nested dict through
Hayhooks multipart parsing. For curl-based indexing, prefer explicit `document_id` and keep metadata
out of the request unless the client can send structured multipart objects.

Response `result` fields:

| Field | Description |
|---|---|
| `status` | Always `indexed` on success. |
| `shop_id` | Normalized shop id. |
| `document_ids` | Logical document ids touched by this request. |
| `documents_received` | Number of source documents before splitting. |
| `chunks_deleted` | Old chunks removed because `replace_existing=true`. |
| `chunks_written` | New chunks written after splitting and embedding. |
| `table_name` | Physical pgvector table name. |
| `table_exists` | `true` after successful indexing. |
| `embedding_model` | Embedding model used. |
| `embedding_dimension` | Stored vector dimension. |
| `vector_type` | pgvector storage type, for example `halfvec`. |

Index raw text:

```bash
curl -sS -X POST http://localhost:1416/indexing/run \
  -F 'shop_id=shop_a' \
  -F 'document_id=delivery_policy' \
  -F 'replace_existing=true' \
  -F 'text=We deliver to Russia by courier.'
```

Index a Markdown file:

```bash
curl -sS -X POST http://localhost:1416/indexing/run \
  -F 'shop_id=shop_a' \
  -F 'document_id=delivery_policy' \
  -F 'replace_existing=true' \
  -F 'files=@Bloom_info.md;type=text/markdown'
```

Index several files at once. In this mode omit `document_id`; ids are generated from filenames:

```bash
curl -sS -X POST http://localhost:1416/indexing/run \
  -F 'shop_id=shop_a' \
  -F 'files=@delivery.md;type=text/markdown' \
  -F 'files=@returns.pdf;type=application/pdf'
```

### `POST /retrieve/run`

Returns relevant context chunks for a query. It does not generate an answer.

Content type: `application/json`.

Request fields:

| Field | Type | Required | Default | Description |
|---|---:|---:|---:|---|
| `shop_id` | string | yes | - | Shop knowledge base id. |
| `query` | string | yes | - | User query to retrieve context for. |
| `top_k` | integer/null | no | `HAYSTACK_DEFAULT_TOP_K` | Maximum number of chunks to return. |
| `document_id` | string/null | no | `null` | Restrict retrieval to one logical document. |
| `filters` | object/null | no | `null` | Additional Haystack metadata filters. |
| `mode` | `vector`/`keyword` | no | `vector` | Retrieval strategy. |

Modes:

| Mode | Behavior |
|---|---|
| `vector` | Embeds `query` with the configured external embedding API and searches pgvector. Best default for multilingual semantic search. |
| `keyword` | Uses PostgreSQL full-text search over chunk content. `HAYSTACK_PGVECTOR_LANGUAGE` controls the FTS config; default is `simple`. |

If the shop table does not exist, the endpoint returns `chunks: []` and `table_exists: false`.
For `mode=vector`, this also avoids an embedding API call.

Response `result` fields:

| Field | Description |
|---|---|
| `status` | Always `retrieved` on success. |
| `shop_id` | Normalized shop id. |
| `mode` | Used retrieval mode. |
| `query` | Original query. |
| `top_k` | Effective top-k value. |
| `filters` | Effective filter expression. |
| `table_name` | Physical pgvector table name. |
| `table_exists` | Whether the shop table exists. |
| `chunks` | Retrieved chunk payloads. |
| `embedding_model` | Configured embedding model. |

Vector retrieval:

```bash
curl -sS -X POST http://localhost:1416/retrieve/run \
  -H 'Content-Type: application/json' \
  -d '{
    "shop_id": "shop_a",
    "query": "Есть доставка в Россию?",
    "top_k": 5,
    "mode": "vector"
  }'
```

Retrieve only from one document:

```bash
curl -sS -X POST http://localhost:1416/retrieve/run \
  -H 'Content-Type: application/json' \
  -d '{
    "shop_id": "shop_a",
    "document_id": "delivery_policy",
    "query": "Какие есть варианты доставки?",
    "top_k": 3
  }'
```

Keyword retrieval:

```bash
curl -sS -X POST http://localhost:1416/retrieve/run \
  -H 'Content-Type: application/json' \
  -d '{
    "shop_id": "shop_a",
    "query": "courier Russia",
    "top_k": 5,
    "mode": "keyword"
  }'
```

Retrieval with an extra metadata filter:

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

Counts, lists, or deletes indexed chunks/documents for one shop.

Content type: `application/json`.

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

| Action | Behavior |
|---|---|
| `count` | Returns chunk count. Does not create an empty table for unknown shops. |
| `list` | Returns document summaries and optionally raw chunks. |
| `delete` | Deletes matching chunks. If no chunks remain, drops the shop table. |

Response `result` fields depend on action:

| Field | Actions | Description |
|---|---|---|
| `status` | all | `counted`, `listed`, or `deleted`. |
| `shop_id` | all | Normalized shop id. |
| `document_id` | all | Requested document id, if any. |
| `filters` | all | Effective filter expression. |
| `table_name` | all | Physical pgvector table name. |
| `table_exists` | all | Whether the shop table exists after the operation. |
| `chunks_count` | `count`, `list` | Number of matching chunks. |
| `chunks_deleted` | `delete` | Number of deleted chunks. |
| `documents` | `list` | Grouped document summaries: `document_id`, `shop_id`, `source_name`, `file_name`, `chunks_count`. |
| `chunks` | `list` | Raw chunk payloads when `include_chunks=true`; otherwise empty. |

Count chunks in a shop:

```bash
curl -sS -X POST http://localhost:1416/documents/run \
  -H 'Content-Type: application/json' \
  -d '{
    "shop_id": "shop_a",
    "action": "count"
  }'
```

List document summaries:

```bash
curl -sS -X POST http://localhost:1416/documents/run \
  -H 'Content-Type: application/json' \
  -d '{
    "shop_id": "shop_a",
    "action": "list",
    "limit": 20
  }'
```

List chunks for one document:

```bash
curl -sS -X POST http://localhost:1416/documents/run \
  -H 'Content-Type: application/json' \
  -d '{
    "shop_id": "shop_a",
    "document_id": "delivery_policy",
    "action": "list",
    "include_chunks": true,
    "limit": 5
  }'
```

Delete one document:

```bash
curl -sS -X POST http://localhost:1416/documents/run \
  -H 'Content-Type: application/json' \
  -d '{
    "shop_id": "shop_a",
    "document_id": "delivery_policy",
    "action": "delete"
  }'
```

Delete the whole shop knowledge base:

```bash
curl -sS -X POST http://localhost:1416/documents/run \
  -H 'Content-Type: application/json' \
  -d '{
    "shop_id": "shop_a",
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

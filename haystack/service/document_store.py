from __future__ import annotations

import hashlib
import re
from typing import Any

import psycopg
from haystack.utils import Secret
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore
from psycopg import sql

from service.filters import validate_identifier
from service.settings import HaystackSettings, get_settings

_PG_IDENTIFIER_MAX_LENGTH = 63
_INDEX_SUFFIX_MAX_LENGTH = len("_keyword_index")
_TABLE_NAME_MAX_LENGTH = _PG_IDENTIFIER_MAX_LENGTH - _INDEX_SUFFIX_MAX_LENGTH
_SAFE_IDENTIFIER_RE = re.compile(r"[^a-z0-9]+")


def _safe_identifier_part(value: str, *, fallback: str) -> str:
    normalized = _SAFE_IDENTIFIER_RE.sub("_", value.lower()).strip("_")
    if not normalized:
        normalized = fallback
    if not normalized[0].isalpha():
        normalized = f"{fallback}_{normalized}"
    return normalized


def get_shop_table_name(shop_id: str, settings: HaystackSettings | None = None) -> str:
    config = settings or get_settings()
    normalized_shop_id = validate_identifier(shop_id, field_name="shop_id")
    prefix = _safe_identifier_part(config.pg_table_prefix, fallback="haystack_documents")[
        :20
    ].strip("_")
    slug = _safe_identifier_part(normalized_shop_id, fallback="shop")[:10].strip("_")
    prefix = prefix or "haystack_documents"
    slug = slug or "shop"
    digest = hashlib.sha256(normalized_shop_id.encode("utf-8")).hexdigest()[:16]
    table_name = f"{prefix}_{slug}_{digest}"
    return table_name[:_TABLE_NAME_MAX_LENGTH]


def create_document_store(
    shop_id: str,
    settings: HaystackSettings | None = None,
) -> PgvectorDocumentStore:
    config = settings or get_settings()
    table_name = get_shop_table_name(shop_id, config)
    init_kwargs: dict[str, Any] = {
        "connection_string": Secret.from_token(config.pg_conn_str),
        "create_extension": config.pg_create_extension,
        "schema_name": config.pg_schema,
        "table_name": table_name,
        "language": config.pg_language,
        "embedding_dimension": config.embedding_dimension,
        "vector_type": config.pg_vector_type,
        "vector_function": config.pg_vector_function,
        "recreate_table": config.pg_recreate_table,
        "search_strategy": config.pg_search_strategy,
        "hnsw_index_name": f"{table_name}_hnsw_index",
        "keyword_index_name": f"{table_name}_keyword_index",
    }
    if config.pg_hnsw_ef_search is not None:
        init_kwargs["hnsw_ef_search"] = config.pg_hnsw_ef_search
    return PgvectorDocumentStore(**init_kwargs)


def shop_table_exists(shop_id: str, settings: HaystackSettings | None = None) -> bool:
    config = settings or get_settings()
    table_name = get_shop_table_name(shop_id, config)
    with psycopg.connect(config.pg_conn_str) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = %s
                )
                """,
                (config.pg_schema, table_name),
            )
            row = cursor.fetchone()
    return bool(row[0]) if row else False


def drop_shop_table(shop_id: str, settings: HaystackSettings | None = None) -> None:
    config = settings or get_settings()
    table_name = get_shop_table_name(shop_id, config)
    with psycopg.connect(config.pg_conn_str) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                    sql.Identifier(config.pg_schema),
                    sql.Identifier(table_name),
                )
            )

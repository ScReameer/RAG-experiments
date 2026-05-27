import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Collection, Literal, TypeVar, cast
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv(".env.haystack", override=False)

SplitBy = Literal["function", "page", "passage", "period", "word", "line", "sentence"]
VectorFunction = Literal["cosine_similarity", "inner_product", "l2_distance"]
VectorType = Literal["vector", "halfvec"]
SearchStrategy = Literal["exact_nearest_neighbor", "hnsw"]

_T = TypeVar("_T", bound=str)


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def _get_optional_int(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    return int(value)


def _get_choice(name: str, default: _T, choices: Collection[_T]) -> _T:
    value = os.getenv(name, default).strip()
    if value not in choices:
        msg = f"{name} must be one of: {', '.join(sorted(choices))}"
        raise ValueError(msg)
    return cast(_T, value)


def _build_pg_conn_str() -> str:
    explicit_conn_str = os.getenv("PG_CONN_STR")
    if explicit_conn_str:
        return explicit_conn_str

    user = quote(os.getenv("HAYSTACK_POSTGRES_USER", "sa"), safe="")
    password = quote(os.getenv("HAYSTACK_POSTGRES_PASSWORD", "sa"), safe="")
    host = os.getenv("HAYSTACK_POSTGRES_HOST", "localhost")
    port = os.getenv("HAYSTACK_POSTGRES_PORT", "5433")
    database = quote(os.getenv("HAYSTACK_POSTGRES_DATABASE", "sa"), safe="")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


@dataclass(frozen=True, slots=True)
class HaystackSettings:
    pg_conn_str: str
    pg_schema: str
    pg_table_prefix: str
    pg_language: str
    pg_create_extension: bool
    pg_recreate_table: bool
    pg_vector_type: VectorType
    pg_vector_function: VectorFunction
    pg_search_strategy: SearchStrategy
    pg_hnsw_ef_search: int | None
    embedding_model: str
    embedding_dimension: int
    embedding_api_dimensions: int | None
    embedding_api_key: str
    embedding_api_base_url: str | None
    embedding_batch_size: int
    split_by: SplitBy
    split_length: int
    split_overlap: int
    default_top_k: int
    default_context_window_size: int


@lru_cache
def get_settings() -> HaystackSettings:
    return HaystackSettings(
        pg_conn_str=_build_pg_conn_str(),
        pg_schema=os.getenv("HAYSTACK_PGVECTOR_SCHEMA", "public"),
        pg_table_prefix=(
            os.getenv("HAYSTACK_PGVECTOR_TABLE_PREFIX")
            or os.getenv("HAYSTACK_PGVECTOR_TABLE")
            or "haystack_documents"
        ),
        pg_language=os.getenv("HAYSTACK_PGVECTOR_LANGUAGE", "simple"),
        pg_create_extension=_get_bool("HAYSTACK_PGVECTOR_CREATE_EXTENSION", True),
        pg_recreate_table=_get_bool("HAYSTACK_PGVECTOR_RECREATE_TABLE", False),
        pg_vector_type=_get_choice(
            "HAYSTACK_PGVECTOR_VECTOR_TYPE",
            "halfvec",
            ("vector", "halfvec"),
        ),
        pg_vector_function=_get_choice(
            "HAYSTACK_PGVECTOR_VECTOR_FUNCTION",
            "cosine_similarity",
            ("cosine_similarity", "inner_product", "l2_distance"),
        ),
        pg_search_strategy=_get_choice(
            "HAYSTACK_PGVECTOR_SEARCH_STRATEGY",
            "hnsw",
            ("exact_nearest_neighbor", "hnsw"),
        ),
        pg_hnsw_ef_search=_get_optional_int("HAYSTACK_PGVECTOR_HNSW_EF_SEARCH"),
        embedding_model=os.getenv("HAYSTACK_EMBEDDING_MODEL", "text-embedding-3-large"),
        embedding_dimension=_get_int("HAYSTACK_EMBEDDING_DIMENSION", 3072),
        embedding_api_dimensions=_get_optional_int("HAYSTACK_EMBEDDING_API_DIMENSIONS"),
        embedding_api_key=os.getenv("HAYSTACK_EMBEDDING_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or "replace-me",
        embedding_api_base_url=os.getenv("HAYSTACK_EMBEDDING_API_BASE_URL")
        or os.getenv("OPENAI_BASE_URL"),
        embedding_batch_size=_get_int("HAYSTACK_EMBEDDING_BATCH_SIZE", 16),
        split_by=_get_choice(
            "HAYSTACK_SPLIT_BY",
            "word",
            ("function", "page", "passage", "period", "word", "line", "sentence"),
        ),
        split_length=_get_int("HAYSTACK_SPLIT_LENGTH", 250),
        split_overlap=_get_int("HAYSTACK_SPLIT_OVERLAP", 40),
        default_top_k=_get_int("HAYSTACK_DEFAULT_TOP_K", 10),
        default_context_window_size=_get_int("HAYSTACK_CONTEXT_WINDOW_SIZE", 1),
    )

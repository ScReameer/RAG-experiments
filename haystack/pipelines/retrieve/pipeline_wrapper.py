from typing import Any, Literal, cast

from hayhooks import BasePipelineWrapper
from haystack_integrations.components.retrievers.pgvector import (
    PgvectorEmbeddingRetriever,
    PgvectorKeywordRetriever,
)
from service.document_store import (
    create_document_store,
    get_shop_table_name,
    shop_table_exists,
)
from service.embedders import create_text_embedder
from service.filters import scoped_filter, validate_identifier
from service.serialization import documents_to_payload
from service.settings import HaystackSettings, get_settings

from haystack import Document, Pipeline


class PipelineWrapper(BasePipelineWrapper):
    settings: HaystackSettings

    def setup(self) -> None:
        self.settings = get_settings()

    def _create_vector_pipeline(self, shop_id: str) -> Pipeline:
        document_store = create_document_store(shop_id, self.settings)
        vector_pipeline = Pipeline()
        vector_pipeline.add_component("text_embedder", create_text_embedder(self.settings))
        vector_pipeline.add_component(
            "retriever",
            PgvectorEmbeddingRetriever(
                document_store=document_store,
                top_k=self.settings.default_top_k,
                vector_function=self.settings.pg_vector_function,
            ),
        )
        vector_pipeline.connect("text_embedder.embedding", "retriever.query_embedding")
        return vector_pipeline

    def _create_keyword_retriever(self, shop_id: str) -> PgvectorKeywordRetriever:
        document_store = create_document_store(shop_id, self.settings)
        return PgvectorKeywordRetriever(
            document_store=document_store, top_k=self.settings.default_top_k
        )

    def run_api(
        self,
        shop_id: str,
        query: str,
        top_k: int | None = None,
        document_id: str | None = None,
        filters: dict[str, Any] | None = None,
        mode: Literal["vector", "keyword"] = "vector",
    ) -> dict[str, Any]:
        normalized_shop_id = validate_identifier(shop_id, field_name="shop_id")
        retrieval_top_k = top_k or self.settings.default_top_k
        scoped = scoped_filter(normalized_shop_id, document_id=document_id, extra_filters=filters)
        table_name = get_shop_table_name(normalized_shop_id, self.settings)

        if not shop_table_exists(normalized_shop_id, self.settings):
            return {
                "status": "retrieved",
                "shop_id": normalized_shop_id,
                "mode": mode,
                "query": query,
                "top_k": retrieval_top_k,
                "filters": scoped,
                "table_name": table_name,
                "table_exists": False,
                "chunks": [],
                "embedding_model": self.settings.embedding_model,
            }

        if mode == "keyword":
            keyword_retriever = self._create_keyword_retriever(normalized_shop_id)
            keyword_result = keyword_retriever.run(
                query=query,
                filters=scoped,
                top_k=retrieval_top_k,
            )
            documents = keyword_result["documents"]
        else:
            vector_pipeline = self._create_vector_pipeline(normalized_shop_id)
            vector_result: Any = vector_pipeline.run(
                {
                    "text_embedder": {"text": query},
                    "retriever": {"filters": scoped, "top_k": retrieval_top_k},
                }
            )
            documents = cast(list[Document], vector_result["retriever"]["documents"])

        return {
            "status": "retrieved",
            "shop_id": normalized_shop_id,
            "mode": mode,
            "query": query,
            "top_k": retrieval_top_k,
            "filters": scoped,
            "table_name": table_name,
            "table_exists": True,
            "chunks": documents_to_payload(documents),
            "embedding_model": self.settings.embedding_model,
        }

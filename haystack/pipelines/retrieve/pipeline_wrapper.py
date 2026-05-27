from typing import Any, cast

from hayhooks import BasePipelineWrapper
from haystack.components.joiners import DocumentJoiner
from haystack.components.retrievers import SentenceWindowRetriever
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
from service.schemas import (
    ContextStrategy,
    ContextWindowPayload,
    RetrievalMode,
    RetrieveResponse,
)
from service.serialization import document_to_payload, documents_to_payload, unique_documents_by_id
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

    def _create_hybrid_pipeline(self, shop_id: str) -> Pipeline:
        document_store = create_document_store(shop_id, self.settings)
        hybrid_pipeline = Pipeline()
        hybrid_pipeline.add_component("text_embedder", create_text_embedder(self.settings))
        hybrid_pipeline.add_component(
            "vector_retriever",
            PgvectorEmbeddingRetriever(
                document_store=document_store,
                top_k=self.settings.default_top_k,
                vector_function=self.settings.pg_vector_function,
            ),
        )
        hybrid_pipeline.add_component(
            "keyword_retriever",
            PgvectorKeywordRetriever(
                document_store=document_store,
                top_k=self.settings.default_top_k,
            ),
        )
        hybrid_pipeline.add_component(
            "document_joiner",
            DocumentJoiner(join_mode="reciprocal_rank_fusion"),
        )
        hybrid_pipeline.connect("text_embedder.embedding", "vector_retriever.query_embedding")
        hybrid_pipeline.connect("vector_retriever.documents", "document_joiner.documents")
        hybrid_pipeline.connect("keyword_retriever.documents", "document_joiner.documents")
        return hybrid_pipeline

    def _create_keyword_retriever(self, shop_id: str) -> PgvectorKeywordRetriever:
        document_store = create_document_store(shop_id, self.settings)
        return PgvectorKeywordRetriever(
            document_store=document_store, top_k=self.settings.default_top_k
        )

    def _apply_context_strategy(
        self,
        *,
        shop_id: str,
        documents: list[Document],
        context_strategy: ContextStrategy,
        context_window_size: int,
    ) -> tuple[list[ContextWindowPayload], list[Document]]:
        if context_strategy == "chunks" or not documents:
            return [], []

        document_store = create_document_store(shop_id, self.settings)
        window_retriever = SentenceWindowRetriever(
            document_store=document_store,
            window_size=context_window_size,
            raise_on_missing_meta_fields=False,
        )
        result = window_retriever.run(
            retrieved_documents=documents,
            window_size=context_window_size,
        )
        context_windows = cast(list[str], result["context_windows"])
        context_documents = cast(list[Document], result["context_documents"])
        contexts = [
            ContextWindowPayload(content=content, matched_chunk=document_to_payload(document))
            for document, content in zip(documents, context_windows, strict=True)
        ]
        return contexts, unique_documents_by_id(context_documents)

    def _retrieve_documents(
        self,
        *,
        shop_id: str,
        query: str,
        mode: RetrievalMode,
        filters: dict[str, Any] | None,
        top_k: int,
    ) -> list[Document]:
        if mode == "keyword":
            keyword_retriever = self._create_keyword_retriever(shop_id)
            keyword_result = keyword_retriever.run(
                query=query,
                filters=filters,
                top_k=top_k,
            )
            return keyword_result["documents"]

        if mode == "hybrid":
            hybrid_pipeline = self._create_hybrid_pipeline(shop_id)
            hybrid_result: Any = hybrid_pipeline.run(
                {
                    "text_embedder": {"text": query},
                    "vector_retriever": {"filters": filters, "top_k": top_k},
                    "keyword_retriever": {"query": query, "filters": filters, "top_k": top_k},
                    "document_joiner": {"top_k": top_k},
                }
            )
            return cast(list[Document], hybrid_result["document_joiner"]["documents"])

        vector_pipeline = self._create_vector_pipeline(shop_id)
        vector_result: Any = vector_pipeline.run(
            {
                "text_embedder": {"text": query},
                "retriever": {"filters": filters, "top_k": top_k},
            }
        )
        return cast(list[Document], vector_result["retriever"]["documents"])

    def _resolve_positive_int(self, value: int | None, *, default: int, field_name: str) -> int:
        resolved = value if value is not None else default
        if resolved < 1:
            msg = f"{field_name} must be greater than 0"
            raise ValueError(msg)
        return resolved

    def run_api(
        self,
        shop_id: str,
        query: str,
        top_k: int | None = None,
        document_id: str | None = None,
        filters: dict[str, Any] | None = None,
        mode: RetrievalMode = "vector",
        context_strategy: ContextStrategy = "chunks",
        context_window_size: int | None = None,
    ) -> dict[str, Any]:
        normalized_shop_id = validate_identifier(shop_id, field_name="shop_id")
        retrieval_top_k = self._resolve_positive_int(
            top_k,
            default=self.settings.default_top_k,
            field_name="top_k",
        )
        resolved_context_window_size = self._resolve_positive_int(
            context_window_size,
            default=self.settings.default_context_window_size,
            field_name="context_window_size",
        )
        scoped = scoped_filter(normalized_shop_id, document_id=document_id, extra_filters=filters)
        table_name = get_shop_table_name(normalized_shop_id, self.settings)

        if not shop_table_exists(normalized_shop_id, self.settings):
            return RetrieveResponse(
                shop_id=normalized_shop_id,
                mode=mode,
                context_strategy=context_strategy,
                context_window_size=(
                    resolved_context_window_size if context_strategy == "window" else None
                ),
                query=query,
                top_k=retrieval_top_k,
                filters=scoped,
                table_name=table_name,
                table_exists=False,
                chunks=[],
                embedding_model=self.settings.embedding_model,
            ).to_payload()

        documents = self._retrieve_documents(
            shop_id=normalized_shop_id,
            query=query,
            mode=mode,
            filters=scoped,
            top_k=retrieval_top_k,
        )
        contexts, context_documents = self._apply_context_strategy(
            shop_id=normalized_shop_id,
            documents=documents,
            context_strategy=context_strategy,
            context_window_size=resolved_context_window_size,
        )

        return RetrieveResponse(
            shop_id=normalized_shop_id,
            mode=mode,
            context_strategy=context_strategy,
            context_window_size=resolved_context_window_size
            if context_strategy == "window"
            else None,
            query=query,
            top_k=retrieval_top_k,
            filters=scoped,
            table_name=table_name,
            table_exists=True,
            chunks=documents_to_payload(documents),
            contexts=contexts,
            context_chunks=documents_to_payload(context_documents),
            embedding_model=self.settings.embedding_model,
        ).to_payload()

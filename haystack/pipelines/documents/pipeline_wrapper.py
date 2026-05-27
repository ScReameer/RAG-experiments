from typing import Any

from hayhooks import BasePipelineWrapper
from service.document_store import (
    create_document_store,
    drop_shop_table,
    get_shop_table_name,
    shop_table_exists,
)
from service.filters import scoped_filter, validate_identifier
from service.schemas import (
    DocumentAction,
    DocumentsCountResponse,
    DocumentsDeletedResponse,
    DocumentsListResponse,
)
from service.serialization import documents_to_payload, summarize_documents
from service.settings import HaystackSettings, get_settings


class PipelineWrapper(BasePipelineWrapper):
    settings: HaystackSettings

    def setup(self) -> None:
        self.settings = get_settings()

    def run_api(
        self,
        shop_id: str,
        action: DocumentAction = "count",
        document_id: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 50,
        include_chunks: bool = False,
    ) -> dict[str, Any]:
        normalized_shop_id = validate_identifier(shop_id, field_name="shop_id")
        scoped = scoped_filter(normalized_shop_id, document_id=document_id, extra_filters=filters)
        table_name = get_shop_table_name(normalized_shop_id, self.settings)

        if not shop_table_exists(normalized_shop_id, self.settings):
            if action == "delete":
                return DocumentsDeletedResponse(
                    shop_id=normalized_shop_id,
                    document_id=document_id,
                    chunks_deleted=0,
                    filters=scoped,
                    table_name=table_name,
                    table_exists=False,
                ).to_payload()
            if action == "count":
                return DocumentsCountResponse(
                    shop_id=normalized_shop_id,
                    document_id=document_id,
                    chunks_count=0,
                    filters=scoped,
                    table_name=table_name,
                    table_exists=False,
                ).to_payload()
            return DocumentsListResponse(
                shop_id=normalized_shop_id,
                document_id=document_id,
                chunks_count=0,
                limit=limit,
                filters=scoped,
                table_name=table_name,
                table_exists=False,
                documents=[],
                chunks=[],
            ).to_payload()

        document_store = create_document_store(normalized_shop_id, self.settings)

        if action == "delete":
            if scoped is None:
                deleted = document_store.count_documents()
                drop_shop_table(normalized_shop_id, self.settings)
                table_exists = False
            else:
                deleted = document_store.count_documents_by_filter(scoped)
                document_store.delete_by_filter(scoped)
                table_exists = document_store.count_documents() > 0
                if not table_exists:
                    drop_shop_table(normalized_shop_id, self.settings)
            return DocumentsDeletedResponse(
                shop_id=normalized_shop_id,
                document_id=document_id,
                chunks_deleted=deleted,
                filters=scoped,
                table_name=table_name,
                table_exists=table_exists,
            ).to_payload()

        count = (
            document_store.count_documents()
            if scoped is None
            else document_store.count_documents_by_filter(scoped)
        )
        if action == "count":
            return DocumentsCountResponse(
                shop_id=normalized_shop_id,
                document_id=document_id,
                chunks_count=count,
                filters=scoped,
                table_name=table_name,
                table_exists=True,
            ).to_payload()

        documents = document_store.filter_documents(scoped)[:limit]
        return DocumentsListResponse(
            shop_id=normalized_shop_id,
            document_id=document_id,
            chunks_count=count,
            limit=limit,
            filters=scoped,
            table_name=table_name,
            table_exists=True,
            documents=summarize_documents(documents),
            chunks=documents_to_payload(documents) if include_chunks else [],
        ).to_payload()

from typing import Any, Literal

from hayhooks import BasePipelineWrapper
from service.document_store import (
    create_document_store,
    drop_shop_table,
    get_shop_table_name,
    shop_table_exists,
)
from service.filters import scoped_filter, validate_identifier
from service.serialization import documents_to_payload, summarize_documents
from service.settings import HaystackSettings, get_settings


class PipelineWrapper(BasePipelineWrapper):
    settings: HaystackSettings

    def setup(self) -> None:
        self.settings = get_settings()

    def run_api(
        self,
        shop_id: str,
        action: Literal["count", "list", "delete"] = "count",
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
                return {
                    "status": "deleted",
                    "shop_id": normalized_shop_id,
                    "document_id": document_id,
                    "chunks_deleted": 0,
                    "filters": scoped,
                    "table_name": table_name,
                    "table_exists": False,
                }
            if action == "count":
                return {
                    "status": "counted",
                    "shop_id": normalized_shop_id,
                    "document_id": document_id,
                    "chunks_count": 0,
                    "filters": scoped,
                    "table_name": table_name,
                    "table_exists": False,
                }
            return {
                "status": "listed",
                "shop_id": normalized_shop_id,
                "document_id": document_id,
                "chunks_count": 0,
                "limit": limit,
                "filters": scoped,
                "table_name": table_name,
                "table_exists": False,
                "documents": [],
                "chunks": [],
            }

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
            return {
                "status": "deleted",
                "shop_id": normalized_shop_id,
                "document_id": document_id,
                "chunks_deleted": deleted,
                "filters": scoped,
                "table_name": table_name,
                "table_exists": table_exists,
            }

        count = (
            document_store.count_documents()
            if scoped is None
            else document_store.count_documents_by_filter(scoped)
        )
        if action == "count":
            return {
                "status": "counted",
                "shop_id": normalized_shop_id,
                "document_id": document_id,
                "chunks_count": count,
                "filters": scoped,
                "table_name": table_name,
                "table_exists": True,
            }

        documents = document_store.filter_documents(scoped)[:limit]
        return {
            "status": "listed",
            "shop_id": normalized_shop_id,
            "document_id": document_id,
            "chunks_count": count,
            "limit": limit,
            "filters": scoped,
            "table_name": table_name,
            "table_exists": True,
            "documents": summarize_documents(documents),
            "chunks": documents_to_payload(documents) if include_chunks else [],
        }

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FilterExpression = dict[str, Any]
RetrievalMode = Literal["vector", "keyword", "hybrid"]
ContextStrategy = Literal["chunks", "window"]
DocumentAction = Literal["count", "list", "delete"]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ChunkPayload(ApiModel):
    id: str
    content: str | None
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentSummary(ApiModel):
    document_id: str
    shop_id: Any = None
    source_name: Any = None
    file_name: Any = None
    chunks_count: int = 0


class ContextWindowPayload(ApiModel):
    content: str
    matched_chunk: ChunkPayload


class IndexingResponse(ApiModel):
    status: Literal["indexed"] = "indexed"
    shop_id: str
    document_ids: list[str]
    documents_received: int
    chunks_deleted: int
    chunks_written: int
    table_name: str
    table_exists: bool
    embedding_model: str
    embedding_dimension: int
    vector_type: str


class RetrieveResponse(ApiModel):
    status: Literal["retrieved"] = "retrieved"
    shop_id: str
    mode: RetrievalMode
    context_strategy: ContextStrategy
    context_window_size: int | None
    query: str
    top_k: int
    filters: FilterExpression | None
    table_name: str
    table_exists: bool
    chunks: list[ChunkPayload]
    contexts: list[ContextWindowPayload] = Field(default_factory=list)
    context_chunks: list[ChunkPayload] = Field(default_factory=list)
    embedding_model: str


class DocumentsDeletedResponse(ApiModel):
    status: Literal["deleted"] = "deleted"
    shop_id: str
    document_id: str | None
    chunks_deleted: int
    filters: FilterExpression | None
    table_name: str
    table_exists: bool


class DocumentsCountResponse(ApiModel):
    status: Literal["counted"] = "counted"
    shop_id: str
    document_id: str | None
    chunks_count: int
    filters: FilterExpression | None
    table_name: str
    table_exists: bool


class DocumentsListResponse(ApiModel):
    status: Literal["listed"] = "listed"
    shop_id: str
    document_id: str | None
    chunks_count: int
    limit: int
    filters: FilterExpression | None
    table_name: str
    table_exists: bool
    documents: list[DocumentSummary]
    chunks: list[ChunkPayload]

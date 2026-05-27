from typing import Any

from haystack import Document
from service.schemas import ChunkPayload, DocumentSummary


def document_to_payload(document: Document) -> ChunkPayload:
    return ChunkPayload(
        id=document.id,
        content=document.content,
        score=getattr(document, "score", None),
        metadata=dict(document.meta or {}),
    )


def documents_to_payload(documents: list[Document]) -> list[ChunkPayload]:
    return [document_to_payload(document) for document in documents]


def summarize_documents(documents: list[Document]) -> list[DocumentSummary]:
    grouped: dict[str, dict[str, Any]] = {}
    for document in documents:
        meta = dict(document.meta or {})
        document_id = str(meta.get("document_id") or document.id)
        item = grouped.setdefault(
            document_id,
            {
                "document_id": document_id,
                "shop_id": meta.get("shop_id"),
                "source_name": meta.get("source_name"),
                "file_name": meta.get("file_name"),
                "chunks_count": 0,
            },
        )
        item["chunks_count"] += 1
    return [DocumentSummary(**item) for item in grouped.values()]


def unique_documents_by_id(documents: list[Document]) -> list[Document]:
    seen: set[str] = set()
    unique: list[Document] = []
    for document in documents:
        if document.id in seen:
            continue
        seen.add(document.id)
        unique.append(document)
    return unique

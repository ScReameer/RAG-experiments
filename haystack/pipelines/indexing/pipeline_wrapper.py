import hashlib
from typing import Any

from fastapi import UploadFile
from hayhooks import BasePipelineWrapper
from haystack.components.converters import MarkdownToDocument, PyPDFToDocument, TextFileToDocument
from haystack.components.joiners import DocumentJoiner
from haystack.components.preprocessors import DocumentCleaner, DocumentSplitter
from haystack.components.routers import FileTypeRouter
from haystack.components.writers import DocumentWriter
from haystack.dataclasses import ByteStream
from haystack.document_stores.types import DuplicatePolicy
from service.document_store import create_document_store
from service.embedders import create_document_embedder
from service.filters import scoped_filter, validate_identifier
from service.schemas import IndexingResponse
from service.settings import HaystackSettings, get_settings

from haystack import Document, Pipeline


def _stable_document_id(value: str, *, prefix: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _merge_metadata(
    metadata: dict[str, Any] | None,
    *,
    shop_id: str,
    document_id: str,
    source_name: str,
    ingestion_type: str,
    mime_type: str | None = None,
    file_name: str | None = None,
) -> dict[str, Any]:
    meta = dict(metadata or {})
    meta.update(
        {
            "shop_id": shop_id,
            "document_id": document_id,
            "source_name": source_name,
            "ingestion_type": ingestion_type,
        }
    )
    if mime_type:
        meta["mime_type"] = mime_type
    if file_name:
        meta["file_name"] = file_name
    return meta


class PipelineWrapper(BasePipelineWrapper):
    settings: HaystackSettings
    conversion_pipeline: Pipeline

    def setup(self) -> None:
        self.settings = get_settings()

        conversion_pipeline = Pipeline()
        conversion_pipeline.add_component(
            "file_type_router",
            FileTypeRouter(mime_types=["text/plain", "text/markdown", "application/pdf"]),
        )
        conversion_pipeline.add_component("text_file_converter", TextFileToDocument())
        conversion_pipeline.add_component("markdown_converter", MarkdownToDocument())
        conversion_pipeline.add_component("pdf_converter", PyPDFToDocument())
        conversion_pipeline.add_component("document_joiner", DocumentJoiner())
        conversion_pipeline.connect("file_type_router.text/plain", "text_file_converter.sources")
        conversion_pipeline.connect("file_type_router.text/markdown", "markdown_converter.sources")
        conversion_pipeline.connect("file_type_router.application/pdf", "pdf_converter.sources")
        conversion_pipeline.connect("text_file_converter.documents", "document_joiner.documents")
        conversion_pipeline.connect("markdown_converter.documents", "document_joiner.documents")
        conversion_pipeline.connect("pdf_converter.documents", "document_joiner.documents")

        self.conversion_pipeline = conversion_pipeline

    def _create_indexing_pipeline(self, shop_id: str) -> Pipeline:
        document_store = create_document_store(shop_id, self.settings)
        indexing_pipeline = Pipeline()
        indexing_pipeline.add_component("document_cleaner", DocumentCleaner())
        indexing_pipeline.add_component(
            "document_splitter",
            DocumentSplitter(
                split_by=self.settings.split_by,
                split_length=self.settings.split_length,
                split_overlap=self.settings.split_overlap,
            ),
        )
        indexing_pipeline.add_component(
            "document_embedder", create_document_embedder(self.settings)
        )
        indexing_pipeline.add_component(
            "document_writer",
            DocumentWriter(document_store=document_store, policy=DuplicatePolicy.OVERWRITE),
        )
        indexing_pipeline.connect("document_cleaner.documents", "document_splitter.documents")
        indexing_pipeline.connect("document_splitter.documents", "document_embedder.documents")
        indexing_pipeline.connect("document_embedder.documents", "document_writer.documents")
        return indexing_pipeline

    def run_api(
        self,
        shop_id: str,
        document_id: str | None = None,
        text: str | None = None,
        metadata: dict[str, Any] | None = None,
        replace_existing: bool = True,
        files: list[UploadFile] | None = None,
    ) -> dict[str, Any]:
        normalized_shop_id = validate_identifier(shop_id, field_name="shop_id")
        uploaded_files = files or []
        inputs_count = len(uploaded_files) + (1 if text else 0)
        if inputs_count == 0:
            raise ValueError("Provide either text or files")
        if document_id and inputs_count > 1:
            raise ValueError("document_id can be provided only for a single text/file input")

        documents: list[Document] = []
        document_ids: list[str] = []

        if text:
            resolved_document_id = validate_identifier(
                document_id or _stable_document_id(text, prefix="text"),
                field_name="document_id",
            )
            document_ids.append(resolved_document_id)
            documents.append(
                Document(
                    content=text,
                    meta=_merge_metadata(
                        metadata,
                        shop_id=normalized_shop_id,
                        document_id=resolved_document_id,
                        source_name=str(
                            (metadata or {}).get("source_name") or resolved_document_id
                        ),
                        ingestion_type="text",
                        mime_type="text/plain",
                    ),
                )
            )

        byte_streams: list[ByteStream] = []
        for file in uploaded_files:
            file_name = file.filename or "uploaded_file"
            resolved_document_id = validate_identifier(
                document_id or _stable_document_id(file_name, prefix="file"),
                field_name="document_id",
            )
            document_ids.append(resolved_document_id)
            mime_type = file.content_type or "text/plain"
            byte_streams.append(
                ByteStream(
                    data=file.file.read(),
                    mime_type=mime_type,
                    meta=_merge_metadata(
                        metadata,
                        shop_id=normalized_shop_id,
                        document_id=resolved_document_id,
                        source_name=file_name,
                        ingestion_type="file",
                        mime_type=mime_type,
                        file_name=file_name,
                    ),
                )
            )

        if byte_streams:
            conversion_result = self.conversion_pipeline.run(
                {"file_type_router": {"sources": byte_streams}}
            )
            converted_documents = conversion_result["document_joiner"]["documents"]
            documents.extend(converted_documents)

        deleted_chunks = 0
        document_store = create_document_store(normalized_shop_id, self.settings)
        if replace_existing:
            for resolved_document_id in sorted(set(document_ids)):
                filter_expression = scoped_filter(
                    normalized_shop_id,
                    document_id=resolved_document_id,
                )
                if filter_expression is None:
                    raise ValueError("document_id filter is required when replacing a document")
                deleted_chunks += document_store.count_documents_by_filter(filter_expression)
                document_store.delete_by_filter(filter_expression)

        indexing_pipeline = self._create_indexing_pipeline(normalized_shop_id)
        indexing_result = indexing_pipeline.run({"document_cleaner": {"documents": documents}})
        chunks_written = indexing_result["document_writer"]["documents_written"]

        return IndexingResponse(
            shop_id=normalized_shop_id,
            document_ids=sorted(set(document_ids)),
            documents_received=len(documents),
            chunks_deleted=deleted_chunks,
            chunks_written=chunks_written,
            table_name=document_store.table_name,
            table_exists=True,
            embedding_model=self.settings.embedding_model,
            embedding_dimension=self.settings.embedding_dimension,
            vector_type=self.settings.pg_vector_type,
        ).to_payload()

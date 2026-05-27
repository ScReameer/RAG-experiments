from typing import Any

from haystack.components.embedders import OpenAIDocumentEmbedder, OpenAITextEmbedder
from haystack.utils import Secret

from service.settings import HaystackSettings, get_settings


def _openai_kwargs(settings: HaystackSettings) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "api_key": Secret.from_token(settings.embedding_api_key),
        "model": settings.embedding_model,
        "api_base_url": settings.embedding_api_base_url,
    }
    if settings.embedding_api_dimensions is not None:
        kwargs["dimensions"] = settings.embedding_api_dimensions
    return kwargs


def create_document_embedder(
    settings: HaystackSettings | None = None,
) -> OpenAIDocumentEmbedder:
    config = settings or get_settings()
    return OpenAIDocumentEmbedder(
        **_openai_kwargs(config),
        batch_size=config.embedding_batch_size,
        progress_bar=False,
    )


def create_text_embedder(settings: HaystackSettings | None = None) -> OpenAITextEmbedder:
    config = settings or get_settings()
    return OpenAITextEmbedder(**_openai_kwargs(config))

"""Knowledge base (RAG) data shapes."""

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class DocumentMeta(BaseModel):
    """Facts about a source document. Supplied by a person in knowledge/manifest.toml, never invented."""

    file_name: str
    title: str
    publisher: str | None = None
    source_url: str | None = None
    published_on: str | None = None  # as printed on the document, e.g. "2016-04-08"
    jurisdiction: str | None = None  # e.g. "India", "Maharashtra", "KDMC"

    @field_validator("source_url")
    @classmethod
    def _http_only(cls, v: str | None) -> str | None:
        if v and not v.lower().startswith(("https://", "http://")):
            raise ValueError("source_url must start with http:// or https://")
        return v or None


class Chunk(BaseModel):
    index: int
    content: str
    heading: str | None = None
    page_from: int | None = None


class RetrievedChunk(BaseModel):
    content: str
    similarity: float
    title: str
    publisher: str | None = None
    source_url: str | None = None
    published_on: str | None = None
    heading: str | None = None
    page_from: int | None = None
    chunk_index: int = 0


class AnswerMode(StrEnum):
    GROUNDED = "grounded"  # AI answer where every claim carries a citation
    PASSAGES = "passages"  # no AI available: we show the matching passages verbatim
    NO_SOURCE = "no_source"  # nothing relevant in the knowledge base
    UNAVAILABLE = "unavailable"  # knowledge base not set up or a service failed


class AnswerSegment(BaseModel):
    text: str
    source_numbers: list[int] = Field(default_factory=list)  # 1-based, into Answer.sources


class Answer(BaseModel):
    mode: AnswerMode
    question: str
    segments: list[AnswerSegment] = Field(default_factory=list)
    sources: list[RetrievedChunk] = Field(default_factory=list)
    message: str | None = None

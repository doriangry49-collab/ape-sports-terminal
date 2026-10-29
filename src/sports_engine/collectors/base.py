"""Base collector interfaces for bronze layer ingestion."""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class BronzePayload(BaseModel):
    """Raw, immutable source payload container for Bronze layer storage."""

    source_name: str
    endpoint: str
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw_content: Any
    metadata: dict[str, Any] | None = None


class BaseCollector(ABC):
    """Abstract collector defining interface for extracting raw data into Bronze layer.

    Specific collectors (LiveScoreJSON, PropLine, API-Football, etc.) will be implemented
    in subsequent tasks per TASK-001 instructions.
    """

    def __init__(self, source_name: str):
        self.source_name = source_name

    @abstractmethod
    def fetch_raw(self, *args, **kwargs) -> BronzePayload:
        """Fetch raw response payload from upstream source without normalization."""
        pass

"""
Every data source implements this interface. Adding a new sensor/dataset
means writing one new adapter class, not touching the orchestration code
in app/jobs/run_ingestion.py — that's the whole point of the pattern.

    class MyNewSourceAdapter(IngestionAdapter):
        name = "my_new_source"

        def fetch(self, **kwargs) -> Any:
            ...  # hit the API / download the file

        def to_records(self, raw: Any) -> list[dict]:
            ...  # normalize into plain dicts ready for the DB layer
"""
from abc import ABC, abstractmethod
from typing import Any


class IngestionAdapter(ABC):
    name: str = "base"

    @abstractmethod
    def fetch(self, **kwargs) -> Any:
        """Hit the external API / download the file. Returns raw data
        (DataFrame, GeoJSON dict, raster path — whatever is natural for
        this source). Should raise on failure; the job runner decides
        whether that's fatal or skippable per-source."""
        raise NotImplementedError

    @abstractmethod
    def to_records(self, raw: Any) -> list[dict]:
        """Normalize raw fetch() output into a list of plain dicts matching
        (a subset of) the Hotspot/ORM column names, ready for bulk insert."""
        raise NotImplementedError

    def run(self, **kwargs) -> list[dict]:
        raw = self.fetch(**kwargs)
        return self.to_records(raw)

from abc import ABC, abstractmethod

from impurity_leads.models import SourceRecord


class SourceAdapter(ABC):
    name: str

    @abstractmethod
    def parse(self, payload: dict) -> list[SourceRecord]:
        raise NotImplementedError

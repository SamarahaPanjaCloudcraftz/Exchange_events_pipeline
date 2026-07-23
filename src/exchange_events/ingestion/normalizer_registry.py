"""Maps a source's name to its normalizer (design doc §5.3, §8.2)."""

from __future__ import annotations

from collections.abc import Iterable

from ..contracts.normalizer import EventNormalizer


class NormalizerRegistry:
    def __init__(self, normalizers: dict[str, EventNormalizer] | None = None) -> None:
        self._by_source: dict[str, EventNormalizer] = dict(normalizers or {})

    @classmethod
    def from_list(cls, normalizers: Iterable[EventNormalizer]) -> NormalizerRegistry:
        """Build a registry keyed by each normalizer's own ``target_source()``."""
        return cls({n.target_source(): n for n in normalizers})

    def register(self, normalizer: EventNormalizer) -> None:
        self._by_source[normalizer.target_source()] = normalizer

    def get(self, source_name: str) -> EventNormalizer | None:
        return self._by_source.get(source_name)

    def __contains__(self, source_name: str) -> bool:
        return source_name in self._by_source

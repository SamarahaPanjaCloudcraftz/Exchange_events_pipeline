"""ISM normalizer (design doc §5.2) — best-effort ISM Manufacturing PMI only.

Not part of the official-statistics tier (FRED/BLS/BEA): ISM's Manufacturing PMI
has been licensed/proprietary data since FRED discontinued its ISM series in 2016
(see DECISIONS.md's "Economic-release waterfall" entry). This normalizer is
scoped to exactly one release code and depends on whichever aggregator
``adapters/ism.py`` is configured against; it degrades to "no data" rather than
blocking the other six releases when unavailable. Thin subclass of
:class:`GovernmentReleaseNormalizer` — same raw-record shape applies.
"""

from __future__ import annotations

from .government_release import GovernmentReleaseNormalizer


class ISMNormalizer(GovernmentReleaseNormalizer):
    def target_source(self) -> str:
        return "ism_pmi"

"""
Optional suggested sectors for the CSV preview.

The split this package exists to enforce: **the lookup proposes, the user
confirms, the stored row is truth.** A suggestion is shown to a person beside
an editable sector; only what that person saves reaches `Position.sector`,
which is all evaluation ever reads. Nothing here runs during ingestion or a
comparison, so a model that answers differently tomorrow cannot change a
number today (NFR-2, guarded by tests/golden).

Off by default. With the flag off the SDK is never imported, nothing leaves the
process, and the preview still lets the user set any sector by hand — the
feature is complete without this package.

  payload.py   what may leave the process: ticker symbols only (NFR-3)
  prompt.py    the versioned prompt
  schema.py    what the model returns: a classification per symbol
  validate.py  checking each classification (the honesty boundary)
  client.py    the only network call
  cache.py     in-process per-ticker LRU, keyed on model + prompt version
  service.py   cache -> payload -> client -> validate -> merge
"""

from .cache import SectorLookupCache, lookup_cache_key
from .client import SectorLookupClient, get_client
from .payload import LookupPayload, build_payload, is_symbol, normalize_symbol
from .prompt import PROMPT_VERSION
from .service import LookupResult, cached_suggestions, lookup_sectors
from .validate import SectorSuggestion

__all__ = [
    "LookupPayload",
    "LookupResult",
    "PROMPT_VERSION",
    "SectorLookupCache",
    "SectorLookupClient",
    "SectorSuggestion",
    "build_payload",
    "cached_suggestions",
    "get_client",
    "is_symbol",
    "lookup_cache_key",
    "lookup_sectors",
    "normalize_symbol",
]

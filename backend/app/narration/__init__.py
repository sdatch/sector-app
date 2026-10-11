"""
Optional LLM narration for suggested sector shifts.

The split this package exists to enforce: **the math decides, the model only
narrates.** `engines/common/shifts.py` chooses which moves appear and computes
every number on them; nothing here can change either. An LLM that picked or
scored a move would break determinism (NFR-2, guarded by tests/golden) and
traceability (NFR-5, every metric tied to an EstimationMethod).

Off by default. With the flag off the SDK is never imported, no request leaves
the process, and the client renders its own deterministic copy — the feature is
complete without this package.

  payload.py   what may leave the process        (the privacy boundary, NFR-3)
  prompt.py    the versioned prompt
  schema.py    what the model returns: prose only
  validate.py  checking prose against the figures (the honesty boundary)
  client.py    the only network call
  cache.py     in-process LRU, keyed on the comparison + prompt version
  service.py   cache -> payload -> client -> validate -> fallback
"""

from .cache import NarrationCache, narration_cache_key
from .client import NarrationClient, get_client
from .prompt import PROMPT_VERSION
from .service import NarratedMoveResult, NarrationResult, narrate

__all__ = [
    "NarrationCache",
    "NarrationClient",
    "NarrationResult",
    "NarratedMoveResult",
    "PROMPT_VERSION",
    "get_client",
    "narrate",
    "narration_cache_key",
]

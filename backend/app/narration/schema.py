"""
What the narration model is asked to return: prose, and nothing else.

There is no metric here by design (PRD NFR-5). The numbers the user sees are
rendered by the client from the `ComparisonResource` it already holds; this
layer only supplies the sentence beside them. `from_sector`/`to_sector` are
echoed back so the result can be tied to a specific shift — and so the
validator can reject a reply that invented a fourth move or reordered them.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class NarratedMove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_sector: str = Field(description="Echoed from the move being explained")
    to_sector: str = Field(description="Echoed from the move being explained")
    text: str = Field(description="One or two sentences explaining the move")


class NarrationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    moves: list[NarratedMove]

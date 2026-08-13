"""Request and response shapes for authentication."""

import uuid

from pydantic import BaseModel


class Identity(BaseModel):
    """What the API will admit about the caller to the caller.

    Deliberately only the identifier. `CLAUDE.md` requires minimum necessary
    fields, and this endpoint's job is answering "is this credential still
    good", not returning a profile.
    """

    user_id: uuid.UUID

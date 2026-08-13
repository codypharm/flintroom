"""Request and response shapes for authentication."""

import uuid

from pydantic import BaseModel, Field


class Identity(BaseModel):
    """What the API will admit about the caller to the caller.

    Deliberately only the identifier. `CLAUDE.md` requires minimum necessary
    fields, and this endpoint's job is answering "is this credential still
    good", not returning a profile.
    """

    user_id: uuid.UUID


class SignInRequest(BaseModel):
    """What the app sends after a native Sign in with Apple or Google.

    `provider` is a plain string rather than an enum on purpose. A closed set
    would answer an unrecognised value with a 422 listing the ones we accept,
    which enumerates our configuration; an unknown provider is refused as an
    invalid sign-in instead.
    """

    provider: str = Field(min_length=1, max_length=32)
    id_token: str = Field(min_length=1, max_length=8192)


class SignedIn(BaseModel):
    """The credential the app stores and sends back on every request.

    No refresh token yet — that is its own slice. Until then a session lasts
    the access token's lifetime and the user signs in again, which is correct
    but not yet comfortable.
    """

    access_token: str
    token_type: str = "bearer"
    #: Seconds. The client refreshes on this rather than parsing the token,
    #: which keeps the token opaque to the app and its format ours to change.
    expires_in: int

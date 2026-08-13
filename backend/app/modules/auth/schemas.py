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


class RefreshRequest(BaseModel):
    """The stored credential, offered in exchange for a fresh pair."""

    refresh_token: str = Field(min_length=1, max_length=512)


class SignedIn(BaseModel):
    """The credential pair the app stores.

    Both are returned by sign-in and by every refresh, because the refresh
    token rotates on use. A client that keeps the old one will be treated as a
    replay and lose the session, so "always store both" is the contract.
    """

    access_token: str
    #: Rotates on every use. Never logged, and never put in a URL — it is the
    #: credential that outlives the access token by weeks.
    refresh_token: str
    token_type: str = "bearer"
    #: Seconds. The client refreshes on this rather than parsing the token,
    #: which keeps the token opaque to the app and its format ours to change.
    expires_in: int

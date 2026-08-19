"""Request and response shapes for authentication."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.onboarding.schemas import Answers


class Identity(BaseModel):
    """What the API will admit about the caller to the caller.

    Still not a profile. `CLAUDE.md` requires minimum necessary fields, and this
    endpoint's job is answering "is this credential still good" — plus, since
    2026-08-20, the one other thing the launch gate has to know before it can
    draw anything.
    """

    user_id: uuid.UUID

    #: Whether this account has ever described a room it is preparing for.
    #:
    #: Here rather than on an endpoint of its own, because the client asks both
    #: questions at the same instant: `read_current_identity`'s own docstring
    #: says "the mobile client calls this on launch", and a second round trip on
    #: the slowest screen in the product buys nothing.
    #:
    #: **Keyed to the account, never to the install.** A reinstall is the moment
    #: a returning user most needs to be left alone, and a local flag is exactly
    #: what a reinstall destroys.
    #:
    #: Not a profile field and not personal: it is a boolean about whether a
    #: form was filled, which reveals nothing about what was said in it.
    onboarded: bool = False


class SignInRequest(BaseModel):
    """What the app sends after a native Sign in with Apple or Google.

    `provider` is a plain string rather than an enum on purpose. A closed set
    would answer an unrecognised value with a 422 listing the ones we accept,
    which enumerates our configuration; an unknown provider is refused as an
    invalid sign-in instead.
    """

    provider: str = Field(min_length=1, max_length=32)
    id_token: str = Field(min_length=1, max_length=8192)

    #: The plan they filled in, on the one request that carries it.
    #:
    #: `docs/onboarding.md` holds the answers on-device through the survey and
    #: posts them here rather than afterwards — *"a partially-created account
    #: with no configuration is a state worth not having"*. A second call could
    #: fail on its own and leave an account that exists and has been asked
    #: nothing.
    #:
    #: Absent on every launch after the first, which is why it is optional
    #: rather than defaulted: sign-in runs each time the app opens, and a
    #: missing block must mean "nothing new to say", never "forget what I told
    #: you".
    onboarding: Answers | None = None


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

    #: Whether this sign-in called off a scheduled deletion.
    #:
    #: `docs/account-deletion.md` decision 5, and the app owes the user a
    #: sentence when it is true — an account that quietly un-deletes itself is
    #: worse than one that stayed deleted.
    #:
    #: Defaulted, and refresh never sets it. Rotating a token is not somebody
    #: coming back, so a refresh that reported a cancellation would be claiming
    #: an event that did not happen.
    deletion_cancelled: bool = False


class DeletionScheduled(BaseModel):
    """When an account that asked to be deleted actually goes.

    The date rather than a bare acknowledgement, because the window is
    recoverable and a user who is not told when it closes cannot use it. It is
    also what makes the repeat request legible: asking twice returns the same
    moment, which is the wire-level expression of a window that does not move.

    Nothing else is returned. `CLAUDE.md` wants minimum necessary fields, and
    the caller already knows whose account this is — they authenticated as
    them.
    """

    purge_at: datetime

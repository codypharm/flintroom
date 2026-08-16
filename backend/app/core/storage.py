"""The seam an object store plugs into.

Structural (`Protocol`) rather than inherited, for the same reason
`voice.provider` is one: an adapter is a class that happens to fit rather than
one that had to import us, so a vendor SDK wrapper never acquires a dependency
on our module graph.

**The contract is the presigned URL, not the vendor SDK** (CLAUDE.md). Every
method here returns a URL the caller hands to the client, or acts on a key.
Nothing returns bytes, because a method that returned bytes would be the
proxying that uploaded material is forbidden to go through.

Two levels of escape, and they cost differently. Moving between S3, R2, B2 or a
self-hosted MinIO is an endpoint and a credential — the implementation below
speaks all of them. This Protocol buys the second level: a store that is not
S3-shaped at all is a sibling module, and no caller changes.
"""

from __future__ import annotations

from typing import Protocol


class ObjectStorage(Protocol):
    """Somewhere to put a deck, and a way to hand it back out again."""

    def presign_put(self, key: str, *, content_length: int, content_type: str) -> str:
        """A URL the client may upload one object to, for a short while.

        The size and the type are arguments rather than advice because both are
        signed. SigV4 covers every header it lists in `SignedHeaders`, so a body
        of a different length, or sent under a different type, produces a
        signature that does not match and the store refuses it. That is what
        turns a tier's byte cap from a number we validated once into a property
        of the upload itself — a client cannot ask for a URL saying eight
        megabytes and then send four hundred.

        The exactness is the cost: this signs one length, not a range, so a
        client that does not know its own file size cannot upload. Every source
        we accept comes from a file handle that does.

        Not `async`: signing is an HMAC chain over a canonical request and
        touches no network. Making it a coroutine would advertise IO that never
        happens and force every caller to await something instantaneous.
        """
        ...

    def presign_get(self, key: str) -> str:
        """A URL that reads one object, for a short while.

        Scoped to a single key by construction. Whether the caller is allowed to
        read that key is the service's question, answered before it asks for a
        URL — this layer signs what it is told to sign.
        """
        ...

    async def exists(self, key: str) -> bool:
        """Whether an object is actually there.

        Asked once, at the end of the upload handshake. The client saying the
        bytes landed is the only signal we have that they did, and a material
        that enters the extraction queue pointing at nothing costs a claim, a
        model call that fails, and a requeue — all of it for an object that was
        never written.

        Returns whether, not what. A method that returned the object would be
        the proxying this interface exists to avoid.
        """
        ...

    async def delete(self, key: str) -> None:
        """Remove one object.

        The only method here that touches the network, and so the only one that
        is a coroutine. `docs/ingestion.md` calls this once extraction succeeds:
        the claims and a thumbnail survive, the uploaded deck does not.
        """
        ...

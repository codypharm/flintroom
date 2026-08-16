"""`ObjectStorage` over anything that speaks S3.

The endpoint is configuration, so this one class is MinIO in development, and
AWS S3, Cloudflare R2 or Backblaze B2 in production, with no branch and nothing
recompiled. That is the whole reason development runs a real S3 server rather
than a filesystem stub — the code exercised here is the code that deploys.

boto3 is confined to this module. `ObjectStorage` is what the rest of the
application depends on, so replacing the SDK, or leaving the S3 API entirely,
touches one file.
"""

from __future__ import annotations

import asyncio

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import Settings
from app.core.storage import ObjectStorage

#: How long a signed URL stays valid. Short, because these URLs are bearer
#: credentials for one object: whoever holds one can use it, and a deck is the
#: most confidential thing this product will ever store. Long enough that an
#: upload over a bad mobile connection finishes, which is the constraint that
#: stops it being shorter.
DEFAULT_EXPIRY_SECONDS = 15 * 60


class S3ObjectStorage:
    """One bucket, addressed by key.

    The bucket is fixed at construction rather than passed per call. A caller
    that can choose the bucket is a caller that can be persuaded to choose the
    wrong one, and nothing in this product has a second bucket to choose.
    """

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        region: str,
        addressing_style: str = "virtual",
        expiry_seconds: int = DEFAULT_EXPIRY_SECONDS,
    ) -> None:
        self._bucket = bucket
        self._expiry_seconds = expiry_seconds
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            config=Config(
                signature_version="s3v4",
                # Virtual-hosted by default; see `Settings.s3_addressing_style`
                # for why the deprecated style is not the one baked in. Only the
                # hostname differs — SigV4 signs `Host` either way, so the
                # signing and upload paths development exercises are the ones
                # production runs.
                s3={"addressing_style": addressing_style},
            ),
        )

    def presign_put(self, key: str, *, content_length: int, content_type: str) -> str:
        """Sign one object, at one size, of one type.

        Both extra params land in `SignedHeaders`, which is what makes them
        binding rather than declarative — verified against a real server in
        `tests/test_storage.py` rather than assumed from the SDK's shape.

        A consequence worth knowing before a 100MB tier is real: this is a
        single PUT, so a dropped mobile connection restarts the whole upload.
        The fix when it bites is a multipart presign, which is why the SDK that
        already implements one is the one in this module.
        """
        return self._client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "ContentLength": content_length,
                "ContentType": content_type,
            },
            ExpiresIn=self._expiry_seconds,
        )

    def presign_get(self, key: str) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=self._expiry_seconds,
        )

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        """Write one object, off the event loop.

        No presign and no signature dance: this call is already authenticated by
        the client's own credentials, and the size is whatever we just rendered
        rather than something a caller declared and might be lying about.
        """
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    async def get(self, key: str) -> bytes | None:
        """Read one object into memory, off the event loop.

        Whole rather than streamed, because the caller renders every page of it
        and a PDF cannot be parsed from a prefix. The ceiling is the tier's
        upload cap, which is the number to look at if this ever needs to be
        spooled to disk instead — 100MB at the top rung, held by one worker at
        a time.

        The 404 is caught and the rest re-raised, for the reason `exists` gives
        just below: a 403 read as "no object" is somebody's deck marked failed
        because a credential expired.
        """
        try:
            response = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=key
            )
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                return None
            raise
        return await asyncio.to_thread(response["Body"].read)

    async def exists(self, key: str) -> bool:
        """HEAD, and read the absence rather than letting it raise.

        `ClientError` is caught narrowly and only for 404: any other status —
        403 from a bad credential, 503 from a store having a bad day — is a real
        failure and must not be reported to the caller as "the user never
        uploaded", which is the answer that silently loses their deck.
        """
        try:
            await asyncio.to_thread(
                self._client.head_object, Bucket=self._bucket, Key=key
            )
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                return False
            raise
        return True

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(
            self._client.delete_object, Bucket=self._bucket, Key=key
        )


def build_object_storage(settings: Settings) -> ObjectStorage | None:
    """The configured store, or nothing if this deployment has no bucket.

    Lives beside the implementation rather than in a package `__init__` the way
    `build_voice_provider` does, because there is only one implementation to
    choose between and no prospect of a second: S3, R2, B2 and MinIO are all
    this class with a different endpoint. If a store that is genuinely not
    S3-shaped ever lands, this function moves and nothing else does.

    All four fields or none. Partial configuration builds a client that signs
    URLs the store will reject, and that surfaces as a 403 at upload time
    rather than as a missing variable at boot.
    """
    if not (
        settings.s3_endpoint_url
        and settings.s3_access_key_id
        and settings.s3_secret_access_key
        and settings.s3_bucket
    ):
        return None

    return S3ObjectStorage(
        endpoint_url=settings.s3_endpoint_url,
        access_key_id=settings.s3_access_key_id,
        secret_access_key=settings.s3_secret_access_key,
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        addressing_style=settings.s3_addressing_style,
    )

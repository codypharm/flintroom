"""Object storage, exercised against a real S3 server rather than a stub.

`docs/ingestion.md` refused a filesystem shim for development on the grounds
that a filesystem cannot do direct-to-storage PUT without proxying — the thing
production forbids — so a shim would leave the presigned path unexercised until
deploy. This module is the cash-out of that decision: MinIO is in
`docker-compose.yml`, and these tests sign a URL and then actually use it.
"""

import os
import uuid

import httpx
import pytest

from app.core.config import Settings
from app.core.storage_s3 import S3ObjectStorage, build_object_storage

TEST_S3_ENDPOINT_URL = os.getenv("TEST_S3_ENDPOINT_URL", "http://localhost:59000")
TEST_S3_BUCKET = os.getenv("TEST_S3_BUCKET", "flintroom-material")


@pytest.fixture
def storage() -> S3ObjectStorage:
    return S3ObjectStorage(
        endpoint_url=TEST_S3_ENDPOINT_URL,
        access_key_id="flintroom",
        secret_access_key="flintroom",
        bucket=TEST_S3_BUCKET,
        region="us-east-1",
        addressing_style="path",
    )


async def test_presigned_put_accepts_bytes_a_presigned_get_returns(storage):
    """The tracer bullet: a signed URL round-trips real bytes through real S3.

    Deliberately asserts on content rather than on the shape of the URL. What
    the signature looks like is the vendor's business and changes with the
    signing version; whether the object arrived is ours.
    """
    key = f"test/{uuid.uuid4()}.pdf"
    body = b"%PDF-1.7 a deck, for the purposes of this test"

    async with httpx.AsyncClient() as http:
        stored = await http.put(storage.presign_put(key), content=body)
        assert stored.status_code == 200, stored.text

        fetched = await http.get(storage.presign_get(key))

    assert fetched.status_code == 200, fetched.text
    assert fetched.content == body


async def test_delete_removes_the_object(storage):
    """`docs/ingestion.md` deletes the source document once extraction succeeds.

    That is a promise made to a privacy policy and to the App Store review
    questionnaire, so it is worth proving against a real store rather than
    against a mock that records the call and deletes nothing.
    """
    key = f"test/{uuid.uuid4()}.pdf"

    async with httpx.AsyncClient() as http:
        await http.put(storage.presign_put(key), content=b"a deck")

        await storage.delete(key)

        fetched = await http.get(storage.presign_get(key))

    assert fetched.status_code == 404


def test_signed_urls_carry_the_lifetime_they_were_configured_with():
    """A signed URL is a bearer credential for one object, so its life is short.

    Asserted on the URL rather than by waiting out a clock: the failure worth
    catching is `ExpiresIn` never being passed at all, which leaves boto3's own
    default of an hour in place — four times what we chose, and silent. A
    wall-clock test would prove S3 honours the field, which is not our bug to
    have. `X-Amz-Expires` is part of the SigV4 query protocol rather than a
    boto3 detail, so this survives an SDK change.
    """
    storage = S3ObjectStorage(
        endpoint_url=TEST_S3_ENDPOINT_URL,
        access_key_id="flintroom",
        secret_access_key="flintroom",
        bucket=TEST_S3_BUCKET,
        region="us-east-1",
        addressing_style="path",
        expiry_seconds=90,
    )

    for url in (storage.presign_put("deck.pdf"), storage.presign_get("deck.pdf")):
        assert "X-Amz-Expires=90" in url


#: The required half of a valid environment, so the storage cases below can add
#: to it. Kept separate from `test_config.COMPLETE` rather than imported: these
#: tests are about storage being *absent*, and borrowing another module's idea
#: of complete would make them fail for its reasons.
BASE_ENVIRONMENT = {
    "DATABASE_URL": "postgresql+asyncpg://user:pw@localhost:5432/flintroom",
    "JWT_SECRET": "x" * 48,
    "GOOGLE_CLIENT_ID": "297.apps.googleusercontent.com",
    "APPLE_CLIENT_ID": "com.flintroom.app",
}


def test_storage_is_absent_when_the_deployment_has_no_credentials():
    """No bucket configured is an unconfigured integration, not a broken boot.

    The same trade `Settings.elevenlabs_api_key` makes: a missing signing key is
    an insecure default and must never start, whereas a missing bucket takes
    only ingestion down. Refusing to boot would stop auth, balances and the
    voice loop over a feature none of them use.
    """
    settings = Settings(_env_file=None, **BASE_ENVIRONMENT)

    assert build_object_storage(settings) is None


def test_storage_is_built_when_every_field_is_present():
    """Partial configuration counts as absent — see the test above for why.

    All four fields or none. A bucket without a secret key produces a client
    that signs URLs nothing will accept, and the failure surfaces at upload
    time as a 403 rather than at boot as a missing variable.
    """
    settings = Settings(
        _env_file=None,
        **BASE_ENVIRONMENT,
        S3_ENDPOINT_URL=TEST_S3_ENDPOINT_URL,
        S3_ACCESS_KEY_ID="flintroom",
        S3_SECRET_ACCESS_KEY="flintroom",
        S3_BUCKET=TEST_S3_BUCKET,
    )

    storage = build_object_storage(settings)

    assert isinstance(storage, S3ObjectStorage)


def test_addressing_defaults_to_virtual_hosted_style():
    """Path-style is the deprecated one, and only MinIO needs it.

    AWS: *"path-style URLs will be discontinued in the future"* — delayed in
    September 2020 with no replacement date and a promise of a year's notice, so
    it works everywhere today and is nonetheless the wrong thing to hardcode
    into production. Development overrides this for MinIO, which has no DNS to
    put a bucket name in front of; that override is the exception and lives in
    configuration, not in the default.

    Signed offline against an endpoint nothing is listening on — the assertion
    is about which host the URL names, and reaching it would prove nothing.
    """
    settings = Settings(
        _env_file=None,
        **BASE_ENVIRONMENT,
        S3_ENDPOINT_URL="https://s3.eu-west-2.amazonaws.com",
        S3_ACCESS_KEY_ID="key",
        S3_SECRET_ACCESS_KEY="secret",
        S3_BUCKET="flintroom-material",
        S3_REGION="eu-west-2",
    )

    url = build_object_storage(settings).presign_get("deck.pdf")

    assert url.startswith(
        "https://flintroom-material.s3.eu-west-2.amazonaws.com/deck.pdf?"
    ), url


def test_addressing_style_is_configurable_for_stores_without_dns():
    """MinIO, and anything else addressed by path. The dev default, set once."""
    settings = Settings(
        _env_file=None,
        **BASE_ENVIRONMENT,
        S3_ENDPOINT_URL=TEST_S3_ENDPOINT_URL,
        S3_ACCESS_KEY_ID="flintroom",
        S3_SECRET_ACCESS_KEY="flintroom",
        S3_BUCKET=TEST_S3_BUCKET,
        S3_ADDRESSING_STYLE="path",
    )

    url = build_object_storage(settings).presign_get("deck.pdf")

    assert url.startswith(f"{TEST_S3_ENDPOINT_URL}/{TEST_S3_BUCKET}/deck.pdf?"), url

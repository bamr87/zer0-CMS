"""A software passkey for the tests: what a browser and a platform
authenticator answer to WebAuthn's create() and get(), built from python-fido2's
own data types and an EC P-256 key — so allauth's Fido2Server verifies a real
attestation ("none") and a real signature, with no device and no network."""

import hashlib
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fido2.cose import ES256
from fido2.utils import websafe_decode, websafe_encode
from fido2.webauthn import AttestationObject, AttestedCredentialData, AuthenticatorData, CollectedClientData

FLAGS = AuthenticatorData.FLAG
ORIGIN = "http://testserver"


class Passkey:
    def __init__(self, origin: str = ORIGIN):
        self.origin = origin
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(16)
        self.user_handle: str | None = None
        self.counter = 0

    def create(self, options: dict) -> dict:
        """The registration response to `creation_options` (WebAuthn's PublicKeyCredential, as JSON)."""
        public_key = options["publicKey"]
        self.rp_id = public_key["rp"]["id"]
        self.user_handle = public_key["user"]["id"]
        attested = AttestedCredentialData.create(
            b"\0" * 16, self.credential_id, ES256.from_cryptography_key(self.key.public_key())
        )
        auth_data = AuthenticatorData.create(
            hashlib.sha256(self.rp_id.encode()).digest(), FLAGS.UP | FLAGS.UV | FLAGS.AT, self.counter, attested
        )
        client_data = CollectedClientData.create(
            "webauthn.create", websafe_decode(public_key["challenge"]), self.origin
        )
        encoded = websafe_encode(self.credential_id)
        return {
            "id": encoded,
            "rawId": encoded,
            "type": "public-key",
            "response": {
                "clientDataJSON": websafe_encode(bytes(client_data)),
                "attestationObject": websafe_encode(bytes(AttestationObject.create("none", auth_data, {}))),
                "transports": ["internal"],
            },
            "clientExtensionResults": {"credProps": {"rk": True}},
            "authenticatorAttachment": "platform",
        }

    def get(self, options: dict) -> dict:
        """The assertion for `request_options`, signed with the passkey's key."""
        public_key = options["publicKey"]
        self.counter += 1
        auth_data = AuthenticatorData.create(
            hashlib.sha256(self.rp_id.encode()).digest(), FLAGS.UP | FLAGS.UV, self.counter
        )
        client_data = CollectedClientData.create("webauthn.get", websafe_decode(public_key["challenge"]), self.origin)
        signature = self.key.sign(bytes(auth_data) + client_data.hash, ec.ECDSA(hashes.SHA256()))
        encoded = websafe_encode(self.credential_id)
        return {
            "id": encoded,
            "rawId": encoded,
            "type": "public-key",
            "response": {
                "clientDataJSON": websafe_encode(bytes(client_data)),
                "authenticatorData": websafe_encode(bytes(auth_data)),
                "signature": websafe_encode(signature),
                "userHandle": self.user_handle,
            },
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
        }

import hmac
import hashlib
import pytest
from github_action_triage.app.web.signature import verify_github_signature


def test_verify_valid_signature():
    payload = b'{"test": "payload"}'
    secret = "my-secret"
    
    computed_hmac = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256
    )
    signature = f"sha256={computed_hmac.hexdigest()}"
    
    assert verify_github_signature(payload, signature, secret) is True


def test_verify_invalid_signature():
    payload = b'{"test": "payload"}'
    secret = "my-secret"
    signature = "sha256=invalid_signature"
    
    assert verify_github_signature(payload, signature, secret) is False


def test_verify_wrong_secret():
    payload = b'{"test": "payload"}'
    secret = "my-secret"
    
    computed_hmac = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256
    )
    signature = f"sha256={computed_hmac.hexdigest()}"
    
    assert verify_github_signature(payload, signature, "wrong-secret") is False


def test_verify_missing_signature_prefix():
    payload = b'{"test": "payload"}'
    secret = "my-secret"
    signature = "invalid_format"
    
    assert verify_github_signature(payload, signature, secret) is False


def test_verify_empty_secret():
    payload = b'{"test": "payload"}'
    signature = "sha256=some_signature"
    
    assert verify_github_signature(payload, signature, "") is False


def test_verify_empty_signature():
    payload = b'{"test": "payload"}'
    secret = "my-secret"
    
    assert verify_github_signature(payload, "", secret) is False

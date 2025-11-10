import hashlib
import hmac


def verify_github_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook signature using HMAC SHA-256.

    Args:
        payload: Raw webhook payload bytes
        signature: Signature from X-Hub-Signature-256 header (format: "sha256=...")
        secret: GitHub webhook secret

    Returns:
        True if signature is valid, False otherwise
    """
    if not secret:
        return False

    if not signature or not signature.startswith("sha256="):
        return False

    expected_signature = signature.removeprefix("sha256=")
    computed_hmac = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256)
    computed_signature = computed_hmac.hexdigest()

    return hmac.compare_digest(computed_signature, expected_signature)

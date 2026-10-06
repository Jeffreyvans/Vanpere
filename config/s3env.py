"""Resolve S3-compatible object-storage settings from the environment.

Accepts the standard AWS_* names first (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
AWS_STORAGE_BUCKET_NAME, AWS_S3_ENDPOINT_URL, AWS_S3_REGION_NAME,
AWS_S3_SIGNATURE_VERSION, AWS_S3_ADDRESSING_STYLE) and falls back to the legacy
S3_* names used by earlier deployments, so existing environments keep working.

Placeholder values left in templates (YOUR_R2_ENDPOINT, <ACCOUNT_ID>..., change-me,
empty strings) are treated as unset so they can never reach boto3 and raise
"ValueError: Invalid endpoint". No value here is ever logged or exposed to the
browser; credentials stay server-side and are passed straight to boto3.
"""
import re

_PLACEHOLDER = re.compile(
    r"^(your[_-]|<.*>|change[-_]?me|placeholder|example[_-]?|xxx+$|todo|tbd)", re.IGNORECASE)
_EMPTY = {"", "none", "null", "undefined"}


def _clean(value):
    v = (value or "").strip()
    if v.lower() in _EMPTY or _PLACEHOLDER.match(v):
        return ""
    return v


def _first(env, *keys):
    for key in keys:
        if v := _clean(env.get(key)):
            return v
    return ""


def s3_env(env):
    """Return cleaned S3 settings dict (never contains placeholder values)."""
    endpoint = _first(env, "AWS_S3_ENDPOINT_URL", "S3_ENDPOINT_URL")
    bucket = _first(env, "AWS_STORAGE_BUCKET_NAME", "S3_BUCKET")
    access_key_id = _first(env, "AWS_ACCESS_KEY_ID", "S3_ACCESS_KEY_ID")
    secret_access_key = _first(env, "AWS_SECRET_ACCESS_KEY", "S3_SECRET_ACCESS_KEY")
    signature_version = _first(env, "AWS_S3_SIGNATURE_VERSION", "S3_SIGNATURE_VERSION") or "s3v4"
    region = _first(env, "AWS_S3_REGION_NAME", "S3_REGION")
    if not region:
        # A custom endpoint needs an explicit signing region: "auto" is what
        # Filebase expects; otherwise defer to boto3's normal chain.
        region = _first(env, "AWS_DEFAULT_REGION", "AWS_REGION") or ("auto" if endpoint else "")
    addressing_style = _first(env, "AWS_S3_ADDRESSING_STYLE", "S3_ADDRESSING_STYLE")
    if not addressing_style:
        # Path style works with every S3-compatible endpoint (Filebase, B2,
        # Wasabi); "virtual" would need bucket.<endpoint> DNS.
        addressing_style = "path" if endpoint else "auto"
    return {
        "endpoint": endpoint or None,
        "region": region or None,
        "bucket": bucket,
        "access_key_id": access_key_id,
        "secret_access_key": secret_access_key,
        "signature_version": signature_version,
        "addressing_style": addressing_style,
    }

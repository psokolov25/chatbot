import logging
import os
from typing import Any, Mapping


DEFAULT_LOG_LEVEL = "INFO"
PII_KEYS = {
    "telegramcustomerid",
    "telegramcustomerfullname",
    "customerid",
    "customername",
    "phone",
    "email",
    "passport",
}


def get_log_level(default: str = DEFAULT_LOG_LEVEL) -> int:
    raw_level = os.getenv("LOG_LEVEL", default).strip().upper()
    return getattr(logging, raw_level, logging.INFO)


def sanitize_payload(payload: Mapping[str, Any]) -> dict:
    sanitized = {}
    for key, value in payload.items():
        if key.lower() in PII_KEYS and value is not None:
            sanitized[key] = "***"
        elif isinstance(value, dict):
            sanitized[key] = sanitize_payload(value)
        else:
            sanitized[key] = value
    return sanitized

"""Tests for utils.crypto — Fernet-based header encryption."""
import json

import pytest
from cryptography.fernet import Fernet

from utils import crypto


@pytest.fixture
def fernet_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("API_HEADERS_KEY", key)
    return key


def test_encrypt_then_decrypt_round_trip(fernet_key):
    headers = {"Authorization": "Bearer abc123", "X-Custom": "value"}
    encrypted = crypto.encrypt_headers(headers)
    assert encrypted != json.dumps(headers)
    assert crypto.decrypt_headers(encrypted) == headers


def test_encrypt_without_key_returns_plaintext_json(monkeypatch):
    monkeypatch.delenv("API_HEADERS_KEY", raising=False)
    headers = {"k": "v"}
    result = crypto.encrypt_headers(headers)
    assert json.loads(result) == headers


def test_decrypt_plaintext_when_key_absent(monkeypatch):
    monkeypatch.delenv("API_HEADERS_KEY", raising=False)
    plaintext = json.dumps({"k": "v"})
    assert crypto.decrypt_headers(plaintext) == {"k": "v"}


def test_decrypt_plaintext_fallback_when_token_invalid(fernet_key):
    plaintext = json.dumps({"k": "v"})
    assert crypto.decrypt_headers(plaintext) == {"k": "v"}


def test_decrypt_garbage_returns_empty_dict(fernet_key):
    assert crypto.decrypt_headers("not-json-not-fernet") == {}


def test_invalid_key_disables_encryption(monkeypatch):
    monkeypatch.setenv("API_HEADERS_KEY", "not-a-valid-fernet-key")
    headers = {"k": "v"}
    result = crypto.encrypt_headers(headers)
    assert json.loads(result) == headers


def test_round_trip_with_unicode_values(fernet_key):
    headers = {"X-Lang": "繁體中文", "emoji": "🚀"}
    encrypted = crypto.encrypt_headers(headers)
    assert crypto.decrypt_headers(encrypted) == headers

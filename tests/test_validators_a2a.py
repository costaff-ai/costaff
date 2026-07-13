"""Tests for utils.validators._validate_a2a_url SSRF hardening.

The a2a_url validator now DNS-resolves and rejects hostnames that map to
loopback or the link-local / cloud-metadata range — even via a custom
domain (DNS rebinding) — while still allowing private LAN ranges, which
internal agents and enterprise-federation nodes legitimately use.
"""
import socket

import pytest

from utils import validators


def _patch_resolve(monkeypatch, ip: str):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0))]
    monkeypatch.setattr(validators.socket, "getaddrinfo", fake_getaddrinfo)


def test_scheme_rejected():
    with pytest.raises(ValueError):
        validators._validate_a2a_url("ftp://example.com")


def test_literal_localhost_rejected():
    with pytest.raises(ValueError):
        validators._validate_a2a_url("http://localhost:8080")


@pytest.mark.parametrize("ip", ["127.0.0.1", "169.254.169.254", "169.254.1.5"])
def test_domain_resolving_to_dangerous_range_rejected(monkeypatch, ip):
    # A custom domain that resolves to loopback / metadata must be blocked.
    _patch_resolve(monkeypatch, ip)
    with pytest.raises(ValueError):
        validators._validate_a2a_url("http://evil.example.com:8080")


@pytest.mark.parametrize("ip", ["10.146.0.4", "192.168.1.10", "172.16.5.5"])
def test_private_lan_allowed(monkeypatch, ip):
    # Internal agents / federation nodes on private LAN ranges are allowed.
    _patch_resolve(monkeypatch, ip)
    validators._validate_a2a_url("http://internal-agent:18080")  # no raise


def test_public_ip_allowed(monkeypatch):
    _patch_resolve(monkeypatch, "93.184.216.34")
    validators._validate_a2a_url("https://agent.example.com")  # no raise


def test_transient_dns_failure_does_not_block(monkeypatch):
    def boom(*a, **k):
        raise socket.gaierror("temporary failure")
    monkeypatch.setattr(validators.socket, "getaddrinfo", boom)
    # Unresolvable now → don't block registration on a transient DNS error
    validators._validate_a2a_url("https://agent.example.com")  # no raise

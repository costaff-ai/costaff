"""Tests for utils.network — SSRF guard."""
import socket

import pytest

from utils import network


def _patch_resolve(monkeypatch, ip: str):
    """Force socket.getaddrinfo to return a single fixed IPv4 address."""
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0))]
    monkeypatch.setattr(network.socket, "getaddrinfo", fake_getaddrinfo)


@pytest.mark.parametrize("ip", [
    "10.0.0.1",
    "10.255.255.255",
    "172.16.0.1",
    "172.31.255.255",
    "192.168.1.1",
    "127.0.0.1",
    "169.254.169.254",
])
def test_rejects_private_ipv4(monkeypatch, ip):
    _patch_resolve(monkeypatch, ip)
    assert network.is_safe_url(f"http://example.com") is False


def test_rejects_loopback_ipv6(monkeypatch):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::1", 0, 0, 0))]
    monkeypatch.setattr(network.socket, "getaddrinfo", fake_getaddrinfo)
    assert network.is_safe_url("http://example.com") is False


def test_rejects_unique_local_ipv6(monkeypatch):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("fc00::1", 0, 0, 0))]
    monkeypatch.setattr(network.socket, "getaddrinfo", fake_getaddrinfo)
    assert network.is_safe_url("http://example.com") is False


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34"])
def test_accepts_public_ipv4(monkeypatch, ip):
    _patch_resolve(monkeypatch, ip)
    assert network.is_safe_url("https://example.com") is True


def test_rejects_url_without_host():
    assert network.is_safe_url("not-a-url") is False
    assert network.is_safe_url("") is False


def test_rejects_when_dns_resolution_fails(monkeypatch):
    def fake_getaddrinfo(*args, **kwargs):
        raise socket.gaierror("DNS failure")
    monkeypatch.setattr(network.socket, "getaddrinfo", fake_getaddrinfo)
    assert network.is_safe_url("https://nonexistent.invalid") is False


def test_rejects_when_any_resolved_ip_is_private(monkeypatch):
    """If a host resolves to multiple IPs and any is private, reject."""
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0)),
        ]
    monkeypatch.setattr(network.socket, "getaddrinfo", fake_getaddrinfo)
    assert network.is_safe_url("https://example.com") is False

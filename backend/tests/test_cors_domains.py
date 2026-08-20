"""Custom-domain CORS — visitors on Cloudflare/white-label hosts must not see
the browser TypeError that the web app translates as \"Can't reach the ChatMood server\"."""

from app.config import settings
from app.core.cors import forget_cors_host, origin_allowed, remember_cors_host, reset_cors_hosts


def test_origin_allowed_frontend_and_www_twin(monkeypatch):
    monkeypatch.setattr(settings, "CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://5boost.me")
    reset_cors_hosts()
    assert origin_allowed("https://5boost.me") is True
    assert origin_allowed("https://www.5boost.me") is True
    assert origin_allowed("https://evil.example") is False


def test_origin_allowed_star_allows_any(monkeypatch):
    monkeypatch.setattr(settings, "CORS_ORIGINS", "*")
    monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:3000")
    assert origin_allowed("https://anything.example") is True


def test_remembered_custom_host_and_www_are_allowed(monkeypatch):
    monkeypatch.setattr(settings, "CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:3000")
    reset_cors_hosts()
    remember_cors_host("acme.ai")
    assert origin_allowed("https://acme.ai") is True
    assert origin_allowed("https://www.acme.ai") is True
    forget_cors_host("acme.ai")
    assert origin_allowed("https://acme.ai") is False

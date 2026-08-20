"""Custom-domain helpers: Cloudflare DNS automation + apex verification fallbacks."""

import asyncio

import httpx
import pytest

from app.config import settings
from app.services import domains as dom


def test_zone_candidates_walk_suffixes():
    assert dom.zone_candidates("chat.example.com") == ["chat.example.com", "example.com"]
    assert dom.zone_candidates("a.b.example.co.uk") == [
        "a.b.example.co.uk",
        "b.example.co.uk",
        "example.co.uk",
        "co.uk",
    ]


def test_a_points_matches_platform_ip(monkeypatch):
    monkeypatch.setattr(dom, "_sync_a_records", lambda name: ["203.0.113.10", "198.51.100.5"])
    assert asyncio.run(dom.a_points("app.example.com", "203.0.113.10")) is True
    assert asyncio.run(dom.a_points("app.example.com", "192.0.2.44")) is False


def test_cloudflare_relative_name_handles_zone_apex_and_subdomain():
    assert dom.CloudflareClient._relative_name("example.com", "example.com") == "@"
    assert dom.CloudflareClient._relative_name("chat.example.com", "example.com") == "chat"
    assert dom.CloudflareClient._relative_name("_mood-verify.chat.example.com", "example.com") == "_mood-verify.chat"


def test_cloudflare_provision_subdomain_uses_txt_and_cname(monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", "cf-token")
    monkeypatch.setattr(settings, "PLATFORM_CNAME_TARGET", "edge.mood.test")
    monkeypatch.setattr(settings, "PLATFORM_A_RECORD_IP", "")

    calls: list[dict] = []
    cf = dom.CloudflareClient()

    async def _find_zone(domain: str):
        assert domain == "chat.example.com"
        return {"id": "zone-1", "name": "example.com"}

    async def _upsert(zone_id: str, *, type: str, name: str, content: str, proxied: bool = False, ttl: int = 300, zone_name: str | None = None):
        calls.append({"zone_id": zone_id, "type": type, "name": name, "content": content, "proxied": proxied, "ttl": ttl, "zone_name": zone_name})

    monkeypatch.setattr(cf, "find_zone", _find_zone)
    monkeypatch.setattr(cf, "upsert_record", _upsert)

    out = asyncio.run(cf.provision_connected_domain("chat.example.com", "verify-123"))

    assert out["zone"] == "example.com"
    assert out["txt_name"] == "_mood-verify.chat.example.com"
    assert out["record_type"] == "CNAME"
    assert out["record_name"] == "chat.example.com"
    assert out["record_value"] == "edge.mood.test"
    assert out["proxied"] == "false"
    assert calls == [
        {
            "zone_id": "zone-1",
            "type": "TXT",
            "name": "_mood-verify.chat",
            "content": "verify-123",
            "proxied": False,
            "ttl": 300,
            "zone_name": "example.com",
        },
        {
            "zone_id": "zone-1",
            "type": "CNAME",
            "name": "chat",
            "content": "edge.mood.test",
            "proxied": False,
            "ttl": 300,
            "zone_name": "example.com",
        },
    ]


def test_cloudflare_provision_apex_prefers_a_record_when_platform_ip_exists(monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", "cf-token")
    monkeypatch.setattr(settings, "PLATFORM_CNAME_TARGET", "edge.mood.test")
    monkeypatch.setattr(settings, "PLATFORM_A_RECORD_IP", "203.0.113.10")

    calls: list[dict] = []
    cf = dom.CloudflareClient()

    async def _find_zone(domain: str):
        assert domain == "example.com"
        return {"id": "zone-1", "name": "example.com"}

    async def _upsert(zone_id: str, *, type: str, name: str, content: str, proxied: bool = False, ttl: int = 300, zone_name: str | None = None):
        calls.append({"zone_id": zone_id, "type": type, "name": name, "content": content, "proxied": proxied, "ttl": ttl, "zone_name": zone_name})

    monkeypatch.setattr(cf, "find_zone", _find_zone)
    monkeypatch.setattr(cf, "upsert_record", _upsert)

    out = asyncio.run(cf.provision_connected_domain("example.com", "verify-123"))

    assert out["zone"] == "example.com"
    assert out["txt_name"] == "_mood-verify.example.com"
    assert out["record_type"] == "A"
    assert out["record_name"] == "example.com"
    assert out["record_value"] == "203.0.113.10"
    assert out["proxied"] == "false"
    assert {
        "zone_id": "zone-1",
        "type": "A",
        "name": "@",
        "content": "203.0.113.10",
        "proxied": False,
        "ttl": 300,
        "zone_name": "example.com",
    } in calls
    assert any(c["name"] == "www" and c["proxied"] is False for c in calls)


def test_cloudflare_fqdn_normalizes_at_and_relative():
    assert dom.CloudflareClient._fqdn("@", "example.com") == "example.com"
    assert dom.CloudflareClient._fqdn("chat", "example.com") == "chat.example.com"
    assert dom.CloudflareClient._fqdn("chat.example.com", "example.com") == "chat.example.com"
    assert dom.CloudflareClient._fqdn("_mood-verify.chat", "example.com") == "_mood-verify.chat.example.com"


def test_cname_points_accepts_flattened_a_records(monkeypatch):
    """Cloudflare orange-cloud hides the CNAME; matching A sets still count."""
    monkeypatch.setattr(dom, "_sync_cname_records", lambda name: [])
    monkeypatch.setattr(
        dom,
        "_sync_a_records",
        lambda name: ["203.0.113.10"] if name in {"app.example.com", "edge.mood.test"} else [],
    )
    assert asyncio.run(dom.cname_points("app.example.com", "edge.mood.test")) is True
    assert asyncio.run(dom.cname_points("other.example.com", "edge.mood.test")) is False


def test_upsert_looks_up_fqdn_and_replaces_conflicting_a(monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", "cf-token")
    cf = dom.CloudflareClient()
    calls: list[tuple] = []

    async def _api(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs.get("params"), kwargs.get("json")))
        if method == "GET" and path.endswith("/dns_records"):
            return {
                "result": [
                    {"id": "a-old", "type": "A", "name": "chat.example.com", "content": "198.51.100.1", "proxied": True},
                ]
            }
        return {"success": True, "result": {}}

    monkeypatch.setattr(cf, "_api", _api)
    asyncio.run(
        cf.upsert_record(
            "zone-1",
            type="CNAME",
            name="chat",
            content="edge.mood.test",
            proxied=False,
            zone_name="example.com",
        )
    )
    methods = [c[0] for c in calls]
    assert "GET" in methods
    assert ("GET", "/zones/zone-1/dns_records", {"name": "chat.example.com", "per_page": 100}, None) in [
        (m, p, params, body) for m, p, params, body in calls
    ]
    assert any(c[0] == "DELETE" and c[1].endswith("/a-old") for c in calls)
    post = [c for c in calls if c[0] == "POST"]
    assert post and post[0][3]["name"] == "chat.example.com"
    assert post[0][3]["proxied"] is False
    assert post[0][3]["type"] == "CNAME"


def test_upsert_retries_update_existing_by_fqdn(monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", "cf-token")
    cf = dom.CloudflareClient()

    async def _api(method: str, path: str, **kwargs):
        if method == "GET":
            return {
                "result": [
                    {"id": "cname-1", "type": "CNAME", "name": "chat.example.com", "content": "old.edge.test", "proxied": True},
                ]
            }
        assert method == "PUT"
        assert path.endswith("/cname-1")
        assert kwargs["json"]["content"] == "edge.mood.test"
        assert kwargs["json"]["proxied"] is False
        assert kwargs["json"]["name"] == "chat.example.com"
        return {"success": True}

    monkeypatch.setattr(cf, "_api", _api)
    asyncio.run(
        cf.upsert_record(
            "zone-1",
            type="CNAME",
            name="chat",
            content="edge.mood.test",
            proxied=False,
            zone_name="example.com",
        )
    )


def test_cloudflare_api_unreachable_is_domain_error(monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", "cf-token")
    cf = dom.CloudflareClient()

    async def boom(method, url, **kwargs):
        raise httpx.ConnectError("dns failed", request=httpx.Request(method, url))

    monkeypatch.setattr(cf._http, "request", boom)
    with pytest.raises(dom.DomainError, match="Can't reach the Cloudflare API"):
        asyncio.run(cf._api("GET", "/zones"))


def test_records_match_reads_txt_and_cname(monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", "cf-token")
    monkeypatch.setattr(settings, "PLATFORM_CNAME_TARGET", "edge.mood.test")
    monkeypatch.setattr(settings, "PLATFORM_A_RECORD_IP", "")
    cf = dom.CloudflareClient()

    async def _find_zone(domain: str):
        return {"id": "zone-1", "name": "example.com", "status": "active"}

    async def _list(zone_id: str, *, name: str | None = None, type: str | None = None):
        if name and name.startswith("_mood-verify"):
            return [{"type": "TXT", "content": "verify-123"}]
        return [{"type": "CNAME", "content": "edge.mood.test"}]

    monkeypatch.setattr(cf, "find_zone", _find_zone)
    monkeypatch.setattr(cf, "list_records", _list)
    out = asyncio.run(cf.records_match("chat.example.com", "verify-123"))
    assert out["txt_verified"] is True
    assert out["cname_points"] is True
    assert out["zone_status"] == "active"


def test_find_zone_scopes_account_and_falls_back_to_pending(monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", "cf-token")
    monkeypatch.setattr(settings, "CLOUDFLARE_ACCOUNT_ID", "acct-9")
    cf = dom.CloudflareClient()
    seen: list[dict] = []

    async def _api(method: str, path: str, **kwargs):
        seen.append(kwargs["params"])
        if kwargs["params"].get("status") == "pending":
            return {"result": [{"id": "z1", "name": "example.com", "status": "pending"}]}
        return {"result": []}

    monkeypatch.setattr(cf, "_api", _api)
    zone = asyncio.run(cf.find_zone("chat.example.com"))
    assert zone == {"id": "z1", "name": "example.com", "status": "pending"}
    assert any(p.get("account.id") == "acct-9" for p in seen)

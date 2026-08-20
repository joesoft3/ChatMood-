"""Custom domains: DNS verification (connect-your-own) and a registrar client for
real-time domain search + purchase (GoDaddy; OTE sandbox by default so the full
flow is testable without charging real money — flip GODADDY_ENV=production to go live).
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import settings

log = logging.getLogger(__name__)

DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.I)


class DomainError(Exception):
    pass


class RegistrarNotConfigured(Exception):
    pass


def clean_domain(raw: str) -> str:
    d = raw.strip().lower().rstrip(".")
    d = re.sub(r"^https?://", "", d).split("/")[0]
    if not DOMAIN_RE.match(d):
        raise DomainError("That doesn't look like a valid domain (e.g. chat.mybusiness.com).")
    return d


def price_with_markup(cost_cents: int) -> int:
    return round(cost_cents * (1 + settings.DOMAIN_MARKUP_PCT / 100))


# --------------------------------------------------------------------- DNS checks
_DOH_URL = "https://cloudflare-dns.com/dns-query"
_DOH_TYPE = {"A": 1, "AAAA": 28, "CNAME": 5, "TXT": 16}


def _strip_txt(value: str) -> str:
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] == '"':
        v = v[1:-1]
    return v.replace('" "', "")


def _doh_records(name: str, rtype: str) -> list[str]:
    """Ask 1.1.1.1 directly. System resolvers often cache NXDOMAIN for minutes
    after we just created a Cloudflare record, which made Verify / on-demand TLS
    look like Cloudflare was down."""
    import json
    import urllib.parse
    import urllib.request

    qtype = _DOH_TYPE.get(rtype.upper())
    if not qtype:
        return []
    url = f"{_DOH_URL}?{urllib.parse.urlencode({'name': name, 'type': rtype})}"
    req = urllib.request.Request(url, headers={"accept": "application/dns-json"})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode() or "{}")
    except Exception:
        return []
    out: list[str] = []
    for ans in data.get("Answer") or []:
        if ans.get("type") != qtype:
            continue
        raw = str(ans.get("data") or "").strip()
        if rtype.upper() == "TXT":
            raw = _strip_txt(raw)
        elif rtype.upper() == "CNAME":
            raw = raw.rstrip(".").lower()
        if raw:
            out.append(raw)
    return out


def _resolver_records(name: str, rtype: str) -> list[str]:
    import dns.resolver

    try:
        answers = dns.resolver.resolve(name, rtype, lifetime=6)
    except Exception:
        return []
    out: list[str] = []
    for r in answers:
        try:
            if rtype == "TXT":
                try:
                    out.append("".join(s.decode() if isinstance(s, bytes) else str(s) for s in r.strings))
                except AttributeError:
                    out.append(_strip_txt(str(r)))
            elif rtype == "CNAME":
                out.append(str(r.target).rstrip(".").lower())
            elif rtype in {"A", "AAAA"}:
                out.append(str(r.address).strip())
            else:
                out.append(str(r).rstrip("."))
        except Exception:
            continue
    return out


def _lookup(name: str, rtype: str) -> list[str]:
    got = _resolver_records(name, rtype)
    return got if got else _doh_records(name, rtype)


def _sync_txt_records(name: str) -> list[str]:
    return _lookup(name, "TXT")


def _sync_cname_records(name: str) -> list[str]:
    return _lookup(name, "CNAME")


def _sync_a_records(name: str) -> list[str]:
    return _lookup(name, "A")


async def verify_txt(domain: str, token: str) -> bool:
    """TXT record _mood-verify.<domain> must contain our verification token."""
    records = await asyncio.to_thread(_sync_txt_records, f"_mood-verify.{domain}")
    return any(token in r for r in records)


def _sets_alias(host_as: list[str], target_as: list[str]) -> bool:
    """True when flattened CNAME / CF orange-cloud A records match the target."""
    host, tgt = set(host_as), set(target_as)
    return bool(host and tgt and (tgt <= host or host <= tgt))


async def cname_points(domain: str, target: str) -> bool:
    """Does <domain> (or www.<domain> for apex) CNAME to the platform target?

    Cloudflare orange-cloud / CNAME flattening hides the CNAME at the public
    DNS layer and publishes A records instead. Treat matching A sets as the
    same proof — otherwise Verify never flips to live and the edge (Caddy)
    refuses TLS, which surfaces as Cloudflare Error 522 (origin unreachable).
    """
    target = target.rstrip(".").lower()
    names = (domain, f"www.{domain}")
    for name in names:
        if target in await asyncio.to_thread(_sync_cname_records, name):
            return True
    target_as = await asyncio.to_thread(_sync_a_records, target)
    if not target_as:
        return False
    for name in names:
        if _sets_alias(await asyncio.to_thread(_sync_a_records, name), target_as):
            return True
    return False


async def a_points(domain: str, ip: str) -> bool:
    """Does <domain> publish an A record to the platform edge IP?

    Helpful for apex domains on providers like Cloudflare where the operator may
    use CNAME flattening or an explicit apex A record instead of a visible CNAME.
    """
    return ip.strip() in await asyncio.to_thread(_sync_a_records, domain)


def zone_candidates(domain: str) -> list[str]:
    """Longest-to-shortest suffixes to probe for a managed DNS zone.

    Examples:
      chat.example.com      → [chat.example.com, example.com]
      a.b.example.co.uk     → [a.b.example.co.uk, b.example.co.uk, example.co.uk, co.uk]
    The DNS provider simply returns the suffixes it actually manages.
    """
    bits = clean_domain(domain).split(".")
    return [".".join(bits[i:]) for i in range(0, max(1, len(bits) - 1))]


class CloudflareNotConfigured(Exception):
    pass


class CloudflareClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(12.0, read=25.0))

    @property
    def configured(self) -> bool:
        return bool(settings.CLOUDFLARE_API_TOKEN)

    def _headers(self) -> dict[str, str]:
        if not self.configured:
            raise CloudflareNotConfigured(
                "Cloudflare DNS not configured — set CLOUDFLARE_API_TOKEN (Zone:Read + DNS:Edit)."
            )
        return {
            "Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN}",
            "Content-Type": "application/json",
        }

    @property
    def _base(self) -> str:
        return settings.CLOUDFLARE_API_BASE_URL.rstrip("/")

    async def _api(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self._base}{path}"
        try:
            r = await self._http.request(method, url, headers=self._headers(), **kwargs)
        except httpx.RequestError as e:
            raise DomainError(
                f"Can't reach the Cloudflare API at {self._base} ({e.__class__.__name__}: {e}). "
                "Check CLOUDFLARE_API_TOKEN / CLOUDFLARE_API_BASE_URL and that this host can open https://api.cloudflare.com."
            ) from e
        if r.status_code >= 400:
            raise DomainError(f"Cloudflare API failed ({r.status_code}): {r.text[:240]}")
        data = r.json() if r.content else {}
        if isinstance(data, dict) and data.get("success") is False:
            errs = "; ".join(str(e.get("message") or e) for e in data.get("errors") or [])
            raise DomainError(f"Cloudflare API error: {errs or 'unknown error'}")
        return data

    async def find_zone(self, domain: str) -> dict[str, str]:
        account = (settings.CLOUDFLARE_ACCOUNT_ID or "").strip()
        for cand in zone_candidates(domain):
            # Active zones first (nameservers already at Cloudflare). Pending is
            # a fallback so we can still write records, but callers must not
            # treat pending as publicly reachable.
            for status in ("active", "pending"):
                params: dict[str, Any] = {"name": cand, "per_page": 1, "status": status}
                if account:
                    params["account.id"] = account
                data = await self._api("GET", "/zones", params=params)
                rows = data.get("result") or []
                if rows:
                    z = rows[0]
                    return {
                        "id": str(z.get("id") or ""),
                        "name": str(z.get("name") or cand),
                        "status": str(z.get("status") or status),
                    }
        raise DomainError(
            f"No accessible Cloudflare zone found for {domain}. Make sure the domain is in this Cloudflare account."
        )

    @staticmethod
    def _relative_name(fqdn: str, zone_name: str) -> str:
        fqdn = fqdn.strip().lower().rstrip(".")
        fqdn = re.sub(r"^https?://", "", fqdn).split("/")[0]
        zone_name = clean_domain(zone_name)
        if fqdn == zone_name:
            return "@"
        suffix = f".{zone_name}"
        if not fqdn.endswith(suffix):
            raise DomainError(f"{fqdn} does not belong to Cloudflare zone {zone_name}")
        return fqdn[: -len(suffix)]

    @staticmethod
    def _fqdn(name: str, zone_name: str) -> str:
        """Cloudflare's list filter requires the fully-qualified name, not `@` / a relative label."""
        zone_name = clean_domain(zone_name)
        n = (name or "").strip().lower().rstrip(".")
        n = re.sub(r"^https?://", "", n).split("/")[0]
        if n in {"", "@", zone_name}:
            return zone_name
        if n.endswith(f".{zone_name}"):
            return n
        return f"{n}.{zone_name}"

    async def list_records(self, zone_id: str, *, name: str | None = None, type: str | None = None) -> list[dict]:
        params: dict[str, Any] = {"per_page": 100}
        if name:
            params["name"] = name.strip().lower().rstrip(".")
        if type:
            params["type"] = type
        data = await self._api("GET", f"/zones/{zone_id}/dns_records", params=params)
        return list(data.get("result") or [])

    async def upsert_record(
        self,
        zone_id: str,
        *,
        type: str,
        name: str,
        content: str,
        proxied: bool = False,
        ttl: int = 300,
        zone_name: str | None = None,
    ) -> None:
        """Create or replace a record. Lookup is by FQDN so retries actually update.

        Traffic records stay DNS-only (`proxied=False`) unless the caller opts in.
        Orange-cloud proxying this hostname makes Cloudflare the HTTPS client of
        our origin — and when the origin cert/SNI doesn't match (Fly/Caddy
        on-demand TLS), Cloudflare returns Error 522/526: origin unreachable.
        """
        fqdn = self._fqdn(name, zone_name) if zone_name else name.strip().lower().rstrip(".")
        payload: dict[str, Any] = {
            "type": type,
            "name": fqdn,
            "content": content,
            "ttl": 1 if proxied else ttl,
        }
        if type in {"A", "AAAA", "CNAME"}:
            payload["proxied"] = proxied

        rows = await self.list_records(zone_id, name=fqdn)
        same = [r for r in rows if (r.get("type") or "") == type]
        if type in {"A", "AAAA", "CNAME"}:
            for r in rows:
                rtype = r.get("type") or ""
                rid = r.get("id")
                if rid and rtype in {"A", "AAAA", "CNAME"} and rtype != type:
                    # Apex/subdomain cannot hold both a CNAME and A/AAAA.
                    await self._api("DELETE", f"/zones/{zone_id}/dns_records/{rid}")

        if same:
            rid = same[0].get("id")
            await self._api("PUT", f"/zones/{zone_id}/dns_records/{rid}", json=payload)
            for extra in same[1:]:
                eid = extra.get("id")
                if eid:
                    await self._api("DELETE", f"/zones/{zone_id}/dns_records/{eid}")
            return
        await self._api("POST", f"/zones/{zone_id}/dns_records", json=payload)

    async def records_match(self, domain: str, verification_token: str) -> dict[str, Any]:
        """Authoritative check against the Cloudflare API (not public DNS)."""
        zone = await self.find_zone(domain)
        fqdn = clean_domain(domain)
        txt_fqdn = f"_mood-verify.{fqdn}"
        txt_rows = await self.list_records(zone["id"], name=txt_fqdn, type="TXT")
        traffic = await self.list_records(zone["id"], name=fqdn)
        want_cname = (settings.PLATFORM_CNAME_TARGET or "").rstrip(".").lower()
        want_ip = (settings.PLATFORM_A_RECORD_IP or "").strip()
        txt_ok = any(verification_token in _strip_txt(str(r.get("content") or "")) for r in txt_rows)
        cname_ok = any(
            (r.get("type") == "CNAME")
            and want_cname
            and want_cname == str(r.get("content") or "").rstrip(".").lower()
            for r in traffic
        )
        a_ok = any((r.get("type") == "A") and want_ip and want_ip == str(r.get("content") or "").strip() for r in traffic)
        return {
            "zone": zone.get("name"),
            "zone_status": zone.get("status") or "active",
            "txt_verified": txt_ok,
            "cname_points": cname_ok,
            "a_record_points": a_ok,
        }

    async def provision_connected_domain(self, domain: str, verification_token: str) -> dict[str, str]:
        zone = await self.find_zone(domain)
        zone_name = zone["name"]
        zone_id = zone["id"]

        txt_fqdn = f"_mood-verify.{clean_domain(domain)}"
        txt_name = self._relative_name(txt_fqdn, zone_name)
        await self.upsert_record(
            zone_id, type="TXT", name=txt_name, content=verification_token, zone_name=zone_name
        )

        traffic_type = ""
        traffic_name = ""
        traffic_value = ""
        # Always DNS-only so Cloudflare does not try (and fail) to reach our origin.
        if clean_domain(domain) == zone_name and settings.PLATFORM_A_RECORD_IP:
            traffic_type = "A"
            traffic_name = self._relative_name(domain, zone_name)
            traffic_value = settings.PLATFORM_A_RECORD_IP.strip()
            await self.upsert_record(
                zone_id, type="A", name=traffic_name, content=traffic_value, proxied=False, zone_name=zone_name
            )
        elif settings.PLATFORM_CNAME_TARGET:
            traffic_type = "CNAME"
            traffic_name = self._relative_name(domain, zone_name)
            traffic_value = settings.PLATFORM_CNAME_TARGET.rstrip(".")
            await self.upsert_record(
                zone_id, type="CNAME", name=traffic_name, content=traffic_value, proxied=False, zone_name=zone_name
            )
        elif settings.PLATFORM_A_RECORD_IP:
            traffic_type = "A"
            traffic_name = self._relative_name(domain, zone_name)
            traffic_value = settings.PLATFORM_A_RECORD_IP.strip()
            await self.upsert_record(
                zone_id, type="A", name=traffic_name, content=traffic_value, proxied=False, zone_name=zone_name
            )
        else:
            raise DomainError("Platform traffic target is not configured — set PLATFORM_CNAME_TARGET or PLATFORM_A_RECORD_IP.")

        # Apex visitors often type www. — grey-cloud it too so Cloudflare isn't
        # the HTTPS client of a host Caddy/Fly have no cert for.
        if clean_domain(domain) == zone_name:
            try:
                if settings.PLATFORM_CNAME_TARGET:
                    await self.upsert_record(
                        zone_id,
                        type="CNAME",
                        name="www",
                        content=settings.PLATFORM_CNAME_TARGET.rstrip("."),
                        proxied=False,
                        zone_name=zone_name,
                    )
                elif traffic_type == "A" and traffic_value:
                    await self.upsert_record(
                        zone_id,
                        type="A",
                        name="www",
                        content=traffic_value,
                        proxied=False,
                        zone_name=zone_name,
                    )
            except DomainError as e:
                log.warning("cloudflare www record for %s skipped: %s", domain, e)

        return {
            "zone": zone_name,
            "zone_status": zone.get("status") or "active",
            "txt_name": txt_fqdn,
            "record_type": traffic_type,
            "record_name": domain,
            "record_value": traffic_value,
            "proxied": "false",
        }


# --------------------------------------------------------------------- Registrar (GoDaddy)
class GoDaddyClient:
    BASE = {"ote": "https://api.ote-godaddy.com", "production": "https://api.godaddy.com"}

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(15.0, read=45.0))

    @property
    def configured(self) -> bool:
        return bool(settings.GODADDY_API_KEY and settings.GODADDY_API_SECRET)

    def _headers(self) -> dict:
        if not self.configured:
            raise RegistrarNotConfigured(
                "Registrar not configured — set GODADDY_API_KEY/SECRET (developer.godaddy.com/keys)."
            )
        return {
            "Authorization": f"sso-key {settings.GODADDY_API_KEY}:{settings.GODADDY_API_SECRET}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @property
    def _base(self) -> str:
        return self.BASE.get(settings.GODADDY_ENV, self.BASE["ote"])

    def _check(self, name: str, r: httpx.Response) -> Any:
        if r.status_code >= 400:
            raise DomainError(f"{name} failed ({r.status_code}): {r.text[:240]}")
        return r.json() if r.content else {}

    async def availability(self, domain: str) -> dict:
        r = await self._http.get(
            f"{self._base}/v1/domains/available", headers=self._headers(), params={"domain": domain, "checkType": "FULL"}
        )
        j = self._check("availability", r)
        # price is given in micro-units of currency
        price_micro = j.get("price") or 0
        return {
            "domain": domain,
            "available": bool(j.get("available")),
            "cost_cents": round(price_micro / 10_000),  # micros → cents
            "currency": j.get("currency", "USD"),
        }

    async def suggest(self, query: str, limit: int = 6) -> list[str]:
        r = await self._http.get(
            f"{self._base}/v1/domains/suggest", headers=self._headers(), params={"query": query, "limit": limit}
        )
        j = self._check("suggest", r)
        return [s for s in j if isinstance(s, str)][:limit]

    async def agreements(self, tld: str) -> list[dict]:
        r = await self._http.get(
            f"{self._base}/v1/domains/agreements", headers=self._headers(),
            params={"tlds": tld, "privacy": "true", "forTransfer": "false"},
        )
        j = self._check("agreements", r)
        return j if isinstance(j, list) else []

    async def purchase(self, domain: str, contact: dict, years: int) -> dict:
        tld = domain.rsplit(".", 1)[-1]
        agreements = await self.agreements(tld)
        body = {
            "domain": domain,
            "consent": {
                "agreementKeys": [a.get("agreementKey") for a in agreements if a.get("agreementKey")],
                "agreedBy": contact.get("email", "owner"),
                "agreedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            },
            "contactRegistrant": contact,
            "contactAdmin": contact,
            "contactTech": contact,
            "contactBilling": contact,
            "period": years,
            "privacy": True,
            "renewAuto": True,
            "nameServers": None,  # keep registrar defaults
        }
        r = await self._http.post(f"{self._base}/v1/domains/purchase", headers=self._headers(), json=body)
        return self._check("purchase", r)

    async def point_to_platform(self, domain: str) -> None:
        """Route a freshly purchased domain at the platform: apex A (if configured) + www CNAME."""
        ops: list[tuple[str, str, dict]] = []
        if settings.PLATFORM_CNAME_TARGET:
            ops.append(
                ("PUT", "replace", {"name": "www", "data": settings.PLATFORM_CNAME_TARGET.rstrip("."), "ttl": 3600})
            )
        if settings.PLATFORM_A_RECORD_IP:
            ops.append(("PUT", "replace", {"name": "@", "data": settings.PLATFORM_A_RECORD_IP, "ttl": 3600}))
        for method, _, rec in ops:
            r = await self._http.put(
                f"{self._base}/v1/domains/{domain}/records/{'CNAME' if rec['name'] == 'www' else 'A'}/{rec['name']}",
                headers=self._headers(),
                json=[{"data": rec["data"], "ttl": rec["ttl"], "name": rec["name"], "type": "CNAME" if rec["name"] == "www" else "A"}],
            )
            if r.status_code >= 400:
                log.warning("point_to_platform %s %s failed (%s): %s", domain, rec["name"], r.status_code, r.text[:160])


    async def get_domain(self, domain: str) -> dict:
        """Registrar-side details: expires (ISO), renewAuto, status, …"""
        r = await self._http.get(f"{self._base}/v1/domains/{domain}", headers=self._headers())
        return self._check("get_domain", r)

    async def set_auto_renew(self, domain: str, flag: bool) -> None:
        r = await self._http.patch(
            f"{self._base}/v1/domains/{domain}", headers=self._headers(), json={"renewAuto": flag}
        )
        self._check("set_auto_renew", r)

    async def renew(self, domain: str, years: int) -> dict:
        """Extend registration at the registrar (charges the platform's reseller account)."""
        r = await self._http.post(
            f"{self._base}/v1/domains/{domain}/renew",
            headers=self._headers(),
            json={"period": years},
        )
        return self._check("renew", r)


cloudflare = CloudflareClient()
registrar = GoDaddyClient()


def parse_expiry(raw: Any) -> datetime | None:
    """Registrar returns ISO-8601 like 2027-07-16T23:59:59Z → aware datetime."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# --------------------------------------------------------------------- expiry watchdog
async def sync_expirations() -> int:
    """Pull expiry/auto-renew from the registrar for purchased domains that are
    stale (unknown expiry, or expiring within 90 days). Returns rows updated."""
    from sqlalchemy import or_, select

    from ..db.models import Domain
    from ..db.session import SessionLocal

    if not registrar.configured:
        return 0
    updated = 0
    try:
        now = datetime.now(timezone.utc)
        async with SessionLocal() as s:
            rows = (
                await s.execute(
                    select(Domain).where(
                        Domain.kind == "purchased",
                        Domain.registrar == "godaddy",
                        or_(Domain.expires_at.is_(None), Domain.status == "active"),
                    )
                )
            ).scalars().all()
            for d in rows:
                # skip fresh rows far from expiry
                if d.expires_at and (d.expires_at - now).days > 90:
                    continue
                try:
                    info = await registrar.get_domain(d.domain)
                except Exception as e:
                    log.warning("expiry sync %s failed: %s", d.domain, e)
                    continue
                exp = parse_expiry(info.get("expires"))
                if exp:
                    d.expires_at = exp
                if "renewAuto" in info:
                    d.auto_renew = bool(info.get("renewAuto"))
                updated += 1
            if updated:
                await s.commit()
    except Exception as e:
        log.warning("expiry sync cycle failed: %s", e)
    await _send_renewal_reminders()
    return updated


async def _send_renewal_reminders() -> None:
    """Owner reminder (via their connected Gmail, best-effort) when a purchased domain
    is inside the renewal window AND registrar auto-renew is OFF. Once per expiry date
    — Redis dedup key includes the expiry, so next year's window reminds again."""
    try:
        from sqlalchemy import select

        from ..api.deps import get_redis
        from ..db.models import Domain, User
        from ..db.session import SessionLocal
        from .notify import send_email

        window = max(7, settings.DOMAIN_RENEW_WINDOW_DAYS)
        now = datetime.now(timezone.utc)
        r = await get_redis()
        async with SessionLocal() as s:
            due = (
                await s.execute(
                    select(Domain).where(
                        Domain.kind == "purchased",
                        Domain.status == "active",
                        Domain.auto_renew.is_(False),
                        Domain.expires_at.is_not(None),
                    )
                )
            ).scalars().all()
            for d in due:
                if not d.expires_at:
                    continue
                days = (d.expires_at - now).days
                if days < 0 or days > window:
                    continue
                dedup = f"domrenew:{d.id}:{d.expires_at.strftime('%Y%m%d')}"
                try:
                    if await r.get(dedup):
                        continue
                    owner = await s.get(User, d.user_id)
                    if not owner:
                        continue
                    link = f"{settings.FRONTEND_URL}/settings"
                    ok = await send_email(
                        s,
                        owner.id,
                        owner.email,
                        f"⏳ Your domain {d.domain} expires in {days} day(s)",
                        (
                            f"Hi {owner.display_name or 'there'},\n\n"
                            f"Your domain {d.domain} expires on {d.expires_at.date().isoformat()} "
                            f"and registrar auto-renew is OFF.\n\n"
                            f"Renew it in one click: {link} (Custom domains → 🔁 Renew now).\n\n"
                            f"— ChatMood"
                        ),
                    )
                    if ok:
                        await r.set(dedup, "1", ex=45 * 86400)
                        log.info("renewal reminder sent for %s (%dd left)", d.domain, days)
                except Exception as e:
                    log.warning("renewal reminder failed for %s: %s", d.domain, e)
    except Exception as e:
        log.warning("renewal reminder pass failed: %s", e)


async def expiry_watchdog() -> None:
    """Background task: keep registrar expiry dates fresh (daily by default)."""
    import asyncio

    await asyncio.sleep(90)  # let the stack settle after startup
    while True:
        n = await sync_expirations()
        if n:
            log.info("domain expiry watchdog refreshed %d domain(s)", n)
        await asyncio.sleep(max(1, settings.DOMAIN_SYNC_HOURS) * 3600)


# --------------------------------------------------------------------- Vercel attach (optional)
async def vercel_attach(domain: str) -> bool:
    """Attach a verified custom domain to the hosting project (Vercel), best-effort."""
    if not (settings.VERCEL_API_TOKEN and settings.VERCEL_PROJECT_ID):
        return False
    async with httpx.AsyncClient(timeout=10) as h:
        params = {"teamId": settings.VERCEL_TEAM_ID} if settings.VERCEL_TEAM_ID else {}
        r = await h.post(
            f"https://api.vercel.com/v10/projects/{settings.VERCEL_PROJECT_ID}/domains",
            headers={"Authorization": f"Bearer {settings.VERCEL_API_TOKEN}"},
            params=params,
            json={"name": domain},
        )
        if r.status_code >= 400:
            log.warning("vercel attach %s failed: %s", domain, r.text[:160])
            return False
    return True

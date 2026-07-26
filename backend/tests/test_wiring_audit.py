"""🔌 A–Z wiring audit — every route must resolve, and settings must exist.

These are the bugs an end-to-end sweep found that unit tests missed: a route
referencing a config attribute that was never defined, and a module-level
constant used but never imported. Both raise only when the endpoint is actually
called, so they shipped invisibly.
"""

import os

from app.config import settings


def test_every_settings_attribute_referenced_in_routes_exists():
    """Guards the class of bug behind `settings.MODELS_VIDEO`.

    A typo'd setting is a 500 that no import-time check catches — the attribute
    is only resolved when a request hits that line.
    """
    import re
    from pathlib import Path

    routes_dir = Path(__file__).resolve().parent.parent / "app"
    missing: list[str] = []
    for path in routes_dir.rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r"\bsettings\.([A-Z][A-Z0-9_]{2,})\b", src):
            name = m.group(1)
            if not hasattr(settings, name):
                line = src[: m.start()].count("\n") + 1
                missing.append(f"{path.name}:{line} settings.{name}")
    assert not missing, "undefined settings referenced:\n  " + "\n  ".join(sorted(set(missing)))


def test_route_modules_have_no_undefined_names():
    """Guards the class of bug behind `NEGATIVE_DEFAULT` (used, never imported).

    Compiling each module and resolving its global loads catches names that only
    blow up on the request path.
    """
    import ast
    import builtins
    from pathlib import Path

    routes_dir = Path(__file__).resolve().parent.parent / "app" / "api" / "routes"
    problems: list[str] = []
    for path in sorted(routes_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        defined = set(dir(builtins))
        # module-level bindings: imports, assignments, defs, classes
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    defined.add((a.asname or a.name).split(".")[0])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                defined.add(node.id)
            elif isinstance(node, (ast.arg,)):
                defined.add(node.arg)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                defined.add(node.name)
            elif isinstance(node, ast.alias):
                defined.add((node.asname or node.name).split(".")[0])
        # SCREAMING_CASE loads are module constants — the pattern that broke.
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                n = node.id
                if n.isupper() and len(n) > 3 and n not in defined:
                    problems.append(f"{path.name}:{node.lineno} {n}")
    assert not problems, "undefined module constants:\n  " + "\n  ".join(sorted(set(problems)))


def test_video_model_setting_is_wired():
    """The specific regression: /videos/grok + /videos/grok-info used
    `settings.MODELS_VIDEO`, which never existed."""
    assert hasattr(settings, "MODEL_VIDEO")
    assert not hasattr(settings, "MODELS_VIDEO")


def test_no_route_param_mixes_string_and_numeric_constraints():
    """Guards the class of bug behind `size: int = Query(pattern=...)`.

    `pattern` / `min_length` / `max_length` are *string* constraints. Pydantic
    raises TypeError when one is applied to an int/float, and it raises while
    building the validator for the request — so the endpoint 500s on EVERY
    call, including the default value. Nothing at import time catches it, and a
    unit test that never issues a request won't either.

    The inverse (ge/le/gt/lt on a `str`) is the same mistake mirrored.
    """
    import inspect
    import typing

    from fastapi.routing import APIRoute

    from app.main import app

    string_only = ("pattern", "min_length", "max_length")
    numeric_only = ("gt", "ge", "lt", "le", "multiple_of")

    def constraint(param_default, name):
        """FastAPI stashes constraints in `.metadata` (pydantic v2), not as
        plain attributes — reading only attributes silently finds nothing."""
        value = getattr(param_default, name, None)
        if value is not None:
            return value
        for meta in getattr(param_default, "metadata", None) or []:
            value = getattr(meta, name, None)
            if value is not None:
                return value
        return None

    def walk(router):
        """Routers are mounted as sub-routers, so `app.routes` only exposes a
        handful of top-level entries — recurse or 150 of 153 routes go
        unchecked (and this guard silently passes on everything)."""
        for entry in getattr(router, "routes", []) or []:
            if isinstance(entry, APIRoute):
                yield entry
                continue
            # Newer FastAPI mounts `include_router` results as `_IncludedRouter`
            # wrappers that expose the real router via `original_router`.
            nested = getattr(entry, "original_router", None) or getattr(entry, "app", None)
            if nested is not None:
                yield from walk(nested)
            else:
                yield from walk(entry)

    all_routes = list(walk(app))
    assert len(all_routes) > 100, f"route discovery broke — only found {len(all_routes)}"

    problems: list[str] = []
    for route in all_routes:
        try:
            hints = typing.get_type_hints(route.endpoint)
        except Exception:  # pragma: no cover - unresolvable annotations
            continue
        for name, param in inspect.signature(route.endpoint).parameters.items():
            default = param.default
            if default is inspect.Parameter.empty:
                continue
            annotation = hints.get(name)
            # Unwrap `X | None` so Optional params are still checked.
            args = [a for a in typing.get_args(annotation) if a is not type(None)]
            if len(args) == 1:
                annotation = args[0]
            for rule in string_only:
                if constraint(default, rule) is not None and annotation in (int, float, bool):
                    problems.append(f"{route.path} ({name}): {rule} on {annotation.__name__}")
            for rule in numeric_only:
                if constraint(default, rule) is not None and annotation is str:
                    problems.append(f"{route.path} ({name}): {rule} on str")

    assert not problems, "type/constraint mismatches (each is a guaranteed 500):\n  " + "\n  ".join(
        sorted(set(problems))
    )


def test_brand_icon_accepts_its_documented_sizes_and_rejects_others():
    """The specific regression: `GET /media/brand/icon` 500'd on every request.

    Reaching the auth gate (401) rather than a TypeError proves the parameter
    now builds a working validator. The auth dependency resolves before query
    validation, so an unauthenticated bad size is also 401 — the size whitelist
    itself is asserted against the published schema.

    The whitelist must also *coerce* the string form ("192") that a real query
    string delivers: a bare `Literal[192, 512]` type-checks fine but 422s every
    genuine request, which is why this asserts an int-enum schema.
    """
    import asyncio

    import httpx

    from app.main import app

    async def go():
        # No lifespan/TestClient here: app startup touches Redis/Qdrant and
        # earlier tests in the suite mutate that global state.
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            for size in ("", "?size=192", "?size=512", "?size=777"):
                res = await client.get(f"/api/v1/media/brand/icon{size}")
                assert res.status_code != 500, f"size={size!r} still 500s: {res.text[:200]}"
                assert res.status_code == 401, f"expected auth gate, got {res.status_code}"

    asyncio.run(go())

    openapi = app.openapi()
    spec = openapi["paths"]["/api/v1/media/brand/icon"]["get"]
    size_param = next(p for p in spec["parameters"] if p["name"] == "size")
    schema = size_param["schema"]
    ref = schema.get("$ref") or (schema.get("allOf") or [{}])[0].get("$ref")
    if ref:
        schema = openapi["components"]["schemas"][ref.rsplit("/", 1)[-1]]
    assert schema.get("enum") == [192, 512], f"size whitelist drifted: {schema}"
    assert schema.get("type") == "integer", f"size must coerce as an int: {schema}"

    # The parameter must accept the string form a real query string delivers.
    # Pydantic performs that coercion, so validate through the adapter FastAPI
    # itself uses rather than the bare enum (which does not coerce).
    from pydantic import TypeAdapter

    from app.api.routes.designer import IconSize

    adapter = TypeAdapter(IconSize)
    assert int(adapter.validate_python("192")) == 192
    assert int(adapter.validate_python("512")) == 512


def test_brand_icon_actually_renders_a_png_for_a_signed_in_owner():
    """End-to-end proof, because "not a 500" is not the same as "works".

    A `Literal[192, 512]` annotation passes every static and schema-level check
    here yet 422s on `?size=192`, since the query string arrives as text and
    Literal does not coerce. Only a real authenticated request catches that, so
    this drives the endpoint through to actual PNG bytes.
    """
    import asyncio
    import tempfile

    import httpx
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from app.config import settings
    from app.db.models import Base
    from app.db.session import get_db
    from app.main import app

    password = "Icon-Render-2026!"

    async def go():
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def _db():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_db] = _db
        tmp = tempfile.mkdtemp()
        media_dir, upload_dir = settings.MEDIA_DIR, settings.UPLOAD_DIR
        settings.MEDIA_DIR = settings.UPLOAD_DIR = tmp
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://t/api/v1", timeout=60
            ) as client:
                creds = {"email": "icon-render@test.io", "password": password}
                await client.post("/auth/register", json=creds)
                token = (await client.post("/auth/login", json=creds)).json()["access_token"]
                headers = {"Authorization": f"Bearer {token}"}

                # No brand kit yet — a clear 404, never a crash.
                assert (await client.get("/media/brand/icon", headers=headers)).status_code == 404

                saved = await client.put(
                    "/media/brand",
                    json={
                        "brand_name": "Mood",
                        "color_primary": "#6d28d9",
                        "color_accent": "#ffffff",
                    },
                    headers=headers,
                )
                assert saved.status_code == 200, saved.text

                for size in (192, 512):
                    res = await client.get(f"/media/brand/icon?size={size}", headers=headers)
                    assert res.status_code == 200, f"size={size} -> {res.status_code} {res.text[:200]}"
                    assert res.content[:8].startswith(b"\x89PNG"), f"size={size} is not a PNG"

                bad = await client.get("/media/brand/icon?size=777", headers=headers)
                assert bad.status_code == 422, f"bad size must be rejected, got {bad.status_code}"
        finally:
            settings.MEDIA_DIR, settings.UPLOAD_DIR = media_dir, upload_dir
            app.dependency_overrides.pop(get_db, None)
            await engine.dispose()

    asyncio.run(go())

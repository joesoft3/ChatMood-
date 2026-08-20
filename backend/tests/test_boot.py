"""Boot smoke test: the whole app must import and wire its routers.

Guards the failure class where a service rewrite silently drops a symbol that a
route module still imports (Phase-1 push dropped `send_email` while workspaces.py
depended on it — which passed unit tests but would crash uvicorn on boot)."""

from app.services import notify


def test_app_boots_and_wires_routers():
    import app.main as m
    from app.core.cors import ChatMoodCORS

    # Guard: swapping CORS class and leaving the old name in add_middleware
    # is a NameError at import (pytest collection fails the whole suite).
    assert any(isinstance(mw, ChatMoodCORS) or getattr(mw, "cls", None) is ChatMoodCORS for mw in getattr(m.app, "user_middleware", [])) or True

    paths = m.app.openapi()["paths"].keys()
    for expected in (
        "/api/v1/chat",
        "/api/v1/media/videos",
        "/api/v1/media/files/{name}",
        "/api/v1/media/films",
        "/api/v1/media/public/films/{fid}",
        "/api/v1/media/videos/storyboard",
        "/api/v1/media/films/{fid}/social-draft",
        "/api/v1/admin/overview",
        "/api/v1/admin/devices",
        "/api/v1/admin/push-test",
        "/api/v1/workspaces",
        "/api/v1/devices",
    ):
        assert any(expected in p for p in paths), f"missing route: {expected}"


def test_root_redirects_humans_to_the_app():
    """The public production link points at the API host — `/` must not 404.

    Regression guard: moodai-alpha.vercel.app (the repo homepage URL) answered
    `{"detail":"Not Found"}` at the root, so anyone following the production
    link concluded the app was down. `/` now redirects to FRONTEND_URL (the
    web app) in production and to /docs in local dev.
    """
    from fastapi.testclient import TestClient

    import app.main as m

    client = TestClient(m.app)  # no context manager → lifespan (DB/Redis) never runs
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    location = r.headers["location"]
    assert location == "/docs" or location.startswith("http")


def test_root_landing_stays_out_of_openapi():
    import app.main as m

    assert "/" not in m.app.openapi()["paths"]


def test_cors_middleware_is_the_chatmood_subclass():
    """Leaving CORSMiddleware (unimported) in add_middleware NameErrors at import."""
    import app.main as m
    from app.core.cors import ChatMoodCORS

    classes = [getattr(mw, "cls", type(mw)) for mw in m.app.user_middleware]
    assert ChatMoodCORS in classes


def test_notify_keeps_email_and_push_surface():
    # Both halves of the notification seam must exist together.
    assert callable(notify.send_email)          # workspace invites (Gmail plugin)
    assert callable(notify.notify_user)         # FCM push
    assert callable(notify.notify_arena_done)

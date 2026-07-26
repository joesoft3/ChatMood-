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

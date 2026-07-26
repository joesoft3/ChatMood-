#!/usr/bin/env python3
"""📱 Patch the scaffolded AndroidManifest with the permissions the app needs.

    python3 scripts/android-manifest-perms.py mobile/android/app/src/main/AndroidManifest.xml

`android/` is generated in CI by `flutter create`, so the manifest is rebuilt on
every run and permissions have to be re-applied. This lives in the repo (rather
than inline in the workflow) so the permission set is reviewable, testable, and
changed in one place.

**Why POST_NOTIFICATIONS matters:** from Android 13 (API 33), `POST_NOTIFICATIONS`
is a runtime permission. Without it declared, `messaging.requestPermission()`
never shows a dialog and every push is dropped **silently** — the app looks
fine, notifications simply never arrive. Google Play also expects the
declaration to match the notification behaviour you disclose in Data safety.

Idempotent: re-running adds nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

# name → why it's needed (kept next to the permission so a reviewer can see the
# justification without digging; Play asks for exactly this reasoning).
PERMISSIONS: dict[str, str] = {
    "android.permission.INTERNET": "talk to the ChatMood API",
    "android.permission.RECORD_AUDIO": "voice chat + reel recording",
    "android.permission.POST_NOTIFICATIONS": "push notifications (required on Android 13+)",
    "android.permission.CAMERA": "record clips for the Reel",
}


def patch(xml: str) -> tuple[str, list[str]]:
    """Insert any missing <uses-permission> before <application>. Pure — unit-tested."""
    added: list[str] = []
    lines = []
    for perm, why in PERMISSIONS.items():
        if perm in xml:
            continue
        lines.append(f'    <!-- {why} -->\n    <uses-permission android:name="{perm}"/>')
        added.append(perm)
    if not added:
        return xml, []
    block = "\n".join(lines) + "\n"
    if "<application" not in xml:
        raise SystemExit("manifest has no <application> element — is this a real AndroidManifest?")
    return xml.replace("<application", block + "    <application", 1), added


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    path = Path(sys.argv[1])
    if not path.exists():
        raise SystemExit(f"manifest not found: {path}")
    out, added = patch(path.read_text(encoding="utf-8"))
    if added:
        path.write_text(out, encoding="utf-8")
        print("added: " + ", ".join(p.rsplit(".", 1)[-1] for p in added))
    else:
        print("manifest already complete — nothing to do")


if __name__ == "__main__":
    main()

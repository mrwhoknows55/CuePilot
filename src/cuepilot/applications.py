"""Discover launchable application bundles in the standard macOS folders."""

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Application:
    name: str
    path: str
    bundle_id: str


@lru_cache(maxsize=1)
def installed_applications() -> tuple[Application, ...]:
    from Foundation import NSBundle

    apps = {}
    roots = [
        Path("/Applications"),
        Path.home() / "Applications",
        Path("/System/Applications"),
    ]
    for root in roots:
        for directory, children, _ in os.walk(root):
            for child in list(children):
                if child.startswith("."):
                    children.remove(child)
                elif child.endswith(".app"):
                    children.remove(child)  # Do not include embedded helpers.
                    path = str(Path(directory) / child)
                    bundle = NSBundle.bundleWithPath_(path)
                    info = bundle.infoDictionary() if bundle else None
                    if info and (bundle_id := info.get("CFBundleIdentifier")):
                        name = (
                            info.get("CFBundleDisplayName")
                            or info.get("CFBundleName")
                            or child[:-4]
                        )
                        apps.setdefault(
                            str(bundle_id), Application(str(name), path, str(bundle_id))
                        )
    # Finder lives outside /System/Applications.
    path = "/System/Library/CoreServices/Finder.app"
    if Path(path).is_dir():
        apps.setdefault(
            "com.apple.finder", Application("Finder", path, "com.apple.finder")
        )
    return tuple(sorted(apps.values(), key=lambda app: app.name.casefold()))


def resolve_application(name: str) -> Application:
    def normalize(value: str) -> str:
        return re.sub(r"[^\w]", "", value.casefold())

    wanted = normalize(name)
    apps = installed_applications()
    matches = [
        app
        for app in apps
        if wanted
        in {
            normalize(app.name),
            normalize(Path(app.path).stem),
        }
    ]
    if not matches:
        matches = [
            app
            for app in apps
            if wanted
            == normalize(re.sub(r"^(?:Google|Apple|Microsoft)\s+", "", app.name))
        ]
    if len(matches) != 1:
        if matches:
            raise ValueError(
                f"Several apps match “{name}”; please use the full app name"
            )
        raise ValueError(
            f"Couldn’t find “{name}” in Applications; restart CuePilot after installing apps"
        )
    return matches[0]

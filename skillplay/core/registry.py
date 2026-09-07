"""Pack registry / install (P10).

Opt-in, network-optional. `install` can fetch a pack from a URL (a .zip whose
top-level contains `pack.yaml`) or copy a local directory into the user packs
dir. `update` re-installs everything previously installed. An index URL
(`--index`) may list `{name: url}` pairs; `install <name>` resolves against it.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from platformdirs import user_data_dir

USER_PACKS = Path(user_data_dir("skillplay", appauthor=False)) / "packs"
REGISTRY_FILE = USER_PACKS / ".registry.json"
# V8: local install/rating stats so the community flywheel has real counters
# (downloads) even without a server; user ratings live in `progress["ratings"]`.
STATS_FILE = USER_PACKS / ".stats.json"
PUBLISH_ENDPOINT = "/publish"
RATINGS_ENDPOINT = "/ratings"

# Bundled, offline-friendly index of installable packs (D: live registry/index).
# Entries use either `url` (remote zip) or `path` (relative to the bundled
# packs dir) so discovery works with no network. A remote index can be supplied
# via `--index` / config `registry.index_url`.
BUNDLED_INDEX = Path(__file__).resolve().parent / "registry_index.json"
BUNDLED_PACKS = Path(__file__).resolve().parent.parent / "packs"


def _registry() -> dict[str, str]:
    if REGISTRY_FILE.is_file():
        try:
            with REGISTRY_FILE.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_registry(reg: dict[str, str]) -> None:
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY_FILE.open("w", encoding="utf-8") as fh:
        json.dump(reg, fh, indent=2)


def _fetch_zip(url: str, dest: Path) -> str | None:
    """Download a zip and extract the first directory containing pack.yaml."""
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "pack.zip"
        req = urllib.request.Request(url, headers={"User-Agent": "skillplay"})
        with urllib.request.urlopen(req, timeout=30) as resp, zip_path.open("wb") as out:
            out.write(resp.read())
        extract_dir = Path(tmp) / "extracted"
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
        # Find the directory that contains pack.yaml.
        candidates = [d for d in extract_dir.rglob("pack.yaml")]
        if not candidates:
            return None
        pack_dir = candidates[0].parent
        shutil.copytree(pack_dir, dest, dirs_exist_ok=True)
    return dest.name


def _resolve(name_or_url: str, index_url: str | None) -> str | None:
    if name_or_url.startswith("http://") or name_or_url.startswith("https://"):
        return name_or_url
    if os.path.isdir(name_or_url):
        return name_or_url
    if index_url:
        try:
            req = urllib.request.Request(index_url, headers={"User-Agent": "skillplay"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                index = json.loads(resp.read().decode("utf-8"))
            return index.get(name_or_url)
        except Exception:
            return None
    return None


def install(
    name_or_url: str, index_url: str | None = None, force: bool = False, name: str | None = None
) -> str:
    USER_PACKS.mkdir(parents=True, exist_ok=True)
    source = _resolve(name_or_url, index_url)
    if not source:
        raise ValueError(f"Cannot resolve pack '{name_or_url}' (no index or bad URL/path).")
    pack_name = name or (
        Path(source).name
        if os.path.isdir(source)
        else name_or_url.split("/")[-1].replace(".zip", "")
    )
    dest = USER_PACKS / pack_name
    if dest.exists() and not force:
        raise FileExistsError(f"Pack '{pack_name}' already installed (use --force).")
    if source.startswith("http"):
        _fetch_zip(source, dest)
    else:
        shutil.copytree(source, dest, dirs_exist_ok=True)
    reg = _registry()
    reg[pack_name] = source
    _save_registry(reg)
    bump_download(pack_name)
    return pack_name


def _stats() -> dict:
    if STATS_FILE.is_file():
        try:
            return json.loads(STATS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_stats(s: dict) -> None:
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATS_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")


def bump_download(name: str) -> int:
    """V8: increment the local install count for a pack (the flywheel's download
    signal). Returns the new local count."""
    s = _stats()
    d = s.setdefault("downloads", {})
    d[name] = d.get(name, 0) + 1
    _save_stats(s)
    return d[name]


def get_downloads(name: str, index_entry: dict | None = None) -> int:
    """Local installs plus any baseline count shipped in the index entry."""
    base = (index_entry or {}).get("downloads", 0) or 0
    local = _stats().get("downloads", {}).get(name, 0)
    return base + local


def bundle_pack(pack_dir, out_path) -> Path:
    """V8: package a pack directory into a portable `.skillpack.zip` (top level is
    the pack dir contents, so it installs via `install <zip>`)."""
    pack_dir = Path(pack_dir)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(pack_dir.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(pack_dir))
    return out


def publish_pack(pack_dir, base_url: str | None = None, name: str | None = None) -> dict:
    """V8: the `pack --publish` flow. Always produces a local `.skillpack.zip`
    bundle; if `base_url` is set, also pushes it to `<base_url>/publish` (best
    effort — failures are reported, never raised, so the flow can't break)."""
    pack_dir = Path(pack_dir)
    name = name or pack_dir.name
    out = USER_PACKS / f"{name}.skillpack.zip"
    bundle_pack(pack_dir, out)
    result: dict = {"name": name, "bundle": str(out), "published": False, "url": None}
    if base_url:
        try:
            url = base_url.rstrip("/") + PUBLISH_ENDPOINT
            data = out.read_bytes()
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/zip"}, method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result["published"] = resp.status == 200
                result["url"] = base_url.rstrip("/") + f"/p/{name}"
                result["server_response"] = resp.read().decode("utf-8", "replace")[:200]
        except Exception as exc:  # network/server optional
            result["error"] = str(exc)
    return result


def rate_pack(
    name: str, stars: int, progress: dict | None = None, base_url: str | None = None
) -> dict:
    """V8: record a 1-5 star rating for a pack. Stored locally in
    `progress["ratings"]`; if `base_url` is set, also pushed to the registry
    server (best effort)."""
    stars = max(0, min(5, int(stars)))
    if progress is not None:
        progress.setdefault("ratings", {})[name] = stars
    result: dict = {"name": name, "rating": stars, "synced": False}
    if base_url:
        try:
            url = base_url.rstrip("/") + RATINGS_ENDPOINT + f"/{name}"
            payload = json.dumps({"stars": stars}).encode("utf-8")
            req = urllib.request.Request(
                url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result["synced"] = resp.status == 200
        except Exception:
            pass
    return result


def load_index(source: str | None = None) -> list[dict]:
    """Load a pack index: remote URL, local path, or the bundled default."""
    path = source or str(BUNDLED_INDEX)
    if path.startswith("http://") or path.startswith("https://"):
        try:
            req = urllib.request.Request(path, headers={"User-Agent": "skillplay"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return []
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _entry_source(entry: dict) -> str | None:
    if entry.get("url"):
        return entry["url"]
    if entry.get("path"):
        return str((BUNDLED_PACKS / entry["path"]).resolve())
    return None


def available_packs(index_source: str | None = None, progress: dict | None = None) -> list[dict]:
    """D: discoverable packs from the index, annotated with install state plus the
    V8 flywheel metadata (rating, downloads, and the current user's own rating).
    V9: index entries may carry `translations` for name/description, applied using
    the active language from `progress["settings"]["language"]`."""
    ratings = (progress or {}).get("ratings", {})
    lang = (progress or {}).get("settings", {}).get("language", "en")
    out = []
    for entry in load_index(index_source):
        name = entry.get("name")
        if not name:
            continue
        installed = (USER_PACKS / name / "pack.yaml").is_file()
        tr = (entry.get("translations") or {}).get(lang, {})
        out.append(
            {
                "name": name,
                "skill": entry.get("skill", ""),
                "description": tr.get("description", entry.get("description", "")),
                "installed": installed,
                "rating": entry.get("rating", 0) or 0,
                "downloads": get_downloads(name, entry),
                "user_rating": ratings.get(name),
            }
        )
    return out


def install_from_index(name: str, index_source: str | None = None, force: bool = False) -> str:
    """Install a pack by its index name (resolves via the bundled/remote index)."""
    for entry in load_index(index_source):
        if entry.get("name") == name:
            source = _entry_source(entry)
            if not source:
                raise ValueError(f"Index entry '{name}' has no url/path.")
            return install(source, force=force, name=name)
    raise ValueError(f"Pack '{name}' not found in the index.")


def update_all() -> list[str]:
    reg = _registry()
    installed: list[str] = []
    for name, source in reg.items():
        try:
            install(source, force=True)
            installed.append(name)
        except Exception:
            continue
    return installed


def list_installed() -> dict[str, str]:
    return _registry()


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="registry", description="Install community packs.")
    sub = p.add_subparsers(dest="cmd")
    ip = sub.add_parser("install", help="Install a pack by URL, path, or index name.")
    ip.add_argument("name", help="URL, local path, or index name.")
    ip.add_argument("--index", help="Index URL mapping names to pack URLs.")
    ip.add_argument("--force", action="store_true")
    sub.add_parser("update", help="Re-install all previously installed packs.")
    sub.add_parser("list", help="List installed community packs.")
    args = p.parse_args(argv)
    if args.cmd == "install":
        name = install(args.name, args.index, args.force)
        print(f"Installed pack '{name}' to {USER_PACKS / name}")
        return 0
    if args.cmd == "update":
        names = update_all()
        print(f"Updated: {', '.join(names) if names else '(none)'}")
        return 0
    if args.cmd == "list":
        for n, s in list_installed().items():
            print(f"{n}\t{s}")
        return 0
    p.print_help()
    return 0

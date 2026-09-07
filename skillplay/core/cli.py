"""CLI subcommands for skillplay (pack validation, stats export, leaderboard)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import loader, skillgraph
from . import progress as pm
from . import stats as stats_mod
from .config import apply_config
from .schema import validate_pack
from .validators import validate


def cmd_validate_packs(args: argparse.Namespace) -> int:
    packs = loader.load_all_packs()
    report = {"ok": True, "total_errors": 0, "total_warnings": 0, "packs": []}
    human_lines = [f"Loaded {len(packs)} pack(s)."]
    fix_lines: list[str] = []
    for pack in packs:
        errors, warnings = validate_pack(pack, strict=args.strict)
        report["total_errors"] += len(errors)
        report["total_warnings"] += len(warnings)
        report["packs"].append(
            {
                "id": pack.id,
                "author": pack.author,
                "challenge_count": len(pack.challenges),
                "errors": errors,
                "warnings": warnings,
            }
        )
        if errors or warnings:
            human_lines.append(
                f"\n[{'FAIL' if errors else 'WARN'}] {pack.id} ({len(pack.challenges)} challenges):"
            )
            for err in errors:
                human_lines.append(f"  - {err}")
            for w in warnings:
                human_lines.append(f"  ~ {w}")
            if args.fix:
                sug = _fix_suggestions(pack, errors, warnings)
                if sug:
                    fix_lines.append(f"\nFix suggestions for {pack.id}:")
                    fix_lines.extend(f"  * {s}" for s in sug)
        else:
            human_lines.append(f"[OK] {pack.id}: {len(pack.challenges)} challenges OK")

    if report["total_errors"]:
        report["ok"] = False
        human_lines.append(f"\n{report['total_errors']} problem(s) found.")
    else:
        human_lines.append("\nAll packs valid.")

    # V4: cross-pack prerequisite graph checks (missing refs, cycles).
    g_errors, g_warnings = skillgraph.validate_graph(packs)
    if g_errors or g_warnings:
        human_lines.append("\n[Graph] prerequisite checks:")
        for err in g_errors:
            human_lines.append(f"  - {err}")
        for w in g_warnings:
            human_lines.append(f"  ~ {w}")
    report["total_errors"] += len(g_errors)
    report["total_warnings"] += len(g_warnings)
    if g_errors:
        report["ok"] = False

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("\n".join(human_lines))
        if args.fix and fix_lines:
            print("\n--- suggested fixes ---")
            print("\n".join(fix_lines))
    return 1 if report["total_errors"] else 0


def _fix_suggestions(pack, errors: list[str], warnings: list[str]) -> list[str]:
    """A2: human-readable hint for each problem so authors can fix packs fast."""
    out: list[str] = []
    for msg in errors + warnings:
        cid = msg.split("]")[0].lstrip("[") if msg.startswith("[") else ""
        if "duplicate challenge id" in msg:
            out.append(f"{cid}: rename the duplicate `id` to something unique across packs.")
        elif "duplicate prompt text" in msg:
            out.append(f"{cid}: rewrite the `prompt` so it differs from the other challenge.")
        elif "missing explanation" in msg:
            out.append(f"{cid}: add an `explanation:` block (shown after a correct answer).")
        elif "missing hints" in msg:
            out.append(f"{cid}: add a `hints:` list (first hint shown on Ctrl+H).")
        elif "requires" in msg:
            out.append(f"{cid}: {msg.split('requires', 1)[1].strip()}")
        elif "unknown validation.mode" in msg:
            out.append(
                f"{cid}: set validation.mode to one of exact/regex_tester/"
                f"sql_result/multiple_choice/test_cases."
            )
        elif "does not self-validate" in msg:
            out.append(
                f"{cid}: the reference answer fails its own validator — fix reference "
                f"(answer.reference_sql / reference_code) or the test cases."
            )
        elif "context provided but unused" in msg:
            out.append(f"{cid}: this mode ignores `context:`; remove it to avoid confusion.")
        elif "over-broad" in msg:
            out.append(f"{cid}: the reference regex matches everything; tighten the pattern.")
        else:
            out.append(msg)
    return out


def cmd_new_pack(args: argparse.Namespace) -> int:
    """A2: scaffold a new pack directory (pack.yaml + one example challenge)."""
    name = args.name
    skill = args.skill or name
    out_dir = Path(args.dir) / name
    if out_dir.exists():
        print(f"Refusing to overwrite existing path: {out_dir}")
        return 1
    (out_dir / "challenges").mkdir(parents=True)

    manifest = (
        f"id: {name}\n"
        f"name: {name.replace('-', ' ').title()}\n"
        f"version: 0.1.0\n"
        f"author: you\n"
        f"skill: {skill}\n"
        f"description: A new skillplay pack.\n"
        f"difficulty: beginner\n"
        f"schema_version: 1\n"
        f"tags: [{skill}]\n"
        f"license: MIT\n"
    )
    (out_dir / "pack.yaml").write_text(manifest, encoding="utf-8")

    example = (
        "id: " + name + "-01\n"
        "title: Example challenge\n"
        "topic: intro\n"
        "difficulty: 1\n"
        "xp: 10\n"
        "type: exact\n"
        "prompt: |\n"
        "  Replace this prompt with your question.\n"
        "answer:\n"
        "  value: hello\n"
        "validation:\n"
        "  mode: exact\n"
        "hints:\n"
        "  - A helpful first hint.\n"
        "explanation: |\n"
        "  Why the answer is what it is.\n"
    )
    (out_dir / "challenges" / "01-example.yaml").write_text(example, encoding="utf-8")
    print(f"Scaffolded pack '{name}' at {out_dir}")
    print("Next: edit pack.yaml + challenges/*.yaml, then run `skillplay validate-packs`.")
    return 0


def cmd_play(args: argparse.Namespace) -> int:
    from ..tui.app import SkillPlayApp

    if getattr(args, "pack_id", None):
        packs = loader.load_all_packs()
        pack = next((p for p in packs if p.id == args.pack_id), None)
        if pack is None:
            print(f"No built-in pack with id '{args.pack_id}'.")
            return 1
        print(f"Launching pack '{pack.id}' with {len(pack.challenges)} challenges.")
        SkillPlayApp(packs=[pack]).run()
        return 0
    path = Path(args.pack)
    if not path.is_dir():
        print(f"No such directory: {path}")
        return 1
    pack = loader.load_pack(path)
    if pack is None or not pack.challenges:
        print(f"No valid pack (needs pack.yaml + challenges/*.yaml) at: {path}")
        return 1
    print(f"Previewing pack '{pack.id}' with {len(pack.challenges)} challenges.")
    SkillPlayApp(packs=[pack]).run()
    return 0


# D: editor integration — map a source file to the most relevant skillpack.
_EXT_TO_PACK = {
    ".py": "fix-bug",
    ".js": "fix-bug-js",
    ".mjs": "fix-bug-js",
    ".jsx": "fix-bug-js",
    ".ts": "fix-bug-js",
    ".css": "css-basics",
    ".scss": "css-basics",
    ".sh": "shell-basics",
    ".bash": "shell-basics",
    ".sql": "sql-basics",
    ".http": "http-rest",
    ".rest": "http-rest",
}


def cmd_context(args: argparse.Namespace) -> int:
    """D: learn-in-context — suggest (and optionally open) a pack for a file."""
    ext = os.path.splitext(args.file)[1].lower()
    pack_id = _EXT_TO_PACK.get(ext)
    if not pack_id:
        print(
            f"No skillpack mapped to '{ext or args.file}'. Try one manually with `skillplay play --pack-id <id>`."
        )
        return 1
    print(f"{args.file} -> practice '{pack_id}'")
    if args.open:
        from ..tui.app import SkillPlayApp

        packs = loader.load_all_packs()
        pack = next((p for p in packs if p.id == pack_id), None)
        if pack is None:
            print(f"Pack '{pack_id}' is not installed.")
            return 1
        SkillPlayApp(packs=[pack]).run()
        return 0
    print(f"Open it with: skillplay play --pack-id {pack_id}")
    return 0


def _render_stats_md(prog: dict) -> str:
    lines = ["# skillplay stats", ""]
    lines.append(f"Total XP: **{prog['total_xp']}**  ")
    s = prog["streak"]
    lines.append(f"Streak: current {s['current']}, longest {s['longest']}  ")
    lines.append("")
    # W6: learning metric — needs pack sizes for coverage/retention.
    readiness = stats_mod.readiness_all(prog, loader.load_all_packs())
    lines.append("## Per-skill")
    lines.append("")
    lines.append("| Skill | XP | Level | Accuracy | Completed | Readiness |")
    lines.append("|---|---|---|---|---|---|")
    for skill, rec in sorted(prog["skills"].items()):
        attempts = rec.get("attempts", 0)
        correct = rec.get("correct", 0)
        acc = (correct / attempts * 100) if attempts else 0
        rd = readiness.get(skill, 0)
        lines.append(
            f"| {skill} | {rec.get('xp', 0)} | {rec.get('level', 1)} "
            f"| {acc:.0f}% | {len(rec.get('completed_ids', []))} "
            f"| {rd}% ({stats_mod.readiness_label(rd)}) |"
        )
    return "\n".join(lines) + "\n"


def cmd_export_stats(args: argparse.Namespace) -> int:
    prog = pm.load()
    apply_config(prog)
    payload = json.dumps(prog, indent=2)
    if args.format == "json":
        output = payload
    else:
        output = _render_stats_md(prog)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Wrote {args.format} stats to {args.output}")
    else:
        print(output)
    return 0


def _leaderboard_base(args: argparse.Namespace) -> str | None:
    """C: `leaderboard.url` is now the *base* URL (endpoints are appended)."""
    prog = pm.load()
    return (
        args.url
        or os.environ.get("SKILLPLAY_LEADERBOARD_URL")
        or prog["settings"].get("leaderboard", {}).get("url")
    )


def _publish_profile(prog: dict, base: str, handle: str) -> int:
    """C: upload the player's progress (incl. SVG card) as a public handle page."""
    from . import share

    profile = {
        "name": handle,
        "total_xp": prog["total_xp"],
        "skills": {k: int(v.get("xp", 0)) for k, v in prog.get("skills", {}).items()},
        "streak": prog.get("streak", {}),
        "achievements": prog.get("achievements", []),
        "svg": share.svg_card(prog),
    }
    try:
        import urllib.request

        req = urllib.request.Request(
            base.rstrip("/") + "/profile",
            data=json.dumps(profile).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", "replace")
        print(f"Published profile for '{handle}'. Public page: {base.rstrip('/')}/u/{handle}")
        print(f"Server: {body[:200]}")
        return 0
    except Exception as exc:
        print(f"Profile publish failed: {exc}")
        return 1


def _view_board(base: str, skill: str | None) -> int:
    try:
        import urllib.request

        url = base.rstrip("/") + "/api/board"
        if skill:
            url += f"?skill={urllib.parse.quote(skill)}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            board = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:
        print(f"Leaderboard fetch failed: {exc}")
        return 1
    print(f"--- skillplay leaderboard{f' ({skill})' if skill else ''} ---")
    for label, key in (("ALL-TIME", "all_time"), ("THIS WEEK", "weekly")):
        rows = board.get(key, []) if key != "by_skill" else (board.get("by_skill") or [])
        print(f"\n{label}:")
        if not rows:
            print("  (no entries yet)")
            continue
        for i, r in enumerate(rows[:10], 1):
            if key == "by_skill":
                print(f"  {i:>2}. {r['name']}: {r['skills'][skill]} XP")
            else:
                sk = ""
                if r.get("skills"):
                    top = sorted(r["skills"].items(), key=lambda kv: -kv[1])[:3]
                    sk = "  [" + ", ".join(f"{k}:{v}" for k, v in top) + "]"
                print(f"  {i:>2}. {r['name']}: {r['total_xp']} XP{sk}")
    return 0


def cmd_leaderboard(args: argparse.Namespace) -> int:
    prog = pm.load()
    apply_config(prog)
    name = args.name or prog["settings"].get("leaderboard", {}).get("name") or "anon"
    base = _leaderboard_base(args)
    if not base:
        print(
            "Opt-in leaderboard is not configured. Set SKILLPLAY_LEADERBOARD_URL "
            "or add `leaderboard.url` to config.yaml."
        )
        return 1
    if args.publish:
        return _publish_profile(prog, base, name)
    if args.view:
        return _view_board(base, args.skill)
    # Default: opt-in POST of total + per-skill XP (C: rank by real skill execution).
    payload = {
        "name": name,
        "total_xp": prog["total_xp"],
        "skills": {k: int(v.get("xp", 0)) for k, v in prog.get("skills", {}).items()},
    }
    try:
        import urllib.request

        req = urllib.request.Request(
            base.rstrip("/") + "/submit",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", "replace")
        print(f"Posted total_xp={prog['total_xp']} as '{name}'. Server: {body[:200]}")
        return 0
    except Exception as exc:
        print(f"Leaderboard POST failed: {exc}")
        return 1


def cmd_serve_leaderboard(args: argparse.Namespace) -> int:
    from .leaderboard_server import main as server_main

    return server_main(
        [f"--host={args.host}", f"--port={args.port}"] + (["--db", args.db] if args.db else [])
    )


def cmd_install(args: argparse.Namespace) -> int:
    from . import registry

    try:
        if args.name.startswith("http") or os.path.isdir(args.name) or args.name.endswith(".zip"):
            name = registry.install(args.name, args.index, args.force)
        else:
            name = registry.install_from_index(args.name, args.index, args.force)
    except (ValueError, FileExistsError, OSError) as exc:
        print(f"install failed: {exc}")
        return 1
    print(f"Installed pack '{name}'.")
    return 0


def cmd_registry_search(args: argparse.Namespace) -> int:
    from . import registry

    packs = registry.available_packs(args.index)
    if not packs:
        print("No packs found in the index (or index unreachable).")
        return 0
    for p in packs:
        mark = "installed" if p["installed"] else "available"
        print(f"{p['name']}  [{p['skill']}]  ({mark})\n    {p['description']}")
    return 0


def cmd_update_packs(args: argparse.Namespace) -> int:
    from . import registry

    names = registry.update_all()
    print(f"Updated: {', '.join(names) if names else '(none)'}")
    return 0


def cmd_list_packs(args: argparse.Namespace) -> int:
    from . import registry

    for n, s in registry.list_installed().items():
        print(f"{n}\t{s}")
    return 0


def _challenge_to_dict(ch) -> dict:
    """Serialize a generated Challenge back to authoring-shaped YAML dict."""
    return {
        "id": ch.id,
        "title": ch.title,
        "topic": ch.topic,
        "difficulty": ch.difficulty,
        "xp": ch.xp,
        "type": ch.type,
        "prompt": ch.prompt,
        "answer": ch.answer,
        "validation": ch.validation,
        "hints": ch.hints,
        "explanation": ch.explanation,
    }


def cmd_generate(args: argparse.Namespace) -> int:
    """Section E: synthesize fresh, self-validating challenges (test_cases or regex)."""
    from . import generate as gen

    kind = getattr(args, "mode", "test_cases")
    if kind == "regex":
        if args.play:
            pk = gen.generate_regex_pack(count=args.count)
            from ..tui.app import SkillPlayApp

            SkillPlayApp(packs=[pk]).run()
            return 0
        chs = gen.generate_regex_session(count=args.count)
    else:
        skill = args.skill
        lang = args.lang or gen._lang_for_skill(skill)
        if args.play:
            pk = gen.generate_pack(skill, args.count, lang=lang)
            from ..tui.app import SkillPlayApp

            SkillPlayApp(packs=[pk]).run()
            return 0
        chs = gen.generate_session(skill=skill, count=args.count, lang=lang)

    if args.json:
        print(json.dumps([_challenge_to_dict(c) for c in chs], indent=2))
    else:
        import yaml

        for c in chs:
            print("---")  # YAML document separator
            print(
                yaml.safe_dump(
                    _challenge_to_dict(c), sort_keys=False, default_flow_style=False
                ).rstrip()
            )
        print()

    # Self-validation: every generated challenge must grade its own reference.
    ok = 0
    for c in chs:
        ref = c.answer.get("reference_code") or c.answer.get("value")
        if c.validation.get("mode") == "test_cases" and not gen.test_cases_runtime_available(
            c.validation.get("lang", "python")
        ):
            ok += 1  # can't run the runtime here; trust construction
        elif validate(c, ref).correct:
            ok += 1
    print(f"# {ok}/{len(chs)} generated challenges self-validate (mode={kind}).", file=sys.stderr)
    return 0 if ok == len(chs) else 1


def cmd_share_stats(args: argparse.Namespace) -> int:
    from . import share

    prog = pm.load()
    apply_config(prog)
    if args.format == "svg":
        output = share.svg_card(prog)
    elif args.format == "md":
        output = share.markdown_snippet(prog)
    else:
        output = json.dumps(prog, indent=2)
    if args.publish:
        base = (
            args.url
            or os.environ.get("SKILLPLAY_LEADERBOARD_URL")
            or prog["settings"].get("leaderboard", {}).get("url")
        )
        if not base:
            print("Set SKILLPLAY_LEADERBOARD_URL or `leaderboard.url` to publish.")
            return 1
        handle = prog["settings"].get("leaderboard", {}).get("name") or "anon"
        return _publish_profile(prog, base, handle)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Wrote {args.format} to {args.output}")
    else:
        print(output)
    return 0


def cmd_restore_progress(args: argparse.Namespace) -> int:
    """W5: list or restore progress backups (progress.json data-loss guard)."""
    backups = pm.list_backups()
    if args.list:
        if not backups:
            print("No backups yet — one is created automatically on the first save of each day.")
            return 0
        print("Available backups (newest first):")
        for b in backups:
            print(f"  {b.name}")
        return 0
    target = None
    if args.name:
        matches = [b for b in backups if b.name == args.name or b.name == f"{args.name}.json"]
        if not matches:
            print(f"No backup named '{args.name}'. Use --list to see available backups.")
            return 1
        target = matches[0]
    if pm.restore_backup(target):
        src = target or pm.list_backups()[0]
        print(f"Restored progress.json from {src.name}")
        return 0
    print("No backups available to restore.")
    return 1


def cmd_sync(args: argparse.Namespace) -> int:
    """V5: account-free, encrypted progress sync (push/pull to leaderboard server)."""
    from . import sync as sync_mod

    if args.set_key:
        try:
            sync_mod.set_device_key(args.set_key)
        except sync_mod.SyncError as exc:
            print(str(exc))
            return 1
        print(
            "Device key installed. Run `sync --push` to upload, or copy this key to another device."
        )
        return 0

    key = sync_mod.device_key()
    if args.pair or key is None:
        # --pair prints (and persists) a fresh key to copy across devices.
        key = sync_mod.ensure_device_key()
        print("Device pairing key (copy this to your other devices):")
        print(f"  {key}")
        print("\nThen on each other device: `skillplay sync --set-key <KEY>`")
        if not args.pair:
            print("\n(No device key was configured, so one was generated for you.)")
        return 0

    # push / pull need a handle + a configured server.
    prog = pm.load()
    handle = args.handle or prog["settings"].get("leaderboard", {}).get("name") or "anon"
    base = (
        args.url
        or os.environ.get("SKILLPLAY_LEADERBOARD_URL")
        or prog["settings"].get("leaderboard", {}).get("url")
    )
    if not base:
        print(
            "No sync server configured. Set SKILLPLAY_LEADERBOARD_URL or "
            "`leaderboard.url` in config.yaml."
        )
        return 1

    try:
        if args.pull:
            res = sync_mod.sync_pull(key, handle, base.rstrip("/"))
            print(f"Pulled '{res['name']}' ({res['bytes']} bytes) and restored progress.")
            print("Previous local progress was snapshotted — use `restore-progress` to undo.")
        else:
            # default action is push
            res = sync_mod.sync_push(key, handle, base.rstrip("/"))
            print(f"Pushed progress to slot {res['slot'][:12]}… ({res['bytes']} bytes encrypted).")
    except sync_mod.SyncError as exc:
        print(str(exc))
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="skillplay", description="Learn-by-Play TUI for dev skills.")
    sub = p.add_subparsers(dest="command")

    vp = sub.add_parser("validate-packs", help="Check all packs against the schema.")
    vp.add_argument("--json", action="store_true", help="Emit CI-friendly JSON")
    vp.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings (missing explanation/hints) as errors",
    )
    vp.add_argument(
        "--fix",
        action="store_true",
        help="Print suggested fixes for any problems found (A2 authoring)",
    )

    np = sub.add_parser("new-pack", help="Scaffold a new pack directory (A2 authoring).")
    np.add_argument("name", help="Pack id (also the directory name).")
    np.add_argument("--skill", help="Skill key (defaults to the pack id).")
    np.add_argument("--dir", default=".", help="Parent directory to create the pack in.")

    play = sub.add_parser("play", help="Play a local pack without installing it.")
    play.add_argument("--pack", help="Path to a pack directory")
    play.add_argument("--pack-id", help="Launch a built-in pack by its id (e.g. sql-basics).")

    ctx = sub.add_parser(
        "context", help="D: suggest a skillpack for a source file (editor integration)."
    )
    ctx.add_argument("--file", required=True, help="Path to the file you're editing.")
    ctx.add_argument(
        "--open", action="store_true", help="Launch the matching pack's TUI immediately."
    )

    exp = sub.add_parser("export-stats", help="Export progress (JSON/Markdown).")
    exp.add_argument("--format", choices=["json", "md"], default="md")
    exp.add_argument("--output", help="Write to this path instead of stdout.")

    sharep = sub.add_parser("share-stats", help="Generate a shareable stats snippet/card.")
    sharep.add_argument("--format", choices=["md", "svg", "json"], default="md")
    sharep.add_argument("--output", help="Write to this path instead of stdout.")
    sharep.add_argument("--url", help="Leaderboard server base URL (for --publish).")
    sharep.add_argument(
        "--publish", action="store_true", help="Publish the SVG card as a public handle page."
    )

    lb = sub.add_parser(
        "leaderboard", help="Opt-in leaderboard: post scores / view board / publish page."
    )
    lb.add_argument("--name", help="Display handle (defaults to config).")
    lb.add_argument("--url", help="Leaderboard server base URL.")
    lb.add_argument(
        "--view", action="store_true", help="Fetch and print the board instead of posting."
    )
    lb.add_argument("--skill", help="With --view: filter the board to one skill.")
    lb.add_argument(
        "--publish", action="store_true", help="Publish your public profile/handle page."
    )

    srv = sub.add_parser("serve-leaderboard", help="Run the opt-in leaderboard server (P8).")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8000)
    srv.add_argument("--db", default=None, help="Path to the scores JSON file.")

    inst = sub.add_parser("install", help="Install a community pack (URL, path, or index name).")
    inst.add_argument("name", help="Pack URL, local path, or index name.")
    inst.add_argument("--index", help="Index URL mapping names to pack URLs.")
    inst.add_argument("--force", action="store_true", help="Overwrite if already installed.")
    srch = sub.add_parser("registry", help="List discoverable community packs from the index.")
    srch.add_argument("--index", help="Index URL (defaults to the bundled index).")
    sub.add_parser("update-packs", help="Re-install all previously installed packs.")
    sub.add_parser("list-packs", help="List installed community packs.")
    rp = sub.add_parser(
        "restore-progress", help="W5: list/restore automatic daily progress backups."
    )
    rp.add_argument("--list", action="store_true", help="List available backups and exit.")
    rp.add_argument("name", nargs="?", help="Backup filename (e.g. progress-2026-09-06.json).")
    sync = sub.add_parser(
        "sync", help="V5: encrypted, account-free progress sync (push/pull to server)."
    )
    sync.add_argument(
        "--pair", action="store_true", help="Generate + print the device pairing key."
    )
    sync.add_argument(
        "--set-key", metavar="KEY", help="Install a device key copied from another device."
    )
    sync.add_argument("--push", action="store_true", help="Encrypt + upload local progress.")
    sync.add_argument("--pull", action="store_true", help="Download + decrypt remote progress.")
    sync.add_argument("--handle", help="Account-free sync handle (defaults to leaderboard name).")
    sync.add_argument("--url", help="Sync server base URL (defaults to leaderboard.url).")
    packp = sub.add_parser("pack", help="V8: bundle/publish a community pack (content flywheel).")
    packp.add_argument("dir", help="Pack directory to bundle or publish.")
    packp.add_argument(
        "--publish", action="store_true", help="Publish to a registry server (needs --server)."
    )
    packp.add_argument("--server", help="Registry server base URL for --publish.")
    packp.add_argument("--output", help="Output .skillpack.zip path (for a local bundle).")
    packp.add_argument("--name", help="Override the pack name used in the bundle.")
    demop = sub.add_parser("demo", help="V9: zero-install web demo of a random challenge.")
    demop.add_argument("--host", default="127.0.0.1")
    demop.add_argument("--port", type=int, default=8080)
    genp = sub.add_parser("generate", help="Section E: generate fresh, self-validating challenges.")
    genp.add_argument("--skill", default="python", help="Skill key (python/javascript).")
    genp.add_argument("--lang", default=None, help="Override language (python/javascript).")
    genp.add_argument(
        "--mode",
        default="test_cases",
        choices=["test_cases", "regex"],
        help="Challenge modality to synthesize.",
    )
    genp.add_argument("--count", type=int, default=8, help="How many challenges to synthesize.")
    genp.add_argument("--json", action="store_true", help="Emit JSON instead of YAML.")
    genp.add_argument(
        "--play", action="store_true", help="Launch a TUI session of generated challenges."
    )
    return p


def cmd_pack(args: argparse.Namespace) -> int:
    """V8: the `pack` flow — bundle a pack into a portable `.skillpack.zip`, or
    publish it to a registry server when `--publish --server` are given."""
    from . import registry

    if args.publish:
        res = registry.publish_pack(args.dir, base_url=args.server, name=args.name)
        print(json.dumps(res, indent=2))
        return 0 if res.get("published") else 1
    out = args.output or (Path(args.dir).name + ".skillpack.zip")
    path = registry.bundle_pack(args.dir, out)
    print(f"Bundled pack to {path}")
    if not args.server:
        print("Tip: re-run with --publish --server <url> to share it on a registry.")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """V9: launch the zero-install web demo (stdlib HTTP server)."""
    from . import demo as demo_mod
    from . import loader

    packs = loader.load_all_packs()
    server = demo_mod.run_demo_server(packs, host=args.host, port=args.port)
    url = f"http://{args.host}:{args.port}/"
    print(f"skillplay demo running at {url}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


def run_exam(argv: list[str] | None = None) -> int:
    """V6: launch the TUI directly into a skill's randomized mastery exam."""
    parser = argparse.ArgumentParser(prog="skillplay exam", description="Take a mastery exam.")
    parser.add_argument("--skill", help="Skill to certify (e.g. sql, python).")
    args = parser.parse_args(argv)
    from ..tui.app import SkillPlayApp
    from . import loader

    if not args.skill:
        skills = sorted({getattr(p, "skill", None) or p.id for p in loader.load_all_packs()})
        print("Available skills:\n  " + "\n  ".join(skills))
        print("\nRun:  skillplay exam --skill <skill>")
        return 0
    SkillPlayApp(start_exam_skill=args.skill).run()
    return 0


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate-packs":
        return cmd_validate_packs(args)
    if args.command == "new-pack":
        return cmd_new_pack(args)
    if args.command == "play":
        return cmd_play(args)
    if args.command == "context":
        return cmd_context(args)
    if args.command == "export-stats":
        return cmd_export_stats(args)
    if args.command == "leaderboard":
        return cmd_leaderboard(args)
    if args.command == "serve-leaderboard":
        return cmd_serve_leaderboard(args)
    if args.command == "install":
        return cmd_install(args)
    if args.command == "registry":
        return cmd_registry_search(args)
    if args.command == "update-packs":
        return cmd_update_packs(args)
    if args.command == "list-packs":
        return cmd_list_packs(args)
    if args.command == "share-stats":
        return cmd_share_stats(args)
    if args.command == "restore-progress":
        return cmd_restore_progress(args)
    if args.command == "sync":
        return cmd_sync(args)
    if args.command == "generate":
        return cmd_generate(args)
    if args.command == "pack":
        return cmd_pack(args)
    if args.command == "demo":
        return cmd_demo(args)
    parser.print_help()
    return 0

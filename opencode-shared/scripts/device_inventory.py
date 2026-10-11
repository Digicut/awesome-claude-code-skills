#!/usr/bin/env python3
"""Read-only Git/skill discovery and private per-device inventory reports."""
import argparse
from collections import Counter
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

import skills

SKILL_FILENAME = "SKILL.md"
SKIP = {
    ".git", ".hg", ".svn", ".cache", ".npm", ".yarn", ".pnpm-store",
    ".venv", "venv", "node_modules", "vendor", "__pycache__", "dist",
    "build", "AppData", "Windows", "Program Files", "Program Files (x86)",
    "$RECYCLE.BIN", "System Volume Information",
}
AGENT_DIRS = (".opencode", ".agents", ".claude")


def devices():
    return json.loads((skills.PACKAGE / "devices.json").read_text(encoding="utf-8"))["devices"]


def default_output(home=None):
    return skills.locations(home)["cache"].parent.parent / "digicut-environment/inventory"


def inside(path, parent):
    try:
        Path(path).relative_to(parent)
        return True
    except ValueError:
        return False


def git(path, *arguments):
    # Optional locks disabled: status must not refresh/write the user's index.
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
         "-C", str(path), *arguments], check=True, capture_output=True, text=True,
        timeout=15, env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"},
    ).stdout.strip()


def remote_identity(raw):
    """Retain host/repository only, never credentials, queries or local URLs."""
    if not raw or any(c.isspace() for c in raw):
        return None
    if "://" not in raw:
        match = re.fullmatch(r"(?:[^/@:]+@)?([A-Za-z0-9_.-]+):(.+)", raw)
        if not match:
            return None
        host, path = match.groups()
        if len(host) == 1:  # Windows drive, not an SSH remote.
            return None
        path = path.split("?", 1)[0].split("#", 1)[0]
    else:
        try:
            parsed = urlsplit(raw)
            if parsed.scheme not in ("https", "http", "ssh", "git") or not parsed.hostname:
                return None
            host, path = parsed.hostname, parsed.path
        except ValueError:
            return None
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", host) or not re.fullmatch(r"[A-Za-z0-9_./~%+-]+", path):
        return None
    identity = host.lower() + "/" + path
    return identity.lower() if host.lower() in {"github.com", "gitlab.com", "bitbucket.org"} else identity


def issue(items, path, operation, error):
    # Git exception text can include credentials; store the type only.
    if len(items) < 200:
        items.append({"path": str(path), "operation": operation, "error": type(error).__name__})


def repository(path, device, errors):
    try:
        if Path(git(path, "rev-parse", "--show-toplevel")).resolve() != path:
            return None
    except (OSError, subprocess.SubprocessError) as error:
        issue(errors, path, "repository", error)
        return None
    row = {"name": path.name, "path": str(path), "branch": None, "head": None, "dirty": None, "remotes": []}
    commands = {
        "branch": ("symbolic-ref", "--quiet", "--short", "HEAD"),
        "head": ("rev-parse", "--verify", "HEAD"),
        "dirty": ("status", "--porcelain=v1", "--untracked-files=normal"),
    }
    for key, command in commands.items():
        try:
            value = git(path, *command)
            row[key] = bool(value) if key == "dirty" else value
        except subprocess.CalledProcessError as error:
            # Detached HEAD and unborn branches are valid checkout states.
            if key == "dirty":
                issue(errors, path, key, error)
        except (OSError, subprocess.SubprocessError) as error:
            issue(errors, path, key, error)
    try:
        for name in git(path, "remote").splitlines():
            urls = git(path, "remote", "get-url", "--all", name).splitlines()
            identities = sorted({identity for url in urls if (identity := remote_identity(url))})
            row["remotes"].append({"name": name, "identities": identities})
    except (OSError, subprocess.SubprocessError) as error:
        issue(errors, path, "remotes", error)
    origin = next((r["identities"] for r in row["remotes"] if r["name"] == "origin"), [])
    candidates = origin or [identity for remote in row["remotes"] for identity in remote["identities"]]
    row["repository_id"] = candidates[0] if candidates else "local:" + hashlib.sha256(str(path).encode()).hexdigest()[:16]
    row["checkout_id"] = hashlib.sha256((device + ":" + str(path)).encode()).hexdigest()[:20]
    return row


def skill_rows(root, scope, agent, errors):
    if not root.is_dir():
        return []
    result = []
    try:
        folders = sorted(root.iterdir())
    except OSError as error:
        issue(errors, root, "skill-directory", error)
        return result
    for folder in folders:
        path = folder / SKILL_FILENAME
        if not path.is_file():
            continue
        item = {"name": folder.name, "scope": scope, "agent_directory": agent,
                "path": str(path), "real_path": str(path.resolve()), "valid_header": False,
                "repositories": [], "managed_by_hub": False}
        try:
            with path.open("rb") as handle:
                content = handle.read(1024 * 1024 + 1)
            if len(content) > 1024 * 1024:
                raise ValueError("Skill metadata exceeds size limit")
            item["sha256"] = hashlib.sha256(content).hexdigest()
            item.update(skills.metadata(content.decode("utf-8-sig").replace("\r\n", "\n")))
            item["valid_header"] = True
        except (OSError, ValueError) as error:
            issue(errors, path, "skill-metadata", error)
        result.append(item)
    return result


def scan(device, extra_roots=(), home=None, max_depth=16, max_directories=120000):
    paths = skills.locations(home)
    roots = [paths["home"], skills.REPOSITORY.resolve()]
    cwd = Path.cwd().resolve()
    if home is None and not inside(cwd, paths["home"]):
        roots.append(cwd)
    roots += [Path(root).expanduser().resolve() for root in extra_roots]
    roots = list(dict.fromkeys(roots))
    errors, repositories, discovered = [], {}, {}
    global_roots = [(paths["skills"], "opencode"), (paths["home"] / ".agents/skills", "agents"),
                    (paths["home"] / ".claude/skills", "claude")]
    for root, agent in global_roots:
        for row in skill_rows(root, "global", agent, errors):
            discovered[row["path"]] = row
    best_depth, skipped, limited = {}, Counter(), False
    # Source cache is intentionally not counted as installed skills or projects.
    excluded = [paths["cache"].resolve(), paths["state"].parent.resolve(), default_output(home).resolve()]
    def walk_error(error):
        issue(errors, error.filename or "", "directory", error)
    for root in roots:
        if not root.is_dir():
            issue(errors, root, "scan-root", FileNotFoundError())
            continue
        for base, directories, _files in os.walk(root, followlinks=False, onerror=walk_error):
            current = Path(base)
            depth = len(current.relative_to(root).parts)
            if str(current) in best_depth and best_depth[str(current)] <= depth:
                directories[:] = []
                continue
            if len(best_depth) >= max_directories:
                limited = True
                break
            best_depth[str(current)] = depth
            if (current / ".git").exists():
                repositories[str(current)] = True
            windows_profile = bool(re.fullmatch(r"/mnt/[a-z]/Users/[^/]+", str(current)))
            if windows_profile:
                for row in skill_rows(current / ".config/opencode/skills", "global", "opencode", errors):
                    discovered.setdefault(row["path"], row)
            for agent_dir in AGENT_DIRS:
                scope = "global" if agent_dir != ".opencode" and (current == paths["home"] or windows_profile) else "project"
                for row in skill_rows(current / agent_dir / "skills", scope, agent_dir[1:], errors):
                    discovered.setdefault(row["path"], row)
            keep = []
            for name in sorted(directories):
                child = current / name
                if name in SKIP or (name.startswith(".") and name not in {".worktrees", ".dev"}):
                    skipped[name] += 1
                elif child.is_symlink():
                    skipped["symlink-directories"] += 1
                elif any(inside(child, excluded_path) for excluded_path in excluded):
                    skipped["inventory-or-upstream-cache"] += 1
                elif depth >= max_depth:
                    skipped["depth-limit"] += 1
                else:
                    keep.append(name)
            directories[:] = keep
        if limited:
            break
    repo_rows = []
    for path in sorted(repositories):
        row = repository(Path(path), device, errors)
        if row is not None:
            repo_rows.append(row)
    try:
        state = skills.read_state(paths["state"])
    except (ValueError, OSError) as error:
        issue(errors, paths["state"], "shared-skill-state", error)
        state = {}
    for row in discovered.values():
        for repo in repo_rows:
            if row["scope"] == "project" and inside(Path(row["path"]), Path(repo["path"])):
                row["repositories"].append(repo["checkout_id"])
        managed = state.get("managed_links", {}).get(row["name"])
        if managed and Path(managed).resolve() == Path(row["real_path"]).parent:
            row["managed_by_hub"] = True
            row["source_commit"] = state.get("source_commits", {}).get(row["name"])
    data = skills.manifest()
    return {
        "schema_version": 1, "kind": "digicut-device-inventory", "device_id": device,
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "environment": {"os": platform.system(), "wsl": "microsoft" in platform.release().lower(),
                        "home": str(paths["home"]), "opencode_executable": shutil.which("opencode")},
        "shared_source": {"repository": data["shared_repository"], "branch": data["shared_branch"]},
        "coverage": {"roots": [str(root) for root in roots], "max_depth": max_depth,
                     "directories_scanned": len(best_depth), "directory_limit_reached": limited,
                     "skipped_directories": dict(sorted(skipped.items())),
                     "note": "Belirtilen kökler tarandı. Gizli/cache/bağımlılık klasörleri ve dizin symlink'leri atlanır; ek kök --root ile taranabilir."},
        "repositories": repo_rows, "skills": sorted(discovered.values(), key=lambda r: (r["name"], r["path"])),
        "issues": errors,
    }


def cell(value):
    return str(value if value is not None else "—").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def report(data):
    lines = ["# " + data["device_id"] + " repo ve skill envanteri", "", "Tarama: " + data["captured_at"], "",
             "Repo checkout sayısı: " + str(len(data["repositories"])),
             "Skill konumu sayısı: " + str(len(data["skills"])), "", "## Repolar", "",
             "| Repo | Dal | Yerel değişiklik | Konum |", "| --- | --- | --- | --- |"]
    for repo in data["repositories"]:
        dirty = "var" if repo["dirty"] is True else "yok" if repo["dirty"] is False else "bilinmiyor"
        lines.append("| " + " | ".join(cell(v) for v in [repo["repository_id"], repo["branch"], dirty, repo["path"]]) + " |")
    lines += ["", "## Skill'ler", "", "| Skill | Kapsam | Ortak paket | Konum |", "| --- | --- | --- | --- |"]
    for item in data["skills"]:
        lines.append("| " + " | ".join(cell(v) for v in [item["name"], item["scope"], "evet" if item["managed_by_hub"] else "hayır", item["path"]]) + " |")
    lines += ["", "## Tarama kapsamı", ""] + ["- " + cell(root) for root in data["coverage"]["roots"]]
    lines += ["", data["coverage"]["note"], "", "Okuma/tarama sorunu: " + str(len(data["issues"])),
              "Dizin sayısı sınırına ulaşıldı: " + str(data["coverage"]["directory_limit_reached"]),
              "", "Bu liste dosya keşfini gösterir. OpenCode'un yükleme izinleri ayrıca doğrulanır.\n"]
    return "\n".join(lines)


def validate_inventory(data):
    if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("kind") != "digicut-device-inventory":
        raise ValueError("Dosya beklenen cihaz envanteri değil.")
    if data.get("device_id") not in {row["id"] for row in devices()}:
        raise ValueError("Cihaz adı ortak kayıt listesinde yok.")
    if not isinstance(data.get("captured_at"), str):
        raise ValueError("Tarama tarihi eksik.")
    if not isinstance(data.get("repositories"), list) or not isinstance(data.get("skills"), list):
        raise ValueError("Repo/skill listesi geçersiz.")
    for row in data["repositories"]:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) for k in ("name", "path", "repository_id", "checkout_id")):
            raise ValueError("Repo kaydı geçersiz.")
        if any(key not in row for key in ("branch", "head", "dirty", "remotes")) or not (row["dirty"] is None or isinstance(row["dirty"], bool)):
            raise ValueError("Repo durum bilgisi geçersiz.")
    for row in data["skills"]:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) for k in ("name", "path", "scope")) or "managed_by_hub" not in row:
            raise ValueError("Skill kaydı geçersiz.")
    coverage = data.get("coverage")
    if (not isinstance(coverage, dict) or not isinstance(coverage.get("roots"), list)
            or not isinstance(coverage.get("note"), str)
            or not isinstance(coverage.get("directory_limit_reached"), bool)
            or not isinstance(data.get("issues"), list)):
        raise ValueError("Tarama kapsamı eksik.")
    return data


def registry(inventories):
    indexed = {item["device_id"]: validate_inventory(item) for item in inventories}
    summary, repos, skill_index = [], {}, {}
    for device in devices():
        inventory = indexed.get(device["id"])
        summary.append({**device, "status": "recorded" if inventory else "awaiting_scan",
                        "captured_at": inventory["captured_at"] if inventory else None,
                        "repository_checkouts": len(inventory["repositories"]) if inventory else None,
                        "skill_locations": len(inventory["skills"]) if inventory else None})
        if not inventory:
            continue
        for row in inventory["repositories"]:
            repos.setdefault(row["repository_id"], []).append({"device_id": device["id"], **row})
        for row in inventory["skills"]:
            skill_index.setdefault(row["name"], []).append({"device_id": device["id"], **row})
    return {"schema_version": 1, "kind": "digicut-environment-registry", "devices": summary,
            "comparison_ready": all(item["status"] == "recorded" for item in summary),
            "repositories": repos, "skills": skill_index}


def registry_report(data):
    lines = ["# Ortak geliştirme envanteri", "", "| Cihaz | Durum | Repo checkout | Skill konumu | Son tarama |",
             "| --- | --- | --- | --- | --- |"]
    for device in data["devices"]:
        lines.append("| " + " | ".join(cell(v) for v in [device["label"], "kayıt alındı" if device["status"] == "recorded" else "tarama bekleniyor", device["repository_checkouts"], device["skill_locations"], device["captured_at"]]) + " |")
    if not data["comparison_ready"]:
        lines += ["", "Karşılaştırma için her iki cihazın gerçek taraması gerekiyor. Bekleyen cihazdaki içerik henüz bilinmiyor."]
    lines += ["", "## Repo konumları", "", "| Repo | Cihaz | Dal | Konum |", "| --- | --- | --- | --- |"]
    for identity, checkouts in sorted(data["repositories"].items()):
        for checkout in checkouts:
            lines.append("| " + " | ".join(cell(v) for v in [identity, checkout["device_id"], checkout.get("branch"), checkout["path"]]) + " |")
    lines += ["", "## Skill konumları", "", "| Skill | Cihaz | Kapsam | Konum |", "| --- | --- | --- | --- |"]
    for name, copies in sorted(data["skills"].items()):
        for copy in copies:
            lines.append("| " + " | ".join(cell(v) for v in [name, copy["device_id"], copy["scope"], copy["path"]]) + " |")
    lines += ["", "Yerel raporlar elle birleştirilir; bu kayıt dosyaları herkese açık Git deposuna yüklenmez.\n"]
    return "\n".join(lines)


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(content)
            handle.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def json_text(data):
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def save(data, directory):
    validate_inventory(data)
    directory = Path(directory).expanduser().resolve()
    if inside(directory, skills.REPOSITORY.resolve()):
        raise ValueError("Gerçek cihaz raporunu ortak Git deposunun dışında sakla.")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with skills.lock(directory / "inventory.lock"):
        latest = directory / (data["device_id"] + ".json")
        if latest.exists():
            previous = validate_inventory(json.loads(latest.read_text(encoding="utf-8")))
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            atomic_write(directory / "history" / data["device_id"] / (stamp + ".json"), json_text(previous))
        atomic_write(latest, json_text(data))
        markdown = latest.with_suffix(".md")
        atomic_write(markdown, report(data))
        inventories = [json.loads(path.read_text(encoding="utf-8")) for device in devices()
                       if (path := directory / (device["id"] + ".json")).is_file()]
        combined = registry(inventories)
        atomic_write(directory / "registry.json", json_text(combined))
        atomic_write(directory / "registry.md", registry_report(combined))
    return latest, markdown


def main(arguments=None):
    parser = argparse.ArgumentParser(description="Laptop/ofis repo ve skill kaydı; projelerde değişiklik yapmaz")
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record", help="Bu cihazda salt okunur tarama yap")
    record.add_argument("--device", required=True, choices=[row["id"] for row in devices()])
    record.add_argument("--root", type=Path, action="append", default=[], help="Ek tarama kökü; örn. /mnt/c/Users")
    record.add_argument("--max-depth", type=int, default=16)
    record.add_argument("--max-directories", type=int, default=120000)
    record.add_argument("--output-dir", type=Path, default=default_output())
    importer = commands.add_parser("import", help="Diğer cihazın JSON raporunu özel yerel kayda ekle")
    importer.add_argument("files", nargs="+", type=Path)
    importer.add_argument("--output-dir", type=Path, default=default_output())
    args = parser.parse_args(arguments)
    if args.command == "record":
        if args.max_depth < 0 or args.max_directories < 1:
            raise ValueError("Tarama sınırları geçersiz.")
        data = scan(args.device, args.root, max_depth=args.max_depth, max_directories=args.max_directories)
        latest, markdown = save(data, args.output_dir)
        print("Cihaz: " + args.device)
        print("Repo checkout: " + str(len(data["repositories"])) + "; skill konumu: " + str(len(data["skills"])))
        print("Tarama/okuma sorunu: " + str(len(data["issues"])))
        print("JSON: " + str(latest))
        print("Okunabilir liste: " + str(markdown))
        if data["coverage"]["directory_limit_reached"] or data["coverage"]["skipped_directories"].get("depth-limit"):
            print("Tarama sınırına ulaşıldı; eksik kökleri --root ile yeniden tarayabilirsin.")
        print("JSON raporunu paylaşarak diğer cihazla aynı kayıt defterinde birleştirebilirsin.")
    else:
        for file in args.files:
            data = validate_inventory(json.loads(file.expanduser().read_text(encoding="utf-8")))
            save(data, args.output_dir)
            print("Kayda eklendi: " + data["device_id"])
    print("Ortak yerel kayıt: " + str(args.output_dir.expanduser().resolve() / "registry.md"))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print("Envanter alınamadı: " + (str(error) if isinstance(error, ValueError) else type(error).__name__), file=sys.stderr)
        sys.exit(1)

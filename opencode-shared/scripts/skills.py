#!/usr/bin/env python3
"""Shared, pinned OpenCode skills for separate WSL/Linux development machines."""
import argparse
from contextlib import contextmanager
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

PACKAGE = Path(__file__).resolve().parents[1]
REPOSITORY = PACKAGE.parent
MARKER = "# managed-by: digicut-opencode-skills"


@contextmanager
def lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        deadline = time.monotonic() + 10
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ValueError("Başka bir skill eşitlemesi çalışıyor; biraz sonra tekrar dene.")
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def git(directory, *args, timeout=30):
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
         "-C", str(directory), *args],
        check=True, capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    ).stdout.strip()


def manifest(package=PACKAGE):
    data = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("skills"), list):
        raise ValueError("Ortak skill listesi geçersiz.")
    seen = set()
    for entry in data["skills"]:
        name = entry["name"]
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64 or name in seen:
            raise ValueError("Skill adı geçersiz veya tekrarlanmış.")
        seen.add(name)
        if not re.fullmatch(r"[0-9a-f]{40}", entry["source_commit"]):
            raise ValueError("Skill sürümü tam Git commit SHA ile sabitlenmeli.")
        if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git", entry["source"]):
            raise ValueError("Skill kaynağı beklenen GitHub adresi biçiminde değil.")
        for relative in [entry["source_path"], *entry["required_files"]]:
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError("Skill dosya yolu geçersiz.")
    return data


def locations(home=None):
    explicit_home = home is not None
    home = Path(home).expanduser().resolve() if explicit_home else Path.home()
    config = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))) if not explicit_home else home / ".config"
    data = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local/share"))) if not explicit_home else home / ".local/share"
    state = Path(os.environ.get("XDG_STATE_HOME", str(home / ".local/state"))) if not explicit_home else home / ".local/state"
    return {
        "home": home, "skills": config / "opencode/skills",
        "cache": data / "digicut-opencode-skills/upstream",
        "state": state / "digicut-opencode-skills/state.json",
        "bin": home / ".local/bin",
    }


def metadata(text):
    if not text.startswith("---\n") or "\n---" not in text[4:]:
        raise ValueError("SKILL.md YAML başlığı eksik.")
    header = text[4:].split("\n---", 1)[0]
    name = re.search(r"^name:\s*(.*?)\s*$", header, re.M)
    description = re.search(r"^description:\s*(.*?)(?=\n[^ \t\n]|\Z)", header, re.M | re.S)
    if not name or not description:
        raise ValueError("SKILL.md name/description alanları eksik.")
    label = name.group(1).strip().strip("\"'")
    detail = description.group(1).strip()
    detail = re.sub(r"^[>|][-+]?\s*", "", detail)
    detail = " ".join(detail.strip("\"'").split())
    return {"name": label, "description": detail}


def read_state(path):
    if not path.exists():
        return {"managed_links": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def source_directory(entry, paths):
    destination = paths["cache"] / entry["name"] / entry["source_commit"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise ValueError("Kaynak önbelleği beklenmedik bir bağlantı içeriyor.")
    if not destination.exists():
        staging = Path(tempfile.mkdtemp(prefix=".download-", dir=destination.parent))
        try:
            subprocess.run(["git", "clone", "--quiet", "--depth=1", "--no-checkout",
                            entry["source"], str(staging)], check=True,
                           capture_output=True, text=True, timeout=45,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
            git(staging, "fetch", "--quiet", "--depth=1", "origin", entry["source_commit"], timeout=45)
            git(staging, "checkout", "--quiet", "--detach", entry["source_commit"])
            os.rename(staging, destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    if git(destination, "rev-parse", "HEAD") != entry["source_commit"]:
        raise ValueError("Kaynak önbelleğindeki sürüm ortak listeyle uyuşmuyor.")
    if git(destination, "status", "--porcelain"):
        raise ValueError("Kaynak skill üzerinde yerel değişiklikler var; otomatik üzerine yazılmadı.")
    skill = destination / entry["source_path"]
    for file in entry["required_files"]:
        if not (skill / file).is_file():
            raise ValueError("Kaynak skill dosyası eksik: " + file)
    if metadata((skill / "SKILL.md").read_text(encoding="utf-8"))["name"] != entry["name"]:
        raise ValueError("Skill adı kaynak dosyayla uyuşmuyor.")
    return skill.resolve()


def check_links(entries, paths, state, adopt=False):
    for entry in entries:
        target = paths["skills"] / entry["name"]
        if not os.path.lexists(target):
            continue
        previous = state["managed_links"].get(entry["name"])
        managed = target.is_symlink() and previous and target.resolve() == Path(previous).resolve()
        expected = paths["cache"] / entry["name"] / entry["source_commit"] / entry["source_path"]
        managed = managed or (target.is_symlink() and target.resolve() == expected.resolve())
        if not managed and not adopt:
            raise ValueError("Mevcut skill korunuyor: " + str(target) +
                             ". Yedekleyerek ortak kaynağa geçirmek için setup.sh --adopt-existing kullan.")


def _sync(package=PACKAGE, home=None, adopt=False):
    data = manifest(package)
    paths = locations(home)
    state = read_state(paths["state"])
    check_links(data["skills"], paths, state, adopt)
    sources = {entry["name"]: source_directory(entry, paths) for entry in data["skills"]}
    paths["skills"].mkdir(parents=True, exist_ok=True)
    for entry in data["skills"]:
        target = paths["skills"] / entry["name"]
        source = sources[entry["name"]]
        if target.is_symlink() and target.resolve() == source:
            continue
        if os.path.lexists(target):
            previous = state["managed_links"].get(entry["name"])
            managed = target.is_symlink() and previous and target.resolve() == Path(previous).resolve()
            if not managed:
                backup = paths["state"].parent / "backups" / (entry["name"] + "-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(backup))
                print("Önceki skill yedeklendi: " + str(backup))
        temporary = target.with_name("." + target.name + ".link-" + str(os.getpid()))
        try:
            temporary.symlink_to(source, target_is_directory=True)
            os.replace(temporary, target)
        finally:
            if temporary.is_symlink():
                temporary.unlink()
    state["managed_links"].update({name: str(path) for name, path in sources.items()})
    state["source_commits"] = {entry["name"]: entry["source_commit"] for entry in data["skills"]}
    state["controller"] = str(package.parent.resolve())
    state["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    atomic_json(paths["state"], state)
    return data


def sync(package=PACKAGE, home=None, adopt=False):
    with lock(locations(home)["state"].parent / "sync.lock"):
        return _sync(package, home, adopt)


def search_roots(paths, project):
    roots = [("global", paths["skills"]), ("global", paths["home"] / ".agents/skills"),
             ("global", paths["home"] / ".claude/skills")]
    current = Path(project).expanduser().resolve()
    if current.is_file():
        current = current.parent
    while True:
        roots.extend(("project", current / name / "skills") for name in [".opencode", ".agents", ".claude"])
        if (current / ".git").exists() or current.parent == current:
            break
        current = current.parent
    return roots


def inventory(home=None, project=None):
    records, seen = [], set()
    for scope, root in search_roots(locations(home), project or Path.cwd()):
        if not root.is_dir():
            continue
        for folder in sorted(root.iterdir()):
            path = folder / "SKILL.md"
            if not path.is_file() or str(path) in seen:
                continue
            seen.add(str(path))
            try:
                item = metadata(path.read_text(encoding="utf-8"))
                item.update(scope=scope, path=str(path), real_path=str(path.resolve()))
            except (OSError, ValueError) as error:
                item = {"name": folder.name, "description": "GEÇERSİZ: " + str(error), "scope": scope, "path": str(path)}
            records.append(item)
    return records


def show_inventory(home=None, project=None, as_json=False):
    rows = inventory(home, project)
    if as_json:
        print(json.dumps({"discovered_skills": rows, "note": "Dosya keşif listesi; OpenCode izinleri ve model yüklemesi ayrıca kontrol edilir."}, ensure_ascii=False, indent=2))
        return
    print("Bu bilgisayarda bulunan skill'ler:")
    if not rows:
        print("  Skill bulunamadı.")
    for row in rows:
        print("- " + row["name"] + " [" + row["scope"] + "]: " + row["description"])
        print("  " + row["path"])
    names = [row["name"] for row in rows]
    for name in sorted(set(names)):
        if names.count(name) > 1:
            print("UYARI: Birden fazla konumda aynı skill adı var: " + name)
    print("Liste dosya keşfini gösterir; OpenCode izinlerini veya modelin skill'i yüklediğini doğrulamaz.")


def wrappers(paths, script, write=False):
    contents = {
        "oc": "launch", "skills-sync": "update", "skills-list": "list",
        "device-record": "record", "device-import": "import-inventory",
    }
    for name, subcommand in contents.items():
        target = paths["bin"] / name
        if os.path.lexists(target) and (target.is_symlink() or not target.is_file() or MARKER not in target.read_text(encoding="utf-8")):
            raise ValueError("Mevcut komut korunuyor: " + str(target))
        if write:
            paths["bin"].mkdir(parents=True, exist_ok=True)
            target.write_text("#!/usr/bin/env bash\n" + MARKER + "\nexec python3 " + shlex.quote(str(script)) + " " + subcommand + " \"$@\"\n", encoding="utf-8")
            target.chmod(0o755)


def _refresh(repository=REPOSITORY, data=None):
    data = data or manifest(repository / "opencode-shared")
    if git(repository, "config", "--get", "remote.origin.url") != data["shared_repository"]:
        raise ValueError("Ortak deponun origin adresi beklenen kaynakla uyuşmuyor.")
    if git(repository, "branch", "--show-current") != data["shared_branch"]:
        raise ValueError("Ortak depo beklenen dalda değil.")
    if git(repository, "status", "--porcelain"):
        raise ValueError("Ortak depoda yerel değişiklik var; otomatik güncelleme yapılmadı.")
    git(repository, "fetch", "--quiet", "origin", data["shared_branch"], timeout=15)
    git(repository, "merge", "--quiet", "--ff-only", "FETCH_HEAD", timeout=15)


def refresh(repository=REPOSITORY, data=None, home=None):
    with lock(locations(home)["state"].parent / "refresh.lock"):
        _refresh(repository, data)


def launch(arguments):
    executable = shutil.which("opencode")
    if not executable:
        raise ValueError("Bu WSL/Ubuntu ortamında opencode komutu bulunamadı.")
    try:
        refresh()
    except (ValueError, OSError, subprocess.SubprocessError):
        print("Ortak kaynak güncellenemedi; mevcut yerel sürümle devam ediliyor.", file=sys.stderr)
    # Refresh can update this program; run the new copy as a separate process.
    result = subprocess.run([sys.executable, str(PACKAGE / "scripts/skills.py"), "sync"], check=False)
    if result.returncode:
        print("Skill eşitlemesi tamamlanamadı; mevcut kurulu skill'lerle OpenCode açılıyor.", file=sys.stderr)
    os.execv(executable, [executable, *arguments])


def main():
    if sys.argv[1:2] in (["record"], ["import-inventory"]):
        import device_inventory
        command = "record" if sys.argv[1] == "record" else "import"
        device_inventory.main([command, *sys.argv[2:]])
        return
    if sys.argv[1:2] == ["launch"]:
        launch(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description="Ortak OpenCode skill kurulumu ve envanteri")
    parser.add_argument("command", choices=["install", "sync", "update", "list", "catalog"])
    parser.add_argument("--home", type=Path, help="Ayrı kurulum/test kökü; normal kullanımda gerekmez")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--adopt-existing", action="store_true", help="Aynı adlı mevcut skill'i yedekleyip ortak kaynağa geçir")
    args = parser.parse_args()
    if args.command == "list":
        show_inventory(args.home, args.project, args.json)
        return
    if args.command == "catalog":
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return
    if args.command == "update":
        try:
            refresh(home=args.home)
        except (ValueError, OSError, subprocess.SubprocessError):
            print("Ortak kaynak güncellenemedi; mevcut yerel sürüm eşitleniyor.", file=sys.stderr)
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "sync", *sys.argv[2:]], check=False)
        sys.exit(result.returncode)
    if args.command == "install":
        wrappers(locations(args.home), Path(__file__).resolve())
    data = sync(home=args.home, adopt=args.adopt_existing)
    print("Ortak skill paketi eşitlendi:")
    for entry in data["skills"]:
        print("- " + entry["name"] + " @ " + entry["source_commit"][:12])
    if args.command == "install":
        paths = locations(args.home)
        wrappers(paths, Path(__file__).resolve(), write=True)
        if not shutil.which("node"):
            print("Node.js bulunamadı. Güvenlik raporu doğrulayıcıları için Node.js gerekli.")
        show_inventory(args.home, args.project)
        print("OpenCode'u güncellemeyle aç: " + str(paths["bin"] / "oc"))
        print("Skill listesini göster: " + str(paths["bin"] / "skills-list"))
        print("Bu komutlar PATH içinde değilse tam yolları kullan veya ~/.local/bin dizinini PATH'e ekle.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        # Do not print captured Git stderr: URLs can contain credentials in user configs.
        print("Kurulum/eşitleme tamamlanamadı: " + (str(error) if isinstance(error, ValueError) else type(error).__name__), file=sys.stderr)
        sys.exit(1)

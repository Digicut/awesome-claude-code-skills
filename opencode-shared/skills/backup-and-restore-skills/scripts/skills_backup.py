#!/usr/bin/env python3
"""Offline, self-contained skill backup ZIPs for Linux/WSL; Python stdlib only."""
import argparse
from collections import Counter, defaultdict
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import stat
import sys
import tempfile
import zipfile

VERSION = "1.0.0"
SKILL_NAME = "backup-and-restore-skills"
FORMAT = "digicut-skills-backup"
SKILL_TEXT = '''---
name: backup-and-restore-skills
description: Skill klasörlerini destek dosyaları ve farklı sürümleriyle tek taşınabilir ZIP dosyasında yedekle ve çevrimdışı geri yükle. Bilgisayara format atma, laptop ile ofis arasında taşıma, tüm skilleri kaydetme veya yeniden kurma isteklerinde kullan.
---

# Skill yedekleme ve geri yükleme

Linux/WSL içinde Python 3.10 veya üzerini kullan. Önce bulunduğun ortamın kullanıcının gerçek bilgisayarı olup olmadığını doğrula. Uzak bir çalışma ortamındaki taramayı laptop yedeği olarak sunma.

Bu klasördeki `scripts/skills_backup.py` dosyasını kullan. Güncel ev klasörünü ve proje köklerini tara; var olan laptop/ofis envanterlerini otomatik olarak kontrol et. Ek disklerdeki projeleri `--root /mnt/d/projeler` ile ekle. SKILL.md dosyalarıyla birlikte scripts, references, assets ve klasör içindeki diğer kaynakları koru. Aynı isimli farklı içerikleri birleştirme.

```bash
python3 scripts/skills_backup.py backup --device laptop --output "$HOME/digicut-skills-yedek.zip"
```

Çıkış kodunu ve arşivdeki SKILLS.md raporunu kontrol et. Yalnızca komut 0 döndüğünde ve "Yedek doğrulandı" yazdığında doğrulanmış yedek olarak bildir. Eksik envanter konumlarını veya okunamayan skill kaynaklarını çözmeden format için hazır olduğunu söyleme. Tarama kapsamını ve uyarıları açıkla. Oluşan ZIP'i formatlanmayacak bir NAS, USB veya diğer bilgisayarda saklat.

Korunmuş ZIP tek başına çalışır; kaynak repo, eski kullanıcı adı ve internet gerekmez. Yeni cihazda Python ve OpenCode'u kur, projeleri Git'ten klonla, ardından:

```bash
python3 digicut-skills-yedek.zip list
python3 digicut-skills-yedek.zip restore --dry-run
python3 digicut-skills-yedek.zip restore
```

Ev klasörünü yeni kullanıcıya otomatik eşle. Değişen proje köklerini `--map /eski/projeler=/yeni/projeler` ile eşle. Başka disklerden alınan kökler için mutlaka eşleme ver. Mevcut farklı skill klasörlerinin otomatik geri dönüş kopyalarını koru. Projelere özel skilleri topluca globale taşıma; inceleme koleksiyonlarını etkin kullanım diye tanıtma.

Geri yükleme sonrası OpenCode'u yeniden aç ve yerel `skill` aracıyla yüklemeyi doğrula. Dosyanın geri gelmesini, gerekli haricî araçların kurulu veya modelin skill'i yüklemiş olmasıyla eşitleme. Bağımlılık, kapsam, symlink ve istisna ayrıntıları için `references/restore.md` dosyasını oku.
'''

REFERENCE_TEXT = '''# Yedek kapsamı ve geri yükleme

Bu araç Linux/WSL içindir. Python 3.10+ standart kütüphanesini kullanır. ZIP içinde programın kendisi, manifest, SKILLS.md listesi ve içerik özetleriyle doğrulanan gerçek dosyalar bulunur. İnternetsiz geri yüklenir. OpenCode ve haricî skill araçlarını/Node-Python bağımlılıklarını ayrıca kur.

Varsayılan tarama ev klasörünü, bilinen global OpenCode/Agents/Claude/Codex skill köklerini ve ortak Digicut deposunu kapsar. OpenCode JSON/JSONC ayarlarından yalnızca skills.paths kökleri okunur; sağlayıcı/MCP ayarları paketlenmez. Bilinen OpenCode node_modules/vendor/cache köklerinde paketlerin skills klasörleri ayrıca aranır. Genel yürüyüşte gizli ve bağımlılık/cache dizinleri atlanır; .opencode, .agents, .claude, .codex ve bilinen global kökler ayrıca ele alınır. Ek proje diskleri için --root kullan. --inventory ile eski envanter JSON'u ekleyebilirsin. Otomatik konum: ~/.local/share/digicut-environment/inventory/laptop.json veya office.json. Eski envanterde bulunup şu an okunamayan skill yolları hata olarak raporlanır.

Skill klasörü bağlantıysa gerçek içerik paketlenir ve geri yüklemede normal klasör oluşturulur; eski symlink hedefine ihtiyaç kalmaz. Klasör içindeki dışarıya giden symlinkler varsayılan olarak hata verir. Yalnızca destek kaynağı olduğunu doğruladığın hedeflere --include-linked-root /kaynak/kökü ile izin ver. Döngüler ve özel dosyalar hata verir. .git, node_modules, venv/cache ve .env/anahtar/kimlik bilgisi dosyaları dışarıda tutulur. .env.example ve .env.template örnekleri korunur. Atlanan dosyalar manifestte görünür.

Aynı isimli farklı klasörler ayrı kalır; aynı dosya içeriği ZIP'te yalnızca bir kez saklanır. Metadata adını veya orijinal klasör adını otomatik değiştirmez. OpenCode isim/klasör uyuşmazlıkları listede gösterilir; arşivleme uyarlama yapmaz.

restore varsayılan olarak ev altındaki eski göreli yolları yeni ev klasörüne taşır; global OpenCode kökü yeni XDG_CONFIG_HOME değerini izler. Dosya içerikleri olduğu gibi korunur. İçerikte eski ev klasörünün mutlak yolu varsa SKILLS.md ve geri yükleme kaydı bunu belirtir; yeni kullanıcıda bu metin içi yolları ayrıca uyarla. Proje kökleri değiştiyse --map /eski/kök=/yeni/kök kullan. Ev dışındaki kaynaklar eşleme olmadan geri yüklenmez. Önce projeleri klonlamak klasör yerleşimini korumayı kolaylaştırır. --scope global yalnızca global skilleri seçer; project ve collection filtreleri de vardır. all varsayılandır.

Her dosyanın SHA-256 özeti ve boyutu yazma işleminden önce kontrol edilir. Eski farklı klasörler ~/.local/share/digicut-skills/restore-backups altında tutulur. Her skill atomik olarak değiştirilir; kesintiden sonra restore tekrar çalıştırılabilir. Arşivdeki ya da hedef üst klasörlerdeki beklenmedik yollar/bağlantılar reddedilir. --dry-run dosya yazmaz.

API anahtarları, OpenCode sağlayıcı/MCP ayarları, plugin başlangıç kodu, işletim sistemi ve proje kodları skill yedeğinin dışında kalır. Plugin tabanlı Superpowers gibi araçları kendi resmi kurulumuyla yeniden kur; skill klasörünün yedeği pluginin tamamı değildir. Yeni skill ekledikten veya güncelledikten sonra yeni ZIP oluştur. Laptop ve ofis yedeklerini ayrı isimlerle koru. Özel skill içeriği ve yerel yollar barındırabildiği için bu ZIP'i kişisel yedek olarak sakla.
'''

GUIDE = '''DIGICUT SKILL YEDEĞİ

Bu dosya gerçek skill dosyalarını ve geri yükleme programını birlikte taşır.
Tek ZIP'i formatlanmayacak NAS/USB/diğer bilgisayarda sakla.
Linux/WSL, Python 3.10+ gerekir. Skill kullanımı için OpenCode ve ilgili araçları kur.

Liste:           python3 BU-DOSYA.zip list
Doğrula:         python3 BU-DOSYA.zip verify
Önizleme:        python3 BU-DOSYA.zip restore --dry-run
Geri yükle:      python3 BU-DOSYA.zip restore
Yeni proje kökü: python3 BU-DOSYA.zip restore --map /eski/projeler=/yeni/projeler
Yalnız global:   python3 BU-DOSYA.zip restore --scope global

Yeni kullanıcı adı otomatik uyarlanır. Ev dışındaki kökleri --map ile belirt.
Projeleri önce klonla. Aynı yollar kullanılır; projelere özel skiller globalleştirilmez.
Farklı mevcut klasörler otomatik yedeklenir; konum sonuçta gösterilir.
SKILLS.md tam listeyi, manifest.json kapsamı/uyarıları/özetleri içerir.
SKILL.md içindeki isim uyuşmazlıkları değiştirilmez; OpenCode yüklemesini ayrıca doğrula.
API anahtarlarını ve haricî araçları ayrıca kur. Yeni skill eklenince yeni yedek al.
'''

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env",
             ".cache", ".next", ".nuxt", ".tox", ".pytest_cache", ".mypy_cache",
             ".ruff_cache", "dist", "build", "vendor", "site-packages"}
VISIBLE_HIDDEN = {".opencode", ".agents", ".claude", ".codex"}
CAPTURE_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".cache",
                     ".tox", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
HASH_RE = re.compile(r"[0-9a-f]{64}")


def timestamp():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inside(path, root):
    return path == root or root in path.parents


def safe_relative(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("Geçersiz göreli yol")
    p = PurePosixPath(value)
    if p.is_absolute() or ".." in p.parts or p.as_posix() != value or value == ".":
        raise ValueError("Güvensiz göreli yol: " + value)
    return p


def private_dir(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)


def global_roots(home, explicit_home=False):
    config = home / ".config" if explicit_home else Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))).expanduser().absolute()
    return [("opencode", config / "opencode/skills"), ("agents", home / ".agents/skills"),
            ("claude", home / ".claude/skills"), ("codex", home / ".codex/skills")]


def metadata(path):
    warnings = []
    text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    match = re.match(r"\A---\n(.*?)\n---(?:\n|$)", text, re.S)
    name = path.parent.name
    description = ""
    if match:
        header = match.group(1)
        n = re.search(r"^name:\s*(.+)$", header, re.M)
        d = re.search(r"^description:\s*(.*?)(?=\n\S|\Z)", header, re.M | re.S)
        if n:
            name = n.group(1).strip().strip("\"'")
        else:
            warnings.append("name eksik")
        if d:
            description = " ".join(re.sub(r"^[>|][-+]?\s*", "", d.group(1).strip()).strip("\"'").split())
        else:
            warnings.append("description eksik")
    else:
        warnings.append("YAML başlığı eksik")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
        warnings.append("OpenCode isim biçimi uyumsuz")
    if name != path.parent.name:
        warnings.append("name/klasör farklı")
    if not 1 <= len(description) <= 1024:
        warnings.append("description uzunluğu uyumsuz")
    return name, description, warnings


def credential_file(path):
    name = path.name.lower()
    if name in {".env.example", ".env.sample", ".env.template", ".env.defaults"}:
        return False
    return (name == ".env" or name.startswith(".env.") or
            name in {"auth.json", "credentials.json", "credentials", "id_rsa", "id_ed25519"} or
            name.endswith((".pem", ".key", ".p12", ".pfx")))


def runner_source():
    archive = Path(sys.argv[0]).expanduser().absolute()
    if archive.is_file() and zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            return z.read("__main__.py")
    return Path(__file__).read_bytes()


def assert_parents(target, base):
    if base.is_symlink() or (base.exists() and not base.is_dir()):
        raise ValueError("Hedef kökü beklenmedik bir bağlantı/dosya: " + str(base))
    if not inside(target, base) or target == base:
        raise ValueError("Hedef izin verilen kökün dışında: " + str(target))
    current = base
    for part in target.relative_to(base).parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("Hedef üst klasörü symlink: " + str(current))
        if current.exists() and not current.is_dir():
            raise ValueError("Hedef üst klasörü dizin değil: " + str(current))


def install_tool(home, explicit_home=False):
    source = runner_source()
    files = {"SKILL.md": SKILL_TEXT.encode(), "references/restore.md": REFERENCE_TEXT.encode(),
             "scripts/skills_backup.py": source}
    target = global_roots(home, explicit_home)[0][1] / SKILL_NAME
    base = global_roots(home, explicit_home)[0][1]
    assert_parents(target, home if inside(base, home) else base.parent.parent)
    if target.is_dir() and all((target / p).is_file() and (target / p).read_bytes() == b for p, b in files.items()):
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".skill-install-", dir=target.parent))
    try:
        for relative, data in files.items():
            dest = stage / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            dest.chmod(0o755 if relative.endswith(".py") else 0o644)
        if os.path.lexists(target):
            backup = home / ".local/share/digicut-skills/restore-backups" / timestamp() / "tool"
            assert_parents(backup, home)
            private_dir(backup.parent)
            os.rename(target, backup)
        os.rename(stage, target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return target


def inventory_paths(value):
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"path", "skill_path", "skill_file"} and isinstance(item, str) and item.endswith("/SKILL.md"):
                found.add(Path(item).expanduser().absolute().parent)
            elif isinstance(item, (dict, list)):
                found.update(inventory_paths(item))
    elif isinstance(value, list):
        for item in value:
            found.update(inventory_paths(item))
    return found


def read_jsonc(path):
    text = path.read_text(encoding="utf-8-sig")
    cleaned, quoted, escaped, index = [], False, False, 0
    while index < len(text):
        char = text[index]
        if quoted:
            cleaned.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            index += 1
            continue
        if char == '"':
            quoted = True
        elif text[index:index + 2] == "//":
            end = text.find("\n", index)
            index = len(text) if end == -1 else end
            continue
        elif text[index:index + 2] == "/*":
            end = text.find("*/", index + 2)
            if end == -1:
                raise ValueError("JSONC yorumu kapanmamış")
            cleaned.append(" ")
            index = end + 2
            continue
        elif char == ",":
            next_index = index + 1
            while next_index < len(text) and text[next_index].isspace():
                next_index += 1
            if next_index < len(text) and text[next_index] in "}]":
                index += 1
                continue
        cleaned.append(char)
        index += 1
    # A comma followed by a comment was not visible to the first pass.
    plain = "".join(cleaned)
    if plain != text:
        temporary_text = plain
        cleaned, quoted, escaped = [], False, False
        for index, char in enumerate(temporary_text):
            if not quoted and char == "," and temporary_text[index + 1:].lstrip().startswith(("}", "]")):
                continue
            cleaned.append(char)
            if escaped:
                escaped = False
            elif quoted and char == "\\":
                escaped = True
            elif char == '"':
                quoted = not quoted
        plain = "".join(cleaned)
    return json.loads(plain)


def registered_roots(config_file, home, issues):
    try:
        value = read_jsonc(config_file)
        skills = value.get("skills", {})
        paths = skills.get("paths", []) if isinstance(skills, dict) else []
        if not isinstance(paths, list):
            raise ValueError("skills.paths dizi değil")
        roots = []
        for item in paths:
            if not isinstance(item, str):
                continue
            path = Path(item.replace("${HOME}", str(home))).expanduser()
            if path.is_absolute():
                options = [path]
            else:
                options = [config_file.parent / path]
                if config_file.parent.name == ".opencode":
                    options.append(config_file.parent.parent / path)
            valid = [p.absolute() for p in options if p.is_dir()]
            roots.extend(valid)
            if not valid:
                issues.append({"level": "error", "path": str(config_file), "detail": "Kayıtlı skill kökü bulunamadı: " + item})
        # Retain only skill directories; never export provider or MCP settings.
        return roots
    except (OSError, ValueError, AttributeError) as exc:
        issues.append({"level": "warning", "path": str(config_file), "detail": "Skill path ayarı okunamadı: " + type(exc).__name__})
        return []


def discover(home, roots, inventories, globals_, issues, max_dirs=250000, max_depth=32):
    candidates = set()
    expected = set()
    for inventory in inventories:
        try:
            expected.update(inventory_paths(json.loads(inventory.read_text(encoding="utf-8"))))
        except (OSError, ValueError) as exc:
            issues.append({"level": "error", "path": str(inventory), "detail": "Envanter okunamadı: " + type(exc).__name__})
    candidates.update(expected)
    for _, root in globals_:
        if root.is_dir():
            try:
                for child in root.iterdir():
                    if (child / "SKILL.md").is_file():
                        candidates.add(child.absolute())
            except OSError as exc:
                issues.append({"level": "error", "path": str(root), "detail": type(exc).__name__})
    scanned = 0
    pruned_depth = 0
    skipped_links = 0
    extra = home / ".local/share/digicut-opencode-skills"
    scan_roots = list(dict.fromkeys([*roots, *([extra] if extra.is_dir() else [])]))
    config_root = globals_[0][1].parent
    for name in ["opencode.json", "opencode.jsonc"]:
        config_file = config_root / name
        if config_file.is_file():
            scan_roots.extend(registered_roots(config_file, home, issues))
    for package_root in [config_root / "node_modules", config_root / "vendor", home / ".cache/opencode/node_modules"]:
        if not package_root.is_dir():
            continue
        try:
            packages = list(package_root.iterdir())
            for package in list(packages):
                if package.name.startswith("@") and package.is_dir():
                    packages.extend(package.iterdir())
            for package in packages:
                for suffix in ["skills", ".opencode/skills", ".agents/skills", ".claude/skills"]:
                    candidate = package / suffix
                    if candidate.is_dir():
                        scan_roots.append(candidate.absolute())
        except OSError as exc:
            issues.append({"level": "warning", "path": str(package_root), "detail": type(exc).__name__})
    visited = set()
    for scan_root in scan_roots:
        if not scan_root.is_dir():
            issues.append({"level": "error", "path": str(scan_root), "detail": "Tarama kökü bulunamadı"})
            continue
        def onerror(error):
            issues.append({"level": "warning", "path": str(error.filename), "detail": "Tarama erişim sorunu: " + type(error).__name__})
        for current, dirs, files in os.walk(scan_root, topdown=True, followlinks=False, onerror=onerror):
            here = Path(current)
            if str(here) in visited:
                dirs[:] = []
                continue
            visited.add(str(here))
            scanned += 1
            if scanned > max_dirs:
                issues.append({"level": "error", "path": str(scan_root), "detail": "Dizin sınırına ulaşıldı; --max-dirs artır"})
                return sorted(candidates), {"directories": scanned, "depth_pruned": pruned_depth, "directory_symlinks_skipped": skipped_links}
            if "SKILL.md" in files:
                candidates.add(here.absolute())
                dirs[:] = []
                continue
            for config_name in ["opencode.json", "opencode.jsonc"]:
                if config_name in files:
                    scan_roots.extend(registered_roots(here / config_name, home, issues))
            keep = []
            for name in dirs:
                child = here / name
                if name in SKIP_DIRS or (name.startswith(".") and name not in VISIBLE_HIDDEN):
                    continue
                if child.is_symlink():
                    if (child / "SKILL.md").is_file():
                        candidates.add(child.absolute())
                    else:
                        skipped_links += 1
                    continue
                if len(child.relative_to(scan_root).parts) > max_depth:
                    pruned_depth += 1
                    continue
                keep.append(name)
            dirs[:] = sorted(keep)
    if pruned_depth:
        issues.append({"level": "error", "detail": "Derinlik sınırına ulaşıldı; --max-depth artır", "count": pruned_depth})
    return sorted(candidates), {"directories": scanned, "depth_pruned": pruned_depth, "directory_symlinks_skipped": skipped_links}


def capture_tree(folder, z, blobs, file_cache, allowed_links, exclusions, original_home=None):
    root = folder.resolve(strict=True)
    files, directories, home_references = {}, [], []
    def visit(physical, relative, ancestry):
        real = physical.resolve(strict=True)
        if physical.is_symlink() and not inside(real, root) and not any(inside(real, p) for p in allowed_links):
            raise ValueError("Klasör dışına giden symlink: " + str(physical) + "; --include-linked-root ile kaynak kökünü belirt")
        mode = real.stat().st_mode
        if stat.S_ISDIR(mode):
            if real in ancestry:
                raise ValueError("Dizin bağlantısı döngüsü: " + str(physical))
            if relative:
                directories.append(relative)
            for child in sorted(physical.iterdir()):
                rel = child.name if not relative else relative + "/" + child.name
                if child.name in CAPTURE_SKIP_DIRS or credential_file(child):
                    exclusions.append({"skill_path": str(folder), "relative": rel, "reason": "cache/git/dependency/credential"})
                    continue
                safe_relative(rel)
                visit(child, rel, ancestry | {real})
        elif stat.S_ISREG(mode):
            before = real.stat()
            signature = (str(real), before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            cached = file_cache.get(signature)
            if cached is None:
                data = real.read_bytes()
                after = real.stat()
                if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise ValueError("Yedek sırasında dosya değişti: " + str(physical))
                digest = sha(data)
                cached = {"sha256": digest, "size": len(data),
                          "home_reference": bool(original_home and str(original_home).encode() in data)}
                if digest not in blobs:
                    z.writestr("blobs/" + digest, data)
                    blobs.add(digest)
                file_cache[signature] = cached
            files[relative] = {"sha256": cached["sha256"], "size": cached["size"], "mode": 0o755 if mode & 0o111 else 0o644}
            if cached.get("home_reference"):
                home_references.append(relative)
        else:
            raise ValueError("Desteklenmeyen özel dosya: " + str(physical))
    visit(root, "", set())
    if "SKILL.md" not in files:
        raise ValueError("SKILL.md bulunamadı: " + str(folder))
    return {"files": files, "directories": sorted(directories), "absolute_home_references": sorted(home_references)}


def classify(folder, globals_):
    for label, root in globals_:
        if folder.parent == root:
            return "global", label
    if any("skills-review" in part or "incoming-skills" in part for part in folder.parts):
        return "collection", None
    if folder.parent.name == "skills" and folder.parent.parent.name in VISIBLE_HIDDEN:
        return "project", None
    return "collection", None


def report_text(manifest):
    groups = defaultdict(list)
    for entry in manifest["skills"]:
        groups[entry["name"]].append(entry)
    errors = [x for x in manifest["issues"] if x["level"] == "error"]
    lines = ["# Skill yedeği", "", "Tarih: " + manifest["created_at"], "Cihaz: " + manifest["device"],
             "", f"{len(groups)} farklı ad, {len(manifest['skills'])} konum, {len(manifest['trees'])} farklı tam klasör içeriği.",
             "", "Durum: " + ("EKSİK: hataları çöz ve yeniden yedek al." if errors else "Dosya içerikleri ve özetleri doğrulanabilir biçimde paketlendi."),
             "", "Bu liste dosya keşfidir; modelde yüklenmiş olmayı göstermez.", "", "| Skill | Konum | Tam içerik sürümü | Kapsam | Uyumluluk notu |", "| --- | ---: | ---: | --- | --- |"]
    for name, entries in sorted(groups.items()):
        flags = sorted({flag for e in entries for flag in e["metadata_warnings"]})
        if any(manifest["trees"][e["tree"]].get("absolute_home_references") for e in entries):
            flags.append("İçerikte eski ev klasörünün mutlak yolu var")
        escape = lambda s: str(s).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {escape(name)} | {len(entries)} | {len({e['tree'] for e in entries})} | {', '.join(sorted({e['scope'] for e in entries}))} | {escape('; '.join(flags))} |")
    lines.extend(["", "## Konumlar", ""])
    lines.extend("- " + e["name"] + " [" + e["scope"] + "]: `" + e["original_path"].replace("`", "") + "`" for e in manifest["skills"])
    if manifest["issues"]:
        lines.extend(["", "## Kapsam uyarıları ve hatalar", ""])
        lines.extend("- " + x["level"] + ": " + x.get("path", "") + " — " + x["detail"] for x in manifest["issues"])
    lines.extend(["", "Cache, Git, bağımlılık ve kimlik bilgisi dosyalarının atlanan konumları manifest.json içinde kayıtlıdır.", ""])
    return "\n".join(lines)


def backup(args, home):
    install_tool(home, args.home is not None)
    roots = list(dict.fromkeys([home, *[p.expanduser().absolute() for p in args.root]]))
    globals_ = global_roots(home, args.home is not None)
    inventories = [p.expanduser().absolute() for p in args.inventory]
    auto = home / ".local/share/digicut-environment/inventory" / (args.device + ".json")
    if auto.is_file() and auto not in inventories:
        inventories.append(auto)
    issues, exclusions = [], []
    folders, coverage = discover(home, roots, inventories, globals_, issues, args.max_dirs, args.max_depth)
    out = (args.output or home / ("digicut-skills-" + args.device + "-" + timestamp() + ".zip")).expanduser().absolute()
    if out.exists():
        raise ValueError("Mevcut yedek korunuyor; başka --output adı seç: " + str(out))
    if any(inside(out, p) or inside(out.resolve(), p.resolve()) for p in folders):
        raise ValueError("Yedek ZIP'i skill klasörünün dışında oluştur")
    if out.parent.is_symlink():
        raise ValueError("Yedek hedefinin üst klasörü symlink")
    out.parent.mkdir(parents=True, exist_ok=True)
    allowed_links = [p.expanduser().resolve(strict=True) for p in args.include_linked_root]
    manifest = {"format": FORMAT, "schema_version": 1, "tool_version": VERSION, "device": args.device,
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "hostname": socket.gethostname(),
                "home": str(home), "scan_roots": [str(p) for p in roots], "inventories": [str(p) for p in inventories],
                "coverage": coverage, "skills": [], "trees": {}, "issues": issues, "exclusions": exclusions}
    fd, temporary = tempfile.mkstemp(prefix=".skill-backup-", suffix=".zip", dir=out.parent)
    os.close(fd)
    temp = Path(temporary)
    blobs, file_cache = set(), {}
    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
            runner = runner_source()
            z.writestr("__main__.py", runner)
            manifest["runner_sha256"] = sha(runner)
            for index, folder in enumerate(folders):
                try:
                    if not (folder / "SKILL.md").is_file():
                        raise ValueError("Envanterdeki SKILL.md artık bulunamıyor")
                    tree = capture_tree(folder, z, blobs, file_cache, allowed_links, exclusions, home)
                    tree_id = sha(canonical(tree))
                    manifest["trees"][tree_id] = tree
                    name, description, flags = metadata(folder / "SKILL.md")
                    scope, global_kind = classify(folder, globals_)
                    manifest["skills"].append({"name": name, "description": description, "scope": scope,
                                               "global_kind": global_kind, "original_path": str(folder),
                                               "tree": tree_id, "metadata_warnings": flags})
                except (OSError, ValueError, RuntimeError) as exc:
                    issues.append({"level": "error", "path": str(folder), "detail": str(exc)})
                if (index + 1) % 100 == 0:
                    print(f"Paketlendi: {index + 1}/{len(folders)} konum", flush=True)
            manifest["unique_blobs"] = len(blobs)
            manifest["complete"] = not any(x["level"] == "error" for x in issues)
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            z.writestr("SKILLS.md", report_text(manifest))
            z.writestr("KULLANIM.txt", GUIDE)
        verify_archive(temp)
        # Publish without overwriting an archive created concurrently.
        os.link(temp, out)
        out.chmod(0o600)
    finally:
        if temp.exists():
            temp.unlink()
    print(f"Yedek: {out}")
    print(f"Skill adı: {len({e['name'] for e in manifest['skills']})}; konum: {len(manifest['skills'])}; tam içerik sürümü: {len(manifest['trees'])}")
    for issue in issues:
        print(issue["level"].upper() + ": " + issue.get("path", "") + " " + issue["detail"])
    if manifest["complete"]:
        print("Yedek doğrulandı. ZIP'i formatlanmayacak bir yere kopyala.")
        return 0
    print("Yedek EKSİK. Kaydedilen dosyalar kurtarılabilir; hataları çözmeden format için hazır sayma.")
    return 2


def verify_archive(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Arşivde yinelenen üye var")
        allowed = {"__main__.py", "manifest.json", "SKILLS.md", "KULLANIM.txt"}
        if not allowed.issubset(names) or any(n not in allowed and not re.fullmatch(r"blobs/[0-9a-f]{64}", n) for n in names):
            raise ValueError("Arşiv üye listesi geçersiz")
        if z.getinfo("manifest.json").file_size > 50 * 1024 * 1024:
            raise ValueError("Manifest beklenen boyuttan büyük")
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("format") != FORMAT or manifest.get("schema_version") != 1:
            raise ValueError("Yedek biçimi desteklenmiyor")
        if sha(z.read("__main__.py")) != manifest.get("runner_sha256"):
            raise ValueError("Geri yükleme programının özeti uyuşmuyor")
        if not isinstance(manifest.get("skills"), list) or not isinstance(manifest.get("trees"), dict):
            raise ValueError("Yedek listesi geçersiz")
        original_home = Path(manifest["home"])
        if not original_home.is_absolute():
            raise ValueError("Kaynak ev yolu mutlak olmalı")
        referenced = {}
        for tree_id, tree in manifest["trees"].items():
            if not HASH_RE.fullmatch(tree_id) or sha(canonical(tree)) != tree_id:
                raise ValueError("Skill klasörü özeti uyuşmuyor")
            if not isinstance(tree.get("files"), dict) or "SKILL.md" not in tree["files"]:
                raise ValueError("Skill klasöründe SKILL.md eksik")
            for directory in tree["directories"]:
                safe_relative(directory)
            file_paths = set()
            for relative, item in tree["files"].items():
                p = safe_relative(relative)
                digest = item["sha256"]
                if not isinstance(digest, str) or not HASH_RE.fullmatch(digest) or type(item["size"]) is not int or item["size"] < 0 or item["mode"] not in {0o644, 0o755}:
                    raise ValueError("Dosya kaydı geçersiz")
                file_paths.add(p)
                if digest in referenced and referenced[digest] != item["size"]:
                    raise ValueError("Aynı dosya için farklı boyutlar var")
                referenced[digest] = item["size"]
            if any(parent in file_paths for p in file_paths for parent in p.parents if str(parent) != "."):
                raise ValueError("Dosya/dizin yolu çakışıyor")
            if any(PurePosixPath(d) in file_paths for d in tree["directories"]):
                raise ValueError("Dosya/dizin kaydı çakışıyor")
        seen = set()
        for entry in manifest["skills"]:
            original = Path(entry["original_path"])
            if not original.is_absolute() or ".." in original.parts or str(original) in seen:
                raise ValueError("Kaynak skill yolu geçersiz/tekrarlanmış")
            seen.add(str(original))
            if entry["tree"] not in manifest["trees"] or entry["scope"] not in {"global", "project", "collection"}:
                raise ValueError("Skill kaydı geçersiz")
            if entry["scope"] == "global" and entry.get("global_kind") not in {"opencode", "agents", "claude", "codex"}:
                raise ValueError("Global skill türü geçersiz")
        for digest, size in referenced.items():
            member = "blobs/" + digest
            if member not in names or z.getinfo(member).file_size != size:
                raise ValueError("Yedek dosyası eksik veya boyutu değişmiş: " + digest)
            actual = hashlib.sha256()
            with z.open(member) as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    actual.update(chunk)
            if actual.hexdigest() != digest:
                raise ValueError("Dosya özeti uyuşmuyor: " + digest)
        # Also validate orphaned blobs from a failed capture; they are recoverable bytes.
        for member in set(names) - allowed - {"blobs/" + d for d in referenced}:
            actual = hashlib.sha256()
            with z.open(member) as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    actual.update(chunk)
            if actual.hexdigest() != member.split("/")[1]:
                raise ValueError("Artık dosya özeti uyuşmuyor")
        return manifest


def mapping(args):
    pairs = []
    for item in args.map:
        if "=" not in item:
            raise ValueError("Eşleme /eski/kök=/yeni/kök biçiminde olmalı")
        old, new = item.split("=", 1)
        old_path = Path(old).expanduser()
        new_path = Path(new).expanduser()
        if not old_path.is_absolute() or not new_path.is_absolute() or ".." in old_path.parts or ".." in new_path.parts:
            raise ValueError("Eşleme yolları mutlak olmalı")
        pairs.append((old_path, new_path.resolve()))
    return sorted(pairs, key=lambda p: len(p[0].parts), reverse=True)


def destinations(manifest, args, home):
    pairs = mapping(args)
    original_home = Path(manifest["home"])
    new_globals = dict(global_roots(home, args.home is not None))
    planned, pending = [], []
    seen = set()
    for entry in manifest["skills"]:
        if args.scope != "all" and args.scope != entry["scope"]:
            continue
        original = Path(entry["original_path"])
        target = base = None
        for old, new in pairs:
            if inside(original, old):
                target, base = new / original.relative_to(old), new
                break
        if target is None and entry["scope"] == "global":
            skill_root = new_globals[entry["global_kind"]]
            target = skill_root / original.name
            base = home if inside(skill_root, home) else skill_root.parent.parent
        if target is None and inside(original, original_home):
            target, base = home / original.relative_to(original_home), home
        if target is None:
            pending.append(entry)
            continue
        if str(target) in seen:
            raise ValueError("İki skill aynı hedefe eşlendi: " + str(target))
        seen.add(str(target))
        assert_parents(target, base)
        planned.append((entry, target, base))
    return sorted(planned, key=lambda p: (len(p[1].parts), str(p[1]))), pending


def current_matches(target, tree):
    if not target.is_dir():
        return False
    expected = set(tree["files"])
    found = set()
    try:
        for current, dirs, files in os.walk(target, followlinks=False):
            dirs[:] = [d for d in dirs if d not in CAPTURE_SKIP_DIRS]
            if any((Path(current) / d).is_symlink() for d in dirs):
                return False
            for name in files:
                path = Path(current) / name
                if credential_file(path):
                    return False
                rel = path.relative_to(target).as_posix()
                if path.is_symlink() or rel not in expected:
                    return False
                item = tree["files"][rel]
                if path.stat().st_size != item["size"] or sha(path.read_bytes()) != item["sha256"]:
                    return False
                if bool(path.stat().st_mode & 0o111) != (item["mode"] == 0o755):
                    return False
                found.add(rel)
        return found == expected and all((target / d).is_dir() for d in tree["directories"])
    except OSError:
        return False


def restore(args, home, path):
    manifest = verify_archive(path)
    planned, pending = destinations(manifest, args, home)
    portability = [{"target": str(target), "files": manifest["trees"][entry["tree"]].get("absolute_home_references", [])}
                   for entry, target, _ in planned
                   if (str(home) != manifest["home"] or args.map) and manifest["trees"][entry["tree"]].get("absolute_home_references")]
    print(f"Hedef konum: {len(planned)}; eşleme bekleyen: {len(pending)}")
    if portability:
        print(f"İçerikte eski kullanıcı yolları bulunan {len(portability)} skill var; yerleşim taşınır, metin içi yolları kontrol et. Ayrıntılar işlem kaydında/SKILLS.md içinde.")
    for entry in pending:
        print("EŞLEME GEREKİYOR: " + entry["original_path"])
    if args.dry_run:
        for entry, target, _ in planned:
            print(entry["scope"] + ": " + entry["name"] + " -> " + str(target))
        print("Önizleme tamamlandı; dosya yazılmadı.")
        return 2 if pending or not manifest["complete"] else 0
    backup_root = home / ".local/share/digicut-skills/restore-backups" / timestamp()
    assert_parents(backup_root, home)
    changed = unchanged = 0
    backups = []
    with zipfile.ZipFile(path) as z:
        for index, (entry, target, base) in enumerate(planned):
            tree = manifest["trees"][entry["tree"]]
            if current_matches(target, tree):
                unchanged += 1
                continue
            assert_parents(target, base)
            target.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix=".skill-restore-", dir=target.parent))
            try:
                for relative in tree["directories"]:
                    (stage / relative).mkdir(parents=True, exist_ok=True)
                for relative, item in tree["files"].items():
                    dest = stage / relative
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open("blobs/" + item["sha256"]) as src, dest.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    dest.chmod(item["mode"])
                stage.chmod(0o755)
                previous = None
                if os.path.lexists(target):
                    previous = backup_root / f"{index:05d}-{target.name}"
                    private_dir(previous.parent)
                    shutil.move(str(target), str(previous))
                    backups.append({"target": str(target), "backup": str(previous)})
                try:
                    os.rename(stage, target)
                except OSError:
                    if previous is not None and not os.path.lexists(target):
                        shutil.move(str(previous), str(target))
                    raise
                changed += 1
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
    log_root = home / ".local/share/digicut-skills/restores"
    assert_parents(log_root / "record.json", home)
    private_dir(log_root)
    log = log_root / (timestamp() + ".json")
    log.write_text(json.dumps({"archive": str(path), "changed": changed, "unchanged": unchanged,
                               "backups": backups, "pending": pending, "portability_review": portability}, ensure_ascii=False, indent=2), encoding="utf-8")
    log.chmod(0o600)
    print(f"Geri yüklendi: {changed}; zaten aynı: {unchanged}")
    if backups:
        print("Önceki klasörler korundu: " + str(backup_root))
    print("İşlem kaydı: " + str(log))
    print("OpenCode'u yeniden aç ve skill aracıyla yüklemeyi kontrol et.")
    if not manifest["complete"]:
        print("Kaynak yedek eksik olarak işaretli; yalnızca paketlenmiş dosyalar geri geldi.")
    return 2 if pending or not manifest["complete"] else 0


def archive_argument(args):
    path = args.archive
    if path is None:
        candidate = Path(sys.argv[0]).expanduser().absolute()
        if candidate.is_file() and zipfile.is_zipfile(candidate):
            path = candidate
    if path is None:
        raise ValueError("Yedek ZIP yolunu belirt veya doğrudan 'python3 YEDEK.zip " + args.command + "' çalıştır")
    return path.expanduser().absolute()


def main(argv=None):
    if os.name != "posix":
        raise ValueError("Bu paket Linux/WSL içindir; Windows'ta Ubuntu/WSL terminalini kullan")
    parser = argparse.ArgumentParser(description="Tüm skill dosyalarını tek çevrimdışı ZIP'te koru ve yeniden kur")
    parser.add_argument("command", nargs="?", choices=["backup", "restore", "list", "verify", "install"], default="backup")
    parser.add_argument("archive", nargs="?", type=Path)
    parser.add_argument("--home", type=Path, help="Yeni ev/test kökü; normalde otomatik")
    parser.add_argument("--device", choices=["laptop", "office"], default="laptop")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--root", action="append", type=Path, default=[])
    parser.add_argument("--inventory", action="append", type=Path, default=[])
    parser.add_argument("--include-linked-root", action="append", type=Path, default=[])
    parser.add_argument("--max-dirs", type=int, default=250000)
    parser.add_argument("--max-depth", type=int, default=32)
    parser.add_argument("--map", action="append", default=[])
    parser.add_argument("--scope", choices=["all", "global", "project", "collection"], default="all")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.max_dirs < 1 or args.max_depth < 1:
        raise ValueError("Tarama sınırları pozitif olmalı")
    home = (args.home.expanduser() if args.home is not None else Path.home()).resolve()
    if args.command == "install":
        print("Skill kuruldu: " + str(install_tool(home, args.home is not None)))
        return 0
    if args.command == "backup":
        return backup(args, home)
    path = archive_argument(args)
    if args.command == "restore":
        return restore(args, home, path)
    manifest = verify_archive(path)
    if args.command == "list":
        print(report_text(manifest))
    else:
        print("Arşivdeki dosya özetleri doğrulandı; konum: " + str(len(manifest["skills"])))
    return 0 if manifest["complete"] else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, zipfile.BadZipFile) as error:
        print("İşlem tamamlanamadı: " + str(error), file=sys.stderr)
        sys.exit(1)

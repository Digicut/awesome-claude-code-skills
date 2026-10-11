import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("shared_skills", ROOT / "scripts/skills.py")
skills = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(skills)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.package = self.root / "package"
        self.package.mkdir()
        shutil.copy2(ROOT / "manifest.json", self.package / "manifest.json")
        self.paths = skills.locations(self.home)
        self.source = self.paths["cache"] / "security-audit" / ("c" * 40) / "skills/security-audit"
        self.source.mkdir(parents=True)
        (self.source / "content.fixture").write_text("upstream fixture", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def apply(self, adopt=False):
        with patch.object(skills, "source_directory", return_value=self.source):
            return skills.sync(self.package, self.home, adopt)

    def test_idempotent_global_install_and_update(self):
        self.apply()
        self.apply()
        target = self.paths["skills"] / "security-audit"
        self.assertEqual(target.resolve(), self.source)
        newer = self.root / "newer-source"
        newer.mkdir()
        with patch.object(skills, "source_directory", return_value=newer):
            skills.sync(self.package, self.home)
        self.assertEqual(target.resolve(), newer)

    def test_unknown_existing_skill_is_preserved(self):
        target = self.paths["skills"] / "security-audit"
        target.mkdir(parents=True)
        sentinel = target / "owner-content"
        sentinel.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Mevcut skill korunuyor"):
            self.apply()
        self.assertEqual(sentinel.read_text(), "keep")
        self.assertFalse(self.paths["state"].exists())

    def test_explicit_adoption_retains_backup(self):
        target = self.paths["skills"] / "security-audit"
        target.mkdir(parents=True)
        (target / "owner-content").write_text("keep", encoding="utf-8")
        self.apply(adopt=True)
        self.assertTrue(target.is_symlink())
        backups = list((self.paths["state"].parent / "backups").glob("security-audit-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "owner-content").read_text(), "keep")

    def test_failed_download_does_not_change_installed_link(self):
        self.apply()
        target = self.paths["skills"] / "security-audit"
        with patch.object(skills, "source_directory", side_effect=OSError("network unavailable")):
            with self.assertRaises(OSError):
                skills.sync(self.package, self.home)
        self.assertEqual(target.resolve(), self.source)

    def test_user_redirected_managed_link_is_preserved(self):
        self.apply()
        target = self.paths["skills"] / "security-audit"
        other = self.root / "owner-source"
        other.mkdir()
        target.unlink()
        target.symlink_to(other)
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(target.resolve(), other)

    def test_wrapper_preserves_existing_command(self):
        self.paths["bin"].mkdir(parents=True)
        existing = self.paths["bin"] / "oc"
        existing.write_text("owner command", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Mevcut komut korunuyor"):
            skills.wrappers(self.paths, ROOT / "scripts/skills.py", write=True)
        self.assertEqual(existing.read_text(), "owner command")

    def test_wrapper_paths_are_quoted_and_arguments_forwarded(self):
        script = self.root / "space and quote' directory" / "skills.py"
        script.parent.mkdir()
        script.write_text("import json,sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8")
        skills.wrappers(self.paths, script, write=True)
        result = subprocess.run([str(self.paths["bin"] / "skills-list"), "--project", "a b"], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), ["list", "--project", "a b"])

    def test_source_pin_and_path_escape_are_rejected(self):
        data = skills.manifest(self.package)
        for key, value in [("source_commit", "main"), ("source_path", "../../outside")]:
            bad = json.loads(json.dumps(data))
            bad["skills"][0][key] = value
            (self.package / "manifest.json").write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(ValueError):
                skills.manifest(self.package)

    def test_frontmatter_folded_description_and_required_fields(self):
        parsed = skills.metadata("---\nname: sample-skill\ndescription: >\n  First line\n  second line\nlicense: MIT\n---\nBody")
        self.assertEqual(parsed, {"name": "sample-skill", "description": "First line second line"})
        with self.assertRaises(ValueError):
            skills.metadata("---\nname: sample-skill\n---\n")

    def test_project_roots_stop_at_worktree(self):
        repo = self.root / "project"
        child = repo / "src/deeper"
        child.mkdir(parents=True)
        (repo / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
        roots = [path for scope, path in skills.search_roots(self.paths, child) if scope == "project"]
        self.assertIn(repo / ".opencode/skills", roots)
        self.assertNotIn(self.root / ".opencode/skills", roots)

    def test_dirty_common_repo_is_not_pulled(self):
        data = skills.manifest(self.package)
        answers = [data["shared_repository"], data["shared_branch"], " M owner-file"]
        with patch.object(skills, "git", side_effect=answers) as command:
            with self.assertRaisesRegex(ValueError, "yerel değişiklik"):
                skills.refresh(self.root, data, self.home)
            self.assertEqual(command.call_count, 3)

    def test_common_repo_fetches_real_fast_forward(self):
        upstream = self.root / "upstream"
        clone = self.root / "clone"
        subprocess.run(["git", "init", "--quiet", "--initial-branch=opencode-shared-skills", str(upstream)], check=True)
        (upstream / "version.txt").write_text("one", encoding="utf-8")
        skills.git(upstream, "add", "version.txt")
        subprocess.run(["git", "-C", str(upstream), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "initial"], check=True)
        subprocess.run(["git", "clone", "--quiet", str(upstream), str(clone)], check=True)
        (upstream / "version.txt").write_text("two", encoding="utf-8")
        skills.git(upstream, "add", "version.txt")
        subprocess.run(["git", "-C", str(upstream), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "update"], check=True)
        data = {"shared_repository": str(upstream), "shared_branch": "opencode-shared-skills"}
        skills.refresh(clone, data, self.home)
        self.assertEqual((clone / "version.txt").read_text(), "two")
        self.assertEqual(skills.git(clone, "rev-parse", "HEAD"), skills.git(upstream, "rev-parse", "HEAD"))


if __name__ == "__main__":
    unittest.main()

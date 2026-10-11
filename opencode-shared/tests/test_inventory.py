import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import device_inventory as inventory


class DeviceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.controller = self.home / ".local/share/digicut-opencode-skills"
        self.controller.mkdir(parents=True)
        self.repo = self.home / "projects/project"
        self.repo.mkdir(parents=True)
        self.run_git(self.repo, "init", "--quiet", "--initial-branch=main")
        (self.repo / "tracked.txt").write_text("original", encoding="utf-8")
        self.run_git(self.repo, "add", "tracked.txt")
        self.run_git(self.repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "initial")
        self.run_git(self.repo, "remote", "add", "origin", "https://private:super-secret@github.com/Example/Project.git?token=also-secret")
        self.patch_controller = patch.object(inventory.skills, "REPOSITORY", self.controller)
        self.patch_controller.start()
        # Ordinary fixture files exercise discovery without defining a live skill.
        self.patch_filename = patch.object(inventory, "SKILL_FILENAME", "SKILL.fixture")
        self.patch_filename.start()

    def tearDown(self):
        self.patch_filename.stop()
        self.patch_controller.stop()
        self.temp.cleanup()

    def run_git(self, path, *arguments):
        return subprocess.run(["git", "-C", str(path), *arguments], check=True, capture_output=True, text=True).stdout.strip()

    def skill_fixture(self, path, name="sample"):
        path.mkdir(parents=True)
        (path / "SKILL.fixture").write_text("---\nname: " + name + "\ndescription: Read-only test fixture\n---\nBody\n", encoding="utf-8")

    def scan(self, device="laptop", **kwargs):
        return inventory.scan(device, home=self.home, **kwargs)

    def test_scan_retains_checkout_and_redacts_credentials(self):
        data = self.scan()
        self.assertEqual(len(data["repositories"]), 1)
        row = data["repositories"][0]
        self.assertEqual(row["repository_id"], "github.com/example/project")
        self.assertEqual(row["branch"], "main")
        self.assertFalse(row["dirty"])
        output = json.dumps(data)
        self.assertNotIn("super-secret", output)
        self.assertNotIn("also-secret", output)

    def test_scan_leaves_index_config_and_dirty_files_untouched(self):
        (self.repo / "tracked.txt").write_text("local work", encoding="utf-8")
        (self.repo / ".env").write_text("PRIVATE=must-never-be-read", encoding="utf-8")
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in [self.repo / ".git/index", self.repo / ".git/config", self.repo / "tracked.txt"]}
        data = self.scan()
        self.assertTrue(data["repositories"][0]["dirty"])
        self.assertNotIn("must-never-be-read", json.dumps(data))
        self.assertNotIn(".env", json.dumps(data))
        for path, original in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), original)

    def test_global_symlink_and_project_skills_are_discovered(self):
        global_root = inventory.skills.locations(self.home)["skills"]
        global_root.mkdir(parents=True)
        source = self.root / "upstream/skills/sample"
        self.skill_fixture(source)
        (global_root / "sample").symlink_to(source, target_is_directory=True)
        self.skill_fixture(self.repo / ".opencode/skills/project-helper", "project-helper")
        self.skill_fixture(self.home / ".agents/skills/compatibility", "compatibility")
        data = self.scan()
        by_name = {row["name"]: row for row in data["skills"]}
        self.assertEqual(set(by_name), {"sample", "project-helper", "compatibility"})
        self.assertEqual(by_name["sample"]["scope"], "global")
        self.assertEqual(by_name["sample"]["real_path"], str(source / "SKILL.fixture"))
        self.assertEqual(by_name["project-helper"]["repositories"], [data["repositories"][0]["checkout_id"]])
        self.assertEqual(by_name["compatibility"]["scope"], "global")

    def test_worktrees_are_separate_checkouts_of_same_repository(self):
        worktree = self.home / "worktrees/project-feature"
        worktree.parent.mkdir()
        self.run_git(self.repo, "worktree", "add", "--quiet", "-b", "feature", str(worktree))
        rows = self.scan()["repositories"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({row["repository_id"] for row in rows}), 1)
        self.assertEqual({row["branch"] for row in rows}, {"main", "feature"})
        self.assertEqual(len({row["checkout_id"] for row in rows}), 2)

    def test_dependency_and_symlink_loops_are_skipped(self):
        ignored = self.repo / "node_modules/nested-repo"
        ignored.mkdir(parents=True)
        self.run_git(ignored, "init", "--quiet")
        (self.home / "loop").symlink_to(self.home, target_is_directory=True)
        data = self.scan()
        self.assertEqual(len(data["repositories"]), 1)
        self.assertGreater(data["coverage"]["skipped_directories"]["symlink-directories"], 0)

    def test_external_root_and_directory_cap_are_reported(self):
        external = self.root / "external-project"
        external.mkdir()
        self.run_git(external, "init", "--quiet", "--initial-branch=new")
        data = self.scan(extra_roots=[external, self.root / "missing"])
        self.assertEqual(len(data["repositories"]), 2)
        self.assertTrue(any(row["operation"] == "scan-root" for row in data["issues"]))
        limited = self.scan(max_directories=1)
        self.assertTrue(limited["coverage"]["directory_limit_reached"])
        self.assertEqual(limited["coverage"]["directories_scanned"], 1)

    def test_detached_and_unborn_checkouts_are_valid(self):
        self.run_git(self.repo, "checkout", "--quiet", "--detach")
        row = self.scan()["repositories"][0]
        self.assertIsNone(row["branch"])
        self.assertEqual(len(row["head"]), 40)
        unborn = self.home / "projects/new"
        unborn.mkdir()
        self.run_git(unborn, "init", "--quiet", "--initial-branch=main")
        rows = self.scan()["repositories"]
        row = next(row for row in rows if row["path"] == str(unborn))
        self.assertEqual(row["branch"], "main")
        self.assertIsNone(row["head"])

    def test_registry_does_not_call_pending_office_empty(self):
        combined = inventory.registry([self.scan()])
        office = next(row for row in combined["devices"] if row["id"] == "office")
        self.assertFalse(combined["comparison_ready"])
        self.assertEqual(office["status"], "awaiting_scan")
        self.assertIsNone(office["repository_checkouts"])
        self.assertIsNone(office["skill_locations"])

    def test_private_reports_merge_and_preserve_history(self):
        output = self.root / "private-inventory"
        laptop = self.scan()
        json_file, markdown = inventory.save(laptop, output)
        inventory.save(laptop, output)
        office = self.scan("office")
        inventory.main(["import", str(json_file), "--output-dir", str(output)])
        inventory.save(office, output)
        combined = json.loads((output / "registry.json").read_text())
        self.assertTrue(combined["comparison_ready"])
        self.assertEqual(len(combined["repositories"]["github.com/example/project"]), 2)
        self.assertTrue(markdown.is_file())
        self.assertEqual(len(list((output / "history/laptop").glob("*.json"))), 2)
        self.assertEqual(json_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(output.stat().st_mode & 0o777, 0o700)

    def test_report_cannot_be_written_to_public_controller(self):
        with self.assertRaisesRegex(ValueError, "Git deposunun dışında"):
            inventory.save(self.scan(), self.controller / "inventory")
        self.assertFalse((self.controller / "inventory").exists())

    def test_remote_variants_match_without_credentials(self):
        expected = "github.com/example/project"
        for raw in ["git@github.com:Example/Project.git", "ssh://git@github.com/Example/Project.git", "https://alice:token@github.com/Example/Project.git?secret=token#more"]:
            self.assertEqual(inventory.remote_identity(raw), expected)
        for raw in ["file:///home/alice/private.git", "/home/alice/private.git", "C:\\dev\\project", "ext::arbitrary-command", "https://[invalid"]:
            self.assertIsNone(inventory.remote_identity(raw))

    def test_import_rejects_invalid_or_unknown_device(self):
        for data in [{"schema_version": 1}, {**self.scan(), "device_id": "unknown"}]:
            with self.assertRaises(ValueError):
                inventory.validate_inventory(data)


if __name__ == "__main__":
    unittest.main()

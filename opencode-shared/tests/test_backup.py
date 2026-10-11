import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

SCRIPT = Path(os.environ.get('SKILL_BACKUP_SCRIPT', str(Path(__file__).resolve().parents[1] / 'skills/backup-and-restore-skills/scripts/skills_backup.py')))
spec = importlib.util.spec_from_file_location('skills_backup', SCRIPT)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def make_skill(folder, name='demo', text='v1'):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'SKILL.md').write_text(f'---\nname: {name}\ndescription: Run the {name} task.\n---\n{text}\n')
    return folder


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old = self.root / 'old-user'
        self.new = self.root / 'new-user'
        self.old.mkdir()
        self.new.mkdir()
        self.archive = self.root / 'saved.zip'

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = tool.main(list(args))
        return code, out.getvalue()

    def backup(self, *args):
        return self.run_tool('backup', '--home', str(self.old), '--output', str(self.archive), *args)

    def restore(self, *args):
        return self.run_tool('restore', str(self.archive), '--home', str(self.new), *args)

    def rewrite(self, edit):
        with zipfile.ZipFile(self.archive) as z:
            payload = {n: z.read(n) for n in z.namelist()}
        edit(payload)
        with zipfile.ZipFile(self.archive, 'w') as z:
            for n, b in payload.items():
                z.writestr(n, b)

    def test_offline_zip_runs_alone_and_restores_full_resources_and_modes(self):
        folder = make_skill(self.old / '.agents/skills/demo')
        (folder / 'assets').mkdir()
        (folder / 'assets/icon.bin').write_bytes(bytes(range(256)))
        (folder / 'build').mkdir()
        (folder / 'build/template.txt').write_text('keep generated template')
        script = folder / 'helper.sh'
        script.write_text('#!/bin/sh\nexit 0\n')
        script.chmod(0o755)
        code, output = self.backup()
        self.assertEqual(code, 0, output)
        cli = subprocess.run([sys.executable, str(self.archive), 'restore', '--home', str(self.new)], capture_output=True, text=True)
        self.assertEqual(cli.returncode, 0, cli.stderr + cli.stdout)
        restored = self.new / '.agents/skills/demo'
        self.assertEqual((restored / 'assets/icon.bin').read_bytes(), bytes(range(256)))
        self.assertTrue((restored / 'helper.sh').stat().st_mode & 0o111)
        self.assertEqual((restored / 'build/template.txt').read_text(), 'keep generated template')
        self.assertTrue((self.new / '.config/opencode/skills/backup-and-restore-skills/SKILL.md').is_file())

    def test_variants_and_project_scope_are_preserved(self):
        make_skill(self.old / '.agents/skills/demo', text='global')
        make_skill(self.old / 'projects/app/.opencode/skills/demo', text='project')
        self.assertEqual(self.backup()[0], 0)
        m = tool.verify_archive(self.archive)
        entries = [e for e in m['skills'] if e['name'] == 'demo']
        self.assertEqual(len({e['tree'] for e in entries}), 2)
        self.assertEqual({e['scope'] for e in entries}, {'global', 'project'})
        self.assertEqual(self.restore()[0], 0)
        self.assertIn('project', (self.new / 'projects/app/.opencode/skills/demo/SKILL.md').read_text())
        self.assertFalse((self.new / '.config/opencode/skills/demo').exists())

    def test_global_symlink_is_copied_and_not_dependent_on_old_machine(self):
        upstream = make_skill(self.root / 'upstream/demo')
        dest = self.old / '.agents/skills/demo'
        dest.parent.mkdir(parents=True)
        dest.symlink_to(upstream, target_is_directory=True)
        self.assertEqual(self.backup()[0], 0)
        upstream.rename(self.root / 'source-no-longer-exists')
        self.assertEqual(self.restore()[0], 0)
        result = self.new / '.agents/skills/demo'
        self.assertFalse(result.is_symlink())
        self.assertTrue((result / 'SKILL.md').is_file())

    def test_external_support_link_requires_declared_root_and_is_embedded(self):
        folder = make_skill(self.old / '.agents/skills/demo')
        shared = self.old / 'resources'
        shared.mkdir()
        (shared / 'schema.json').write_text('{"required":true}')
        (folder / 'assets').symlink_to(shared, target_is_directory=True)
        code, output = self.backup()
        self.assertEqual(code, 2, output)
        self.assertFalse(tool.verify_archive(self.archive)['complete'])
        self.archive.unlink()
        self.assertEqual(self.backup('--include-linked-root', str(shared))[0], 0)
        self.assertEqual(self.restore()[0], 0)
        self.assertFalse((self.new / '.agents/skills/demo/assets').is_symlink())
        self.assertEqual((self.new / '.agents/skills/demo/assets/schema.json').read_text(), '{"required":true}')

    def test_missing_inventory_files_are_reported_incomplete(self):
        inventory = self.old / 'inventory.json'
        inventory.write_text(json.dumps({'skills':[{'path':str(self.old / '.agents/skills/missing/SKILL.md')}]}))
        code, output = self.backup('--inventory', str(inventory))
        self.assertEqual(code, 2, output)
        self.assertFalse(tool.verify_archive(self.archive)['complete'])
        self.assertIn('missing', output)

    def test_existing_different_skill_is_preserved_and_second_restore_idempotent(self):
        make_skill(self.old / '.agents/skills/demo', text='saved')
        self.assertEqual(self.backup()[0], 0)
        make_skill(self.new / '.agents/skills/demo', text='newer-local')
        self.assertEqual(self.restore()[0], 0)
        backups = list((self.new / '.local/share/digicut-skills/restore-backups').rglob('SKILL.md'))
        self.assertEqual(len(backups), 1)
        self.assertIn('newer-local', backups[0].read_text())
        self.assertEqual(self.restore()[0], 0)
        self.assertEqual(len(list((self.new / '.local/share/digicut-skills/restore-backups').rglob('SKILL.md'))), 1)

    def test_restore_dry_run_leaves_no_files_and_scopes_filter(self):
        make_skill(self.old / 'projects/app/.opencode/skills/demo')
        self.assertEqual(self.backup()[0], 0)
        self.assertEqual(self.restore('--dry-run')[0], 0)
        self.assertEqual(list(self.new.iterdir()), [])
        self.assertEqual(self.restore('--scope', 'global')[0], 0)
        self.assertFalse((self.new / 'projects').exists())

    def test_external_project_root_requires_mapping_and_can_move(self):
        external = self.root / 'old-disk'
        make_skill(external / 'app/.opencode/skills/demo')
        self.assertEqual(self.backup('--root', str(external))[0], 0)
        code, output = self.restore('--dry-run')
        self.assertEqual(code, 2, output)
        self.assertIn('EŞLEME GEREKİYOR', output)
        new_disk = self.root / 'new-disk'
        self.assertEqual(self.restore('--map', str(external) + '=' + str(new_disk))[0], 0)
        self.assertTrue((new_disk / 'app/.opencode/skills/demo/SKILL.md').is_file())

    def test_changed_project_subroot_maps_before_home(self):
        make_skill(self.old / 'projects/app/.claude/skills/demo')
        self.assertEqual(self.backup()[0], 0)
        dest = self.new / 'work'
        self.assertEqual(self.restore('--map', str(self.old / 'projects') + '=' + str(dest))[0], 0)
        self.assertTrue((dest / 'app/.claude/skills/demo/SKILL.md').is_file())
        self.assertFalse((self.new / 'projects').exists())

    def test_credentials_and_dependencies_excluded_but_sample_kept(self):
        folder = make_skill(self.old / '.agents/skills/demo')
        (folder / '.env').write_text('TOKEN=not-to-export')
        (folder / '.env.example').write_text('TOKEN=replace-me')
        (folder / 'auth.json').write_text('{"secret":"do-not-copy"}')
        (folder / 'node_modules').mkdir()
        (folder / 'node_modules/bundle.js').write_text('installed dependency')
        self.assertEqual(self.backup()[0], 0)
        m = tool.verify_archive(self.archive)
        demo = next(e for e in m['skills'] if e['name'] == 'demo')
        paths = m['trees'][demo['tree']]['files']
        self.assertIn('.env.example', paths)
        self.assertNotIn('.env', paths)
        self.assertNotIn('auth.json', paths)
        self.assertFalse(any(p.startswith('node_modules/') for p in paths))

    def test_blob_corruption_stops_restore_before_any_mutation(self):
        make_skill(self.old / '.agents/skills/demo')
        self.assertEqual(self.backup()[0], 0)
        def corrupt(payload):
            name = next(n for n in payload if n.startswith('blobs/'))
            payload[name] = b'changed'
        self.rewrite(corrupt)
        with self.assertRaises(ValueError):
            self.restore()
        self.assertEqual(list(self.new.iterdir()), [])

    def test_zip_traversal_is_rejected(self):
        self.assertEqual(self.backup()[0], 0)
        self.rewrite(lambda payload: payload.update({'../../bad':b'bad'}))
        with self.assertRaises(ValueError):
            self.restore()
        self.assertEqual(list(self.new.iterdir()), [])

    def test_hostile_manifest_file_path_is_rejected(self):
        self.assertEqual(self.backup()[0], 0)
        def edit(payload):
            m = json.loads(payload['manifest.json'])
            old_id, tree = next(iter(m['trees'].items()))
            tree['files']['../../bad'] = tree['files']['SKILL.md']
            new_id = tool.sha(tool.canonical(tree))
            del m['trees'][old_id]
            m['trees'][new_id] = tree
            for e in m['skills']:
                if e['tree'] == old_id: e['tree'] = new_id
            payload['manifest.json'] = json.dumps(m).encode()
        self.rewrite(edit)
        with self.assertRaises(ValueError):
            self.restore()
        self.assertEqual(list(self.new.iterdir()), [])

    def test_target_ancestor_symlink_cannot_escape_new_home(self):
        make_skill(self.old / 'projects/app/.opencode/skills/demo')
        self.assertEqual(self.backup()[0], 0)
        outside = self.root / 'unrelated'
        outside.mkdir()
        (self.new / 'projects').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.restore()
        self.assertEqual(list(outside.iterdir()), [])

    def test_existing_archive_never_overwritten(self):
        self.assertEqual(self.backup()[0], 0)
        original = self.archive.read_bytes()
        with self.assertRaises(ValueError):
            self.backup()
        self.assertEqual(self.archive.read_bytes(), original)

    def test_full_content_dedup_keeps_metadata_same_but_different_assets(self):
        a = make_skill(self.old / 'projects/a/.opencode/skills/demo')
        b = make_skill(self.old / 'projects/b/.opencode/skills/demo')
        (a / 'asset.txt').write_text('A')
        (b / 'asset.txt').write_text('B')
        self.assertEqual(self.backup()[0], 0)
        m = tool.verify_archive(self.archive)
        entries = [e for e in m['skills'] if e['name'] == 'demo']
        self.assertEqual(len({e['tree'] for e in entries}), 2)
        hashes = [m['trees'][e['tree']]['files']['SKILL.md']['sha256'] for e in entries]
        self.assertEqual(len(set(hashes)), 1)

    def test_registered_jsonc_skill_paths_and_cached_plugin_skills_are_discovered(self):
        config = self.old / '.config/opencode'
        config.mkdir(parents=True)
        registered = make_skill(self.old / '.custom/skills/registered', name='registered')
        (config / 'opencode.jsonc').write_text('{\n// settings\n"skills":{"paths":["' + str(registered.parent) + '",]}, /* kept URL */\n"provider":{"url":"https://example.invalid/v1"},\n}')
        make_skill(config / 'node_modules/superpowers/skills/brainstorming', name='brainstorming')
        self.assertEqual(self.backup()[0], 0)
        m = tool.verify_archive(self.archive)
        names = {e['name'] for e in m['skills']}
        self.assertIn('registered', names)
        self.assertIn('brainstorming', names)
        self.assertFalse(any(e['original_path'].endswith('opencode.jsonc') for e in m['skills']))

    def test_absolute_home_references_flagged_without_changing_original_content(self):
        folder = make_skill(self.old / '.agents/skills/demo')
        original = str(self.old / 'projects/app/helper.py')
        (folder / 'references.txt').write_text(original)
        self.assertEqual(self.backup()[0], 0)
        m = tool.verify_archive(self.archive)
        demo = next(e for e in m['skills'] if e['name'] == 'demo')
        self.assertIn('references.txt', m['trees'][demo['tree']]['absolute_home_references'])
        code, output = self.restore()
        self.assertEqual(code, 0, output)
        self.assertIn('metin içi yolları kontrol et', output)
        self.assertEqual((self.new / '.agents/skills/demo/references.txt').read_text(), original)

    def test_backup_keeps_matching_shared_managed_tool_symlink(self):
        source = self.root / 'controller/backup-and-restore-skills'
        source.joinpath('scripts').mkdir(parents=True)
        source.joinpath('references').mkdir()
        source.joinpath('SKILL.md').write_text(tool.SKILL_TEXT)
        source.joinpath('references/restore.md').write_text(tool.REFERENCE_TEXT)
        source.joinpath('scripts/skills_backup.py').write_bytes(tool.runner_source())
        target = self.old / '.config/opencode/skills/backup-and-restore-skills'
        target.parent.mkdir(parents=True)
        target.symlink_to(source, target_is_directory=True)
        self.assertEqual(self.backup()[0], 0)
        self.assertTrue(target.is_symlink())
        self.assertEqual(target.resolve(), source)


if __name__ == '__main__':
    unittest.main()

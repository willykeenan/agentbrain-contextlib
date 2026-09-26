"""CLI commands call the core API. doctor and mcp are not exercised here."""
from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _unload():
    for key in list(sys.modules):
        if key == 'agentbrain_contextlib' or key.startswith('agentbrain_contextlib.'):
            del sys.modules[key]


def _bind():
    global main
    from agentbrain_contextlib.cli import main


def _git_available():
    try:
        subprocess.run(['git', '--version'], check=True, capture_output=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _git(cwd, *args):
    env = os.environ.copy()
    env['GIT_AUTHOR_NAME'] = 'ContextLib'
    env['GIT_AUTHOR_EMAIL'] = 'ctxlib@localhost'
    env['GIT_COMMITTER_NAME'] = 'ContextLib'
    env['GIT_COMMITTER_EMAIL'] = 'ctxlib@localhost'
    env['GIT_TERMINAL_PROMPT'] = '0'
    subprocess.run(
        ['git', '-c', 'commit.gpgsign=false', *args],
        cwd=str(cwd),
        check=True,
        env=env,
        capture_output=True,
    )


class CliTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(_unload)
        _bind()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'lib'
        self._old_root = os.environ.get('CONTEXTLIB_ROOT')
        os.environ.pop('CONTEXTLIB_ROOT', None)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self._old_root is None:
            os.environ.pop('CONTEXTLIB_ROOT', None)
        else:
            os.environ['CONTEXTLIB_ROOT'] = self._old_root

    def invoke(self, *argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(list(argv))
        return code, stdout.getvalue(), stderr.getvalue()

    def lib(self, *argv):
        return self.invoke('--library', str(self.root), *argv)

    def _id_from(self, out):
        for line in out.splitlines():
            if line.startswith('id: '):
                return line[4:].strip()
        self.fail('no id in output:\n%s' % out)

    def _init(self):
        code, out, err = self.invoke(
            'init', str(self.root),
            '--project', 'harbor',
            '--name', 'Harbor',
            '--purpose', 'Headland board.',
        )
        self.assertEqual(code, 0, err)
        self.assertIn('initialized', out)
        self.assertIn('harbor', out)
        return code, out, err


class TestLazyDoctorMcp(CliTest):
    def test_cli_import_does_not_load_doctor_or_mcp(self):
        import agentbrain_contextlib.cli as cli_mod
        loaded = [name for name in sys.modules if name.endswith('.doctor') or name.endswith('.mcp')]
        self.assertEqual(loaded, [])
        src = Path(cli_mod.__file__).read_text(encoding='utf-8')
        tree = ast.parse(src)
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ''
                self.assertFalse(mod.endswith('.doctor') or mod.endswith('.mcp'), mod)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn('doctor', alias.name)
                    self.assertNotIn('mcp', alias.name)

    def test_help_does_not_import_doctor_or_mcp(self):
        code, out, err = self.invoke('--help')
        self.assertEqual(code, 0, err)
        self.assertIn('init', out)
        self.assertIn('mcp', out)
        self.assertIn('doctor', out)
        code, out, err = self.invoke('doctor', '--help')
        self.assertEqual(code, 0, err)
        self.assertIn('ten-minute', out)
        code, out, err = self.invoke('mcp', '--help')
        self.assertEqual(code, 0, err)
        self.assertIn('identity', out)
        self.assertNotIn('agentbrain_contextlib.doctor', sys.modules)
        self.assertNotIn('agentbrain_contextlib.mcp', sys.modules)


class TestErrors(CliTest):
    def test_errors_are_one_line_on_stderr_exit_1(self):
        code, out, err = self.invoke('add')
        self.assertEqual(code, 1)
        self.assertNotIn('Traceback', err)
        self.assertNotIn('Traceback', out)
        self.assertTrue(err.strip())
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_unknown_project_is_plain_error(self):
        self._init()
        code, out, err = self.lib('brief', 'missing')
        self.assertEqual(code, 1)
        self.assertNotIn('Traceback', err)
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertIn('no project', err)

    def test_missing_command(self):
        code, out, err = self.invoke()
        self.assertEqual(code, 1)
        self.assertNotIn('Traceback', err)
        self.assertEqual(len(err.strip().splitlines()), 1)


class TestLibraryPath(CliTest):
    def test_library_flag_beats_env(self):
        self._init()
        other = Path(self.tmp.name) / 'other'
        os.environ['CONTEXTLIB_ROOT'] = str(other)
        code, out, err = self.lib('project', 'list')
        self.assertEqual(code, 0, err)
        self.assertIn('harbor', out)

    def test_env_root(self):
        self._init()
        os.environ['CONTEXTLIB_ROOT'] = str(self.root)
        code, out, err = self.invoke('project', 'list')
        self.assertEqual(code, 0, err)
        self.assertIn('harbor', out)

    def test_default_is_home_contextlib(self):
        home = Path(self.tmp.name) / 'home'
        home.mkdir()
        target = home / 'ContextLib'
        code, out, err = self.invoke('init', str(target), '--project', 'demo', '--name', 'Demo')
        self.assertEqual(code, 0, err)
        with mock.patch('agentbrain_contextlib.cli.Path.home', return_value=home):
            code, out, err = self.invoke('project', 'list')
        self.assertEqual(code, 0, err)
        self.assertIn('demo', out)


class TestCommands(CliTest):
    def test_project_add_and_list(self):
        code, out, err = self.invoke('init', str(self.root))
        self.assertEqual(code, 0, err)
        code, out, err = self.lib('project', 'add', 'harbor', 'Harbor', '--purpose', 'Headland board.')
        self.assertEqual(code, 0, err)
        self.assertIn('harbor', out)
        code, out, err = self.lib('project', 'list')
        self.assertEqual(code, 0, err)
        self.assertIn('harbor', out)
        self.assertIn('Harbor', out)

    def test_add_get_brief_inbox_accept_reject(self):
        self._init()
        code, out, err = self.lib(
            'add', 'harbor', 'decision', 'Use keeper logs',
            '--body', '**Decision:** logs, not AIS.',
            '--author', 'guest',
            '--evidence', 'note:keeper log',
            '--tag', 'lamp',
        )
        self.assertEqual(code, 0, err)
        proposed = self._id_from(out)
        self.assertIn('proposed', out)
        code, out, err = self.lib('inbox', 'harbor')
        self.assertEqual(code, 0, err)
        self.assertIn(proposed, out)
        code, out, err = self.lib('accept', 'harbor', proposed, '--author', 'mara')
        self.assertEqual(code, 0, err)
        self.assertIn('current', out)
        code, out, err = self.lib('get', 'harbor', proposed)
        self.assertEqual(code, 0, err)
        self.assertIn('Use keeper logs', out)
        self.assertIn('logs, not AIS', out)
        self.assertIn('path:', out)
        self.assertIn('supersession_chain:', out)
        code, out, err = self.lib('brief', 'harbor')
        self.assertEqual(code, 0, err)
        self.assertTrue(out.strip())
        self.assertLessEqual(len(out.encode('utf-8')), 8192)

        code, out, err = self.lib(
            'add', 'harbor', 'lesson', 'Skip this',
            '--body', '**Lesson:** not ready.',
            '--author', 'guest',
            '--evidence', 'note:draft',
        )
        self.assertEqual(code, 0, err)
        skipped = self._id_from(out)
        code, out, err = self.lib('reject', 'harbor', skipped, '--reason', 'folded into the brief', '--author', 'mara')
        self.assertEqual(code, 0, err)
        self.assertIn('retired', out)
        code, out, err = self.lib('inbox', 'harbor')
        self.assertEqual(code, 0, err)
        self.assertNotIn(skipped, out)

    def test_add_body_file_and_approved_by(self):
        self._init()
        body = Path(self.tmp.name) / 'body.md'
        body.write_text('**Fact:** lamp character is Fl W 15s.\n', encoding='utf-8')
        code, out, err = self.lib(
            'add', 'harbor', 'fact', 'Lamp character is Fl W 15s',
            '--body-file', str(body),
            '--author', 'guest',
            '--evidence', 'note:signed log',
            '--review-by', '2026-10-26',
            '--approved-by', 'mara — files first',
        )
        self.assertEqual(code, 0, err)
        ident = self._id_from(out)
        self.assertIn('current', out)
        code, out, err = self.lib('get', 'harbor', ident)
        self.assertEqual(code, 0, err)
        self.assertIn('Fl W 15s', out)
        self.assertIn('2026-10-26', out)

    def test_search_rebuild_due_regen(self):
        self._init()
        code, out, err = self.lib(
            'add', 'harbor', 'fact', 'Lamp character is Fl W 15s',
            '--body', '**Fact:** white flash every 15 seconds.',
            '--author', 'guest',
            '--evidence', 'note:log',
        )
        self.assertEqual(code, 0, err)
        fact_id = self._id_from(out)
        code, out, err = self.lib(
            'add', 'harbor', 'decision', 'Old poll',
            '--body', '**Decision:** later due.',
            '--author', 'guest',
            '--evidence', 'note:trial',
            '--approved-by', 'mara',
            '--review-by', '2020-01-01',
        )
        self.assertEqual(code, 0, err)
        due_id = self._id_from(out)
        code, out, err = self.lib('rebuild')
        self.assertEqual(code, 0, err)
        self.assertIn('rebuilt', out)
        code, out, err = self.lib('search', 'harbor', 'lamp')
        self.assertEqual(code, 0, err)
        self.assertIn(fact_id, out)
        code, out, err = self.lib('search', 'harbor', 'lamp', '--type', 'fact')
        self.assertEqual(code, 0, err)
        self.assertIn(fact_id, out)
        code, out, err = self.lib('search', 'harbor', 'lamp', '--all')
        self.assertEqual(code, 0, err)
        self.assertIn(fact_id, out)
        code, out, err = self.lib('due', 'harbor')
        self.assertEqual(code, 0, err)
        self.assertIn(due_id, out)
        code, out, err = self.lib('regen', 'harbor')
        self.assertEqual(code, 0, err)
        self.assertIn('regenerated', out)
        self.assertTrue((self.root / 'projects' / 'harbor' / 'BRIEF.md').is_file())
        code, out, err = self.lib('regen', '--all')
        self.assertEqual(code, 0, err)
        self.assertIn('regenerated', out)

    def test_supersede_and_review(self):
        self._init()
        code, out, err = self.lib(
            'add', 'harbor', 'decision', 'Poll AIS',
            '--body', '**Decision:** treat AIS as the lamp.',
            '--author', 'guest',
            '--evidence', 'note:early',
            '--approved-by', 'mara',
        )
        self.assertEqual(code, 0, err)
        old_id = self._id_from(out)
        code, out, err = self.lib(
            'add', 'harbor', 'decision', 'Use keeper logs',
            '--body', '**Decision:** the lamp is what the keeper signed.',
            '--author', 'guest',
            '--evidence', 'note:keeper log',
            '--approved-by', 'mara',
        )
        self.assertEqual(code, 0, err)
        new_id = self._id_from(out)
        code, out, err = self.lib(
            'supersede', 'harbor', old_id, new_id,
            '--reason', 'AIS is traffic, not lamp status',
            '--author', 'mara',
        )
        self.assertEqual(code, 0, err)
        self.assertIn('superseded', out)
        self.assertIn(new_id, out)
        code, out, err = self.lib(
            'review', 'harbor', new_id, 'confirm',
            '--note', 'still right',
            '--author', 'mara',
        )
        self.assertEqual(code, 0, err)
        self.assertIn('confirm', out)
        extra = self.lib(
            'add', 'harbor', 'lesson', 'Retire me',
            '--body', '**Lesson:** done.',
            '--author', 'guest',
            '--evidence', 'note:x',
            '--approved-by', 'mara',
        )
        self.assertEqual(extra[0], 0, extra[2])
        retire_id = self._id_from(extra[1])
        code, out, err = self.lib(
            'review', 'harbor', retire_id, 'retire',
            '--note', 'folded',
            '--author', 'mara',
        )
        self.assertEqual(code, 0, err)
        self.assertIn('retired', out)

    def test_capture_import_md_export_import(self):
        self._init()
        result_path = Path(self.tmp.name) / 'RESULT.json'
        result_path.write_text(json.dumps({
            'title': 'Keeper trial',
            'userOutcome': 'Lamp status stayed current',
            'lessons': ['Offline forms get filled when the hut link drops'],
        }), encoding='utf-8')
        code, out, err = self.lib('capture', 'harbor', str(result_path))
        self.assertEqual(code, 0, err)
        self.assertIn('return_id:', out)
        self.assertIn('proposed_ids:', out)

        md = Path(self.tmp.name) / 'character.md'
        md.write_text('# Character\n\nA lamp pattern such as Fl W 15s.\n', encoding='utf-8')
        code, out, err = self.lib(
            'import-md', 'harbor', str(md),
            '--type', 'glossary',
            '--author', 'mara',
        )
        self.assertEqual(code, 0, err)
        ident = self._id_from(out)
        code, out, err = self.lib('get', 'harbor', ident)
        self.assertEqual(code, 0, err)
        self.assertIn('Character', out)
        self.assertIn('Fl W 15s', out)

        out_dir = Path(self.tmp.name) / 'exports'
        code, out, err = self.lib('export', 'harbor', str(out_dir))
        self.assertEqual(code, 0, err)
        self.assertIn('sha256:', out)
        zip_path = None
        for line in out.splitlines():
            if line.startswith('path: '):
                zip_path = line[6:].strip()
        self.assertTrue(zip_path and Path(zip_path).is_file())

        other = Path(self.tmp.name) / 'lib2'
        code, out, err = self.invoke('init', str(other))
        self.assertEqual(code, 0, err)
        code, out, err = self.invoke('--library', str(other), 'import', zip_path)
        self.assertEqual(code, 0, err)
        self.assertIn('harbor', out)
        self.assertIn('conflicts: none', out)
        code, out, err = self.invoke('--library', str(other), 'get', 'harbor', ident)
        self.assertEqual(code, 0, err)
        self.assertIn('Character', out)

    def test_tilde_paths_expand(self):
        self._init()
        home = Path(self.tmp.name) / 'home'
        home.mkdir()
        md = home / 'character.md'
        md.write_text('# Character\n\nA lamp pattern such as Fl W 15s.\n', encoding='utf-8')
        result_path = home / 'RESULT.json'
        result_path.write_text(json.dumps({
            'title': 'Keeper trial',
            'userOutcome': 'Lamp status stayed current',
        }), encoding='utf-8')
        old_home = os.environ.get('HOME')
        os.environ['HOME'] = str(home)

        def _restore_home():
            if old_home is None:
                os.environ.pop('HOME', None)
            else:
                os.environ['HOME'] = old_home

        self.addCleanup(_restore_home)
        code, out, err = self.lib(
            'import-md', 'harbor', '~/character.md',
            '--type', 'glossary',
            '--author', 'mara',
        )
        self.assertEqual(code, 0, err)
        self.assertTrue(self._id_from(out))
        code, out, err = self.lib('capture', 'harbor', '~/RESULT.json')
        self.assertEqual(code, 0, err)
        self.assertIn('return_id:', out)

    def test_init_project_requires_name_before_write(self):
        code, out, err = self.invoke('init', str(self.root), '--project', 'harbor')
        self.assertEqual(code, 1)
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertIn('--name', err)
        self.assertFalse(out.strip())
        self.assertFalse(self.root.exists())

    def test_sync_noop_without_git(self):
        self._init()
        code, out, err = self.lib('sync')
        self.assertEqual(code, 0, err)
        self.assertIn('no-op', out.lower())

    def test_sync_pull_push_when_git_repo(self):
        if not _git_available():
            self.skipTest('git binary not available')
        self._init()
        _git(self.root, 'init')
        _git(self.root, 'add', '.')
        _git(self.root, 'commit', '-m', 'library')
        remote = Path(self.tmp.name) / 'remote.git'
        _git(self.tmp.name, 'init', '--bare', str(remote))
        _git(self.root, 'remote', 'add', 'origin', str(remote))
        branch = subprocess.run(
            ['git', '-C', str(self.root), 'rev-parse', '--abbrev-ref', 'HEAD'],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        _git(self.root, 'push', '-u', 'origin', branch)
        code, out, err = self.lib('sync')
        self.assertEqual(code, 0, err + out)
        self.assertIn('synced', out)

    def test_sync_git_failure_is_one_line(self):
        if not _git_available():
            self.skipTest('git binary not available')
        self._init()
        _git(self.root, 'init')
        _git(self.root, 'add', '.')
        _git(self.root, 'commit', '-m', 'library')
        code, out, err = self.lib('sync')
        self.assertEqual(code, 1)
        self.assertNotIn('Traceback', err)
        self.assertNotIn('Traceback', out)
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertIn('git', err.lower())

    def test_sync_ignores_git_dir_env(self):
        if not _git_available():
            self.skipTest('git binary not available')
        self._init()
        _git(self.root, 'init')
        _git(self.root, 'add', '.')
        _git(self.root, 'commit', '-m', 'library')
        remote = Path(self.tmp.name) / 'remote.git'
        _git(self.tmp.name, 'init', '--bare', str(remote))
        _git(self.root, 'remote', 'add', 'origin', str(remote))
        branch = subprocess.run(
            ['git', '-C', str(self.root), 'rev-parse', '--abbrev-ref', 'HEAD'],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        _git(self.root, 'push', '-u', 'origin', branch)
        other = Path(self.tmp.name) / 'other.git'
        _git(self.tmp.name, 'init', '--bare', str(other))
        old = os.environ.get('GIT_DIR')
        os.environ['GIT_DIR'] = str(other)

        def _restore_git_dir():
            if old is None:
                os.environ.pop('GIT_DIR', None)
            else:
                os.environ['GIT_DIR'] = old

        self.addCleanup(_restore_git_dir)
        code, out, err = self.lib('sync')
        self.assertEqual(code, 0, err + out)
        self.assertIn('synced', out)


class TestMainModule(CliTest):
    def test_main_module_exists(self):
        import agentbrain_contextlib.__main__ as mod
        self.assertTrue(hasattr(mod, 'main') or mod.__file__.endswith('__main__.py'))


if __name__ == '__main__':
    unittest.main()

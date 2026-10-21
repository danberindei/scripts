import contextlib
import importlib.machinery
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

script = Path(__file__).with_name('cgroups-top')
loader = importlib.machinery.SourceFileLoader('cgroups_top', str(script))
spec = importlib.util.spec_from_loader(loader.name, loader)
cgroups_top = importlib.util.module_from_spec(spec)
loader.exec_module(cgroups_top)


class CgroupsTopTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        iterate = cgroups_top.iter_cgroup_dirs
        replacement = patch.object(cgroups_top, 'iter_cgroup_dirs', lambda: iterate(self.root))
        replacement.start()
        self.addCleanup(replacement.stop)
        self.iterate = iterate

    def make_cgroup(self, name, memory=8192, pids=None):
        directory = self.root / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'memory.current').write_text(str(memory))
        (directory / 'memory.swap.current').write_text('4096\n')
        (directory / 'memory.stat').write_text('shmem 1024\ninactive_file 2048\n')
        (directory / 'cgroup.procs').write_text(f'{os.getpid()}\n' if pids is None else pids)
        return directory

    def test_directory_traversal_excludes_control_files_and_root(self):
        parent = self.make_cgroup('session.slice')
        child = self.make_cgroup('session.slice/application.scope')
        empty = self.root / 'empty.slice'
        empty.mkdir()
        self.assertEqual(set(self.iterate(self.root)), {parent, child, empty})

    def test_collection_preserves_totals_sorting_and_skips_empty_or_invalid_cgroups(self):
        self.make_cgroup('.')
        smaller = self.make_cgroup('session.slice/smaller.scope')
        larger = self.make_cgroup('session.slice/larger.scope', memory=16384)
        self.make_cgroup('empty.scope', pids='')
        self.make_cgroup('invalid.scope', memory='invalid')

        rows = cgroups_top.collect_cgroup_data()

        self.assertEqual([row['cgroup_path'] for row in rows], [str(larger), str(smaller)])
        self.assertEqual([row['memory_bytes'] for row in rows], [14336, 6144])
        self.assertEqual([row['swap_bytes'] for row in rows], [4096, 4096])
        self.assertEqual([row['shmem_bytes'] for row in rows], [1024, 1024])
        self.assertEqual(rows[0]['pids'], [os.getpid()])
        self.assertEqual(rows[0]['processes'][0]['pid'], os.getpid())
        self.assertTrue(rows[0]['executables'])

    def test_process_view_finds_nested_cgroup(self):
        directory = self.make_cgroup('session.slice/application.scope')
        output = io.StringIO()

        found = cgroups_top.show_cgroup_processes('application.scope', file=output)

        self.assertTrue(found)
        self.assertIn(f'Cgroup: {directory}', output.getvalue())
        self.assertIn(str(os.getpid()), output.getvalue())

    def test_process_view_reports_missing_cgroup(self):
        self.make_cgroup('session.slice/application.scope')
        error = io.StringIO()

        with contextlib.redirect_stderr(error):
            found = cgroups_top.show_cgroup_processes('missing.scope', file=io.StringIO())

        self.assertFalse(found)
        self.assertIn("Cgroup 'missing.scope' not found", error.getvalue())


if __name__ == '__main__':
    unittest.main()

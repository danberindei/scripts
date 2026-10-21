import contextlib
import importlib.machinery
import importlib.util
import io
import json
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
        entries = dict(self.iterate(self.root))
        self.assertEqual(set(entries), {parent, child, empty})
        self.assertIn('memory.current', entries[child])

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

    def test_processes_are_sorted_by_total_bytes(self):
        self.make_cgroup('application.scope', pids=f'{os.getpid()}\n1\n')
        memory = {
            os.getpid(): {'rss_bytes': 100, 'file_bytes': 0, 'anon_bytes': 0, 'swap_bytes': 0, 'shmem_bytes': 0},
            1: {'rss_bytes': 900, 'file_bytes': 0, 'anon_bytes': 0, 'swap_bytes': 0, 'shmem_bytes': 0},
        }

        with patch.object(cgroups_top, 'get_proc_memory', side_effect=lambda pid: memory[pid]):
            rows = cgroups_top.collect_cgroup_data()

        self.assertEqual([p['pid'] for p in rows[0]['processes']], [1, os.getpid()])
        self.assertEqual([p['total_bytes'] for p in rows[0]['processes']], [900, 100])

    def test_process_view_finds_nested_cgroup(self):
        directory = self.make_cgroup('session.slice/application.scope')
        output = io.StringIO()

        found = cgroups_top.show_cgroup_processes('application.scope', file=output)

        self.assertTrue(found)
        self.assertIn(f'Cgroup: {directory}', output.getvalue())
        self.assertIn(str(os.getpid()), output.getvalue())

    def test_empty_cgroup_does_not_read_memory_counters(self):
        directory = self.make_cgroup('empty.scope', pids='')

        with patch.object(Path, 'read_text', autospec=True, side_effect=Path.read_text) as read:
            rows = cgroups_top.collect_cgroup_data()

        self.assertEqual(rows, [])
        read_paths = [call.args[0] for call in read.call_args_list]
        self.assertNotIn(directory / 'memory.stat', read_paths)
        self.assertNotIn(directory / 'memory.swap.current', read_paths)

    def test_collection_reads_files_without_existence_checks(self):
        self.make_cgroup('application.scope')

        with patch.object(Path, 'exists', side_effect=AssertionError('Unexpected existence check')):
            rows = cgroups_top.collect_cgroup_data()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['memory_bytes'], 6144)

    def test_missing_swap_counter_defaults_to_zero(self):
        directory = self.make_cgroup('no-swap.scope')
        (directory / 'memory.swap.current').unlink()

        rows = cgroups_top.collect_cgroup_data()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['memory_bytes'], 6144)
        self.assertEqual(rows[0]['shmem_bytes'], 1024)
        self.assertEqual(rows[0]['swap_bytes'], 0)

    def test_missing_memory_stat_skips_cgroup(self):
        directory = self.make_cgroup('no-stat.scope')
        (directory / 'memory.stat').unlink()

        self.assertEqual(cgroups_top.collect_cgroup_data(), [])

    def test_cgroup_without_memory_controller_is_skipped_without_reads(self):
        directory = self.make_cgroup('threaded.scope')
        (directory / 'memory.current').unlink()
        (directory / 'memory.stat').unlink()

        with patch.object(Path, 'read_text', autospec=True, side_effect=Path.read_text) as read:
            rows = cgroups_top.collect_cgroup_data()

        self.assertEqual(rows, [])
        self.assertEqual(read.call_args_list, [])

    def test_missing_required_files_skip_cgroup(self):
        no_memory = self.make_cgroup('no-memory.scope')
        (no_memory / 'memory.current').unlink()
        no_procs = self.make_cgroup('no-procs.scope')
        (no_procs / 'cgroup.procs').unlink()

        self.assertEqual(cgroups_top.collect_cgroup_data(), [])

    def test_table_and_json_reuse_collected_process_data(self):
        self.make_cgroup('application.scope')
        table = io.StringIO()
        default_json = io.StringIO()
        detailed_json = io.StringIO()
        proportional = {'pss_bytes': 1024, 'pss_shmem_bytes': 0, 'swap_pss_bytes': 0}

        with (
            patch.object(cgroups_top, 'get_proc_comm', wraps=cgroups_top.get_proc_comm) as comm,
            patch.object(cgroups_top, 'get_proc_memory', wraps=cgroups_top.get_proc_memory) as memory,
            patch.object(cgroups_top, 'get_proc_proportional', return_value=proportional),
        ):
            rows = cgroups_top.collect_cgroup_data()
            cgroups_top.print_jsonl(rows, file=default_json)
            cgroups_top.print_jsonl(rows, include_processes=True, file=detailed_json)
            cgroups_top.print_cgroups_table(rows, file=table)

        comm.assert_called_once_with(os.getpid())
        memory.assert_called_once_with(os.getpid())
        process = rows[0]['processes'][0]
        self.assertIn(f"1.0KiB {process['comm']}", table.getvalue())
        default_process = json.loads(default_json.getvalue())['processes'][0]
        self.assertEqual(set(default_process), {
            'pid', 'cmdline', 'rss_bytes', 'file_bytes', 'anon_bytes',
            'swap_bytes', 'shmem_bytes', 'total_bytes',
        })
        detailed_process = json.loads(detailed_json.getvalue())['processes'][0]
        self.assertEqual(detailed_process, {key: process[key] for key in (
            'pid', 'comm', 'rss_bytes', 'file_bytes', 'anon_bytes', 'swap_bytes', 'shmem_bytes',
        )})
        self.assertNotIn('proportional', rows[0]['processes'][0])

    def test_empty_cmdline_reuses_collected_command_name(self):
        self.make_cgroup('application.scope')
        read_text = Path.read_text

        def read(path, *args, **kwargs):
            if path == Path(f'/proc/{os.getpid()}/cmdline'):
                return ''
            return read_text(path, *args, **kwargs)

        with patch.object(Path, 'read_text', autospec=True, side_effect=read):
            rows = cgroups_top.collect_cgroup_data()
            output = io.StringIO()
            found = cgroups_top.show_cgroup_processes('application.scope', file=output)

        process = rows[0]['processes'][0]
        self.assertTrue(process['comm'])
        self.assertEqual(process['cmdline'], process['comm'])
        self.assertTrue(found)
        self.assertIn(process['comm'], output.getvalue())

    def test_process_view_reports_missing_cgroup(self):
        self.make_cgroup('session.slice/application.scope')
        error = io.StringIO()

        with contextlib.redirect_stderr(error):
            found = cgroups_top.show_cgroup_processes('missing.scope', file=io.StringIO())

        self.assertFalse(found)
        self.assertIn("Cgroup 'missing.scope' not found", error.getvalue())


if __name__ == '__main__':
    unittest.main()

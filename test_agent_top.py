"""Tests for the local agent memory display."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).with_name("agent-top")
LOADER = SourceFileLoader("agent_top", str(SCRIPT_PATH))
SPEC = importlib.util.spec_from_loader("agent_top", LOADER)
agent_top = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = agent_top
LOADER.exec_module(agent_top)


def process(
    pid,
    ppid=0,
    name="worker",
    executable="worker",
    argv=(),
    cwd="/work",
    agent_id=None,
    agent_cwd=None,
    cgroup_path=None,
    rss_kib=10,
    rss_shmem_kib=0,
    swap_kib=0,
):
    return agent_top.ProcessInfo(
        pid=pid,
        ppid=ppid,
        name=name,
        executable=executable,
        argv=tuple(argv),
        cwd=cwd,
        paseo_agent_id=agent_id,
        paseo_agent_cwd=agent_cwd,
        cgroup_path=cgroup_path,
        rss_kib=rss_kib,
        rss_shmem_kib=rss_shmem_kib,
        swap_kib=swap_kib,
    )


class ParseTest(unittest.TestCase):
    def test_parses_status_and_kib_values(self):
        status = agent_top.parse_status("Name:\tclaude\nVmRSS:\t 2048 kB\n")
        self.assertEqual(status["Name"], "claude")
        self.assertEqual(agent_top.parse_kib(status["VmRSS"]), 2048)

    def test_reads_only_paseo_identity_from_environment(self):
        agent_id, cwd = agent_top.parse_environment(
            b"SECRET=hidden\0PASEO_AGENT_ID=agent-1\0PASEO_AGENT_CWD=/workspace\0"
        )
        self.assertEqual(agent_id, "agent-1")
        self.assertEqual(cwd, "/workspace")

    def test_parses_unified_cgroup_path(self):
        content = "9:cpu:/legacy\n0::/user.slice/app-Paseo-1.scope\n"
        self.assertEqual(
            agent_top.parse_cgroup(content),
            "/user.slice/app-Paseo-1.scope",
        )

    def test_finds_paseo_ancestor_scope(self):
        path = "/user.slice/app-Paseo-1.scope/child.scope"
        self.assertEqual(
            agent_top.paseo_scope_for_path(path),
            "/user.slice/app-Paseo-1.scope",
        )

    def test_prefers_app_slice_over_descendant_scope(self):
        self.assertEqual(
            agent_top.paseo_scope_for_path(
                "/user.slice/app-paseo.slice/paseo-1.scope/child.scope"
            ),
            "/user.slice/app-paseo.slice",
        )

    def test_parses_memory_rollup(self):
        memory = agent_top.parse_smaps_rollup(
            "Rss: 100 kB\nPss: 60 kB\nPss_Shmem: 4 kB\n"
            "Swap: 20 kB\nSwapPss: 10 kB\n",
            rss_shmem_kib=8,
        )
        self.assertEqual(memory.rss_kib, 100)
        self.assertEqual(memory.pss_kib, 60)
        self.assertEqual(memory.rss_shmem_kib, 8)
        self.assertEqual(memory.pss_shmem_kib, 4)
        self.assertEqual(memory.swap_kib, 20)
        self.assertEqual(memory.swap_pss_kib, 10)

    def test_missing_rollup_fields_use_status_fallbacks(self):
        memory = agent_top.parse_smaps_rollup(
            "", rss_kib=100, rss_shmem_kib=8, swap_kib=20
        )
        self.assertIsNone(memory.pss_kib)
        self.assertIsNone(memory.pss_shmem_kib)
        self.assertIsNone(memory.swap_pss_kib)
        self.assertEqual(memory.effective_pss_kib, 100)
        self.assertEqual(memory.effective_pss_shmem_kib, 8)
        self.assertEqual(memory.effective_swap_pss_kib, 20)

    def test_zero_rollup_fields_do_not_use_status_fallbacks(self):
        memory = agent_top.parse_smaps_rollup(
            "Rss: 0 kB\nPss: 0 kB\nPss_Shmem: 0 kB\nSwap: 0 kB\nSwapPss: 0 kB\n",
            rss_kib=100, rss_shmem_kib=8, swap_kib=20,
        )
        self.assertEqual(memory.effective_pss_kib, 0)
        self.assertEqual(memory.effective_pss_shmem_kib, 0)
        self.assertEqual(memory.effective_swap_pss_kib, 0)


class ProviderDetectionTest(unittest.TestCase):
    def test_detects_native_executable(self):
        self.assertEqual(
            agent_top.provider_for_process(process(1, executable="claude")), "claude"
        )

    def test_detects_node_script(self):
        item = process(
            1,
            executable="node",
            argv=("node", "/opt/node_modules/@openai/codex/bin/codex.js"),
        )
        self.assertEqual(agent_top.provider_for_process(item), "codex")

    def test_detects_python_module(self):
        item = process(1, executable="python3", argv=("python3", "-m", "aider.main"))
        self.assertEqual(agent_top.provider_for_process(item), "aider")

    def test_does_not_match_an_argument_mention(self):
        item = process(1, executable="bash", argv=("bash", "-c", "ask claude for help"))
        self.assertIsNone(agent_top.provider_for_process(item))


class GroupDiscoveryTest(unittest.TestCase):
    def test_groups_paseo_descendants_by_inherited_identity(self):
        processes = {
            10: process(10, executable="codex", agent_id="agent-a"),
            11: process(11, ppid=10),
            12: process(12, ppid=11),
        }
        groups = agent_top.discover_groups(processes)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].key, "paseo:agent-a")
        self.assertEqual(groups[0].pids, [10, 11, 12])
        self.assertEqual(groups[0].root_pid, 10)

    def test_separates_nested_paseo_agents(self):
        processes = {
            10: process(10, executable="claude", agent_id="parent"),
            11: process(11, ppid=10, executable="codex", agent_id="child"),
            12: process(12, ppid=11),
        }
        groups = {group.key: group for group in agent_top.discover_groups(processes)}
        self.assertEqual(groups["paseo:parent"].pids, [10])
        self.assertEqual(groups["paseo:child"].pids, [11, 12])

    def test_separates_nested_detected_agents(self):
        processes = {
            10: process(10, executable="claude"),
            11: process(11, ppid=10),
            12: process(12, ppid=11, executable="codex"),
            13: process(13, ppid=12),
        }
        groups = {group.key: group for group in agent_top.discover_groups(processes)}
        self.assertEqual(groups["detected:10"].pids, [10, 11])
        self.assertEqual(groups["detected:12"].pids, [12, 13])

    def test_groups_same_provider_launcher_and_child(self):
        processes = {
            10: process(10, executable="node", argv=("node", "/opt/codex.js")),
            11: process(11, ppid=10, executable="codex"),
            12: process(12, ppid=11, executable="codex-linux-sandbox"),
        }
        groups = agent_top.discover_groups(processes)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].key, "detected:10")
        self.assertEqual(groups[0].pids, [10, 11, 12])

    def test_excludes_unrelated_process_tree(self):
        processes = {
            10: process(10, executable="bash"),
            11: process(11, ppid=10, executable="make"),
        }
        self.assertEqual(agent_top.discover_groups(processes), [])


class ProcFixtureTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.proc_root = self.root / "proc"
        self.cgroup_root = self.root / "cgroup"
        self.proc_root.mkdir()
        self.cgroup_root.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_read_memory_uses_status_when_rollup_fields_are_missing(self):
        self.add_process(10, 0, "worker", ("worker",), rss=100, rss_shmem=8, swap=20)
        (self.proc_root / "10" / "smaps_rollup").write_text("Rss: 100 kB\nPss: 60 kB\n")
        item = agent_top.read_process(self.proc_root, 10, os.getuid())

        memory = agent_top.read_memory(self.proc_root, item)

        self.assertEqual(memory.effective_pss_kib, 60)
        self.assertEqual(memory.effective_pss_shmem_kib, 8)
        self.assertEqual(memory.effective_swap_pss_kib, 20)

    def add_process(
        self,
        pid,
        ppid,
        name,
        cmdline,
        environment=b"",
        cgroup_path="/user.slice/shell.scope",
        rss=100,
        pss=60,
        rss_shmem=8,
        pss_shmem=4,
        swap=20,
        swap_pss=10,
    ):
        process_dir = self.proc_root / str(pid)
        process_dir.mkdir()
        uid = os.getuid()
        (process_dir / "status").write_text(
            f"Name:\t{name}\nPPid:\t{ppid}\nUid:\t{uid} {uid} {uid} {uid}\n"
            f"VmRSS:\t{rss} kB\nRssShmem:\t{rss_shmem} kB\nVmSwap:\t{swap} kB\n"
        )
        (process_dir / "cmdline").write_bytes(
            b"\0".join(item.encode() for item in cmdline) + b"\0"
        )
        (process_dir / "environ").write_bytes(environment)
        (process_dir / "cgroup").write_text(f"0::{cgroup_path}\n")
        (process_dir / "smaps_rollup").write_text(
            f"Rss: {rss} kB\nPss: {pss} kB\nPss_Shmem: {pss_shmem} kB\n"
            f"Swap: {swap} kB\nSwapPss: {swap_pss} kB\n"
        )

    def add_cgroup(self, path, memory, inactive_file, shmem, swap, active_file=0):
        directory = self.cgroup_root / path.lstrip("/")
        directory.mkdir(parents=True)
        (directory / "memory.current").write_text(str(memory * 1024))
        (directory / "memory.stat").write_text(
            f"inactive_file {inactive_file * 1024}\nactive_file {active_file * 1024}\n"
            f"shmem {shmem * 1024}\n"
        )
        (directory / "memory.swap.current").write_text(str(swap * 1024))

    def test_snapshot_reads_process_memory_and_metadata(self):
        self.add_process(
            10,
            0,
            "claude",
            ("claude",),
            b"PASEO_AGENT_ID=agent-1\0PASEO_AGENT_CWD=/project\0",
        )
        self.add_process(
            11,
            10,
            "node",
            ("node", "worker.js"),
            rss=50,
            pss=30,
            swap=4,
            swap_pss=2,
        )

        measurements = agent_top.take_snapshot(
            {
                "agent-1": {
                    "id": "agent-1",
                    "name": "Investigate memory",
                    "provider": "claude/opus",
                    "cwd": "/wrong",
                }
            },
            self.proc_root,
            os.getuid(),
            self.cgroup_root,
        )

        self.assertEqual(len(measurements), 1)
        measurement = measurements[0]
        self.assertEqual(measurement.name, "Investigate memory")
        self.assertEqual(measurement.provider, "claude/opus")
        self.assertEqual(measurement.cwd, "/project")
        self.assertEqual(measurement.pss_kib, 90)
        self.assertEqual(measurement.swap_pss_kib, 12)
        self.assertEqual(measurement.pss_shmem_kib, 8)
        self.assertEqual(measurement.total_kib, 102)
        self.assertTrue(measurement.pss_complete)
        table = agent_top.render_table(measurements, 0)
        self.assertIn("/project", table)
        self.assertIn("claude", table)
        self.assertIn("Investigate memory", table)
        self.assertNotIn("SOURCE", table)
        self.assertNotIn("PROVIDER", table)

    def test_synthetic_overhead_reconciles_proportional_totals(self):
        scope = "/user.slice/app-Paseo-1.scope"
        self.add_process(
            10,
            0,
            "claude",
            ("claude",),
            b"PASEO_AGENT_ID=agent-1\0",
            cgroup_path=scope,
        )
        self.add_cgroup(scope, memory=1000, inactive_file=100, shmem=50, swap=200)

        measurements = agent_top.take_snapshot(
            {}, self.proc_root, os.getuid(), self.cgroup_root
        )
        by_source = {item.source: item for item in measurements}
        agent = by_source["paseo"]
        overhead = by_source["cgroup"]

        self.assertEqual(overhead.name, "[Paseo app accounting difference]")
        self.assertTrue(overhead.synthetic)
        self.assertEqual(agent.pss_kib + overhead.pss_kib, 900)
        self.assertEqual(agent.swap_pss_kib + overhead.swap_pss_kib, 200)
        self.assertEqual(agent.pss_shmem_kib + overhead.pss_shmem_kib, 50)
        self.assertEqual(agent.total_kib + overhead.total_kib, 1100)

        with (
            patch.object(agent_top.sys.stdout, "isatty", return_value=True),
            patch.object(agent_top.shutil, "get_terminal_size", return_value=os.terminal_size((180, 30))),
        ):
            table = agent_top.render_table(measurements, 0)
        colored = [line for line in table.splitlines() if line.startswith("\033[36m")]
        self.assertEqual(len(colored), 1)
        self.assertIn(overhead.name, colored[0])
        self.assertTrue(colored[0].endswith("\033[0m"))
        with patch.object(agent_top.sys.stdout, "isatty", return_value=False):
            self.assertNotIn("\033", agent_top.render_table(measurements, 0))
        payloads = [
            json.loads(line) for line in agent_top.render_json_lines(measurements, False).splitlines()
        ]
        self.assertEqual(next(item for item in payloads if item["synthetic"])["name"], overhead.name)

    def test_splits_app_and_daemon_without_counting_descendant_scopes_twice(self):
        app = "/user.slice/app-paseo.slice"
        daemon = "/user.slice/paseo-daemon.service"
        self.add_process(10, 0, "Paseo", ("Paseo",), cgroup_path=app + "/paseo-1.scope")
        self.add_process(11, 10, "Paseo", ("Paseo",), cgroup_path=app + "/app-Paseo-1.scope")
        self.add_process(
            20, 0, "claude", ("claude",), b"PASEO_AGENT_ID=agent-1\0",
            cgroup_path=daemon,
        )
        self.add_process(
            21, 20, "worker", ("worker",), cgroup_path=daemon + "/child.scope",
            pss=30, swap_pss=2,
        )
        self.add_cgroup(app, memory=1000, inactive_file=100, shmem=50, swap=200)
        self.add_cgroup(app + "/paseo-1.scope", memory=400, inactive_file=40, shmem=20, swap=80)
        self.add_cgroup(app + "/app-Paseo-1.scope", memory=600, inactive_file=60, shmem=30, swap=120)
        self.add_cgroup(daemon, memory=500, inactive_file=50, shmem=20, swap=100)

        measurements = agent_top.take_snapshot(
            {}, self.proc_root, os.getuid(), self.cgroup_root
        )
        overhead = {item.name: item for item in measurements if item.synthetic}

        self.assertEqual(len(overhead), 2)
        app_overhead = overhead["[Paseo app accounting difference]"]
        daemon_overhead = overhead["[Paseo daemon accounting difference]"]
        services = next(item for item in measurements if item.source == "services")
        self.assertEqual(app_overhead.pss_kib, 780)
        self.assertEqual(app_overhead.pss_shmem_kib, 42)
        self.assertEqual(app_overhead.swap_pss_kib, 180)
        self.assertEqual(services.name, "[Paseo app services]")
        self.assertEqual({item.process.pid for item in services.processes}, {10, 11})
        self.assertEqual(app_overhead.cwd, app)
        self.assertEqual(daemon_overhead.pss_kib, 360)
        self.assertEqual(daemon_overhead.pss_shmem_kib, 12)
        self.assertEqual(daemon_overhead.swap_pss_kib, 88)
        self.assertEqual(sum(item.pss_kib for item in measurements), 1350)
        self.assertEqual(sum(item.swap_pss_kib for item in measurements), 300)

    def test_combines_app_scopes_and_shows_overhead_without_agents(self):
        scopes = ("/user.slice/paseo-1.scope", "/user.slice/app-Paseo-1.scope")
        for pid, scope in enumerate(scopes, start=10):
            self.add_process(pid, 0, "Paseo", ("Paseo",), cgroup_path=scope)
            self.add_cgroup(scope, memory=1000, inactive_file=100, shmem=50, swap=200)
        daemon = "/user.slice/paseo-daemon.service"
        self.add_process(20, 0, "node", ("node",), cgroup_path=daemon)
        self.add_cgroup(daemon, memory=500, inactive_file=50, shmem=20, swap=100)

        measurements = agent_top.take_snapshot(
            {}, self.proc_root, os.getuid(), self.cgroup_root
        )
        by_name = {item.name: item for item in measurements}

        self.assertEqual(len(measurements), 4)
        app_overhead = by_name["[Paseo app accounting difference]"]
        self.assertEqual(app_overhead.pss_kib, 1680)
        self.assertEqual(app_overhead.swap_pss_kib, 380)
        self.assertEqual(app_overhead.pss_shmem_kib, 92)
        self.assertEqual(set(app_overhead.cwd.split(", ")), set(scopes))
        app_services = by_name["[Paseo app services]"]
        self.assertFalse(app_services.synthetic)
        self.assertEqual(app_services.pss_kib, 120)
        self.assertEqual(app_services.swap_pss_kib, 20)
        self.assertEqual(app_services.pss_shmem_kib, 8)
        self.assertEqual({item.process.pid for item in app_services.processes}, {10, 11})
        daemon_services = by_name["[Paseo daemon services]"]
        self.assertEqual(daemon_services.total_kib, 70)
        self.assertEqual(by_name["[Paseo daemon accounting difference]"].total_kib, 480)
        self.assertEqual(sum(item.total_kib for item in measurements), 2750)

        with patch.object(agent_top.sys.stdout, "isatty", return_value=True):
            table = agent_top.render_table(measurements, 0)
        self.assertEqual(sum(line.startswith("\033[36m") for line in table.splitlines()), 4)
        self.assertIn("Memory", table.splitlines()[0])
        self.assertNotIn("PSS", table.splitlines()[0].split("Executables")[0])

        payloads = {
            row["name"]: row
            for line in agent_top.render_json_lines(measurements, True).splitlines()
            if (row := json.loads(line))
        }
        services_json = payloads["[Paseo app services]"]
        self.assertEqual(services_json["pss_bytes"], 120 * 1024)
        self.assertEqual(services_json["process_count"], 2)
        self.assertEqual({item["pid"] for item in services_json["processes"]}, {10, 11})
        difference_json = payloads["[Paseo app accounting difference]"]
        self.assertIsNone(difference_json["pss_bytes"])
        self.assertIsNone(difference_json["pss_complete"])
        self.assertEqual(difference_json["memory_bytes"], 1680 * 1024)

        args = agent_top.build_parser().parse_args(["--processes", "services:paseo-daemon"])
        details, success = agent_top.render_once(measurements, args)
        self.assertTrue(success)
        self.assertIn("[Paseo daemon services]", details)
        self.assertIn("20 node", details)

    def test_separates_services_and_agents_in_the_same_daemon_cgroup(self):
        scope = "/user.slice/paseo-daemon.service"
        self.add_process(
            10, 0, "Paseo Daemon", ("Paseo Daemon",), cgroup_path=scope,
            pss=120, swap_pss=30,
        )
        self.add_process(
            20, 10, "codex", ("codex",), b"PASEO_AGENT_ID=agent-1\0",
            cgroup_path=scope,
        )
        self.add_process(
            21, 20, "worker", ("worker",), cgroup_path=scope + "/child.scope",
            pss=30, swap_pss=2,
        )
        self.add_process(
            30, 10, "node", ("node", "plugin-process.js"), cgroup_path=scope,
            pss=20, swap_pss=5,
        )
        self.add_cgroup(scope, memory=1000, inactive_file=100, shmem=50, swap=200)

        measurements = agent_top.take_snapshot(
            {}, self.proc_root, os.getuid(), self.cgroup_root
        )
        by_source = {item.source: item for item in measurements}
        services = by_source["services"]
        agents = by_source["paseo"]
        difference = by_source["cgroup"]

        self.assertEqual({item.process.pid for item in services.processes}, {10, 30})
        self.assertEqual({item.process.pid for item in agents.processes}, {20, 21})
        self.assertEqual(services.pss_kib, 140)
        self.assertEqual(services.swap_pss_kib, 35)
        self.assertEqual(difference.pss_kib, 670)
        self.assertEqual(difference.swap_pss_kib, 153)
        self.assertEqual(sum(item.pss_kib for item in measurements), 900)
        self.assertEqual(sum(item.pss_shmem_kib for item in measurements), 50)
        self.assertEqual(sum(item.swap_pss_kib for item in measurements), 200)

    def test_services_use_rss_fallback_and_skip_exited_processes(self):
        scope = "/user.slice/paseo-daemon.service"
        self.add_process(10, 0, "node", ("node",), cgroup_path=scope, rss=100, swap=20)
        self.add_process(11, 10, "worker", ("worker",), cgroup_path=scope)
        (self.proc_root / "11" / "smaps_rollup").unlink()
        self.add_cgroup(scope, memory=1000, inactive_file=100, shmem=50, swap=200)
        fallback = agent_top.ProcessMemory(100, None, 8, None, 20, None)
        read_memory = agent_top.read_memory

        def read_with_fallback(proc_root, item):
            return fallback if item.pid == 10 else read_memory(proc_root, item)

        with patch.object(agent_top, "read_memory", side_effect=read_with_fallback):
            measurements = agent_top.take_snapshot(
                {}, self.proc_root, os.getuid(), self.cgroup_root
            )

        services = next(item for item in measurements if item.source == "services")
        self.assertEqual([item.process.pid for item in services.processes], [10])
        self.assertFalse(services.pss_complete)
        self.assertEqual(services.pss_kib, 100)
        self.assertEqual(services.pss_shmem_kib, 8)
        self.assertEqual(services.swap_pss_kib, 20)
        self.assertEqual(sum(item.total_kib for item in measurements), 1100)

    def test_subtracts_detected_agents_and_preserves_negative_overhead(self):
        scope = "/user.slice/paseo-daemon.service"
        self.add_process(10, 0, "codex", ("codex",), cgroup_path=scope, pss=60)
        self.add_cgroup(scope, memory=50, inactive_file=10, shmem=0, swap=0)

        measurements = agent_top.take_snapshot(
            {}, self.proc_root, os.getuid(), self.cgroup_root
        )
        overhead = next(item for item in measurements if item.synthetic)

        self.assertEqual(overhead.name, "[Paseo daemon accounting difference]")
        self.assertEqual(overhead.pss_kib, -20)
        self.assertEqual(sum(item.total_kib for item in measurements), 40)

    def test_synthetic_overhead_keeps_active_file_like_cgroups_top(self):
        scope = "/user.slice/app-Paseo-1.scope"
        self.add_process(
            10,
            0,
            "claude",
            ("claude",),
            b"PASEO_AGENT_ID=agent-1\0",
            cgroup_path=scope,
        )
        self.add_cgroup(
            scope, memory=1000, inactive_file=100, active_file=150, shmem=50, swap=200
        )

        measurements = agent_top.take_snapshot(
            {}, self.proc_root, os.getuid(), self.cgroup_root
        )
        by_source = {item.source: item for item in measurements}
        agent = by_source["paseo"]
        overhead = by_source["cgroup"]

        self.assertEqual(agent.pss_kib + overhead.pss_kib, 900)

    def test_json_lines_can_include_process_data(self):
        self.add_process(20, 0, "codex", ("codex",), rss=80, pss=50)
        measurements = agent_top.take_snapshot(
            {}, self.proc_root, os.getuid(), self.cgroup_root
        )
        lines = agent_top.render_json_lines(measurements, include_processes=True).splitlines()
        payload = json.loads(lines[0])
        self.assertEqual(payload["pss_bytes"], 50 * 1024)
        self.assertEqual(payload["swap_bytes"], 10 * 1024)
        self.assertEqual(payload["total_bytes"], 60 * 1024)
        self.assertTrue(payload["pss_complete"])
        self.assertEqual(payload["processes"][0]["comm"], "codex")
        self.assertEqual(payload['memory_bytes'], payload['pss_bytes'])
        self.assertEqual(payload['name'], 'codex pid 20')
        self.assertEqual(payload['source'], 'detected')
        self.assertEqual(payload['provider'], 'codex')


class EffectiveMemoryTest(unittest.TestCase):
    def memory(self, pss_kib, pss_shmem_kib, swap_pss_kib):
        return agent_top.ProcessMemory(
            rss_kib=100,
            pss_kib=pss_kib,
            rss_shmem_kib=8,
            pss_shmem_kib=pss_shmem_kib,
            swap_kib=20,
            swap_pss_kib=swap_pss_kib,
        )

    def test_uses_proportional_values_when_available(self):
        memory = self.memory(60, 4, 10)
        self.assertTrue(memory.pss_available)
        self.assertEqual(memory.effective_pss_kib, 60)
        self.assertEqual(memory.effective_pss_shmem_kib, 4)
        self.assertEqual(memory.effective_swap_pss_kib, 10)
        self.assertEqual(memory.effective_total_kib, 70)

    def test_falls_back_to_resident_values_when_rollup_unavailable(self):
        memory = self.memory(None, None, None)
        self.assertFalse(memory.pss_available)
        self.assertEqual(memory.effective_pss_kib, 100)
        self.assertEqual(memory.effective_pss_shmem_kib, 8)
        self.assertEqual(memory.effective_swap_pss_kib, 20)
        self.assertEqual(memory.effective_total_kib, 120)

    def test_aggregate_marks_incomplete_when_a_process_falls_back(self):
        totals = agent_top.aggregate_effective(
            [self.memory(60, 4, 10), self.memory(None, None, None)]
        )
        self.assertEqual(totals.pss_kib, 160)
        self.assertEqual(totals.swap_pss_kib, 30)
        self.assertEqual(totals.pss_shmem_kib, 12)
        self.assertFalse(totals.complete)


class InterfaceTest(unittest.TestCase):
    def test_process_name_precedes_versioned_executable_target(self):
        measured = agent_top.MeasuredProcess(
            process(10, name="claude", executable="2.1.238"),
            agent_top.ProcessMemory(
                rss_kib=100,
                pss_kib=60,
                rss_shmem_kib=0,
                pss_shmem_kib=0,
                swap_kib=0,
                swap_pss_kib=0,
            ),
        )
        self.assertEqual(agent_top.process_name(measured), "claude")

    def test_formats_positive_negative_and_unknown_memory(self):
        self.assertEqual(agent_top.format_kib(512), "512KiB")
        self.assertEqual(agent_top.format_kib(1536), "1.5MiB")
        self.assertEqual(agent_top.format_kib(-1536), "-1.5MiB")
        self.assertEqual(agent_top.format_kib(None), "?")

    def test_rejects_invalid_interval_and_limit(self):
        with self.assertRaises(agent_top.argparse.ArgumentTypeError):
            agent_top.positive_interval("0")
        with self.assertRaises(agent_top.argparse.ArgumentTypeError):
            agent_top.nonnegative_limit("-1")

    def test_parser_mirrors_cgroups_top_flags(self):
        args = agent_top.build_parser().parse_args(
            [
                "--json",
                "--include-processes",
                "--processes",
                "agent-1",
                "--watch",
                "--interval",
                "0.5",
                "--limit",
                "0",
            ]
        )
        self.assertTrue(args.json)
        self.assertTrue(args.include_processes)
        self.assertEqual(args.processes, "agent-1")
        self.assertTrue(args.watch)
        self.assertEqual(args.interval, 0.5)
        self.assertEqual(args.limit, 0)


if __name__ == "__main__":
    unittest.main()

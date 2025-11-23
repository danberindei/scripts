#!/usr/bin/env python3

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def human_size(bytes_val):
    """Convert bytes to human-readable format."""
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.1f}{unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f}PiB"


def get_proc_comm(pid):
    """Get command name for a PID."""
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except (FileNotFoundError, PermissionError):
        return None


def get_proc_cmdline(pid):
    """Get full command line for a PID."""
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_text()
        if cmdline:
            return ' '.join(cmdline.split('\x00')).strip()
        return get_proc_comm(pid)
    except (FileNotFoundError, PermissionError):
        return None


def get_proc_memory(pid):
    """Get memory usage for a PID from /proc/pid/status."""
    try:
        status = Path(f"/proc/{pid}/status").read_text()
        rss_kb = 0
        swap_kb = 0
        shmem_kb = 0

        for line in status.split('\n'):
            if line.startswith('VmRSS:'):
                rss_kb = int(line.split()[1])
            elif line.startswith('VmSwap:'):
                swap_kb = int(line.split()[1])
            elif line.startswith('RssShmem:'):
                shmem_kb = int(line.split()[1])

        return {
            'rss_bytes': rss_kb * 1024,
            'swap_bytes': swap_kb * 1024,
            'shmem_bytes': shmem_kb * 1024
        }
    except (FileNotFoundError, PermissionError, ValueError):
        return {'rss_bytes': 0, 'swap_bytes': 0, 'shmem_bytes': 0}


def collect_cgroup_data():
    """Collect cgroup memory and process data."""
    results = []

    for cgroup_dir in Path("/sys/fs/cgroup").rglob("*"):
        if not cgroup_dir.is_dir():
            continue

        memory_file = cgroup_dir / "memory.current"
        swap_file = cgroup_dir / "memory.swap.current"
        stat_file = cgroup_dir / "memory.stat"
        procs_file = cgroup_dir / "cgroup.procs"

        if not (memory_file.exists() and procs_file.exists()):
            continue

        try:
            memory_bytes = int(memory_file.read_text().strip())
            swap_bytes = int(swap_file.read_text().strip()) if swap_file.exists() else 0

            # Extract shmem from memory.stat
            shmem_bytes = 0
            if stat_file.exists():
                for line in stat_file.read_text().split('\n'):
                    if line.startswith('shmem '):
                        shmem_bytes = int(line.split()[1])
                        break

            pids = [int(p) for p in procs_file.read_text().strip().split('\n') if p]
            if not pids:
                continue

            root_pid = pids[0]

            # Get distinct executable names
            exes = set()
            for pid in pids:
                comm = get_proc_comm(pid)
                if comm:
                    exes.add(comm)

            # Collect per-process memory totals for this cgroup
            processes = []
            for pid in pids:
                cmdline = get_proc_cmdline(pid) or get_proc_comm(pid) or ''
                mem = get_proc_memory(pid)
                total = mem['rss_bytes'] + mem['swap_bytes'] + mem['shmem_bytes']
                processes.append({
                    'pid': pid,
                    'cmdline': cmdline,
                    **mem,
                    'total_bytes': total
                })

            # Sort processes by total memory usage descending
            processes.sort(key=lambda x: x['total_bytes'], reverse=True)

            service_name = cgroup_dir.name[:40]

            results.append({
                'memory_bytes': memory_bytes,
                'swap_bytes': swap_bytes,
                'shmem_bytes': shmem_bytes,
                'root_pid': root_pid,
                'service': service_name,
                'executables': sorted(exes),
                'processes': processes,
                'cgroup_path': str(cgroup_dir),
                'pids': pids
            })

        except (ValueError, PermissionError):
            continue

    # Sort by total memory usage (memory + swap + shmem)
    results.sort(key=lambda x: x['memory_bytes'] + x['swap_bytes'] + x['shmem_bytes'], reverse=True)
    return results


def get_terminal_width():
    """Get terminal width if output is interactive."""
    is_tty = sys.stdout.isatty()
    if is_tty:
        terminal_width = shutil.get_terminal_size().columns
    else:
        terminal_width = None
    return is_tty, terminal_width


def print_cgroups_table(data):
    """Print cgroup data in aligned table format."""
    if not data:
        return

    is_tty, terminal_width = get_terminal_width()

    # Calculate max widths
    max_pid_width = max(len(str(row['root_pid'])) for row in data)

    # Print header
    print(f"{'Total':>9} {'Memory':>9} {'Shmem':>9} {'Swap':>9} {'PID':>{max_pid_width}} {'Service':40} {'Executables(Mem)'}")
    if is_tty:
        print("-" * terminal_width)
    else:
        print("-" * 100)

    # Calculate fixed width for clipping. Executables column will include per-executable memory totals.
    fixed_width = 9 + 1 + 9 + 1 + 9 + 1 + 9 + 1 + max_pid_width + 1 + 40 + 1
    if is_tty:
        exes_width = max(20, terminal_width - fixed_width)
    else:
        exes_width = None

    for row in data:
        total_bytes = row['memory_bytes'] + row['swap_bytes'] + row['shmem_bytes']
        total_str = human_size(total_bytes)
        memory_str = human_size(row['memory_bytes'])
        shmem_str = human_size(row['shmem_bytes'])
        swap_str = human_size(row['swap_bytes'])
        pid_str = str(row['root_pid'])
        service = row['service']

        # Aggregate memory per executable name (prefer /proc/<pid>/comm).
        # Count RSS+swap for each process, but include shared memory only once per executable
        exe_rss_swap = {}
        exe_shmem_once = {}
        for p in (row.get('processes') or []):
            try:
                comm = get_proc_comm(p['pid']) or ''
            except Exception:
                comm = ''
            if not comm:
                # fallback to first token of cmdline
                cmd = p.get('cmdline') or ''
                comm = cmd.split(' ')[0] if cmd else ''

            rss = p.get('rss_bytes', 0)
            swap = p.get('swap_bytes', 0)
            shmem = p.get('shmem_bytes', 0)

            exe_rss_swap[comm] = exe_rss_swap.get(comm, 0) + rss + swap
            # include shared memory only once per executable: track the max shmem seen
            exe_shmem_once[comm] = max(exe_shmem_once.get(comm, 0), shmem)

        # Build sorted list by memory desc (rss+swap summed per-exe + shmem counted once per-exe)
        exe_items = []
        for name, rss_swap_sum in exe_rss_swap.items():
            shmem_once = exe_shmem_once.get(name, 0)
            total = rss_swap_sum + shmem_once
            exe_items.append((name, total))

        exe_items.sort(key=lambda x: x[1], reverse=True)
        exes_with_mem = [f"{name} {human_size(size)}" for name, size in exe_items if name]
        exes_str = ','.join(exes_with_mem)

        # Clip executables string to available width
        if exes_width and len(exes_str) > exes_width:
            exes_str = exes_str[:exes_width-3] + '...'

        print(f"{total_str:>9} {memory_str:>9} {shmem_str:>9} {swap_str:>9} {pid_str:>{max_pid_width}} {service:40} {exes_str}")


def print_processes_table(data, title=None):
    """Print process data in aligned table format."""
    if not data:
        return

    is_tty, terminal_width = get_terminal_width()

    if title:
        print(title)

    # Calculate max widths
    max_pid_width = max(len(str(row['pid'])) for row in data)

    # Print header
    print(f"{'Total':>9} {'RSS':>9} {'Shmem':>9} {'Swap':>9} {'PID':>{max_pid_width}} {'COMMAND'}")
    if is_tty:
        print("-" * terminal_width)
    else:
        print("-" * 100)

    # Calculate fixed width for clipping
    fixed_width = 9 + 1 + 9 + 1 + 9 + 1 + 9 + 1 + max_pid_width + 1
    if is_tty:
        cmdline_width = max(20, terminal_width - fixed_width)
    else:
        cmdline_width = None

    for row in data:
        total_bytes = row['rss_bytes'] + row['swap_bytes'] + row['shmem_bytes']
        total_str = human_size(total_bytes)
        rss_str = human_size(row['rss_bytes'])
        shmem_str = human_size(row['shmem_bytes'])
        swap_str = human_size(row['swap_bytes'])
        pid_str = str(row['pid'])
        cmdline = row['cmdline']

        if cmdline_width and len(cmdline) > cmdline_width:
            cmdline = cmdline[:cmdline_width-3] + '...'

        print(f"{total_str:>9} {rss_str:>9} {shmem_str:>9} {swap_str:>9} {pid_str:>{max_pid_width}} {cmdline}")


def print_jsonl(data, include_processes=False):
    """Print data in JSON Lines format."""
    for row in data:
        output = {k: v for k, v in row.items() if k not in ['cgroup_path', 'pids']}
        # Add a simple exe field (first executable name) to make grouping by executable easier with jq
        exe = None
        exes = row.get('executables') or []
        if exes:
            exe = exes[0]
        output['exe'] = exe
        if include_processes:
            output['processes'] = []
            for pid in row['pids']:
                mem = get_proc_memory(pid)
                output['processes'].append({
                    'pid': pid,
                    'comm': get_proc_comm(pid),
                    **mem
                })
        print(json.dumps(output))


def show_cgroup_processes(cgroup_name, limit=10):
    """Show individual process memory usage for a specific cgroup."""
    for cgroup_dir in Path("/sys/fs/cgroup").rglob("*"):
        if not cgroup_dir.is_dir():
            continue

        if cgroup_dir.name != cgroup_name:
            continue

        procs_file = cgroup_dir / "cgroup.procs"
        if not procs_file.exists():
            continue

        try:
            pids = [int(p) for p in procs_file.read_text().strip().split('\n') if p]
            if not pids:
                continue

            # Collect process data
            processes = []
            for pid in pids:
                cmdline = get_proc_cmdline(pid)
                mem = get_proc_memory(pid)
                if cmdline:
                    processes.append({
                        'pid': pid,
                        'cmdline': cmdline,
                        **mem
                    })

            # Sort by total memory
            processes.sort(key=lambda x: x['rss_bytes'] + x['swap_bytes'] + x['shmem_bytes'], reverse=True)

            # Apply limit
            if limit > 0:
                processes = processes[:limit]

            # Use print_processes_table to display processes
            print_processes_table(processes, title=f"Cgroup: {cgroup_dir}")

            return

        except (ValueError, PermissionError):
            continue

    print(f"Cgroup '{cgroup_name}' not found", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Display cgroup memory usage')
    parser.add_argument('--json', action='store_true', help='Output in JSON Lines format')
    parser.add_argument('--processes', metavar='CGROUP', help='Show individual process memory for a specific cgroup')
    parser.add_argument('--include-processes', action='store_true', help='Include process details in JSON output')
    parser.add_argument('-n', '--limit', type=int, default=10, help='Number of top entries to show (default: 10, use 0 for all)')
    args = parser.parse_args()

    if args.processes:
        show_cgroup_processes(args.processes, args.limit)
        return

    data = collect_cgroup_data()

    # Apply limit for table output
    if not args.json and args.limit > 0:
        data = data[:args.limit]

    try:
        if args.json:
            print_jsonl(data, include_processes=args.include_processes)
        else:
            print_cgroups_table(data)
    except BrokenPipeError:
        print("Broken pipe", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()

"""Memory formatting and terminal controls shared by the process monitors."""

import argparse
import math
import os
import re
import select
import shutil
import sys
import termios
import time
import tty
from pathlib import Path


def human_size(value):
    """Format signed byte counts with binary units and consistent precision."""
    if value is None:
        return '?'
    sign = '-' if value < 0 else ''
    amount = float(abs(value))
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'):
        if amount < 1024 or unit == 'PiB':
            precision = 0 if amount >= 100 else 1
            return f'{sign}{amount:.{precision}f}{unit}'
        amount /= 1024


def positive_interval(value):
    try:
        interval = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError('interval must be a number') from error
    if not math.isfinite(interval) or interval <= 0:
        raise argparse.ArgumentTypeError('interval must be finite and greater than zero')
    return interval


def nonnegative_limit(value):
    try:
        limit = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError('limit must be an integer') from error
    if limit < 0:
        raise argparse.ArgumentTypeError('limit cannot be negative')
    return limit


def read_cgroup_memory(directory):
    """Read cgroup RAM and swap, excluding inactive file cache from RAM.

    Cgroup counters already include descendants. Callers must not add child
    counters to these values. A missing swap counter contributes zero.
    RAM retains active file cache and kernel memory; it is not process RSS/PSS.
    """
    directory = Path(directory)
    current = int((directory / 'memory.current').read_text())
    stat = dict(line.split() for line in (directory / 'memory.stat').read_text().splitlines())
    try:
        swap = int((directory / 'memory.swap.current').read_text())
    except FileNotFoundError:
        swap = 0
    return {
        'memory_bytes': max(0, current - int(stat.get('inactive_file', 0))),
        'shmem_bytes': int(stat.get('shmem', 0)),
        'swap_bytes': swap,
    }


def watch_page(output, offset, height, header_lines=1, footer_lines=0):
    """Scroll table rows while retaining headings, explanatory notes, and status."""
    lines = output.splitlines()
    heading = lines[:header_lines]
    rows = lines[header_lines:]
    footer = rows[-footer_lines:] if footer_lines else []
    rows = rows[:-footer_lines] if footer_lines else rows
    footer = footer[:max(0, height - len(heading) - 2)]
    capacity = max(1, height - len(heading) - len(footer) - 1)
    offset = max(0, min(offset, max(0, len(rows) - capacity)))
    visible = rows[offset:offset + capacity]
    start = offset + 1 if rows else 0
    status = f'Rows {start}-{offset + len(visible)} of {len(rows)} | Up/Down PgUp/PgDn Home/End | q quit'
    return '\n'.join(heading + visible + footer + [status]), offset, capacity


def clip_terminal_line(line, width):
    """Keep SGR styling while preventing a table row from wrapping."""
    parts = re.split(r'(\033\[[0-9;]*m)', line)
    result = []
    remaining = width
    for part in parts:
        if part.startswith('\033['):
            result.append(part)
        else:
            result.append(part[:remaining])
            remaining -= min(remaining, len(part))
        if remaining == 0:
            break
    return ''.join(result) + ('\033[0m' if '\033[' in line else '')


class WatchDisplay:
    """Render a scrolling watch view and restore terminal state on exit.

    Redirected output stays plain text. Keyboard controls are enabled only
    when both input and output are terminals.
    """

    def __init__(self, enabled=True, header_lines=1, footer_lines=0):
        self.interactive = enabled and sys.stdout.isatty() and sys.stdin.isatty()
        self.header_lines = header_lines
        self.footer_lines = footer_lines
        self.offset = 0
        self.capacity = 1
        self.output = ''
        self.title = ''
        self.input_buffer = ''
        self.attributes = None

    def __enter__(self):
        if self.interactive:
            self.attributes = termios.tcgetattr(sys.stdin.fileno())
            tty.setcbreak(sys.stdin.fileno())
            print('\033[?1049h\033[?25l', end='', flush=True)
        return self

    def __exit__(self, *_args):
        if self.attributes is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.attributes)
            print('\033[0m\033[?25h\033[?1049l', end='', flush=True)

    def render(self, output, title=''):
        self.output = output
        self.title = title
        if not self.interactive:
            print(output, flush=True)
            return
        size = shutil.get_terminal_size()
        page, self.offset, self.capacity = watch_page(
            output, self.offset, size.lines, self.header_lines, self.footer_lines
        )
        page = '\n'.join(clip_terminal_line(line, size.columns) for line in page.splitlines())
        safe_title = re.sub(r'[\x00-\x1f\x7f]', '', title)
        print(f'\033]2;{safe_title}\007\033[H\033[J{page}', end='', flush=True)

    def handle_key(self, key):
        if key in ('q', 'Q', '\x04'):
            return False
        if key in ('j', '\033[B', '\033OB'):
            self.offset += 1
        elif key in ('k', '\033[A', '\033OA'):
            self.offset -= 1
        elif key in (' ', '\033[6~'):
            self.offset += self.capacity
        elif key in ('b', '\033[5~'):
            self.offset -= self.capacity
        elif key in ('g', '\033[H', '\033[1~', '\033OH'):
            self.offset = 0
        elif key in ('G', '\033[F', '\033[4~', '\033OF'):
            self.offset = len(self.output.splitlines())
        return True

    def wait(self, interval):
        """Wait for the next sample while handling navigation and resizing."""
        if not self.interactive:
            time.sleep(interval)
            return True
        deadline = time.monotonic() + interval
        size = shutil.get_terminal_size()
        while (remaining := deadline - time.monotonic()) > 0:
            ready, _, _ = select.select([sys.stdin], [], [], min(remaining, 0.25))
            if ready:
                data = os.read(sys.stdin.fileno(), 128)
                if not data:
                    return False
                self.input_buffer += data.decode(errors='replace')
                while self.input_buffer:
                    if self.input_buffer.startswith('\033'):
                        match = re.match(r'\033(?:\[[0-9;]*[A-Za-z~]|O[A-Za-z])', self.input_buffer)
                        if match is None:
                            if self.input_buffer in ('\033', '\033[', '\033O') or re.fullmatch(r'\033\[[0-9;]+', self.input_buffer):
                                break
                            self.input_buffer = self.input_buffer[1:]
                            continue
                        key = match.group()
                    else:
                        key = self.input_buffer[0]
                    self.input_buffer = self.input_buffer[len(key):]
                    if not self.handle_key(key):
                        return False
                self.render(self.output, self.title)
            new_size = shutil.get_terminal_size()
            if new_size != size:
                size = new_size
                self.render(self.output, self.title)
        return True

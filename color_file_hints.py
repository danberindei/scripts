# Kitty hints customization that matches file paths in terminal output and opens them in IntelliJ.
# Paths with a line number suffix (e.g. src/Foo.java:42) are always shown as hints.
# Plain paths (no line number) are only shown as hints when the text is colored in the terminal,
# which filters out noise like prose text and focuses on compiler/tool output.
# Color detection works by fetching the screen's ANSI text via `kitty @` and checking that
# every character of the matched path has a foreground color applied, with no color bleed
# from adjacent characters.
#
# Kitty config:
#   map ctrl+shift+p>i kitten hints --type regex --regex '(?:(?:~|\.\.?|[A-Za-z0-9_~.+-]*)\/)+[A-Za-z0-9_~.+-]+\.[A-Za-z][A-Za-z0-9._+-]{0,15}|[A-Za-z0-9_~+-]+\.[A-Za-z][A-Za-z0-9._+-]{0,15}' --customize-processing color_file_hints.py --program /home/dan/Tools/bin/open-idea-fileline

import re
import subprocess

HINT_PATTERN = re.compile(
    r'(?:(?:~|\.\.?|[A-Za-z0-9_~.+-]*)\/)+[A-Za-z0-9_~.+-]+\.[A-Za-z][A-Za-z0-9._+-]{0,15}(?::\d+)?'
    r'|[A-Za-z0-9_~+-]+\.[A-Za-z][A-Za-z0-9._+-]{0,15}(?::\d+)?'
)

LINE_NUM_RE = re.compile(r':\d+$')


def build_color_map(ansi_text):
    # Returns (plain_text, color_map) where color_map[i] is True if plain_text[i] is colored.
    plain = []
    colors = []
    is_colored = False
    i = 0
    while i < len(ansi_text):
        c = ansi_text[i]
        if c == '\x1b' and i + 1 < len(ansi_text) and ansi_text[i + 1] == '[':
            j = i + 2
            while j < len(ansi_text) and ansi_text[j] not in 'ABCDEFGHJKSTfmnsulh':
                j += 1
            if j < len(ansi_text) and ansi_text[j] == 'm':
                params_str = ansi_text[i + 2:j]
                # Split by ';', but each token may itself have colon sub-params (e.g. 38:2:r:g:b)
                params = params_str.split(';') if params_str else ['0']
                k = 0
                while k < len(params):
                    token = params[k]
                    # Handle colon sub-params within a single token (e.g. "38:2:80:200:80")
                    if ':' in token:
                        sub = token.split(':')
                        try:
                            n = int(sub[0])
                        except ValueError:
                            k += 1
                            continue
                        if n == 38:
                            is_colored = True
                        elif n == 48 or n == 39:
                            pass  # bg or default fg — no change to fg color state
                        k += 1
                        continue
                    try:
                        n = int(token) if token else 0
                    except ValueError:
                        k += 1
                        continue
                    if n == 0:
                        is_colored = False
                    elif n == 1:
                        is_colored = True
                    elif 30 <= n <= 37 or 90 <= n <= 97:
                        is_colored = True
                    elif n == 38:
                        is_colored = True
                        if k + 1 < len(params) and params[k + 1] == '5':
                            k += 2
                        elif k + 1 < len(params) and params[k + 1] == '2':
                            k += 4
                    elif n == 39:
                        is_colored = False
                    k += 1
            i = j + 1
        elif c == '\x1b':
            # Skip non-CSI escape sequence
            i += 2
        else:
            plain.append(c)
            colors.append(is_colored)
            i += 1
    return ''.join(plain), colors


def mark(text, args, Mark, extra_cli_args, *a):
    try:
        ansi_text = subprocess.check_output(
            ['kitty', '@', 'get-text', '--ansi', '--extent', 'screen'],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        ansi_text = None

    if ansi_text is None:
        color_map = None
        search_text = text
    else:
        search_text, color_map = build_color_map(ansi_text)

    # Collect matches from both texts in parallel — same strings, same order
    text_matches = [m for m in HINT_PATTERN.finditer(text) if len(m.group()) >= 8]

    if color_map is None:
        search_matches = [None] * len(text_matches)
    else:
        search_matches = [m for m in HINT_PATTERN.finditer(search_text) if len(m.group()) >= 8]

    marks = []
    idx = 0
    for tm, sm in zip(text_matches, search_matches):
        match_text = tm.group()
        has_line_num = bool(LINE_NUM_RE.search(match_text))
        if not has_line_num and sm is not None:
            s, e = sm.start(), sm.end()
            # All chars must be colored
            if not (e <= len(color_map) and all(color_map[s:e])):
                continue
            # Color must start and end at exact match boundaries
            if s > 0 and color_map[s - 1]:
                continue
            if e < len(color_map) and color_map[e]:
                continue
        marks.append(Mark(idx, tm.start(), tm.end(), match_text, {}))
        idx += 1
    return marks

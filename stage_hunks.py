#!/usr/bin/env python3
"""Stage specific hunks (0-indexed) from a file's git diff.

Usage: stage_hunks.py <filename> <hunk_idx,...>
Example: stage_hunks.py backends/_sherpa_onnx.py 0
         stage_hunks.py backends/_pipeline.py 0,1,2
"""
import subprocess
import sys


def stage_hunks(filename, hunk_indices):
    result = subprocess.run(["git", "diff", filename], capture_output=True, text=True)
    diff = result.stdout
    if not diff:
        print(f"No diff for {filename}")
        return False

    lines = diff.splitlines(keepends=True)

    # Separate the file header (lines before first @@)
    header_lines = []
    i = 0
    while i < len(lines) and not lines[i].startswith("@@"):
        header_lines.append(lines[i])
        i += 1

    # Split into hunks
    hunks = []
    current = []
    while i < len(lines):
        if lines[i].startswith("@@") and current:
            hunks.append(current)
            current = []
        current.append(lines[i])
        i += 1
    if current:
        hunks.append(current)

    print(f"Total hunks in {filename}: {len(hunks)}")
    selected = [hunks[idx] for idx in hunk_indices if idx < len(hunks)]
    if not selected:
        print(f"No hunks selected for {filename}")
        return False

    patch = "".join(header_lines) + "".join("".join(h) for h in selected)

    proc = subprocess.run(
        ["git", "apply", "--cached"],
        input=patch, text=True, capture_output=True,
    )
    if proc.returncode != 0:
        print(f"Error staging {filename} hunks {hunk_indices}:\n{proc.stderr}")
        return False
    print(f"Staged hunks {hunk_indices} from {filename}")
    return True


if __name__ == "__main__":
    fname = sys.argv[1]
    indices = [int(x) for x in sys.argv[2].split(",")]
    ok = stage_hunks(fname, indices)
    sys.exit(0 if ok else 1)

import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DIRECTORY = Path(__file__).parent


def load_sync_fork():
    loader = importlib.machinery.SourceFileLoader('sync_fork', str(DIRECTORY / 'sync_fork'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_release_branches_are_checked_before_any_push(monkeypatch):
    sync = load_sync_fork()
    calls = []

    def git(*args, **kwargs):
        calls.append(args)
        if args[:2] == ('config', '--get'):
            value = {'sync.upstreamRepo': 'upstream', 'sync.releaseBranches': 'one two'}[args[2]]
        elif args[0] == 'rev-parse':
            value = 'local'
        elif args[0] == 'ls-remote':
            value = ('local' if args[-1].endswith('/one') else 'different') + '\t' + args[-1]
        else:
            raise AssertionError(args)
        return SimpleNamespace(returncode=0, stdout=value, check_returncode=lambda: None)

    monkeypatch.setattr(sync, 'git', git)
    monkeypatch.setattr(sys, 'argv', ['sync_fork'])
    with pytest.raises(SystemExit) as exc:
        sync.main()
    assert exc.value.code == 3
    assert not any(call[0] == 'push' for call in calls)


def test_release_push_uses_verified_commit(monkeypatch):
    sync = load_sync_fork()
    calls = []

    def git(*args, **kwargs):
        calls.append(args)
        if args[:2] == ('config', '--get'):
            value = {'sync.upstreamRepo': 'upstream', 'sync.releaseBranches': 'release'}[args[2]]
        elif args[0] == 'rev-parse':
            value = 'verified'
        elif args[0] == 'ls-remote':
            value = 'verified\trefs/heads/release\n'
        else:
            value = ''
        return SimpleNamespace(returncode=0, stdout=value, check_returncode=lambda: None)

    monkeypatch.setattr(sync, 'git', git)
    monkeypatch.setattr(sys, 'argv', ['sync_fork'])
    sync.main()
    assert ('push', '-f', 'origin', 'verified:refs/heads/release') in calls


def test_root_mapping_matches_descendants_and_nested_rule_wins(tmp_path):
    source = (DIRECTORY / 'idea').read_text().split('\npaths, line, column = parse_args', 1)[0]
    namespace = {}
    exec(compile(source, str(DIRECTORY / 'idea'), 'exec'), namespace)  # noqa: S102
    root_project = tmp_path / 'root_project'
    nested_project = tmp_path / 'nested_project'
    root_project.mkdir()
    nested_project.mkdir()
    namespace['MAPPED_PROJECTS'] = {'/': str(root_project), '/nested': str(nested_project)}
    assert namespace['mapped_project']('/elsewhere/child') == str(root_project)
    assert namespace['mapped_project']('/nested/child') == str(nested_project)
    assert namespace['mapped_project']('/nested-other') == str(root_project)

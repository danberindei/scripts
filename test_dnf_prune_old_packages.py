import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).with_name('dnf-prune-old-packages')
LOADER = importlib.machinery.SourceFileLoader('dnf_prune_old_packages', str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
prune = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = prune
LOADER.exec_module(prune)


def header(version, release='1', epoch=None, name='example', arch='aarch64'):
    return dict(name=name, arch=arch, epoch=epoch, version=version, release=release)


class VersionTests(unittest.TestCase):
    def test_rpm_ordering(self):
        cases = [
            (header('1.9'), header('1.10'), True),
            (header('1.10'), header('1.10'), False),
            (header('1.11'), header('1.10'), False),
            (header('1.10', release='1'), header('1.10', release='2'), True),
            (header('99'), header('1', epoch=1), True),
            (header('1', epoch=1), header('99'), False),
            (header('2.0~rc1'), header('2.0'), True),
            (header('2.0^git1'), header('2.0'), False),
            (header('1', arch='x86_64'), header('2'), False),
            (header('1', name='absent'), header('2'), False),
        ]
        for cached, installed, expected in cases:
            with self.subTest(cached=cached, installed=installed):
                versions = prune.newest_versions([installed])
                self.assertEqual(prune.older_than_reference(cached, versions), expected)

    def test_multiple_installed_versions_use_newest_for_each_architecture(self):
        installed = prune.newest_versions([
            header('3'), header('2'), header('1'), header('1', arch='x86_64')])
        self.assertTrue(prune.older_than_reference(header('2'), installed))
        self.assertFalse(prune.older_than_reference(header('3'), installed))
        self.assertFalse(prune.older_than_reference(header('2', arch='x86_64'), installed))


class CacheTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.cache = self.root / 'cache'
        self.cache.mkdir()
        self.old = self.cache / 'old.rpm'
        self.old.write_bytes(b'old RPM')
        self.installed = prune.newest_versions([header('2')])

    def scan(self):
        return prune.find_candidates(None, self.installed, [self.cache])

    def test_preview_and_apply_preserve_other_files_and_symlinks(self):
        current = self.cache / 'current.rpm'
        current.write_bytes(b'current RPM')
        metadata = self.cache / 'repomd.xml'
        metadata.write_text('metadata')
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'outside.rpm').write_bytes(b'outside RPM')
        (self.cache / 'linked-dir').symlink_to(outside, target_is_directory=True)
        (self.cache / 'linked.rpm').symlink_to(outside / 'outside.rpm')
        with patch.object(prune, 'read_header', side_effect=lambda ts, path:
                          header('1' if path == self.old else '2')):
            candidates = self.scan()
        self.assertEqual([candidate.path for candidate in candidates], [self.old])
        self.assertTrue(self.old.exists())
        prune.remove_candidates(candidates)
        self.assertFalse(self.old.exists())
        self.assertTrue(current.exists())
        self.assertTrue(metadata.exists())
        self.assertTrue((outside / 'outside.rpm').exists())
        self.assertTrue((self.cache / 'linked.rpm').is_symlink())

    def test_corrupt_rpm_aborts_without_removing_anything(self):
        (self.cache / 'z-corrupt.rpm').write_bytes(b'corrupt RPM')
        with patch.object(prune, 'read_header', side_effect=[header('1'),
                          prune.rpm.error('invalid RPM')]):
            with self.assertRaisesRegex(ValueError, 'z-corrupt.rpm'):
                self.scan()
        self.assertTrue(self.old.exists())

    def test_removed_package_keeps_newest_across_caches_and_architectures(self):
        second_cache = self.root / 'second-cache'
        second_cache.mkdir()
        headers = {
            self.old: header('1.9', name='removed'),
            self.cache / 'newest.rpm': header('1.10', name='removed'),
            second_cache / 'duplicate.rpm': header('1.10', name='removed'),
            self.cache / 'other-arch.rpm': header('1.8', name='removed', arch='x86_64'),
            self.cache / 'single.rpm': header('1', name='single'),
            self.cache / 'epoch-old.rpm': header('99', name='epoch'),
            second_cache / 'epoch-new.rpm': header('1', epoch=1, name='epoch'),
        }
        for path in headers:
            path.write_bytes(b'cached RPM')
        with patch.object(prune, 'read_header', side_effect=lambda ts, path: headers[path]):
            candidates = prune.find_candidates(None, self.installed,
                                               [self.cache, second_cache])
        expected = {self.old, self.cache / 'epoch-old.rpm'}
        self.assertEqual({candidate.path for candidate in candidates}, expected)
        self.assertTrue(all(path.exists() for path in headers))
        prune.remove_candidates(candidates)
        for path in headers:
            self.assertEqual(path.exists(), path not in expected)

    def test_installed_version_takes_precedence_over_newest_cached(self):
        headers = {
            self.old: header('1'),
            self.cache / 'current.rpm': header('2'),
            self.cache / 'newer.rpm': header('3'),
        }
        for path in headers:
            path.write_bytes(b'cached RPM')
        with patch.object(prune, 'read_header', side_effect=lambda ts, path: headers[path]):
            candidates = self.scan()
        self.assertEqual([candidate.path for candidate in candidates], [self.old])

    def test_changed_candidate_aborts_before_any_deletion(self):
        other = self.cache / 'other.rpm'
        other.write_bytes(b'old RPM')
        candidates = [prune.Candidate(path, path.lstat()) for path in (self.old, other)]
        other.write_bytes(b'replaced RPM')
        with self.assertRaisesRegex(ValueError, 'changed during inspection'):
            prune.remove_candidates(candidates)
        self.assertTrue(self.old.exists())
        self.assertTrue(other.exists())

    def test_missing_cache_is_ignored(self):
        self.assertEqual(prune.find_candidates(None, {}, [self.root / 'absent']), [])

    def test_unreadable_directory_aborts(self):
        with patch.object(prune.os, 'walk', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                self.scan()

    def test_main_defaults_to_preview(self):
        candidate = prune.Candidate(self.old, self.old.lstat())
        with patch.object(prune, 'find_candidates', return_value=[candidate]), \
                patch.object(prune, 'newest_versions', return_value=self.installed), \
                patch('sys.stdout'), patch('sys.stderr'):
            self.assertEqual(prune.main([]), 0)
        self.assertTrue(self.old.exists())
        with patch.object(prune, 'find_candidates', return_value=[candidate]), \
                patch.object(prune, 'newest_versions', return_value=self.installed), \
                patch('sys.stdout'), patch('sys.stderr'):
            self.assertEqual(prune.main(['--apply']), 0)
        self.assertFalse(self.old.exists())


if __name__ == '__main__':
    unittest.main()

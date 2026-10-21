import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name('extrase_cont.sh')


class ExtraseContTests(unittest.TestCase):
    def test_extraction_failure_does_not_prevent_later_statement_rename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = root / 'commands'
            commands.mkdir()
            extractor = commands / 'pdftotext'
            extractor.write_text('''#!/bin/bash
case "$1" in
  ./a-corrupt.pdf)
    printf 'Partial output\n'
    exit 1
    ;;
  ./b-unrelated.pdf)
    printf 'Unrelated document\n'
    ;;
  *)
    printf 'Wise Europe SA\n'
    ;;
esac
''')
            extractor.chmod(0o755)
            corrupt = root / 'a-corrupt.pdf'
            unrelated = root / 'b-unrelated.pdf'
            statement = root / 'statement_123_EUR_2026-09-01_2026-09-30.pdf'
            for path in (corrupt, unrelated, statement):
                path.write_bytes(b'fixture')
            result = subprocess.run(['bash', str(SCRIPT)], cwd=root, text=True,
                                    capture_output=True, timeout=15,
                                    env=dict(os.environ, PATH=f'{commands}:{os.environ["PATH"]}'))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Cannot extract PDF text: ./a-corrupt.pdf', result.stderr)
            self.assertIn('Unrecognized statement: ./b-unrelated.pdf', result.stderr)
            self.assertTrue(corrupt.exists())
            self.assertTrue(unrelated.exists())
            self.assertFalse(statement.exists())
            self.assertEqual((root / 'WISE_EUR_123_2026-09.pdf').read_bytes(), b'fixture')


if __name__ == '__main__':
    unittest.main()

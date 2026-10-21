import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name('podman-prune-old-images')


class PodmanPruneOldImagesTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.state = self.root / 'images.json'
        self.events = self.root / 'events.json'
        self.calls = self.root / 'calls.jsonl'
        self.events.write_text('')
        self.calls.write_text('')
        self.env = dict(os.environ, PATH=f'{self.root}:{os.environ["PATH"]}',
                        PRUNE_FIXTURE=str(self.root), EVENT_STATUS='0')
        self.write_command('podman', '''
import json
import os
import sys
from pathlib import Path

root = Path(os.environ['PRUNE_FIXTURE'])
args = sys.argv[1:]
with (root / 'calls.jsonl').open('a') as output:
    output.write(json.dumps(args) + '\\n')
state = root / 'images.json'
images = json.loads(state.read_text())
if args[0] == 'images':
    if '-f' in args:
        for image in images:
            if not image['Names']:
                print(image['Id'])
    else:
        print(json.dumps(images))
elif args[0] == 'ps':
    for image_id in json.loads(os.environ.get('CONTAINER_IMAGES', '[]')):
        print(image_id)
elif args[0] == 'rmi':
    ref = args[1]
    matches = [image for image in images if ref in image['Names']]
    if len(matches) != 1:
        sys.exit('Reference does not exist: ' + ref)
    image = matches[0]
    image['Names'].remove(ref)
    if not image['Names']:
        images.remove(image)
    state.write_text(json.dumps(images))
elif args == ['image', 'prune', '--force']:
    state.write_text(json.dumps([image for image in images if image['Names']]))
else:
    sys.exit('Unexpected podman arguments: ' + repr(args))
''')
        self.write_command('journalctl', '''
import os
import sys
from pathlib import Path

if '--list-boots' in sys.argv:
    print('[{"first_entry": 1000000}]')
else:
    print((Path(os.environ['PRUNE_FIXTURE']) / 'events.json').read_text(), end='')
    sys.exit(int(os.environ['EVENT_STATUS']))
''')

    def write_command(self, name, source):
        path = self.root / name
        path.write_text('#!/usr/bin/env python3\n' + source)
        path.chmod(0o755)

    def image(self, number, names, days=180):
        created = int(time.time()) - days * 86400
        return dict(Id=f'{number:064x}', Names=names, Created=created,
                    CreatedAt='2026-01-01', Size=1024)

    def run_script(self, images, apply=True):
        self.state.write_text(json.dumps(images))
        self.calls.write_text('')
        return subprocess.run(['bash', str(SCRIPT)] + (['--apply'] if apply else []),
                              env=self.env, text=True, capture_output=True, timeout=15)

    def mutations(self):
        return [args for args in map(json.loads, self.calls.read_text().splitlines())
                if args[0] in ('rmi', 'image')]

    def test_event_query_failure_aborts_before_any_removal(self):
        images = [self.image(1, ['one:v1']), self.image(2, ['one:v2'], days=1)]
        for output, status in [('', '1'), ('{"PODMAN_IMAGE":"one:v1",'
                                         '"__REALTIME_TIMESTAMP":"2000000"}\n', '1'),
                               ('invalid json\n', '0')]:
            with self.subTest(output=output, status=status):
                self.events.write_text(output)
                self.env['EVENT_STATUS'] = status
                result = self.run_script(images)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Cannot query container-create events', result.stderr)
                self.assertEqual(self.mutations(), [])
                self.assertEqual(json.loads(self.state.read_text()), images)

    def test_usage_under_removed_alias_protects_image(self):
        images = [self.image(1, ['one:v1', 'two:latest']),
                  self.image(2, ['one:v2'], days=1)]
        self.events.write_text(json.dumps(dict(PODMAN_IMAGE='one:v1',
                                              __REALTIME_TIMESTAMP='2000000')) + '\n')
        for apply in (False, True):
            with self.subTest(apply=apply):
                result = self.run_script(images, apply=apply)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('0 aged image(s)', result.stdout)
                remaining = json.loads(self.state.read_text())
                self.assertIn('two:latest', remaining[0]['Names'])
                removals = [args for args in self.mutations() if args[0] == 'rmi']
                self.assertEqual(removals, [['rmi', 'one:v1']] if apply else [])

    def test_age_candidate_removes_all_aliases_and_counts_one_image(self):
        images = [self.image(1, ['one:v1', 'two:latest'])]
        result = self.run_script(images, apply=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('one:v1,two:latest', result.stdout)
        self.assertIn('1 aged image(s)', result.stdout)
        self.assertEqual(self.mutations(), [])

        result = self.run_script(images)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.state.read_text()), [])
        self.assertIn('1 aged image(s)', result.stdout)
        self.assertEqual([args for args in self.mutations() if args[0] == 'rmi'],
                         [['rmi', 'one:v1'], ['rmi', 'two:latest']])

    def test_used_or_recent_images_remain(self):
        images = [self.image(1, ['one:latest']), self.image(2, ['two:latest']),
                  self.image(3, ['three:latest'], days=1)]
        self.events.write_text(json.dumps(dict(PODMAN_IMAGE='one:latest',
                                              __REALTIME_TIMESTAMP='2000000')) + '\n')
        self.env['CONTAINER_IMAGES'] = json.dumps([images[1]['Id']])
        result = self.run_script(images)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('0 aged image(s)', result.stdout)
        self.assertEqual(json.loads(self.state.read_text()), images)


if __name__ == '__main__':
    unittest.main()

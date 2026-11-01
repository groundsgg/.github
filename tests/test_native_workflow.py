import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


class NativeWorkflowTest(unittest.TestCase):
    def run_build(self, targets):
        workflow = Path(__file__).parents[1] / '.github/workflows/native-gradle-build-push.yml'
        steps = yaml.safe_load(workflow.read_text())['jobs']['native-build']['steps']
        script = next(s['run'] for s in steps if s.get('name') == 'Build native runtime targets')
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            docker = directory / 'docker'
            docker.write_text('#!' + sys.executable + '\nimport os,sys,json\nwith open(os.environ["DOCKER_CALLS"],"a") as f:f.write(json.dumps(sys.argv[1:])+"\\n")\n')
            docker.chmod(0o755)
            calls = directory / 'calls.jsonl'
            result = subprocess.run(['bash', '-euo', 'pipefail', '-c', script], capture_output=True, text=True,
                env={**os.environ, 'PATH': str(directory) + ':' + os.environ['PATH'], 'DOCKER_CALLS': str(calls),
                     'NATIVE_TARGETS': targets, 'GITHUB_ACTOR': 'actor', 'GITHUB_SHA': 'a' * 40,
                     'BUILD_SOURCE_SHA256': 'b' * 64, 'NATIVE_IMAGE_PREFIX': 'grounds/service-example',
                     'PACKAGES_TOKEN': 'never-put-this-in-an-argument'})
            records = [json.loads(l) for l in calls.read_text().splitlines()] if calls.exists() else []
            return result, records

    def test_native_targets_load_images_and_pass_credentials_only_as_a_secret(self):
        result, calls = self.run_build('native-micro native-distroless')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)
        for target, args in zip(['native-micro', 'native-distroless'], calls):
            self.assertIn('--load', args)
            self.assertNotIn('--push', args)
            self.assertEqual(args[args.index('--target') + 1], target)
            self.assertEqual(args[args.index('--secret') + 1], 'id=github_token,env=PACKAGES_TOKEN')
            self.assertNotIn('never-put-this-in-an-argument', ' '.join(args))
            self.assertIn('BUILD_COMMIT=' + 'a' * 40, args)

    def test_empty_or_unknown_target_fails_without_executing_docker(self):
        for target in ['', 'native-micro;echo-injected']:
            result, calls = self.run_build(target)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()

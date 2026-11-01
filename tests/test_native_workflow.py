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
            docker.write_text('#!' + sys.executable + '\nimport os,sys,json\na=sys.argv[1:];a.append(json.load(open(a[a.index("--file")+1])))\nwith open(os.environ["DOCKER_CALLS"],"a") as f:f.write(json.dumps(a)+"\\n")\n')
            docker.chmod(0o755)
            calls = directory / 'calls.jsonl'
            result = subprocess.run(['bash', '-euo', 'pipefail', '-c', script], capture_output=True, text=True,
                env={**os.environ, 'PATH': str(directory) + ':' + os.environ['PATH'], 'DOCKER_CALLS': str(calls),
                     'RUNNER_TEMP': tmp, 'NATIVE_TARGETS': targets, 'GITHUB_ACTOR': 'actor', 'GITHUB_SHA': 'a' * 40,
                     'BUILD_SOURCE_SHA256': 'b' * 64, 'NATIVE_IMAGE_PREFIX': 'grounds/service-example',
                     'PACKAGES_TOKEN': 'never-put-this-in-an-argument'})
            records = [json.loads(l) for l in calls.read_text().splitlines()] if calls.exists() else []
            return result, records

    def test_native_targets_load_images_and_pass_credentials_only_as_a_secret(self):
        result, calls = self.run_build('native-micro native-distroless')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 1, 'Both targets must share one BuildKit solve')
        args = calls[0]
        self.assertIn('--load', args)
        self.assertNotIn('--push', args)
        self.assertEqual(args[:2], ['buildx', 'bake'])
        config = args[-1]
        for target in ['native-micro', 'native-distroless']:
            options = config['target'][target]
            self.assertEqual(options['target'], target)
            self.assertEqual(options['secret'], ['id=github_token,env=PACKAGES_TOKEN'])
            self.assertEqual(options['args']['BUILD_COMMIT'], 'a' * 40)
        self.assertNotIn('never-put-this-in-an-argument', json.dumps(calls))

    def test_empty_or_unknown_target_fails_without_executing_docker(self):
        for target in ['', 'native-micro;echo-injected']:
            result, calls = self.run_build(target)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, [])

    def test_runtime_hook_receives_file_credentials_and_always_removes_them(self):
        workflow = Path(__file__).parents[1] / '.github/workflows/native-gradle-build-push.yml'
        steps = yaml.safe_load(workflow.read_text())['jobs']['native-build']['steps']
        script = next(s['run'] for s in steps if s.get('name') == 'Packaged-image contracts')
        for exit_code in [0, 17]:
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                wrapper = root / 'gradlew'
                wrapper.write_text("#!/bin/sh\n" + sys.executable + " - <<'PYCHILD'\n" +
                    "import os,pathlib,sys\np=pathlib.Path(os.environ['GRADLE_USER_HOME'])/'gradle.properties'\n" +
                    "values=dict(line.split('=',1) for line in p.read_text().splitlines())\n" +
                    "assert values=={'github.user':'actor','github.token':'test-secret','org.gradle.jvmargs':'-Xmx4g -XX:MaxMetaspaceSize=1g'}\n" +
                    "assert p.stat().st_mode & 0o077 == 0\n" +
                    "sys.exit(" + str(exit_code) + ")\nPYCHILD\n")
                wrapper.chmod(0o755)
                result = subprocess.run(['bash','-euo','pipefail','-c',script],cwd=root,capture_output=True,text=True,
                    env={**os.environ,'GRADLE_USER_HOME':str(root/'gradle-home'),'GITHUB_ACTOR':'actor',
                         'PACKAGES_TOKEN':'test-secret','VERIFY_COMMAND':'./gradlew runtimeTest'})
                self.assertEqual(result.returncode,exit_code,result.stderr)
                self.assertFalse((root/'gradle-home/gradle.properties').exists())
                self.assertNotIn('test-secret',result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()

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

    def run_publish(self, ref, targets='native-micro native-distroless', alias_prefix=''):
        workflow = Path(__file__).parents[1] / '.github/workflows/native-gradle-build-push.yml'
        steps = yaml.safe_load(workflow.read_text())['jobs']['native-build']['steps']
        step = next(s for s in steps if s.get('name') == 'Publish verified native images')
        self.assertEqual(step['if'], "github.event_name != 'pull_request'")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docker = root / 'docker'
            docker.write_text('#!' + sys.executable + "\nimport sys,os,json\nargs=sys.argv[1:]\nstdin=sys.stdin.read() if args[0]=='login' else ''\nwith open(os.environ['DOCKER_CALLS'],'a') as f:f.write(json.dumps({'args':args,'stdin':stdin})+'\\n')\n")
            docker.chmod(0o755)
            calls = root / 'calls'
            result = subprocess.run(['bash', '-euo', 'pipefail', '-c', step['run']], capture_output=True, text=True,
                env={**os.environ, 'PATH': str(root) + ':' + os.environ['PATH'], 'DOCKER_CALLS': str(calls),
                     'GITHUB_REF': ref, 'GITHUB_SHA': 'a' * 40, 'GITHUB_ACTOR': 'actor',
                     'GITHUB_REPOSITORY': 'groundsgg/service-example', 'NATIVE_TARGETS': targets,
                     'NATIVE_IMAGE_PREFIX': 'grounds/service-example', 'REGISTRY_TOKEN': 'fixture-token',
                     'NATIVE_ALIAS_PREFIX': alias_prefix})
            records = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
            return result, records

    def assert_publish_aliases(self, ref, standard, alias_prefix=''):
        result, calls = self.run_publish(ref, alias_prefix=alias_prefix)
        self.assertEqual(result.returncode, 0, result.stderr)
        repo = 'ghcr.io/groundsgg/service-example:'
        sha = 'a' * 40
        expected = {repo + 'native-micro-sha-' + sha, repo + 'native-sha-' + sha,
                    repo + 'native-distroless-sha-' + sha} | {repo + tag for tag in standard}
        tag_calls = [call['args'] for call in calls if call['args'][0] == 'tag']
        push_calls = [call['args'][1] for call in calls if call['args'][0] == 'push']
        self.assertEqual({call[2] for call in tag_calls}, expected)
        self.assertEqual(set(push_calls), expected)
        for call in tag_calls:
            expected_source = 'grounds/service-example:native-distroless-pilot' if 'native-distroless-sha-' in call[2] else 'grounds/service-example:native-micro-pilot'
            self.assertEqual(call[1], expected_source)
        login = next(call for call in calls if call['args'][0] == 'login')
        self.assertIn('--password-stdin', login['args'])
        self.assertEqual(login['stdin'], 'fixture-token')
        self.assertNotIn('fixture-token', json.dumps([call['args'] for call in calls]))
        self.assertFalse(any(call['args'][0] in ('build', 'buildx') for call in calls))

    def test_publication_aliases_use_the_verified_micro_image(self):
        for ref, aliases in [('refs/heads/main', {'edge', 'sha-aaaaaaa'}),
                             ('refs/tags/v1.2.3', {'1.2.3', 'latest'}),
                             ('refs/tags/v1.2.3-rc.1', {'1.2.3-rc.1'}),
                             ('refs/heads/feature/test', set())]:
            with self.subTest(ref=ref):
                self.assert_publish_aliases(ref, aliases)

    def test_invalid_release_versions_fail_before_docker_login_or_push(self):
        for ref in ['refs/tags/v1.2', 'refs/tags/v01.2.3', 'refs/tags/v1.2.3-01',
                    'refs/tags/v1.2.3+metadata', 'refs/tags/v1.2.3;malicious']:
            with self.subTest(ref=ref):
                result, calls = self.run_publish(ref)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])

    def test_separate_native_aliases_preserve_existing_jvm_release_tags(self):
        for ref, aliases in [('refs/heads/main', {'native-edge', 'native-sha-aaaaaaa'}),
                             ('refs/tags/v1.2.3', {'native-1.2.3', 'native-latest'}),
                             ('refs/tags/v1.2.3-rc.1', {'native-1.2.3-rc.1'}),
                             ('refs/heads/feature/test', set())]:
            with self.subTest(ref=ref):
                self.assert_publish_aliases(ref, aliases, alias_prefix='native-')

    def test_invalid_alias_prefix_fails_before_registry_access(self):
        for prefix in ['../', '-bad', 'bad space', 'bad;command', 'A' * 33]:
            with self.subTest(prefix=prefix):
                result, calls = self.run_publish('refs/tags/v1.2.3', alias_prefix=prefix)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])

    def test_prefixed_release_tag_length_is_validated_before_registry_access(self):
        result, calls = self.run_publish('refs/tags/v1.2.3-' + 'x' * 118, alias_prefix='native-')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_standard_aliases_require_a_verified_micro_target(self):
        result, calls = self.run_publish('refs/heads/main', 'native-distroless')
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

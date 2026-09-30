import re
import unittest
from pathlib import Path

import yaml


WORKFLOW = Path(__file__).parents[1] / '.github/workflows/docker-gradle-build-push.yml'


def resolve(value, context):
    if not isinstance(value, str):
        return value
    def expression(match):
        source = match.group(1).strip()
        source = re.sub(r'\b(?:github|inputs|steps|env|runner)\.[\w.]+', lambda field: repr(context[field[0]]), source)
        # GitHub's format('{0}', x); evaluated as Python's str.format.
        source = re.sub(r'\bformat\(', 'str.format(', source)
        source = source.replace('&&', ' and ').replace('||', ' or ')
        return str(eval('(' + source + ')', {'__builtins__': {}, 'str': str}, {}))
    return re.sub(r'\$\{\{(.*?)\}\}', expression, value, flags=re.DOTALL)


class DockerWorkflowTest(unittest.TestCase):
    def test_preview_builder_retains_signing_and_pr_isolated_cache(self):
        workflow = yaml.safe_load((WORKFLOW.parent / 'platform-test-preview.yml').read_text())
        build = workflow['jobs']['build']
        steps = build['steps']
        self.assertFalse(any('useblacksmith/' in step.get('uses', '') for step in steps))
        builder_index = next(i for i, step in enumerate(steps) if 'setup-buildx-action' in step.get('uses', ''))
        auth_index = next(i for i, step in enumerate(steps) if step.get('name') == 'Prepare Docker auth config')
        self.assertLess(auth_index, builder_index, 'DOCKER_CONFIG relocation must precede builder setup')
        image = next(step for step in steps if step.get('id') == 'build')
        self.assertIn('docker/build-push-action', image['uses'])
        self.assertTrue(image['with']['push'])
        self.assertEqual(image['with']['platforms'], 'linux/amd64')
        context = {'github.repository': 'groundsgg/plugin-social', 'github.event.pull_request.number': 123}
        self.assertEqual(resolve(image['with']['cache-to'], context), 'type=gha,scope=groundsgg/plugin-social-preview-123-amd64,mode=max')
        signing = next(step for step in steps if step.get('name') == 'Sign image')
        self.assertIn('steps.build.outputs.digest', signing['run'])
        self.assertEqual(build['if'], "github.event.action != 'closed'")

    def test_build_and_cache_contract_for_public_and_private_events(self):
        job = yaml.safe_load(WORKFLOW.read_text())['jobs']['docker-build-push']
        for visibility in ['public', 'private']:
            for event in ['pull_request', 'push']:
                with self.subTest(visibility=visibility, event=event):
                    context = {
                        'github.event.repository.visibility': visibility,
                        'github.event.repository.name': 'plugin-notifications',
                        'github.event_name': event,
                        'github.repository': 'groundsgg/plugin-notifications',
                        'inputs.runner': '',
                    }
                    active = [step for step in job['steps'] if resolve('${{ ' + step['if'] + ' }}' if 'if' in step else True, context) not in ['False', False]]
                    builders = [step for step in active if 'setup-buildx-action' in step.get('uses', '')]
                    self.assertEqual(len(builders), 1, 'every event needs a local Buildx builder')
                    self.assertFalse(any('useblacksmith/' in step.get('uses', '') for step in active))
                    builds = [step for step in active if 'build-push-action' in step.get('uses', '')]
                    self.assertTrue(builds)
                    for step in builds:
                        options = step['with']
                        self.assertEqual(options['platforms'], 'linux/amd64')
                        self.assertIn('github_token=', options['secrets'])
                        # Where the cache lives is decided at run time by "Resolve layer cache".
                        self.assertEqual(options['cache-from'], '${{ steps.layer_cache.outputs.from }}')
                    pushes = [step for step in builds if step['with'].get('push') is True]
                    cache_writes = [step for step in builds if step['with'].get('cache-to')]
                    if event == 'pull_request':
                        self.assertEqual(pushes, [])
                        self.assertEqual(cache_writes, [])
                        self.assertTrue(any(step['with'].get('load') for step in builds))
                    else:
                        self.assertEqual(len(pushes), 1)
                        self.assertEqual(len(cache_writes), 1)
                        self.assertEqual(cache_writes[0]['with']['cache-to'], '${{ steps.layer_cache.outputs.to }}')
                    expected_runner = 'ubuntu-24.04' if visibility == 'public' else 'grounds-runners'
                    self.assertEqual(resolve(job['runs-on'], context).strip(), expected_runner)
                    expected_budget = 30 if visibility == 'public' else 60
                    self.assertEqual(int(resolve(job['timeout-minutes'], context)), expected_budget)

    def run_layer_cache(self, **env):
        """Run the "Resolve layer cache" script the way the runner would and return its outputs."""
        import os
        import subprocess
        import tempfile
        job = yaml.safe_load(WORKFLOW.read_text())['jobs']['docker-build-push']
        script = next(step for step in job['steps'] if step.get('id') == 'layer_cache')['run']
        with tempfile.NamedTemporaryFile('r', suffix='.out') as output:
            base = {'PATH': os.environ['PATH'], 'GITHUB_OUTPUT': output.name,
                    'GITHUB_REPOSITORY': 'groundsgg/plugin-match'}
            subprocess.run(['bash', '-c', script], env={**base, **env}, check=True, capture_output=True)
            text = output.read()
        outputs, lines = {}, iter(text.splitlines())
        for line in lines:
            if '<<' in line:
                key, marker = line.split('<<', 1)
                body = []
                for inner in lines:
                    if inner == marker:
                        break
                    body.append(inner)
                outputs[key] = '\n'.join(body).strip()
            else:
                key, _, value = line.partition('=')
                outputs[key] = value
        return outputs

    def test_layer_cache_is_gha_on_hosted_runners(self):
        out = self.run_layer_cache(RUNNER_ENVIRONMENT='github-hosted', BUILDKIT_CACHE_REGISTRY='ignored:5000')
        self.assertEqual(out['from'], 'type=gha,scope=groundsgg/plugin-match-amd64')
        self.assertEqual(out['to'], 'type=gha,scope=groundsgg/plugin-match-amd64,mode=max')
        self.assertEqual(out['buildkitd-config'], '')

    def test_layer_cache_uses_the_registry_a_self_hosted_runner_advertises(self):
        registry = 'build-cache-registry.arc-runners.svc.cluster.local:5000'
        out = self.run_layer_cache(RUNNER_ENVIRONMENT='self-hosted', BUILDKIT_CACHE_REGISTRY=registry)
        ref = registry + '/cache/plugin-match:amd64'
        self.assertEqual(out['from'], 'type=registry,ref=' + ref)
        self.assertEqual(out['to'], 'type=registry,ref=' + ref + ',mode=max,ignore-error=true')
        # BuildKit must be told the registry is plain HTTP, or every cache call fails TLS.
        self.assertIn('[registry."' + registry + '"]', out['buildkitd-config'])
        self.assertIn('http = true', out['buildkitd-config'])

    def test_no_layer_cache_on_a_self_hosted_runner_without_a_registry(self):
        out = self.run_layer_cache(RUNNER_ENVIRONMENT='self-hosted')
        self.assertEqual((out['from'], out['to'], out['buildkitd-config']), ('', '', ''))

    def test_cold_arc_budget_preserves_hosted_override_and_fallback_limits(self):
        job = yaml.safe_load(WORKFLOW.read_text())['jobs']['docker-build-push']
        cases = [
            ('private', '', 'service-moderation', 60),
            ('internal', '', 'service-moderation', 60),
            ('public', '', 'service-moderation', 30),
            ('', '', '', 30),
            ('', '', 'service-moderation', 60),
            ('private', 'ubuntu-24.04', 'service-moderation', 30),
            ('private', 'custom-amd64', 'service-moderation', 30),
            ('public', 'custom-amd64', 'service-moderation', 30),
        ]
        for visibility, runner, name, expected in cases:
            with self.subTest(visibility=visibility, runner=runner, name=name):
                context = {
                    'inputs.runner': runner,
                    'github.event.repository.visibility': visibility,
                    'github.event.repository.name': name,
                }
                budget = int(resolve(job['timeout-minutes'], context))
                self.assertEqual(budget, expected)
                self.assertLessEqual(budget, 60)

    def test_every_central_workflow_routes_private_repos_to_the_shared_pool(self):
        """Public -> GitHub-hosted, private -> grounds-runners, no payload -> hosted amd64.

        The last case matters: hosted arm64 does not exist for private repos, and a
        public repo sent to the self-hosted pool is refused by the org's runner group,
        so either wrong guess queues a job forever.
        """
        checked = 0
        for path in sorted(WORKFLOW.parent.glob('*.yml')):
            jobs = (yaml.safe_load(path.read_text()) or {}).get('jobs', {})
            for name, job in jobs.items():
                runs_on = job.get('runs-on')
                if not isinstance(runs_on, str) or 'grounds-runners' not in runs_on:
                    continue
                checked += 1
                base = {'inputs.runner': ''}
                with self.subTest(workflow=path.name, job=name):
                    private = resolve(runs_on, {**base, 'github.event.repository.visibility': 'private',
                                                'github.event.repository.name': 'plugin-match'}).strip()
                    self.assertEqual(private, 'grounds-runners')
                    public = resolve(runs_on, {**base, 'github.event.repository.visibility': 'public',
                                               'github.event.repository.name': 'service-maps'}).strip()
                    self.assertTrue(public.startswith('ubuntu-24.04'), public)
                    missing = resolve(runs_on, {**base, 'github.event.repository.visibility': '',
                                                'github.event.repository.name': ''}).strip()
                    self.assertEqual(missing, 'ubuntu-24.04')
        self.assertEqual(checked, 9, 'every repo-routed job should target the shared pool')

    def test_runner_override_and_missing_event_payload(self):
        job = yaml.safe_load(WORKFLOW.read_text())['jobs']['docker-build-push']
        context = {'inputs.runner': '', 'github.event.repository.visibility': '', 'github.event.repository.name': ''}
        self.assertEqual(resolve(job['runs-on'], context), 'ubuntu-24.04')
        context['inputs.runner'] = 'custom-amd64'
        self.assertEqual(resolve(job['runs-on'], context), 'custom-amd64')


if __name__ == '__main__':
    unittest.main()

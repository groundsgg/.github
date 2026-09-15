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
        source = re.sub(r'\b(?:github|inputs|steps|env)\.[\w.]+', lambda field: repr(context[field[0]]), source)
        source = source.replace('&&', ' and ').replace('||', ' or ')
        return str(eval('(' + source + ')', {'__builtins__': {}}, {}))
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
                        self.assertEqual(resolve(options['cache-from'], context), 'type=gha,scope=groundsgg/plugin-notifications-amd64')
                    pushes = [step for step in builds if step['with'].get('push') is True]
                    cache_writes = [step for step in builds if step['with'].get('cache-to')]
                    if event == 'pull_request':
                        self.assertEqual(pushes, [])
                        self.assertEqual(cache_writes, [])
                        self.assertTrue(any(step['with'].get('load') for step in builds))
                    else:
                        self.assertEqual(len(pushes), 1)
                        self.assertEqual(len(cache_writes), 1)
                        self.assertIn('mode=max', cache_writes[0]['with']['cache-to'])
                    expected_runner = 'ubuntu-24.04' if visibility == 'public' else 'plugin-notifications'
                    self.assertEqual(resolve(job['runs-on'], context).strip(), expected_runner)
                    expected_budget = 30 if visibility == 'public' else 60
                    self.assertEqual(int(resolve(job['timeout-minutes'], context)), expected_budget)

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

    def test_runner_override_and_missing_event_payload(self):
        job = yaml.safe_load(WORKFLOW.read_text())['jobs']['docker-build-push']
        context = {'inputs.runner': '', 'github.event.repository.visibility': '', 'github.event.repository.name': ''}
        self.assertEqual(resolve(job['runs-on'], context), 'ubuntu-24.04')
        context['inputs.runner'] = 'custom-amd64'
        self.assertEqual(resolve(job['runs-on'], context), 'custom-amd64')


if __name__ == '__main__':
    unittest.main()

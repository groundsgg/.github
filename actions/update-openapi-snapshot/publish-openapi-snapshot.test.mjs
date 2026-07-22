import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const workflowPath = new URL('../../.github/workflows/publish-openapi-snapshot.yml', import.meta.url)

test('publishing workflow exposes the fixed reusable contract', async () => {
  assert.equal(existsSync(workflowPath), true, 'reusable publishing workflow must exist')
  const workflow = await readFile(workflowPath, 'utf8')

  for (const input of [
    'artifact_name',
    'service_id',
    'service_title',
    'service_slug',
    'source_ref',
    'source_sha',
  ]) {
    assert.match(workflow, new RegExp(`\\n\\s{6}${input}:`))
  }
  assert.match(workflow, /app_private_key:[\s\S]*?required: true/)
  assert.match(workflow, /permissions:\n\s+contents: read/)
  assert.match(workflow, /group: openapi-snapshot-\$\{\{ inputs\.service_id \}\}/)
  assert.match(workflow, /github\.repository_owner == 'groundsgg'/)
})

test('publishing workflow restricts credentials and writes only through a stable PR', async () => {
  assert.equal(existsSync(workflowPath), true, 'reusable publishing workflow must exist')
  const workflow = await readFile(workflowPath, 'utf8')

  assert.match(workflow, /actions\/create-github-app-token@v3/)
  assert.match(workflow, /owner: groundsgg\n\s+repositories: api-reference/)
  assert.match(workflow, /permission-contents: write/)
  assert.match(workflow, /permission-pull-requests: write/)
  assert.match(workflow, /repository: groundsgg\/api-reference/)
  assert.match(workflow, /BRANCH_NAME: docs\/update-\$\{\{ inputs\.service_id \}\}-openapi/)
  assert.match(workflow, /git push --force-with-lease origin/)
  assert.match(workflow, /gh pr (create|edit)/)
  assert.doesNotMatch(workflow, /^\s+pull_request:/m)
  assert.doesNotMatch(workflow, /target_repository|target_path|personal access token/i)
})

test('publishing workflow validates the integrated API reference before git changes', async () => {
  assert.equal(existsSync(workflowPath), true, 'reusable publishing workflow must exist')
  const workflow = await readFile(workflowPath, 'utf8')

  assert.match(workflow, /actions\/download-artifact@v7/)
  assert.match(workflow, /actions\/checkout@v7/)
  assert.match(workflow, /actions\/setup-node@v6/)
  assert.match(workflow, /npm ci\n\s+npm run validate:specs\n\s+npm test\n\s+npm run build/)
  assert.match(workflow, /git status --porcelain/)
})

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const readmePath = new URL('../../README.md', import.meta.url)

test('README documents the publisher setup and least-privilege boundary', async () => {
  const readme = await readFile(readmePath, 'utf8')

  assert.match(readme, /grounds-openapi-publisher/)
  assert.match(readme, /groundsgg\/api-reference/)
  assert.match(readme, /OPENAPI_PUBLISHER_APP_ID/)
  assert.match(readme, /OPENAPI_PUBLISHER_PRIVATE_KEY/)
  assert.match(readme, /Contents[^\n]*Read and write/i)
  assert.match(readme, /Pull requests[^\n]*Read and write/i)
  assert.match(readme, /Webhooks[^\n]*None/i)
  assert.match(readme, /no PAT fallback/i)
})

test('README provides the complete reusable workflow caller contract', async () => {
  const readme = await readFile(readmePath, 'utf8')

  assert.match(
    readme,
    /uses: groundsgg\/\.github\/\.github\/workflows\/publish-openapi-snapshot\.yml@main/,
  )
  for (const value of [
    'artifact_name: openapi-snapshot',
    'service_id: service-moderation',
    'service_title: Moderation API',
    'service_slug: moderation',
    'app_private_key: ${{ secrets.OPENAPI_PUBLISHER_PRIVATE_KEY }}',
  ]) {
    assert.ok(readme.includes(value), `README must contain: ${value}`)
  }
  assert.match(readme, /same workflow run/i)
  assert.match(readme, /exactly `openapi\.json`/i)
})

test('README documents deterministic update and failure behavior', async () => {
  const readme = await readFile(readmePath, 'utf8')

  for (const behavior of [
    /missing artifact/i,
    /invalid specification or registry/i,
    /metadata conflict/i,
    /no changes/i,
    /existing pull request/i,
    /missing app installation or permission/i,
  ]) {
    assert.match(readme, behavior)
  }
})

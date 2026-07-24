import assert from 'node:assert/strict'
import { mkdtemp, mkdir, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import { updateOpenApiSnapshot } from './update-openapi-snapshot.mjs'

async function fixture({
  registry = { schemaVersion: 1, sources: [] },
  artifact = { openapi: '3.1.0', info: { title: 'Moderation API', version: '1.0.0' }, paths: {} },
  serviceId = 'service-moderation',
  serviceTitle = 'Moderation API',
  serviceSlug = 'moderation',
} = {}) {
  const root = await mkdtemp(join(tmpdir(), 'openapi-snapshot-'))
  const checkoutPath = join(root, 'api-reference')
  const artifactPath = join(root, 'openapi.json')
  await mkdir(join(checkoutPath, 'public', 'specs'), { recursive: true })
  if (registry !== null) {
    await writeFile(
      join(checkoutPath, 'public', 'specs', 'registry.json'),
      typeof registry === 'string' ? registry : `${JSON.stringify(registry, null, 2)}\n`,
    )
  }
  if (artifact !== null) {
    await writeFile(
      artifactPath,
      typeof artifact === 'string' ? artifact : `${JSON.stringify(artifact, null, 2)}\n`,
    )
  }
  return { artifactPath, checkoutPath, serviceId, serviceTitle, serviceSlug }
}

test('onboards the first source as default and copies the exact snapshot bytes', async () => {
  const input = await fixture()
  const artifactBytes = await readFile(input.artifactPath)

  const result = await updateOpenApiSnapshot(input)

  assert.equal(result.sourceAdded, true)
  assert.equal(result.snapshotPath, 'public/specs/service-moderation/openapi.json')
  const registry = JSON.parse(await readFile(join(input.checkoutPath, result.registryPath), 'utf8'))
  assert.deepEqual(registry.sources, [
    {
      id: 'service-moderation',
      title: 'Moderation API',
      slug: 'moderation',
      path: 'service-moderation/openapi.json',
      default: true,
    },
  ])
  assert.deepEqual(await readFile(join(input.checkoutPath, result.snapshotPath)), artifactBytes)
})

test('onboards later sources as non-default and sorts them by id', async () => {
  const input = await fixture({
    serviceId: 'service-chat',
    serviceTitle: 'Chat API',
    serviceSlug: 'chat',
    registry: {
      schemaVersion: 1,
      sources: [
        {
          id: 'service-zeta',
          title: 'Zeta API',
          slug: 'zeta',
          path: 'service-zeta/openapi.json',
          default: true,
        },
      ],
    },
  })

  await updateOpenApiSnapshot(input)

  const registry = JSON.parse(
    await readFile(join(input.checkoutPath, 'public/specs/registry.json'), 'utf8'),
  )
  assert.deepEqual(registry.sources.map(({ id }) => id), ['service-chat', 'service-zeta'])
  assert.equal(registry.sources[0].default, false)
})

test('updates only the exact snapshot bytes for an existing source', async () => {
  const source = {
    id: 'service-moderation',
    title: 'Moderation API',
    slug: 'moderation',
    path: 'service-moderation/openapi.json',
    default: true,
  }
  const input = await fixture({ registry: { schemaVersion: 1, sources: [source] } })
  const registryPath = join(input.checkoutPath, 'public/specs/registry.json')
  const registryBefore = await readFile(registryPath)

  const result = await updateOpenApiSnapshot(input)

  assert.equal(result.sourceAdded, false)
  assert.deepEqual(await readFile(registryPath), registryBefore)
})

test('rejects metadata drift for an existing source', async () => {
  const input = await fixture({
    registry: {
      schemaVersion: 1,
      sources: [
        {
          id: 'service-moderation',
          title: 'Another API',
          slug: 'moderation',
          path: 'service-moderation/openapi.json',
          default: true,
        },
      ],
    },
  })

  await assert.rejects(updateOpenApiSnapshot(input), /metadata/i)
})

for (const [name, overrides] of [
  ['invalid service id', { serviceId: '../escape' }],
  ['invalid service slug', { serviceSlug: 'Not Valid' }],
  ['missing artifact', { artifact: null }],
  ['invalid artifact JSON', { artifact: '{' }],
  ['non-OpenAPI artifact', { artifact: { openapi: '2.0', paths: {} } }],
  ['missing registry', { registry: null }],
  ['invalid registry JSON', { registry: '{' }],
]) {
  test(`rejects ${name}`, async () => {
    const input = await fixture(overrides)
    await assert.rejects(updateOpenApiSnapshot(input))
  })
}

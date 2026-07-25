import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { pathToFileURL } from 'node:url'

const identifierPattern = /^[a-z0-9]+(?:-[a-z0-9]+)*$/

export async function updateOpenApiSnapshot({
  artifactPath,
  checkoutPath,
  serviceId,
  serviceTitle,
  serviceSlug,
}) {
  validateIdentifier('service ID', serviceId)
  validateIdentifier('service slug', serviceSlug)
  if (typeof serviceTitle !== 'string' || serviceTitle.trim() === '') {
    throw new Error('Service title must not be empty')
  }

  const artifactBytes = await readFile(artifactPath)
  const artifact = parseJson(artifactBytes, 'OpenAPI artifact')
  if (typeof artifact?.openapi !== 'string' || !artifact.openapi.startsWith('3.')) {
    throw new Error('OpenAPI artifact must contain an OpenAPI 3.x document')
  }

  const registryPath = 'public/specs/registry.json'
  const absoluteRegistryPath = join(checkoutPath, registryPath)
  const registryBytes = await readFile(absoluteRegistryPath)
  const registry = parseJson(registryBytes, 'API source registry')
  validateRegistry(registry)

  const sourcePath = `${serviceId}/openapi.json`
  const snapshotPath = `public/specs/${sourcePath}`
  const existing = registry.sources.find(({ id }) => id === serviceId)
  let sourceAdded = false
  if (existing) {
    if (
      existing.title !== serviceTitle ||
      existing.slug !== serviceSlug ||
      existing.path !== sourcePath
    ) {
      throw new Error('Existing source metadata differs from the requested metadata')
    }
  } else {
    registry.sources.push({
      id: serviceId,
      title: serviceTitle,
      slug: serviceSlug,
      path: sourcePath,
      default: registry.sources.length === 0,
    })
    registry.sources.sort((left, right) => left.id.localeCompare(right.id))
    await writeFile(absoluteRegistryPath, `${JSON.stringify(registry, null, 2)}\n`)
    sourceAdded = true
  }

  const absoluteSnapshotPath = join(checkoutPath, snapshotPath)
  await mkdir(dirname(absoluteSnapshotPath), { recursive: true })
  await writeFile(absoluteSnapshotPath, artifactBytes)
  return { registryPath, snapshotPath, sourceAdded }
}

function validateIdentifier(label, value) {
  if (typeof value !== 'string' || !identifierPattern.test(value)) {
    throw new Error(`${label} must use lowercase kebab-case`)
  }
}

function parseJson(bytes, label) {
  try {
    return JSON.parse(bytes.toString('utf8'))
  } catch (error) {
    throw new Error(`${label} must be valid JSON`, { cause: error })
  }
}

function validateRegistry(registry) {
  if (registry?.schemaVersion !== 1 || !Array.isArray(registry.sources)) {
    throw new Error('API source registry must use schemaVersion 1 and contain sources')
  }
  const ids = new Set()
  for (const source of registry.sources) {
    if (
      !source ||
      typeof source.id !== 'string' ||
      typeof source.title !== 'string' ||
      typeof source.slug !== 'string' ||
      typeof source.path !== 'string' ||
      typeof source.default !== 'boolean' ||
      ids.has(source.id)
    ) {
      throw new Error('API source registry contains an invalid source')
    }
    ids.add(source.id)
  }
}

function parseArguments(values) {
  const argumentsByName = {}
  for (let index = 0; index < values.length; index += 2) {
    const name = values[index]
    const value = values[index + 1]
    if (!name?.startsWith('--') || value === undefined) {
      throw new Error('CLI arguments must be provided as --name value pairs')
    }
    argumentsByName[name.slice(2)] = value
  }
  return {
    artifactPath: argumentsByName['artifact-path'],
    checkoutPath: argumentsByName['checkout-path'],
    serviceId: argumentsByName['service-id'],
    serviceTitle: argumentsByName['service-title'],
    serviceSlug: argumentsByName['service-slug'],
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await updateOpenApiSnapshot(parseArguments(process.argv.slice(2)))
}

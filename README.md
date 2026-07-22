# .github

Organization-level .github repository which contains our issue templates, pull request templates, reusable workflows and more.

## OpenAPI snapshot publishing

The reusable `publish-openapi-snapshot.yml` workflow accepts a validated OpenAPI artifact from a Grounds service and opens or updates a reviewable pull request in `groundsgg/api-reference`. It never pushes to the target's `main` branch and has no PAT fallback.

The workflow derives the target path as `public/specs/<service-id>/openapi.json`. The first published source becomes the default source; later sources are non-default. Existing source metadata cannot be changed by a service publication.

### GitHub App setup

Create a dedicated GitHub App named `grounds-openapi-publisher` with this configuration:

| Setting | Value |
| --- | --- |
| Installation | Only `groundsgg/api-reference` |
| Repository Contents | Read and write |
| Pull requests | Read and write |
| Metadata | Read |
| Webhooks | None |

Expose the App ID as the organization variable `OPENAPI_PUBLISHER_APP_ID`. Store its private key as the organization secret `OPENAPI_PUBLISHER_PRIVATE_KEY` and grant that secret only to explicitly approved service repositories.

The workflow creates a short-lived token restricted to `groundsgg/api-reference` with only contents and pull-request write access. The App must not be installed on unrelated repositories, and the workflow does not support personal access tokens.

### Calling the workflow

The service must generate and upload an artifact in the same workflow run before calling the publisher. The artifact must contain exactly `openapi.json` at its root.

```yaml
jobs:
  publish-openapi:
    needs: export-openapi
    uses: groundsgg/.github/.github/workflows/publish-openapi-snapshot.yml@main
    with:
      artifact_name: openapi-snapshot
      service_id: service-moderation
      service_title: Moderation API
      service_slug: moderation
      source_ref: ${{ github.ref_name }}
      source_sha: ${{ github.sha }}
    secrets:
      app_private_key: ${{ secrets.OPENAPI_PUBLISHER_PRIVATE_KEY }}
```

The source workflow remains responsible for generating and validating its code-first contract. The reusable workflow downloads the artifact, updates a fixed target checkout, runs the complete `api-reference` validation and build, then writes to the stable `docs/update-<service-id>-openapi` branch. Repeated publications update the existing pull request.

### Failure behavior

| Situation | Result |
| --- | --- |
| Missing artifact | The workflow fails before target checkout changes. |
| Invalid specification or registry | Validation fails before a commit or push. |
| Metadata conflict | Publication fails and the metadata must be changed in a separate `api-reference` pull request. |
| No changes | The workflow succeeds without a commit or pull request update. |
| Existing pull request | The stable branch, title, and body are updated instead of opening a duplicate. |
| Missing App installation or permission | The workflow fails without a PAT fallback. |

Workflow logs must not print the App token or OpenAPI document. The generated pull request identifies the exact source repository, ref, and commit for review.

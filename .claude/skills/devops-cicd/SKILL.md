---
name: devops-cicd
description: >
  GitHub Actions CI/CD pipeline rules for ocpiconnector. Load for ANY task
  touching .github/workflows/, deployment pipelines, Docker builds, GCP
  Artifact Registry, Kustomize deploys, Sentry releases, or release tagging.
  Covers the exact job chain, auth pattern, and environment split used here.
---

# DevOps & CI/CD — ocpiconnector

## Pipelines overview

| Workflow | Triggers | Target |
|---|---|---|
| `deploy-staging-gke.yml` | push/PR to `develop`, push to feature branches | GKE staging namespace |
| `deploy-production-gke.yml` | push/PR to `main`, workflow_dispatch | GKE production namespace |

---

## Job chains

### Staging pipeline
```
lint → test → build-staging-gke → migrate-staging-gke → deploy-staging-gke
```
No release draft for staging. Image tag = `{branch-name}-{short-commit-hash}`.

### Production pipeline
```
lint → test → tag-and-release-draft → build-production-gke → migrate-production-gke → deploy-production-gke → publish-release
```
Release draft is created before the build. Image tag = semver from release-drafter (e.g. `v1.4.2`).

Build and deploy steps only run on `push` or `workflow_dispatch` — not on pull_request events.

---

## GCP authentication — OIDC (no long-lived keys)

```yaml
- uses: google-github-actions/auth@v2
  with:
    workload_identity_provider: ${{ secrets.GCP_WID_PROVIDER }}
    service_account: ${{ secrets.GCP_SERVICE_ACCOUNT }}
```

**Never** use `credentials_json` or service account key files. All GCP auth is via Workload Identity Federation.

Required permissions on the workflow job:
```yaml
permissions:
  id-token: write    # required for OIDC token exchange
  contents: write    # production only — for tagging/releasing
```

---

## Docker build

```yaml
- uses: docker/setup-buildx-action@v3

- name: Build and Push Image
  run: |
    docker buildx build \
      --platform linux/amd64 \
      --cache-from=type=gha,scope=gke-{staging|production}-build \
      --cache-to=type=gha,mode=max,scope=gke-{staging|production}-build \
      -f ./Dockerfile \
      -t "${IMAGE_REPO}:${IMAGE_TAG}" \
      --push .
```

- Always `linux/amd64` — GKE nodes are amd64
- Always use GHA cache with distinct scopes per environment
- Push directly from buildx (no separate push step)
- Registry: `{GCP_REGION}-docker.pkg.dev/{GCP_PROJECT_ID}/{GCP_REPO_NAME}/solidroam-app`

Configure Docker auth before building:
```bash
gcloud auth configure-docker ${GCP_REGION}-docker.pkg.dev --quiet
```

---

## Kustomize setup in CI

```yaml
- name: Set up Kustomize
  run: |
    curl -sfLo kustomize.tar.gz https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv5.4.1/kustomize_v5.4.1_linux_amd64.tar.gz
    tar -xzf kustomize.tar.gz
    sudo mv kustomize /usr/local/bin/kustomize
```

Always pin to `v5.4.1`. Don't use `kustomize` from apt — it's outdated.

---

## GKE credentials in CI

```yaml
- uses: google-github-actions/setup-gcloud@v2
  with:
    install_components: gke-gcloud-auth-plugin   # required for kubectl auth

- name: Get GKE Credentials
  run: |
    gcloud container clusters get-credentials ${{ secrets.GKE_CLUSTER_NAME }} \
      --location=${{ secrets.GKE_CLUSTER_LOCATION }} \
      --project="${GCP_PROJECT_ID}" \
      --quiet
```

Always install `gke-gcloud-auth-plugin` — kubectl will fail without it on GKE clusters.

---

## Migration job pattern in CI

```bash
# 1. Clear stale job (TTL may not have expired yet)
kubectl delete job django-migrate --namespace={env} --ignore-not-found=true

# 2. Render configmap and set image, then apply everything (includes job-migrate.yaml)
cd kubernetes/overlays/{staging|production}
envsubst < configmap.yaml > configmap.yaml.tmp && mv configmap.yaml.tmp configmap.yaml
kustomize edit set image solidroam-app="${IMAGE_REPO}:${IMAGE_TAG}"
kustomize build . | kubectl apply -f -

# 3. Wait for completion
kubectl wait job/django-migrate \
  --for=condition=complete \
  --timeout=300s \
  --namespace={env}
```

Migration runs **before** deploy — never after. If migration fails, deploy job is blocked.

---

## Configmap rendering

The configmap contains `$VAR` placeholders that are substituted at deploy time via `envsubst`. Variables come from GitHub Actions `vars.*` (not `secrets.*` — they are non-sensitive):

```
HOSTNAME, BUSINESS_NAME, CPO, EMSP, SIMULATOR, BACKGROUND_SEND,
LOCAL_STATIC, REFRESH_RDS_TOKEN_FOR_TASKS, CSRF_TRUSTED_ORIGINS, CELERY_QUEUE_NAME
```

Always pass these as `env:` on the step — `envsubst` reads from the process environment.

---

## Sentry release

```yaml
- uses: getsentry/action-release@v3
  env:
    SENTRY_AUTH_TOKEN: ${{ secrets.SENTRY_AUTH_TOKEN }}
    SENTRY_ORG: ${{ secrets.SENTRY_ORG }}
    SENTRY_PROJECT: ${{ secrets.SENTRY_PROJECT }}
  with:
    environment: staging   # or production
    release: ${{ env.IMAGE_TAG }}
    set_commits: auto
    finalize: true
```

Runs **after** deploy succeeds. Uses the image tag as the release identifier so Sentry releases match Docker image tags.

---

## Release flow (production only)

1. `release-drafter/release-drafter@v6` creates a draft release and outputs the tag
2. Build uses that tag as the image tag
3. After deploy succeeds, `publish-release` job:
   - Pushes a git tag with `git tag "$RELEASE_TAG" && git push origin "$RELEASE_TAG"`
   - Publishes the draft: `gh release edit "$RELEASE_TAG" --draft=false`

Tag is semver. Never manually create tags that conflict with release-drafter output.

---

## Runner

All jobs use `ubuntu-latest-m` (medium runner). Do not change to `ubuntu-latest` — the project relies on medium runner specs for parallel test performance (`pytest -n auto`).

---

## Secrets vs vars

| Type | Used for | Access in workflow |
|---|---|---|
| `secrets.*` | Credentials, keys, tokens | `${{ secrets.NAME }}` |
| `vars.*` | Non-sensitive config (feature flags, hostnames) | `${{ vars.NAME }}` |

Never promote a `vars.*` value to `secrets.*` unless it is actually sensitive. Never put a secret in `vars.*`.

---

## Common mistakes to avoid

- **Do not** use `actions/checkout@v4` — repo pins `v3` for all checkout steps
- **Do not** use `setup-python@v5` — repo pins `v4`
- **Do not** skip the migration job when deploying a branch that has no new migrations — the job is idempotent and safe
- **Do not** add `workflow_dispatch` to staging without also ensuring the configmap vars are available in the staging environment
- **Do not** run `kubectl apply -k` before the migration job completes
- **Do not** use `credentials_json` for GCP auth — OIDC only

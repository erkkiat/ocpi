---
name: kubernetes-gke
description: >
  Kubernetes and GKE rules for ocpiconnector. Load for ANY task touching
  kubernetes/ manifests, Kustomize overlays, deployment resources, migration
  jobs, secrets, probes, or resource limits. Covers the exact structure,
  constraints, and GKE-specific patterns used in this repo.
---

# Kubernetes & GKE — ocpiconnector

## Repo structure

```
kubernetes/
├── base/                          # shared manifests, no env-specific values
│   ├── deployment-django-app.yaml
│   ├── deployment-celery-django.yaml
│   ├── deployment-celery-mqtt.yaml
│   ├── deployment-mqtt-subscriber.yaml
│   ├── job-migrate.yaml
│   ├── secret-provider-class.yaml
│   ├── service-django-app.yaml
│   ├── serviceaccount.yaml
│   ├── namespace.yaml
│   └── kustomization.yaml
└── overlays/
    ├── staging/                   # develop branch → staging namespace
    └── production/                # main branch → production namespace
```

Overlays patch: replicas, image tag, Workload Identity SA annotation, SecretProviderClass secrets, configmap vars.

---

## Deployments and their constraints

| Deployment | Replicas | Strategy | Why |
|---|---|---|---|
| `django-app` | 1 (base), 2 (prod overlay) | RollingUpdate | Stateless web — safe to scale |
| `celery-django` | **always 1** | **Recreate** | Runs `--beat` scheduler — multiple replicas cause duplicate scheduled tasks |
| `mqtt-subscriber` | **always 1** | **Recreate** | Single consumer — multiple replicas process every MQTT message N times |
| `celery-mqtt` | **always 1** | **Recreate** | Same as mqtt-subscriber — MQTT fan-out hazard |

**Never change celery-django, mqtt-subscriber, or celery-mqtt replicas above 1.**
**Never change their strategy from Recreate to RollingUpdate.**

---

## Secrets — GCP Secret Manager CSI driver

Secrets are **not** env vars baked into the image. They are mounted via the GKE-managed Secrets Store CSI driver:

```yaml
volumes:
  - name: secrets-store
    csi:
      driver: secrets-store-gke.csi.k8s.io   # GKE managed — NOT secrets-store.csi.k8s.io
      readOnly: true
      volumeAttributes:
        secretProviderClass: ocpiconnector-secrets
```

The CSI driver syncs each secret to a native k8s Secret named `ocpiconnector-env`. Pods consume it via:

```yaml
envFrom:
  - configMapRef:
      name: ocpiconnector-config   # non-sensitive runtime config
  - secretRef:
      name: ocpiconnector-env      # synced from GCP Secret Manager
```

**Secrets in this repo (all sourced from GCP Secret Manager):**
- `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `ALLOWED_HOSTS`
- `HUBJECT_CLIENT_CERTIFICATE`, `HUBJECT_PRIVATE_KEY`, `HUBJECT_CA_CERTIFICATE`
- `SENTRY_DSN`

**Rules:**
- Never add secrets to `configmap.yaml` — configmaps are non-sensitive only
- Always use `PROJECT_NUMBER` (not `PROJECT_ID`) in `resourceName` paths for the GKE CSI provider
- The `secrets` block in `SecretProviderClass` is **replaced entirely** per overlay via Kustomize patch — never hardcode project numbers in base
- Use `path:` (not `fileName:`) — that's the GKE managed CSI field name

---

## Workload Identity

Service account: `ocpiconnector-ksa`
Every pod spec must include:
```yaml
serviceAccountName: ocpiconnector-ksa
```

The `iam.gke.io/gcp-service-account` annotation is set per overlay (different GCP SAs for staging vs production).

---

## Migration job

```yaml
# job-migrate.yaml
spec:
  backoffLimit: 1
  ttlSecondsAfterFinished: 300    # auto-cleanup after 5 min
```

**CI pattern for migrations:**
1. `kubectl delete job django-migrate --namespace={env} --ignore-not-found=true` — clear previous job (TTL may not have fired yet)
2. `kustomize build . | kubectl apply -f -` — applies the job along with all resources
3. `kubectl wait job/django-migrate --for=condition=complete --timeout=300s --namespace={env}`

Never run migrations by exec-ing into a pod. Always use the Job.

---

## Health probes

`django-app` only (Celery and MQTT have no HTTP endpoint):

```yaml
readinessProbe:
  httpGet:
    path: /health-check/
    port: 8000
  initialDelaySeconds: 15
  periodSeconds: 10
  failureThreshold: 3
  timeoutSeconds: 5

livenessProbe:
  httpGet:
    path: /health-check/
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 20
  failureThreshold: 3
  timeoutSeconds: 5
```

`celery-django` liveness uses `celery inspect ping`:
```yaml
livenessProbe:
  exec:
    command:
      - bash
      - -c
      - "celery -A ocpi22.tasks inspect ping -d celery-django@$HOSTNAME --timeout 10"
  initialDelaySeconds: 30
  periodSeconds: 60
  timeoutSeconds: 15
  failureThreshold: 3
```

`mqtt-subscriber` has **no liveness probe** — it's a long-running subscriber process, not a request handler.

---

## Resource limits

| Deployment | CPU request | CPU limit | Memory request | Memory limit |
|---|---|---|---|---|
| django-app | 250m | 1000m | 512Mi | 1Gi |
| celery-django | 250m | 1000m | 512Mi | 2Gi |
| mqtt-subscriber | 100m | 500m | 256Mi | 512Mi |
| migrate job | 100m | 500m | 256Mi | 512Mi |

When adjusting limits: always set both request and limit. Never set limit below request.

---

## Kustomize overlay workflow

```bash
# Apply an overlay (CI does this):
cd kubernetes/overlays/{staging|production}
envsubst < configmap.yaml > configmap.yaml.tmp && mv configmap.yaml.tmp configmap.yaml
kustomize edit set image solidroam-app="${IMAGE_REPO}:${IMAGE_TAG}"
kubectl apply -k .
kubectl rollout status deployment -n {namespace} --timeout=300s
```

**Image naming convention:**
- Base placeholder: `solidroam-app`
- Full name: `{GCP_REGION}-docker.pkg.dev/{GCP_PROJECT_ID}/{GCP_REPO_NAME}/solidroam-app`
- Staging tag: `{branch-name}-{short-commit-hash}` (e.g. `develop-a1b2c3d`)
- Production tag: semver from release-drafter (e.g. `v1.4.2`)

---

## Namespaces

- `staging` — maps to `develop` branch pushes
- `production` — maps to `main` branch pushes

Never mix namespaces. kubectl commands in CI always pass `--namespace={env}` explicitly.

---

## terminationGracePeriodSeconds

| Deployment | Value | Reason |
|---|---|---|
| django-app | 60s | Allow in-flight HTTP requests to complete |
| celery-django | 120s | Allow running Celery tasks to finish |
| mqtt-subscriber | 30s | Short — subscriber reconnects cleanly |

`django-app` also has a `preStop: sleep 5` to drain load balancer connections before SIGTERM.

---

## Common mistakes to avoid

- **Do not** add `deployment-celery-mqtt.yaml` or `deployment-mqtt-subscriber.yaml` to base `kustomization.yaml` twice
- **Do not** use `secrets-store.csi.k8s.io` driver — this project uses the GKE-managed `secrets-store-gke.csi.k8s.io`
- **Do not** store secrets in configmap — even base64-encoded
- **Do not** set `replicas > 1` on Celery beat or MQTT consumers
- **Do not** use `strategy: RollingUpdate` for Celery beat or MQTT consumers
- **Do not** run `kubectl apply` without first running the migration job

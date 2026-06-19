# Deployment Runbook — Thor + Loki (DGX Spark)

End-to-end guide for deploying the full Gardening Agent stack to the two-node k3s cluster.

---

## Architecture

```
Thor (control plane + worker)   Loki (worker)
  k3s server                      k3s agent
  Cambium (2 replicas)            Postgres (pinned, PVC)
  Rhizome #1                      Rhizome #2
  Ingress (Traefik)
```

Pods communicate over cluster-internal DNS:
- Cambium → `http://rhizome-svc:8001`
- Rhizome → `postgresql+psycopg2://postgres-svc:5432/postgres`

---

## Prerequisites

- Docker installed on your Mac with `buildx` for cross-platform builds
- `kubectl` configured to point at the k3s cluster
- `helm` installed
- Access to push to `ghcr.io/ybordag/`

---

## Step 1 — Set up k3s

**On Thor (run once):**
```bash
curl -sfL https://get.k3s.io | sh -
# Wait ~30s for k3s to start, then get the join token:
sudo cat /var/lib/rancher/k3s/server/node-token
# Copy kubeconfig to your Mac:
sudo cat /etc/rancher/k3s/k3s.yaml   # copy to ~/.kube/config, replace 127.0.0.1 with thor's IP
```

**On Loki (run once):**
```bash
curl -sfL https://get.k3s.io | \
  K3S_URL=https://<thor-ip>:6443 \
  K3S_TOKEN=<token-from-above> \
  sh -
```

**Verify on your Mac:**
```bash
kubectl get nodes
# NAME   STATUS   ROLES                  AGE
# thor   Ready    control-plane,master   2m
# loki   Ready    <none>                 1m
```

---

## Step 2 — Deploy Postgres

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

helm install postgres bitnami/postgresql \
  -f k8s/postgres-values.yaml \
  --set auth.postgresPassword=<your-strong-password>

# Wait for Postgres to be ready:
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=postgresql --timeout=120s
```

---

## Step 3 — Create secrets

```bash
# Copy templates and fill in real values (never commit the filled-in files)
cp k8s/secrets.yaml.template k8s/secrets.yaml
cp ../cambium/k8s/secrets.yaml.template ../cambium/k8s/secrets.yaml

# Edit both files, then apply:
kubectl apply -f k8s/secrets.yaml
kubectl apply -f ../cambium/k8s/secrets.yaml
```

---

## Step 4 — Build and push Docker images

From your Mac (cross-compiling for linux/amd64):

```bash
# Enable multi-platform builds (once)
docker buildx create --use --name sparks

# Rhizome
docker buildx build --platform linux/amd64 \
  -t ghcr.io/ybordag/rhizome:latest \
  -t ghcr.io/ybordag/rhizome:$(git -C . rev-parse --short HEAD) \
  --push .

# Cambium
docker buildx build --platform linux/amd64 \
  -t ghcr.io/ybordag/cambium:latest \
  -t ghcr.io/ybordag/cambium:$(git -C ../cambium rev-parse --short HEAD) \
  --push ../cambium
```

---

## Step 5 — Deploy

```bash
# Rhizome (includes Alembic migration init container)
kubectl apply -f k8s/rhizome.yaml

# Cambium
kubectl apply -f ../cambium/k8s/cambium.yaml

# Watch rollout
kubectl rollout status deployment/rhizome
kubectl rollout status deployment/cambium
```

---

## Step 6 — Verify

```bash
# All pods running
kubectl get pods

# Health checks
kubectl port-forward svc/cambium-svc 8080:8080 &
curl http://localhost:8080/health        # {"status":"ok"}
curl http://localhost:8080/docs/index.html   # Swagger UI

# Or directly via Thor's IP (via Ingress)
curl http://<thor-ip>/health
```

---

## Updating after a code change

```bash
# 1. Build and push new image (tags :latest and :<git-sha>)
docker buildx build --platform linux/amd64 \
  -t ghcr.io/ybordag/rhizome:latest --push .

# 2. Rolling restart (pulls new :latest, zero downtime because replicas=2)
kubectl rollout restart deployment/rhizome

# Watch: old pods terminate only after new ones pass readiness probe
kubectl rollout status deployment/rhizome
```

---

## Monitoring pod health

```bash
# Live pod status
kubectl get pods -w

# Logs from a specific pod
kubectl logs -f deployment/rhizome

# Logs from both Rhizome replicas
kubectl logs -l app=rhizome --all-containers

# Describe a pod to see probe failures
kubectl describe pod <pod-name>

# Events (shows restarts, probe failures, OOM kills)
kubectl get events --sort-by=.lastTimestamp
```

---

## How k3s keeps services alive

- **Liveness probe** — `GET /health` every 10s. Three consecutive failures → pod killed and restarted
- **Readiness probe** — `GET /health` every 5s. Failure → pod removed from load balancer rotation (not killed)
- **ReplicaSet** — always maintains exactly 2 replicas; if a node goes down, pods reschedule to the surviving node
- **Restart policy** — `Always` (default); crashed containers restart with exponential backoff
- **Resource limits** — prevent a single pod from consuming all node memory and causing OOM kills on neighbours

---

## Rollback

```bash
# List rollout history
kubectl rollout history deployment/rhizome

# Rollback to previous version
kubectl rollout undo deployment/rhizome

# Rollback to a specific revision
kubectl rollout undo deployment/rhizome --to-revision=2
```

---

## Secrets rotation

To rotate `JWT_SECRET` or `CAMBIUM_ENCRYPTION_KEY`:

```bash
# Edit the secret
kubectl edit secret cambium-secrets

# Rolling restart picks up the new value
kubectl rollout restart deployment/cambium
```

**Note:** rotating `CAMBIUM_ENCRYPTION_KEY` requires re-encrypting all stored provider keys first — see `docs/roadmap/overview.md` (Key rotation section).

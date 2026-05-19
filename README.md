# pipeline-ml

An **ML Pipeline Reliability Platform** ("Datadog for ML systems") — a learning /
portfolio project. It detects when a deployed model silently goes wrong (data drift),
traces any prediction back to the exact model + data + code that produced it (lineage),
and automatically rolls back bad model releases (closed loop).

> What this category *is* and why it matters:
> [`docs/ml-pipeline-reliability-platform.md`](docs/ml-pipeline-reliability-platform.md)

## Milestones

| | Milestone | Status |
|--|--|--|
| M0 | ML logic, no infra: train → serve → log → detect drift | ✅ |
| M1 | Containerize (Docker + docker-compose) | ✅ |
| M2 | Local Kubernetes (k3d) | ✅ |
| M3 | Lineage receipt API | ✅ |
| M4 | Closed loop (Argo Rollouts auto-rollback) | ✅ |
| M5 | Dashboards & polish (Grafana, Streamlit) | ✅ |

## M0 quickstart (pure Python, no Docker/Kubernetes)

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS/Linux

# 1. Train + register the model, save the drift baseline
python ml/train.py

# 2. Start the inference service (new terminal, keep it running)
python -m uvicorn services.inference.app:app --port 8000

# 3a. Send normal traffic, then check drift  -> STABLE
python scripts/inject_drift.py --mode normal --n 400
python services/drift_job/drift_job.py

# 3b. Send drifted traffic, then check drift  -> DRIFT DETECTED
python scripts/inject_drift.py --mode drift --n 400
python services/drift_job/drift_job.py
```

**What M0 proves:** a model is trained, versioned in MLflow, served over HTTP with every
prediction logged, and a drift job that turns "is the data still normal?" into a number
(PSI/KS) — the foundation every later milestone builds on.

## M1 quickstart (the whole system in one command)

Requires Docker (Docker Desktop on Windows/Mac). No Python venv needed — the
containers carry their own dependencies.

```bash
# Build images + bring up postgres -> mlflow server -> train (one-shot) -> inference.
# Compose waits on healthchecks, so this returns only once the API is ready.
docker compose -f deploy/docker-compose.yml up -d --build

# The API is now on http://localhost:8000  (model loaded from the MLflow server)
curl http://localhost:8000/health

# Send traffic, then run the drift job ON DEMAND (a container, reads Postgres):
python scripts/inject_drift.py --mode normal --n 400 --url http://127.0.0.1:8000
docker compose -f deploy/docker-compose.yml run --rm drift \
  python services/drift_job/drift_job.py --limit 400          # -> stable

python scripts/inject_drift.py --mode drift --n 400 --url http://127.0.0.1:8000
docker compose -f deploy/docker-compose.yml run --rm drift \
  python services/drift_job/drift_job.py --limit 400          # -> DRIFT DETECTED

# Tear everything down (add -v to also wipe the Postgres/artifact volumes):
docker compose -f deploy/docker-compose.yml down
```

The traffic generator still runs from the host for convenience; install just
its deps with `pip install requests numpy scikit-learn` if you don't have a
venv, or reuse the M0 `.venv`.

**What M1 proves:** the *same* code from M0 runs unchanged in containers. Every
infrastructure location (Postgres, the MLflow server) is injected via
environment variables — nothing is hardcoded — so the prediction log moved from
a local SQLite file to a shared Postgres service and the model now loads from a
real MLflow server, while the verified drift numbers stay identical
(normal → stable; drifted `f0` → PSI ≈ 1.83 SIGNIFICANT).

## M2 quickstart (local Kubernetes via k3d)

Requires Docker + [k3d](https://k3d.io) + kubectl. k3d runs a real
Kubernetes cluster *inside Docker* on your machine.

```bash
# 1. Create the cluster
k3d cluster create pipeline-ml
# Windows/Docker Desktop only: if kubectl can't reach the API, repoint it off
# the broken host.docker.internal entry to the published localhost port:
#   PORT=$(docker port k3d-pipeline-ml-serverlb 6443/tcp | cut -d: -f2)
#   kubectl config set-cluster k3d-pipeline-ml --server=https://127.0.0.1:$PORT

# 2. Build images and load them into the cluster (no registry needed)
docker build -f services/inference/Dockerfile  -t pipeline-ml-inference:dev .
docker build -f services/drift_job/Dockerfile  -t pipeline-ml-drift:dev .
k3d image import pipeline-ml-inference:dev pipeline-ml-drift:dev -c pipeline-ml

# 3. Deploy everything (namespace, config, Postgres, MLflow, train Job,
#    inference Deployment+Service, drift CronJob)
kubectl apply -f deploy/k8s/
kubectl wait --for=condition=complete job/train -n pipeline-ml --timeout=600s
kubectl rollout status deployment/inference -n pipeline-ml

# 4. Reach the API from the host
kubectl port-forward svc/inference 8000:8000 -n pipeline-ml &   # background
curl http://127.0.0.1:8000/health

# 5. Send traffic, then run the drift check NOW (instead of waiting for the
#    */5 CronJob schedule) by creating a one-off Job from it:
python scripts/inject_drift.py --mode normal --n 400 --url http://127.0.0.1:8000
kubectl create job --from=cronjob/drift drift-now -n pipeline-ml
kubectl wait --for=condition=complete job/drift-now -n pipeline-ml --timeout=150s
kubectl logs job/drift-now -n pipeline-ml          # -> stable

# Free resources without deleting the cluster:  k3d cluster stop pipeline-ml
# Start it again later:                          k3d cluster start pipeline-ml
# Delete it entirely:                            k3d cluster delete pipeline-ml
```

**What M2 proves:** the *same* images from M1 run on a real Kubernetes
cluster. Inference is a self-healing **Deployment + Service**, training is a
run-once **Job**, and the drift check is an automatic **CronJob** (every 5
min) — yet the verified numbers are still identical (train accuracy 0.9380;
normal → max PSI 0.0636 stable; drifted `f0` → PSI 1.8285 SIGNIFICANT).

## M3 — lineage receipt

Every prediction can be traced back to exactly how its model was made.
`GET /lineage/{prediction_id}` joins the prediction log → the MLflow run that
produced that model version → its params, accuracy, git commit, and dataset
fingerprint.

```bash
# (model trained + server running, e.g. via the M0/M1/M2 quickstart)
PID=$(curl -s -X POST http://127.0.0.1:8000/predict \
        -H 'Content-Type: application/json' \
        -d '{"features":[0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8]}' | jq -r .prediction_id)
curl -s http://127.0.0.1:8000/lineage/$PID | jq
```

Example receipt:

```json
{
  "prediction": {
    "prediction_id": "20c13653-…", "ts": "2026-05-18T19:28:39Z",
    "model": "income-clf", "model_version": "2",
    "features": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
    "prediction": 1, "proba": 0.6116
  },
  "model_lineage": {
    "run_id": "31a93b9a…", "status": "FINISHED",
    "params": {"n_estimators": "120", "max_depth": "8", "n_samples": "6000"},
    "metrics": {"accuracy": 0.938, "f1": 0.9373},
    "git_sha": "d698f22", "dataset_hash": "cce02db9b4e9a5a7"
  }
}
```

The training git commit reaches the receipt via a `GIT_SHA` env var (images
exclude `.git`), e.g. `GIT_SHA=$(git rev-parse --short HEAD) docker compose
... up`; unknown ids return **404**.

**What M3 proves:** the system is auditable — any single prediction yields a
full, honest provenance receipt (model version + training params + accuracy +
code commit + data fingerprint), the foundation for the M4 closed loop.

## M4 — the closed loop (canary + auto-rollback)

A new model release is **not** trusted blindly. Inference runs as an Argo
**Rollout**: every release goes 25 % canary → automated analysis → 100 %.
The analysis asks Prometheus for the *worst* holdout accuracy across all
inference pods and **fails the release if it drops below 0.7**, so a bad
model is auto-rolled-back with no human in the loop and no serving downtime.

How the pieces fit:

- Each inference pod scores a fixed labeled holdout at startup and exposes
  `model_holdout_accuracy{model_version=…}` at `/metrics`.
- Prometheus scrapes every pod individually (canary *and* stable).
- The `AnalysisTemplate` query is `min(model_holdout_accuracy)` with
  success condition `≥ 0.7` (FQDN
  `prometheus.pipeline-ml.svc.cluster.local:9090` so the controller, which
  runs in the `argo-rollouts` namespace, resolves it correctly).
- A release = bump `MODEL_VERSION` in the `model-release` ConfigMap **and**
  the `pipeline-ml/release` pod-template annotation (both in
  `deploy/k8s/50-inference.yaml`); the annotation change is what makes Argo
  start a canary.

Prereqs: the M2 cluster up, plus the Argo Rollouts controller and the
`kubectl argo rollouts` plugin (the
[kubectl-argo-rollouts](https://github.com/argoproj/argo-rollouts/releases)
binary on PATH).

```bash
kubectl apply -f deploy/k8s/                       # includes the Rollout + analysis
kubectl argo rollouts get rollout inference -n pipeline-ml   # → Healthy

# --- good release: edit MODEL_VERSION + release annotation to a good
#     version in deploy/k8s/50-inference.yaml, then ---
kubectl apply -f deploy/k8s/50-inference.yaml
kubectl argo rollouts get rollout inference -n pipeline-ml --watch
#  → canary 25% → AnalysisRun Successful → auto-promoted to 100%

# --- bad release (rollback proof) ---
kubectl delete job train-bad -n pipeline-ml --ignore-not-found
kubectl apply -f deploy/train-bad-job.yaml         # registers a ~0.45-acc model
# point MODEL_VERSION + annotation at that version, apply, watch:
#  → AnalysisRun Failed → RolloutAborted → previous good model still serving
kubectl exec -n pipeline-ml deploy/inference -- \
  python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/health').read().decode())"
#  → model_version is still the previous GOOD version
```

**What M4 proves (verified 2026-05-19):** the loop is closed. A good model
(v2, holdout 0.917) auto-promoted through the canary in ~1.5 min; a
deliberately-bad model (v4, holdout 0.444) drove `min(model_holdout_accuracy)`
below the 0.7 gate and Argo **auto-aborted in ~32 s** while the previous good
model kept serving uninterrupted. Captured runs: [`docs/m4-proof/`](docs/m4-proof/).

## M5 — dashboards & polish (Grafana + Streamlit)

The wall of graphs on top of the Prometheus data, plus a small Streamlit
page that renders the M3 `/lineage/{id}` receipt as something a human can
read at a glance.

What's new in M5:

- **Inference `/metrics` extended** with `prediction_requests_total`,
  `prediction_errors_total`, and `prediction_latency_seconds_{sum,count}`
  alongside the existing `model_holdout_accuracy`. Hand-rendered to keep the
  inference image's slow pip layer cached (no new dependency).
- **Grafana** (`deploy/k8s/80-grafana.yaml`) — Prometheus datasource and a
  7-panel dashboard (`pipeline-ml — ML reliability`) baked into ConfigMaps
  so the whole thing comes up identically on every `kubectl apply`, no
  click-configuration. Anonymous Admin removes the login wall for the demo.
- **Streamlit lineage UI** (`services/lineage_ui/` +
  `deploy/k8s/90-lineage-ui.yaml`) — talks only to inference over HTTP;
  Send a prediction, paste the returned id, see the full receipt as a page.

```bash
kubectl apply -f deploy/k8s/
kubectl port-forward -n pipeline-ml svc/grafana    3000:3000   # http://localhost:3000/d/pipeline-ml
kubectl port-forward -n pipeline-ml svc/lineage-ui 8501:8501   # http://localhost:8501
```

The Grafana dashboard panels: holdout accuracy by model_version with the 0.7
canary-gate threshold drawn on; drift PSI (worst feature) with 0.1/0.2
thresholds; prediction volume (req/s); avg prediction latency; plus stat
tiles for the current min holdout accuracy, total predictions served, and
the latest worst PSI.

**Capacity caveat (honest):** the whole single-node k3d sits inside a
Docker Desktop VM that, on this laptop, is 3.83 GiB. M4 + Grafana +
Streamlit all at once initially tipped that over and OOM-killed mlflow.
The fix is documented in PROGRESS.md as resolved-issue #10 and is more
interesting than "give it more RAM": mlflow gets `strategy: Recreate` so
rolling updates don't briefly run two pods, inference gets a `startupProbe`
plus tolerant liveness/readiness so a slow under-load start isn't mistaken
for a crash, the inference Rollout runs at `replicas: 1` (canary already
proven in M4), and the drift CronJob is suspended (run on demand). The
full stack now fits with headroom on 3.83 GiB.

**What M5 proves (verified 2026-05-19):** the platform has the visible
surface a real reliability tool needs — live dashboards reading the same
metrics the closed loop is gated on, and a friendly receipt page anyone can
hand a `prediction_id` to. Live-API verification in
[`docs/m5-proof/m5-verification.txt`](docs/m5-proof/m5-verification.txt).

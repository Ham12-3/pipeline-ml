# pipeline-ml — Progress Checklist

_Last updated: 2026-05-18_

Legend: `[x]` done · `[~]` in progress / partial · `[ ]` not started

**Overall:** **M0–M3 committed and verified.** **M4 built but NOT yet
verified** — committed as a work-in-progress checkpoint. M4 adds the closed
loop (Argo Rollouts canary + Prometheus/Pushgateway + auto-rollback). During
M4 verification two real bugs were found and fixed (see Resolved issues #6,
#7); the good-release canary retry was launched but the k3d API server became
unreachable under laptop resource pressure, so neither the good-release
promotion nor the bad-release auto-rollback has been confirmed yet. M5 not
started.

---

## Step 0 — Persist the research

- [x] `docs/ml-pipeline-reliability-platform.md` written (research + beginner explainer + sources)
- [x] Beginner explanations of cron jobs / Kubernetes / Grafana delivered
- [x] User background saved to memory (new to Docker/K8s; explain before building)

## M0 — ML logic, no infra  ✅ COMPLETE

### Code written
- [x] `requirements.txt` (scikit-learn, mlflow, fastapi, uvicorn, scipy, numpy, pandas, requests)
- [x] `.gitignore` (venv + `.claude/` harness dir + local state)
- [x] `common.py` — shared paths, model/data contract, one-fixed-pool data helpers
- [x] `ml/drift_metrics.py` — hand-rolled PSI + KS, verdict, per-feature report
- [x] `ml/baseline.py` — save/load training distribution as drift reference
- [x] `ml/train.py` — train RF, log to MLflow, register model, set `production` alias, tag git SHA + dataset hash, save baseline
- [x] `services/inference/app.py` — FastAPI `/health` + `/predict`, logs every prediction to SQLite
- [x] `services/drift_job/drift_job.py` — PSI/KS over recent predictions vs baseline, prints verdict
- [x] `scripts/inject_drift.py` — normal vs drift traffic generator
- [x] `README.md` — M0 quickstart + milestone table

### Environment
- [x] Python 3.13.2, git, Docker 28.1.1, kubectl v1.32.2 confirmed available
      (k3d NOT yet installed — needed for M2/M4)
- [x] Repo-root `.venv` created, dependencies installed
      (sklearn 1.8.0, mlflow 3.12.0, fastapi 0.136.1, scipy 1.17.1)

### Verification (all re-run from repo root, 2026-05-18)
- [x] `python ml/train.py` works — model `income-clf` v1, alias `production`,
      accuracy ≈ 0.938, baseline saved
- [x] Inference server starts; `GET /health` returns ok + model version 1
- [x] `/predict` accepts traffic (800 requests total, 0 errors)
- [x] **STABLE case verified** — normal traffic → all features STABLE,
      max PSI = 0.0636 (< 0.1)
- [x] **DRIFT DETECTED case verified** — shifted `f0` → PSI = 1.83 SIGNIFICANT,
      all other features STABLE (proves the detector is specific, not noisy)
- [x] **Drift false-positive bug RESOLVED** (see Resolved issues below)

## M1 — Containerize  ✅ COMPLETE

### Code written
- [x] `.dockerignore` (keeps venv/local state out of the build context)
- [x] `common.py` config now env-driven: `PREDICTIONS_DB_URL`,
      `MLFLOW_TRACKING_URI`, `MLFLOW_ARTIFACT_ROOT`, `PIPELINE_ARTIFACTS_DIR`
      — local SQLite remains the default when no env vars are set
- [x] `db.py` — SQLAlchemy prediction store; ONE code path for SQLite (local)
      and Postgres (containers). `app.py` + `drift_job.py` refactored onto it
- [x] `services/inference/Dockerfile`, `services/drift_job/Dockerfile`
- [x] `deploy/docker-compose.yml` (postgres → mlflow server → train one-shot →
      inference; drift job under a `jobs` profile, run on demand)
- [x] `requirements.txt` += `sqlalchemy`, `psycopg2-binary`
- [x] README M1 one-command quickstart

### Verification (2026-05-18, fully containerized)
- [x] `docker compose -f deploy/docker-compose.yml up -d --build` brings the
      stack up; postgres + mlflow + inference healthy; `train` exits 0
- [x] Train in-container: accuracy **0.9380** (== M0); `income-clf` v1
      registered + `production` alias set IN the MLflow server (Postgres-backed)
- [x] `GET /health` on containerized API → `model_version` 1 from the registry
- [x] STABLE: 400 normal → max PSI **0.0636** → stable (== M0)
- [x] DRIFT: 400 drifted `f0` → PSI **1.8285** SIGNIFICANT, f1–f7 STABLE (== M0)
- [x] Predictions persisted in Postgres; baseline shared via a Docker volume

## M2 — Local Kubernetes (k3d)  ✅ COMPLETE

### Done
- [x] k3d v5.8.3 installed (direct binary → `C:\Users\mobol\bin`, on user PATH)
- [x] Cluster `pipeline-ml` created (k3s v1.31.5); kubeconfig repointed off the
      broken `host.docker.internal` to `https://127.0.0.1:<port>`
- [x] `deploy/k8s/`: 00-namespace, 10-config (ConfigMap + Secret), 20-postgres
      (PVC+Deploy+Svc), 30-mlflow (PVC+Deploy+Svc), 40-train-job (Job + baseline
      PVC), 50-inference (Deploy+Svc), 60-drift-cronjob (CronJob `*/5`)
- [x] Ordering without `depends_on`: initContainers (wait-postgres, wait-mlflow,
      wait-model) + readiness/liveness probes
- [x] `k3d image import` of `pipeline-ml-inference:dev` + `pipeline-ml-drift:dev`
      (local images, no registry); `imagePullPolicy: IfNotPresent`

### Verification (2026-05-18, on the k3d cluster)
- [x] `kubectl apply -f deploy/k8s/` → postgres/mlflow/inference 1/1, train Job
      Completed (accuracy **0.9380**, `income-clf` v1 + `production` alias)
- [x] `GET /health` via `kubectl port-forward` → `model_version` 1
- [x] STABLE: 400 normal → CronJob-spawned Job → max PSI **0.0636** → stable
- [x] DRIFT: 400 drifted `f0` → PSI **1.8285** SIGNIFICANT, f1–f7 STABLE
- [x] Numbers byte-identical to M0 (laptop) and M1 (Compose)

## M3 — Lineage receipt  ✅ COMPLETE
- [x] Train-time tags: git SHA + dataset hash (done early in M0)
- [x] Inference stamps `model_version` + `run_id` on every logged prediction
- [x] `lineage.py`: `run_provenance(run_id)` → params/metrics/git_sha/dataset_hash
      from MLflow; `db.get_prediction(id)` → the logged serving row
- [x] `GET /lineage/{prediction_id}` joins them into one receipt; 404 on
      unknown id
- [x] `common.git_sha()` prefers `GIT_SHA` env var (images exclude `.git`);
      injected in `docker-compose.yml` train + the k8s ConfigMap
- [x] Verified locally: predict → receipt shows real model v2, run_id,
      accuracy 0.938, **git_sha d698f22** (not "unknown"), dataset_hash;
      bogus id → 404

### Known caveat (honest)
`dataset_hash` is environment-sensitive: local venv (sklearn 1.8.0) →
`cce02db9…`, container image (sklearn resolved at build) → `43616cb6…`.
`make_classification` output bytes differ across library versions, so the
fingerprint differs even though the data is statistically identical. The
receipt faithfully reports whatever was recorded at train time — but pin
sklearn/numpy if a *cross-environment* identical hash is ever needed.

## M4 — The closed loop  🚧 BUILT, NOT YET VERIFIED

### Done (code + infra)
- [x] Argo Rollouts controller installed (argo-rollouts ns; CRDs present)
- [x] Inference app: serves a pinned `MODEL_VERSION` (falls back to the
      `production` alias), scores a fixed labeled holdout at startup, exposes
      `model_holdout_accuracy{model_version=…}` at `/metrics` (hand-rendered,
      no new pip dep so the slow image layer stays cached)
- [x] `ml/train.py --bad` / `TRAIN_BAD=1` trains a deliberately bad model
      (shuffled labels) for the rollback proof
- [x] `deploy/k8s/70-observability.yaml`: Pushgateway + Prometheus (+ RBAC,
      pod-discovery scrape config)
- [x] Drift CronJob pushes `model_drift_psi` to Pushgateway
- [x] Inference is an Argo `Rollout` (canary 25% → analysis → 100%) +
      `AnalysisTemplate` (Prometheus `min(model_holdout_accuracy) ≥ 0.7`) +
      `model-release` ConfigMap selecting the version
- [x] Baseline Rollout reached Healthy at v1 (holdout_accuracy 0.917);
      Prometheus confirmed scraping the metric from all 4 pods

### NOT done — verification blocked
- [ ] Good release auto-promotes (canary passes) — **not confirmed**
- [ ] Deliberately-bad model auto-rolls-back (canary fails) — **not started**
- Blocker: after fixing bugs #6/#7 the good-release retry was launched but
  the k3d API server went unreachable (`Unable to connect: EOF`) under
  laptop resource pressure (postgres + mlflow + 4 inference + prometheus +
  pushgateway + argo + train pods). Cluster needs recovery/right-sizing,
  then re-run the good-release retry and the bad-release rollback.

## M5 — Dashboards & polish
- [ ] Prometheus scrape config
- [ ] Grafana dashboards (PSI/feature over time, rollout status, latency, volume)
- [ ] Streamlit `/lineage` receipt page
- [ ] README scripted demo + screenshots

---

## Resolved issues

1. **Drift false-positive (was blocking M0 sign-off) — FIXED & VERIFIED.**
   Root cause: generating "normal" traffic with a different `make_classification`
   seed produced a *different distribution*, not more samples of the same one,
   so the detector correctly-but-unhelpfully flagged it as drift.
   Fix: `common.py` now builds ONE fixed 20k-row pool (`_pool()`), trains on the
   first 6k rows (`training_data()`), and draws production traffic from a
   disjoint slice of the *same* pool (`production_sample()`). `make_dataset` /
   seed-based generation removed. `ml/train.py`, `ml/baseline.py`, and
   `scripts/inject_drift.py` updated accordingly.
   Proof: normal → max PSI 0.0636 (STABLE); drifted f0 → PSI 1.83 (SIGNIFICANT),
   f1–f7 unchanged.

2. **MLflow 3.x "Invalid Host header" 403 (blocked M1 train) — FIXED.**
   MLflow 3.x adds DNS-rebinding protection; the server rejected client
   requests with Host `mlflow:5000`. `MLFLOW_SERVER_ALLOWED_HOSTS` *replaces*
   the built-in localhost defaults, so the Compose value re-lists them too:
   `mlflow:*,localhost:*,127.0.0.1:*` (last two for the server's healthcheck).
3. **Artifact upload 500 — `PermissionError: /mlartifacts` — FIXED.** Images
   run as non-root `appuser`, but a fresh Docker named volume is root-owned.
   Fix: the Dockerfiles `mkdir`+`chown` `/mlartifacts` and `/shared/artifacts`
   before `USER appuser`; Docker copies that ownership when first initializing
   an empty named volume. Needed a one-time `down -v` to re-init old volumes.
4. **k3d on Windows: kubectl can't reach the API — FIXED.** k3d wrote the
   kubeconfig server as `https://host.docker.internal:54447`, which resolved to
   an unreachable LAN IP. The API is actually published on `127.0.0.1:<port>`
   (`docker port k3d-pipeline-ml-serverlb 6443/tcp`). Fix:
   `kubectl config set-cluster k3d-pipeline-ml --server=https://127.0.0.1:<port>`
   (k3d's TLS cert SANs include 127.0.0.1, so no TLS flag needed). Must be
   redone if the cluster is recreated, or create with `--api-port 127.0.0.1:N`.
5. **k8s probes vs MLflow host guard — AVOIDED BY DESIGN.** An HTTP probe's
   Host header is the pod IP, which the DNS-rebinding guard would 403. The
   mlflow Deployment uses a `tcpSocket` probe instead, keeping the guard strict
   for real traffic while letting readiness/liveness pass.
6. **`lineage.py` missing from the inference image — FIXED (latent M3 bug).**
   M3 added `lineage.py` at repo root but the inference Dockerfile never
   `COPY`d it. M3 was verified *locally* (file on disk), so the bug stayed
   hidden until M4 redeployed the image to k8s → `ModuleNotFoundError: No
   module named 'lineage'` CrashLoopBackOff. Fix: `COPY lineage.py .` in
   `services/inference/Dockerfile`. Lesson: verify containerised, not just
   local. (The M3 commit's container path was broken; M4 fixes it.)
7. **AnalysisTemplate Prometheus address — FIXED.** Used a bare `prometheus`
   host. The Argo Rollouts controller runs in the `argo-rollouts` namespace
   and issues the query from there, so the name resolved against the wrong
   namespace → `server misbehaving`, analysis `Error`, false abort of a GOOD
   model. Fix: FQDN `http://prometheus.pipeline-ml.svc.cluster.local:9090`.
8. **k3d API unreachable under load — OPEN.** Running the full M4 stack on a
   laptop (postgres + mlflow + 4 inference + prometheus + pushgateway + argo
   + train pods) made the k3d API server return `Unable to connect: EOF`
   mid-verification. Likely Docker Desktop resource limits. To recover:
   ensure Docker Desktop has more CPU/RAM, `k3d cluster start pipeline-ml`,
   re-apply resolved-issue #4, scale `inference` replicas down (e.g. 2), then
   re-run the good-release retry + bad-release rollback.

## File inventory

```
docs/ml-pipeline-reliability-platform.md
common.py            db.py            lineage.py
.gitignore           .dockerignore
requirements.txt
README.md
PROGRESS.md
ml/train.py          ml/baseline.py        ml/drift_metrics.py
services/inference/app.py        services/inference/Dockerfile
services/drift_job/drift_job.py  services/drift_job/Dockerfile
deploy/docker-compose.yml
deploy/k8s/  (00-namespace 10-config 20-postgres 30-mlflow 40-train-job
              50-inference[Rollout+AnalysisTemplate] 60-drift-cronjob
              70-observability[Prometheus+Pushgateway]).yaml
scripts/inject_drift.py
```
Local (gitignored) state: `.venv/`, `.claude/`, `mlflow.db`, `mlartifacts/`,
`predictions.db`, `artifacts/baseline.npz`. Docker (M1) state = named volumes
`deploy_pgdata`/`deploy_mlartifacts`/`deploy_baseline`. K8s (M2) state =
PVCs in the `pipeline-ml` namespace; k3d binary at `C:\Users\mobol\bin`.

## How to resume

M0–M3 are committed and verified. **M4 is committed as a WIP checkpoint —
built but NOT verified.**

**To finish M4 (pick up here):**
1. Give Docker Desktop more CPU/RAM (laptop ran out under the full stack).
2. `k3d cluster start pipeline-ml`; re-apply resolved-issue #4 (repoint
   kubeconfig to `https://127.0.0.1:<port>`).
3. Consider lowering the inference Rollout `replicas` to 2 to ease load.
4. `kubectl apply -f deploy/k8s/`; wait for the Rollout Healthy at v1.
5. **Good-release retry:** `model-release` MODEL_VERSION=3 + bump the
   `pipeline-ml/release` annotation → expect canary analysis to PASS
   (min holdout accuracy ≈ 0.92 ≥ 0.7) → auto-promote to 100%.
6. **Bad-release proof:** run a `TRAIN_BAD=1` training pod (registers a
   ~0.5-accuracy version), point `model-release` at it + bump the
   annotation → expect canary analysis to FAIL → Argo auto-aborts →
   previous good model keeps serving (rollback). Capture evidence.
7. Then update README (M4 section + flip the milestone table) and
   re-commit as verified-complete.

- Re-demo M0/M1/M2/M3: see the matching README quickstart sections.

**After M4: M5 — Dashboards & polish** (Grafana on the Prometheus data,
Streamlit lineage page, scripted demo + screenshots).

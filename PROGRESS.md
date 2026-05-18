# pipeline-ml — Progress Checklist

_Last updated: 2026-05-18_

Legend: `[x]` done · `[~]` in progress / partial · `[ ]` not started

**Overall:** Research + plan complete. **M0 committed; M1 fully built and
verified** (train → serve → log → detect drift; STABLE vs DRIFT DETECTED both
proven with real numbers). M1 runs the *identical* code in containers (Docker
Compose: Postgres + MLflow server + one-shot train + inference + on-demand
drift job) with every infra location injected via env vars — no hardcoding.
M1 not yet committed. M2–M5 not started.

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

## M2 — Local Kubernetes (k3d)
- [ ] Install k3d (NOT currently installed)
- [ ] Create k3d cluster
- [ ] Manifests: namespace, Postgres, MLflow, inference Deployment
- [ ] Drift job as a k8s `CronJob`
- [ ] System runs on the local cluster

## M3 — Lineage receipt
- [x] Train-time tags: git SHA + dataset hash (done early in M0)
- [x] Inference stamps `model_version` + `run_id` on every logged prediction
- [ ] `GET /lineage/{prediction_id}` joining prediction log → MLflow run → params/SHA/data hash
- [ ] Any prediction → full provenance receipt

## M4 — The closed loop
- [ ] Install Argo Rollouts
- [ ] Inference as a `Rollout` with canary strategy
- [ ] Drift job pushes drift + canary-quality gauges to Pushgateway/Prometheus
- [ ] `AnalysisTemplate` queries Prometheus; abort thresholds wired
- [ ] Deliberately-bad model → automatic rollback verified

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

## File inventory

```
docs/ml-pipeline-reliability-platform.md
common.py            db.py
.gitignore           .dockerignore
requirements.txt
README.md
PROGRESS.md
ml/train.py          ml/baseline.py        ml/drift_metrics.py
services/inference/app.py        services/inference/Dockerfile
services/drift_job/drift_job.py  services/drift_job/Dockerfile
deploy/docker-compose.yml
scripts/inject_drift.py
```
Local (gitignored) state: `.venv/`, `.claude/`, `mlflow.db`, `mlartifacts/`,
`predictions.db`, `artifacts/baseline.npz`. Docker (M1) state lives in named
volumes: `deploy_pgdata`, `deploy_mlartifacts`, `deploy_baseline`.

## How to resume

M0 is committed to `master`. **M1 is built and verified but NOT yet committed.**
The stack is brought down after verification (`docker compose -f
deploy/docker-compose.yml down`) — no server left running.

- Re-demo M0 locally (no Docker): README "M0 quickstart".
- Re-demo M1 (containers): README "M1 quickstart" — one `docker compose up`.

**Next milestone: M2 — Local Kubernetes (k3d).** k3d is NOT yet installed
(install it first). Reuse the M1 images: inference becomes a Deployment +
Service, the drift job a Kubernetes `CronJob`, with Postgres + the MLflow
server as in-cluster workloads. Explain k3d / pods / Deployments / Services /
CronJobs in plain language before wiring them.

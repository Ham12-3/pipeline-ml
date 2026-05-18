# pipeline-ml — Progress Checklist

_Last updated: 2026-05-18_

Legend: `[x]` done · `[~]` in progress / partial · `[ ]` not started

**Overall:** Research + plan complete. **M0 fully built, verified, and committed**
(train → serve → log → detect drift; STABLE vs DRIFT DETECTED both proven with
real numbers). Code consolidated from the scratch worktree into the repo root.
M1–M5 not started.

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

## M1 — Containerize
- [ ] Dockerfile per service (inference, drift_job)
- [ ] `deploy/docker-compose.yml` (inference + MLflow + Postgres + drift job)
- [ ] `docker-compose up` brings the whole system up with one command

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

## File inventory

```
docs/ml-pipeline-reliability-platform.md
common.py
.gitignore
requirements.txt
README.md
PROGRESS.md
ml/train.py        ml/baseline.py        ml/drift_metrics.py
services/inference/app.py
services/drift_job/drift_job.py
scripts/inject_drift.py
```
Local (gitignored) state: `.venv/`, `.claude/`, `mlflow.db`, `mlartifacts/`,
`predictions.db`, `artifacts/baseline.npz`

## How to resume

M0 is complete, verified, and committed to `master`. No server should be left
running (the M0 dev server is stopped after each verification).

To re-demo M0 locally, follow the README quickstart (train → serve → inject
normal/drift → drift job).

**Next milestone: M1 — Containerize.** Write a Dockerfile per service and a
`deploy/docker-compose.yml` so `docker-compose up` brings up inference + MLflow
+ the drift job together. Docker 28.1.1 is already available; explain the
container/compose concepts in plain language before wiring them.

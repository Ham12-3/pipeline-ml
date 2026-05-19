# pipeline-ml — Progress Checklist

_Last updated: 2026-05-19_

Legend: `[x]` done · `[~]` in progress / partial · `[ ]` not started

**Overall:** **M0–M5 committed and verified.** M5 adds Grafana
dashboards (auto-provisioned datasource + 7-panel dashboard), a small
Streamlit lineage receipt page, and request-volume + latency
instrumentation on the inference `/metrics` endpoint. All verified live
on the cluster.

**Today (2026-05-19/20, session 3 — M5 VERIFIED):** built M5 in pieces.
Added hand-rendered `prediction_requests_total` /
`prediction_latency_seconds_{sum,count}` to `services/inference/app.py`
`/metrics` (no new pip dep), rebuilt the image, k3d-imported. Deployed
Grafana (`deploy/k8s/80-grafana.yaml`) with the Prometheus datasource
and a 7-panel dashboard auto-provisioned from ConfigMaps (anonymous
Admin for the local demo). Built a small Streamlit lineage UI
(`services/lineage_ui/{app.py,Dockerfile}` +
`deploy/k8s/90-lineage-ui.yaml`).

Adding Grafana to the M4 stack tipped the 3.83 GiB Docker Desktop VM
over (mlflow OOM/CrashLoopBackOff cascading to inference Init wait) —
resolved-issue #10. The fix was not "give it more RAM" but
**right-size the deployment**: drift CronJob suspended; inference
Rollout `replicas: 2 → 1`; mlflow Deployment switched to
`strategy: Recreate` (no rolling-update doubling on a tight node);
generous probe timeouts/failureThresholds on mlflow + a startupProbe
on inference (so a slow under-load start isn't mistaken for a crash).
After applying these the cluster converged cleanly and the full M5
stack — postgres, mlflow, prometheus, pushgateway, inference, grafana,
lineage-ui — sits at ~2.5 GiB of the 3.83 GiB VM with headroom.

Verified end-to-end (see `docs/m5-proof/m5-verification.txt`):
- /metrics increments correctly under traffic (50 predictions ⇒ counter
  50, latency_sum 7.26 s ≈ 145 ms / prediction)
- Grafana `/api/health` `db=ok`; the Prometheus datasource and the
  `pipeline-ml — ML reliability` dashboard are both provisioned; all
  four panel queries return live data through Grafana's datasource
  proxy (`min(model_holdout_accuracy)=0.917`,
  `sum(prediction_requests_total)=50`, avg latency 0.025 s,
  `model_drift_psi=0.9631`)
- Streamlit `/_stcore/health` HTTP 200; predict→lineage flow returns a
  full receipt for a generated `prediction_id`

**Today (2026-05-19, session 2 — M4 VERIFIED):** kubectl connectivity was
fine on the recovered cluster (resolved-issue #4 did not recur this restart).
Installed the `kubectl-argo-rollouts` plugin (v1.9.0 →
`C:\Users\mobol\bin`). Re-applied `deploy/k8s/` — this pushed the
resolved-issue #7 FQDN AnalysisTemplate and `replicas: 2` onto the running
cluster (the cluster had been running the *old* broken bare-`prometheus`
AnalysisTemplate, leaving the Rollout stuck Degraded/aborted). Rollout
recovered to Healthy v1, then:
- **Good-release proof PASSED:** released model **v2** (`MODEL_VERSION`+
  annotation bump) → canary 1 pod (v2, holdout 0.917) → analysis 5/5
  (`min(model_holdout_accuracy)` = 0.917 ≥ 0.7) → **auto-promoted to 100%**
  in ~1.5 min. `/health` confirmed v2 serving.
- **Bad-release proof PASSED:** trained a deliberately-bad model
  (`deploy/train-bad-job.yaml`, registered **v4**, accuracy 0.445) →
  released v4 → canary pushed `min(model_holdout_accuracy)` to **0.444**
  (< 0.7) → analysis `assessed Failed (2 > failureLimit 1)` → **Argo
  auto-aborted in ~32 s**; the good v2 stayed serving the whole time
  (`ready 2/2` throughout, `/health` still v2 after the abort).
- Restored the Rollout to the verified-good v2 (Healthy), re-pointed the
  MLflow `production` alias back to v2 (the `--bad` train had moved it to
  v4), deleted the one-off `train-bad` Job. Evidence captured under
  `docs/m4-proof/`. Resolved-issues #7 and #8 CLOSED.

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

## M4 — The closed loop  ✅ COMPLETE

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
- [x] **Resource right-sizing (2026-05-19):** inference Rollout `replicas`
      dropped 4 → 2 in `50-inference.yaml` to keep the full M4 stack inside
      laptop Docker Desktop limits. 25% canary weight still resolves to 1 pod
      (rounded up from 0.5), so the canary path is unchanged.

### Verification (2026-05-19, on the k3d cluster, replicas=2)
- [x] `kubectl-argo-rollouts` v1.9.0 plugin installed → `C:\Users\mobol\bin`
- [x] `kubectl apply -f deploy/k8s/` pushed the FQDN AnalysisTemplate
      (resolved-issue #7) + `replicas: 2`; Rollout recovered to **Healthy v1**
- [x] Prometheus scraping both inference pods; `min(model_holdout_accuracy)`
      = 0.917 (the exact analysis query) resolves correctly
- [x] **Good release auto-promotes** — released v2: canary pod served v2
      (holdout 0.917), AnalysisRun 5/5 Successful, `RolloutCompleted:
      Completed all 3 canary steps`, `/health` → `model_version 2`.
      Evidence: `docs/m4-proof/m4-good-rollout.txt`, `m4-good-monitor.log`
- [x] **Deliberately-bad model auto-rolls-back** — `train-bad` registered
      v4 (accuracy 0.445); released v4: canary pod served v4 (holdout
      0.444), `min(model_holdout_accuracy)` dipped to 0.444,
      `AnalysisRunFailed`, `RolloutAborted ... assessed Failed (2 >
      failureLimit 1)`; the good v2 kept serving (`ready 2/2` throughout,
      `/health` still `model_version 2` after the abort). Evidence:
      `docs/m4-proof/m4-bad-rollout.txt`, `m4-bad-events.txt`,
      `m4-bad-monitor.log`
- [x] End-to-end run survived at `replicas: 2` without the k3d API server
      dropping (resolved-issue #8 closed)
- [x] Post-verification cleanup: Rollout restored to Healthy v2, MLflow
      `production` alias re-pointed to v2, one-off `train-bad` Job deleted
      (manifest `deploy/train-bad-job.yaml` kept for re-runs)

## M5 — Dashboards & polish  ✅ COMPLETE

### Done
- [x] **Prometheus scrape config** — already done in M4 (`70-observability`:
      scrapes pushgateway + per-pod inference via k8s SD)
- [x] **Inference metrics extended** — `prediction_requests_total`,
      `prediction_errors_total`, `prediction_latency_seconds_{sum,count}`
      hand-rendered alongside the existing `model_holdout_accuracy`; no new
      pip dep, image layer cache preserved (see resolved-issue #10 lesson
      that *applies* must follow file edits to actually reach the cluster)
- [x] **Grafana** (`deploy/k8s/80-grafana.yaml`) — Deployment + Service;
      Prometheus datasource + 7-panel dashboard
      (`pipeline-ml — ML reliability`) auto-provisioned from ConfigMaps;
      anonymous Admin for the local demo. Panels: holdout accuracy + 0.7
      canary gate, drift PSI with thresholds, prediction volume (req/s),
      avg latency, and three stat tiles
- [x] **Streamlit lineage UI** (`services/lineage_ui/{app.py,Dockerfile}`
      + `deploy/k8s/90-lineage-ui.yaml`) — talks ONLY to inference over
      HTTP; "Send a prediction" → "Fetch receipt" renders the M3
      `/lineage/{id}` response as a readable page
- [x] **One-off bad-train manifest** for the rollback demo
      (`deploy/train-bad-job.yaml`, intentionally outside `deploy/k8s/`)
- [x] **Capacity right-sizing** — see resolved-issue #10. Inference
      Rollout `replicas: 2 → 1`; drift CronJob suspended (run on demand);
      mlflow Deployment `strategy: Recreate` (no surge doubling);
      tolerant probe timeouts + a startupProbe on inference. The full
      M5 stack now fits the 3.83 GiB Docker Desktop VM with headroom

### Verification (2026-05-19, live on the cluster)
- [x] Live `/metrics` after a 50-burst: `prediction_requests_total=50`,
      `prediction_latency_seconds_sum=7.26 s` (~145 ms / prediction)
- [x] Grafana `/api/health` `db=ok`, datasource + dashboard provisioned;
      all 4 panel queries return live values via the datasource proxy
- [x] Streamlit `/_stcore/health` HTTP 200; predict→lineage returns a
      full receipt for a generated `prediction_id` (model v2,
      run_id 6be3353a…, accuracy 0.938)
- [x] Evidence captured: `docs/m5-proof/m5-verification.txt`

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
7. **AnalysisTemplate Prometheus address — FIXED & CLOSED (2026-05-19).**
   Used a bare `prometheus` host. The Argo Rollouts controller runs in the
   `argo-rollouts` namespace and issues the query from there, so the name
   resolved against the wrong namespace → `server misbehaving`, analysis
   `Error`, false abort of a GOOD model. Fix: FQDN
   `http://prometheus.pipeline-ml.svc.cluster.local:9090`. The fix was in
   the file but had never been applied to the running cluster — the cluster
   sat Degraded on the old bare-host template until the 2026-05-19
   re-apply. Confirmed closed: the bad-release analysis returned `assessed
   **Failed**` (real value below threshold), not `assessed **Error**`
   (Prometheus unreachable) — i.e. the query now resolves and the verdict
   is genuine. Lesson: a fix in the repo is not a fix on the cluster until
   re-applied.
8. **k3d API unreachable under load — CLOSED (2026-05-19).** Running the
   full M4 stack on a laptop (postgres + mlflow + 4 inference + prometheus +
   pushgateway + argo + train pods) made the k3d API server return `Unable
   to connect: EOF` mid-verification on 2026-05-18. Mitigations applied:
   (a) Docker Desktop CPU/RAM bumped; (b) inference Rollout `replicas`
   dropped 4 → 2 in `50-inference.yaml`; (c) cluster restarted clean.
   CLOSED: the full M4 verification (good promote + bad rollback +
   v2 restore, including a transient `train-bad` pod) ran end-to-end at
   `replicas: 2` with no API-server drop.
9. **Docker Desktop zombie-daemon after CPU/RAM bump (2026-05-19) — FIXED.**
   Bumping Docker Desktop's resource allocation triggered an auto-restart
   that didn't complete cleanly. The daemon ended up accepting commands but
   never replying — `docker ps`, `docker logs`, and `k3d cluster start` all
   hung with no output. Root cause: a stuck WSL2 backend from the partial
   restart. Recovery sequence (in admin PowerShell):
   `taskkill /F /IM "Docker Desktop.exe" /IM "com.docker.backend.exe" /IM
   "com.docker.build.exe" /IM "com.docker.dev-envs.exe" /IM "vpnkit.exe"`,
   `wsl --shutdown`, then relaunch Docker Desktop normally. After ~3 min
   the daemon came back; `docker ps` returned the empty header row,
   `k3d cluster list` showed `pipeline-ml 0/1`, and
   `k3d cluster start pipeline-ml` completed in ~16s.
   Lesson: any Docker Desktop resource change on Windows can leave the
   daemon half-alive. If `docker ps` hangs (not errors, hangs) for >60s,
   skip diagnosis and go straight to the hard-kill + `wsl --shutdown`
   recovery — it's faster than waiting.
10. **M5 capacity: rolling-update surge deadlocks a 3.83 GiB VM —
    FIXED & CLOSED (2026-05-19).** Adding Grafana on top of the M4
    stack pushed the single-node k3d (Docker Desktop VM = 3.83 GiB,
    runs the entire cluster) into mlflow CrashLoopBackOff that
    cascaded to inference Init wait. Two root causes:
    (a) **Rolling-update SURGE under tight RAM**: a Deployment/Rollout
    template change starts the new pod alongside the old (maxSurge=1
    default). Briefly running 2 mlflow + 2 inference left nothing with
    enough resources to pass readiness, so the old pods were never
    retired — permanent surge, permanent deadlock. Fix: mlflow
    `strategy: Recreate` (kill-then-create, never two at once).
    (b) **Default-tight probes**: under CPU starvation a 1-second
    `tcpSocket` connect can fail 3× → kubelet SIGTERMs a perfectly
    healthy server → `Completed exit 0` CrashLoop. Fix: generous
    `timeoutSeconds` + `failureThreshold` on liveness/readiness, plus
    a `startupProbe` on inference (the slow startup — load model from
    MLflow + score a 2k-row holdout — can take a long time under a
    starved laptop). Also: inference Rollout `replicas: 2 → 1` (canary
    already proven in M4); drift CronJob suspended (run on demand).
    Result: full M5 stack converges cleanly to ~2.5 GiB resident with
    headroom; no probe-kill restart storms. Lesson: a "fix in the
    file" isn't a fix on the cluster until applied (same lesson as #7);
    and on a resource-tight node, **surge tolerances + probe tolerances
    matter more than absolute pod RAM**.

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
deploy/k8s/  (00-namespace 10-config 20-postgres
              30-mlflow[strategy:Recreate, tolerant probes]
              40-train-job
              50-inference[Rollout+AnalysisTemplate, replicas=1 (M5),
                           startupProbe + tolerant liveness/readiness,
                           model-release MODEL_VERSION=2 / release="3"]
              60-drift-cronjob[SUSPENDED — run on demand]
              70-observability[Prometheus+Pushgateway]
              80-grafana[Deployment+Svc+provisioned datasource+dashboard]
              90-lineage-ui[Deployment+Svc, Streamlit]).yaml
deploy/train-bad-job.yaml   (one-off; NOT in deploy/k8s/ — never auto-applied)
services/lineage_ui/{app.py,Dockerfile}    (Streamlit lineage receipt page)
docs/m4-proof/  (m4-good-rollout.txt m4-good-monitor.log
                 m4-bad-rollout.txt m4-bad-events.txt m4-bad-monitor.log)
docs/m5-proof/  (m5-verification.txt — Grafana/Streamlit live-API proof)
scripts/inject_drift.py
```
Local (gitignored) state: `.venv/`, `.claude/`, `mlflow.db`, `mlartifacts/`,
`predictions.db`, `artifacts/baseline.npz`. Docker (M1) state = named volumes
`deploy_pgdata`/`deploy_mlartifacts`/`deploy_baseline`. K8s (M2) state =
PVCs in the `pipeline-ml` namespace. Binaries on user PATH at
`C:\Users\mobol\bin`: `k3d`, `kubectl-argo-rollouts` (v1.9.0, the
`kubectl argo rollouts` plugin).

## How to resume

**M0–M5 are committed and verified.** The portfolio milestones are
done. (Honest scope: this is a learning-cluster demo, not a production
deployment — see resolved-issue #10 for the laptop-VM trade-offs.)

**Open dashboards / re-demo** (cluster already up; if not, `k3d cluster
start pipeline-ml`, then `kubectl get nodes` — if it errors with
`host.docker.internal`, apply resolved-issue #4):

```
kubectl port-forward -n pipeline-ml svc/grafana    3000:3000
kubectl port-forward -n pipeline-ml svc/lineage-ui 8501:8501
kubectl port-forward -n pipeline-ml svc/prometheus 9090:9090
```

Open `http://localhost:3000/d/pipeline-ml` (Grafana, anonymous Admin)
and `http://localhost:8501` (Streamlit). Generate prediction traffic
from inside the inference pod (so the volume/latency panels light up),
and run a one-off drift job to refresh the PSI panel:

```
POD=$(kubectl get pods -n pipeline-ml -l app=inference -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n pipeline-ml $POD -- python -c "import urllib.request,json,random
for _ in range(100):
    b=json.dumps({'features':[round(random.uniform(-2.5,2.5),4) for _ in range(8)]}).encode()
    urllib.request.urlopen(urllib.request.Request('http://localhost:8000/predict',data=b,headers={'Content-Type':'application/json'}))"
kubectl delete job drift-m5 -n pipeline-ml --ignore-not-found
kubectl create job --from=cronjob/drift drift-m5 -n pipeline-ml
```

**Re-demo the M4 closed loop** (cluster already up; if not, `k3d cluster
start pipeline-ml`, then `kubectl get nodes` — if it errors with
`host.docker.internal`, apply resolved-issue #4):

1. Baseline: `kubectl argo rollouts get rollout inference -n pipeline-ml`
   → Healthy, serving v2.
2. **Good release:** bump `MODEL_VERSION` + the `pipeline-ml/release`
   annotation in `deploy/k8s/50-inference.yaml` to an existing good
   version, `kubectl apply -f deploy/k8s/50-inference.yaml`, watch
   `kubectl argo rollouts get rollout inference -n pipeline-ml --watch`
   → canary analysis PASS → auto-promote.
3. **Bad release / rollback:**
   `kubectl delete job train-bad -n pipeline-ml --ignore-not-found` then
   `kubectl apply -f deploy/train-bad-job.yaml` (registers a fresh bad
   version), point `50-inference.yaml` at it + bump the annotation, apply
   → canary analysis FAIL → Argo auto-aborts → previous good model keeps
   serving. Restore with the good `MODEL_VERSION`/annotation when done.
   - Prometheus (analysis source):
     `kubectl port-forward -n pipeline-ml svc/prometheus 9090:9090`,
     query `min(model_holdout_accuracy)`.
   - Last run's evidence is under `docs/m4-proof/`.
- Re-demo M0/M1/M2/M3: see the matching README quickstart sections.

**M5 — Dashboards & polish** (next): Grafana on the Prometheus data
(PSI/feature over time, rollout status, latency, volume), Streamlit
`/lineage` receipt page, README scripted demo + screenshots.
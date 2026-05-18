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
| M1 | Containerize (Docker + docker-compose) | ⏳ |
| M2 | Local Kubernetes (k3d) | ⏳ |
| M3 | Lineage receipt API | ⏳ |
| M4 | Closed loop (Argo Rollouts auto-rollback) | ⏳ |
| M5 | Dashboards & polish (Grafana, Streamlit) | ⏳ |

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

"""FastAPI inference service.

- Loads the model the registry currently aliases as `production`.
- POST /predict returns a prediction AND logs the request (features, prediction,
  model version, run id) -- the raw material the drift job and the lineage
  receipt are built from.
- GET /lineage/{prediction_id} returns the full provenance receipt.

Run from repo root:  python -m uvicorn services.inference.app:app --port 8000
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Response
from mlflow.tracking import MlflowClient
from pydantic import BaseModel, Field
from sklearn.metrics import accuracy_score

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path
from common import (  # noqa: E402
    FEATURE_NAMES, MLFLOW_TRACKING_URI, MODEL_ALIAS, MODEL_NAME, N_FEATURES,
    production_sample,
)
from db import get_prediction, init_db, log_prediction  # noqa: E402
from lineage import run_provenance  # noqa: E402

STATE: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    client = MlflowClient()

    # The Argo Rollout pins which model version a given revision serves via
    # MODEL_VERSION. With it unset we fall back to the `production` alias, so
    # running this image anywhere else behaves exactly as before.
    pinned = os.environ.get("MODEL_VERSION")
    if pinned:
        mv = client.get_model_version(MODEL_NAME, pinned)
        model_uri = f"models:/{MODEL_NAME}/{pinned}"
    else:
        mv = client.get_model_version_by_alias(MODEL_NAME, MODEL_ALIAS)
        model_uri = f"models:/{MODEL_NAME}@{MODEL_ALIAS}"

    STATE["model"] = mlflow.sklearn.load_model(model_uri)
    STATE["model_version"] = mv.version
    STATE["run_id"] = mv.run_id

    # Closed-loop signal: score THIS model on a fixed labeled holdout once at
    # startup and expose it at /metrics. The canary analysis reads this back
    # from Prometheus to decide promote vs auto-rollback.
    Xh, yh = production_sample(2000, seed=12345)
    Xh = pd.DataFrame(Xh, columns=FEATURE_NAMES)
    STATE["holdout_accuracy"] = float(accuracy_score(yh, STATE["model"].predict(Xh)))

    init_db()
    yield
    STATE.clear()


app = FastAPI(title="pipeline-ml inference", lifespan=lifespan)


class PredictRequest(BaseModel):
    features: list[float] = Field(..., description=f"{N_FEATURES} numeric features")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "model_version": STATE.get("model_version"),
        "alias": MODEL_ALIAS,
        "holdout_accuracy": STATE.get("holdout_accuracy"),
    }


@app.get("/metrics")
def metrics():
    """Prometheus exposition. Hand-rendered on purpose: keeps the image's
    dependency set (and its slow-to-build layer) unchanged. The metric is
    labelled by model_version so the canary analysis can query the candidate.
    """
    version = STATE.get("model_version", "unknown")
    acc = STATE.get("holdout_accuracy", 0.0)
    body = (
        "# HELP model_holdout_accuracy Accuracy of the served model on a "
        "fixed labeled holdout.\n"
        "# TYPE model_holdout_accuracy gauge\n"
        f'model_holdout_accuracy{{model="{MODEL_NAME}",'
        f'model_version="{version}"}} {acc}\n'
    )
    return Response(content=body, media_type="text/plain; version=0.0.4")


@app.post("/predict")
def predict(req: PredictRequest):
    if len(req.features) != N_FEATURES:
        raise HTTPException(
            status_code=422,
            detail=f"expected {N_FEATURES} features, got {len(req.features)}",
        )
    X = pd.DataFrame([req.features], columns=FEATURE_NAMES)
    model = STATE["model"]
    pred = int(model.predict(X)[0])
    proba = float(np.max(model.predict_proba(X)[0]))

    prediction_id = str(uuid.uuid4())
    log_prediction(
        prediction_id=prediction_id,
        model_version=STATE["model_version"],
        run_id=STATE["run_id"],
        features=req.features,
        prediction=pred,
        proba=proba,
    )

    return {
        "prediction_id": prediction_id,
        "prediction": pred,
        "proba": proba,
        "model_version": STATE["model_version"],
    }


@app.get("/lineage/{prediction_id}")
def lineage(prediction_id: str):
    """Full provenance receipt for one prediction: the served request joined
    to the model version that produced it, joined to how that model was
    trained (params, accuracy, git SHA, dataset fingerprint).
    """
    pred = get_prediction(prediction_id)
    if pred is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown prediction_id {prediction_id}",
        )
    provenance = run_provenance(pred["run_id"])
    return {
        "prediction": {
            "prediction_id": pred["prediction_id"],
            "ts": pred["ts"],
            "model": MODEL_NAME,
            "model_version": pred["model_version"],
            "features": json.loads(pred["features"]),
            "prediction": pred["prediction"],
            "proba": pred["proba"],
        },
        "model_lineage": provenance
        or {"error": f"MLflow run {pred['run_id']} not found"},
    }

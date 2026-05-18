"""FastAPI inference service.

- Loads the model the registry currently aliases as `production`.
- POST /predict returns a prediction AND logs the request (features, prediction,
  model version, run id) to a SQLite "prediction log" -- the raw material the
  drift job and (later) the lineage receipt are built from.

Run from repo root:  python -m uvicorn services.inference.app:app --port 8000
"""
from __future__ import annotations

import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from mlflow.tracking import MlflowClient
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path
from common import (  # noqa: E402
    FEATURE_NAMES, MLFLOW_TRACKING_URI, MODEL_ALIAS, MODEL_NAME, N_FEATURES,
)
from db import init_db, log_prediction  # noqa: E402

STATE: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mv = MlflowClient().get_model_version_by_alias(MODEL_NAME, MODEL_ALIAS)
    STATE["model"] = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}@{MODEL_ALIAS}")
    STATE["model_version"] = mv.version
    STATE["run_id"] = mv.run_id
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
    }


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

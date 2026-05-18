"""FastAPI inference service.

- Loads the model the registry currently aliases as `production`.
- POST /predict returns a prediction AND logs the request (features, prediction,
  model version, run id) to a SQLite "prediction log" -- the raw material the
  drift job and (later) the lineage receipt are built from.

Run from repo root:  python -m uvicorn services.inference.app:app --port 8000
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
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
    PRED_DB,
)

STATE: dict = {}


def init_db() -> None:
    with sqlite3.connect(PRED_DB) as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS predictions (
                   prediction_id TEXT PRIMARY KEY,
                   ts            TEXT NOT NULL,
                   model_version TEXT NOT NULL,
                   run_id        TEXT NOT NULL,
                   features      TEXT NOT NULL,
                   prediction    INTEGER NOT NULL,
                   proba         REAL NOT NULL)"""
        )


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
    ts = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(PRED_DB) as con:
        con.execute(
            "INSERT INTO predictions VALUES (?,?,?,?,?,?,?)",
            (prediction_id, ts, str(STATE["model_version"]), STATE["run_id"],
             json.dumps(req.features), pred, proba),
        )

    return {
        "prediction_id": prediction_id,
        "prediction": pred,
        "proba": proba,
        "model_version": STATE["model_version"],
    }

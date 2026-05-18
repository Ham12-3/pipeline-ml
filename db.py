"""Prediction store — one code path for SQLite (local) and Postgres (containers).

Which database is used is decided ENTIRELY by `PREDICTIONS_DB_URL` in
common.py (an env var). This module never names a backend; SQLAlchemy
translates the same statements to whichever URL is configured. That is what
lets the identical inference/drift code run on a laptop and in Compose.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (Column, Float, Integer, MetaData, String, Table, Text,
                        create_engine, insert, select)

sys.path.insert(0, str(Path(__file__).resolve().parent))  # repo root on path
from common import PREDICTIONS_DB_URL  # noqa: E402

_metadata = MetaData()

# Same columns as the original M0 SQLite table.
predictions = Table(
    "predictions", _metadata,
    Column("prediction_id", String(64), primary_key=True),
    Column("ts", String(40), nullable=False),
    Column("model_version", String(32), nullable=False),
    Column("run_id", String(64), nullable=False),
    Column("features", Text, nullable=False),
    Column("prediction", Integer, nullable=False),
    Column("proba", Float, nullable=False),
)

_engine = None


def engine():
    """Lazily build (once) the connection pool for the configured URL."""
    global _engine
    if _engine is None:
        _engine = create_engine(PREDICTIONS_DB_URL, future=True)
    return _engine


def init_db() -> None:
    """Create the predictions table if it doesn't exist (idempotent)."""
    _metadata.create_all(engine())


def log_prediction(prediction_id: str, model_version, run_id: str,
                    features: list[float], prediction: int,
                    proba: float) -> str:
    """Insert one prediction row. Returns the UTC timestamp used."""
    ts = datetime.now(timezone.utc).isoformat()
    with engine().begin() as con:
        con.execute(insert(predictions).values(
            prediction_id=prediction_id,
            ts=ts,
            model_version=str(model_version),
            run_id=run_id,
            features=json.dumps(features),
            prediction=int(prediction),
            proba=float(proba),
        ))
    return ts


def recent_feature_rows(limit: int) -> list[list[float]]:
    """Most-recent `limit` feature vectors, newest first (for the drift job)."""
    with engine().connect() as con:
        rows = con.execute(
            select(predictions.c.features)
            .order_by(predictions.c.ts.desc())
            .limit(limit)
        ).fetchall()
    return [json.loads(r[0]) for r in rows]

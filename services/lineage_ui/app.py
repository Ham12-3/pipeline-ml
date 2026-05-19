"""Streamlit lineage receipt page.

A thin, friendly face over the M3 provenance API. Streamlit turns this plain
script into a web page with no front-end code: paste (or generate) a
prediction id and see the full, honest receipt -- which model version served
it, how that model was trained, on what data, at which git commit.

It only ever calls the inference service over HTTP; it holds no model or DB
logic of its own.
"""
from __future__ import annotations

import os
import random

import requests
import streamlit as st

INFERENCE_URL = os.environ.get("INFERENCE_URL", "http://inference:8000").rstrip("/")
N_FEATURES = 8

st.set_page_config(page_title="pipeline-ml — lineage receipt", page_icon="🧾")
st.title("🧾 Prediction lineage receipt")
st.caption(
    "Every prediction can be traced back to the exact model + data + code "
    f"that produced it. Backend: `{INFERENCE_URL}`"
)


def _get(path: str):
    r = requests.get(f"{INFERENCE_URL}{path}", timeout=10)
    return r


# --- 1. Make a prediction (so there's an id to trace) ----------------------
st.subheader("1 · Make a prediction")
st.write(
    "Sends 8 random features to `POST /predict`. The returned "
    "`prediction_id` is what the receipt is keyed on."
)
if st.button("Send a prediction", type="primary"):
    feats = [round(random.uniform(-2.5, 2.5), 4) for _ in range(N_FEATURES)]
    try:
        r = requests.post(
            f"{INFERENCE_URL}/predict", json={"features": feats}, timeout=10
        )
        r.raise_for_status()
        body = r.json()
        st.session_state["last_id"] = body["prediction_id"]
        st.success(
            f"prediction = **{body['prediction']}** "
            f"(proba {body['proba']:.4f}, model v{body['model_version']})"
        )
        st.code(body["prediction_id"], language=None)
    except requests.RequestException as e:
        st.error(f"inference call failed: {e}")

# --- 2. Look up the receipt -----------------------------------------------
st.subheader("2 · Look up the lineage receipt")
pid = st.text_input(
    "prediction_id",
    value=st.session_state.get("last_id", ""),
    placeholder="paste a prediction_id, or generate one above",
)
if st.button("Fetch receipt") and pid:
    try:
        r = _get(f"/lineage/{pid.strip()}")
    except requests.RequestException as e:
        st.error(f"inference call failed: {e}")
        st.stop()

    if r.status_code == 404:
        st.warning(f"404 — no prediction with id `{pid.strip()}` (honest miss).")
        st.stop()
    if r.status_code != 200:
        st.error(f"unexpected {r.status_code}: {r.text[:300]}")
        st.stop()

    receipt = r.json()
    pred = receipt.get("prediction", {})
    lin = receipt.get("model_lineage", {})

    st.markdown("#### The served prediction")
    st.json(pred)

    st.markdown("#### How that model was made")
    if "error" in lin:
        st.error(lin["error"])
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("model version", f"v{pred.get('model_version', '?')}")
        metrics = lin.get("metrics", {}) or {}
        if "accuracy" in metrics:
            c2.metric("train accuracy", f"{metrics['accuracy']:.4f}")
        c3.metric("git commit", str(lin.get("git_sha", "unknown")))
        st.write(f"**dataset fingerprint:** `{lin.get('dataset_hash', '?')}`")
        st.write(f"**MLflow run:** `{lin.get('run_id', '?')}`")
        st.json(lin)

st.divider()
st.caption(
    "M5 · the Streamlit face of the M3 `/lineage/{id}` API. "
    "Unknown ids return an honest 404."
)

# ML Pipeline Reliability Platform — what it is

> Research + a plain-language explainer for the `pipeline-ml` project.

## The one-sentence answer

This is an **ML observability / ML reliability platform**: software that wraps around
already-deployed ML pipelines and continuously answers one question — *"is this model
still doing its job correctly?"* — by detecting silent quality decay, auto-rolling-back
bad model releases, tracing every prediction back to the exact data and code that
produced it, and watching cost/latency.

It is a **real, mature product category**, not a novel invention: Evidently AI, Arize AI,
WhyLabs, Fiddler AI, NannyML, Aporia, plus cloud-native versions (AWS SageMaker Model
Monitor) and Datadog's own ML monitoring. The portfolio value is in building one slice of
it really well, not in being first.

## The core problem: ML fails *silently*

Traditional software fails **loudly** — exceptions, HTTP 500s, crashes — and monitoring
catches it in minutes. ML systems fail **silently**: the service stays up, returns 200s,
latency is fine, but the *predictions* are quietly wrong, and nobody notices for weeks.
*"The model that hit 95% accuracy in your notebook will silently degrade to 60% in
production — and you may not notice for months."*

Three dominant silent-failure modes:

- **Data drift (covariate shift)** — the input distribution moves; the model now answers
  questions about a world it no longer recognizes (a fraud model trained on 2019
  behavior facing 2026 spending).
- **Concept drift** — the *relationship* between input and correct answer changes (same
  inputs, different right answer, because the world's rules changed).
- **Training-serving skew** — the most common and most damaging failure: a feature is
  computed one way in training and a subtly different way in the low-latency serving
  path (e.g. a timeout makes `avg_transaction_amount_last_7_days` silently flip to `0`
  and the fraud model labels active users as low-risk).

## How this differs from normal DevOps observability

| DevOps / APM (Datadog, Prometheus) | ML observability (this platform) |
|---|---|
| Is the service up? Latency? Errors? | Are the *predictions* still good? |
| Signals are explicit (exceptions) | Signals are statistical (distribution shift) |
| "Correct" is binary and known instantly | "Correct" (the label) often arrives late or never |
| A deploy = code change | A deploy = code **+ data + model weights + features** versioned together |

The "Datadog for ML" pitch is great for explaining the idea but breaks on one point:
infra monitoring knows *immediately* whether a request succeeded; ML monitoring usually
**doesn't have the ground-truth label yet** (you learn if a loan defaulted months
later), so it must lean on *proxy* signals — input drift, prediction drift, confidence
distribution — instead of direct accuracy. That delayed/absent-label problem is the
defining technical challenge of the field.

## The five components

1. **Drift detection engine** — numeric/categorical features: **PSI** (sample-size
   stable; `<0.1` stable, `0.1–0.2` moderate, `>0.2` significant) and the **KS test**
   (more sensitive, especially in the tails, over-fires on huge samples) — run both and
   reconcile. Unstructured data: embed it, then measure **embedding drift** (cosine /
   Euclidean / MMD / domain classifier). Distinguish data vs prediction vs concept drift.
2. **Automated rollback (the DevOps half)** — GitOps + progressive delivery: **shadow**
   (mirror traffic, serve none), **canary** (1→5→25→100%), **blue-green**. Tooling:
   **Argo Rollouts** vs **Flagger**, both gate promotion on metrics and auto-revert on
   breach. The ML twist: the gate is a *model-quality* metric, not just HTTP success.
3. **Lineage & reproducibility tracker** — any prediction → exact model version →
   training-data hash → feature-pipeline commit → hyperparameters → environment. Built
   on **MLflow Model Registry** (+ dataset/version tracking) and **Feast** (feature
   store, online/offline consistency). Hard because training, feature, and serving code
   live in three repos with three release cadences.
4. **Cost & latency optimizer** — GPU utilization, batch size, latency/throughput per
   model version; recommend quantization, distillation, dynamic batching, cheaper
   instances, scale-to-zero.
5. **Incident replay** — replay sampled production inputs against any historical model
   version to reproduce a regression and bisect the breaking change (depends on #3).

## Why it's technically hard

Streaming ingest at scale (Kafka/Kinesis); a time-series store with **windowed**
statistical jobs; Kubernetes integration for the rollback control loop; statistical
tests that stay sane on high-cardinality *unlabeled* data; a readable cross-system
lineage-graph UI; and the "no ground truth yet" problem.

## Honest portfolio assessment

The category is crowded with funded companies, so a from-scratch full clone is not
credible solo. The credible move is a **narrow, deep MVP** whose differentiator is the
**closed loop** — drift detected → automatic canary hold/rollback — wired end to end.
Most open-source tools do detection *or* deployment; showing them *connected* is the
memorable demo.

---

## In simple terms (new to MLOps)

**What's an "ML pipeline"?** Training a model in a notebook is ~5% of a real ML system.
The other 95% is plumbing: get data → clean it → make "features" → train → test →
package → deploy → watch it. **MLOps is "DevOps for that pipeline."**

**The one idea to burn in:** normal software *crashes* when it breaks — you know. An ML
model **does not crash when it goes wrong**; it keeps cheerfully returning answers that
quietly get worse. It's a smoke detector with a dead battery — everything *looks* fine,
which is the danger. This platform is the thing always sniffing for the smoke.

Whole-system analogy: a **car dashboard for a model**. The model is the engine; it can
be slowly dying while the car still drives. The dashboard warns you *before* you're
stranded.

The five parts, plainly:

1. **Drift detection = the check-engine light.** Compares what the model sees *now* to
   what it saw in training; too different → warn.
2. **Automated rollback = an undo button that presses itself.** A new model is shown to
   a tiny slice of traffic (a "canary"); if it does worse, traffic snaps back to the old
   model automatically.
3. **Lineage tracker = a receipt for every prediction.** Which model version, trained on
   which data, with which code/settings — git history for "why did the model say that?"
4. **Cost/latency optimizer = the fuel-economy gauge.** "You're burning expensive GPU;
   here's a cheaper way to the same answer."
5. **Incident replay = a flight recorder.** Re-run the exact real-world inputs against
   older model versions to find which change broke it.

**Mini-glossary**
- **Drift** — the data (or the world) changed out from under the model.
- **Data vs concept drift** — inputs changed vs. the right answer for the same input
  changed.
- **Training-serving skew** — a feature computed differently in training vs live; the #1
  silent killer.
- **PSI / KS test** — two stats that put a *number* on "how different is now vs before"
  (PSI rule of thumb: `<0.1` fine, `0.1–0.2` watch, `>0.2` act).
- **Embedding** — turning text/images into numbers so "different" is measurable.
- **Canary / shadow / blue-green** — careful ways to release a new model.
- **Ground truth** — the real correct answer, which in ML often arrives late or never —
  which is *why* monitoring ML is hard.

**Suggested learning order:** (1) train & serve one model behind FastAPI; (2) log every
input + prediction; (3) compute PSI on one feature on a schedule and alert;
(4) Dockerize, then run on local k8s (k3d); (5) manual canary, then automate the
rollback gate. Each step is a standalone portfolio win — and is exactly the M0→M5
milestone plan for this repo.

## Sources

- [Comparison of ML Model Monitoring Tools (Evidently, Alibi Detect, NannyML, WhyLabs, Fiddler)](https://medium.com/@tanish.kandivlikar1412/comprehensive-comparison-of-ml-model-monitoring-tools-evidently-ai-alibi-detect-nannyml-a016d7dd8219)
- [The 17 Best AI Observability Tools (Monte Carlo)](https://www.montecarlodata.com/blog-best-ai-observability-tools/)
- [Drift Detection: KS Test, PSI, and Interpreting Signals](https://www.statstest.com/drift-detection-ks-test-psi-interpret-signals)
- [Measuring Data Drift with the Population Stability Index (Fiddler AI)](https://www.fiddler.ai/blog/measuring-data-drift-population-stability-index)
- [We compared 5 methods to detect data drift on large datasets (Evidently AI)](https://www.evidentlyai.com/blog/data-drift-detection-large-datasets)
- [5 methods to detect drift in ML embeddings (Evidently AI)](https://www.evidentlyai.com/blog/embedding-drift-detection)
- [Argo Rollouts (official)](https://argoproj.github.io/rollouts/)
- [ArgoCD + Argo Rollouts vs Flagger: Progressive Delivery Showdown](https://oneuptime.com/blog/post/2026-02-26-argocd-rollouts-vs-flagger/view)
- [MLflow Model Registry (official docs)](https://mlflow.org/docs/latest/ml/model-registry/)
- [Why Your ML Model Works in Training But Fails in Production (Towards Data Science)](https://towardsdatascience.com/why-your-ml-model-works-in-training-but-fails-in-production/)
- [Why do ML Models Fail in Production: 3 Common Causes (NannyML)](https://www.nannyml.com/blog/3-common-causes-of-ml-model-failure-in-production)
- [MLOps: Continuous delivery and automation pipelines (Google Cloud)](https://docs.cloud.google.com/architecture/mlops-continuous-delivery-and-automation-pipelines-in-machine-learning)
- [MLOps Principles (ml-ops.org)](https://ml-ops.org/content/mlops-principles)

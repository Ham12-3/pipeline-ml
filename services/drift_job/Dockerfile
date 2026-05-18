# Same base + dependency-caching pattern as the inference image. The drift job
# is a one-shot batch program, not a server: it runs, prints a verdict, exits.
# (In M2 this same image becomes a Kubernetes CronJob.)
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code the job imports: common.py (config), db.py (reads the shared prediction
# store), ml/ (baseline + drift metrics), and the job itself.
COPY common.py .
COPY db.py .
COPY ml/ ml/
COPY services/drift_job/ services/drift_job/

# Non-root user; pre-own the shared baseline mount (see inference Dockerfile).
# appuser gets the same uid in both images, so the file train writes here is
# readable by the drift job.
RUN useradd --create-home appuser \
    && mkdir -p /shared/artifacts \
    && chown -R appuser /shared/artifacts
USER appuser

# Default run analyses the 1000 most recent predictions. Compose / Kubernetes
# can override the args (e.g. --limit) without rebuilding the image.
CMD ["python", "services/drift_job/drift_job.py", "--limit", "1000"]

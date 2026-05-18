# --- Base image: a minimal Linux with Python 3.13 already installed ----------
# "slim" = same Python, far fewer extra OS packages -> smaller, faster image.
FROM python:3.13-slim

# Inside the container, do everything under /app. Think of it as the repo root.
WORKDIR /app

# Copy ONLY requirements first, then install. Docker caches each step ("layer");
# as long as requirements.txt is unchanged, the slow pip install is reused on
# rebuilds even when you edit your Python code. Order matters for speed.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the code this service actually needs. common.py, db.py and ml/ are
# imported by the app (it walks up to the repo root), so all must be present.
COPY common.py .
COPY db.py .
COPY ml/ ml/
COPY services/inference/ services/inference/

# Run as a non-root user (good practice: if the app is compromised, the
# attacker isn't root inside the container). We also pre-create the volume
# mount points owned by appuser: Docker copies an image directory's ownership
# when it first initializes an empty named volume, so the MLflow artifact
# store (/mlartifacts) and the shared drift baseline dir (/shared/artifacts)
# come up writable by this user instead of root-owned.
RUN useradd --create-home appuser \
    && mkdir -p /mlartifacts /shared/artifacts \
    && chown -R appuser /mlartifacts /shared/artifacts
USER appuser

# Document the port the API listens on.
EXPOSE 8000

# Start the server. --host 0.0.0.0 is REQUIRED in a container: the default
# 127.0.0.1 would only accept connections from inside the container itself,
# so nothing outside could ever reach it.
CMD ["uvicorn", "services.inference.app:app", "--host", "0.0.0.0", "--port", "8000"]

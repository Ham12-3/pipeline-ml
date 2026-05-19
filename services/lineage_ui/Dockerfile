# Streamlit lineage page. Its own tiny image (Streamlit is a heavy-ish dep we
# deliberately keep OUT of the inference image so that image's slow layer
# stays cached). Built from the repo root for consistency with the others:
#   docker build -t pipeline-ml-lineage-ui:dev -f services/lineage_ui/Dockerfile .
FROM python:3.13-slim
WORKDIR /app

RUN pip install --no-cache-dir streamlit==1.40.2 requests==2.32.3

COPY services/lineage_ui/app.py .

RUN useradd --create-home appuser
USER appuser

EXPOSE 8501

# --server.address=0.0.0.0 so it's reachable from outside the container;
# headless + no telemetry so it starts clean in a cluster.
CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.headless=true", "--browser.gatherUsageStats=false"]

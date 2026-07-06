FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies first (cached layer — only rebuilds on requirements change)
COPY requirements-crawler.txt .
RUN pip install --no-cache-dir -r requirements-crawler.txt

# Redirect caches into /app so the non-root user can read them at runtime.
# Without these, browsers and models land in /root/.cache which appuser can't access.
ENV PLAYWRIGHT_BROWSERS_PATH=/app/pw-browsers
ENV HF_HOME=/app/hf-cache
RUN playwright install --with-deps chromium

# Pre-download SentenceTransformer model into the image layer
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"

# Copy project files (structure must match what scrapers/ reference at runtime)
COPY scrapers/ scrapers/
COPY scripts/ scripts/
COPY ["Streamlit Interface/districts.json", "Streamlit Interface/districts.json"]
COPY extractor.py db_utils.py crawler.py ./

# Run as non-root user
RUN useradd --no-create-home --shell /bin/false appuser \
    && chown -R appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "crawler.py"]
# Default: incremental crawl. Override in Cloud Scheduler for weekly full crawl:
#   gcloud run jobs update crawler-job --args="--mode,full"
CMD ["--mode", "incremental"]

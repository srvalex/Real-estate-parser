FROM python:3.12-slim

WORKDIR /app

# Redirect HuggingFace cache into /app so the non-root user can read it at runtime.
ENV HF_HOME=/app/hf-cache

# Prevent OpenMP/MKL from spawning extra threads — avoids hangs in container sandboxes
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV NUMEXPR_NUM_THREADS=1
ENV TOKENIZERS_PARALLELISM=false

# CPU-only torch first — avoids pulling ~2 GB of CUDA packages
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# NOTE: build context must be the project root, not embedding-service/:
#   docker build -f embedding-service/Dockerfile -t IMAGE .
COPY embedding-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake both models into /app/hf-cache during build (HF_HUB_OFFLINE not yet set)
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2'); \
from transformers import CLIPModel, CLIPProcessor; \
CLIPModel.from_pretrained('openai/clip-vit-base-patch32'); \
CLIPProcessor.from_pretrained('openai/clip-vit-base-patch32')"

COPY embedding-service/main.py .
COPY embedding-service/embed_job.py .
COPY db_utils.py .

# Run as non-root user — chown after all files and model cache are in place
RUN useradd --no-create-home --shell /bin/false appuser \
    && chown -R appuser /app
USER appuser

# Force offline mode at RUNTIME — models are pre-baked, no network calls needed.
# Set after the download RUN step so the build itself can still fetch models.
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1
ENV PYTHONUNBUFFERED=1

# Default: batch embedding job (Cloud Run Job mode).
# To run as an HTTP service instead: override CMD with
#   ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
CMD ["python", "embed_job.py"]

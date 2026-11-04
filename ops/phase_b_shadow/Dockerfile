FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt requirements-phase-b.txt ./
RUN pip install --no-cache-dir -r requirements-phase-b.txt
COPY extract_document_v2.py route_document_v2.py build_multimodal_chunks_v2.py source_registry_v1.yaml ./
COPY phase_b_shadow/ ./phase_b_shadow/
RUN useradd --uid 10001 --create-home worker
USER 10001:10001
ENV PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 CUDA_VISIBLE_DEVICES="" \
    HOME=/tmp HF_HOME=/tmp/hf XDG_CACHE_HOME=/tmp/.cache OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
CMD ["celery", "-A", "phase_b_shadow.celery_app:app", "worker", "--loglevel=INFO", "--concurrency=1", "--queues=phase_b_shadow_pdf"]

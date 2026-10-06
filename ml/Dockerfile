FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY ml/requirements-runtime.txt ./ml/requirements-runtime.txt
RUN pip install --no-cache-dir -r ml/requirements-runtime.txt
COPY ml/ ./ml/

ENV MODEL_PATH=/app/ml/artifacts/models/champion_model.joblib
ENV PREPROCESSOR_PATH=/app/ml/artifacts/models/preprocessor.joblib
ENV PORT=5001

EXPOSE 5001
CMD ["python", "-m", "ml.api"]

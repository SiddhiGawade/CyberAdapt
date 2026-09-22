# ─────────────────────────────────────────────────────────────────
# CyberAdapt Edge Sensor — Docker Container
# ─────────────────────────────────────────────────────────────────
FROM python:3.10-slim

# Install libpcap for Scapy's raw socket capture
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpcap-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/cyberadapt

# Install Python dependencies
RUN pip install --no-cache-dir scapy requests

# Copy sensor code
COPY sensor.py .

# Default environment (override at runtime)
ENV SENSOR_KEY=""
ENV INGEST_URL=""
ENV INTERFACE="eth0"
ENV BATCH_INTERVAL="2"
ENV BATCH_SIZE="100"

ENTRYPOINT ["python", "sensor.py"]

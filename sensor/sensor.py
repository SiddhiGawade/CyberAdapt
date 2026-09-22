#!/usr/bin/env python3
"""
CyberAdapt Edge Sensor — Passive Network Flow Sniffer
=====================================================
Captures IP packets via Scapy, aggregates them into bidirectional
5-tuple flows, computes a 52-feature statistical vector per flow,
and micro-batches them to the CyberAdapt ingestion gateway.

Environment Variables / CLI Arguments:
  SENSOR_KEY      — CyberAdapt sensor API key (required)
  INGEST_URL      — Telemetry ingestion endpoint (required)
  INTERFACE       — Network interface to sniff (default: eth0)
  BATCH_INTERVAL  — Seconds between batch flushes (default: 2)
  BATCH_SIZE      — Max flows per batch before forced flush (default: 100)

52-Feature Vector Schema (indices 0-51):
  0:  Flow ID Hash (fnv1a-like numeric identifier)
  1:  Flow Duration (microseconds)
  2:  Total Forward Packets
  3:  Total Backward Packets
  4:  Total Length of Forward Packets
  5:  Total Length of Backward Packets
  6:  Forward Packet Length Max
  7:  Forward Packet Length Min
  8:  Forward Packet Length Mean
  9:  Forward Packet Length Std
  10: Backward Packet Length Max
  11: Backward Packet Length Min
  12: Backward Packet Length Mean
  13: Backward Packet Length Std
  14: Flow Bytes/s
  15: Flow Packets/s
  16: Flow IAT Mean
  17: Flow IAT Std
  18: Flow IAT Max
  19: Flow IAT Min
  20: Forward IAT Total
  21: Forward IAT Mean
  22: Forward IAT Std
  23: Forward IAT Max
  24: Forward IAT Min
  25: Backward IAT Total
  26: Backward IAT Mean
  27: Backward IAT Std
  28: Backward IAT Max
  29: Backward IAT Min
  30: Forward PSH Flags
  31: Backward PSH Flags
  32: Forward URG Flags
  33: Backward URG Flags
  34: Forward Header Length (bytes)
  35: Backward Header Length (bytes)
  36: Forward Packets/s
  37: Backward Packets/s
  38: Min Packet Length (global)
  39: Max Packet Length (global)
  40: Packet Length Mean (global)
  41: Packet Length Std (global)
  42: Packet Length Variance (global)
  43: FIN Flag Count
  44: SYN Flag Count
  45: RST Flag Count
  46: PSH Flag Count
  47: ACK Flag Count
  48: URG Flag Count
  49: Down/Up Ratio
  50: Forward Avg Segment Size
  51: Backward Avg Segment Size
"""

import os
import sys
import time
import uuid
import math
import json
import hashlib
import threading
import logging
from collections import defaultdict
from queue import Queue, Empty

import requests

# ── Scapy (suppress startup banner) ──
logging.getLogger("scapy.runtime").setLevel(logging.ERROR)
from scapy.all import sniff, IP, TCP, UDP  # noqa: E402

# ─────────────────────────── Configuration ───────────────────────────
SENSOR_KEY     = os.environ.get("SENSOR_KEY", "")
INGEST_URL     = os.environ.get("INGEST_URL", "")
INTERFACE      = os.environ.get("INTERFACE", "eth0")
BATCH_INTERVAL = float(os.environ.get("BATCH_INTERVAL", "2"))
BATCH_SIZE     = int(os.environ.get("BATCH_SIZE", "100"))
SENSOR_ID      = os.environ.get("SENSOR_ID", f"sensor-{uuid.uuid4().hex[:8]}")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("cyberadapt-sensor")


# ─────────────────────────── Flow State ──────────────────────────────
class FlowRecord:
    """Bidirectional network flow accumulator."""

    __slots__ = (
        "flow_id", "src_ip", "src_port", "dst_ip", "dst_port", "proto",
        "start_time", "last_time",
        "fwd_packets", "bwd_packets",
        "fwd_lengths", "bwd_lengths",
        "fwd_iats", "bwd_iats",
        "fwd_psh", "bwd_psh", "fwd_urg", "bwd_urg",
        "fwd_header_bytes", "bwd_header_bytes",
        "fin_count", "syn_count", "rst_count", "psh_count", "ack_count", "urg_count",
        "all_iats", "all_lengths",
        "_last_fwd_time", "_last_bwd_time",
    )

    def __init__(self, src_ip, src_port, dst_ip, dst_port, proto, ts):
        self.flow_id = f"{src_ip}:{src_port}-{dst_ip}:{dst_port}-{proto}"
        self.src_ip = src_ip
        self.src_port = src_port
        self.dst_ip = dst_ip
        self.dst_port = dst_port
        self.proto = proto
        self.start_time = ts
        self.last_time = ts

        self.fwd_packets = 0
        self.bwd_packets = 0
        self.fwd_lengths = []
        self.bwd_lengths = []
        self.fwd_iats = []
        self.bwd_iats = []

        self.fwd_psh = 0
        self.bwd_psh = 0
        self.fwd_urg = 0
        self.bwd_urg = 0
        self.fwd_header_bytes = 0
        self.bwd_header_bytes = 0

        self.fin_count = 0
        self.syn_count = 0
        self.rst_count = 0
        self.psh_count = 0
        self.ack_count = 0
        self.urg_count = 0

        self.all_iats = []
        self.all_lengths = []

        self._last_fwd_time = ts
        self._last_bwd_time = ts

    def add_packet(self, pkt_len, header_len, flags, is_forward, ts):
        """Incorporate a packet into this flow."""
        iat = ts - self.last_time
        self.last_time = ts
        self.all_iats.append(iat)
        self.all_lengths.append(pkt_len)

        if is_forward:
            self.fwd_packets += 1
            self.fwd_lengths.append(pkt_len)
            fwd_iat = ts - self._last_fwd_time
            self.fwd_iats.append(fwd_iat)
            self._last_fwd_time = ts
            self.fwd_header_bytes += header_len
            if flags and "P" in flags:
                self.fwd_psh += 1
            if flags and "U" in flags:
                self.fwd_urg += 1
        else:
            self.bwd_packets += 1
            self.bwd_lengths.append(pkt_len)
            bwd_iat = ts - self._last_bwd_time
            self.bwd_iats.append(bwd_iat)
            self._last_bwd_time = ts
            self.bwd_header_bytes += header_len
            if flags and "P" in flags:
                self.bwd_psh += 1
            if flags and "U" in flags:
                self.bwd_urg += 1

        # Global TCP flag counters
        if flags:
            if "F" in flags:
                self.fin_count += 1
            if "S" in flags:
                self.syn_count += 1
            if "R" in flags:
                self.rst_count += 1
            if "P" in flags:
                self.psh_count += 1
            if "A" in flags:
                self.ack_count += 1
            if "U" in flags:
                self.urg_count += 1


# ─────────────────────── Stats helpers ───────────────────────────────
def _mean(arr):
    return sum(arr) / len(arr) if arr else 0.0

def _std(arr):
    if len(arr) < 2:
        return 0.0
    m = _mean(arr)
    return math.sqrt(sum((x - m) ** 2 for x in arr) / len(arr))

def _variance(arr):
    s = _std(arr)
    return s * s

def _safe_div(a, b):
    return a / b if b else 0.0


def flow_to_features(f: FlowRecord) -> list:
    """Convert a FlowRecord into the 52-element feature vector."""
    duration_us = max((f.last_time - f.start_time) * 1e6, 0)  # clamp negative
    duration_s = duration_us / 1e6 if duration_us > 0 else 1e-9

    total_fwd_len = sum(f.fwd_lengths)
    total_bwd_len = sum(f.bwd_lengths)
    total_pkts = f.fwd_packets + f.bwd_packets

    # Hash-based numeric flow id
    fid_hash = int(hashlib.md5(f.flow_id.encode()).hexdigest()[:8], 16)

    return [
        float(fid_hash),                          # 0:  Flow ID hash
        duration_us,                               # 1:  Flow Duration (µs)
        float(f.fwd_packets),                      # 2:  Total Fwd Packets
        float(f.bwd_packets),                      # 3:  Total Bwd Packets
        float(total_fwd_len),                      # 4:  Total Length Fwd
        float(total_bwd_len),                      # 5:  Total Length Bwd
        float(max(f.fwd_lengths) if f.fwd_lengths else 0),   # 6:  Fwd Pkt Len Max
        float(min(f.fwd_lengths) if f.fwd_lengths else 0),   # 7:  Fwd Pkt Len Min
        _mean(f.fwd_lengths),                      # 8:  Fwd Pkt Len Mean
        _std(f.fwd_lengths),                       # 9:  Fwd Pkt Len Std
        float(max(f.bwd_lengths) if f.bwd_lengths else 0),   # 10: Bwd Pkt Len Max
        float(min(f.bwd_lengths) if f.bwd_lengths else 0),   # 11: Bwd Pkt Len Min
        _mean(f.bwd_lengths),                      # 12: Bwd Pkt Len Mean
        _std(f.bwd_lengths),                       # 13: Bwd Pkt Len Std
        _safe_div(total_fwd_len + total_bwd_len, duration_s),  # 14: Flow Bytes/s
        _safe_div(total_pkts, duration_s),         # 15: Flow Packets/s
        _mean(f.all_iats) * 1e6,                   # 16: Flow IAT Mean (µs)
        _std(f.all_iats) * 1e6,                    # 17: Flow IAT Std
        float(max(f.all_iats) * 1e6 if f.all_iats else 0),   # 18: Flow IAT Max
        float(min(f.all_iats) * 1e6 if f.all_iats else 0),   # 19: Flow IAT Min
        sum(f.fwd_iats) * 1e6,                     # 20: Fwd IAT Total
        _mean(f.fwd_iats) * 1e6,                   # 21: Fwd IAT Mean
        _std(f.fwd_iats) * 1e6,                    # 22: Fwd IAT Std
        float(max(f.fwd_iats) * 1e6 if f.fwd_iats else 0),   # 23: Fwd IAT Max
        float(min(f.fwd_iats) * 1e6 if f.fwd_iats else 0),   # 24: Fwd IAT Min
        sum(f.bwd_iats) * 1e6,                     # 25: Bwd IAT Total
        _mean(f.bwd_iats) * 1e6,                   # 26: Bwd IAT Mean
        _std(f.bwd_iats) * 1e6,                    # 27: Bwd IAT Std
        float(max(f.bwd_iats) * 1e6 if f.bwd_iats else 0),   # 28: Bwd IAT Max
        float(min(f.bwd_iats) * 1e6 if f.bwd_iats else 0),   # 29: Bwd IAT Min
        float(f.fwd_psh),                          # 30: Fwd PSH Flags
        float(f.bwd_psh),                          # 31: Bwd PSH Flags
        float(f.fwd_urg),                          # 32: Fwd URG Flags
        float(f.bwd_urg),                          # 33: Bwd URG Flags
        float(f.fwd_header_bytes),                 # 34: Fwd Header Length
        float(f.bwd_header_bytes),                 # 35: Bwd Header Length
        _safe_div(f.fwd_packets, duration_s),      # 36: Fwd Packets/s
        _safe_div(f.bwd_packets, duration_s),      # 37: Bwd Packets/s
        float(min(f.all_lengths) if f.all_lengths else 0),  # 38: Min Pkt Length
        float(max(f.all_lengths) if f.all_lengths else 0),  # 39: Max Pkt Length
        _mean(f.all_lengths),                      # 40: Pkt Length Mean
        _std(f.all_lengths),                       # 41: Pkt Length Std
        _variance(f.all_lengths),                  # 42: Pkt Length Variance
        float(f.fin_count),                        # 43: FIN Flag Count
        float(f.syn_count),                        # 44: SYN Flag Count
        float(f.rst_count),                        # 45: RST Flag Count
        float(f.psh_count),                        # 46: PSH Flag Count
        float(f.ack_count),                        # 47: ACK Flag Count
        float(f.urg_count),                        # 48: URG Flag Count
        _safe_div(f.bwd_packets, f.fwd_packets) if f.fwd_packets else 0.0,  # 49: Down/Up Ratio
        _safe_div(total_fwd_len + total_bwd_len, total_pkts),               # 50: Avg Pkt Size
        _safe_div(total_fwd_len, f.fwd_packets),   # 51: Fwd Avg Segment Size
    ]


# ─────────────────────── 5-Tuple Key ────────────────────────────────
def _flow_key(pkt):
    """Return a canonical bidirectional 5-tuple key + direction flag."""
    if not pkt.haslayer(IP):
        return None, None

    ip = pkt[IP]
    proto = ip.proto
    sport = dport = 0
    if pkt.haslayer(TCP):
        sport, dport = pkt[TCP].sport, pkt[TCP].dport
    elif pkt.haslayer(UDP):
        sport, dport = pkt[UDP].sport, pkt[UDP].dport

    fwd = f"{ip.src}:{sport}-{ip.dst}:{dport}-{proto}"
    bwd = f"{ip.dst}:{dport}-{ip.src}:{sport}-{proto}"

    # Canonical ordering: smaller string is always the key
    if fwd <= bwd:
        return fwd, True   # forward
    else:
        return bwd, False  # backward (we matched the reverse)


# ─────────────────────── Sender Thread ───────────────────────────────
class BatchSender(threading.Thread):
    """Background thread that drains the flow queue and POSTs micro-batches."""

    def __init__(self, queue: Queue):
        super().__init__(daemon=True)
        self.queue = queue
        self.session = requests.Session()
        self.session.headers.update({
            "X-Sensor-Key": SENSOR_KEY,
            "Content-Type": "application/json",
        })

    def run(self):
        while True:
            batch = []
            # Block until at least one flow is available
            try:
                first = self.queue.get(timeout=BATCH_INTERVAL)
                batch.append(first)
            except Empty:
                continue

            # Drain up to BATCH_SIZE
            while len(batch) < BATCH_SIZE:
                try:
                    batch.append(self.queue.get_nowait())
                except Empty:
                    break

            self._send(batch)

    def _send(self, flows: list):
        payload = {
            "sensor_id": SENSOR_ID,
            "batch_timestamp": time.time(),
            "flow_count": len(flows),
            "flows": flows,
        }
        for attempt in range(5):
            try:
                resp = self.session.post(INGEST_URL, json=payload, timeout=10)
                if resp.status_code in (200, 202):
                    log.info(
                        "Batch sent: %d flows → %s (HTTP %d)",
                        len(flows), INGEST_URL, resp.status_code,
                    )
                    return
                else:
                    log.warning("Ingest returned HTTP %d: %s", resp.status_code, resp.text[:200])
            except requests.RequestException as e:
                log.warning("Send attempt %d failed: %s", attempt + 1, e)

            backoff = min(2 ** attempt, 30)
            log.info("Retrying in %ds…", backoff)
            time.sleep(backoff)

        log.error("Dropped batch of %d flows after 5 retries", len(flows))


# ─────────────────────── Main Capture Loop ───────────────────────────
def main():
    if not SENSOR_KEY:
        log.error("SENSOR_KEY is required. Set via environment variable.")
        sys.exit(1)
    if not INGEST_URL:
        log.error("INGEST_URL is required. Set via environment variable.")
        sys.exit(1)

    log.info("════════════════════════════════════════════════")
    log.info(" CyberAdapt Edge Sensor")
    log.info("  Sensor ID  : %s", SENSOR_ID)
    log.info("  Interface  : %s", INTERFACE)
    log.info("  Ingest URL : %s", INGEST_URL)
    log.info("  Batch Size : %d / %ds", BATCH_SIZE, BATCH_INTERVAL)
    log.info("════════════════════════════════════════════════")

    flow_table = {}           # key → FlowRecord
    send_queue = Queue()
    sender = BatchSender(send_queue)
    sender.start()

    last_flush = time.time()

    def flush_flows():
        """Finalize all flows, compute features, enqueue for sending."""
        nonlocal last_flush
        for key, flow in flow_table.items():
            features = flow_to_features(flow)
            send_queue.put({"flow_id": flow.flow_id, "features": features})
        count = len(flow_table)
        flow_table.clear()
        last_flush = time.time()
        if count:
            log.info("Flushed %d flows to send queue", count)

    def process_packet(pkt):
        """Callback for each sniffed packet."""
        nonlocal last_flush

        key, is_forward = _flow_key(pkt)
        if key is None:
            return

        ts = float(pkt.time)
        ip = pkt[IP]
        pkt_len = len(pkt)

        # TCP header length & flags
        header_len = 0
        flags = ""
        if pkt.haslayer(TCP):
            tcp = pkt[TCP]
            header_len = tcp.dataofs * 4 if tcp.dataofs else 20
            flags = str(tcp.flags)
        elif pkt.haslayer(UDP):
            header_len = 8

        if key not in flow_table:
            parts = key.split("-")
            src_parts = parts[0].rsplit(":", 1)
            dst_parts = parts[1].rsplit(":", 1)
            flow_table[key] = FlowRecord(
                src_ip=src_parts[0],
                src_port=int(src_parts[1]),
                dst_ip=dst_parts[0],
                dst_port=int(dst_parts[1]),
                proto=int(parts[2]),
                ts=ts,
            )

        flow_table[key].add_packet(pkt_len, header_len, flags, is_forward, ts)

        # Flush on batch size or interval
        if len(flow_table) >= BATCH_SIZE or (time.time() - last_flush) >= BATCH_INTERVAL:
            flush_flows()

    log.info("Starting packet capture on %s…", INTERFACE)

    try:
        sniff(
            iface=INTERFACE,
            filter="ip",
            prn=process_packet,
            store=False,
        )
    except KeyboardInterrupt:
        log.info("Shutting down…")
        flush_flows()
    except Exception as e:
        log.error("Capture error: %s", e)
        flush_flows()
        sys.exit(1)


if __name__ == "__main__":
    main()

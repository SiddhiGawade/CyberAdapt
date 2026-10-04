# Sensor and End-to-End Data Flow

This guide follows one flow from the input source to storage, prediction, drift monitoring, and the dashboard. The most important clarification is that the project contains both a packet-capture sensor and synthetic Labrooms-shaped generators; they are not the same input source.

## 1. Where the traffic data actually comes from

| Input | What it sends | Is it captured from the Labrooms website? |
|---|---|---|
| [`sensor/sensor.py`](../sensor/sensor.py) | Scapy-captured IP packets aggregated into 52-number flow vectors. | Only if it is run on an authorized network interface that can see the traffic. The script itself does not know a website or domain. |
| [`sensor/mock_sensor.py`](../sensor/mock_sensor.py) | Randomly generated, realistic-looking 52-number vectors. | No. This is synthetic input for local testing without packet-capture privileges. |
| [`sensor/normal_traffic.py`](../sensor/normal_traffic.py) | Generated benign Labrooms-shaped HTTP-flow vectors. | No. It generates JSON feature arrays; it does not browse the Labrooms site. |
| [`sensor/attack_campaign.py`](../sensor/attack_campaign.py) | A timed sequence of synthetic normal/attack feature vectors with optional `LBL::` class tags. | The vectors are synthetic. `--mode live` can also send limited HTTP requests to an explicitly supplied target, but those requests are not what the pipeline scores; the generated vectors are. |
| [`sensor/simulate_attacks.py`](../sensor/simulate_attacks.py) | One synthetic batch containing four attack profiles and one normal profile. | No. It posts the constructed vectors. It also makes a direct `/predict` call to display predictions after ingestion, which can feed the same flows through the stateful ML monitor a second time. |

There is no Labrooms website implementation or dedicated website instrumentation collector in this repository. The project plan describes an existing website as a controlled traffic environment, but the checked-in generators construct feature vectors themselves. Therefore, when the demo uses `normal_traffic.py` or `attack_campaign.py`, call it **simulated Labrooms-shaped telemetry**, not packet-captured website traffic.

`sensor.py` has no website URL or host filter: it only sees IP packets visible on the local capture interface. To observe a particular authorized app's traffic, the sensor must be placed on that host/network path or receive a mirrored copy of the relevant traffic; entering the website URL alone cannot make a remote site's packets visible.

## 2. What `sensor/sensor.py` does

The real sensor is a passive packet sniffer. It does not send attack traffic, log into a website, or read a web server's application database. Its job is to observe visible IP packets and turn packet metadata into per-flow statistics.

### Configuration

The script reads these environment variables when it starts:

| Variable | Default / requirement | Meaning |
|---|---|---|
| `SENSOR_KEY` | Required | Sensor API key sent in the `X-Sensor-Key` HTTP header. |
| `INGEST_URL` | Required | Node ingestion endpoint, normally `http://localhost:5000/api/telemetry/ingest` for local development. |
| `INTERFACE` | `eth0` | Network interface on which Scapy listens. |
| `BATCH_INTERVAL` | `2` seconds | Maximum intended time between flow-table flushes while packets are arriving. |
| `BATCH_SIZE` | `100` | Flow-count threshold for a flush and maximum sender batch size. |
| `SENSOR_ID` | Random `sensor-...` value | Sensor identity included in the payload. |

The script uses Python `requests` for HTTP delivery and Scapy (`sniff`, `IP`, `TCP`, `UDP`) for capture. Windows capture generally requires Npcap and an elevated shell; the interface name must match the local machine.

### Packet-to-flow process

1. **Listen for IPv4 packets.** `sniff()` uses `filter="ip"`, the configured interface, and `store=False`, so packets are handled by a callback rather than retained in a large Scapy capture list.
2. **Choose a flow key.** `_flow_key()` reads the IP protocol and TCP/UDP source and destination ports (other IP protocols use port zero). It makes a bidirectional key by comparing the forward and reverse endpoint strings lexicographically. The smaller string becomes the canonical key; the opposite direction is marked backward.
3. **Create or update `FlowRecord`.** The flow accumulator stores start/last timestamps, forward/backward packet counts and lengths, inter-arrival times, header-byte totals, PSH/URG counts, and TCP FIN/SYN/RST/PSH/ACK/URG counters.
4. **Measure each packet.** `process_packet()` uses the full Scapy packet length, packet timestamp, TCP header length and TCP flags (or the UDP header length). The code does not inspect application payloads or extract HTTP methods, paths, response codes, or credentials.
5. **Compute statistics.** `flow_to_features()` calculates duration, directional counts and byte totals, packet-length summaries, rates, IAT statistics, header lengths, TCP flag totals, ratios, and average sizes. Division-by-zero and negative duration are guarded.
6. **Flush and clear.** When the flow table reaches `BATCH_SIZE`, or the flush interval has elapsed when a packet is processed, all current flow records are converted to feature arrays and queued. The table is cleared. The script does not wait for a TCP FIN/RST or use a connection-idle timeout to decide when a flow is complete; its records are periodic snapshots, so long-lived traffic can be split across flushes.
7. **Send away from capture.** A daemon `BatchSender` drains the queue, sends JSON with `X-Sensor-Key`, and tries up to five times with exponential backoff. A batch that still fails after those tries is logged as dropped.
8. **Stop behavior.** Ctrl+C or a capture exception flushes the remaining flow table before exit.

### The 52 values emitted by `flow_to_features()`

The order below follows the actual Python list returned by `flow_to_features()`, using zero-based indexes. This is safer than relying on the longer header comment in `sensor.py`, whose numbering becomes inconsistent in its later entries.

| Slot | Value emitted |
|---:|---|
| 0 | Numeric hash of the flow ID; identifier, not a meaningful traffic measurement. |
| 1 | Flow duration in microseconds. |
| 2 | Forward packet count. |
| 3 | Backward packet count. |
| 4 | Sum of forward packet lengths (bytes). |
| 5 | Sum of backward packet lengths (bytes). |
| 6 | Maximum forward packet length. |
| 7 | Minimum forward packet length. |
| 8 | Mean forward packet length. |
| 9 | Population standard deviation of forward packet length. |
| 10 | Maximum backward packet length. |
| 11 | Minimum backward packet length. |
| 12 | Mean backward packet length. |
| 13 | Population standard deviation of backward packet length. |
| 14 | Flow bytes per second: total forward and backward bytes divided by duration in seconds. |
| 15 | Flow packets per second. |
| 16 | Mean inter-arrival time across the flow, in microseconds. |
| 17 | Standard deviation of flow inter-arrival times, in microseconds. |
| 18 | Maximum flow inter-arrival time, in microseconds. |
| 19 | Minimum flow inter-arrival time, in microseconds. |
| 20 | Total forward inter-arrival time, in microseconds. |
| 21 | Mean forward inter-arrival time, in microseconds. |
| 22 | Standard deviation of forward inter-arrival times, in microseconds. |
| 23 | Maximum forward inter-arrival time, in microseconds. |
| 24 | Minimum forward inter-arrival time, in microseconds. |
| 25 | Total backward inter-arrival time, in microseconds. |
| 26 | Mean backward inter-arrival time, in microseconds. |
| 27 | Standard deviation of backward inter-arrival times, in microseconds. |
| 28 | Maximum backward inter-arrival time, in microseconds. |
| 29 | Minimum backward inter-arrival time, in microseconds. |
| 30 | Forward TCP PSH count. |
| 31 | Backward TCP PSH count. |
| 32 | Forward TCP URG count. |
| 33 | Backward TCP URG count. |
| 34 | Forward transport-header bytes accumulated (TCP header length or UDP's 8-byte header; IP header bytes are not added here). |
| 35 | Backward transport-header bytes accumulated (TCP header length or UDP's 8-byte header; IP header bytes are not added here). |
| 36 | Forward packets per second. |
| 37 | Backward packets per second. |
| 38 | Minimum packet length across both directions. |
| 39 | Maximum packet length across both directions. |
| 40 | Mean packet length across both directions. |
| 41 | Standard deviation of packet lengths across both directions. |
| 42 | Variance of packet lengths across both directions. |
| 43 | TCP FIN count. |
| 44 | TCP SYN count. |
| 45 | TCP RST count. |
| 46 | TCP PSH count. |
| 47 | TCP ACK count. |
| 48 | TCP URG count. |
| 49 | Backward packet count divided by forward packet count. |
| 50 | Average packet size: total bytes divided by total packet count. |
| 51 | Forward average segment size: forward bytes divided by forward packet count. |

`flow_id` is also included as a separate string beside the vector. The numeric hash in slot 0 is not used as a model feature.

## 3. How the Labrooms-shaped generators work

The normal and attack generators build a list of 52 zeros, fill only a small set of slots, then post it directly. They do not capture packets to derive those values.

- `normal_traffic.py` samples plausible duration, request/response byte sizes, packet counts, and HTTP status values. It derives bytes per second and leaves most slots zero. `--lbl-tag` can prefix the ID with `LBL::Normal_Traffic::` for simulator ground truth.
- `attack_campaign.py` emits warmup, DoS, brute-force, SQLi/web, exfiltration, and cooldown phases. Its flow IDs are `LBL::<CLASS>::...` by default. Exfiltration is labeled `Web_Attacks` because the project's target classes do not include a separate Exfiltration class.
- `simulate_attacks.py` emits one batch of four attack profiles and one normal profile. It uses deterministic example-like feature values, then queries the ML endpoint to print predictions.
- `mock_sensor.py` fabricates random network-looking feature arrays and does not require Scapy/libpcap or root/admin privileges.

The generator vectors populate slots `[0, 1, 2, 3, 4, 5, 6, 7, 14, 44]`. In these app-layer vectors, slot 44 is used for an HTTP status code. In the Scapy sensor, slot 44 is the TCP SYN count. This is not a cosmetic naming difference; rules and PSI monitoring interpret the number differently.

## 4. Critical feature-contract mismatch before using real capture

The current inference API and live rules are built around the generated `labrooms-app-layer-v1` convention. `ml/api.py` treats slot 44 as HTTP status for rule overrides, and `LiveDriftMonitor` labels slot 44 as HTTP Status Code for PSI. But the real Scapy sensor writes TCP SYN count at index 44 and does not parse HTTP status.

There are additional alignment risks:

1. The Labrooms training contract says only ten of 52 slots are populated; `sensor.py` computes many packet-level statistics and therefore emits a different pattern.
2. The live model's feature contract maps slot 3 (backward packet count) to CICIDS2017 `Bwd Packet Length Max` as a proxy and slot 5 (backward bytes) to `Bwd Packet Length Min` as a proxy. These are not identical quantities or units.
3. `sensor.py` chooses forward/backward direction by lexicographic canonicalization, not by knowing which endpoint is the web client. The Labrooms app-layer contract interprets forward as request and backward as response.
4. The Scapy sensor captures IP metadata; it does not decrypt TLS or parse HTTP. HTTP status-dependent rules cannot be populated from this script as written.

**Practical conclusion:** the demo generators and the real Scapy sensor are separate input modes. Before connecting `sensor.py` to the current Labrooms model, agree on one schema and align packet direction, slot meanings, preprocessing, app-layer status collection, drift feature names, and training data. For actual application status/route metadata, instrument the authorized application/server explicitly rather than assuming encrypted packet capture reveals it.

## 5. What happens after a sensor POST

A typical payload looks like this (feature values omitted):

```json
{
  "sensor_id": "sensor-example",
  "batch_timestamp": 1791111111.0,
  "flow_count": 1,
  "flows": [
    { "flow_id": "flow-example", "features": ["52 numeric values"] }
  ]
}
```

The sensor sends it to the Node route with `X-Sensor-Key`. In [`server/routes/telemetry.js`](../server/routes/telemetry.js):

1. `authenticateSensor` hashes the key with SHA-256 and finds an active `ApiKey` record.
2. The route requires `sensor_id`, `batch_timestamp`, and a `flows` array. Each flow needs an ID and exactly 52 numeric values. Negative duration at slot 1 is clamped to zero.
3. Valid flows are inserted into `TelemetryLog` with company, sensor, batch timestamp, flow ID, and raw feature values.
4. Node updates the sensor key's `lastIngestAt` and returns HTTP 202 with accepted/rejected counts.
5. After sending 202, Node asynchronously forwards the inserted batch to Flask `/predict`. If Flask returns predictions, Node bulk-updates the matching Mongo documents with label and confidence.

The sensor's success response means the Node service accepted/stored the records; it does not mean the ML label has already been written. The dashboard can briefly show a flow before its ML fields are populated.

There is also a timestamp-unit inconsistency in the senders: `sensor.py` and `mock_sensor.py` send epoch seconds, while `normal_traffic.py`, `attack_campaign.py`, and `simulate_attacks.py` send epoch milliseconds. Node stores `batch_timestamp` as supplied; the dashboard's recent-flow ordering uses MongoDB `receivedAt` instead.

## 6. From prediction to dashboard

In `ml/api.py`, `/predict`:

1. Validates each 52-element vector and clamps negative duration.
2. Maps named Labrooms slots to the eight model features and applies the stored preprocessor.
3. Runs the active classifier and, where available, obtains class probabilities.
4. Applies deterministic app-layer overrides for specific patterns such as long-duration/504 DoS, very large response payloads, selected 401/403 or high-rate error patterns, and HTTP 500/large error requests.
5. Builds a batch record containing the raw vector, final label, original model label, confidence, and whether a rule overrode the model.
6. Feeds the records to live drift monitoring, the pseudo-label buffer, and the rolling evaluator.

The React pages fetch through Node. The live traffic table reads recent flow documents; the Concept Drift, Adaptation, and Evaluation pages read the Flask-derived state through Node proxy routes. The application endpoints and pages are listed in [Project Architecture](PROJECT_ARCHITECTURE.md).

## 7. Safe interpretation and operation

- Use a newly generated key and supply it through `SENSOR_KEY` or a command-line option; do not rely on baked-in demo defaults. If any fixed example key is still active, revoke/rotate it. Never copy a credential into this guide.
- Capture only traffic on networks and systems for which collection is authorized.
- Keep the sensor and server reachable over a protected network; local development defaults are plain HTTP and are not deployment security controls.
- Use generators for reproducible UI/algorithm demos, but label them as synthetic. Use packet capture only after resolving the feature-contract mismatch above.

"""
Feature Contract Specification for Adaptive Cyber Threat Intelligence.

Defines canonical feature lists, target label schemas, questionable feature evaluation,
negative Flow Duration handling, and JSON contract generation for both offline benchmark
(cicids2017-flow-v1), production deployment (production-flow-v1), and Labrooms deployment
(labrooms-app-layer-v1).

Labrooms Deployment Note:
  The Labrooms sensor sends a 52-element feature array (based on the CyberAdapt spec) where
  only 10 slots are populated; the other 42 are always zero. Because zero-only features carry no
  information, LABROOMS_DEPLOYMENT_FEATURES selects only the CICIDS2017 columns that semantically
  correspond to the populated Labrooms slots. Training on the full 52-feature set against Labrooms
  traffic would cause severe training-serving skew.

  Labrooms → CICIDS2017 semantic mapping (non-zero slots only):
    [1]  Flow Duration         → 'Flow Duration'
    [2]  Total Fwd Packets     → 'Total Fwd Packets'
    [3]  Total Bwd Packets*    → 'Bwd Packet Length Max'  (closest CICIDS2017 proxy)
    [4]  Total Fwd Bytes       → 'Total Length of Fwd Packets'
    [5]  Total Bwd Bytes*      → 'Bwd Packet Length Min'  (closest CICIDS2017 proxy)
    [6]  Fwd Pkt Len Max       → 'Fwd Packet Length Max'
    [7]  Fwd Pkt Len Min       → 'Fwd Packet Length Min'
    [14] Flow Bytes/s          → 'Flow Bytes/s'
    [44] HTTP Status Code**    → omitted (no CICIDS2017 equivalent)
    [0]  Flow ID Hash          → omitted (identifier, not a ML feature)

  * CICIDS2017 does not have "Total Bwd Packets" or "Total Bwd Bytes" as named columns;
    Bwd Packet Length Max/Min are used as the closest available proxies.
  ** CICIDS2017 does not contain HTTP status codes, so the SYN-Count/Status-Code slot
     has no equivalent and is omitted from training.
"""

from pathlib import Path
from typing import Dict, List, Tuple, Any
import json
import logging
import pandas as pd

logger = logging.getLogger(__name__)

# Target Column and Class Labels
TARGET_COLUMN: str = "Attack Type"

TARGET_CLASSES: List[str] = [
    "Normal Traffic",
    "DoS",
    "DDoS",
    "Port Scanning",
    "Brute Force",
    "Web Attacks",
    "Bots",
]

SCHEMA_VERSION: str = "cicids2017-flow-v1"
PRODUCTION_SCHEMA_VERSION: str = "production-candidate-flow-v1"
LABROOMS_SCHEMA_VERSION: str = "labrooms-app-layer-v1"

# All 52 numeric feature columns available in cleaned CSV dataset (excluding target column)
ALL_AVAILABLE_FEATURES: List[str] = [
    "Destination Port",
    "Flow Duration",
    "Total Fwd Packets",
    "Total Length of Fwd Packets",
    "Fwd Packet Length Max",
    "Fwd Packet Length Min",
    "Fwd Packet Length Mean",
    "Fwd Packet Length Std",
    "Bwd Packet Length Max",
    "Bwd Packet Length Min",
    "Bwd Packet Length Mean",
    "Bwd Packet Length Std",
    "Flow Bytes/s",
    "Flow Packets/s",
    "Flow IAT Mean",
    "Flow IAT Std",
    "Flow IAT Max",
    "Flow IAT Min",
    "Fwd IAT Total",
    "Fwd IAT Mean",
    "Fwd IAT Std",
    "Fwd IAT Max",
    "Fwd IAT Min",
    "Bwd IAT Total",
    "Bwd IAT Mean",
    "Bwd IAT Std",
    "Bwd IAT Max",
    "Bwd IAT Min",
    "Fwd Header Length",
    "Bwd Header Length",
    "Fwd Packets/s",
    "Bwd Packets/s",
    "Min Packet Length",
    "Max Packet Length",
    "Packet Length Mean",
    "Packet Length Std",
    "Packet Length Variance",
    "FIN Flag Count",
    "PSH Flag Count",
    "ACK Flag Count",
    "Average Packet Size",
    "Subflow Fwd Bytes",
    "Init_Win_bytes_forward",
    "Init_Win_bytes_backward",
    "act_data_pkt_fwd",
    "min_seg_size_forward",
    "Active Mean",
    "Active Max",
    "Active Min",
    "Idle Mean",
    "Idle Max",
    "Idle Min",
]

# Questionable / Sensor-Dependent Features evaluated during audit
QUESTIONABLE_FEATURES: List[str] = [
    "Init_Win_bytes_forward",
    "Init_Win_bytes_backward",
    "Subflow Fwd Bytes",
    "act_data_pkt_fwd",
    "min_seg_size_forward",
]

# Benchmark candidate features (52 numeric features)
PRODUCTION_CANDIDATE_FEATURES: List[str] = list(ALL_AVAILABLE_FEATURES)

# Production-safe features for production-flow-v1 (47 features, excluding sensor-dependent questionable features)
PRODUCTION_FLOW_V1_FEATURES: List[str] = [
    f for f in ALL_AVAILABLE_FEATURES if f not in QUESTIONABLE_FEATURES
]

# ---------------------------------------------------------------------------
# Labrooms Deployment Feature Contract  (labrooms-app-layer-v1)
# ---------------------------------------------------------------------------
# The Labrooms sensor sends a 52-slot CyberAdapt array where only the 10
# indices below are ever populated. The remaining 42 slots are always zero.
# Training on zero-valued features would cause training-serving skew, so we
# restrict the model to only these 8 CICIDS2017 columns that semantically
# correspond to the non-zero (and non-identifier) Labrooms slots.
#
# Slot → Labrooms meaning → CICIDS2017 column used
#  [1]  Flow Duration          → Flow Duration
#  [2]  Total Fwd Packets      → Total Fwd Packets
#  [3]  Total Bwd Packets*     → Bwd Packet Length Max  (closest proxy)
#  [4]  Total Fwd Bytes        → Total Length of Fwd Packets
#  [5]  Total Bwd Bytes*       → Bwd Packet Length Min  (closest proxy)
#  [6]  Fwd Pkt Len Max        → Fwd Packet Length Max
#  [7]  Fwd Pkt Len Min        → Fwd Packet Length Min
#  [14] Flow Bytes/s           → Flow Bytes/s
#
#  Omitted: [0] Flow ID Hash (non-ML identifier)
#            [44] HTTP Status Code (no CICIDS2017 equivalent)
# ---------------------------------------------------------------------------
LABROOMS_DEPLOYMENT_FEATURES: List[str] = [
    "Flow Duration",               # Labrooms slot [1]
    "Total Fwd Packets",           # Labrooms slot [2]
    "Total Length of Fwd Packets", # Labrooms slot [4] — Total Fwd Bytes (request size)
    "Fwd Packet Length Max",       # Labrooms slot [6] — Fwd Pkt Len Max
    "Fwd Packet Length Min",       # Labrooms slot [7] — Fwd Pkt Len Min
    "Bwd Packet Length Max",       # Labrooms slot [3] proxy — Total Bwd Packets
    "Bwd Packet Length Min",       # Labrooms slot [5] proxy — Total Bwd Bytes
    "Flow Bytes/s",                # Labrooms slot [14] — Throughput
]

LABROOMS_ZEROED_FEATURES_NOTE: str = (
    "The following CICIDS2017 feature groups are always zero in Labrooms deployments "
    "and MUST NOT be used during training to avoid training-serving skew: "
    "Packet-level length stats (Fwd/Bwd Mean/Std), Inter-Arrival Times (IAT), "
    "TCP Flags (FIN/RST/PSH/ACK/URG/SYN), Header Lengths, Global Packet Stats, "
    "Window sizes, Subflow stats, Active/Idle stats."
)

# Excluded feature descriptions for production-flow-v1
PRODUCTION_EXCLUSIONS: Dict[str, str] = {
    "Init_Win_bytes_forward": "EXCLUDED in production-flow-v1: Initial TCP window size forward depends on host OS socket state.",
    "Init_Win_bytes_backward": "EXCLUDED in production-flow-v1: Initial TCP window size backward depends on host OS socket state.",
    "Subflow Fwd Bytes": "EXCLUDED in production-flow-v1: Redundant with Total Length of Fwd Packets.",
    "act_data_pkt_fwd": "EXCLUDED in production-flow-v1: Requires deep packet payload inspection.",
    "min_seg_size_forward": "EXCLUDED in production-flow-v1: Dependent on specific generator driver settings.",
}

EXCLUDED_FEATURES: Dict[str, str] = {}

FEATURE_EXCLUSION_REASONS: Dict[str, str] = {
    "Init_Win_bytes_forward": "RETAINED in cicids2017-flow-v1: Initial TCP window size forward.",
    "Init_Win_bytes_backward": "RETAINED in cicids2017-flow-v1: Initial TCP window size backward.",
    "Subflow Fwd Bytes": "RETAINED in cicids2017-flow-v1: Subflow forward bytes count.",
    "act_data_pkt_fwd": "RETAINED in cicids2017-flow-v1: Count of forward payload packets.",
    "min_seg_size_forward": "RETAINED in cicids2017-flow-v1: Minimum TCP header segment size forward.",
}


def quantify_and_clean_negative_duration(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Quantify and remediate negative Flow Duration records."""
    df_clean = df.copy()
    num_negative = 0
    neg_percentage = 0.0

    if "Flow Duration" in df_clean.columns:
        neg_mask = df_clean["Flow Duration"] < 0
        num_negative = int(neg_mask.sum())
        neg_percentage = round((num_negative / len(df_clean)) * 100, 6)
        df_clean.loc[neg_mask, "Flow Duration"] = 0

    report = {
        "column": "Flow Duration",
        "total_records": len(df_clean),
        "negative_duration_count": num_negative,
        "negative_duration_percentage": neg_percentage,
        "remediation_action": "Clipped negative values to 0 (preserved rows to avoid dropping minority class samples)",
    }

    return df_clean, report


def export_feature_contract(
    output_path: Path,
    schema_version: str = SCHEMA_VERSION,
    target_col: str = TARGET_COLUMN,
    candidate_features: List[str] = PRODUCTION_CANDIDATE_FEATURES,
    questionable_features: List[str] = QUESTIONABLE_FEATURES,
    exclusion_reasons: Dict[str, str] = FEATURE_EXCLUSION_REASONS,
) -> Dict[str, Any]:
    """Generate and write final_feature_contract.json file for offline benchmark."""
    contract = {
        "schema_version": schema_version,
        "target_column": target_col,
        "target_classes": TARGET_CLASSES,
        "total_available_features": len(ALL_AVAILABLE_FEATURES),
        "total_selected_features": len(candidate_features),
        "selected_features": candidate_features,
        "excluded_features": list(EXCLUDED_FEATURES.keys()),
        "questionable_features_evaluated": questionable_features,
        "feature_evaluation_notes": exclusion_reasons,
        "dataset_name": "CICIDS2017 Cleaned",
        "notes": (
            "Ordered holdout proxy is used for streaming evaluation because explicit "
            "temporal metadata (timestamps) is not present in this cleaned dataset."
        ),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(contract, f, indent=2)

    logger.info(f"Saved feature contract schema '{schema_version}' to {output_path}")
    return contract


def export_production_candidate_feature_contract(
    output_path: Path,
    schema_version: str = PRODUCTION_SCHEMA_VERSION,
    target_col: str = TARGET_COLUMN,
    candidate_features: List[str] = PRODUCTION_FLOW_V1_FEATURES,
    excluded_features: Dict[str, str] = PRODUCTION_EXCLUSIONS,
) -> Dict[str, Any]:
    """Generate and write final_production_candidate_feature_contract.json file for candidate deployment."""
    contract = {
        "schema_version": schema_version,
        "target_column": target_col,
        "target_classes": TARGET_CLASSES,
        "total_available_features": len(ALL_AVAILABLE_FEATURES),
        "total_selected_features": len(candidate_features),
        "total_excluded_features": len(excluded_features),
        "selected_features": candidate_features,
        "excluded_features": list(excluded_features.keys()),
        "exclusion_reasons": excluded_features,
        "dataset_name": "CICIDS2017 Cleaned",
        "notes": (
            "Production candidate feature contract excluding sensor-dependent host OS TCP socket features. "
            "Requires live sensor hardware verification before full production promotion."
        ),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(contract, f, indent=2)

    logger.info(f"Saved production candidate feature contract schema '{schema_version}' to {output_path}")
    return contract


def export_labrooms_feature_contract(
    output_path: Path,
    schema_version: str = LABROOMS_SCHEMA_VERSION,
    target_col: str = TARGET_COLUMN,
    labrooms_features: List[str] = LABROOMS_DEPLOYMENT_FEATURES,
) -> Dict[str, Any]:
    """Generate and write labrooms_feature_contract.json for Labrooms deployment.

    This contract encodes only the 8 CICIDS2017 features that semantically
    correspond to the non-zero, non-identifier slots of the Labrooms 52-element
    CyberAdapt sensor array.  Training on the full 52-feature set against
    Labrooms traffic would introduce severe training-serving skew because the
    other 44 features are always 0 in production.
    """
    contract = {
        "schema_version": schema_version,
        "target_column": target_col,
        "target_classes": TARGET_CLASSES,
        "total_cicids2017_features": len(ALL_AVAILABLE_FEATURES),
        "total_selected_features": len(labrooms_features),
        "total_zeroed_features": len(ALL_AVAILABLE_FEATURES) - len(labrooms_features),
        "selected_features": labrooms_features,
        "deployment_target": "Labrooms Application-Layer Sensor",
        "anomaly_types_detectable": [
            "Data Exfiltration — abnormally large Response Bytes (Bwd Pkt Len Max/Min)",
            "Brute Force / Scraping — very high Flow Bytes/s with small request size",
            "Slowloris / DoS — extremely high Flow Duration with small byte counts",
            "Abnormal Request Volume — spike in Total Fwd Packets",
        ],
        "feature_mapping": {
            "Flow Duration": "Labrooms slot [1] — total HTTP request processing time (microseconds)",
            "Total Fwd Packets": "Labrooms slot [2] — represents the incoming HTTP Request (always 1)",
            "Total Length of Fwd Packets": "Labrooms slot [4] — size of the incoming HTTP request (bytes)",
            "Fwd Packet Length Max": "Labrooms slot [6] — same as Total Fwd Bytes (request size)",
            "Fwd Packet Length Min": "Labrooms slot [7] — same as Total Fwd Bytes (request size)",
            "Bwd Packet Length Max": "Labrooms slot [3] proxy — Total Bwd Packets (CICIDS2017 proxy)",
            "Bwd Packet Length Min": "Labrooms slot [5] proxy — Total Bwd Bytes / response size (CICIDS2017 proxy)",
            "Flow Bytes/s": "Labrooms slot [14] — (request + response bytes) / duration",
        },
        "omitted_labrooms_slots": {
            "[0] Flow ID Hash": "Omitted — numeric identifier, not a learnable ML feature",
            "[44] HTTP Status Code": "Omitted — no equivalent in CICIDS2017; use if future dataset provides it",
        },
        "zeroed_feature_groups": LABROOMS_ZEROED_FEATURES_NOTE,
        "dataset_name": "CICIDS2017 Cleaned",
        "notes": (
            "Model trained with this contract detects application-layer anomalies rather than "
            "network-layer anomalies. TCP-flag-based attacks (e.g. SYN Floods) cannot be detected "
            "because those features are always zero in Labrooms. Focus instead on flow size, "
            "duration, and throughput anomalies."
        ),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(contract, f, indent=2)

    logger.info(f"Saved Labrooms feature contract schema '{schema_version}' to {output_path}")
    return contract

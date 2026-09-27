"""
These tests exist specifically to guard the causality property described
in app/ml/features.py's module docstring — a future edit that accidentally
lets `build_causal_cluster_density` see future rows should fail here
before it ever reaches a training run.
"""
import pandas as pd

from app.ml.features import build_causal_cluster_density, haversine_km


def test_causal_density_ignores_future_rows():
    hotspots = pd.DataFrame(
        {
            "cluster_id": [1, 1, 1, 1],
            "acq_datetime": pd.to_datetime(
                ["2026-01-01 00:00", "2026-01-01 02:00", "2026-01-01 04:00", "2026-01-02 00:00"]
            ),
        }
    )
    as_of = pd.Timestamp("2026-01-01 03:00")

    count_6h, count_24h = build_causal_cluster_density(hotspots, cluster_id=1, as_of=as_of)

    # Only the first two rows are <= as_of; the 04:00 and next-day rows must
    # not be counted even though they're in the same cluster.
    assert count_6h == 2
    assert count_24h == 2


def test_causal_density_respects_window_width():
    hotspots = pd.DataFrame(
        {
            "cluster_id": [1, 1, 1],
            "acq_datetime": pd.to_datetime(["2026-01-01 00:00", "2026-01-01 12:00", "2026-01-01 23:00"]),
        }
    )
    as_of = pd.Timestamp("2026-01-01 23:00")

    count_6h, count_24h = build_causal_cluster_density(hotspots, cluster_id=1, as_of=as_of)

    assert count_6h == 1  # only the 23:00 row itself
    assert count_24h == 3  # all three fall within the trailing 24h


def test_haversine_known_distance():
    # Delhi to Mumbai is ~1150 km great-circle
    delhi = (28.6139, 77.2090)
    mumbai = (19.0760, 72.8777)
    dist = haversine_km(*delhi, *mumbai)
    assert 1100 < dist < 1200

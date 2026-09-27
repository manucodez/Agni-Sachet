"""app/ml/weak_labeling.py — the deterministic label-generating rule."""
import pandas as pd

from app.ml.weak_labeling import (
    RULE_DEFINING_FEATURES,
    WEAK_LABEL_RULE_VERSION,
    generate_weak_labels,
    weak_label_row,
)


def test_persistent_source_near_power_plant_is_gas_flare():
    row = dict(distance_to_industrial_m=100, distance_to_power_plant_m=100,
               land_cover_class=50, month=6, trailing_detection_count_24h=40)
    assert weak_label_row(row) == "gas_flare"


def test_one_off_spike_near_power_plant_is_not_gas_flare():
    # Same distances as above, but not recurrent — a flare stack fires
    # constantly; a one-off spike near a plant usually isn't one.
    row = dict(distance_to_industrial_m=100, distance_to_power_plant_m=100,
               land_cover_class=50, month=6, trailing_detection_count_24h=1)
    assert weak_label_row(row) != "gas_flare"


def test_close_to_industrial_land_is_industrial_fire():
    row = dict(distance_to_industrial_m=200, distance_to_power_plant_m=5000,
               land_cover_class=50, month=6, trailing_detection_count_24h=2)
    assert weak_label_row(row) == "industrial_fire"


def test_bare_sparse_vegetation_far_from_industry_is_mining():
    row = dict(distance_to_industrial_m=9000, distance_to_power_plant_m=9000,
               land_cover_class=60, month=6, trailing_detection_count_24h=1)
    assert weak_label_row(row) == "mining"


def test_cropland_in_harvest_month_is_agricultural_burn():
    row = dict(distance_to_industrial_m=9000, distance_to_power_plant_m=9000,
               land_cover_class=40, month=4, trailing_detection_count_24h=1)
    assert weak_label_row(row) == "agricultural_burn"


def test_cropland_outside_harvest_month_is_not_agricultural_burn():
    row = dict(distance_to_industrial_m=9000, distance_to_power_plant_m=9000,
               land_cover_class=40, month=7, trailing_detection_count_24h=1)
    assert weak_label_row(row) != "agricultural_burn"


def test_tree_cover_is_wildfire():
    row = dict(distance_to_industrial_m=9000, distance_to_power_plant_m=9000,
               land_cover_class=10, month=6, trailing_detection_count_24h=1)
    assert weak_label_row(row) == "wildfire"


def test_no_evidence_falls_back_to_other():
    row = dict(distance_to_industrial_m=None, distance_to_power_plant_m=None,
               land_cover_class=80, month=6, trailing_detection_count_24h=1)
    assert weak_label_row(row) == "other"


def test_never_produces_unclassified():
    # "unclassified" is reserved for low-confidence model *predictions* at
    # serving time (see app/ml/classifier.py) -- a training label the rule
    # was unsure about should be excluded upstream, never labeled this.
    from app.ml.classifier import CLASSES
    for land_cover in [10, 40, 50, 60, 80, None]:
        for month in range(1, 13):
            row = dict(distance_to_industrial_m=None, distance_to_power_plant_m=None,
                       land_cover_class=land_cover, month=month, trailing_detection_count_24h=0)
            assert weak_label_row(row) in CLASSES


def test_generate_weak_labels_adds_expected_columns():
    df = pd.DataFrame([
        dict(distance_to_industrial_m=100, distance_to_power_plant_m=5000,
             land_cover_class=50, month=6, trailing_detection_count_24h=1),
    ])
    out = generate_weak_labels(df)
    assert "label" in out.columns
    assert out["weak_label_rule_version"].iloc[0] == WEAK_LABEL_RULE_VERSION
    assert out["label"].iloc[0] == "industrial_fire"


def test_rule_defining_features_are_all_real_feature_columns():
    # scripts/circularity_audit.py ablates exactly these columns from
    # FEATURE_COLUMNS -- if one were misspelled, the ablation would
    # silently no-op instead of removing anything.
    from app.ml.features import FEATURE_COLUMNS
    for col in RULE_DEFINING_FEATURES:
        assert col in FEATURE_COLUMNS, f"{col} is not a real feature column"

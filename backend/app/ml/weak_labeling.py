"""
Deterministic, versioned weak-labeling rule for bootstrapping
app/ml/train.py's labels.csv from raw ingested detections.

WHY THIS EXISTS
-----------------
docs/ROADMAP.md's "Label sourcing" section is honest that this is the
hardest part of the whole build: there is no public, pre-labeled dataset
of "this specific FIRMS detection was an industrial fire vs. a gas flare
vs. agricultural burning." The roadmap's answer for most classes was
"manually spot-label" -- which is honest, but doesn't scale to enough
spatial-block diversity (see app/ml/train.py's spatial_block_split) to
produce a trustworthy holdout number in a 7-day build, and app/ml/train.py
itself just assumes a labels.csv exists without saying how you'd get one.

This module is that "how": a documented, versioned, auditable rule that
assigns a label to every fused hotspot row from context that's ALREADY
been joined in by app/jobs/run_ingestion.py (distance to nearest
industrial polygon, distance to nearest power plant, land cover class,
month, recurrence). It's the same idea as the SIH26162 reference
implementation's domain-rule label bootstrap (see docs/MERGE_NOTES.md),
adapted to agni-sachet's own class taxonomy and joined fields, run against
a couple thousand detections in a few seconds rather than by hand.

THIS RULE IS NOT GROUND TRUTH -- IT'S A STARTING POINT
----------------------------------------------------------
A model trained ONLY on these labels will, at best, learn to recite this
rule back using FRP/timing/recurrence as slightly-better proxies for the
same distances and land-cover codes the rule already used directly. That
is expected and is not a free lunch -- see scripts/circularity_audit.py,
which measures exactly how much of the model's reported accuracy is doing
that versus finding real independent signal, and
docs/reference/verified_events.csv + scripts/evaluate_verified_labels.py,
which checks the trained model against a small independently-sourced set
of real, cited incidents rather than this rule's own output. Use this
module to get a spatially-diverse training set off the ground fast; use
those two to find out whether the resulting model is actually any good.
"""
from __future__ import annotations

import pandas as pd

WEAK_LABEL_RULE_VERSION = "agni-weak-v1"

# ESA WorldCover class codes -- see app/ingestion/worldcover.py.
LAND_COVER_TREE_COVER = 10
LAND_COVER_CROPLAND = 40
LAND_COVER_BARE_SPARSE_VEGETATION = 60

# All deliberately named module-level constants, not inlined magic numbers,
# so RULE_DEFINING_FEATURES below can be stated once and so a reviewer (or
# scripts/circularity_audit.py) can see exactly what the rule keys off of.
GAS_FLARE_MAX_POWER_PLANT_DISTANCE_M = 2000
GAS_FLARE_MIN_RECURRENCE_24H = 20  # a true flare stack fires constantly; a one-off spike near a plant usually isn't one
INDUSTRIAL_FIRE_MAX_INDUSTRIAL_DISTANCE_M = 1500

# Loosely: Rabi harvest (Feb-May) and Kharif harvest (Oct-Nov) residue-burning
# windows commonly cited for northern India. This is a coarse, commonly-used
# heuristic, not a peer-reviewed constant -- see docs/DATA_SOURCES.md before
# quoting it as authoritative, and swap in a state-specific calendar if you
# have one.
AGRICULTURAL_BURN_HARVEST_MONTHS = {2, 3, 4, 5, 10, 11}

# The exact fields this rule reads to assign a label. Exposed as a constant
# (rather than left implicit in the function body) specifically so
# scripts/circularity_audit.py can retrain with precisely these columns
# removed and measure how much of the model's accuracy depends on them.
RULE_DEFINING_FEATURES = [
    "distance_to_industrial_m",
    "distance_to_power_plant_m",
    "land_cover_class",
    "month",
    "trailing_detection_count_24h",
]


def weak_label_row(row: dict) -> str:
    """Returns one of app.ml.classifier.CLASSES (never "unclassified" --
    that label is reserved for low-confidence model *predictions* at
    serving time, not for a training label the rule was unsure about;
    unsure rows should be excluded upstream, not labeled "unclassified").

    Checked in priority order -- most specific evidence first -- because a
    row can plausibly match more than one condition (e.g. a flare stack at
    a refinery is both "close to industrial" and "close to a power plant");
    the first match wins.
    """
    dist_industrial = row.get("distance_to_industrial_m")
    dist_power_plant = row.get("distance_to_power_plant_m")
    land_cover = row.get("land_cover_class")
    month = row.get("month")
    recurrence_24h = row.get("trailing_detection_count_24h") or 0

    if (
        dist_power_plant is not None
        and dist_power_plant <= GAS_FLARE_MAX_POWER_PLANT_DISTANCE_M
        and recurrence_24h >= GAS_FLARE_MIN_RECURRENCE_24H
    ):
        return "gas_flare"

    if dist_industrial is not None and dist_industrial <= INDUSTRIAL_FIRE_MAX_INDUSTRIAL_DISTANCE_M:
        return "industrial_fire"

    if land_cover == LAND_COVER_BARE_SPARSE_VEGETATION and (
        dist_industrial is None or dist_industrial > INDUSTRIAL_FIRE_MAX_INDUSTRIAL_DISTANCE_M
    ):
        # Bare/sparse vegetation as a proxy for open-pit mining is a coarse
        # stand-in for a real mining-lease polygon layer -- see
        # docs/ROADMAP.md. It will also catch quarries, brick kilns and
        # some bare fallow land; treat "mining" labels from this rule as
        # lower-confidence than the others.
        return "mining"

    if land_cover == LAND_COVER_CROPLAND and month in AGRICULTURAL_BURN_HARVEST_MONTHS:
        return "agricultural_burn"

    if land_cover == LAND_COVER_TREE_COVER:
        return "wildfire"

    return "other"


def generate_weak_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Applies weak_label_row to every row of a fused-hotspot DataFrame and
    returns a copy with `label` and `weak_label_rule_version` columns
    added, ready to write straight to a labels.csv for app/ml/train.py
    (which additionally requires the FEATURE_COLUMNS + lat + lon +
    acq_datetime columns this function does not itself add or touch)."""
    out = df.copy()
    out["label"] = out.apply(lambda r: weak_label_row(r.to_dict()), axis=1)
    out["weak_label_rule_version"] = WEAK_LABEL_RULE_VERSION
    return out

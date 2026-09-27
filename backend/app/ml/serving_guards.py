"""
Serving guards — small, deterministic rules applied AFTER the trained
classifier, for cases where "let the softmax figure it out" is the wrong
tool by construction rather than a training-data problem.

WHY THIS EXISTS (and why it's separate from the model)
--------------------------------------------------------
app/ml/classifier.py already does the right thing for the general case:
land_cover_class is a real input feature (see app/ml/features.py's
extensive docstring on avoiding lat/lon leakage), so the model CAN in
principle learn "tree cover -> wildfire, cropland -> agricultural_burn"
on its own. That's a genuine, defensible design choice, and it's why this
module does NOT introduce a new class or replace the model's own
land-cover reasoning.

What a trained softmax can't reliably give you, no matter how good the
training data is, is a guarantee: "never call this a fire" for something
that is physically incapable of combusting. A rooftop solar array or a
wind turbine can produce a real VIIRS thermal anomaly (panel glare at a
low sun angle, a gearbox overheating) with no fire at all, and the
non-combustion answer isn't "hope the model learned this pattern from
enough examples" — it's "reference the WRI power-plant fuel_type and
never predict a combustion class here, full stop." That's what guards are
for: cheap, auditable, always-correct rules for the small number of cases
where the correct answer is genuinely a hard rule, not a probability.

This mirrors the `apply_serving_guards()` pattern from the SIH26162
reference implementation with the fully-built-out pipeline (see
docs/MERGE_NOTES.md) — non-combustion override and a land-cover override —
adapted to agni-sachet's own class taxonomy and feature set rather than
copied verbatim, since that implementation trains WITHOUT land cover as a
feature (by design, to keep the model coordinate/context-free) and so
needs land-cover overrides to do more work than agni-sachet's does.

TRANSPARENCY, NOT SILENT OVERRIDING
-------------------------------------
Every override returns a human-readable note, persisted on
DiscoveredCluster.classification_override_note and included in the alert
payload (app/alerts/sachet.py) and API response (app/schemas/cluster.py).
A judge, an analyst, or a future you debugging "why did this get
reclassified" should never have to read this source file to find out —
the note travels with the row.
"""
from __future__ import annotations

from dataclasses import dataclass

# WRI Global Power Plant Database fuel_type values that cannot combust.
# Deliberately narrow: "Hydro" and "Nuclear" plants DO have real fire risk
# (transformer fires, turbine hall fires) and are excluded on purpose.
NON_COMBUSTION_FUEL_TYPES = {"Solar", "Wind"}

# Only override when the detection is essentially AT the facility --
# this guard is about "this specific plant can't be on fire," not "there's
# a solar farm somewhere in the district."
NON_COMBUSTION_OVERRIDE_RADIUS_M = 200

# ESA WorldCover class code for "Tree cover" -- see app/ingestion/worldcover.py.
FOREST_LAND_COVER_CLASS = 10

# Classes eligible for the forest defense-in-depth override. Deliberately
# excludes "mining" and "industrial_fire": a mine or a factory sitting
# inside a forest concession is a real, distinct thing, and this guard
# has no business overriding a class the model was confident about for an
# unrelated reason.
FOREST_OVERRIDE_ELIGIBLE_CLASSES = {"agricultural_burn", "other"}
FOREST_OVERRIDE_TARGET_CLASS = "wildfire"

# Only fires when the model ITSELF wasn't confident -- land_cover_class is
# already a training feature, so a confident prediction means the model
# looked at the land cover and made its own call; this guard is a safety
# net for the low-confidence remainder, not a second vote that overrules it.
FOREST_OVERRIDE_MAX_CONFIDENCE = 0.65

# Below this distance from a mapped industrial polygon, an "in a forest"
# reading is more likely a forestry-adjacent industrial site (a sawmill
# clearing, a mine access road) than open wildfire -- don't override.
FOREST_OVERRIDE_MIN_INDUSTRIAL_DISTANCE_M = 1000


@dataclass(frozen=True)
class GuardResult:
    served_class: str
    served_confidence: float
    override_note: str | None


def apply_serving_guards(
    predicted_class: str,
    confidence: float,
    *,
    land_cover_class: int | None,
    nearest_industrial_distance_m: float | None,
    nearest_power_plant_distance_m: float | None,
    nearest_power_plant_fuel_type: str | None,
) -> GuardResult:
    """Applies guards in a fixed order and returns on the first match.
    Order matters here only in that non-combustion is checked first: a
    solar farm built on cleared former forest land should still be called
    "other," not "wildfire," if a hot panel happens to sit on a
    tree-cover-coded pixel at the polygon's edge.
    """

    if (
        nearest_power_plant_fuel_type in NON_COMBUSTION_FUEL_TYPES
        and nearest_power_plant_distance_m is not None
        and nearest_power_plant_distance_m <= NON_COMBUSTION_OVERRIDE_RADIUS_M
        and predicted_class != "other"
    ):
        note = (
            f"reclassified {predicted_class} -> other: detection is "
            f"{nearest_power_plant_distance_m:.0f}m from a {nearest_power_plant_fuel_type} "
            "facility (WRI Global Power Plant Database), which cannot combust. Served as "
            "'other' rather than dropped -- panel-field vegetation fires and glare "
            "false-positives are still worth a human glance, just not as an industrial fire."
        )
        return GuardResult("other", min(confidence, 0.5), note)

    if (
        predicted_class in FOREST_OVERRIDE_ELIGIBLE_CLASSES
        and land_cover_class == FOREST_LAND_COVER_CLASS
        and confidence <= FOREST_OVERRIDE_MAX_CONFIDENCE
        and (
            nearest_industrial_distance_m is None
            or nearest_industrial_distance_m > FOREST_OVERRIDE_MIN_INDUSTRIAL_DISTANCE_M
        )
    ):
        note = (
            f"reclassified {predicted_class} -> {FOREST_OVERRIDE_TARGET_CLASS}: land cover here "
            f"is ESA WorldCover class {FOREST_LAND_COVER_CLASS} (tree cover) and the model's own "
            f"confidence was low ({confidence:.2f}). land_cover_class is already a training "
            "feature, so this is a low-confidence safety net, not the primary mechanism -- "
            "see app/ml/serving_guards.py module docstring."
        )
        return GuardResult(FOREST_OVERRIDE_TARGET_CLASS, confidence, note)

    return GuardResult(predicted_class, confidence, None)

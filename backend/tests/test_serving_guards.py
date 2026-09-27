"""
app/ml/serving_guards.py — see that module's docstring for why these
overrides exist and why each guard is scoped the way it is.
"""
from app.ml.serving_guards import apply_serving_guards


def test_solar_farm_hot_panel_overridden_to_other():
    result = apply_serving_guards(
        "industrial_fire", 0.80,
        land_cover_class=40, nearest_industrial_distance_m=50,
        nearest_power_plant_distance_m=50, nearest_power_plant_fuel_type="Solar",
    )
    assert result.served_class == "other"
    assert result.override_note is not None


def test_real_gas_flare_at_gas_plant_not_overridden():
    result = apply_serving_guards(
        "gas_flare", 0.90,
        land_cover_class=40, nearest_industrial_distance_m=50,
        nearest_power_plant_distance_m=50, nearest_power_plant_fuel_type="Gas",
    )
    assert result.served_class == "gas_flare"
    assert result.override_note is None


def test_solar_farm_far_away_not_overridden():
    # Same fuel type, but well outside NON_COMBUSTION_OVERRIDE_RADIUS_M —
    # "there's a solar farm somewhere in the district" isn't grounds to
    # override a detection that isn't actually at that facility.
    result = apply_serving_guards(
        "industrial_fire", 0.80,
        land_cover_class=40, nearest_industrial_distance_m=50,
        nearest_power_plant_distance_m=5000, nearest_power_plant_fuel_type="Solar",
    )
    assert result.served_class == "industrial_fire"


def test_low_confidence_forest_agricultural_burn_overridden_to_wildfire():
    result = apply_serving_guards(
        "agricultural_burn", 0.40,
        land_cover_class=10, nearest_industrial_distance_m=5000,
        nearest_power_plant_distance_m=None, nearest_power_plant_fuel_type=None,
    )
    assert result.served_class == "wildfire"
    assert result.override_note is not None


def test_high_confidence_forest_agricultural_burn_not_overridden():
    # The model itself was confident and land_cover_class was already an
    # input feature it could have used — this guard is a low-confidence
    # safety net, not a second vote that overrules a confident model.
    result = apply_serving_guards(
        "agricultural_burn", 0.90,
        land_cover_class=10, nearest_industrial_distance_m=5000,
        nearest_power_plant_distance_m=None, nearest_power_plant_fuel_type=None,
    )
    assert result.served_class == "agricultural_burn"
    assert result.override_note is None


def test_forest_override_does_not_apply_near_industrial_site():
    # A sawmill clearing or mine access road inside forest cover shouldn't
    # get relabeled "wildfire" just because the pixel is tree-cover-coded.
    result = apply_serving_guards(
        "agricultural_burn", 0.40,
        land_cover_class=10, nearest_industrial_distance_m=200,
        nearest_power_plant_distance_m=None, nearest_power_plant_fuel_type=None,
    )
    assert result.served_class == "agricultural_burn"


def test_mining_class_never_overridden_by_forest_guard():
    # mining isn't in FOREST_OVERRIDE_ELIGIBLE_CLASSES -- a confident mining
    # call sitting on a forested pixel is a real, distinct thing.
    result = apply_serving_guards(
        "mining", 0.40,
        land_cover_class=10, nearest_industrial_distance_m=5000,
        nearest_power_plant_distance_m=None, nearest_power_plant_fuel_type=None,
    )
    assert result.served_class == "mining"

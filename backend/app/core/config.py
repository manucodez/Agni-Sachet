"""
Central configuration, loaded once from environment variables / .env.

Every module in the app imports `settings` from here rather than reading
os.environ directly — this is the single place that knows about env var
names, so adding a new data source means adding one field here, not
grepping the codebase for os.getenv calls.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- App ---
    app_name: str = "agni-sachet"
    app_env: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    # --- Database ---
    postgres_user: str = "agni"
    postgres_password: str = "agni_dev_password"
    postgres_db: str = "agni_sachet"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    database_url: str | None = None

    # --- FIRMS ---
    firms_map_key: str = ""
    firms_bbox: str = "68.0,6.5,97.5,37.5"
    firms_sensors: str = "VIIRS_NOAA20_NRT,VIIRS_NOAA21_NRT,MODIS_NRT"
    firms_day_range: int = 10

    # --- OSM ---
    overpass_api_url: str = "https://overpass-api.de/api/interpreter"
    overpass_api_url_fallback: str = "https://overpass.kumi.systems/api/interpreter"

    # --- Public rasters / tables ---
    worldcover_s3_base: str = "https://esa-worldcover.s3.eu-central-1.amazonaws.com"
    worldpop_base_url: str = "https://data.worldpop.org"
    wri_power_plants_url: str = (
        "https://raw.githubusercontent.com/wri/global-power-plant-database/"
        "master/output_database/global_power_plant_database.csv"
    )

    # --- VNF (optional) ---
    vnf_license_key: str = ""

    # --- Advanced: Copernicus / GEE ---
    cdse_client_id: str = ""
    cdse_client_secret: str = ""
    use_gee_backend: bool = False
    gee_service_account_json_path: str = ""

    # --- Advanced: weather ---
    use_era5: bool = False
    cds_api_key: str = ""

    # --- Advanced: foundation model ---
    huggingface_token: str = ""
    gfm_model_id: str = "ibm-nasa-geospatial/Prithvi-EO-2.0-300M"
    gfm_device: str = "cpu"

    # --- Alerts ---
    sachet_webhook_url: str = ""

    # --- Sovereign boundary filter (app/ingestion/india_boundary.py) ---
    # On by default: the FIRMS bbox alone includes ocean and slivers of
    # neighboring countries. Set False only if you've deliberately widened
    # firms_bbox to cover a different country/region, since the bundled
    # boundary polygon is India-specific.
    enforce_india_boundary: bool = True

    # --- Incident escalation (app/alerts/incident_dispatch.py) ---
    # Master safety switch. False means every incident is still created,
    # tiered and logged exactly as normal — nothing about the detection or
    # escalation logic changes — but no email actually leaves the process.
    # This must default to False: a demo run, a replay of historical data,
    # or a CI test run must never be able to page a real duty officer
    # because someone forgot to unset a webhook URL. Flip it on deliberately
    # once real tier recipients are configured below.
    alert_dispatch_enabled: bool = False

    # Comma-separated recipient emails per tier. An empty tier is skipped
    # (logged as NOT_CONFIGURED, not silently treated as success — see
    # app/alerts/email_channel.py).
    incident_tier0_emails: str = ""
    incident_tier0_label: str = "Site Operator / Control Room"
    incident_tier1_emails: str = ""
    incident_tier1_label: str = "Plant Safety Officer"
    incident_tier2_emails: str = ""
    incident_tier2_label: str = "District Disaster Management Authority"

    # How long an incident sits unacknowledged at one tier before the next
    # tier is notified too (tiers are cumulative, not a handoff — see
    # app/alerts/incident_dispatch.py).
    escalation_interval_seconds: int = 900  # 15 minutes

    # A cluster whose risk_score is at least this high skips the wait and
    # notifies every configured tier immediately in parallel, rather than
    # spending escalation_interval_seconds x 2 walking up to Tier 2 for
    # something already unambiguous. Mirrors the confidence-gated
    # sequential-vs-parallel dispatch in the SIH26162 reference
    # implementation — see docs/MERGE_NOTES.md.
    incident_parallel_dispatch_risk_score: float = 90.0

    # Used to build the click-to-acknowledge link included in tier emails
    # (e.g. https://your-deployment.example.com). No trailing slash.
    public_base_url: str = "http://localhost:8000"

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_address: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def firms_bbox_tuple(self) -> tuple[float, float, float, float]:
        w, s, e, n = (float(x) for x in self.firms_bbox.split(","))
        return w, s, e, n

    @property
    def firms_sensor_list(self) -> list[str]:
        return [s.strip() for s in self.firms_sensors.split(",") if s.strip()]

    def incident_tier_emails(self, tier: int) -> list[str]:
        raw = {0: self.incident_tier0_emails, 1: self.incident_tier1_emails, 2: self.incident_tier2_emails}[tier]
        return [e.strip() for e in raw.split(",") if e.strip()]

    def incident_tier_label(self, tier: int) -> str:
        return {0: self.incident_tier0_label, 1: self.incident_tier1_label, 2: self.incident_tier2_label}[tier]

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Cached so every import gets the same instance without re-parsing env."""
    return Settings()


settings = get_settings()

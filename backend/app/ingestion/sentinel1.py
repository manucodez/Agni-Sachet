"""
ADVANCED / PHASE 3 — structural confirmation channel.

For a cluster that the classifier scores as a high-severity candidate
"industrial_fire" (explosion/accident, not a routine flare), pull the most
recent Sentinel-1 SAR pass from before the event and the closest one after,
and compute a coherence-drop ratio in a small window around the site.

Unlike every other channel in this system, SAR works at night and through
cloud cover — during India's monsoon months this is often the *only*
channel that can confirm anything at all, which is precisely why it's used
as a confirmation gate rather than a primary detector: it answers "did
something physically change here", independent of whether it was hot
enough or visible enough for the other channels to see.

This module intentionally stops at "give me a coherence-drop score" rather
than reimplementing full InSAR processing — that's what ASF HyP3
(https://hyp3-docs.asf.alaska.edu/) or the Earth Engine sentinel-1 GRD
collection are for. Swap SAR_BACKEND to pick one.
"""
import logging
from dataclasses import dataclass
from datetime import date, timedelta

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class StructuralChangeResult:
    coherence_drop_ratio: float | None  # 0 = no change, 1 = total decorrelation
    pre_event_date: date | None
    post_event_date: date | None
    confidence_note: str


class Sentinel1Adapter:
    name = "sentinel1"

    def fetch_structural_change(self, lat: float, lon: float, event_date: date, buffer_m: int = 500) -> StructuralChangeResult:
        if settings.use_gee_backend:
            return self._via_gee(lat, lon, event_date, buffer_m)
        return self._via_hyp3(lat, lon, event_date, buffer_m)

    def _via_gee(self, lat: float, lon: float, event_date: date, buffer_m: int) -> StructuralChangeResult:
        """Amplitude-based (incoherent) change detection using Sentinel-1
        GRD VV backscatter — simpler than full InSAR coherence and good
        enough as a corroborating signal, not a certified damage map.
        See docs/ARCHITECTURE.md for why this is a confirmation gate, not
        a standalone detector.
        """
        import ee

        ee.Initialize(ee.ServiceAccountCredentials(None, settings.gee_service_account_json_path))
        point = ee.Geometry.Point([lon, lat]).buffer(buffer_m)

        pre_window = (event_date - timedelta(days=24), event_date - timedelta(days=1))
        post_window = (event_date + timedelta(days=1), event_date + timedelta(days=12))

        def mean_vv(start: date, end: date):
            coll = (
                ee.ImageCollection("COPERNICUS/S1_GRD")
                .filterBounds(point)
                .filterDate(start.isoformat(), end.isoformat())
                .filter(ee.Filter.eq("instrumentMode", "IW"))
                .select("VV")
            )
            return coll.mean().reduceRegion(ee.Reducer.mean(), point, scale=20).get("VV")

        pre_val = mean_vv(*pre_window).getInfo()
        post_val = mean_vv(*post_window).getInfo()

        if pre_val is None or post_val is None:
            return StructuralChangeResult(
                None, None, None, "insufficient Sentinel-1 coverage in the pre/post window"
            )

        # VV backscatter is in dB; a large drop suggests loss of the
        # double-bounce/structural return typical of a demolished or
        # collapsed structure. This is a coarse proxy, not InSAR coherence.
        drop_ratio = max(0.0, min(1.0, (pre_val - post_val) / abs(pre_val))) if pre_val else None
        return StructuralChangeResult(
            coherence_drop_ratio=drop_ratio,
            pre_event_date=pre_window[1],
            post_event_date=post_window[0],
            confidence_note="GRD amplitude proxy (GEE backend) — not full InSAR coherence",
        )

    def _via_hyp3(self, lat: float, lon: float, event_date: date, buffer_m: int) -> StructuralChangeResult:
        """Placeholder for the ASF HyP3 on-demand InSAR coherence product —
        submitting a HyP3 job is an async, multi-minute-to-hours operation
        (you POST a job, poll for completion, then download a GeoTIFF), so
        this is intentionally left as a documented integration point rather
        than a synchronous call. See https://hyp3-docs.asf.alaska.edu/using/sdk/
        for the actual job-submission API once you're ready to wire it in.
        """
        logger.info(
            "HyP3 backend selected but not implemented synchronously — "
            "submit a coherence job for (%s, %s) around %s via the HyP3 SDK "
            "and poll separately; see the docstring for the reference.",
            lat, lon, event_date,
        )
        return StructuralChangeResult(None, None, None, "HyP3 backend requires async job submission — see docstring")

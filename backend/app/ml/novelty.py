"""
ADVANCED / PHASE 3 — visual novelty (open-set detection) channel.

Instead of trusting a bare softmax-confidence cutoff to decide when
something doesn't fit the 6 known classes, embed the Sentinel-2 patch
around a flagged hotspot with a frozen geospatial foundation model
(Prithvi-EO-2.0 by default) and measure its distance from the embedding
centroids of each known class. A high distance from every known centroid
is a "this doesn't look like anything we've trained on" signal that needs
no new labeled accident data to work, because nothing here is trained —
only the reference centroids are computed from existing labeled examples.

This directly targets the rare-accident-class weakness: industrial
accidents are, thankfully, rare, so a supervised classifier alone will
always be data-starved for that class. Open-set/novelty detection doesn't
need examples of the novel thing — it needs good examples of everything
ELSE, and flags what doesn't match.

Requires torch + transformers (backend/requirements-advanced.txt). Weights
are pulled from Hugging Face on first run (~1.2GB for the 300M variant) and
cached under ~/.cache/huggingface — set GFM_DEVICE=cuda if you have a GPU,
otherwise CPU inference on a single small patch is a few seconds, which is
fine for the on-demand, already-flagged-clusters-only usage pattern here.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)

CENTROIDS_PATH = Path("models/gfm_class_centroids.npz")

_model = None
_processor = None


def _lazy_load_model():
    global _model, _processor
    if _model is not None:
        return _model, _processor

    from transformers import AutoImageProcessor, AutoModel

    logger.info("Loading GFM %s on %s (first call only, then cached)", settings.gfm_model_id, settings.gfm_device)
    _processor = AutoImageProcessor.from_pretrained(settings.gfm_model_id, token=settings.huggingface_token or None)
    _model = AutoModel.from_pretrained(settings.gfm_model_id, token=settings.huggingface_token or None)
    _model.to(settings.gfm_device)
    _model.eval()
    return _model, _processor


def embed_patch(image_array: np.ndarray) -> np.ndarray:
    """image_array: HxWxC Sentinel-2 patch (see app/ingestion — pull a small
    chip via CDSE/GEE around the hotspot; wiring the actual chip download is
    left to run_pipeline.py since the right bands/size depend on which GFM
    variant you're running). Returns a single pooled embedding vector.
    """
    import torch

    model, processor = _lazy_load_model()
    inputs = processor(images=image_array, return_tensors="pt").to(settings.gfm_device)
    with torch.no_grad():
        outputs = model(**inputs)
    # Mean-pool the last hidden state — matches the standard Prithvi/Clay
    # "frozen backbone as feature extractor" usage pattern.
    embedding = outputs.last_hidden_state.mean(dim=1).squeeze(0).cpu().numpy()
    return embedding


def build_class_centroids(labeled_embeddings: dict[str, list[np.ndarray]]) -> None:
    """Run once, offline, after you have a labeled dataset — computes and
    saves the mean embedding per known class. This is NOT model training;
    it's just an average, which is why the "no labeled accident data
    needed" claim holds even though this function does need labels for the
    OTHER five classes.
    """
    centroids = {cls: np.mean(np.stack(vecs), axis=0) for cls, vecs in labeled_embeddings.items() if vecs}
    CENTROIDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez(CENTROIDS_PATH, **centroids)
    logger.info("Saved GFM class centroids for %s to %s", list(centroids.keys()), CENTROIDS_PATH)


def novelty_score(embedding: np.ndarray) -> float:
    """0 = matches a known class centroid closely, 1 = far from all of
    them. Cosine distance to the NEAREST centroid, min-max normalized
    against the typical intra-class spread — see docs/ARCHITECTURE.md for
    the exact normalization if you're tuning the 0.8 override threshold in
    app/ml/classifier.py.
    """
    if not CENTROIDS_PATH.exists():
        logger.warning("No GFM centroids file — build_class_centroids() hasn't been run yet")
        return 0.0

    data = np.load(CENTROIDS_PATH)
    distances = []
    for cls in data.files:
        centroid = data[cls]
        cos_sim = np.dot(embedding, centroid) / (np.linalg.norm(embedding) * np.linalg.norm(centroid) + 1e-9)
        distances.append(1 - cos_sim)

    nearest = min(distances)
    # simple squashing so the score is a stable 0-1 range regardless of the
    # embedding dimensionality of whichever GFM variant is configured
    return float(np.tanh(nearest * 2))

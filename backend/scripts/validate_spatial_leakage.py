"""
Diagnostic to run BEFORE trusting app/ml/train.py's spatial-block holdout
number: a spatial-block split is only meaningful if your labeled dataset
actually spans enough distinct blocks per class. If (say) 90% of your
"gas_flare" labels come from 3 refineries, a spatial-block holdout for
that class is barely different from a random one — the honest fix is
more geographically diverse labels, not a different split strategy.

Run with:  python -m scripts.validate_spatial_leakage --labels <path>.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from app.ml.train import SPATIAL_BLOCK_DEGREES, _spatial_block_id

MIN_BLOCKS_PER_CLASS_WARNING = 8


def main(labels_path: Path) -> None:
    df = pd.read_csv(labels_path)
    df["block"] = df.apply(lambda r: _spatial_block_id(r["lat"], r["lon"]), axis=1)

    print(f"Spatial block size: {SPATIAL_BLOCK_DEGREES} degrees (~{SPATIAL_BLOCK_DEGREES * 111:.0f} km)")
    print(f"Total rows: {len(df)} across {df['block'].nunique()} distinct blocks\n")

    summary = df.groupby("label")["block"].nunique().sort_values()
    print("Distinct spatial blocks per class:")
    for label, n_blocks in summary.items():
        flag = "  <-- TOO FEW for a meaningful spatial holdout" if n_blocks < MIN_BLOCKS_PER_CLASS_WARNING else ""
        print(f"  {label:20s} {n_blocks:4d} blocks{flag}")

    thin_classes = summary[summary < MIN_BLOCKS_PER_CLASS_WARNING].index.tolist()
    if thin_classes:
        print(
            f"\nWarning: {thin_classes} have fewer than {MIN_BLOCKS_PER_CLASS_WARNING} distinct spatial "
            "blocks. A spatial-block holdout F1 for these classes will be noisy or misleading — collect "
            "more geographically diverse labels before reporting a per-class number for them, or report "
            "only the macro-average with this caveat stated explicitly."
        )
    else:
        print("\nAll classes clear the minimum block-diversity bar for a meaningful spatial holdout.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True)
    args = parser.parse_args()
    main(args.labels)

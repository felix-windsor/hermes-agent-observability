"""Regenerate the local sample dataset."""
from __future__ import annotations

from collector.store import seed_sample_data


if __name__ == "__main__":
    seed_sample_data(force=True)
    print("Sample observability data regenerated.")

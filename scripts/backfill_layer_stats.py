"""One-off backfill: recompute feature_count/total_length_km on existing layers.

Two bugs, now fixed in app/gis/service.py, meant every GISLayer created before
the fix carries stale aggregate columns even though its real geometry sits
untouched in gis_features: feature_count was never set for the manual/paste/
Overpass path (only file-upload set it), and total_length_km was never
computed at all outside file-upload. This script only recomputes those two
derived statistics columns from the features that already exist for each
layer — it reads gis_features, it never writes to it, so no user-entered
geometry or any other data is touched.

    python scripts/backfill_layer_stats.py          # dry run, prints what would change
    python scripts/backfill_layer_stats.py --apply   # writes the corrected values
"""

import asyncio
import sys

from sqlalchemy import select, text

from app.core.db import AsyncSessionLocal
from app.gis.models import GISLayer


async def main(apply: bool) -> None:
    async with AsyncSessionLocal() as db:
        layers = (await db.scalars(select(GISLayer))).all()
        changed = 0
        for layer in layers:
            real_count = await db.scalar(
                text("SELECT count(*) FROM gis_features WHERE layer_id = :layer_id"),
                {"layer_id": str(layer.id)},
            )
            has_any_line = await db.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM gis_features WHERE layer_id = :layer_id "
                    "AND GeometryType(geom) IN ('LINESTRING', 'MULTILINESTRING'))"
                ),
                {"layer_id": str(layer.id)},
            )
            real_length = None
            if has_any_line:
                total_m = await db.scalar(
                    text(
                        "SELECT COALESCE(SUM(ST_Length(geography(geom))), 0) FROM gis_features "
                        "WHERE layer_id = :layer_id AND GeometryType(geom) IN ('LINESTRING', 'MULTILINESTRING')"
                    ),
                    {"layer_id": str(layer.id)},
                )
                real_length = round(float(total_m) / 1000, 3)

            if layer.feature_count == real_count and layer.total_length_km == real_length:
                continue
            changed += 1
            print(
                f"{layer.layer_name!r} ({layer.id}): "
                f"feature_count {layer.feature_count} -> {real_count}, "
                f"total_length_km {layer.total_length_km} -> {real_length}"
            )
            if apply:
                layer.feature_count = real_count
                layer.total_length_km = real_length

        if apply:
            await db.commit()
            print(f"\nUpdated {changed} layer(s).")
        else:
            print(f"\n{changed} layer(s) would change. Re-run with --apply to write.")


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))

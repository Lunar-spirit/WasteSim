"""Stage 0 (structural) + CRS handling for a GIS_LAYER upload: turn a
GeoJSON, KML, or zipped Shapefile into a flat list of (WKT geometry,
properties, length_m) records, always in EPSG:4326.

Safety for the ZIP case (a shapefile bundle) — ERR-06: extraction happens
only into a fresh temp directory, entry names are checked for path
traversal ("..", absolute paths), and the archive's compression ratio is
checked for a decompression-bomb pattern, before anything is handed to GDAL.

BR-07 (never assume WGS84): a missing/unreadable CRS raises
CRSUndeclaredError rather than defaulting to 4326.
"""

from __future__ import annotations

import io
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import pyproj
from shapely.ops import transform as shapely_transform

# A legitimate shapefile bundle (.shp/.shx/.dbf/.prj, maybe .cpg) never gets
# anywhere near this; a hand-crafted zip bomb (a few KB compressing to GBs)
# does.
MAX_COMPRESSION_RATIO = 100

_TO_WEB_MERCATOR = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform


class ParseError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message


class CRSUndeclaredError(Exception):
    """No CRS could be determined for the source file (e.g. a shapefile with
    no .prj). Distinct from ParseError so the caller can map it to the
    specific CRS_UNDECLARED issue code (BR-07) instead of a generic one."""


@dataclass
class ParsedFeature:
    wkt: str
    properties: dict[str, Any]
    length_m: float | None


@dataclass
class ParsedLayer:
    features: list[ParsedFeature]
    geometry_type: str
    srid_original: int | None


def _safe_extract_zip(data: bytes, dest: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        total_uncompressed = 0
        for info in zf.infolist():
            name = info.filename
            if name.startswith("/") or ".." in Path(name).parts:
                raise ParseError(f"unsafe path in archive: {name}")
            total_uncompressed += info.file_size
        if len(data) > 0 and total_uncompressed / len(data) > MAX_COMPRESSION_RATIO:
            raise ParseError("archive compression ratio looks like a decompression bomb")
        zf.extractall(dest)


def parse_gis_file(data: bytes, extension: str) -> ParsedLayer:
    """`extension` is one of "geojson", "kml", "zip" (a zipped shapefile) —
    the three GIS-layer formats API-34 accepts."""
    with tempfile.TemporaryDirectory(prefix="swms_gis_") as tmp:
        tmp_path = Path(tmp)

        if extension == "zip":
            _safe_extract_zip(data, tmp_path)
            shp_files = list(tmp_path.rglob("*.shp"))
            if not shp_files:
                raise ParseError("no .shp file found inside the archive")
            source_path = shp_files[0]
            if not list(tmp_path.rglob("*.prj")):
                raise CRSUndeclaredError()
        elif extension in ("geojson", "kml"):
            source_path = tmp_path / f"layer.{extension}"
            source_path.write_bytes(data)
        else:
            raise ParseError(f"'.{extension}' is not a supported GIS_LAYER format")

        try:
            gdf = gpd.read_file(source_path, engine="pyogrio")
        except Exception as exc:
            raise ParseError(f"could not read the file: {exc}") from exc

        if gdf.empty:
            raise ParseError("file contains no features")

        if gdf.crs is None:
            raise CRSUndeclaredError()

        try:
            srid_original = gdf.crs.to_epsg()
        except Exception:
            srid_original = None
        if srid_original != 4326:
            gdf = gdf.to_crs(4326)

        features: list[ParsedFeature] = []
        geometry_types: set[str] = set()
        property_columns = [c for c in gdf.columns if c != "geometry"]

        for _, row in gdf.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            if not geom.is_valid:
                # A cheap, well-known repair for self-intersections etc.;
                # ST_MakeValid at insert time (see service.py) is the
                # authoritative repair, this just avoids handing PostGIS
                # something pyproj's reprojection made worse.
                geom = geom.buffer(0)
                if geom.is_empty:
                    continue

            properties = {
                col: (val.item() if hasattr(val, "item") else val)
                for col, val in row[property_columns].items()
                if val is not None
            }

            length_m = None
            if geom.geom_type in ("LineString", "MultiLineString"):
                length_m = shapely_transform(_TO_WEB_MERCATOR, geom).length

            geometry_types.add(geom.geom_type)
            features.append(ParsedFeature(wkt=geom.wkt, properties=properties, length_m=length_m))

        if not features:
            raise ParseError("every feature in the file was empty or unrepairable")

        geometry_type = geometry_types.pop() if len(geometry_types) == 1 else "GEOMETRY"
        return ParsedLayer(features=features, geometry_type=geometry_type, srid_original=srid_original)

"""Minimal KML / KMZ mission-area loader (stdlib only, no new deps).

Extracts Polygon outlines (and LineString routes) as ``[(lat, lon), ...]``
lists.  Used by the GCS "LOAD AREA" control to define the disaster search
boundary shown on the map and used for coverage geometry.
"""

from __future__ import annotations

import io
import os
import xml.etree.ElementTree as ET
import zipfile


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_coords(text: str) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for token in (text or "").split():
        parts = token.split(",")
        if len(parts) >= 2:
            try:
                lon, lat = float(parts[0]), float(parts[1])
            except ValueError:
                continue
            pts.append((lat, lon))
    return pts


def _find_kml_bytes(path: str) -> bytes:
    if path.lower().endswith(".kmz"):
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
            if not names:
                raise ValueError("KMZ contains no .kml file")
            return zf.read(names[0])
    with open(path, "rb") as fh:
        return fh.read()


def load_kml(path: str) -> dict:
    """Return ``{"polygons": [[(lat, lon), ...]], "lines": [[...]], ...}``.

    Raises on unreadable / invalid files so the caller can show an error.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    root = ET.fromstring(_find_kml_bytes(path))

    polygons: list[list[tuple[float, float]]] = []
    lines: list[list[tuple[float, float]]] = []

    for elem in root.iter():
        name = _local(elem.tag)
        if name == "Polygon":
            for child in elem.iter():
                if _local(child.tag) == "coordinates":
                    pts = _parse_coords(child.text or "")
                    if len(pts) >= 3:
                        polygons.append(pts)
                    break
        elif name == "LineString":
            for child in elem.iter():
                if _local(child.tag) == "coordinates":
                    pts = _parse_coords(child.text or "")
                    if len(pts) >= 2:
                        lines.append(pts)
                    break

    if not polygons and not lines:
        raise ValueError("No Polygon or LineString geometry found in KML")

    all_pts = [p for poly in polygons for p in poly] + \
              [p for line in lines for p in line]
    centroid = (
        sum(p[0] for p in all_pts) / len(all_pts),
        sum(p[1] for p in all_pts) / len(all_pts),
    )
    return {
        "polygons": polygons,
        "lines": lines,
        "centroid": centroid,
        "name": os.path.splitext(os.path.basename(path))[0],
        "path": path,
    }

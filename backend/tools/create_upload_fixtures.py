"""Create small, valid GeoTIFF and Shapefile upload fixtures.

The writer uses only the Python standard library so the fixtures can be
regenerated before installing rasterio/geopandas in a local environment.
Both files use EPSG:4326 and cover small areas inside Khon Kaen.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import struct
import zipfile
from pathlib import Path


BOUNDS = (101.4, 15.6, 103.0, 17.0)


def _tiff_entry(tag: int, kind: int, count: int, value: int) -> bytes:
    """Build one little-endian TIFF IFD entry with an inline integer value."""
    if kind == 3 and count == 1:
        raw = struct.pack("<H", value) + b"\x00\x00"
    elif kind == 4 and count == 1:
        raw = struct.pack("<I", value)
    else:
        # For payloads larger than four bytes the IFD stores an offset.
        raw = struct.pack("<I", value)
    return struct.pack("<HHI", tag, kind, count) + raw


def create_geotiff(path: Path) -> None:
    width, height = 4, 4
    west, south, east, north = BOUNDS
    values = [
        0.15, 0.35, 0.55, 0.75,
        0.20, 0.40, 0.60, 0.80,
        0.25, 0.45, 0.65, 0.85,
        0.30, 0.50, 0.70, 0.90,
    ]

    # IFD starts at byte 8.  All non-inline tag payloads are placed directly
    # after the fixed-size IFD, followed by the float32 strip.
    entries_count = 16
    extra_offset = 8 + 2 + entries_count * 12 + 4
    scale_offset = extra_offset
    tiepoint_offset = scale_offset + 24
    geokey_offset = tiepoint_offset + 48
    nodata_offset = geokey_offset + 32
    strip_offset = nodata_offset + 4 + 20

    entries = [
        _tiff_entry(256, 3, 1, width),
        _tiff_entry(257, 3, 1, height),
        _tiff_entry(258, 3, 1, 32),
        _tiff_entry(259, 3, 1, 1),
        _tiff_entry(262, 3, 1, 1),
        _tiff_entry(273, 4, 1, strip_offset),
        _tiff_entry(277, 3, 1, 1),
        _tiff_entry(278, 4, 1, height),
        _tiff_entry(279, 4, 1, width * height * 4),
        _tiff_entry(284, 3, 1, 1),
        _tiff_entry(339, 3, 1, 3),  # IEEE floating point sample format
        _tiff_entry(33550, 12, 3, scale_offset),
        _tiff_entry(33922, 12, 6, tiepoint_offset),
        _tiff_entry(34735, 3, 16, geokey_offset),
        _tiff_entry(42113, 2, 4, nodata_offset),
        _tiff_entry(306, 2, 20, nodata_offset + 4),
    ]
    entries.sort(key=lambda entry: struct.unpack_from("<H", entry)[0])

    extra = io.BytesIO()
    extra.write(struct.pack("<3d", (east - west) / width, (north - south) / height, 0.0))
    extra.write(struct.pack("<6d", 0.0, 0.0, 0.0, west, north, 0.0))
    extra.write(struct.pack("<16H", 1, 1, 0, 3, 1024, 0, 1, 2,
                            1025, 0, 1, 1, 2048, 0, 1, 4326))
    extra.write(b"nan\x00")
    extra.write(b"2026-10-10\x00" + b"\x00" * 9)
    assert extra.tell() == strip_offset - extra_offset

    raw = bytearray(b"II" + struct.pack("<H", 42) + struct.pack("<I", 8))
    raw.extend(struct.pack("<H", len(entries)))
    raw.extend(b"".join(entries))
    raw.extend(struct.pack("<I", 0))
    raw.extend(extra.getvalue())
    raw.extend(struct.pack("<16f", *values))
    path.write_bytes(raw)


def _shp_header(file_length_words: int, bbox: tuple[float, float, float, float]) -> bytes:
    minx, miny, maxx, maxy = bbox
    header = bytearray(100)
    struct.pack_into(">i", header, 0, 9994)
    struct.pack_into(">i", header, 24, file_length_words)
    struct.pack_into("<i", header, 28, 1000)
    struct.pack_into("<i", header, 32, 5)
    struct.pack_into("<4d", header, 36, minx, miny, maxx, maxy)
    return bytes(header)


def _polygon_record(points: list[tuple[float, float]]) -> bytes:
    minx = min(point[0] for point in points)
    miny = min(point[1] for point in points)
    maxx = max(point[0] for point in points)
    maxy = max(point[1] for point in points)
    content = bytearray(struct.pack("<i4d2i", 5, minx, miny, maxx, maxy, 1, len(points)))
    content.extend(struct.pack("<i", 0))
    content.extend(b"".join(struct.pack("<2d", *point) for point in points))
    return bytes(content)


def _dbf(labels: list[str]) -> bytes:
    today = dt.date.today()
    field_name = b"NAME"
    field = field_name + b"\x00" * (11 - len(field_name)) + b"C" + b"\x00" * 4 + bytes([20, 0]) + b"\x00" * 14
    header = struct.pack("<BBBBIHH20x", 3, today.year - 1900, today.month, today.day,
                         len(labels), 65, 21)
    rows = b"".join(b" " + label.encode("ascii")[:20].ljust(20) for label in labels)
    return header + field + b"\x0d" + rows + b"\x1a"


def create_shapefile_zip(path: Path) -> None:
    polygons = [
        [(101.70, 16.20), (102.00, 16.20), (102.00, 16.50), (101.70, 16.50), (101.70, 16.20)],
        [(102.30, 16.00), (102.60, 16.00), (102.60, 16.30), (102.30, 16.30), (102.30, 16.00)],
    ]
    records = [_polygon_record(points) for points in polygons]
    bbox = (min(x for p in polygons for x, _ in p),
            min(y for p in polygons for _, y in p),
            max(x for p in polygons for x, _ in p),
            max(y for p in polygons for _, y in p))

    shp_length = (100 + sum(8 + len(record) for record in records)) // 2
    shx_length = (100 + len(records) * 8) // 2
    shp = bytearray(_shp_header(shp_length, bbox))
    shx = bytearray(_shp_header(shx_length, bbox))
    offset_words = 50
    for index, record in enumerate(records, start=1):
        shp.extend(struct.pack(">2i", index, len(record) // 2))
        shp.extend(record)
        shx.extend(struct.pack(">2i", offset_words, len(record) // 2))
        offset_words += 4 + len(record) // 2

    prj = ('GEOGCS["WGS 84",DATUM["WGS_1984",'
           'SPHEROID["WGS 84",6378137,298.257223563]],'
           'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]')
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("khonkaen-demo.shp", shp)
        archive.writestr("khonkaen-demo.shx", shx)
        archive.writestr("khonkaen-demo.dbf", _dbf(["demo-a", "demo-b"]))
        archive.writestr("khonkaen-demo.prj", prj)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("upload-fixtures"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    create_geotiff(args.output / "khonkaen-demo-layer.tif")
    create_shapefile_zip(args.output / "khonkaen-demo-layer-shapefile.zip")
    print(f"Created fixtures in {args.output.resolve()}")


if __name__ == "__main__":
    main()

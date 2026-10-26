from pathlib import Path

import h3
import shapefile
from pyproj import CRS, Transformer
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import transform, unary_union


def generate_grids(shapefile_path="/data/powiat.shp", resolutions=(6, 7, 8)):
    path = Path(shapefile_path)

    if not path.exists():
        raise FileNotFoundError(f"Brak pliku: {path}")

    source_crs = CRS.from_wkt(path.with_suffix(".prj").read_text())
    to_metric = Transformer.from_crs(
        source_crs, "EPSG:2180", always_xy=True
    ).transform
    to_wgs84 = Transformer.from_crs(
        "EPSG:2180", "EPSG:4326", always_xy=True
    ).transform
    from_wgs84 = Transformer.from_crs(
        "EPSG:4326", "EPSG:2180", always_xy=True
    ).transform

    with shapefile.Reader(str(path)) as reader:
        geometries = [
            shape(item.__geo_interface__) for item in reader.shapes()
        ]

    county = transform(to_metric, unary_union(geometries))

    if not county.is_valid:
        county = county.buffer(0)

    # Bufor pozwala znaleźć również komórki przecinające granicę powiatu.
    search_area = transform(
        to_wgs84, county.buffer(20000).envelope
    )

    grids = {}

    for resolution in resolutions:
        rows = []

        for cell_id in sorted(
            h3.geo_to_cells(mapping(search_area), resolution)
        ):
            boundary = [
                (longitude, latitude)
                for latitude, longitude in h3.cell_to_boundary(cell_id)
            ]
            cell = transform(from_wgs84, Polygon(boundary))
            clipped = cell.intersection(county)

            if clipped.is_empty or clipped.area <= 0:
                continue

            if clipped.geom_type == "Polygon":
                clipped = MultiPolygon([clipped])
            elif clipped.geom_type != "MultiPolygon":
                parts = [
                    part for part in clipped.geoms
                    if part.geom_type in ("Polygon", "MultiPolygon")
                ]
                clipped = unary_union(parts)
                if clipped.geom_type == "Polygon":
                    clipped = MultiPolygon([clipped])

            if not clipped.is_empty:
                rows.append((cell_id, clipped.wkt))

        if not rows:
            raise RuntimeError(f"Pusta siatka dla poziomu {resolution}")

        grids[resolution] = rows

    return grids


if __name__ == "__main__":
    for resolution, rows in generate_grids().items():
        print(f"H3 poziom {resolution}: {len(rows)} komórek")
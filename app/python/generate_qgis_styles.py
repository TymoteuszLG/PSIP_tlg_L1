import os
from pathlib import Path
import xml.etree.ElementTree as ET

import psycopg
from psycopg import sql


COLORS = [
    "215,25,28,255",
    "253,174,97,255",
    "255,255,191,255",
    "166,217,106,255",
    "26,150,65,255",
]

LABELS = [
    "Bardzo niska ocena",
    "Niska ocena",
    "Srednia ocena",
    "Wysoka ocena",
    "Bardzo wysoka ocena",
]


def generate_style(path, minimum, maximum):
    if minimum >= maximum:
        raise RuntimeError(
            "Nie można utworzyć 5 klas: wszystkie wyniki są jednakowe."
        )

    bounds = [
        minimum + (maximum - minimum) * i / 5
        for i in range(6)
    ]
    bounds[0] = minimum
    bounds[-1] = maximum

    root = ET.Element("qgis", version="3.36.0", styleCategories="Symbology")

    renderer = ET.SubElement(
        root,
        "renderer-v2",
        type="graduatedSymbol",
        attr="score",
        graduatedMethod="GraduatedColor",
        symbollevels="0",
        forceraster="0",
        enableorderby="0",
    )

    ranges = ET.SubElement(renderer, "ranges")
    symbols = ET.SubElement(renderer, "symbols")

    for i, color in enumerate(COLORS):
        label = (
            f"{LABELS[i]} "
            f"({bounds[i]:.4f} do {bounds[i + 1]:.4f})"
        )

        ET.SubElement(
            ranges,
            "range",
            lower=repr(bounds[i]),
            upper=repr(bounds[i + 1]),
            label=label,
            symbol=str(i),
            render="true",
        )

        symbol = ET.SubElement(
            symbols,
            "symbol",
            name=str(i),
            type="fill",
            alpha="1",
            clip_to_extent="1",
            force_rhr="0",
        )

        layer = ET.SubElement(
            symbol,
            "layer",
            attrib={
                "class": "SimpleFill",
                "enabled": "1",
                "locked": "0",
                "pass": "0",
            },
        )

        options = ET.SubElement(layer, "Option", type="Map")

        properties = {
            "color": color,
            "style": "solid",
            "outline_color": "100,100,100,255",
            "outline_style": "solid",
            "outline_width": "0.08",
            "outline_width_unit": "MM",
            "joinstyle": "bevel",
            "offset": "0,0",
            "offset_unit": "MM",
        }

        for name, value in properties.items():
            ET.SubElement(
                options,
                "Option",
                name=name,
                value=value,
                type="QString",
            )

    ET.SubElement(
        renderer,
        "classificationMethod",
        id="EqualInterval",
    )

    ET.indent(root, space="  ")
    ET.ElementTree(root).write(
        path,
        encoding="utf-8",
        xml_declaration=True,
    )


def main():
    if os.environ.get("ENVIRONMENT") != "env-test":
        raise RuntimeError("Na razie uruchamiamy tylko na env-test.")

    output = Path("/output")
    output.mkdir(parents=True, exist_ok=True)

    settings = {
        "host": os.environ.get("POSTGRES_HOST", "postgis"),
        "port": int(os.environ.get("POSTGRES_PORT_INTERNAL", "5432")),
        "dbname": os.environ["POSTGRES_DB"],
        "user": os.environ["POSTGRES_USER"],
        "password": os.environ["POSTGRES_PASSWORD"],
        "connect_timeout": 10,
    }

    # Najpierw odczytujemy zakresy wszystkich trzech tabel.
    limits = {}

    with psycopg.connect(**settings) as connection:
        with connection.cursor() as cursor:
            for resolution in (6, 7, 8):
                table = sql.Identifier(
                    "trafficability", f"h3_r{resolution}"
                )

                cursor.execute(
                    sql.SQL("""
                        SELECT min(score), max(score), count(*)
                        FROM {}
                    """).format(table)
                )

                minimum, maximum, count = cursor.fetchone()

                if not count or minimum is None or maximum is None:
                    raise RuntimeError(
                        f"Brak wyników dla r{resolution}."
                    )

                if minimum >= maximum:
                    raise RuntimeError(
                        f"Wyniki r{resolution} nie są zróżnicowane."
                    )

                limits[resolution] = (float(minimum), float(maximum))

    for resolution, (minimum, maximum) in limits.items():
        path = output / f"trafficability_r{resolution}.qml"
        generate_style(path, minimum, maximum)
        print(f"Zapisano: {path}", flush=True)

    print("Gotowe. Style można wczytać w QGIS.", flush=True)


if __name__ == "__main__":
    main()
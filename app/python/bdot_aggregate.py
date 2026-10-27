import os

import psycopg
from psycopg import sql


def main():
    if os.getenv("ENVIRONMENT") != "env-test":
        raise RuntimeError(
            "Agregacja jest przeznaczona dla env-test."
        )

    settings = {
        "host": os.getenv("POSTGRES_HOST", "postgis"),
        "port": 5432,
        "dbname": os.environ["POSTGRES_DB"],
        "user": os.environ["POSTGRES_USER"],
        "password": os.environ["POSTGRES_PASSWORD"],
    }

    with psycopg.connect(**settings) as connection:
        layers = connection.execute("""
            SELECT f_table_name, srid
            FROM public.geometry_columns
            WHERE f_table_schema = 'bdot'
              AND f_geometry_column = 'geom'
            ORDER BY f_table_name
        """).fetchall()

        if len(layers) != 64:
            raise RuntimeError(
                f"Oczekiwano 64 warstw, znaleziono {len(layers)}."
            )

        if any(srid != 2180 for _, srid in layers):
            raise RuntimeError(
                "Warstwy BDOT muszą być w EPSG:2180."
            )

        for name, _ in layers:
            if name.rsplit("_", 1)[-1] not in ("a", "l", "p"):
                raise RuntimeError(
                    f"Nieznany rodzaj warstwy: {name}"
                )

        connection.execute(
            "CREATE SCHEMA IF NOT EXISTS results"
        )

        for resolution in (6, 7, 8):
            grid = sql.Identifier(
                "grid", f"h3_r{resolution}"
            )
            result = sql.Identifier(
                "results", f"h3_r{resolution}"
            )

            srids = connection.execute(
                sql.SQL("""
                    SELECT DISTINCT ST_SRID(geom)
                    FROM {}
                """).format(grid)
            ).fetchall()

            if srids != [(4326,)]:
                raise RuntimeError(
                    f"Siatka h3_r{resolution} musi być w EPSG:4326."
                )

            # Geometria robocza w EPSG:2180.
            # Wspólna precyzja przecięć: 0,001 m, czyli 1 mm.
            connection.execute(
                sql.SQL("""
                    CREATE TEMP TABLE grid_metric
                    ON COMMIT DROP AS
                    SELECT
                        h3_id,
                        ST_ReducePrecision(
                            ST_Transform(geom, 2180),
                            0.001
                        ) AS geom
                    FROM {}
                """).format(grid)
            )

            connection.execute("""
                CREATE INDEX ON grid_metric
                USING GIST (geom)
            """)
            connection.execute("ANALYZE grid_metric")

            # Odtwarzamy wyłącznie tabelę wynikową.
            connection.execute(
                sql.SQL(
                    "DROP TABLE IF EXISTS {}"
                ).format(result)
            )

            # Wynik zachowuje geometrię w EPSG:4326.
            connection.execute(
                sql.SQL("""
                    CREATE TABLE {} AS
                    SELECT
                        h3_id,
                        geom::geometry(
                            MultiPolygon, 4326
                        ) AS geom
                    FROM {}
                """).format(result, grid)
            )

            connection.execute(
                sql.SQL("""
                    ALTER TABLE {}
                    ADD PRIMARY KEY (h3_id)
                """).format(result)
            )

            connection.execute(
                sql.SQL("""
                    CREATE INDEX ON {}
                    USING GIST (geom)
                """).format(result)
            )

            for number, (name, _) in enumerate(
                layers, start=1
            ):
                kind = name.rsplit("_", 1)[-1]

                suffix = {
                    "a": "m2",
                    "l": "m",
                    "p": "count",
                }[kind]

                column = sql.Identifier(
                    f"{name}_{suffix}"
                )
                source = sql.Identifier("bdot", name)

                datatype = sql.SQL(
                    "BIGINT"
                    if kind == "p"
                    else "DOUBLE PRECISION"
                )

                connection.execute(
                    sql.SQL("""
                        ALTER TABLE {}
                        ADD COLUMN {} {}
                        NOT NULL DEFAULT 0
                    """).format(
                        result, column, datatype
                    )
                )

                if kind == "p":
                    # Liczymy punkty w komórkach.
                    # Punkt na wspólnej granicy przypisujemy
                    # tylko do komórki o najmniejszym h3_id.
                    query = sql.SQL("""
                        WITH counts AS (
                            SELECT
                                chosen.h3_id,
                                count(*) AS value
                            FROM {source} AS b

                            CROSS JOIN LATERAL
                                ST_DumpPoints(b.geom) AS p

                            CROSS JOIN LATERAL (
                                SELECT g.h3_id
                                FROM grid_metric AS g
                                WHERE ST_Covers(
                                    g.geom,
                                    p.geom
                                )
                                ORDER BY g.h3_id
                                LIMIT 1
                            ) AS chosen

                            GROUP BY chosen.h3_id
                        )

                        UPDATE {result} AS r
                        SET {column} = c.value
                        FROM counts AS c
                        WHERE r.h3_id = c.h3_id
                    """).format(
                        source=source,
                        result=result,
                        column=column,
                    )

                else:
                    # Poligony: powierzchnia w m².
                    # Linie: długość w metrach.
                    dimension = sql.SQL(
                        "3" if kind == "a" else "2"
                    )
                    measure = sql.SQL(
                        "ST_Area"
                        if kind == "a"
                        else "ST_Length"
                    )

                    query = sql.SQL("""
                        WITH totals AS (
                            SELECT
                                g.h3_id,

                                COALESCE(
                                    (
                                        SELECT SUM(
                                            {measure}(
                                                ST_CollectionExtract(
                                                    ST_Intersection(
                                                        g.geom,
                                                        ST_ReducePrecision(
                                                            b.geom,
                                                            0.001
                                                        ),
                                                        0.001
                                                    ),
                                                    {dimension}
                                                )
                                            )
                                        )

                                        FROM {source} AS b

                                        WHERE ST_Intersects(
                                            g.geom,
                                            b.geom
                                        )
                                    ),
                                    0
                                ) AS value

                            FROM grid_metric AS g
                        )

                        UPDATE {result} AS r
                        SET {column} = t.value
                        FROM totals AS t
                        WHERE r.h3_id = t.h3_id
                    """).format(
                        measure=measure,
                        dimension=dimension,
                        source=source,
                        result=result,
                        column=column,
                    )

                connection.execute(query)

                print(
                    f"H3 r{resolution} "
                    f"[{number}/64]: {name}",
                    flush=True,
                )

            # Zapisujemy kompletny wynik dla rozdzielczości.
            connection.commit()

            print(
                f"Zapisano results.h3_r{resolution}",
                flush=True,
            )

    print("Agregacja zakończona.", flush=True)


if __name__ == "__main__":
    main()
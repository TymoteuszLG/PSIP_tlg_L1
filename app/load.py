import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).parent / "python"))
from h3_generator import generate_grids


def main():
    settings = {
        "host": os.getenv("POSTGRES_HOST", "postgis"),
        "port": 5432,
        "dbname": os.environ["POSTGRES_DB"],
        "user": os.environ["POSTGRES_USER"],
        "password": os.environ["POSTGRES_PASSWORD"],
        "connect_timeout": 5,
    }

    for attempt in range(30):
        try:
            with psycopg.connect(**settings):
                pass
            break
        except psycopg.OperationalError:
            if attempt == 29:
                raise
            time.sleep(2)

    environment = os.environ.copy()
    environment.update({
        "PGHOST": settings["host"],
        "PGPORT": str(settings["port"]),
        "PGDATABASE": settings["dbname"],
        "PGUSER": settings["user"],
        "PGPASSWORD": settings["password"],
    })

    subprocess.run(
        [
            "ogr2ogr",
            "-f", "PostgreSQL",
            "PG:",
            "/data/powiat.shp",
            "-nln", "public.powiat",
            "-lco", "GEOMETRY_NAME=geom",
            "-t_srs", "EPSG:2180",
            "-overwrite",
        ],
        env=environment,
        check=True,
    )
    print("Wczytano granicę powiatu.", flush=True)

    grids = generate_grids()

    with psycopg.connect(**settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA IF NOT EXISTS grid")

            for resolution, rows in grids.items():
                table = sql.Identifier("grid", f"h3_r{resolution}")

                cursor.execute(
                    sql.SQL("DROP TABLE IF EXISTS {}").format(table)
                )
                cursor.execute(
                    sql.SQL("""
                        CREATE TABLE {} (
                            h3_id TEXT PRIMARY KEY,
                            geom geometry(MultiPolygon, 4326) NOT NULL
                        )
                    """).format(table)
                )
                cursor.executemany(
                    sql.SQL("""
                        INSERT INTO {} (h3_id, geom)
                        VALUES (%s, ST_GeomFromText(%s, 4326))
                    """).format(table),
                    rows,
                )
                cursor.execute(
                    sql.SQL("CREATE INDEX ON {} USING GIST (geom)")
                    .format(table)
                )

                print(
                    f"grid.h3_r{resolution}: zapisano {len(rows)} komórek",
                    flush=True,
                )

    print("Zapis do bazy zakończony.", flush=True)


if __name__ == "__main__":
    main()
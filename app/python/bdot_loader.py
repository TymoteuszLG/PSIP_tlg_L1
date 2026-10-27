import os
import re
import subprocess
from pathlib import Path

import psycopg
from psycopg import sql


def main():
    if os.getenv("ENVIRONMENT") != "env-test":
        raise RuntimeError("Import BDOT jest przeznaczony dla env-test.")

    folder = Path("/data/3010_SHP")
    files = sorted(folder.glob("*.shp"))

    if not files:
        raise RuntimeError(f"Nie znaleziono plików SHP w {folder}")

    environment = os.environ.copy()
    environment.update({
        "PGHOST": os.getenv("POSTGRES_HOST", "postgis"),
        "PGPORT": "5432",
        "PGDATABASE": os.environ["POSTGRES_DB"],
        "PGUSER": os.environ["POSTGRES_USER"],
        "PGPASSWORD": os.environ["POSTGRES_PASSWORD"],
    })

    connection_settings = {
        "host": environment["PGHOST"],
        "port": 5432,
        "dbname": environment["PGDATABASE"],
        "user": environment["PGUSER"],
        "password": environment["PGPASSWORD"],
    }

    layers = []
    for path in files:
        match = re.search(r"(OT_[A-Z0-9]+_[ALP])$", path.stem)
        if not match:
            raise RuntimeError(f"Nieznana nazwa warstwy: {path.name}")
        layers.append((path, match.group(1).lower()))

    if len({name for _, name in layers}) != len(layers):
        raise RuntimeError("Powtarzające się nazwy warstw.")

    with psycopg.connect(**connection_settings) as connection:
        connection.execute("CREATE SCHEMA IF NOT EXISTS bdot")

    for number, (path, table) in enumerate(layers, start=1):
        print(f"[{number}/{len(layers)}] Import: {table}", flush=True)

        subprocess.run(
            [
                "ogr2ogr",
                "-f", "PostgreSQL",
                "PG:",
                str(path),
                "-nln", f"bdot.{table}",
                "-lco", "GEOMETRY_NAME=geom",
                "-lco", "FID=bdot_id",
                "-lco", "SPATIAL_INDEX=GIST",
                "-t_srs", "EPSG:2180",
                "-dim", "XY",
                "-nlt", "PROMOTE_TO_MULTI",
                "-makevalid",
                "-overwrite",
            ],
            env=environment,
            check=True,
        )

        with psycopg.connect(**connection_settings) as connection:
            query = sql.SQL("SELECT count(*) FROM {}").format(
                sql.Identifier("bdot", table)
            )
            count = connection.execute(query).fetchone()[0]
            print(f"  Zapisano {count} obiektów.", flush=True)

    print(f"Import zakończony: {len(layers)} warstw.", flush=True)


if __name__ == "__main__":
    main()
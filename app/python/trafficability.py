import math
import os

import psycopg
from psycopg import sql


# Proponowane wagi naszego uproszczonego modelu.
# Wyższy wynik oznacza lepszą względną przejezdność.
WEIGHTS = {
    "ot_adja_a_m2": 0.00,
    "ot_adms_a_m2": 0.00,
    "ot_adms_p_count": 0.00,
    "ot_bubd_a_m2": -0.80,
    "ot_buhd_a_m2": -0.60,
    "ot_buhd_l_m": -0.60,
    "ot_buib_a_m2": -0.35,
    "ot_buin_l_m": 0.00,
    "ot_buit_a_m2": -0.30,
    "ot_buit_p_count": -0.10,
    "ot_busp_a_m2": -0.20,
    "ot_busp_l_m": -0.10,
    "ot_butr_l_m": -0.10,
    "ot_buuo_l_m": -0.35,
    "ot_buwt_p_count": -0.10,
    "ot_buzm_l_m": -0.65,
    "ot_buzt_a_m2": -0.65,
    "ot_buzt_p_count": -0.15,
    "ot_kuho_a_m2": -0.10,
    "ot_kuhu_a_m2": -0.15,
    "ot_kuko_a_m2": 0.00,
    "ot_kuko_p_count": 0.00,
    "ot_kumn_a_m2": -0.20,
    "ot_kuos_a_m2": -0.10,
    "ot_kupg_a_m2": -0.25,
    "ot_kupg_p_count": -0.05,
    "ot_kusc_a_m2": -0.20,
    "ot_kusk_a_m2": -0.10,
    "ot_oikm_a_m2": 0.00,
    "ot_oikm_l_m": -0.15,
    "ot_oikm_p_count": 0.00,
    "ot_oimk_a_m2": -1.00,
    "ot_oior_a_m2": -0.15,
    "ot_oior_l_m": -0.10,
    "ot_oior_p_count": -0.05,
    "ot_oipr_l_m": -0.30,
    "ot_oipr_p_count": -0.10,
    "ot_oisz_a_m2": -0.80,
    "ot_ptgn_a_m2": -0.25,
    "ot_ptkm_a_m2": 0.25,
    "ot_ptlz_a_m2": -0.85,
    "ot_ptnz_a_m2": 0.00,
    "ot_ptpl_a_m2": 0.40,
    "ot_ptrk_a_m2": -0.65,
    "ot_ptso_a_m2": -0.75,
    "ot_pttr_a_m2": 0.30,
    "ot_ptut_a_m2": -0.45,
    "ot_ptwp_a_m2": -1.00,
    "ot_ptwz_a_m2": -0.85,
    "ot_ptzb_a_m2": -0.35,
    "ot_skdr_l_m": 1.00,
    "ot_skjz_l_m": 0.50,
    "ot_skpp_l_m": 0.20,
    "ot_skrp_l_m": 0.00,
    "ot_skrw_p_count": 0.15,
    "ot_sktr_l_m": -0.45,
    "ot_suln_l_m": 0.00,
    "ot_supr_l_m": 0.00,
    "ot_swkn_l_m": -0.85,
    "ot_swrm_l_m": -0.50,
    "ot_swrs_l_m": -0.90,
    "ot_tcon_a_m2": 0.00,
    "ot_tcpk_a_m2": 0.00,
    "ot_tcrz_a_m2": 0.00,
}

RESOLUTIONS = (6, 7, 8)


def main():
    if os.environ.get("ENVIRONMENT") != "env-test":
        raise RuntimeError(
            "Ten skrypt można na razie uruchamiać tylko na env-test."
        )

    if len(WEIGHTS) != 64:
        raise RuntimeError("Słownik musi zawierać dokładnie 64 atrybuty.")

    if any(not -1 <= weight <= 1 for weight in WEIGHTS.values()):
        raise RuntimeError("Wagi muszą należeć do przedziału od -1 do 1.")

    columns = list(WEIGHTS)
    weights = list(WEIGHTS.values())

    settings = {
        "host": os.environ.get("POSTGRES_HOST", "postgis"),
        "port": int(os.environ.get("POSTGRES_PORT_INTERNAL", "5432")),
        "dbname": os.environ["POSTGRES_DB"],
        "user": os.environ["POSTGRES_USER"],
        "password": os.environ["POSTGRES_PASSWORD"],
        "connect_timeout": 10,
    }

    # Wszystkie wyniki powstają w jednej transakcji.
    # Błąd powoduje wycofanie zmian z tego uruchomienia.
    with psycopg.connect(**settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
            )
            cursor.execute("CREATE SCHEMA IF NOT EXISTS trafficability")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trafficability.parameters (
                    resolution INTEGER NOT NULL,
                    attribute TEXT NOT NULL,
                    weight DOUBLE PRECISION NOT NULL
                        CHECK (weight BETWEEN -1 AND 1),
                    min_value DOUBLE PRECISION NOT NULL,
                    max_value DOUBLE PRECISION NOT NULL,
                    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (resolution, attribute)
                )
            """)

            for resolution in RESOLUTIONS:
                table_name = f"h3_r{resolution}"
                source = sql.Identifier("results", table_name)
                target = sql.Identifier("trafficability", table_name)

                print(f"\nAnaliza results.{table_name}", flush=True)

                cursor.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'results'
                      AND table_name = %s
                      AND column_name NOT IN ('h3_id', 'geom')
                """, (table_name,))

                actual_columns = {row[0] for row in cursor.fetchall()}
                expected_columns = set(columns)

                if actual_columns != expected_columns:
                    raise RuntimeError(
                        f"{table_name}: niezgodna lista atrybutów. "
                        f"Brakujące: {sorted(expected_columns - actual_columns)}. "
                        f"Nadmiarowe: {sorted(actual_columns - expected_columns)}."
                    )

                cursor.execute(
                    sql.SQL("SELECT DISTINCT ST_SRID(geom) FROM {}")
                    .format(source)
                )
                if cursor.fetchall() != [(4326,)]:
                    raise RuntimeError(
                        f"{table_name}: wymagana niepusta geometria w EPSG:4326."
                    )

                cursor.execute(
                    sql.SQL("SELECT h3_id, {} FROM {} ORDER BY h3_id")
                    .format(
                        sql.SQL(", ").join(
                            sql.Identifier(column) for column in columns
                        ),
                        source,
                    )
                )
                rows = cursor.fetchall()

                if not rows:
                    raise RuntimeError(f"{table_name}: brak heksagonów.")

                values = []
                for row in rows:
                    numeric_row = []
                    for column, value in zip(columns, row[1:]):
                        if value is None:
                            raise RuntimeError(
                                f"{table_name}, {row[0]}, {column}: NULL."
                            )

                        number = float(value)
                        if not math.isfinite(number) or number < 0:
                            raise RuntimeError(
                                f"{table_name}, {row[0]}, {column}: "
                                "niepoprawna wartość."
                            )
                        numeric_row.append(number)

                    values.append(numeric_row)

                minima = [
                    min(row[j] for row in values)
                    for j in range(len(columns))
                ]
                maxima = [
                    max(row[j] for row in values)
                    for j in range(len(columns))
                ]

                cursor.execute(
                    sql.SQL("DROP TABLE IF EXISTS {}").format(target)
                )
                cursor.execute(
                    sql.SQL("""
                        CREATE TABLE {} AS
                        SELECT h3_id, geom::geometry(MultiPolygon, 4326) AS geom
                        FROM {}
                    """).format(target, source)
                )
                cursor.execute(
                    sql.SQL("ALTER TABLE {} ADD PRIMARY KEY (h3_id)")
                    .format(target)
                )

                for column in columns:
                    normalized_column = sql.Identifier(f"n_{column}")
                    cursor.execute(
                        sql.SQL("""
                            ALTER TABLE {}
                            ADD COLUMN {} DOUBLE PRECISION NOT NULL DEFAULT 0
                            CHECK ({} BETWEEN 0 AND 1)
                        """).format(
                            target,
                            normalized_column,
                            normalized_column,
                        )
                    )

                cursor.execute(
                    sql.SQL("""
                        ALTER TABLE {}
                        ADD COLUMN score DOUBLE PRECISION NOT NULL DEFAULT 0
                    """).format(target)
                )

                assignments = [
                    sql.SQL("{} = %s").format(
                        sql.Identifier(f"n_{column}")
                    )
                    for column in columns
                ]
                assignments.append(sql.SQL("score = %s"))

                update_query = sql.SQL("""
                    UPDATE {} SET {}
                    WHERE h3_id = %s
                """).format(target, sql.SQL(", ").join(assignments))

                updates = []
                scores = []

                for source_row, numeric_row in zip(rows, values):
                    normalized = []

                    for j, value in enumerate(numeric_row):
                        span = maxima[j] - minima[j]

                        # Stała kolumna nie różnicuje heksagonów.
                        normalized_value = (
                            0.0 if span == 0
                            else (value - minima[j]) / span
                        )
                        normalized.append(normalized_value)

                    score = math.fsum(
                        weight * value
                        for weight, value in zip(weights, normalized)
                    )

                    updates.append(
                        tuple(normalized) + (score, source_row[0])
                    )
                    scores.append(score)

                cursor.executemany(update_query, updates)

                cursor.execute(
                    sql.SQL("CREATE INDEX {} ON {} USING GIST (geom)")
                    .format(
                        sql.Identifier(f"{table_name}_geom_idx"),
                        target,
                    )
                )
                cursor.execute(
                    sql.SQL("ANALYZE {}").format(target)
                )

                cursor.execute("""
                    DELETE FROM trafficability.parameters
                    WHERE resolution = %s
                """, (resolution,))

                cursor.executemany("""
                    INSERT INTO trafficability.parameters
                        (resolution, attribute, weight, min_value, max_value)
                    VALUES (%s, %s, %s, %s, %s)
                """, [
                    (
                        resolution,
                        column,
                        WEIGHTS[column],
                        minima[j],
                        maxima[j],
                    )
                    for j, column in enumerate(columns)
                ])

                constant_count = sum(
                    minimum == maximum
                    for minimum, maximum in zip(minima, maxima)
                )

                print(
                    f"Heksagony: {len(rows)} | "
                    f"Atrybuty: {len(columns)} | "
                    f"Stałe kolumny: {constant_count}",
                    flush=True,
                )
                print(
                    f"score: min={min(scores):.6f}, "
                    f"max={max(scores):.6f}",
                    flush=True,
                )

        # Zatwierdzenie nastąpi przy poprawnym zakończeniu bloku connection.

    print(
        "\nZapisano trafficability.h3_r6, h3_r7 i h3_r8. "
        "Wagi i zakresy zapisano w trafficability.parameters.",
        flush=True,
    )


if __name__ == "__main__":
    main()
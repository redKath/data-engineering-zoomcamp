#!/usr/bin/env python
# /// script
# dependencies = [
#     "click",
#     "pandas",
#     "psycopg2-binary",
#     "sqlalchemy",
#     "tqdm",
# ]
# ///

import io
import click
import pandas as pd
from sqlalchemy import create_engine
from tqdm.auto import tqdm
import pyarrow.parquet as pq

dtype = {
    "VendorID": "Int64",
    "passenger_count": "Int64",
    "trip_distance": "float64",
    "RatecodeID": "Int64",
    "store_and_fwd_flag": "string",
    "PULocationID": "Int64",
    "DOLocationID": "Int64",
    "payment_type": "Int64",
    "fare_amount": "float64",
    "extra": "float64",
    "mta_tax": "float64",
    "tip_amount": "float64",
    "tolls_amount": "float64",
    "improvement_surcharge": "float64",
    "total_amount": "float64",
    "congestion_surcharge": "float64"
}

dtype2 = {
    "LocationID":      "Int64",
    "Borough":           "string",
    "Zone":              "string",
    "service_zone":      "string",
}

parse_dates = [
    "tpep_pickup_datetime",
    "tpep_dropoff_datetime"
]


def fast_pg_insert(df, table_name, raw_conn):
    """High-performance direct memory copy into PostgreSQL."""
    buffer = io.StringIO()
    df.to_csv(buffer, index=False, header=False)
    buffer.seek(0)

    with raw_conn.cursor() as cursor:
        cursor.copy_expert(f"COPY {table_name} FROM STDIN WITH CSV", buffer)
    raw_conn.commit()
    buffer.close()


@click.command()
@click.option('--pg-user', default='root', help='PostgreSQL user')
@click.option('--pg-pass', default='root', help='PostgreSQL password')
@click.option('--pg-host', default='localhost', help='PostgreSQL host')
@click.option('--pg-port', default=5432, type=int, help='PostgreSQL port')
@click.option('--pg-db', default='ny_taxi', help='PostgreSQL database name')
@click.option('--year', default=2021, type=int, help='Year of the data')
@click.option('--month', default=1, type=int, help='Month of the data')
@click.option('--target-table', default='yellow_taxi_data', help='Target table name')
@click.option('--chunksize', default=100000, type=int, help='Chunk size for reading CSV')
def run(pg_user, pg_pass, pg_host, pg_port, pg_db, year, month, target_table, chunksize):
    """Ingest NYC taxi data into PostgreSQL database using fast COPY protocol."""
    # prefix = 'https://github.com/DataTalksClub/nyc-tlc-data/releases/download/yellow'
    # url = f'{prefix}/yellow_tripdata_{year}-{month:02d}.csv.gz'
    # url = 'https://github.com/DataTalksClub/nyc-tlc-data/releases/download/misc/taxi_zone_lookup.csv'
    url = 'green_tripdata_2025-11.parquet'
    click.echo(f"\will insert data from '{url}'...")

    click.echo(f"Connecting to database {pg_db} at {pg_host}:{pg_port}...")
    engine = create_engine(f'postgresql+psycopg2://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}')

    click.echo(f"Downloading stream from {url}...")
    # df_iter = pd.read_csv(
    #     url,
    #     dtype=dtype,
    #     # parse_dates=parse_dates,
    #     iterator=True,
    #     chunksize=chunksize,
    # )
    parquet_file = pq.ParquetFile(url)
    df_iter = (batch.to_pandas() for batch in parquet_file.iter_batches(batch_size=chunksize))
    
    first = True
    raw_conn = engine.raw_connection()

    try:
        for df_chunk in tqdm(df_iter, desc="Ingesting chunks"):
            if first:
                # Replace table schema using zero-row DDL write on first chunk
                click.echo(f"\nCreating table '{target_table}'...")
                df_chunk.head(0).to_sql(
                    name=target_table,
                    con=engine,
                    if_exists='replace',
                    index=False
                )
                first = False

            # High-speed insert bypassing slow pandas to_sql rows
            fast_pg_insert(df_chunk, target_table, raw_conn)
            del df_chunk

    finally:
        raw_conn.close()
        engine.dispose()

    click.echo("Ingestion finished successfully!")


if __name__ == '__main__':
    run()
"""
Ricostruzione degli eventi di chiusura dai file CSV
- un evento reale esiste solo quando il Count di una testa incrementa rispetto alla riga precedente
"""

import csv
from src.config import DATA_DIR, NOMI_TESTE, SOGLIA_INCREMENTO 

def inspect_file(file_path, number_of_rows=2):
    """Read and display a few rows from a CSV file."""

    with open(
        file_path,
        mode="r",
        newline="",
        encoding="utf-8",
    ) as csv_file:
        reader = csv.DictReader(csv_file)

        if reader.fieldnames is None:
            raise ValueError(
                f"The file {file_path} does not contain a header"
            )

        print(f"File: {file_path.name}")
        print(f"Number of columns: {len(reader.fieldnames)}")

        for row_number, row in enumerate(reader, start=1):
            print(
                f"Row {row_number}: "
                f"timestamp={row['timestamp']}, "
                f"H01 Count={row['H01 Count']}, "
                f"H01 AppTorque={row['H01 AppTorque']}, "
                f"H01 Status={row['H01 Status']}"
            )

            if row_number >= number_of_rows:
                break

if __name__ == "__main__":
    csv_files = sorted(DATA_DIR.rglob("*.csv"))

    if not csv_files:
        raise FileNotFoundError(
            f"No CSV files found in {DATA_DIR}"
        )

    inspect_file(csv_files[0])


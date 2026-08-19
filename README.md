# ArolProjectQ3

Pipeline locale per ricostruire gli eventi di chiusura dalla telemetria AROL.

## Funzionalità disponibili

- lettura progressiva dei CSV senza caricarli tutti in memoria;
- continuità dei contatori tra file consecutivi;
- gestione di incrementi multipli, gap, reset e valori anomali;
- persistenza idempotente degli eventi in SQLite;
- filtri per tempo, testa, status e qualità;
- velocità aggregata della macchina su finestra mobile;
- test unitari e test end-to-end.

## Esecuzione

Dalla radice del repository:

```bash
python3 -m src.ingestion.pipeline
```

Per provare soltanto il primo CSV e scegliere un database temporaneo:

```bash
python3 -m src.ingestion.pipeline \
  --max-files 1 \
  --database /tmp/arol-events.db
```

## Test

```bash
python3 -m unittest discover -s tests -v
```

La spiegazione delle decisioni è disponibile in [`docs/SOLUTION.md`](docs/SOLUTION.md).

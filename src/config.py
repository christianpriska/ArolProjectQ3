"""
Configurazione centrale del progetto: 
- percorsi
- soglie
- costanti 
Tutti i percorsi e costanti vengono importati da qui.
"""

from pathlib import Path

# --- Percorsi --- 
SRC_DIR = Path(__file__).resolve().parent          
DATA_DIR = SRC_DIR / "data"          
DB_PATH = SRC_DIR / "storage" / "events.db"         

# --- Struttura della macchina ---
NUM_TESTE = 36
NOMI_TESTE = [f"H{n:02d}" for n in range(1, NUM_TESTE + 1)]

# --- Soglie di pulizia dati ---
# Due campioni distanti più di questa soglia non sono considerati consecutivi.
MAX_CONTIGUOUS_GAP_SECONDS = 2.0

# Limite configurabile usato per riconoscere incrementi fisicamente sospetti.
# Il valore definitivo dovrà essere confermato usando le specifiche della macchina.
MAX_CLOSURES_PER_HEAD_SECOND = 100.0

# Alias mantenuto per compatibilità con lo script di profiling esistente.
SOGLIA_INCREMENTO = int(MAX_CLOSURES_PER_HEAD_SECOND)

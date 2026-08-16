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
SOGLIA_INCREMENTO = 100      # oltre: incremento fisicamente impossibile (più di 100 chiusure al secondo) valore corrotto
"""
ANALISI DEI FILE CSV DELLE TESTE DI CHIUSURA

Questo programma analizza tutti i file CSV presenti nella cartella `src/data`.
Ogni file contiene i valori dei contatori di chiusura di 36 teste, denominate
da H01 a H36.

Per ogni testa, il programma confronta il valore `Count` di una riga con quello
della riga precedente:

- se il contatore aumenta, la differenza rappresenta il numero di chiusure
  avvenute tra le due rilevazioni;
- se il contatore diminuisce, viene rilevato un possibile reset del contatore,
  ad esempio causato da un riavvio della macchina;
- se l'aumento tra due righe supera una soglia impostata (>100 chiusure), il file viene
  considerato sospetto perché potrebbe contenere dati corrotti.

Alla fine, ogni file viene classificato in una delle seguenti categorie:

- "ok": nessun reset e nessun incremento anomalo;
- "riavvio macchina": almeno un contatore è diminuito;
- "SOSPETTO (dati corrotti)": almeno un contatore è aumentato oltre la soglia.

Il programma non modifica né elimina i file CSV: stampa soltanto il risultato
dell'analisi e un riepilogo finale dell'intero dataset.
"""

import csv
from src.config import DATA_DIR

def analizza_file(percorso, idx_count_teste):
    """Restituisce eventi totali, incremento massimo e reset rilevati."""
    eventi_totali = 0
    incremento_massimo = 0
    reset_rilevati = 0
    count_precedenti = [None] * 36

    with open(percorso, newline="") as file_csv:
        lettore = csv.reader(file_csv)
        next(lettore)  # Salta l'intestazione

        for riga in lettore:
            for i in range(36):
                count_attuale = float(riga[idx_count_teste[i]])
                count_precedente = count_precedenti[i]

                if count_precedente is not None:
                    if count_attuale > count_precedente:
                        incremento = count_attuale - count_precedente
                        eventi_totali += int(incremento)
                        incremento_massimo = max(
                            incremento_massimo,
                            incremento
                        )
                    elif count_attuale < count_precedente:
                        reset_rilevati += 1

                count_precedenti[i] = count_attuale

    return eventi_totali, incremento_massimo, reset_rilevati


SOGLIA_INCREMENTO = 100

files = sorted(DATA_DIR.rglob("*.csv"))

print(f"Cartella dati: {DATA_DIR}")
print(f"File CSV trovati: {len(files)}")

if not files:
    raise FileNotFoundError(f"Nessun file CSV trovato in {DATA_DIR}")

# Legge l'intestazione una sola volta, dal primo file.
with open(files[0], newline="") as file_csv:
    lettore = csv.reader(file_csv)
    intestazione = next(lettore)

nomi_teste = [f"H{n:02d}" for n in range(1, 37)]
idx_count_teste = [
    intestazione.index(f"{nome} Count")
    for nome in nomi_teste
]

print(f"Numero di colonne: {len(intestazione)}")
print(f"Colonne Count delle 36 teste: {idx_count_teste}")
print("\n--- Analisi dell'intero dataset ---")

file_sospetti = 0
file_con_riavvio = 0
eventi_dataset = 0

for percorso in files:
    eventi, incremento_massimo, reset = analizza_file(
        percorso,
        idx_count_teste
    )
    eventi_dataset += eventi

    if incremento_massimo > SOGLIA_INCREMENTO:
        etichetta = "SOSPETTO (dati corrotti)"
        file_sospetti += 1
    elif reset > 0:
        etichetta = "riavvio macchina"
        file_con_riavvio += 1
    else:
        etichetta = "ok"

    print(
        f"{percorso.name[-14:]}  "
        f"eventi={eventi:>10}  "
        f"inc.max={incremento_massimo:>8}  "
        f"reset={reset:>4}  "
        f"-> {etichetta}"
    )

print("\n--- Riepilogo ---")
print(f"Eventi totali nel dataset: {eventi_dataset}")
print(f"File sospetti/corrotti: {file_sospetti}")
print(f"File con riavvio: {file_con_riavvio}")
print(f"File ok: {len(files) - file_sospetti - file_con_riavvio}")
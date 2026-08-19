# Soluzione implementata nel branch `matte`

## Obiettivo

I CSV contengono una misurazione periodica per ogni testa. `Count` è cumulativo: quando aumenta, una o più chiusure sono avvenute dall'ultima misurazione.

La soluzione trasforma i CSV in eventi, conservando separatamente ciò che è stato osservato e ciò che può essere usato con sicurezza nei conteggi.

## Struttura di un evento

```text
timestamp
head_id
counter
counter_delta
elapsed_seconds
accepted_closure_count
torque_nm
status_code
reset_epoch
event_quality
source_file
```

- `counter_delta`: differenza osservata tra il contatore corrente e il precedente;
- `accepted_closure_count`: chiusure ammesse nei KPI, oppure `null` se il dato non è affidabile;
- `reset_epoch`: segmento del contatore dopo un reset;
- `event_quality`: spiega come è stato interpretato l'incremento.

## 1. Incrementi multipli

### Problema

```text
Count: 100 → 104
```

Il contatore indica quattro chiusure, ma il CSV fornisce un solo torque, status e timestamp.

### Soluzione

```text
counter_delta = 4
accepted_closure_count = 4
event_quality = "aggregated"
```

Viene conservato un solo record aggregato. Non vengono inventati quattro eventi con gli stessi dettagli.

## 2. Gap temporali

### Problema

```text
10:00 → Count 100
12:00 → Count 500
```

Sappiamo che il contatore è cambiato, ma non quando siano avvenute le singole chiusure.

### Soluzione

```text
counter_delta = 400
accepted_closure_count = null
event_quality = "gap"
```

Il cambiamento viene conservato, ma non viene attribuito a un istante preciso e non entra automaticamente nei KPI. I gap vengono rilevati anche tra due file.

## 3. Reset e duplicati

### Problema

```text
100 → 101 → 100 → 101
```

Se il decremento viene eliminato prima della deduplicazione, i due valori `101` sembrano lo stesso evento.

### Soluzione

Il decremento viene rilevato sui dati grezzi e incrementa `reset_epoch`:

```text
H01, reset_epoch 0, Count 101
H01, reset_epoch 1, Count 101
```

I due eventi appartengono a segmenti differenti e vengono entrambi conservati.

## 4. Incrementi anomali

### Problema

Un incremento molto grande in un intervallo breve può essere fisicamente impossibile.

### Soluzione

Il limite è configurabile in `src/config.py` e dipende dal tempo trascorso:

```text
accepted_closure_count = null
event_quality = "anomalous"
```

La soglia predefinita è provvisoria e deve essere confermata con le specifiche AROL.

## 5. Velocità della macchina

La velocità viene calcolata sommando le chiusure accettate di tutte le teste in una finestra completa:

```text
speed_pph = closures_in_window × 3600 / window_seconds
```

Esempio:

```text
500 chiusure in 5 minuti = 6.000 pezzi/ora
```

Dopo un gap la finestra viene azzerata; la velocità viene nuovamente prodotta soltanto dopo un intervallo completamente osservato.

## 5.1 Padding finale tutto a zero

Una macchina ferma conserva il valore raggiunto dai contatori. Alcuni CSV terminano invece con una sequenza in cui `Count`, `AppTorque` e `Status` sono tutti zero per tutte le teste.

La pipeline conserva eventuali righe a zero nel mezzo del file, ma esclude una sequenza tutta a zero soltanto quando arriva fino alla fine. Il numero di righe escluse viene riportato nel riepilogo e i CSV originali non vengono modificati.

## 6. Filtri

`src/analytics/events.py` permette di selezionare gli eventi per:

- intervallo temporale;
- una o più teste;
- status;
- qualità dell'evento;
- presenza di un numero di chiusure accettato.

Queste funzioni potranno essere usate successivamente dal BOT e dagli agenti analitici.

## 7. Database locale

Gli eventi vengono salvati nella tabella SQLite `closure_events`. Un vincolo `UNIQUE` evita che una seconda esecuzione inserisca nuovamente lo stesso evento.

La tabella `ingested_files` registra quanti eventi sono stati rilevati e inseriti per ogni file.

## Flusso completo

```text
CSV ordinati
  → ClosureExtractor
  → classificazione degli incrementi
  → inserimento incrementale in SQLite
  → filtri e analytics deterministiche
```

## Limiti ancora da validare

1. La soglia massima di chiusure al secondo deve essere confermata da AROL.
2. La politica prudente esclude dai KPI gli incrementi avvenuti durante un gap; il gruppo può decidere di includerli soltanto nei totali aggregati.
3. I timestamp vengono interpretati nel formato presente nei CSV senza assegnare automaticamente UTC.
4. La velocità prodotta rappresenta la macchina intera; una metrica separata per testa può essere aggiunta se richiesta.

## Verifica

I test coprono:

- incremento normale e multiplo;
- gap e incremento anomalo;
- reset normale e breve;
- continuità tra file;
- filtri;
- velocità aggregata;
- inserimento SQLite idempotente;
- flusso CSV → SQLite.

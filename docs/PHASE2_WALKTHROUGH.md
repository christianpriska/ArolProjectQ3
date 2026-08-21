# Fase 2 — Percorso completo: il livello di analisi (Layer 2)

Questo documento spiega, nello stesso spirito di `docs/PHASE1_WALKTHROUGH.md`, cosa fa
il livello di analisi costruito sopra ai dati puliti della Fase 1 — e perché è
costruito così.

---

## 1. Il problema e l'obiettivo

La Fase 1 ha prodotto due tabelle pulite: `closure_events.parquet` (55.1 milioni di
righe, una per chiusura) e `idle_periods.parquet` (i periodi di inattività). Ma
nessuna delle due risponde da sola a domande come "quale testa fallisce di più?",
"la macchina sta rallentando?", "quali eventi sono anomali?".

**Obiettivo**: un insieme di funzioni Python deterministiche (niente machine
learning, solo statistica classica — media, deviazione standard, test statistici)
che rispondono a queste domande. Non sono pensate per essere usate solo da una
persona: la Fase 3 (non ancora iniziata) collegherà queste stesse funzioni a un
agente AI che le userà come "strumenti" per rispondere in linguaggio naturale. Per
questo ogni funzione:
- accetta la tabella (o un sottoinsieme già filtrato) come parametro, mai un percorso
  di file — così è testabile e componibile
- restituisce sempre un dizionario con una chiave `summary` (testo leggibile) più i
  dati strutturati, non solo numeri sparsi

---

## 2. Mappa dei file: a cosa serve ciascuno

```
src/arol_analytics/analytics/
├── __init__.py       →  espone le 10 funzioni principali
├── __main__.py        →  permette di lanciare l'intera analisi da riga di comando
├── _common.py           →  pezzi condivisi: filtri, misurazione del tempo, conversione per JSON
├── io.py                  →  carica i due file .parquet della Fase 1
├── summary.py                →  strumenti 1-2 (riassunto del dataset, tasso di successo)
├── torque.py                    →  strumenti 3-4 (statistiche e trend della coppia)
├── anomaly.py                      →  strumento 5 (rilevamento anomalie)
├── heads.py                           →  strumenti 6-7 (confronto teste, analisi guasti)
├── production.py                         →  strumenti 8-9 (velocità di produzione, inattività)
└── dashboard.py                             →  strumento 10 (cruscotto riassuntivo)
```

### `_common.py` — i pezzi condivisi

Tre cose usate da (quasi) ogni strumento:
- `filter_events()`: applica gli stessi due filtri opzionali che quasi tutti gli
  strumenti accettano — per testa (`head_filter`) e per intervallo di tempo
  (`time_range`) — così non si riscrive la stessa logica 10 volte.
- `log_duration()`: misura quanto ci mette un blocco di codice, e scrive un avviso
  nel log se supera 5 secondi (richiesto perché il dataset ha 55 milioni di righe —
  utile sapere se un'operazione sta diventando lenta).
- `group_mean_std_flags()`: il calcolo "questo valore è a più di 2 deviazioni
  standard dalla media del gruppo?", usato in quasi tutti gli strumenti per segnalare
  teste o periodi anomali.

### `io.py` — caricare i dati

Due funzioni, `load_closure_events()` e `load_idle_periods()`, che leggono i file
`.parquet` della Fase 1. Una scelta di efficienza: le colonne testuali con pochi
valori possibili (`head_id`, `status_label`, `classification`, `source_file`) vengono
convertite in tipo "categoria" invece di testo libero — su 55 milioni di righe questo
fa una differenza reale di memoria (36 teste, non 55 milioni di stringhe diverse).

---

## 3. I 10 strumenti, uno per uno

### Tool 1 — `dataset_summary`

Panoramica generale: quante chiusure, quante teste, intervallo di tempo coperto,
quante hanno avuto successo/fallimento/nessun carico, e — se gli passi il report di
qualità della Fase 1 — eventuali avvisi (reset del contatore, buchi ai confini dei
file, ecc.) riportati in linguaggio semplice.

### Tool 2 — `success_rate_analysis`

Tasso di successo (chiusure riuscite / (riuscite + fallite) — le chiusure "nessun
carico" non contano, non sono vera produzione), raggruppabile per testa, giorno, ora
o file sorgente. Segnala automaticamente i gruppi il cui tasso di successo è
significativamente sotto la media (più di 2 deviazioni standard).

### Tool 3 — `torque_statistics`

Statistiche sulla coppia applicata (media, mediana, deviazione standard, quartili,
outlier) con un filtro importante: di default guarda solo le chiusure **riuscite**,
perché la coppia è quasi 0 durante l'inattività e vicina a 2 Nm durante una chiusura
vera — mischiarle produrrebbe una media senza senso. Se qualcuno chiede
esplicitamente le statistiche su "tutti" gli eventi, lo strumento **avvisa** che il
risultato può essere fuorviante, invece di darlo senza commento.

### Tool 4 — `torque_trend_analysis`

Cerca derive nella coppia nel tempo, per testa: media mobile, deviazione standard
mobile, e una regressione lineare per capire se la coppia sta salendo, scendendo, o
è stabile.

**Un avviso trovato per davvero**: sui dati reali, tutte e 36 le teste risultano
"statisticamente significative, in aumento" (probabilità di errore piccolissima,
fino a 1 su 10⁷⁷). Ma il quanto-spiega-davvero (r²) è solo ~0.0004 — il tempo spiega
lo 0.04% della variazione della coppia. Con quasi 900.000 punti dati per testa, è
facilissimo ottenere un risultato "statisticamente significativo" anche quando la
tendenza reale è minuscola e irrilevante. Lo strumento ora **aggiunge da solo** un
avviso al proprio riassunto quando questo succede, così chi legge solo il riassunto
(un agente AI, per esempio) non viene ingannato da un "trend significativo" che in
pratica non vuol dire quasi nulla.

### Tool 5 — `anomaly_detection`

Segnala chiusure anomale per coppia (tre metodi a scelta: deviazione standard, IQR,
o una soglia manuale) e ore con un tasso di fallimento anomalo. Verificato
incrociando due metodi diversi sugli stessi dati: entrambi trovano esattamente gli
stessi 20 eventi con coppia = 0.0 Nm su chiusure altrimenti "riuscite" — quasi
certamente lo stesso artefatto di lettura corrotta scoperto nella Fase 1 (Sezione 10
di `PHASE1_WALKTHROUGH.md`).

### Tool 6 — `head_comparison`

Una tabella con una riga per testa: tasso di successo, coppia media, variabilità,
numero di chiusure. Include un test statistico (Kruskal-Wallis) per capire se le
teste differiscono davvero tra loro nella coppia applicata — risposta: sì, ma la
differenza reale è piccola (le medie per testa vanno da 2.012 a 2.015 Nm, una
differenza dello 0.15%), un altro caso di "vero ma non importante" per via del
grande numero di dati.

### Tool 7 — `failure_analysis`

Analisi dei fallimenti: quali codici di errore dominano, giorni con un picco di
fallimenti, "raffiche" di fallimenti consecutivi sulla stessa testa (3 o più di
fila), e se certe teste tendono a fallire nello stesso momento.

### Tool 8 — `capping_speed_analysis`

**Il punto corretto dopo la review del collega** (vedi Sezione 10.3 di
`PHASE1_WALKTHROUGH.md`): riporta **due numeri diversi e ben etichettati**, non uno
solo:
- `machine_wide_throughput_pph`: il vero ritmo della macchina intera — somma di
  tutte le chiusure di tutte le teste, per ora (~26.610 pezzi/ora sui dati reali)
- `per_head_average_speed_pph`: la media della velocità di ogni singola testa
  (~1.521 pezzi/ora) — utile per confrontare le teste tra loro, **non** per sapere
  quanto produce la macchina

La prima versione di questo strumento riportava solo il secondo numero chiamandolo
genericamente "velocità di produzione" — un'etichetta che si presta facilmente a
essere letta come "quanto fa la macchina", quando invece è quasi 17.5 volte più
piccolo del vero numero.

**Verifica contro un dato esterno**: cercando online le specifiche tipiche di una
tappatrice AROL a 36 teste, il range indicativo è 50.000-72.000 pezzi/ora (più basso
per tappi a vite/ROPP, più alto per tappi piatti). Le **ore di picco** nei dati reali
arrivano a ~51.800-51.877 pezzi/ora — dentro quel range, sul lato basso (coerente con
tappi a vite). Questo conferma che il calcolo (somma delle chiusure per ora) è
corretto: quando la macchina lavora a pieno regime, il numero torna. La **media**
(26.610) è più bassa del picco non perché il calcolo sia sbagliato, ma perché non
tutte le ore sono a regime massimo — e non per teste ferme (in media 35.5 teste su 36
sono attive ogni ora), ma perché il ritmo di ogni testa varia da un'ora all'altra.

**Un'ora finta trovata proprio grazie a questo confronto**: la ora più "produttiva"
nei dati grezzi mostrava 236.795 pezzi/ora — quattro volte il picco reale, impossibile
per una macchina fisica. La causa: è l'ora in cui si chiude il grande buco di
campionamento del 2026-02-04 (6.85 ore senza righe, vedi Sezione 10.1 di
`PHASE1_WALKTHROUGH.md`). Le chiusure "aggregate" recuperate da quel buco (Sezione
10.1) sono conteggiate tutte in una singola riga con un timestamp solo — quando quella
riga viene sommata per ora, tutte le chiusure del buco finiscono nell'unica ora in cui
il dato riprende, invece di essere distribuite sulle ~7 ore reali in cui sono
davvero avvenute. Il **totale complessivo** resta corretto (quelle chiusure sono
avvenute per davvero), ma quella singola ora, presa da sola, è fuorviante.

**Come viene segnalato, non nascosto**: lo strumento non cancella queste ore (le
cancellerebbe silenziosamente e sottostimerebbe il totale) — le marca con
`gap_affected: true` nella serie oraria (`machine_wide_timeline`) e le elenca a
parte in `gap_affected_hours`, con la spiegazione del perché. Il riassunto testuale
(`summary`) avvisa automaticamente se ce ne sono, così anche solo leggendo quella
riga (per esempio un agente AI) non si rischia di prendere un'ora finta come "il
picco reale della macchina". Sull'intero archivio sono state trovate **9 ore**
così, la più grande delle quali è proprio quella del 2026-02-04.

### Tool 9 — `idle_analysis`

Analizza `idle_periods.parquet`: tasso di utilizzo (tempo produttivo / tempo totale),
quanto durano tipicamente i periodi di inattività, in quali ore del giorno la
macchina è più spesso ferma (utile per capire i turni di lavoro), e i 10 periodi di
inattività più lunghi.

### Tool 10 — `generate_kpi_dashboard`

Chiama tutti gli altri strumenti e compila un cruscotto con i numeri chiave in un
colpo solo — pensato per essere il primo output che un agente AI mostra quando gli
si chiede "come va la macchina?".

---

## 4. Risultati finali (numeri chiave, sull'intero archivio)

```
=== AROL KPI Dashboard ===
Tasso di successo: 100.00%
Coppia media (chiusure riuscite): 2.014 Nm
Stabilità coppia (dev. std. tra le medie per testa): 0.001 Nm
Ritmo macchina (aggregato): 26.610 pezzi/ora
  (media per singola testa: 1.521 pezzi/ora)
Tasso di utilizzo: 33.49%
Testa peggiore: H29 (99.99% di successo)
Testa migliore: H24 (100.00% di successo)
Anomalie rilevate (metodo statistico): 307.821
Tempo totale di inattività: 1.421 ore
```

Tempo di esecuzione sull'intero archivio (55.1 milioni di righe): circa 40-90
secondi per il cruscotto completo — abbastanza veloce da non richiedere di lavorare
su un campione ridotto, tranne per un singolo test statistico (Kruskal-Wallis nel
Tool 6) che viene limitato a 50.000 eventi per testa per restare veloce anche se
l'archivio dovesse crescere molto.

---

## 5. Come eseguire

```bash
PYTHONPATH=src python -m arol_analytics.analytics data/processed --output reports
```

Stampa il cruscotto a schermo e salva un report completo in
`reports/analytics_report.md` (leggibile da persona) e `reports/analytics_report.json`
(leggibile da programma) — con tutti e 10 gli strumenti, non solo il cruscotto.

Test rapido su un campione (senza dover aspettare l'archivio intero):

```bash
python tests/test_analytics.py
```

Nota: il test usa le prime 100.000 righe del file — dato che `closure_events.parquet`
è ordinato per testa (non per tempo), questo campione contiene solo la testa H01. È
comunque sufficiente per verificare che ogni strumento funzioni e restituisca la
struttura giusta, che è lo scopo del test.

---

## 6. Cosa manca ancora

- **Livello agente AI (Fase 3)**: un agente che usa questi 10 strumenti per
  rispondere a domande in linguaggio naturale ("quale testa sta peggio questo mese?")
  — non ancora iniziato.

# Fase 4 — Percorso completo: l'interfaccia bot (Layer 4)

Questo documento spiega, nello stesso spirito di `PHASE1_WALKTHROUGH.md` (ingestion),
`PHASE2_WALKTHROUGH.md` (analytics) e `PHASE3_WALKTHROUGH.md` (l'agente AI), cosa fa
l'interfaccia costruita sopra ai 14 strumenti del Layer 2 e all'`AROLAgent` del Layer 3
— e perché è costruita così, inclusi i problemi reali trovati testando con dati e LLM
veri, non solo la teoria.

---

## 1. Il problema e l'obiettivo

Il Layer 3 espone `AROLAgent`, ma solo via CLI (`python -m arol_analytics.agent`) —
niente bottoni, niente grafici, un solo modo di interagire (scrivere una domanda e
aspettare). **Obiettivo del Layer 4**: un'interfaccia con due modalità, scelte
liberamente dall'utente a ogni interazione, non in sequenza forzata:

- **Modalità guidata**: menu a categorie, ogni voce chiama direttamente un tool del
  Layer 2 — nessun LLM coinvolto, risposta sempre deterministica e riproducibile.
- **Modalità libera**: si scrive una domanda in linguaggio naturale, risponde
  `AROLAgent` (Layer 3) — LLM se disponibile, fallback a parole chiave altrimenti.

**Nota sulla scelta del canale**: la prima versione di questo layer era un vero bot
Telegram (`python-telegram-bot`, token da BotFather, connessione live all'API di
Telegram). È stata **rimossa su richiesta esplicita** — l'interesse era nel bot in sé
(menu, tool, LLM), non nel canale Telegram, che richiede un account e aggiunge
complessità di deploy senza aggiungere nulla alla logica. Quello che resta è un
**simulatore da terminale** (`terminal_sim.py`) che riusa esattamente la stessa
struttura a menu/callback e lo stesso backend — nessuna funzionalità persa, un solo
canale invece di due. Il dettaglio della rimozione è nella Sezione 6.

---

## 2. Mappa dei file: a cosa serve ciascuno

```
src/arol_analytics/bot/
├── __init__.py       →  nessuna dipendenza da account/rete esterna
├── __main__.py         →  python -m arol_analytics.bot [data_dir]
├── config.py             →  percorso dati, modello LLM, lista teste H01-H36
├── registry.py             →  dati statici: menu, azioni, testi di help/esempi
├── keyboards.py              →  struttura dei menu (etichetta, callback_data)
├── formatters.py                →  dict grezzo del Layer 2 -> testo leggibile
├── terminal_sim.py                 →  il loop interattivo vero e proprio
└── time_presets.py                   →  preset di intervallo temporale (7gg, 30gg, mesi, tutto)
```

Più due aggiunte al Layer 2, fatte apposta per il Layer 4 (Sezione 4 e 5):

```
src/arol_analytics/analytics/
├── events.py    →  Tool 11: list_events (elenco eventi grezzi filtrati)
├── charts.py    →  Tool 14: visualize (grafici PNG)
├── torque.py    →  + torque_outcome_comparison (Tool 12, successo vs fallito)
└── heads.py     →  + torque_success_correlation (Tool 13)
```

### `config.py`

Solo tre cose: `DATA_DIR` (default `data/processed`), `LLM_MODEL` (override opzionale,
altrimenti decide `llm.py` del Layer 3), `HEADS` (lista `H01`...`H36`, usata da
`keyboards.py` per il selettore testa). Non contiene più nulla legato a Telegram
(token, limite di 4096 caratteri) — rimosso in Sezione 6.

### `registry.py` — i dati, non il comportamento

Tre strutture statiche che `terminal_sim.py` legge:

- `MENUS: dict[str, (testo, funzione_tastiera)]` — una voce per ciascuna categoria
  (`main`, `success`, `torque`, `anomaly`, `cmp`, `failure`, `speed`, `idle`, `info`,
  `viz`, `help`).
- `RUN_ACTIONS: dict[str, RunAction]` — un'azione "canned" per bottone diretto (es.
  `"success:per_head"` → chiama `success_rate_analysis(group_by="per_head")` e formatta
  con `formatters.fmt_success_rate`). `RunAction` ha un campo `is_chart: bool` per
  distinguere le azioni che producono immagini da quelle che producono testo.
- `FLOW_ACTIONS: dict[str, RunAction]` — le stesse azioni ma per i flussi "custom" che
  chiedono prima la testa poi l'intervallo di tempo (Sezione 3).

`_build_examples_text()` genera il testo di `/examples` leggendo `TOOL_REGISTRY` del
Layer 3 (`agent/tools.py`) — le stesse ~45 domande di esempio usate per il prompt di
sistema dell'LLM, riusate qui per aiutare l'utente a scoprire cosa può chiedere senza
leggere il codice sorgente.

### `keyboards.py` — la struttura dei menu

Ogni funzione (`main_menu()`, `torque_menu()`, `head_picker()`, ecc.) costruisce un
`InlineKeyboardMarkup` — la classe dati di `python-telegram-bot`, riusata qui **solo
come contenitore comodo** per coppie (etichetta, callback_data), non per parlare con
l'API di Telegram (Sezione 6). Convenzione callback_data (breve per abitudine, non per
un vincolo reale ora che non c'è più Telegram):

| Prefisso | Significato |
|---|---|
| `m:<menu>` | apri un sottomenu |
| `r:<tool>:<preset>` | esegui un'azione diretta |
| `c:<flow>:head` | entra nel flusso custom, chiedi la testa |
| `h:<flow>:<TESTA\|all>` | testa scelta dentro un flusso custom |
| `t:<flow>:<preset>` | intervallo scelto dentro un flusso custom → esegue |
| `more` | mostra la tabella completa del risultato precedente |
| `ask` | passa alla modalità domanda libera |
| `noop` | bottone disabilitato |

### `formatters.py` — dal dict grezzo al testo

Una funzione `fmt_*` per ciascun tool, tutte con la stessa firma: prendono il dict
restituito dal Layer 2 e tornano `(testo_breve, tabella_completa_o_None)`. Il testo
breve è sempre sicuro da mostrare subito; la tabella completa (quando c'è, es. 36
teste) resta "nascosta" dietro il bottone "Mostra tabella completa" — così una domanda
su un solo numero non genera comunque un muro di testo.

Usa un piccolo sottoinsieme di tag simil-HTML (`<b>`, `<i>`, `<pre>`) che
`terminal_sim.py` converte in stile ANSI — non è HTML vero, è solo un modo condiviso
tra chi formatta e chi disegna a schermo.

### `terminal_sim.py` — il loop vero e proprio

La classe `TerminalSession` tiene lo stato di una conversazione (equivalente a
`bot_data`/`user_data`/`chat_data` di un vero bot Telegram, da cui il nome dei campi):
`buttons` (i bottoni numerati attualmente a schermo), `awaiting` (in attesa di un
input testuale speciale, es. la soglia di coppia per l'anomalia custom),
`pending_head_filter`/`cmp2_head1` (stato dei flussi multi-passo), `last_full_text`
(per il bottone "mostra tutto").

Il ciclo principale (`main()`): mostra il menu principale, poi ad ogni giro legge una
riga. Se è un numero e corrisponde a un bottone a schermo, esegue quell'azione. Se
inizia con `/`, è un comando. Altrimenti, è testo libero → modalità 2. **Non c'è una
scelta esplicita tra le due modalità**: a ogni prompt sono sempre entrambe disponibili,
un numero o una domanda, l'utente sceglie da solo interazione per interazione — non
serve "entrare" in modalità libera per usarla (il bottone "🤖 Free Question" nel menu
esiste solo come promemoria/scorciatoia, non è un cancello obbligato).

`run_action()` esegue un `RunAction`: chiama il tool vero via `ToolExecutor` (lo stesso
del Layer 3 — nessuna duplicazione, stessi dati caricati una sola volta all'avvio),
poi o formatta il testo (`action.formatter`) o, se `is_chart`, salva le immagini su
disco (`_save_chart()`, Sezione 5).

`handle_free_question()` chiama `agent.query()` — lo stesso `AROLAgent` del Layer 3,
istanza unica condivisa con la modalità guidata (stessi dati in memoria, nessun
ricaricamento).

---

## 3. I flussi "custom": testa e intervallo di tempo in due passi

Per i tool che accettano una testa e un intervallo (success rate, torque, failure),
il bottone "Custom" non chiede tutto in un colpo — troppi parametri in un solo prompt
sarebbero scomodi da testare/usare. Due passi:

1. `c:<flow>:head` → mostra la griglia H01...H36 (+ "All Heads").
2. `h:<flow>:<testa>` → salva la scelta in `pending_head_filter`, mostra i preset di
   tempo (calcolati da `time_presets.py` sul vero intervallo del dataset, non
   hardcoded: "Ultimi 7 giorni", "Ultimi 30 giorni", un bottone per ciascun mese
   presente nei dati, "Tutto il dataset").
3. `t:<flow>:<preset>` → esegue l'azione con testa + intervallo combinati.

Il confronto tra due teste specifiche (`c:cmp2:first` → `h:cmp2:<testa1>` →
`h:cmp2b:<testa2>`) è un caso simile ma a sé, perché servono due teste, non testa +
tempo.

---

## 4. Tre strumenti nuovi, aggiunti per colmare lacune reali

Testando le ~35 domande della specifica del progetto (vedi Sezione 7), sono emersi
buchi che nessuno dei 10 tool originali copriva:

- **`list_events`** (`analytics/events.py`) — elenco grezzo di eventi filtrati
  (esito, testa, intervallo di coppia, tempo), con conteggio totale sempre corretto
  anche quando l'elenco restituito è troncato (`total_matching` vs `events` capped a
  `limit`). Serve per domande tipo "mostrami tutti gli eventi falliti della testa 3",
  che nessuno strumento aggregato può rispondere per definizione.
- **`torque_outcome_comparison`** (`analytics/torque.py`) — coppia media di chiusure
  riuscite vs fallite messe a confronto diretto, con test di Mann-Whitney U. Prima,
  "confronta la coppia tra successo e fallimento" non aveva un tool dedicato.
- **`torque_success_correlation`** (`analytics/heads.py`) — correlazione di Pearson
  tra coppia media e tasso di successo, per testa. Risponde a "una coppia più alta
  significa un tasso di successo più alto?" — prima nessuno strumento lo calcolava.

Tutti e tre registrati in `agent/tools.py` (Layer 3) e in `executor.py`, quindi
raggiungibili sia dal menu guidato sia dall'LLM sia dal fallback a parole chiave.

---

## 5. I grafici (`analytics/charts.py`, Tool 14 `visualize`)

### Perché in Layer 2 e non in Layer 4

Anche se un grafico è "presentazione", `render_chart()` vive nel Layer 2 insieme agli
altri strumenti, non nel bot — per la stessa ragione per cui gli altri tool ci sono:
lavora direttamente su `events`/`idle_periods`, e mettendolo qui il Layer 3 (l'agente)
può chiamarlo come un tool qualunque, senza che il Layer 3 debba importare codice dal
Layer 4 (che invertirebbe la direzione di dipendenza tra i livelli).

### Sei tipi di grafico, non uno generico

`torque_over_time`, `torque_histogram`, `success_rate_per_head`, `failures_over_time`,
`production_over_time`, `utilization`, più `kpi_dashboard` che li raggruppa (Sezione
5.3). Colori presi **verbatim** dalla palette validata del progetto (blu/arancio/verde
per le serie, rosso/verde per gli stati critico/buono) — non re-inventati.

### 5.1 Il problema dell'istogramma piatto

Il primo istogramma della coppia (`torque_histogram`) mostrava un solo picco enorme:
la coppia reale è concentratissima (deviazione standard ~0.03-0.08 Nm) con rari valori
lontani, e un istogramma con range automatico su tutto il dominio (0-2.5 Nm) mette il
99.9% della massa in un unico bin — tecnicamente corretto, visivamente inutile.
**Corretto** restringendo l'asse a una banda percentile 0.5-99.5% — gli outlier restano
contati nelle statistiche testuali, solo fuori dal grafico.

### 5.2 Il problema del grafico "piatto per davvero"

`success_rate_per_head` (bar chart) aveva lo stesso problema in una forma più subdola:
i tassi di successo reali oscillano tra 99.98% e 100% — su un asse 0-100 la differenza
è invisibile, tutte le barre sembrano identiche, solo il colore (verde/rosso)
comunicava qualcosa. **Correggere troncando l'asse Y** (non partendo da zero) avrebbe
introdotto l'anti-pattern opposto — un grafico a barre il cui zero non è vero zero
esagera visivamente differenze minuscole. **Soluzione corretta**: cambiare cosa si
misura, non la scala — il grafico ora mostra lo **scostamento dalla media** (asse
centrato su zero = "in linea con la media"), non il valore assoluto. Zero resta un
punto di riferimento onesto, e lo scostamento reale (per quanto piccolo in valore
assoluto) occupa tutta l'altezza del grafico.

### 5.3 Il problema del "collage" 2x2

La prima versione di `kpi_dashboard` era un'unica immagine con 4 sotto-grafici
incastrati in una griglia 2x2 — più difficile da leggere, impossibile vedere un
pannello alla volta. **Corretto**: `kpi_dashboard` ora chiama semplicemente le altre
funzioni di rendering (`success_rate_per_head`, `torque_histogram`,
`production_over_time`, `utilization`) e restituisce **4 immagini separate a piena
risoluzione**, non una composita. Il contratto di `render_chart()` è quindi sempre
`images: list[bytes]` (mai un singolo PNG opzionale) — un tipo di grafico normale
restituisce una lista di un elemento, `kpi_dashboard` ne restituisce quattro.

### 5.4 Come si vedono, ora che non c'è più Telegram

`terminal_sim.py::_save_chart()` salva ogni immagine in `charts/` (esclusa da git) con
nome `<tipo>_<indice>_<timestamp>.png`, e su macOS lancia automaticamente `open` sui
file appena creati — si aprono da soli nel visualizzatore di default, senza dover
cercare manualmente il percorso.

---

## 6. La rimozione dell'integrazione Telegram reale

**Cosa è stato tolto**: `bot.py` (l'`Application` di `python-telegram-bot`, il
polling live, i ~20 handler `async` per comandi/bottoni collegati all'API reale di
Telegram), `docs/telegram_setup.md` (istruzioni BotFather), e da `config.py` tutto
ciò che serviva solo per quello (`TELEGRAM_BOT_TOKEN`, `SETUP_INSTRUCTIONS`,
`TELEGRAM_MESSAGE_LIMIT`). Il vecchio `handlers.py` (le funzioni `async` che
rispondevano agli eventi Telegram) è stato interamente rimosso — quello che restava
di utile (i dati statici: menu, azioni, testi) è diventato `registry.py`.

**Cosa resta, e perché è una scelta deliberata**: `keyboards.py` continua a costruire
oggetti `InlineKeyboardMarkup`/`InlineKeyboardButton` dalla libreria
`python-telegram-bot` — ma solo come struttura dati comoda (coppie etichetta/id),
zero chiamate di rete, zero account. Riscriverla con una classe custom sarebbe stato
puro lavoro di trascrizione senza guadagno funzionale, a rischio di introdurre bug in
codice già testato. La libreria resta quindi una dipendenza pip, ma il "Telegram" nel
nome del pacchetto non descrive più cosa fa il bot.

**Verificato dopo la rimozione**: ricompilato tutto, nessun riferimento morto a
`image_png`/`split_message`/`TELEGRAM_BOT_TOKEN` rimasto, e testata una sessione
completa end-to-end (`python -m arol_analytics.bot`) — menu guidato, domande libere,
LLM reale, tutti confermati funzionanti col nuovo entry point unico.

---

## 7. Un bug vero: l'LLM sicuro ma sbagliato per colpa di una tabella troncata

Domanda: *"What is the head that closes the most?"* Il router ha scelto
`head_comparison` **correttamente**, sia prima che dopo la correzione — il problema
non era l'instradamento.

`composer.py` tronca le liste lunghe a `MAX_TABLE_ROWS_FOR_LLM = 10` righe prima di
metterle nel prompt, per non sprecare contesto — la tabella di `head_comparison` ha 36
righe (una per testa), ordinate per `head_id`. Risultato: l'LLM vedeva solo H01-H10,
mai H33 (la testa col conteggio più alto in realtà). Ha risposto con sicurezza **"H01
ha il maggior numero di chiusure — 1.531.438"** — sbagliato, semplicemente perché H33
non gli arrivava mai in vista. Non un'allucinazione nel senso classico: un dato reale
letto da una tabella reale, solo una tabella incompleta senza che l'LLM potesse
saperlo.

**Corretto** calcolando `busiest_head`/`quietest_head` direttamente dentro
`head_comparison()` (Layer 2) e restituendoli come campi scalari dedicati — questi non
vengono troncati dal composer (solo le liste lo sono), quindi l'LLM li vede sempre,
indipendentemente da quante teste ci sono. Anche il `summary` testuale li include ora
esplicitamente, quindi la correzione vale anche in modalità fallback (senza LLM).

**Verificato prima/dopo con lo stesso LLM** (`gpt-oss:120b` via Ollama Cloud), stessa
domanda:

| | Prima | Dopo |
|---|---|---|
| Tool scelto | `head_comparison` ✅ | `head_comparison` ✅ |
| Risposta | "H01 — 1.531.438" ❌ | "H33 — 1.531.775" ✅ |

**Non è un problema isolato**: qualunque tool con una tabella oltre 10 righe rischia
lo stesso "risposta sicura ma vista solo a metà" su domande tipo "qual è il
massimo/minimo" — `head_comparison` è l'unico corretto finora; un audit degli altri
tool con tabelle lunghe (`torque_statistics` per-testa, `success_rate_analysis`
per-testa) resta da fare (Sezione 9).

---

## 8. Altri problemi reali trovati e corretti

- **"Count successful closures after removing duplicates" → "non ho un tool per
  questo"**: `dataset_summary` ometteva silenziosamente il campo duplicati quando il
  conteggio era zero (`if quality_report.get("duplicate_events_removed_total"):` —
  falso su zero). L'LLM non aveva nessun fatto concreto a cui appoggiarsi e a volte
  inventava un collegamento sbagliato (confondendo i "duplicati" con gli eventi
  "no-load", che sono un concetto completamente diverso — vedi la spiegazione della
  deduplicazione in Sezione 8.1). **Corretto**: `duplicates_removed_total` è ora
  sempre presente nel risultato, esplicitamente a zero se zero, con una frase dedicata
  nel `summary` e un avviso nella descrizione del tool contro quella confusione
  specifica.
- **Fallback a parole chiave incompleto**: mancavano le soglie di coppia ("torque
  above X Nm" → nessuna tool matchava, cadeva sul tool generico sbagliato), i filtri
  per testa specifica nelle domande di tipo "show all events for head 3", e frasi
  come "closes the most"/"most closures"/"busiest". Aggiunte le voci mancanti a
  `fallback.KEYWORD_MAP` — l'ordine resta cruciale (voci più specifiche prima).

### 8.1 Approfondimento: cosa conta davvero come duplicato

Durante la verifica di questi bug è emerso un chiarimento importante sulla
deduplicazione stessa (Layer 1, `ingestion/normalize.py::dedupe_events`), utile
documentarlo qui perché ha guidato direttamente la correzione della Sezione 8:

```python
dup_mask = events.duplicated(subset=["head_id", "segment_id", "counter"], keep="first")
```

Due righe sono duplicate solo se coincidono su **head_id + segment_id + counter** —
non su timestamp, non su torque, non su status. `segment_id` è un contatore
per-testa che sale di 1 a ogni reset fisico del contatore grezzo (rilevato sulla
sequenza raw, non ricostruito dagli eventi già estratti). **Verificato sui dati
reali**: nell'intero archivio di 89 giorni ci sono solo 3 momenti di reset, e in tutti
e 3 i casi **tutte e 36 le teste** resettano nello stesso identico timestamp — un
evento macchina sincronizzato, non indipendente per testa, anche se il codice lo
calcola per-testa per robustezza (non per assunzione). Sullo stesso dataset,
**zero duplicati** sono stati effettivamente trovati e rimossi
(`duplicate_events_removed_total: 0`) — verificato anche a livello di CSV grezzo
(nessun timestamp ripetuto dentro nessuno degli 89 file, nessuna sovrapposizione ai
bordi tra un file e il successivo).

---

## 9. Risultati finali (verificato, non solo dichiarato)

Le 35 domande della specifica del progetto (le stesse 9 categorie di
`bot_proposal.md`), fatte girare due volte contro l'agente reale:

**Solo fallback a parole chiave** (nessun LLM in ambiente sandbox): dopo
l'aggiunta dei 3 nuovi tool e delle keyword mancanti, tutte le categorie
"Filtering and conditional" e "Torque-related" precedentemente rotte ora instradano
al tool giusto — il limite restante è strutturale, non un bug: il fallback a parole
chiave sceglie solo il *tool*, mai i *parametri* (niente raggruppamento per testa,
niente soglie numeriche estratte dal testo).

**Con LLM vero** (`gpt-oss:120b` via Ollama Cloud), sulle 35 domande della specifica in
un unico passaggio: **34/35** corrette al primo giro (l'unica eccezione, "count
successful closures after removing duplicates", risolta subito dopo — Sezione 8 —
e riverificata singolarmente, non in un secondo giro completo delle 35). Il bug della
Sezione 7 (`head_comparison` sicuro ma sbagliato) è emerso **fuori da questo lotto**,
durante un uso reale del bot con una domanda simile ma diversa ("what is the head that
closes the most?", non tra le 35 originali) — corretto e riverificato prima/dopo sulla
stessa domanda, non rieseguendo l'intero lotto.

Il percorso multi-tool (una domanda che ne incatena più di uno, es. "why is the success
rate lower on certain days" → `success_rate_analysis` + `failure_analysis` in
sequenza, report strutturato) **funziona**, verificato con una domanda reale — era un
punto esplicitamente non verificato in `PHASE3_WALKTHROUGH.md` Sezione 11.

Tutti i tipi di grafico (i 4 originali, più i 2 nati dallo smontaggio del collage
2x2 di `kpi_dashboard`, Sezione 5.3) verificati visivamente sui dati reali, non solo controllati per assenza di
eccezioni.

---

## 10. Come eseguire

```bash
source .venv/bin/activate

# Menu guidato + domande libere (LLM se configurato, altrimenti fallback automatico)
PYTHONPATH=src python -m arol_analytics.bot data/processed

# Con Ollama Cloud invece che locale
export OLLAMA_API_KEY="<la-tua-chiave-da-ollama.com/settings/keys>"
export AROL_LLM_MODEL="<un-modello-dalla-lista-cloud-su-ollama.com/models>"
PYTHONPATH=src python -m arol_analytics.bot data/processed
```

Nessun account esterno richiesto per la modalità guidata o per il fallback a parole
chiave — solo `OLLAMA_API_KEY` è opzionale, e solo per sbloccare le risposte in
linguaggio naturale del Layer 3.

---

## 11. Cosa manca ancora

- **`requirements.txt` e `README.md` non ancora pronti per la consegna** — discusso
  ma non ancora fatto, interrotto per lavorare sui bug di questa fase.
- **Audit degli altri tool con tabelle lunghe** per lo stesso bug della Sezione 7
  (`torque_statistics` per-testa, `success_rate_analysis` per-testa) — solo
  `head_comparison` è stato corretto finora.
- **Nessuna interfaccia web** — valutata su richiesta esplicita e scartata per ora
  (lavoro aggiuntivo non essenziale, il terminale copre già lo stesso backend); da
  riconsiderare solo se serve un canale di demo più "presentabile" per la tesi.
- **Nessun test automatico formale (pytest)** per il Layer 4 — solo verifiche manuali
  documentate in questo file e negli script `tests/test_agent.py`/`test_analytics.py`
  per i layer sottostanti.
- **`knowledge.py` (Layer 3) ha una modifica non ancora committata** da un altro
  collaboratore (rinomina `accepted_closure_count` → `inferred_closure_count`, nuovo
  conteggio reset 36 → 108) — verificata coerente con il codice attuale durante questa
  fase, ma da allineare con chi ci sta lavorando prima della consegna.

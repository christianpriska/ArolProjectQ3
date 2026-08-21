# Fase 1 — Percorso completo: esplorazione, pulizia e normalizzazione dei dati

Questo documento spiega, passo per passo, tutto quello che è stato fatto per
trasformare i dati grezzi della macchina tappatrice AROL in un dataset pulito e
pronto per l'analisi — e per ogni file del codice, spiega **a cosa serve**, così puoi
orientarti anche senza rileggere tutto il codice.

---

## 1. Il problema e l'obiettivo

**Dati grezzi**: 89 file CSV (uno al giorno, da inizio febbraio a fine aprile 2026),
circa 4.6 GB totali, in `src/data/`. La macchina ha 36 "teste" (head) di chiusura.
Ogni secondo, per ogni testa, il file registra 3 numeri:

- **Count**: un contatore cumulativo — sale di 1 ogni volta che quella testa chiude
  un tappo
- **AppTorque**: la coppia (torque) applicata durante la chiusura
- **Status**: un codice numerico che dice se la chiusura è andata bene o male

Il problema è che questi dati grezzi **non dicono direttamente** "qui è avvenuta una
chiusura" — dicono solo il valore del contatore riga per riga, che resta identico
per molte righe di fila (la macchina non chiude un tappo ogni secondo) e poi scatta
di colpo quando avviene una chiusura reale.

**Obiettivo**: una tabella pulita con **una riga per ogni chiusura reale** (non una
riga al secondo), più un report che descrive la qualità dei dati grezzi.

---

## 2. Preparazione dell'ambiente

Il `python3` di sistema e il `pip3` di sistema puntavano a due installazioni Python
diverse e incompatibili — mancava `pandas` in uno, `pyarrow` in entrambi. Per evitare
problemi, è stato creato un ambiente virtuale dedicato al progetto:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pandas pyarrow numpy
```

Questa cartella `.venv/` è stata aggiunta a `.gitignore` insieme a `data/processed/`
(gli output generati, troppo pesanti per essere versionati su git).

---

## 3. Cosa abbiamo scoperto esplorando i dati (prima di scrivere codice)

Prima di scrivere qualsiasi riga di codice della pipeline, abbiamo aperto e
analizzato i file veri, perché le specifiche del progetto e la realtà dei dati
spesso non coincidono esattamente. Ecco cosa è emerso:

| La specifica diceva | La realtà dei dati |
|---|---|
| Fino a 48 teste (H01–H48) | Esattamente **36 teste** in ogni file |
| Colonne "a terzetti": `H01 Count, H01 AppTorque, H01 Status, H02 Count, ...` | Colonne **raggruppate per tipo**: prima tutti i 36 `Count`, poi tutti i 36 `AppTorque`, poi tutti i 36 `Status` |
| Timestamp ISO 8601 in UTC (con `Z` finale) | Timestamp **senza `Z`** e **non in UTC stabile** — vedi sotto |
| Codici di stato documentati: {0,2,3,4,5,8,9,16,17,32,33,64,65} | Nella realtà compaiono **solo** {0, 2, 4, 9, 65} |

**Il dettaglio più interessante**: ogni file "giornaliero" in realtà inizia alle
16:00 (o 17:00) del giorno precedente e finisce alle 15:59:59/16:59:59 del giorno
nominale. Lo scarto di un'ora cambia esattamente tra i file del 2026-03-08 e
2026-03-09 — la seconda domenica di marzo, cioè **l'inizio dell'ora legale
americana**. Questo significa che i timestamp sono in ora locale USA, non UTC come
si potrebbe pensare guardando il formato.

Altri dettagli trovati:
- Alcuni file hanno righe "azzerate" (Count/AppTorque/Status = 0) — un artefatto di
  esportazione, non letture vere (il contatore non può azzerarsi da solo). Alcune
  sono una **coda finale continua** (rimossa); altre sono blocchi isolati in mezzo al
  file — la Sezione 10 spiega come li trattiamo oggi (è cambiato rispetto alla prima
  versione di questo documento).
- I contatori "tornano indietro" (reset) — non è un caso raro. A volte è un vero
  fermo macchina (es. 8+ ore, o le 22.6 ore del 2026-03-10→11), a volte è un
  "flicker" del sensore che dura pochi secondi, a volte (scoperto più tardi, vedi
  Sezione 10) è il contatore che smette di essere riportato correttamente per
  minuti mentre la macchina continua a produrre davvero.

> **Nota**: questa sezione descrive la prima esplorazione dei dati. La Sezione 10
> racconta cosa abbiamo scoperto dopo, correggendo dei problemi trovati da un
> collega — cambia in modo sostanziale come trattiamo le righe azzerate e i reset.

---

## 4. Il percorso, passo per passo (walkthrough)

Questo è quello che succede quando lanci la pipeline (`ingest_dataset`), in ordine:

1. **Trovare tutti i file CSV** nella cartella indicata (`src/data/`), ordinati per
   nome (che corrisponde all'ordine cronologico).

2. **Per ogni file, in ordine cronologico**:
   - **Leggerlo e validarne lo schema** — controlla che ci sia la colonna
     `timestamp` e i terzetti `H{nn} Count/AppTorque/Status`. Se un file è
     malformato, viene scartato con un messaggio d'errore e la pipeline **continua**
     con gli altri file (non si blocca).
   - **Rimuovere la coda di righe azzerate**, se presente (solo se è davvero una
     coda finale, come spiegato al punto 3).
   - **Calcolare le metriche di qualità** di quel file (righe, valori mancanti,
     buchi temporali, valori di coppia sospetti, distribuzione dei codici di stato,
     reset del contatore).
   - **Rilevare le chiusure**: per ogni testa, si scorre la colonna `Count` riga per
     riga. Quando il valore **sale** rispetto alla riga prima, quella riga è una
     chiusura. Se **scende**, non è una chiusura ma un reset — viene ignorato, non
     conteggiato come chiusura falsa.
   - **Rilevare i periodi di inattività**: tratti in cui tutte e 36 le teste hanno
     Status=2 (nessun carico) per almeno 30 righe o 30 secondi consecutivi.

3. **Unire i risultati di tutti i file** in un'unica tabella di chiusure.

4. **Arricchire la tabella**: aggiungere l'etichetta leggibile dello stato (es.
   "Closure OK"), se è un successo o un fallimento, e due valori calcolati: quanto
   tempo è passato dall'ultima chiusura della stessa testa, e la velocità di
   chiusura (pezzi/ora).

5. **Rimuovere i doppioni veri** (vedi Sezione 5, "chiusure doppie da flicker").

6. **Salvare tutto su disco** in `data/processed/`: le due tabelle pulite
   (`.parquet`), il report di qualità (`.json`) e il riassunto leggibile (`.md`).

---

## 5. Mappa dei file: a cosa serve ciascuno

```
src/arol_analytics/ingestion/
├── __init__.py       →  espone ingest_dataset() come punto d'ingresso del pacchetto
├── __main__.py        →  permette di lanciare tutto da riga di comando
├── schema.py          →  le "regole del gioco": tabella codici di stato, soglie, nomi colonne
├── loader.py           →  trova i file e controlla che abbiano il formato giusto
├── quality.py           →  calcola le statistiche di qualità + rimuove le righe azzerate finali
├── closures.py           →  il cuore: riconosce quando avviene una chiusura
├── idle.py                →  riconosce i periodi in cui la macchina è ferma
├── normalize.py            →  etichetta le chiusure, rimuove i doppioni, calcola le metriche derivate
├── report.py                →  scrive il riassunto leggibile (Markdown) per l'utente
└── pipeline.py                →  il "direttore d'orchestra": mette insieme tutti i pezzi sopra
```

Ora, il dettaglio di ciascuno — comprese le parti "extra" che risolvono problemi
concreti trovati nei dati reali.

### `schema.py` — le regole del gioco

Contiene tutte le costanti usate ovunque: la tabella dei 13 codici di stato (quali
sono "reject", quale nome leggibile dare a ciascuno), le soglie per l'inattività (30
righe / 30 secondi, prese testuali dalla specifica), la soglia per i buchi temporali
(2× l'intervallo mediano, anche questa dalla specifica), e la tolleranza per
considerare due file "contigui" nel tempo (5 secondi, questa l'abbiamo scelta noi —
vedi Sezione 6).

**Perché un file a parte**: così ogni altro file del codice legge le stesse regole
da un unico posto, invece di ripetere gli stessi numeri/nomi in più punti (rischio di
incoerenza se in futuro si cambia una soglia).

### `loader.py` — trovare e validare i file

Due compiti: elencare tutti i CSV nella cartella data, e controllare che ogni file
abbia davvero le colonne attese prima di provare a elaborarlo. Se manca la colonna
`timestamp`, o non c'è nessun terzetto Count/AppTorque/Status completo, il file
viene rifiutato con un errore chiaro — **senza far crollare tutta la pipeline**.
Questo è stato testato apposta con un file CSV rotto (colonne a caso) per verificare
che venisse scartato correttamente e gli altri 88 file continuassero a essere
elaborati.

### `quality.py` — le statistiche + la pulizia delle letture corrotte

Funzioni principali (la seconda è cambiata molto dalla prima versione, vedi Sezione 10):

- `strip_trailing_padding()`: rimuove la coda di righe azzerate **solo se** sono
  proprio alla fine del file (vedi Sezione 3).
- `mask_corrupted_count_readings()`: per ogni testa, individua i blocchi dove
  `Count` legge 0 in mezzo al file e decide se è un **reset vero** (da lasciare) o
  una **lettura corrotta** (da annullare, sostituendo con un valore "mancante" che
  `closures.py` sa ignorare). Spiegata in dettaglio nella Sezione 10 — è il pezzo di
  codice riscritto tre volte prima di trovare la versione giusta.
- `compute_file_quality()`: per ogni file calcola tutto quello che serve per il
  report — intervallo di tempo coperto, buchi nel campionamento, percentuale di
  valori mancanti, coppie negative o sospette, distribuzione dei codici di stato,
  quante volte il contatore è tornato indietro.

### `closures.py` — il cuore della pipeline: riconoscere le chiusure

La regola base è semplice: **una chiusura è una riga dove `Count` è più alto della
riga precedente** (quella valida, ignorando le letture corrotte annullate da
`quality.py`) **, per quella testa**. Se il valore scende, non è una chiusura, è un
reset — e viene automaticamente escluso, senza bisogno di un controllo apposito.

Da quando `Count` può salire di più di 1 in un colpo solo (Sezione 10), ogni
chiusura registra anche: `counter_delta` (di quanto è salito), `accepted_closure_count`
(quante chiusure contare — oggi sempre uguale a `counter_delta`) e `data_quality`
("single" = normale, "aggregated" = salto >1 in un intervallo normale, "gap" = il
salto attraversa un buco di campionamento rilevato).

**La parte extra utile**: cosa succede al **primo rigo di un nuovo file**? Non c'è
una "riga precedente" dentro allo stesso file per confrontarlo. Se non si facesse
nulla, una chiusura vera che capita esattamente sulla prima riga di un giorno
andrebbe persa, una volta per ogni cambio di file. Per risolverlo, la pipeline porta
avanti da un file all'altro l'ultimo valore del contatore di ogni testa, l'ultimo
timestamp, e il "segmento" corrente di ogni testa (`CarryState`), così anche la
prima riga di ogni nuovo file viene confrontata correttamente. **Verificato
concretamente**: elaborando due giorni consecutivi sia con questo metodo, sia
unendo davvero tutti i dati grezzi in un'unica tabella e facendo il confronto una
sola volta su tutto, il numero di chiusure trovate è risultato **identico**
(612.010 in entrambi i casi) — quindi tenere i file separati non fa perdere nessuna
informazione, e usa molta meno memoria.

Da oggi `closures.py` calcola anche il "segmento" di reset (quante volte il
contatore di quella testa è tornato indietro, guardando i dati **grezzi** riga per
riga) — non più ricostruito dopo, dagli eventi già estratti, come nella prima
versione. Il motivo è nella Sezione 10.

### `idle.py` — trovare i periodi di inattività

Un rigo conta come "inattivo" solo se **tutte e 36 le teste insieme** hanno
Status=2. I tratti di inattività vengono raggruppati e tenuti solo se durano almeno
30 righe o 30 secondi (soglia dalla specifica).

**La parte extra utile**: un periodo di inattività può capitare esattamente a
cavallo di mezzanotte, cioè tra un file e il successivo (es. la macchina si ferma
alle 23:50 di un giorno e riparte alle 08:00 del giorno dopo). Se si guardasse ogni
file da solo, questo periodo verrebbe spezzato in due pezzi invece di essere
riconosciuto come uno unico. La pipeline porta avanti lo stato del periodo di
inattività "in corso" da un file all'altro e li unisce se sono temporalmente
contigui. **Verificato sui dati veri**: un periodo di inattività che andava dal
2026-02-04 alle 16:11 al 2026-02-05 alle 08:35 (16.4 ore) è stato correttamente
riconosciuto come **un unico periodo**, non due.

### `normalize.py` — etichette, doppioni e metriche derivate

Tre cose, in ordine:

1. **Etichette leggibili**: ogni chiusura riceve un nome di stato leggibile
   (`status_label`), se è un successo (`is_successful`), se è un fallimento
   (`is_reject`), e una categoria più ampia (`classification`).

2. **La parte extra più delicata: rimuovere le chiusure doppie senza sbagliare.**
   La specifica chiede di rimuovere i doppioni (stessa testa, stesso valore del
   contatore). Il problema: dopo un reset, il contatore riparte da 0 e **ripassa
   legittimamente** per valori già usati prima del reset — quelle non sono chiusure
   doppie, sono chiusure vere che coincidono per caso con un numero già visto. Se si
   rimuovessero alla cieca tutte le coppie (testa, valore) ripetute in tutto
   l'archivio, si perderebbero chiusure vere. La soluzione: il controllo dei
   doppioni è limitato a un singolo "segmento" — lo spazio tra un reset e il
   successivo, per quella testa (oggi il segmento arriva già calcolato da
   `closures.py`, guardando i dati grezzi — non più ricostruito qui dagli eventi,
   vedi Sezione 10). Solo se lo stesso valore compare due volte **all'interno dello
   stesso segmento** viene considerato un vero doppione e rimosso. **Aggiornamento**:
   da quando `quality.py` pulisce le letture corrotte *prima* che diventino eventi
   (Sezione 10), i doppioni che questa funzione trovava (551, tutti causati da
   quelle stesse letture corrotte) non si formano più — oggi questa funzione trova
   correttamente **zero** doppioni, il che conferma che il problema è stato risolto
   alla radice invece che ripulito dopo.

3. **Metriche derivate**: tempo dall'ultima chiusura della stessa testa e velocità
   di chiusura (pezzi/ora), calcolate dopo aver unito tutti i file, quindi corrette
   automaticamente anche a cavallo tra un giorno e l'altro. Da oggi la velocità
   tiene conto di `accepted_closure_count` (Sezione 10): se una riga rappresenta 4
   chiusure aggregate, la velocità calcolata è "4 chiusure in quell'intervallo", non
   "1 chiusura lentissima".

### `report.py` — il riassunto leggibile

Prende tutti i numeri calcolati e li trasforma nel file `ingestion_summary.md`:
quanti file processati, quante chiusure per testa, percentuali di successo/
fallimento/inattività, avvisi sulla qualità dei dati, riepilogo dei periodi di
inattività.

### `pipeline.py` — il direttore d'orchestra

Mette in fila tutti i pezzi sopra, file per file, portando avanti gli "stati" che
servono per la continuità (`carry_state` per i contatori, `pending_idle_run` per
l'inattività, `prev_last_ts` per i buchi tra file — vedi Sezione 6). Alla fine unisce
tutto, calcola il report aggregato e salva i file di output.

### `__main__.py` — il punto d'ingresso da terminale

Permette di lanciare tutto con un solo comando:

```bash
PYTHONPATH=src python -m arol_analytics.ingestion src/data --output-dir data/processed
```

---

## 6. Un'altra parte "extra": i buchi esattamente al confine tra due file

Durante una verifica (dopo la domanda "non converrebbe unire tutti i file in uno
solo?"), è emerso un problema reale, distinto da quello dei contatori: il controllo
dei "buchi" nel campionamento (righe mancanti) guardava solo **dentro** ogni singolo
file. Un buco che cade esattamente al confine tra un file e il successivo — l'ultima
riga del giorno N e la prima riga del giorno N+1 — non veniva visto da **nessuno dei
due** controlli.

La soluzione, senza bisogno di unire tutti i file in memoria: portare avanti anche
l'ultimo timestamp visto da un file al successivo (stesso principio del
`carry_state` per i contatori) e controllare il buco al confine.

Questo controllo ha trovato **2 buchi veri**, esattamente sui 2 file che avevano
righe azzerate finali (Sezione 3):

| Confine | Buco |
|---|---|
| 2026-03-10 08:53:20 → 2026-03-10 17:00:00 (inizio file 03-11) | 8.11 ore |
| 2026-04-08 16:09:25 → 2026-04-08 17:00:00 (inizio file 04-09) | 50.6 minuti |

Ha senso: le righe azzerate erano dati finti di "riempimento"; una volta tolte
correttamente, il vero buco tra l'ultima lettura reale e la prossima diventa
visibile. Il primo di questi due buchi coincide con un fermo macchina reale già
trovato in altri controlli — buona conferma che il controllo funziona.

**Conclusione sulla domanda "conviene unire tutti i file in uno solo?"**: No. È
stato verificato concretamente che tenere i file separati (con lo stato portato
avanti da un file all'altro) dà **esattamente gli stessi risultati** di un'unione
totale, sia per le chiusure che per l'inattività — ma usando molta meno memoria (i
file grezzi uniti supererebbero i 10 GB in memoria, mentre elaborandoli uno alla
volta bastano circa 600 MB). L'unica cosa che davvero mancava era il controllo dei
buchi al confine, ed è stato aggiunto senza bisogno di unire nulla.

---

## 10. Le correzioni dopo la review di un collega (2026-08-20)

Un collega ha scritto `REVIEW.md`, segnalando 4 problemi possibili nella pipeline.
Prima di correggere qualsiasi cosa, ogni punto è stato **verificato sui dati veri**
(non accettato o respinto a naso) — e due dei problemi più semplici, una volta
corretti, hanno portato a scoprire un problema più grande e più interessante.

### 10.1 Il contatore può salire di più di 1 alla volta

`closures.py` guardava solo "il contatore è salito?" — se salta da 100 a 104 in una
riga, veniva contata **una sola chiusura**, non quattro. Misurato sui dati veri:
succede nello 0.74% delle transizioni, per un totale di **824.421 chiusure perse**
(l'1.5% del totale). Quasi sempre (il 99.8% dei casi) succede perché ci sono righe
mancanti nel mezzo (un buco di campionamento) — non perché la macchina chiude
davvero 4 tappi nello stesso secondo.

**Correzione**: ogni chiusura ora salva anche `counter_delta` (di quanto è salito il
contatore) e `accepted_closure_count` (quante chiusure contare — oggi sempre uguale
a `counter_delta`), etichettata `data_quality`:
- **"single"**: una chiusura, intervallo di campionamento normale (~1s)
- **"aggregated"**: il contatore è salito di più di 1 in un intervallo normale
- **"gap"**: il salto attraversa un buco di campionamento rilevato — sappiamo
  *quante* chiusure sono avvenute, ma non *quando* esattamente, o con che coppia

Non vengono inventate 4 righe con lo stesso torque/status ripetuto — c'è una sola
lettura vera per tutto il salto, quindi si registra una riga sola con l'informazione
onesta ("è successo qualcosa di grande qui, ecco quanto").

### 10.2 Un problema più grande, scoperto correggendo il primo

Per implementare il punto sopra, un blip corrotto conosciuto (Count/Torque/Status
che leggono 0 per 1-3 righe per poi tornare al valore corretto — già visto altrove
in questo documento) doveva essere "pulito" prima di contare le chiusure, altrimenti
un salto da 0 al valore vero verrebbe letto come un numero enorme di chiusure false.

Il primo tentativo di pulizia (basato sulla durata del blip: corto = corrotto, lungo
= reset vero) ha creato un **bug nuovo**: un salto di **476.513** in una riga sola
per la testa H29 — implicherebbe quasi 3 milioni di pezzi/ora, fisicamente assurdo.
Controllando i dati grezzi: per 557 righe, `Count` leggeva 0 ma `AppTorque`
continuava a mostrare valori veri e variabili (~2.0 Nm) — prova che la testa non
aveva mai smesso di produrre, solo il contatore aveva smesso di essere riportato
correttamente. Il primo tentativo guardava solo "tutte e 36 le teste insieme" e
"quanto dura il blip" — non bastava: **una singola testa** può avere questo problema
da sola.

Il secondo tentativo (basato sul torque: se il torque è reale durante `Count==0`, è
corrotto) ha corretto il caso H29, ma ha creato un **terzo bug**: dentro quello
stesso blocco di 557 righe, il torque toccava esattamente 0 per una singola riga
(rumore di misura normale) — quella riga non veniva ripulita, e quel singolo zero
rimasto si propagava in avanti, riproducendo lo stesso identico problema.

**La soluzione che ha davvero funzionato**: per ogni testa, per ogni blocco di righe
dove `Count` legge 0, confrontare il valore **subito prima** del blocco con il
valore **subito dopo**:
- se il valore dopo è vicino o superiore a quello di prima → la produzione non si è
  mai fermata, è solo il contatore che ha smesso di essere riportato → è una lettura
  corrotta, da ripulire (si annulla solo `Count`, non `AppTorque`/`Status` che
  restano dati veri)
- se il valore dopo è molto più basso di quello di prima (vicino a 0) → è un vero
  reset, la macchina è davvero ripartita da zero → si lascia intatto

Verificato su **tutti i 2.088 blocchi** di zeri trovati nell'intero archivio: la
separazione tra le due categorie è netta, **zero casi ambigui**. I blocchi corrotti
arrivano al massimo a 665 righe; i reset veri iniziano da 1.341 righe in su (il vero
fermo macchina del 2026-03-10→11 dura 78.680+ righe). Non serve nessuna soglia sulla
durata — bastava guardare la cosa giusta fin dall'inizio.

Effetto collaterale positivo: dato che ora le letture corrotte vengono pulite
*prima* di diventare eventi, i 551 "doppioni da flicker" della Sezione 5 non si
formano più — sono scesi a **zero**.

### 10.3 Velocità per singola testa scambiata per velocità della macchina

Il Layer 2 (analisi, vedi il documento della Fase 2) calcolava una "velocità di
produzione" che in realtà era la media della velocità *di ogni singola testa*, non
il ritmo reale di tutta la macchina. Misurato: la media per-testa è ~1.521 pezzi/ora,
il vero ritmo aggregato (somma di tutte le teste, per ora) è **~26.610 pezzi/ora —
circa 17.5 volte più alto**. Ora sono riportati entrambi, con nomi chiari, per non
confonderli mai più.

---

## 7. Risultati finali (numeri chiave, aggiornati dopo la Sezione 10)

```
89/89 file elaborati correttamente, 0 errori di formato
55.130.461 righe di chiusura, che rappresentano 55.954.882 chiusure vere
  (la differenza, 824.421, sono le chiusure "aggregate" recuperate — Sezione 10.1)
3.486 periodi di inattività, circa 1.421 ore totali (~66.5% dell'archivio)
36 reset veri del contatore; 0 chiusure doppie rimaste da rimuovere
96.518 letture di Count corrotte, ripulite prima di contare le chiusure (Sezione 10.2)
0 valori di coppia negativi; 0 codici di stato fuori dalla tabella documentata
2 buchi trovati esattamente al confine tra due file (vedi Sezione 6)
Tempo di esecuzione: circa 1 minuto per l'intero archivio
```

Ripartizione degli esiti su tutte le 55.1 milioni di chiusure:

| Esito | Conteggio | % |
|---|---|---|
| successo (status 0) | 31.670.096 | 57.45% |
| nessun carico (status 2) | 23.459.257 | 42.55% |
| fallimento (codici reject) | 1.096 | 0.002% |
| altro (status 4) | 12 | 0.00002% |

**Un avviso da tenere a mente**: il controllo "coppia >3σ dalla media" segnala circa
il 2.4% delle chiusure come "anomale". Non significa che il 2.4% dei dati sia
sbagliato — la coppia è quasi 0 durante l'inattività e diventa alta solo durante una
chiusura vera, quindi la distribuzione non è "a campana" e un test 3σ standard è
poco affidabile su questo tipo di dati. È stato calcolato perché la specifica lo
chiedeva, ma va letto con cautela.

---

## 8. File prodotti

Tutti in `data/processed/` (esclusi da git tramite `.gitignore`):

| File | Contenuto |
|---|---|
| `closure_events.parquet` | 55.1 milioni di righe, la tabella pulita delle chiusure (include `counter_delta`, `accepted_closure_count`, `data_quality` — Sezione 10.1) |
| `idle_periods.parquet` | 3.486 righe: inizio, fine, durata di ogni periodo di inattività |
| `data_quality_report.json` | versione leggibile da programma di tutte le metriche |
| `ingestion_summary.md` | versione leggibile da persona delle stesse metriche |

---

## 9. Cosa manca ancora (prossimi passi)

Questa fase copriva pulizia/normalizzazione dei dati. Aggiornamento:

- **Livello di analisi (Layer 2)**: ✅ fatto — vedi `docs/PHASE2_WALKTHROUGH.md` per
  la spiegazione passo-passo, nello stesso stile di questo documento.
- **Livello agente AI**: un agente che risponde a domande in linguaggio naturale
  usando l'analisi come strumenti — fase futura separata, secondo la proposta del
  corso. Non ancora iniziata.
- **Test automatici** (pytest): la pipeline di ingestion è stata verificata a mano
  su porzioni reali dei dati (Sezioni 5-6 e 10), non con una suite pytest formale.
  Il Layer 2 ha invece uno script di test in `tests/test_analytics.py`.

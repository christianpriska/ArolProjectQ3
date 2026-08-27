# Fase 3 — Percorso completo: l'agente AI (Layer 3)

Questo documento spiega, nello stesso spirito di `docs/PHASE1_WALKTHROUGH.md` (ingestion)
e `docs/PHASE2_WALKTHROUGH.md` (analytics), cosa fa il livello agentico costruito sopra
ai 10 strumenti della Fase 2 — e perché è costruito così.

---

## 1. Il problema e l'obiettivo

La Fase 2 ha prodotto 10 funzioni Python deterministiche che rispondono a domande
precise sui dati — ma solo se sai già **quale** funzione chiamare e **con che
parametri**. "Quale testa ha più fallimenti?" per un utente non tecnico non è
`failure_analysis(head_filter=None)` seguito da un confronto a mano tra le righe della
tabella restituita.

**Obiettivo**: un agente che riceve una domanda in linguaggio naturale, decide
autonomamente quale/i strumento/i chiamare, li esegue, e restituisce una risposta
leggibile — usando un LLM come "cervello" per l'instradamento e la composizione della
risposta, ma **mai** per calcolare i numeri: quelli restano sempre calcolo classico del
Layer 2, l'LLM li legge e li spiega, non li inventa.

Due vincoli fissati dalla specifica del corso, prima di scrivere codice:
- **Niente API a pagamento** (no OpenAI, no Anthropic API) — il modello gira tramite
  [Ollama](https://ollama.com), locale o cloud (vedi Sezione 4).
- **L'agente non deve mai bloccarsi** se il modello non è raggiungibile — deve
  rispondere comunque, in modo più semplice, non restare in silenzio. Questo ha
  guidato buona parte delle scelte di design (Sezione 3).

---

## 2. Mappa dei file: a cosa serve ciascuno

```
src/arol_analytics/agent/
├── __init__.py       →  espone AROLAgent come punto d'ingresso del pacchetto
├── __main__.py         →  CLI interattiva: python -m arol_analytics.agent data/processed
├── tools.py              →  il registro dei 10 strumenti + normalizzazione parametri enum
├── llm.py                  →  client HTTP per Ollama (locale o cloud)
├── router.py                 →  decide quale/i tool chiamare, dato il testo della domanda
├── fallback.py                 →  instradamento a parole chiave, usato se l'LLM non risponde bene
├── executor.py                   →  carica i dati una volta ed esegue davvero i tool
├── composer.py                     →  trasforma l'output grezzo dei tool in una risposta leggibile
├── knowledge.py                      →  fatti statici per domande "come funziona il sistema?"
└── agent.py                            →  l'orchestratore (AROLAgent) che mette insieme tutto
```

Il principio è lo stesso della Fase 2: ogni pezzo fa una cosa sola, così è testabile da
solo — infatti `router.py`, `fallback.py` e `composer.py` funzionano e sono testati
anche **senza** un LLM vero (vedi Sezione 8).

### `tools.py` — il registro degli strumenti

Una lista di dizionari, uno per ciascuno dei 10 strumenti del Layer 2: nome,
descrizione, parametri accettati (con i valori validi quando il parametro è un enum,
es. `group_by` di `success_rate_analysis` può essere solo uno tra `overall`,
`per_head`, `daily`, `hourly`, `per_file`), e alcuni esempi di domande che dovrebbero
attivarlo. `format_registry_for_prompt()` trasforma tutto questo in testo per il prompt
di sistema dell'LLM (Sezione 3); `get_tool()` recupera la definizione di un tool per
nome.

**La parte aggiunta dopo aver trovato un bug vero** (Sezione 5):
`normalize_enum_value()` — confronta un valore ricevuto dall'LLM con i valori enum
dichiarati qui e lo corregge se serve, invece di lasciarlo passare così com'è.

### `llm.py` — parlare con Ollama

Un client HTTP minimale (con `requests`) verso l'endpoint `/api/chat` di Ollama.
Funziona sia in locale (`http://localhost:11434`, nessuna autenticazione) sia con
Ollama Cloud (`https://ollama.com`, richiede una API key) — vedi Sezione 4 per come si
sceglie quale dei due usare. `is_ollama_available()` fa un controllo veloce (GET
`/api/tags`) prima di fidarsi che il server risponda; `chat()` manda i messaggi e
restituisce solo il testo della risposta, sollevando `OllamaUnavailableError` per
qualunque problema di rete o di risposta malformata — un'unica eccezione che il resto
del codice sa gestire in un punto solo.

### `router.py` — decidere quale strumento usare

Il pezzo più delicato. Riceve la domanda dell'utente e:

1. Costruisce un prompt di sistema che elenca tutti i 10 strumenti (da `tools.py`) più
   due voci speciali: `meta_knowledge` (per domande su come funziona il sistema, non
   sui dati) e `none` (se nessuno strumento può rispondere).
2. Chiede all'LLM di rispondere **solo** con un oggetto JSON:
   `{"reasoning": "...", "tool_calls": [{"tool": "...", "parameters": {...}}]}`.
3. **Estrae il JSON dalla risposta**, anche se l'LLM lo ha incapsulato in un blocco
   ```` ```json ... ``` ```` o ci ha aggiunto testo prima/dopo (capita spesso con
   modelli locali più piccoli, e anche occasionalmente con modelli cloud).
4. Se il parsing fallisce, **un solo retry** con un prompt più severo ("rispondi SOLO
   con il JSON, niente altro").
5. Se fallisce ancora, o se l'LLM non è raggiungibile, passa la mano a `fallback.py`.
6. Prima di restituire le `tool_calls`, **normalizza i parametri** contro gli enum
   dichiarati in `tools.py` (Sezione 5) — questo succede sempre, non solo quando
   qualcosa sembra andato storto.

### `fallback.py` — instradamento a parole chiave

Una lista ordinata di `(parole chiave, nome del tool)`. L'ordine conta: le voci più
specifiche vengono prima (es. "contributes most" → `failure_analysis` viene controllato
prima della voce generica "failure/failed" → stesso tool, ma anche prima di
"compare/comparison" → `head_comparison`, per evitare ambiguità tra domande simili).
Usato quando l'LLM non è disponibile, non risponde in tempo, o la sua risposta non si
riesce a interpretare come una chiamata valida — così l'agente risponde comunque,
anche nel caso peggiore.

### `executor.py` — eseguire davvero i tool

Carica `closure_events.parquet`, `idle_periods.parquet` e (se presente)
`data_quality_report.json` **una sola volta**, alla costruzione (`ToolExecutor`) — non
ad ogni domanda, altrimenti ogni interazione richiederebbe di rileggere 55 milioni di
righe da disco. Mappa ogni nome di tool alla vera funzione Python del Layer 2 (import
diretto da `arol_analytics.analytics`, nessuna duplicazione di logica), converte i
parametri nel formato che le funzioni si aspettano (es. `time_range` da lista JSON
`[start, end]` a tupla), ed esegue. **Nessuna eccezione di un tool arriva mai
all'utente come crash**: viene catturata e trasformata in un `ExecutionResult` con
`error` valorizzato, che il composer sa spiegare in linguaggio naturale.

### `composer.py` — trasformare i numeri in una risposta

Riceve l'output grezzo (uno o più `ExecutionResult`) e produce il testo finale:

- **Una domanda, un tool**: usa esclusivamente dati e formule prodotti dal codice.
  La percentuale di successo ha un formatter dedicato; gli altri strumenti usano
  il proprio `summary` deterministico.
- **Più tool, o un errore**: elenca deterministicamente i `summary` dei tool
  eseguiti e gli eventuali errori.

Questa scelta è stata rafforzata dopo una prova con Ollama Cloud: il modello aveva
copiato la percentuale corretta ma l'aveva accompagnata con un denominatore
inventato. L'LLM resta responsabile del routing linguistico, non della riscrittura
dei risultati numerici.
- **`meta_knowledge`**: recupera i fatti pertinenti da `knowledge.py` (Sezione 7) e,
  se l'LLM è disponibile, li riformula in modo conversazionale — senza mai aggiungere
  fatti che non sono nella base di conoscenza.
- **`none`**: spiega perché nessuno strumento può rispondere, usando il `reasoning`
  che l'LLM (o il fallback) ha fornito.

### `knowledge.py` — cosa sa il sistema di se stesso

Un dizionario Python statico di ~12 argomenti (preprocessing, rilevamento chiusure,
letture corrotte, doppioni, timestamp, codici di stato, i vari "caveat" scoperti nelle
Fasi 1-2, ecc.), con i **fatti presi verbatim** da `PHASE1_WALKTHROUGH.md` e
`PHASE2_WALKTHROUGH.md` — non generati né stimati. `pick_topics()` fa un matching a
parole chiave tra la domanda e gli argomenti disponibili, così `composer.py` manda
all'LLM solo i fatti rilevanti, non l'intera base di conoscenza ad ogni domanda.

**Perché statico e non "chiedi all'LLM di leggere il codice"**: un LLM senza accesso
diretto al codice inventerebbe con sicurezza dettagli plausibili ma falsi
sull'ingestion (è il classico rischio di allucinazione). Congelando qui i fatti già
verificati nelle Fasi 1-2, l'LLM può solo *riformulare*, non *inventare*.

### `agent.py` — l'orchestratore

La classe `AROLAgent`: costruisce un `ToolExecutor` (carica i dati), controlla una
volta sola se Ollama è raggiungibile (`llm.is_ollama_available()`) e lo ricorda in
`self.llm_available`. Il metodo `query()` fa girare `router.route()` →
`executor.execute_all()` → `composer.compose()` in sequenza e restituisce un
`AgentResponse` con la risposta testuale, quali tool sono stati chiamati e con che
parametri, i dati grezzi (`raw_data`, utile per un uso programmatico oltre che
testuale), il tempo di esecuzione, ed eventuali errori.

### `__main__.py` — la CLI interattiva

```bash
PYTHONPATH=src python -m arol_analytics.agent data/processed
```

Carica i dati una volta, poi un ciclo `> domanda` → risposta, finché non si scrive
`exit`/`quit` o si preme Ctrl-D. Stampa anche quale tool è stato usato, se l'LLM era
attivo, e quanto ci ha messo — utile per capire *cosa* ha deciso l'agente, non solo
*cosa* ha risposto.

---

## 3. I 10 strumenti visti dal router (riferimento rapido)

Il router non "sa" nulla di suo sui dati AROL — conosce solo quello che `tools.py`
gli mette nel prompt di sistema. Per i dettagli di ciascuno strumento (formule,
soglie, avvisi automatici) vedi `docs/PHASE2_WALKTHROUGH.md`; qui solo il collegamento
domanda-tipo → strumento, utile come "cheat sheet":

| # | Strumento | Risponde a | Esempio di domanda |
|---|---|---|---|
| 1 | `dataset_summary` | Panoramica generale: quante chiusure, quante teste, intervallo di tempo, tasso di successo complessivo | "Quante chiusure ci sono nel dataset?" |
| 2 | `success_rate_analysis` | Tasso di successo, raggruppabile per testa/giorno/ora/file | "Qual è il tasso di successo per testa?" |
| 3 | `torque_statistics` | Statistiche sulla coppia (media, quartili, outlier), filtrabili per esito | "Qual è la coppia media nelle chiusure riuscite?" |
| 4 | `torque_trend_analysis` | Deriva/trend della coppia nel tempo, per testa | "La coppia sta cambiando nel tempo?" |
| 5 | `anomaly_detection` | Chiusure anomale per coppia + ore con tasso di fallimento anomalo | "Ci sono eventi anomali?" |
| 6 | `head_comparison` | Confronto diretto tra teste (o un sottoinsieme) | "Confronta la testa H12 con la H29" |
| 7 | `failure_analysis` | Analisi approfondita dei fallimenti: raffiche, picchi giornalieri, causa dominante | "Perché la testa H29 fallisce di più?" |
| 8 | `capping_speed_analysis` | Velocità di produzione (macchina intera vs singola testa) | "Qual è la velocità di produzione della macchina?" |
| 9 | `idle_analysis` | Periodi di inattività, tasso di utilizzo | "Qual è il tasso di utilizzo della macchina?" |
| 10 | `generate_kpi_dashboard` | Cruscotto riassuntivo (chiama gli altri strumenti internamente) | "Come va la macchina in generale?" |

Più due voci speciali, non presenti nel Layer 2, gestite direttamente dal router:

| Voce | Cosa fa |
|---|---|
| `meta_knowledge` | Domande su come funziona il sistema stesso (preprocessing, assunzioni) — risposta da `knowledge.py`, non dai dati (Sezione 8) |
| `none` | Nessuno strumento può rispondere alla domanda — l'agente lo dice esplicitamente invece di inventare una risposta |

---

## 4. Il percorso passo-passo: cosa succede quando arriva una domanda

1. **Routing**: `router.route(domanda)` prova prima l'LLM (se disponibile). Costruisce
   il prompt di sistema da `tools.py`, manda domanda + prompt, prova a interpretare la
   risposta come JSON valido (con un retry se serve), normalizza gli eventuali
   parametri enum. Se tutto questo fallisce, passa a `fallback.keyword_route()`.
2. **Esecuzione**: `executor.execute_all()` prende la lista di `tool_calls` decisa dal
   router (una o più) e le esegue davvero contro i dati già caricati in memoria. Ogni
   chiamata è isolata: se una fallisce, le altre proseguono comunque.
3. **Composizione**: `composer.compose()` prende i risultati (compresi eventuali
   errori) e produce un testo deterministico. La disponibilità dell'LLM cambia il
   routing, non le formule o i numeri mostrati.
4. **Risposta**: `agent.query()` impacchetta tutto in un `AgentResponse` e lo
   restituisce — la CLI (`__main__.py`) lo stampa, ma qualunque altra interfaccia (es.
   una futura app web, secondo `bot_proposal.md`) potrebbe usare lo stesso oggetto.

---

## 5. Ollama: locale o cloud, a scelta

Il client (`llm.py`) parla lo stesso protocollo HTTP sia che Ollama giri in locale
(`ollama serve` sulla propria macchina, `ollama pull <modello>` per scaricarlo) sia
che si usi [Ollama Cloud](https://ollama.com) (nessuna installazione locale, serve solo
una API key da ollama.com/settings/keys). La scelta è automatica in base alle variabili
d'ambiente:

| Variabile | Effetto |
|---|---|
| (nessuna impostata) | locale, `http://localhost:11434`, nessuna autenticazione |
| `OLLAMA_API_KEY=...` | cloud, `https://ollama.com`, header `Authorization: Bearer ...` aggiunto automaticamente |
| `AROL_OLLAMA_HOST=...` | override esplicito dell'host, vince sempre sulle due regole sopra |
| `AROL_LLM_MODEL=...` | nome del modello (default `mistral`, valido solo in locale) |

**Attenzione ai nomi dei modelli**: quando si passa da un `ollama serve` locale, i
modelli cloud si richiamano con il suffisso `:cloud` (es. `gpt-oss:120b-cloud`). Quando
invece si chiama `https://ollama.com` **direttamente** (come fa questo client quando
c'è una `OLLAMA_API_KEY`), si usa il nome esatto restituito da `GET /api/tags` su
quell'host, **senza** il suffisso — il suffisso serve solo per il routing interno di un
`ollama serve` locale, non ha senso quando non c'è nessun binario locale in mezzo.

---

## 6. Un bug vero, trovato testando con un LLM reale

Tutti i moduli erano stati verificati con l'LLM forzato spento (Sezione 8) prima di
provare un vero modello. Al primo giro con Ollama Cloud (modello `gpt-oss:120b`) sulla
domanda "What is the success rate per capping head?", il router ha correttamente
capito di dover chiamare `success_rate_analysis` raggruppando per testa — ma ha scritto
`"group_by": "head"` nel JSON, non `"per_head"` come richiede la funzione Layer 2.
Risultato: `ValueError: group_by must be one of [...], got 'head'`. L'`executor` l'ha
gestito correttamente (nessun crash, un errore strutturato), ma l'utente si è visto
restituire un messaggio d'errore invece di una risposta.

**La causa**: un LLM capisce affidabilmente *il concetto* giusto ("raggruppa per
testa"), ma non riproduce sempre *la stringa esatta* richiesta da un'API, anche quando
il prompt la elenca esplicitamente. È un problema strutturale del function-calling con
LLM, non un caso isolato — succedeva anche su `torque_statistics` con lo stesso
parametro.

**La correzione**: `tools.normalize_enum_value()` confronta il valore ricevuto con i
valori enum dichiarati nel registro per quel tool/parametro:
1. se coincide esattamente, va bene così com'è;
2. altrimenti prova un confronto senza spazi/trattini/underscore e senza distinguere
   maiuscole/minuscole (`"z-score"`, `"Z Score"` e `"zscore"` diventano tutti la stessa
   cosa);
3. altrimenti cerca corrispondenze per sottostringa (`"head"` è contenuto in
   `"per_head"`, `"success"` è contenuto solo in `"successful_only"` tra le opzioni
   disponibili, quindi la scelta è univoca);
4. se non trova nulla di sensato, **scarta** il parametro invece di passarlo al tool —
   la funzione Layer 2 userà il suo valore di default, che è quasi sempre una scelta
   ragionevole, invece di sollevare un'eccezione.

Il tutto è generico (si applica a qualunque parametro enum di qualunque tool, non solo
`group_by`), quindi copre automaticamente anche `filter_status` di `torque_statistics`
e `method` di `anomaly_detection` senza bisogno di codice specifico per ciascuno.
Verificato con 8 casi di test di regressione (Sezione 8), incluso esattamente il caso
che ha fatto scattare l'errore la prima volta.

---

## 7. Il fallback a parole chiave, e perché l'ordine conta

`fallback.KEYWORD_MAP` è una lista ordinata, non un dizionario: la prima voce che
trova una corrispondenza vince. Le voci più specifiche stanno in cima apposta — es.
"contributes most to overall failures" deve attivare `failure_analysis` e non
`head_comparison`, anche se la domanda parla di teste e potrebbe sembrare un confronto.
Verificato con 13 domande di esempio (una per ciascun tool più `meta_knowledge`), tutte
instradate al tool giusto (Sezione 8).

---

## 8. Perché una base di conoscenza statica, e non "chiedilo all'LLM"

Per le domande sul funzionamento del sistema stesso ("che preprocessing è stato
applicato ai dati grezzi?", "come vengono rilevati i doppioni?"), l'agente **non**
lascia decidere all'LLM cosa rispondere in autonomia — gli fornisce i fatti già
verificati nelle Fasi 1-2 (`knowledge.py`) e gli chiede solo di riformularli in modo
colloquiale. Un LLM a cui si chiedesse direttamente "come funziona il preprocessing di
questo sistema?" senza vedere il codice risponderebbe comunque, con sicurezza, ma
inventando dettagli plausibili — è esattamente il tipo di errore silenzioso più
pericoloso in un contesto industriale, dove le assunzioni sulla qualità dei dati
contano quanto i dati stessi.

---

## 9. Risultati finali (verificato, non solo dichiarato)

`tests/test_agent.py` copre tre livelli, in ordine crescente di dipendenza da un LLM
vero:

```
8/8  casi di normalizzazione enum passati (incluso il bug della Sezione 5)
13/13 casi di instradamento a parole chiave passati
8/8  domande di validazione risolte con l'LLM forzato spento (fallback completo)
```
Questi primi tre gruppi **non richiedono Ollama** — passano sempre, in qualunque
ambiente, anche senza rete.

**Con un LLM vero** (Ollama Cloud, modello `gpt-oss:120b`, sulle stesse 8 domande di
validazione della specifica di progetto): tutte risolte correttamente dopo la
correzione della Sezione 5, incluse quelle che prima fallivano
(`group_by="per_head"` ora arriva corretto sia a `success_rate_analysis` che a
`torque_statistics`).

**Un esempio verificato end-to-end sui dati completi** (non sul campione di test):
alla domanda "Explain why head H29 has more failed closures", il router ha scelto
`failure_analysis(head_filter=['H29'])`, e la risposta dell'LLM (117 fallimenti, 111
di tipo RotatingAtRaise/codice 65 e 6 di tipo EarlyRaise/codice 9, un picco il
2026-02-25 con 49 fallimenti, una raffica di 3 eventi consecutivi alle 11:47:04-11:47:09
dello stesso giorno) è stata **ricontrollata chiamando `failure_analysis` direttamente**,
non solo fidandosi della prosa generata — i numeri corrispondono esattamente
all'output grezzo del tool. Nessuna allucinazione in questo caso, ma il controllo
indipendente resta la prassi giusta prima di fidarsi di un output generato.

**Un limite del campione usato nei test** (stesso problema già documentato in
`PHASE2_WALKTHROUGH.md` per `tests/test_analytics.py`): `test_agent.py` lavora su un
campione di 100.000 righe che, essendo `closure_events.parquet` ordinato per testa e
non per tempo, contiene **solo la testa H01**. Buono per verificare che ogni pezzo
della pipeline funzioni e non vada in errore, ma le risposte su "quale testa ha più
variabilità/fallimenti" nel test sono banali per costruzione (c'è una sola testa) — per
risposte rappresentative su tutte le 36 teste serve la CLI sui dati completi
(`data/processed`, non il campione).

---

## 10. Come eseguire

```bash
source .venv/bin/activate

# CLI interattiva sui dati completi (locale, se Ollama non è configurato: fallback automatico)
PYTHONPATH=src python -m arol_analytics.agent data/processed

# Stessa cosa, ma con Ollama Cloud invece che locale
export OLLAMA_API_KEY="<la-tua-chiave-da-ollama.com>"
export AROL_LLM_MODEL="<un-modello-dalla-lista-cloud-su-ollama.com/models>"
PYTHONPATH=src python -m arol_analytics.agent data/processed

# Test (sempre eseguibile; la parte con LLM vero si attiva solo se Ollama è raggiungibile)
PYTHONPATH=src python tests/test_agent.py
```

---

## 11. Cosa manca ancora

- **Nessuna interfaccia oltre alla CLI**: `bot_proposal.md` (in root) propone due
  architetture per un'eventuale interfaccia utente — query guidate da menu (Proposta
  1) o chat libera (Proposta 2, sconsigliata dallo stesso autore della proposta) — non
  ancora scelta né implementata.
- **Percorso multi-tool del composer** (una domanda che richiede più strumenti in
  sequenza, con il report strutturato a sezioni) verificato solo con dati sintetici
  finti nel codice, non ancora con una vera domanda multi-tool risolta da un LLM reale
  — le 8 domande di validazione usate finora hanno tutte attivato un singolo tool.
- **Nessuna valutazione automatica della qualità del testo generato**: i test
  verificano che l'agente non crashi e scelga il tool giusto, non che la prosa
  dell'LLM sia accurata — quella va controllata a mano (come nella Sezione 8), e
  andrebbe rifatta ogni volta che si cambia modello o provider.
- **Nessun test automatico formale (pytest)** esiste ancora per nessuna delle tre fasi
  — l'ingestion ha solo verifiche manuali documentate in `PHASE1_WALKTHROUGH.md`,
  Layer 2 e Layer 3 hanno script di test (`tests/test_analytics.py`,
  `tests/test_agent.py`), non suite pytest.

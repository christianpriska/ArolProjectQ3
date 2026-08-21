## Proposta 1 - limited interaction
Interazioen limitata alle queries disponibili
Permette un'interazione più veloce e offre una buona soluzione per un dipartimento di R&D
1. Ingestion & Upload                                  
    - Seleziona sorgente: Singolo CSV/zip/cartella    
    - Caricamento file e convalida schema

2. Preprocessing & Scope Filtering
    - Preprocessing (selezione eventi rilevanti, gestione duplicati, ...)
    - Visualizza dashboard riassuntiva (time range, # valid data, heads)
    - Applica filtri opzionali: time range, head(s) 

3. Macro-Categoria di Analisi: userei quelle delle slide (vedi sotto)

4. Selezione Query: terrei quelle delle slide con piccole modifiche (vedi sotto le parti in corsivo)
5. Visualizzazione risposta
6. Prosecuzione con report o nuova query
    - ripartendo da 2/3/4 a seconda che teniamo gli stessi filtri o categiria
7. Rendering Report & Export: in base ai risultati 
    - Proposta di struttura: tabella dati + quey richiesta (+ filtri applicati) + risposta (testo/grafico)
    - Bottone esporta PDF/Markdown

## Proposta 2 - open chat
L'interazione non è limitata alle queries proposte ma è libera e avviene tramite LLM
Mi sembra una complicazione non necessariamente necessaria anche perchè creerebbe una rosa di richeiste di cui non siamo certi averei dati per rispondere.
Sarebbe come caricare i dati su un qualsiasi LLm e fare la domanda --> soluzione già esistente

1. Ingestion & Upload                                  
    - Seleziona sorgente: Singolo CSV/zip/cartella    
    - Caricamento file e convalida schema

2. Preprocessing & Scope Filtering
    - Preprocessing (selezione eventi rilevanti, gestione duplicati, ...)
    - Visualizza dashboard riassuntiva (time range, # valid data, heads)
    - Applica filtri opzionali: time range, head(s) 
   
3. Conversational Prompting with Suggested Chips: il chatbot può suggerire alcune queries ma l'interazione resta libera

4. Visualizzazione risposta
5. Prosecuzione con report o nuova query
    - ripartendo da 2/3/4 a seconda che teniamo gli stessi filtri o categiria
6. Rendering Report & Export: in base ai risultati 
    - Proposta di struttura: tabella dati + quey richiesta (+ filtri applicati) + risposta (testo/grafico)
    - Bottone esporta PDF/Markdown

## Queries richieste

### Summary:
1.  Basic data exploration queries: these help the user understand the dataset after preprocessing
2. Quality and success-rate queries: these directly match your functional requirement about successful capping operations.
3. Torque-related analytical queries: used to assess process stability and mechanical behavior.
4. Time-based and trend queries: these exploit timestamps after event reconstruction.
5. Filtering and conditional queries: queries combining status, torque, and counters.
6. Diagnostic and comparative queries: more advanced, but still feasible with classical analytics or simple *AI reasoning*
7. Explanation-oriented queries (agentic behavior): these test the reasoning and explanation capability of the bot
8. Visualization-oriented queries: these link directly to the student-designed visualization part
9. Meta/system queries: Useful for usability and transparency in a thesis project, possono avere risposte di default

---

### 1. Basic data exploration queries
- **How many** capping operations were performed in the selected month? - *How many capping operations were performed in the selected time period?*
- **How many** closure events were performed by each head?
- Show me the **time range covered** by the dataset.
- Are there any **missing or invalid** torque values?

### 2. Quality and success-rate queries
- What **percentage** of capping operations were **successful**? - *What percentage of capping operations were (un)/successful?*
- **How many** closures ended with a **positive** outcome? - *How many closures ended with a positive/negative outcome?*
- **How many failed** capping operations were recorded? - *Note: Same as the question above*
- What is the **success rate** per capping head? - *What is the success/failure rate per capping head?*
- Which head shows the **lowest success rate**? - *Which head shows the lowest/higest success rate?*

### 3. Torque-related analytical queries
- What is the **average closing torque** for successful capping operations? 
- *What is the **range of closing torque** for unsuccessful capping operations?*
- Show the **torque distribution** for all successful closures. - *Show the torque distribution for all (un)/successful closures*
- Are there torque **values outside the expected** operating **range** of ...?
- Compare the **average** torque of **successful vs failed** closures.
- Which head shows the **highest torque variability**?

### 4. Time-based and trend queries
- How did the capping **success rate** evolve **over time**? - *How did the capping success/ dailure rate evolve (increase/decrease/stale) over time?*
- Show a **daily breakdown** of successful vs failed closures.
- Are there specific **time intervals with abnormal** failure rates?
- Did the **average torque** change **over the observed month**? - *Did the average torque change over the observed time period? *
- Is there a **correlation between time** of day and **failure probability**? - *Is there a correlation between time of day and success/failure probability?*

### 5. Filtering and conditional queries
- **Show only** capping operations with a **positive outcome**
- List **all failed capping** events with torque below threshold.
- How many closures had **torque above** X Nm?
- Show all **capping events for head X** with failed outcome. - *Show all capping events for head X with successful/failed outcome*
- Count successful closures after **removing all duplicated** entries. - *Note: gestiamo già questa situazione nella fase di data prep/cleaning*

### 6. Diagnostic and comparative queries
- **Which** capping head **behaves differently** from the others?
- Is there a head with an **unusual number of failed** closures?
- Compare **performance between head X and head Y**.
- **Which head contributes most** to overall failures? - *Which head contributes most to overall failures/sussecces?* 
- Does **higher torque** correlate with **higher success rate**?

### 7. Explanation-oriented queries (agentic behavior)
- Why is the overall **success rate** lower **on certain days**?
- Explain **why head X has more failed closures**
- **Summarize the main issues** observed in the capping process
- **Which signals should be monitored** more closely?
- Generate a **short report on capping quality** for this dataset - *Note: inserire una traccia da seguire*

### 8. Visualization-oriented queries
- **Plot** the **closing torque over time** for successful closures - *Plot the closing torque over time for successful/failed closures*
- Show a **histogram of closing torque** values.
- Create a chart showing **success rate per head**.
- **Visualize** failed **closures over time**. - *Visualize failed/successful closures over time*
- Generate a **dashboard summary** of capping performance. - *Note: inserire una traccia da seguire*

### 9. Meta / system queries
- What **preprocessing** steps were applied to the raw data?
- How were **duplicated** closures detected and removed?
- Which **assumptions** were made during **data cleaning**?
- What **features** are used to classify a **successful closure**?


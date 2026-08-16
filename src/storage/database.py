"""
Gestione del database SQLite che contiene gli eventi di chiusura ricostruiti e puliti. 
Una riga = una chiusura reale 

Tabella 'events' con attributi: 
- id [intero auto-increment]-> identificativo riga
- timestamp [testo] -> quando è avvenuta la chiusura 
- head [testo]-> quale testa ha chiuso
- torque [numero decimale] -> coppia applicata in Nm 
- status [intero] -> codice di esito (guarda la tabella slide x riferimento)
- source_file [testo] -> da quale file CSV proviene 
"""

import sqlite3
from src.config import DB_PATH

def create_connection(): 
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)

    return connection

def create_table_events(connection): 
    """Creata table 'events' if it doesn't exist"""
    connection.execute("""

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            timestamp TEXT NOT NULL, 
            head TEXT NOT NULL, 
            torque REAL NOT NULL, 
            status INTEGER NOT NULL, 
            source_file TEXT NOT NULL
            )
        """)
    connection.commit()

def insert_events(connection, events): 
    """
    Inserisce più eventi in un colpo solo. 
    Evento è una lista di tuple, ognuna della forma: 
    - (timestamp, head, torque, status, source_file)
    """
    connection.executemany("""
        INSERT INTO events (timestamp, head, torque, status, source_file)
        VALUES (?, ?, ?, ?, ?)
    """, events)

    connection.commit()

def delete_events(connection): 
    connection.execute("DELETE FROM events")
    connection.commit() 

if __name__ == "__main__":
    conn = create_connection()
    create_table_events(conn)
    #delete_events(conn)

    righe = list(conn.execute("SELECT * FROM events"))

    if righe:
        print("Attenzione: la tabella non è vuota!")
        for riga in righe:
            print(" ", riga)
    else:
        print(f"Database pronto e vuoto in: {DB_PATH}")

    conn.close()


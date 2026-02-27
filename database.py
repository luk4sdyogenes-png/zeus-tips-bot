
import sqlite3

def init_db():
    conn = sqlite3.connect("zeus_tips.db")
    cursor = conn.cursor()

    # Tabela para assinantes
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            start_date TEXT,
            end_date TEXT,
            plan TEXT,
            status TEXT
        )
    """)

    # Tabela para histórico de palpites
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS predictions_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER,
            championship TEXT,
            team_a TEXT,
            team_b TEXT,
            match_time TEXT,
            analysis TEXT,
            prediction TEXT,
            confidence REAL,
            suggested_odd REAL,
            sent_date TEXT
        )
    """)

    # Tabela para configurações do bot
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    conn.close()

def get_setting(key):
    conn = sqlite3.connect("zeus_tips.db")
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def set_setting(key, value):
    conn = sqlite3.connect("zeus_tips.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Banco de dados 'zeus_tips.db' inicializado com sucesso.")

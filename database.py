import sqlite3
from datetime import datetime


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


def add_subscriber(user_id, username, plan, end_date):
    conn = sqlite3.connect("zeus_tips.db")
    cursor = conn.cursor()
    start_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT OR REPLACE INTO subscribers (user_id, username, start_date, end_date, plan, status) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, username, start_date, end_date, plan, "active")
    )
    conn.commit()
    conn.close()


def get_subscriber(user_id):
    conn = sqlite3.connect("zeus_tips.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, username, start_date, end_date, plan, status FROM subscribers WHERE user_id = ?",
        (user_id,)
    )
    result = cursor.fetchone()
    conn.close()
    return result


def update_subscriber_status(user_id, status):
    conn = sqlite3.connect("zeus_tips.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE subscribers SET status = ? WHERE user_id = ?",
        (status, user_id)
    )
    conn.commit()
    conn.close()


def get_all_active_subscribers():
    conn = sqlite3.connect("zeus_tips.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, end_date FROM subscribers WHERE status = 'active'"
    )
    results = cursor.fetchall()
    conn.close()
    return results


def get_all_subscribers():
    conn = sqlite3.connect("zeus_tips.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, status FROM subscribers"
    )
    results = cursor.fetchall()
    conn.close()
    return results


def add_prediction_history(match_id, championship, team_a, team_b, match_time, analysis, prediction, confidence, suggested_odd):
    conn = sqlite3.connect("zeus_tips.db")
    cursor = conn.cursor()
    sent_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO predictions_history (match_id, championship, team_a, team_b, match_time, analysis, prediction, confidence, suggested_odd, sent_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (match_id, championship, team_a, team_b, match_time, analysis, prediction, confidence, suggested_odd, sent_date)
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Banco de dados 'zeus_tips.db' inicializado com sucesso.")

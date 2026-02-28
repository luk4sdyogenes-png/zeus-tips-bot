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

    # Tabela para histórico de palpites (atualizada com fixture_id e result)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS predictions_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fixture_id INTEGER,
            championship TEXT,
            team_a TEXT,
            team_b TEXT,
            match_time TEXT,
            analysis TEXT,
            prediction TEXT,
            confidence REAL,
            suggested_odd REAL,
            result TEXT DEFAULT 'pending',
            date_added TEXT
        )
    """)

    # Tabela para configurações do bot
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # --- Migração: adicionar colunas que podem não existir em bancos antigos ---
    _migrate_predictions_history(cursor)

    conn.commit()
    conn.close()


def _migrate_predictions_history(cursor):
    """
    Verifica se as colunas novas existem na tabela predictions_history.
    Se não existirem, adiciona-as para manter compatibilidade com bancos antigos.
    """
    cursor.execute("PRAGMA table_info(predictions_history)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    # Renomear match_id -> fixture_id se necessário (match_id era o nome antigo)
    if "fixture_id" not in existing_columns and "match_id" in existing_columns:
        cursor.execute("ALTER TABLE predictions_history RENAME COLUMN match_id TO fixture_id")

    # Adicionar coluna fixture_id se não existir de nenhuma forma
    if "fixture_id" not in existing_columns and "match_id" not in existing_columns:
        cursor.execute("ALTER TABLE predictions_history ADD COLUMN fixture_id INTEGER")

    # Adicionar coluna result se não existir
    if "result" not in existing_columns:
        cursor.execute("ALTER TABLE predictions_history ADD COLUMN result TEXT DEFAULT 'pending'")

    # Adicionar coluna date_added se não existir (substitui sent_date)
    if "date_added" not in existing_columns:
        if "sent_date" in existing_columns:
            cursor.execute("ALTER TABLE predictions_history RENAME COLUMN sent_date TO date_added")
        else:
            cursor.execute("ALTER TABLE predictions_history ADD COLUMN date_added TEXT")


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


def add_prediction_history(fixture_id, championship, team_a, team_b, match_time, analysis, prediction, confidence, suggested_odd):
    """Adiciona um palpite ao histórico com status 'pending'."""
    conn = sqlite3.connect("zeus_tips.db")
    cursor = conn.cursor()
    date_added = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO predictions_history (fixture_id, championship, team_a, team_b, match_time, analysis, prediction, confidence, suggested_odd, result, date_added) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (fixture_id, championship, team_a, team_b, match_time, analysis, prediction, confidence, suggested_odd, "pending", date_added)
    )
    conn.commit()
    conn.close()


def get_pending_predictions():
    """Retorna todos os palpites com resultado pendente."""
    conn = sqlite3.connect("zeus_tips.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, fixture_id, championship, team_a, team_b, match_time, prediction, confidence, suggested_odd, date_added "
        "FROM predictions_history WHERE result = 'pending'"
    )
    results = cursor.fetchall()
    conn.close()
    return results


def update_prediction_result(prediction_id, result):
    """Atualiza o resultado de um palpite (green, red)."""
    conn = sqlite3.connect("zeus_tips.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE predictions_history SET result = ? WHERE id = ?",
        (result, prediction_id)
    )
    conn.commit()
    conn.close()


def get_daily_predictions_summary(date_str):
    """
    Retorna o resumo dos palpites de um dia específico.
    date_str no formato 'YYYY-MM-DD'.
    Retorna lista de tuplas: (id, fixture_id, prediction, confidence, suggested_odd, result)
    """
    conn = sqlite3.connect("zeus_tips.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, fixture_id, prediction, confidence, suggested_odd, result "
        "FROM predictions_history WHERE date_added LIKE ?",
        (f"{date_str}%",)
    )
    results = cursor.fetchall()
    conn.close()
    return results


if __name__ == "__main__":
    init_db()
    print("Banco de dados 'zeus_tips.db' inicializado com sucesso.")

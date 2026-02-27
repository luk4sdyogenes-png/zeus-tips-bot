
import schedule
import time
import threading
import asyncio
from datetime import datetime, timedelta

# Importar a função de envio de palpites do bot.py
# É importante que esta função seja capaz de ser chamada de forma assíncrona
# e que tenha acesso ao `application` do bot.

def run_continuously(interval=1):
    """Continuously run pending jobs every 'interval' seconds."""
    cease_continuous_run = threading.Event()

    class ScheduleThread(threading.Thread):
        @classmethod
        def run(cls):
            while not cease_continuous_run.is_set():
                schedule.run_pending()
                time.sleep(interval)

    continuous_thread = ScheduleThread()
    continuous_thread.start()
    return cease_continuous_run

async def schedule_daily_predictions(application):
    # A função send_daily_predictions precisa ser um coroutine
    # e precisa do objeto `application` para enviar mensagens.
    # Para agendar uma função assíncrona com `schedule`, precisamos envolvê-la.
    async def job():
        from bot import send_daily_predictions # Importar aqui para evitar circular dependency
        await send_daily_predictions(application)

    # Agendar para meio-dia (12:00) horário de Brasília (GMT-3)
    # Se o servidor estiver em UTC, 12:00 BRT é 15:00 UTC
    schedule.every().day.at("15:00").do(lambda: asyncio.create_task(job()))
    print("Agendamento diário de palpites configurado para 12:00 BRT.")


# Exemplo de como iniciar o scheduler (será chamado do main do bot)
# if __name__ == "__main__":
#     # Isso é apenas um exemplo. O `application` real virá do bot principal.
#     class MockApplication:
#         def create_task(self, coro):
#             asyncio.run(coro)
#
#     mock_app = MockApplication()
#     asyncio.run(schedule_daily_predictions(mock_app))
#     stop_run_continuously = run_continuously()
#     # Para parar o scheduler, chame stop_run_continuously.set()


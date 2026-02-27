import requests
import os
import json
import logging
from datetime import datetime
from openai import OpenAI
import mercadopago

# Carregar variáveis de ambiente apenas se não estiverem já definidas (para Railway)
from dotenv import load_dotenv
load_dotenv(override=False)  # override=False evita sobrescrever variáveis já definidas

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MERCADOPAGO_ACCESS_TOKEN = os.getenv("MERCADOPAGO_ACCESS_TOKEN")

logger = logging.getLogger(__name__)

# --- API-Football Integration ---

def get_api_football_headers():
    return {
        "x-rapidapi-host": "v3.football.api-sports.io",
        "x-rapidapi-key": API_FOOTBALL_KEY
    }

def get_fixtures_by_date(date: str): # date format YYYY-MM-DD
    url = f"https://v3.football.api-sports.io/fixtures?date={date}"
    headers = get_api_football_headers()
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()["response"]

def get_team_statistics(team_id: int, league_id: int, season: int):
    url = f"https://v3.football.api-sports.io/teams/statistics?league={league_id}&team={team_id}&season={season}"
    headers = get_api_football_headers()
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()["response"]

def get_h2h_statistics(team_a_id: int, team_b_id: int):
    url = f"https://v3.football.api-sports.io/fixtures/headtohead?h2h={team_a_id}-{team_b_id}"
    headers = get_api_football_headers()
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()["response"]

# --- OpenAI Integration ---

def analyze_and_predict(match_data: dict):
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY não configurada. Verifique as variáveis de ambiente.")
        return None

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception as e:
        logger.error(f"Erro ao inicializar cliente OpenAI: {e}")
        return None

    prompt = f"""
    Analise os seguintes dados de futebol para gerar um palpite esportivo. Considere as estatísticas dos times, forma recente, confrontos diretos e o fator mandante/visitante. O palpite deve incluir um nível de confiança (%), o melhor mercado (ex: resultado final, ambas marcam, over/under) e odds sugeridas.

    Dados da Partida:
    Campeonato: {match_data.get('championship')}
    Time da Casa: {match_data.get('home_team')}
    Time Visitante: {match_data.get('away_team')}
    Horário: {match_data.get('match_time')}

    Estatísticas do Time da Casa: {json.dumps(match_data.get('home_team_stats'))}
    Estatísticas do Time Visitante: {json.dumps(match_data.get('away_team_stats'))}
    Confrontos Diretos: {json.dumps(match_data.get('h2h'))}

    Formato da Resposta:
    Análise: [resumo da análise]
    Palpite: [palpite]
    Confiança: [X%]
    Mercado: [melhor mercado]
    Odd Sugerida: [odd]
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini", # Usando o modelo gpt-4.1-mini conforme solicitado
            messages=[
                {"role": "system", "content": "Você é um analista de apostas esportivas experiente e imparcial."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Erro ao chamar a API da OpenAI: {e}")
        return None

# --- Mercado Pago Integration ---

def get_mercadopago_sdk():
    if not MERCADOPAGO_ACCESS_TOKEN:
        logger.error("MERCADOPAGO_ACCESS_TOKEN não configurada. Verifique as variáveis de ambiente.")
        return None
    sdk = mercadopago.SDK(MERCADOPAGO_ACCESS_TOKEN)
    return sdk

def create_payment(plan_details: dict, user_id: int):
    """
    Cria um pagamento via Mercado Pago usando a SDK atualizada.
    A SDK atual requer sdk.payment().create() com parênteses em payment().
    """
    sdk = get_mercadopago_sdk()
    if not sdk:
        logger.error("Erro ao obter SDK do Mercado Pago")
        return None

    title = plan_details.get("title", "Assinatura Zeus Tips")
    price = plan_details.get("price", 0.0)
    description = plan_details.get("description", "Assinatura do canal VIP Zeus Tips")

    payment_data = {
        "transaction_amount": price,
        "description": description,
        "payment_method_id": "pix",
        "payer": {
            "email": f"user_{user_id}@example.com", # Email fictício para o payer
        },
        "external_reference": f"zeus_tips_sub_{user_id}_{datetime.now().timestamp()}"
    }

    try:
        # SDK atualizada: sdk.payment().create() com parênteses em payment()
        preference_response = sdk.payment().create(payment_data)
        payment = preference_response["response"]
        
        if payment and payment.get("point_of_interaction") and payment["point_of_interaction"].get("transaction_data"):
            qr_code_base64 = payment["point_of_interaction"]["transaction_data"]["qr_code_base64"]
            qr_code_text = payment["point_of_interaction"]["transaction_data"]["qr_code"]
            payment_id = payment["id"]
            logger.info(f"Pagamento criado com sucesso. ID: {payment_id}")
            return {"qr_code_base64": qr_code_base64, "qr_code_text": qr_code_text, "payment_id": payment_id}
        else:
            error_msg = payment.get('message', 'Resposta inesperada do Mercado Pago')
            logger.error(f"Erro ao criar pagamento: {error_msg}")
            return None
    except AttributeError as e:
        logger.error(f"Erro ao criar pagamento no Mercado Pago (AttributeError - verifique versão da SDK): {e}")
        return None
    except Exception as e:
        logger.error(f"Erro ao criar pagamento no Mercado Pago: {e}")
        return None

def check_payment_status(payment_id: str):
    """
    Verifica o status de um pagamento via Mercado Pago.
    A SDK atual requer sdk.payment().get() com parênteses em payment().
    """
    sdk = get_mercadopago_sdk()
    if not sdk:
        logger.error("Erro ao obter SDK do Mercado Pago")
        return None

    try:
        # SDK atualizada: sdk.payment().get() com parênteses em payment()
        payment_info = sdk.payment().get(payment_id)
        
        if payment_info and payment_info["response"]:
            status = payment_info["response"]["status"]
            logger.info(f"Status do pagamento {payment_id}: {status}")
            return status # Ex: "pending", "approved", "rejected"
        
        logger.warning(f"Resposta vazia ao verificar pagamento {payment_id}")
        return None
    except AttributeError as e:
        logger.error(f"Erro ao verificar status do pagamento (AttributeError - verifique versão da SDK): {e}")
        return None
    except Exception as e:
        logger.error(f"Erro ao verificar status do pagamento no Mercado Pago: {e}")
        return None

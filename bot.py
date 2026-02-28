import os
import logging
from datetime import datetime, timedelta, time
import sqlite3
import json
import io
import base64
import asyncio
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from dotenv import load_dotenv

from api_integrations import get_fixtures_by_date, get_live_fixtures, get_team_statistics, get_h2h_statistics, analyze_and_predict, create_payment, check_payment_status, get_fixture_result
from database import (
    init_db, get_setting, set_setting, add_subscriber, get_subscriber,
    update_subscriber_status, get_all_active_subscribers, add_prediction_history,
    get_all_subscribers, get_pending_predictions, update_prediction_result,
    get_daily_predictions_summary
)

# Carregar variáveis de ambiente
load_dotenv(override=False)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID")) if os.getenv("ADMIN_USER_ID") else None
# A variável VIP_CHANNEL_ID será lida do banco de dados. A variável de ambiente serve como fallback inicial.
VIP_CHANNEL_ID_ENV = os.getenv("VIP_CHANNEL_ID")

# Configurar logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Inicializar o banco de dados
init_db()

# --- Campeonatos Prioritários ---
# IDs dos campeonatos na API-Football
PRIORITY_LEAGUES = {
    71: "Brasileirão Série A",
    72: "Brasileirão Série B",
    73: "Copa do Brasil",
    13: "Libertadores",
    11: "Sul-Americana",
    39: "Premier League",
    140: "La Liga",
    135: "Serie A (Itália)",
    78: "Bundesliga",
    61: "Ligue 1",
    94: "Liga Portugal",
    88: "Eredivisie (Holanda)",
    2: "Champions League",
    3: "Europa League",
    1: "Copa do Mundo",
    4: "Euro (Eurocopa)",
}


# =====================================================
# MELHORIA 1 & 2 - Classificação de Odds e Gestão de Banca
# =====================================================

def classify_odd(odd_value):
    """
    Classifica a odd sugerida e retorna o emoji, a classificação e a % da banca.
    - 🟢 SEGURA: odds até 1.50 → 5% da banca
    - 🟡 MÉDIA: odds entre 1.51 e 2.00 → 3% da banca
    - 🔴 ALTA: odds acima de 2.00 → 1-2% da banca
    """
    try:
        odd = float(odd_value)
    except (ValueError, TypeError):
        odd = 0.0

    if odd <= 1.50:
        return "🟢 SEGURA", "5%"
    elif odd <= 2.00:
        return "🟡 MÉDIA", "3%"
    else:
        return "🔴 ALTA", "1-2%"


def format_prediction_message(pred, header="⚡ ZEUS TIPS - PALPITE DO DIA ⚡"):
    """
    Formata a mensagem de um palpite individual incluindo:
    - Classificação de odd (Melhoria 1)
    - Gestão de banca (Melhoria 2)
    """
    odd_class, banca_pct = classify_odd(pred.get("suggested_odd", 0))

    message_text = f"{header}\n"
    message_text += f"🏆 Campeonato: {pred['championship']}\n"
    message_text += f"⚽ Jogo: {pred['team_a']} vs {pred['team_b']}\n"
    message_text += f"⏰ Horário: {pred['match_time']}\n"
    message_text += f"📊 Análise: {pred['analysis']}\n"
    message_text += f"🎯 Palpite: {pred['prediction']} ({pred.get('market', 'N/A')})\n"
    message_text += f"📈 Confiança: {pred['confidence'] * 100:.0f}%\n"
    message_text += f"💰 Odd sugerida: {pred['suggested_odd']:.2f} {odd_class}\n"
    message_text += f"💼 Gestão: Aposte {banca_pct} da sua banca\n"

    return message_text


def format_live_prediction_message(pred, home_goals, away_goals, elapsed):
    """
    Formata a mensagem de um palpite ao vivo incluindo:
    - Classificação de odd (Melhoria 1)
    - Gestão de banca (Melhoria 2)
    """
    odd_class, banca_pct = classify_odd(pred.get("suggested_odd", 0))

    message_text = f"🔴 ZEUS TIPS - AO VIVO 🔴\n"
    message_text += f"🏆 Campeonato: {pred['championship']}\n"
    message_text += f"⚽ Jogo: {pred['team_a']} {home_goals} x {away_goals} {pred['team_b']}\n"
    message_text += f"⏱ Tempo: {elapsed}'\n"
    message_text += f"📊 Análise: {pred['analysis']}\n"
    message_text += f"🎯 Palpite: {pred['prediction']} ({pred.get('market', 'N/A')})\n"
    message_text += f"📈 Confiança: {pred['confidence'] * 100:.0f}%\n"
    message_text += f"💰 Odd sugerida: {pred['suggested_odd']:.2f} {odd_class}\n"
    message_text += f"💼 Gestão: Aposte {banca_pct} da sua banca\n"

    return message_text


# =====================================================
# MELHORIA 3 - Múltipla Diária (função auxiliar)
# =====================================================

def build_daily_multiple_message(all_predictions):
    """
    Constrói a mensagem da aposta múltipla diária.
    Seleciona os 3 palpites com maior confiança e calcula a odd combinada.
    """
    if len(all_predictions) < 3:
        return None

    # Já devem estar ordenados por confiança (desc), pegar os 3 primeiros
    top3 = all_predictions[:3]
    combined_odd = 1.0
    for p in top3:
        combined_odd *= p["suggested_odd"]

    message = "🔱 ZEUS TIPS - MÚLTIPLA DO DIA 🔱\n"
    message += "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, p in enumerate(top3, 1):
        odd_class, _ = classify_odd(p["suggested_odd"])
        message += f"🎯 Jogo {i}:\n"
        message += f"   🏆 {p['championship']}\n"
        message += f"   ⚽ {p['team_a']} vs {p['team_b']}\n"
        message += f"   📊 Palpite: {p['prediction']} ({p.get('market', 'N/A')})\n"
        message += f"   💰 Odd: {p['suggested_odd']:.2f} {odd_class}\n"
        message += f"   📈 Confiança: {p['confidence'] * 100:.0f}%\n\n"

    message += "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    message += f"💰 Odd combinada: {combined_odd:.2f}\n"
    message += f"💼 Gestão: Aposte 1% da sua banca para múltiplas\n"
    message += "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    message += "⚠️ Múltiplas possuem risco elevado. Aposte com responsabilidade!"

    return message


# =====================================================
# MELHORIA 4 - Verificação de Resultados (RED/GREEN)
# =====================================================

def evaluate_prediction(prediction_text, fixture_result):
    """
    Compara o palpite dado com o resultado real do jogo.
    Retorna 'green' se acertou, 'red' se errou.
    
    Lógica de avaliação:
    - Resultado Final (1X2): compara com o vencedor real
    - Over/Under: compara com total de gols
    - Ambas Marcam: verifica se ambos os times marcaram
    """
    if not fixture_result:
        return None

    home_goals = fixture_result.get("home_goals", 0) or 0
    away_goals = fixture_result.get("away_goals", 0) or 0
    total_goals = home_goals + away_goals
    home_team = fixture_result.get("home_team", "").lower()
    away_team = fixture_result.get("away_team", "").lower()

    pred_lower = prediction_text.lower().strip()

    # --- Avaliação de Over/Under ---
    over_match = re.search(r'over\s*(\d+[.,]?\d*)', pred_lower)
    if over_match:
        line = float(over_match.group(1).replace(",", "."))
        return "green" if total_goals > line else "red"

    under_match = re.search(r'under\s*(\d+[.,]?\d*)', pred_lower)
    if under_match:
        line = float(under_match.group(1).replace(",", "."))
        return "green" if total_goals < line else "red"

    # --- Avaliação de Ambas Marcam ---
    if "ambas marcam" in pred_lower or "btts" in pred_lower:
        if "não" in pred_lower or "no" in pred_lower:
            return "green" if (home_goals == 0 or away_goals == 0) else "red"
        else:
            return "green" if (home_goals > 0 and away_goals > 0) else "red"

    # --- Avaliação de Resultado Final (1X2) ---
    # Verificar se o palpite menciona vitória de um time
    home_words = home_team.split()
    away_words = away_team.split()

    pred_mentions_home = any(w in pred_lower for w in home_words if len(w) > 3)
    pred_mentions_away = any(w in pred_lower for w in away_words if len(w) > 3)

    if "empate" in pred_lower or "draw" in pred_lower:
        return "green" if home_goals == away_goals else "red"

    if "vitória" in pred_lower or "vencer" in pred_lower or "win" in pred_lower or "ganha" in pred_lower:
        if pred_mentions_home and not pred_mentions_away:
            return "green" if home_goals > away_goals else "red"
        elif pred_mentions_away and not pred_mentions_home:
            return "green" if away_goals > home_goals else "red"

    # Se menciona o nome do time diretamente como palpite
    if pred_mentions_home and not pred_mentions_away:
        return "green" if home_goals > away_goals else "red"
    elif pred_mentions_away and not pred_mentions_home:
        return "green" if away_goals > home_goals else "red"

    # Fallback: se não conseguiu interpretar, marca como red por segurança
    logger.warning(f"Não foi possível avaliar o palpite '{prediction_text}' com precisão. Marcando como 'red'.")
    return "red"


async def check_results(context: ContextTypes.DEFAULT_TYPE):
    """
    MELHORIA 4: Verifica os resultados dos jogos palpitados.
    Busca palpites pendentes, consulta a API-Football e marca como GREEN ou RED.
    Envia notificação no canal VIP para cada resultado.
    """
    logger.info("Iniciando verificação de resultados (GREEN/RED)...")
    vip_channel_id = await get_vip_channel_id_from_db()

    pending = get_pending_predictions()
    if not pending:
        logger.info("Nenhum palpite pendente para verificar.")
        return

    logger.info(f"Verificando {len(pending)} palpites pendentes...")

    for pred_row in pending:
        pred_id = pred_row[0]
        fixture_id = pred_row[1]
        championship = pred_row[2]
        team_a = pred_row[3]
        team_b = pred_row[4]
        prediction_text = pred_row[6]
        suggested_odd = pred_row[8]

        if not fixture_id:
            logger.warning(f"Palpite ID={pred_id} sem fixture_id. Pulando.")
            continue

        # Buscar resultado do jogo na API
        fixture_result = get_fixture_result(fixture_id)
        if not fixture_result:
            logger.info(f"Resultado não disponível para fixture {fixture_id}. Mantendo pendente.")
            continue

        # Verificar se o jogo terminou
        status = fixture_result.get("status_short", "")
        if status not in ["FT", "AET", "PEN"]:
            logger.info(f"Jogo {fixture_id} ({team_a} vs {team_b}) ainda não terminou (status: {status}). Pulando.")
            continue

        # Avaliar o palpite
        result = evaluate_prediction(prediction_text, fixture_result)
        if not result:
            continue

        # Salvar resultado no banco
        update_prediction_result(pred_id, result)
        logger.info(f"Palpite ID={pred_id} ({team_a} vs {team_b}): {result.upper()}")

        # Enviar notificação no canal VIP
        if vip_channel_id:
            home_goals = fixture_result.get("home_goals", 0) or 0
            away_goals = fixture_result.get("away_goals", 0) or 0

            if result == "green":
                profit = suggested_odd - 1 if suggested_odd else 0
                msg = (
                    f"✅ GREEN - Acertamos! ✅\n"
                    f"⚽ {team_a} {home_goals} x {away_goals} {team_b}\n"
                    f"🏆 {championship}\n"
                    f"🎯 Palpite: {prediction_text}\n"
                    f"💰 Lucro: +{profit:.2f} unidades por unidade apostada"
                )
            else:
                msg = (
                    f"❌ RED - Não foi dessa vez ❌\n"
                    f"⚽ {team_a} {home_goals} x {away_goals} {team_b}\n"
                    f"🏆 {championship}\n"
                    f"🎯 Palpite: {prediction_text}\n"
                    f"📉 Perda: -1.00 unidade por unidade apostada"
                )

            try:
                await context.bot.send_message(chat_id=vip_channel_id, text=msg)
            except Exception as e:
                logger.error(f"Erro ao enviar resultado no canal VIP: {e}")

        # Pequeno delay entre verificações para não sobrecarregar a API
        await asyncio.sleep(2)

    logger.info("Verificação de resultados concluída.")


# =====================================================
# MELHORIA 5 - ROI Diário
# =====================================================

async def send_daily_summary(context: ContextTypes.DEFAULT_TYPE):
    """
    MELHORIA 5: Envia o resumo diário de resultados no canal VIP às 23:00 BRT.
    Calcula total de palpites, greens, reds e ROI do dia.
    """
    logger.info("Gerando resumo diário de resultados...")
    vip_channel_id = await get_vip_channel_id_from_db()
    if not vip_channel_id:
        logger.warning("VIP_CHANNEL_ID não configurado. Resumo diário não será enviado.")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    predictions = get_daily_predictions_summary(today)

    if not predictions:
        logger.info("Nenhum palpite registrado hoje para o resumo.")
        return

    total = len(predictions)
    greens = 0
    reds = 0
    pending_count = 0
    total_profit = 0.0
    total_staked = 0.0

    for pred in predictions:
        # pred: (id, fixture_id, prediction, confidence, suggested_odd, result)
        result = pred[5]
        suggested_odd = pred[4] or 0.0

        if result == "green":
            greens += 1
            total_profit += (suggested_odd - 1)  # Lucro = odd - 1
            total_staked += 1
        elif result == "red":
            reds += 1
            total_profit -= 1  # Perda = 1 unidade
            total_staked += 1
        else:
            pending_count += 1

    # Calcular ROI
    resolved = greens + reds
    if total_staked > 0:
        roi = (total_profit / total_staked) * 100
    else:
        roi = 0.0

    green_pct = (greens / resolved * 100) if resolved > 0 else 0
    red_pct = (reds / resolved * 100) if resolved > 0 else 0

    roi_emoji = "📈" if roi >= 0 else "📉"
    roi_sign = "+" if roi >= 0 else ""

    message = "📊 ZEUS TIPS - RESUMO DO DIA 📊\n"
    message += "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    message += f"📅 Data: {datetime.now().strftime('%d/%m/%Y')}\n\n"
    message += f"📋 Total de palpites: {total}\n"
    message += f"✅ Greens: {greens} ({green_pct:.0f}%)\n"
    message += f"❌ Reds: {reds} ({red_pct:.0f}%)\n"

    if pending_count > 0:
        message += f"⏳ Pendentes: {pending_count}\n"

    message += f"\n{roi_emoji} ROI do dia: {roi_sign}{roi:.1f}%\n"
    message += f"💰 Lucro/Prejuízo: {roi_sign}{total_profit:.2f} unidades\n"
    message += "\n━━━━━━━━━━━━━━━━━━━━━━━━\n"

    if roi >= 0:
        message += "✨ Dia positivo! Continuamos firmes! ⚡"
    else:
        message += "💪 Dia difícil, mas seguimos com disciplina e gestão!"

    try:
        await context.bot.send_message(chat_id=vip_channel_id, text=message)
        logger.info("Resumo diário enviado com sucesso.")
    except Exception as e:
        logger.error(f"Erro ao enviar resumo diário: {e}")


# --- Funções Auxiliares ---

async def get_vip_channel_id_from_db():
    """
    Obtém o VIP_CHANNEL_ID numérico do banco de dados.
    É crucial que o ID seja o número inteiro do canal (ex: -1001234567890),
    não o link ou o hash.
    """
    vip_channel_id = get_setting("VIP_CHANNEL_ID")
    if not vip_channel_id and VIP_CHANNEL_ID_ENV:
        logger.info("VIP_CHANNEL_ID não encontrado no banco. Usando variável de ambiente como fallback.")
        vip_channel_id = VIP_CHANNEL_ID_ENV
        set_setting("VIP_CHANNEL_ID", vip_channel_id)
    
    try:
        return int(vip_channel_id) if vip_channel_id else None
    except (ValueError, TypeError):
        logger.error(f"VIP_CHANNEL_ID configurado ({vip_channel_id}) não é um ID numérico válido.")
        return None

async def generate_vip_invite_link(context: ContextTypes.DEFAULT_TYPE):
    """
    Gera um link de convite de uso único para o canal VIP.
    O link expira em 24 horas e só pode ser usado por 1 pessoa.
    """
    vip_channel_id = await get_vip_channel_id_from_db()
    if not vip_channel_id:
        logger.error("PROTEÇÃO 1: Falha ao gerar link. VIP_CHANNEL_ID numérico não configurado.")
        return "#ERRO_CANAL_VIP_NAO_CONFIGURADO"

    try:
        expire_date = datetime.now() + timedelta(hours=24)
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=vip_channel_id,
            expire_date=expire_date,
            member_limit=1
        )
        logger.info(f"PROTEÇÃO 1: Link de convite único gerado para o canal {vip_channel_id}.")
        return invite_link.invite_link
    except Exception as e:
        logger.error(f"PROTEÇÃO 1: Erro ao criar link de convite para o canal {vip_channel_id}: {e}")
        return "#ERRO_GERAR_LINK_CONVITE"

async def check_subscriptions_expiration(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Verificando expiração de assinaturas...")
    active_subscribers = get_all_active_subscribers()
    now = datetime.now()

    for user_id, end_date_str in active_subscribers:
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d %H:%M:%S")
        if now > end_date:
            update_subscriber_status(user_id, "expired")
            logger.info(f"Assinatura do usuário {user_id} expirada.")
            try:
                await context.bot.send_message(chat_id=user_id, text=
                    "Sua assinatura Zeus Tips expirou. Para continuar recebendo nossos palpites VIP, "
                    "por favor, renove sua assinatura usando o comando /assinar."
                )
            except Exception as e:
                logger.error(f"Erro ao notificar usuário {user_id} sobre expiração: {e}")

# --- Comandos do Bot ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_html(
        f"Olá, {user.mention_html()}! 👋\n\n"\
        "Bem-vindo ao **Zeus Tips**! Seu canal automatizado de palpites esportivos de futebol.\n\n"\
        "Aqui você encontra as melhores análises e previsões para suas apostas, "\
        "geradas por inteligência artificial avançada e baseadas em dados estatísticos "\
        "detalhados de jogos de futebol.\n\n"\
        "Use os comandos abaixo para interagir:\n\n"\
        "/palpites - Veja uma prévia dos nossos palpites (limitado para não assinantes)\n"\
        "/assinar - Conheça nossos planos e torne-se um membro VIP para acesso exclusivo a todos os palpites!\n"\
        "/status - Verifique o status da sua assinatura\n"\
        "/ajuda - Obtenha mais informações sobre como o bot funciona\n\n"\
        "Pronto para elevar suas apostas? Vamos nessa! ⚡"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Aqui estão os comandos que você pode usar:\n\n"\
        "/start - Mensagem de boas-vindas e apresentação do Zeus Tips\n"\
        "/palpites - Mostrar prévia dos palpites (versão limitada para não assinantes)\n"\
        "/assinar - Mostrar planos e gerar pagamento Pix\n"\
        "/status - Verificar status da sua assinatura\n"\
        "/ajuda - Explicar como funciona\n\n"\
        "Para administradores (apenas o dono do bot):\n"\
        "/admin_jogos [data YYYY-MM-DD] - Indicar jogos específicos para análise\n"\
        "/admin_forcar_envio - Forçar o envio de palpites agora\n"\
        "/admin_estatisticas - Ver estatísticas do bot\n"\
        "/admin_setchannel [ID_numerico_do_canal] - Configurar o ID do canal VIP\n"\
        "/admin_verificar_resultados - Forçar verificação de resultados"
    )

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("Plano Mensal (R$ 29,90)", callback_data='plan_mensal')],
        [InlineKeyboardButton("Plano Trimestral (R$ 69,90)", callback_data='plan_trimestral')],
        [InlineKeyboardButton("Plano Vitalício (R$ 197,00)", callback_data='plan_vitalicio')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Escolha seu plano de assinatura VIP:", reply_markup=reply_markup)

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name

    plans = {
        "plan_mensal": {"title": "Plano Mensal", "price": 29.90, "duration_days": 30},
        "plan_trimestral": {"title": "Plano Trimestral", "price": 69.90, "duration_days": 90},
        "plan_vitalicio": {"title": "Plano Vitalício", "price": 197.00, "duration_days": 36500},
    }

    selected_plan = plans.get(query.data)

    if selected_plan:
        payment_info = create_payment(selected_plan, user_id)
        if payment_info:
            qr_code_base64 = payment_info["qr_code_base64"]
            qr_code_text = payment_info["qr_code_text"]
            payment_id = payment_info["payment_id"]

            context.user_data["current_payment_id"] = payment_id
            context.user_data["current_plan"] = selected_plan

            try:
                qr_img_data = base64.b64decode(qr_code_base64)
                await context.bot.send_photo(chat_id=user_id, photo=qr_img_data)
            except Exception as e:
                logger.error(f"Erro ao enviar imagem do QR Code: {e}")
                await query.edit_message_text("Houve um erro ao gerar a imagem do QR Code. Por favor, tente novamente.")
                return

            await query.edit_message_text(
                f"Você escolheu o {selected_plan['title']} no valor de R$ {selected_plan['price']:.2f}.\n\n"
                f"Para finalizar a assinatura, realize o pagamento via Pix usando o QR Code acima ou o código copia e cola abaixo."
            )

            await context.bot.send_message(
                chat_id=user_id,
                text=f"📋 *Código Pix (toque para copiar):*\n\n`{qr_code_text}`",
                parse_mode='Markdown'
            )

            await context.bot.send_message(
                chat_id=user_id,
                text="Após o pagamento, aguarde alguns minutos para a confirmação. "
                     "Você será notificado automaticamente e receberá o link do canal VIP!\n\n"
                     "Use /status para verificar a confirmação do seu pagamento."
            )
        else:
            await query.edit_message_text("Houve um erro ao gerar o pagamento. Por favor, tente novamente mais tarde.")
    else:
        await query.edit_message_text("Plano inválido selecionado.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    subscriber = get_subscriber(user_id)

    if subscriber:
        _, username, start_date, end_date, plan, status = subscriber
        end_dt = datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S")
        remaining_days = (end_dt - datetime.now()).days

        message = f"**Status da sua Assinatura VIP:**\n\n"\
                  f"Plano: {plan}\n"\
                  f"Início: {start_date}\n"\
                  f"Término: {end_date}\n"\
                  f"Dias restantes: {remaining_days} dias\n"\
                  f"Status: {status.capitalize()}\n\n"
        if status == "active":
            vip_invite_link = await generate_vip_invite_link(context)
            message += f"Você tem acesso total aos palpites VIP! Use este link de uso único para entrar: {vip_invite_link}"
        else:
            message += "Sua assinatura não está ativa. Use /assinar para renovar ou adquirir um plano."
    else:
        payment_id = context.user_data.get("current_payment_id")
        if payment_id:
            payment_status = check_payment_status(payment_id)
            if payment_status == "approved":
                selected_plan = context.user_data.get("current_plan")
                if selected_plan:
                    duration = timedelta(days=selected_plan["duration_days"])
                    end_date = (datetime.now() + duration).strftime("%Y-%m-%d %H:%M:%S")
                    add_subscriber(user_id, update.effective_user.username or update.effective_user.first_name, selected_plan["title"], end_date)
                    vip_invite_link = await generate_vip_invite_link(context)
                    await update.message.reply_text(
                        f"🎉 Parabéns! Seu pagamento foi **APROVADO**!\n\n"\
                        f"Sua assinatura **{selected_plan['title']}** está ativa.\n"\
                        f"Acesse o canal VIP com seu link exclusivo (válido por 24h): {vip_invite_link}\n\n"\
                        "Bem-vindo ao time Zeus Tips! ⚡"
                    )
                    message = "Sua assinatura foi ativada!"
                else:
                    message = "Seu pagamento foi aprovado, mas houve um erro ao ativar o plano. Entre em contato com o suporte."
            elif payment_status == "pending":
                message = "Seu pagamento está **PENDENTE** de confirmação. Por favor, aguarde ou verifique se o pagamento foi concluído.\n"\
                          "Use /assinar para gerar um novo pagamento se necessário."
            else:
                message = "Não encontramos uma assinatura ativa para você e seu último pagamento está com status: "\
                          f"**{payment_status.upper()}**. Use /assinar para adquirir um plano."
        else:
            message = "Você não possui uma assinatura ativa. Use /assinar para adquirir um plano VIP e ter acesso a todos os palpites!"

    await update.message.reply_text(message)

async def predictions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    subscriber = get_subscriber(user_id)

    if subscriber and subscriber[5] == "active":
        await update.message.reply_text("Como assinante VIP, você receberá os palpites completos diretamente no canal VIP. Fique atento às notificações!")
    else:
        today = datetime.now().strftime("%Y-%m-%d")
        fixtures_data = get_fixtures_by_date(today)
        preview_prediction_text = (
            "Aqui está uma prévia dos nossos palpites (limitado para não assinantes):\n\n"\
            "⚡ ZEUS TIPS - PRÉVIA ⚡\n"\
            "🏆 Campeonato: Exemplo de Campeonato\n"\
            "⚽ Jogo: Time da Casa vs Time Visitante\n"\
            "⏰ Horário: HH:MM BRT\n"\
            "📊 Análise: Análise resumida do jogo.\n"\
            "🎯 Palpite: Palpite (Mercado)\n"\
            "📈 Confiança: XX%\n"\
            "💰 Odd sugerida: X.XX\n\n"\
            "Para ter acesso a todos os palpites e análises completas, torne-se um membro VIP! Use /assinar."
        )

        if fixtures_data:
            fixture = fixtures_data[0]
            match_id = fixture["fixture"]["id"]
            championship = fixture["league"]["name"]
            home_team_name = fixture["teams"]["home"]["name"]
            away_team_name = fixture["teams"]["away"]["name"]
            match_time_utc = datetime.fromisoformat(fixture["fixture"]["date"].replace("Z", "+00:00"))
            match_time_brt = match_time_utc - timedelta(hours=3)

            home_team_id = fixture["teams"]["home"]["id"]
            away_team_id = fixture["teams"]["away"]["id"]
            league_id = fixture["league"]["id"]
            season = fixture["league"]["season"]

            try:
                home_team_stats = get_team_statistics(home_team_id, league_id, season)
                away_team_stats = get_team_statistics(away_team_id, league_id, season)
                h2h_stats = get_h2h_statistics(home_team_id, away_team_id)

                match_data = {
                    "championship": championship,
                    "home_team": home_team_name,
                    "away_team": away_team_name,
                    "match_time": match_time_brt.strftime("%H:%M BRT"),
                    "home_team_stats": home_team_stats,
                    "away_team_stats": away_team_stats,
                    "h2h": h2h_stats
                }

                ai_response = analyze_and_predict(match_data)

                if ai_response:
                    analysis = "N/A"
                    prediction = "N/A"
                    confidence = 0.0
                    suggested_odd = 0.0
                    market = "N/A"

                    lines = ai_response.split("\n")
                    for line in lines:
                        if "Análise:" in line: analysis = line.replace("Análise:", "").strip()
                        if "Palpite:" in line: prediction = line.replace("Palpite:", "").strip()
                        if "Confiança:" in line: confidence = float(line.replace("Confiança:", "").replace("%", "").strip()) / 100.0
                        if "Mercado:" in line: market = line.replace("Mercado:", "").strip()
                        if "Odd Sugerida:" in line: suggested_odd = float(line.replace("Odd Sugerida:", "").strip())

                    # Usar format_prediction_message para incluir classificação de odd e gestão de banca
                    pred_data = {
                        "championship": championship,
                        "team_a": home_team_name,
                        "team_b": away_team_name,
                        "match_time": match_time_brt.strftime('%H:%M BRT'),
                        "analysis": analysis,
                        "prediction": prediction,
                        "confidence": confidence,
                        "suggested_odd": suggested_odd,
                        "market": market
                    }
                    preview_prediction_text = format_prediction_message(pred_data, header="⚡ ZEUS TIPS - PRÉVIA ⚡")
                    preview_prediction_text += "\nPara ter acesso a todos os palpites e análises completas, torne-se um membro VIP! Use /assinar."
            except Exception as e:
                logger.error(f"Erro ao gerar prévia de palpite: {e}")

        await update.message.reply_text(preview_prediction_text)

# --- Funções de Automação e Admin ---

async def send_daily_predictions(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Envia palpites diários no canal VIP.
    Inclui: Classificação de Odds (M1), Gestão de Banca (M2), Múltipla Diária (M3).
    """
    logger.info("Iniciando envio diário de palpites...")
    vip_channel_id = await get_vip_channel_id_from_db()
    if not vip_channel_id:
        logger.warning("VIP_CHANNEL_ID não configurado. Palpites não serão enviados.")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    fixtures_data = get_fixtures_by_date(today)

    if not fixtures_data:
        logger.info("Nenhum jogo encontrado para hoje.")
        return

    football_fixtures = [f for f in fixtures_data if f["league"]["type"] == "league" or f["league"]["type"] == "cup"]

    # Separar jogos prioritários dos demais
    priority_fixtures = [f for f in football_fixtures if f["league"]["id"] in PRIORITY_LEAGUES]
    other_fixtures = [f for f in football_fixtures if f["league"]["id"] not in PRIORITY_LEAGUES]
    
    # Priorizar campeonatos da lista, depois os demais
    sorted_fixtures = priority_fixtures + other_fixtures
    logger.info(f"Jogos encontrados: {len(football_fixtures)} total, {len(priority_fixtures)} prioritários.")

    num_games = len(sorted_fixtures)
    predictions_to_send = 10 if num_games >= 6 else 3
    sent_count = 0
    all_predictions = []

    for fixture in sorted_fixtures:
        if len(all_predictions) >= predictions_to_send + 5:
            # Buscar um pouco mais do que o necessário para ter margem
            break

        match_id = fixture["fixture"]["id"]
        championship = fixture["league"]["name"]
        home_team_name = fixture["teams"]["home"]["name"]
        away_team_name = fixture["teams"]["away"]["name"]
        match_time_utc = datetime.fromisoformat(fixture["fixture"]["date"].replace("Z", "+00:00"))
        match_time_brt = match_time_utc - timedelta(hours=3)

        home_team_id = fixture["teams"]["home"]["id"]
        away_team_id = fixture["teams"]["away"]["id"]
        league_id = fixture["league"]["id"]
        season = fixture["league"]["season"]

        try:
            home_team_stats = get_team_statistics(home_team_id, league_id, season)
            away_team_stats = get_team_statistics(away_team_id, league_id, season)
            h2h_stats = get_h2h_statistics(home_team_id, away_team_id)
        except Exception as e:
            logger.error(f"Erro ao buscar estatísticas para {home_team_name} vs {away_team_name}: {e}")
            continue

        match_data = {
            "championship": championship,
            "home_team": home_team_name,
            "away_team": away_team_name,
            "match_time": match_time_brt.strftime("%H:%M BRT"),
            "home_team_stats": home_team_stats,
            "away_team_stats": away_team_stats,
            "h2h": h2h_stats
        }

        ai_response = analyze_and_predict(match_data)

        if ai_response:
            analysis = "N/A"
            prediction = "N/A"
            confidence = 0.0
            suggested_odd = 0.0
            market = "N/A"

            try:
                lines = ai_response.split("\n")
                for line in lines:
                    if "Análise:" in line: analysis = line.replace("Análise:", "").strip()
                    if "Palpite:" in line: prediction = line.replace("Palpite:", "").strip()
                    if "Confiança:" in line: confidence = float(line.replace("Confiança:", "").replace("%", "").strip()) / 100.0
                    if "Mercado:" in line: market = line.replace("Mercado:", "").strip()
                    if "Odd Sugerida:" in line: suggested_odd = float(line.replace("Odd Sugerida:", "").strip())
            except Exception as e:
                logger.error(f"Erro ao parsear resposta da IA para o jogo {home_team_name} vs {away_team_name}: {e}")
                continue

            all_predictions.append({
                "match_id": match_id,
                "championship": championship,
                "team_a": home_team_name,
                "team_b": away_team_name,
                "match_time": match_time_brt.strftime("%H:%M BRT"),
                "analysis": analysis,
                "prediction": prediction,
                "confidence": confidence,
                "suggested_odd": suggested_odd,
                "market": market
            })

    # Ordenar por confiança (maior primeiro)
    all_predictions.sort(key=lambda x: x["confidence"], reverse=True)

    # Enviar palpites individuais com classificação de odd e gestão de banca
    for i, pred in enumerate(all_predictions):
        if i >= predictions_to_send:
            break

        # MELHORIA 1 & 2: Usar format_prediction_message
        message_text = format_prediction_message(pred)

        try:
            await context.bot.send_message(chat_id=vip_channel_id, text=message_text)
            add_prediction_history(
                pred["match_id"], pred["championship"], pred["team_a"], pred["team_b"],
                pred["match_time"], pred["analysis"], pred["prediction"], pred["confidence"],
                pred["suggested_odd"]
            )
            sent_count += 1
            logger.info(f"Palpite enviado para {pred['team_a']} vs {pred['team_b']}")
        except Exception as e:
            logger.error(f"Erro ao enviar palpite para o canal VIP: {e}")

    # MELHORIA 3: Enviar a múltipla diária após os palpites individuais
    if len(all_predictions) >= 3:
        multiple_message = build_daily_multiple_message(all_predictions)
        if multiple_message:
            try:
                await asyncio.sleep(2)  # Pequeno delay antes de enviar a múltipla
                await context.bot.send_message(chat_id=vip_channel_id, text=multiple_message)
                logger.info("Múltipla diária enviada com sucesso.")
            except Exception as e:
                logger.error(f"Erro ao enviar múltipla diária: {e}")

    if sent_count == 0:
        logger.info("Nenhum palpite foi enviado hoje.")
    else:
        logger.info(f"Envio diário concluído. {sent_count} palpites individuais enviados.")

async def send_live_predictions(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Busca jogos ao vivo e envia palpites em tempo real para o canal VIP.
    Inclui: Classificação de Odds (M1), Gestão de Banca (M2).
    """
    logger.info("Iniciando envio de palpites ao vivo...")
    vip_channel_id = await get_vip_channel_id_from_db()
    if not vip_channel_id:
        logger.warning("VIP_CHANNEL_ID não configurado. Palpites ao vivo não serão enviados.")
        return

    live_fixtures = get_live_fixtures()
    if not live_fixtures:
        logger.info("Nenhum jogo ao vivo encontrado no momento.")
        return

    # Filtrar apenas jogos de campeonatos prioritários
    priority_live = [f for f in live_fixtures if f["league"]["id"] in PRIORITY_LEAGUES]
    
    if not priority_live:
        logger.info("Nenhum jogo ao vivo de campeonatos prioritários encontrado.")
        return

    logger.info(f"Jogos ao vivo prioritários encontrados: {len(priority_live)}")
    sent_count = 0

    for fixture in priority_live[:5]:  # Máximo 5 palpites ao vivo por vez
        match_id = fixture["fixture"]["id"]
        championship = fixture["league"]["name"]
        home_team_name = fixture["teams"]["home"]["name"]
        away_team_name = fixture["teams"]["away"]["name"]
        home_goals = fixture["goals"]["home"] or 0
        away_goals = fixture["goals"]["away"] or 0
        elapsed = fixture["fixture"]["status"]["elapsed"] or 0
        status_short = fixture["fixture"]["status"]["short"]

        # Pular jogos no intervalo ou já finalizados
        if status_short in ["HT", "FT", "AET", "PEN", "PST", "CANC", "ABD"]:
            continue

        home_team_id = fixture["teams"]["home"]["id"]
        away_team_id = fixture["teams"]["away"]["id"]
        league_id = fixture["league"]["id"]
        season = fixture["league"]["season"]

        try:
            h2h_stats = get_h2h_statistics(home_team_id, away_team_id)
        except Exception as e:
            logger.error(f"Erro ao buscar H2H para {home_team_name} vs {away_team_name}: {e}")
            h2h_stats = []

        match_data = {
            "championship": championship,
            "home_team": home_team_name,
            "away_team": away_team_name,
            "match_time": f"AO VIVO - {elapsed}'",
            "live_score": f"{home_goals} x {away_goals}",
            "home_team_stats": {"live": True, "goals": home_goals},
            "away_team_stats": {"live": True, "goals": away_goals},
            "h2h": h2h_stats
        }

        ai_response = analyze_and_predict(match_data)

        if ai_response:
            analysis = "N/A"
            prediction = "N/A"
            confidence = 0.0
            suggested_odd = 0.0
            market = "N/A"

            try:
                lines = ai_response.split("\n")
                for line in lines:
                    if "Análise:" in line: analysis = line.replace("Análise:", "").strip()
                    if "Palpite:" in line: prediction = line.replace("Palpite:", "").strip()
                    if "Confiança:" in line: confidence = float(line.replace("Confiança:", "").replace("%", "").strip()) / 100.0
                    if "Mercado:" in line: market = line.replace("Mercado:", "").strip()
                    if "Odd Sugerida:" in line: suggested_odd = float(line.replace("Odd Sugerida:", "").strip())
            except Exception as e:
                logger.error(f"Erro ao parsear resposta da IA (ao vivo) para {home_team_name} vs {away_team_name}: {e}")
                continue

            # MELHORIA 1 & 2: Usar format_live_prediction_message
            pred_data = {
                "championship": championship,
                "team_a": home_team_name,
                "team_b": away_team_name,
                "analysis": analysis,
                "prediction": prediction,
                "confidence": confidence,
                "suggested_odd": suggested_odd,
                "market": market
            }
            message_text = format_live_prediction_message(pred_data, home_goals, away_goals, elapsed)

            try:
                await context.bot.send_message(chat_id=vip_channel_id, text=message_text)
                # Salvar palpite ao vivo no histórico também
                add_prediction_history(
                    match_id, championship, home_team_name, away_team_name,
                    f"AO VIVO - {elapsed}'", analysis, prediction, confidence,
                    suggested_odd
                )
                sent_count += 1
                logger.info(f"Palpite ao vivo enviado: {home_team_name} vs {away_team_name}")
            except Exception as e:
                logger.error(f"Erro ao enviar palpite ao vivo: {e}")

        await asyncio.sleep(1)

    logger.info(f"Envio de palpites ao vivo concluído. {sent_count} palpites enviados.")

async def admin_force_send_predictions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("Você não tem permissão para usar este comando.")
        return
    await update.message.reply_text("Forçando o envio de palpites agora...")
    await send_daily_predictions(context)
    await update.message.reply_text("Envio de palpites concluído (verifique os logs para detalhes).")

async def admin_force_live_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("Você não tem permissão para usar este comando.")
        return
    await update.message.reply_text("Buscando jogos ao vivo agora...")
    await send_live_predictions(context)
    await update.message.reply_text("Envio de palpites ao vivo concluído (verifique os logs para detalhes).")

async def admin_force_check_results_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando admin para forçar verificação de resultados."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("Você não tem permissão para usar este comando.")
        return
    await update.message.reply_text("Forçando verificação de resultados...")
    await check_results(context)
    await update.message.reply_text("Verificação de resultados concluída (verifique os logs para detalhes).")

async def admin_force_summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando admin para forçar envio do resumo diário."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("Você não tem permissão para usar este comando.")
        return
    await update.message.reply_text("Forçando envio do resumo diário...")
    await send_daily_summary(context)
    await update.message.reply_text("Resumo diário enviado (verifique os logs para detalhes).")

async def admin_games_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("Você não tem permissão para usar este comando.")
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Uso: /admin_jogos YYYY-MM-DD")
        return

    date_str = context.args[0]
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text("Formato de data inválido. Use YYYY-MM-DD.")
        return

    fixtures = get_fixtures_by_date(date_str)

    if fixtures:
        message = f"Jogos encontrados para {date_str}:\n\n"
        for fixture in fixtures:
            home_team = fixture["teams"]["home"]["name"]
            away_team = fixture["teams"]["away"]["name"]
            championship = fixture["league"]["name"]
            match_time_utc = datetime.fromisoformat(fixture["fixture"]["date"].replace("Z", "+00:00"))
            match_time_brt = match_time_utc - timedelta(hours=3)
            message += f"🏆 {championship}\n⚽ {home_team} vs {away_team}\n⏰ {match_time_brt.strftime('%H:%M BRT')}\n\n"
        await update.message.reply_text(message)
    else:
        await update.message.reply_text(f"Nenhum jogo encontrado para {date_str}.")

async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Estatísticas do bot com informações de GREEN/RED (atualizado).
    """
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("Você não tem permissão para usar este comando.")
        return

    conn = sqlite3.connect("zeus_tips.db")
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM subscribers WHERE status = 'active'")
    active_subscribers = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM predictions_history")
    total_predictions = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM predictions_history WHERE result = 'green'")
    total_greens = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM predictions_history WHERE result = 'red'")
    total_reds = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM predictions_history WHERE result = 'pending'")
    total_pending = cursor.fetchone()[0]

    conn.close()

    resolved = total_greens + total_reds
    win_rate = (total_greens / resolved * 100) if resolved > 0 else 0

    message = f"**Estatísticas do Bot Zeus Tips:**\n\n"\
              f"👥 Assinantes Ativos: {active_subscribers}\n"\
              f"📋 Total de Palpites: {total_predictions}\n\n"\
              f"✅ Greens: {total_greens}\n"\
              f"❌ Reds: {total_reds}\n"\
              f"⏳ Pendentes: {total_pending}\n"\
              f"📊 Taxa de Acerto: {win_rate:.1f}%\n"

    await update.message.reply_text(message)

async def admin_setchannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("Você não tem permissão para usar este comando.")
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "Uso: /admin_setchannel [ID_numérico_do_canal]\n\n"\
            "**Como obter o ID numérico:**\n"\
            "1. Adicione o bot @userinfobot ao seu canal como administrador.\n"\
            "2. Envie qualquer mensagem no canal.\n"\
            "3. O bot responderá com as informações do canal, incluindo o ID (geralmente começa com -100...)"
        )
        return

    channel_input = context.args[0]
    try:
        # Valida se é um ID numérico de canal/supergrupo
        if channel_input.startswith('-100') and channel_input[1:].isdigit():
            vip_channel_id = int(channel_input)
            set_setting("VIP_CHANNEL_ID", str(vip_channel_id))
            await update.message.reply_text(f"Canal VIP configurado com sucesso para o ID: `{vip_channel_id}`")
        else:
            raise ValueError("ID de canal inválido")
    except (ValueError, TypeError):
        await update.message.reply_text(
            "Formato de ID de canal inválido. O ID deve ser um número inteiro, geralmente começando com -100. "\
            "Siga as instruções em /admin_setchannel para obter o ID correto."
        )

async def check_vip_members(context: ContextTypes.DEFAULT_TYPE):
    logger.info("PROTEÇÃO 2: Iniciando verificação periódica de membros no canal VIP...")
    vip_channel_id = await get_vip_channel_id_from_db()
    if not vip_channel_id:
        logger.error("PROTEÇÃO 2: Verificação de membros abortada. VIP_CHANNEL_ID numérico não configurado.")
        return

    all_subscribers = get_all_subscribers()
    active_subscriber_ids = {sub[0] for sub in all_subscribers if sub[1] == 'active'}

    for user_id, db_status in all_subscribers:
        # Nunca remover o admin do bot
        if user_id == ADMIN_USER_ID:
            continue

        try:
            chat_member = await context.bot.get_chat_member(chat_id=vip_channel_id, user_id=user_id)
            is_in_channel = chat_member.status in ["member", "administrator", "creator"]

            # Cenário: Usuário está no canal, mas não tem assinatura ativa no DB
            if is_in_channel and user_id not in active_subscriber_ids:
                logger.info(f"PROTEÇÃO 2: Removendo usuário {user_id} do canal VIP. Status no DB: '{db_status}', Status no Canal: '{chat_member.status}'.")
                await context.bot.ban_chat_member(chat_id=vip_channel_id, user_id=user_id)
                await context.bot.unban_chat_member(chat_id=vip_channel_id, user_id=user_id)
                logger.info(f"PROTEÇÃO 2: Usuário {user_id} banido e desbanido para permitir reentrada futura.")

        except Exception as e:
            # Ignora erros de "user not found", que são comuns para usuários que saíram
            if "user not found" in str(e).lower():
                logger.debug(f"PROTEÇÃO 2: Usuário {user_id} não encontrado no canal VIP (provavelmente já saiu).")
            else:
                logger.error(f"PROTEÇÃO 2: Erro ao verificar/remover membro {user_id} do canal {vip_channel_id}: {e}")
        
        await asyncio.sleep(1)

    logger.info("PROTEÇÃO 2: Verificação de membros do canal VIP concluída.")

# --- Agendamento de Tarefas com Job Queue ---

async def setup_jobs(application: Application) -> None:
    job_queue = application.job_queue
    
    # Agendar envio diário de palpites para 12:00 BRT (15:00 UTC) - todos os dias
    job_queue.run_daily(
        send_daily_predictions,
        time=time(hour=15, minute=0),
        name="send_daily_predictions_12h"
    )
    logger.info("Agendamento diário de palpites configurado para 12:00 BRT (15:00 UTC).")

    # Agendar envio extra aos sábados e domingos às 09:00 BRT (12:00 UTC)
    job_queue.run_daily(
        send_daily_predictions,
        time=time(hour=12, minute=0),
        days=(5, 6),  # 5=Sábado, 6=Domingo
        name="send_daily_predictions_09h_weekend"
    )
    logger.info("Agendamento extra de palpites aos sábados e domingos às 09:00 BRT (12:00 UTC).")

    # Agendar verificação de expiração de assinaturas a cada 6 horas
    job_queue.run_repeating(
        check_subscriptions_expiration,
        interval=6 * 3600,
        first=0,
        name="check_subscriptions_expiration"
    )
    logger.info("Agendamento de verificação de expiração de assinaturas configurado a cada 6 horas.")

    # Agendar verificação de membros do canal VIP a cada 6 horas
    job_queue.run_repeating(
        check_vip_members,
        interval=6 * 3600,
        first=60,
        name="check_vip_members"
    )
    logger.info("PROTEÇÃO 2: Agendamento de verificação de membros do canal VIP configurado a cada 6 horas.")

    # Agendar palpites ao vivo a cada 2 horas (busca jogos em andamento)
    job_queue.run_repeating(
        send_live_predictions,
        interval=2 * 3600,
        first=300,  # Começa 5 minutos após iniciar
        name="send_live_predictions"
    )
    logger.info("Agendamento de palpites ao vivo configurado a cada 2 horas.")

    # MELHORIA 4: Agendar verificação de resultados a cada 3 horas
    job_queue.run_repeating(
        check_results,
        interval=3 * 3600,
        first=600,  # Começa 10 minutos após iniciar
        name="check_results"
    )
    logger.info("MELHORIA 4: Agendamento de verificação de resultados configurado a cada 3 horas.")

    # MELHORIA 5: Agendar resumo diário para 23:00 BRT (02:00 UTC do dia seguinte)
    job_queue.run_daily(
        send_daily_summary,
        time=time(hour=2, minute=0),
        name="send_daily_summary_23h"
    )
    logger.info("MELHORIA 5: Agendamento de resumo diário configurado para 23:00 BRT (02:00 UTC).")

async def post_init(application: Application) -> None:
    await setup_jobs(application)

# --- Main --- 

def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Comandos de usuário
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("assinar", subscribe_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("palpites", predictions_command))

    # Callback para botões inline
    application.add_handler(CallbackQueryHandler(button_callback_handler))

    # Comandos de administração
    application.add_handler(CommandHandler("admin_forcar_envio", admin_force_send_predictions_command))
    application.add_handler(CommandHandler("admin_jogos", admin_games_command))
    application.add_handler(CommandHandler("admin_estatisticas", admin_stats_command))
    application.add_handler(CommandHandler("admin_setchannel", admin_setchannel_command))
    application.add_handler(CommandHandler("admin_aovivo", admin_force_live_command))
    application.add_handler(CommandHandler("admin_verificar_resultados", admin_force_check_results_command))
    application.add_handler(CommandHandler("admin_resumo", admin_force_summary_command))

    # Iniciar o bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

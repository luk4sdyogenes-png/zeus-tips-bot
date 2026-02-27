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

from api_integrations import get_fixtures_by_date, get_team_statistics, get_h2h_statistics, analyze_and_predict, create_payment, check_payment_status
from database import init_db, get_setting, set_setting, add_subscriber, get_subscriber, update_subscriber_status, get_all_active_subscribers, add_prediction_history

# Carregar variáveis de ambiente (override=False evita sobrescrever variáveis já definidas no Railway)
load_dotenv(override=False)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID")) if os.getenv("ADMIN_USER_ID") else None
VIP_CHANNEL_ID_ENV = os.getenv("VIP_CHANNEL_ID")  # Fallback para variável de ambiente

# Configurar logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Inicializar o banco de dados
init_db()

# --- Funções Auxiliares ---

async def get_vip_channel_id_from_db():
    """
    Obtém o VIP_CHANNEL_ID do banco de dados.
    Se não estiver no banco, usa a variável de ambiente como fallback.
    Isso garante que o canal VIP não se perca em redeploys no Railway.
    """
    vip_channel_id = get_setting("VIP_CHANNEL_ID")
    
    # Se não estiver no banco, tenta usar a variável de ambiente
    if not vip_channel_id and VIP_CHANNEL_ID_ENV:
        logger.info("VIP_CHANNEL_ID não encontrado no banco. Usando variável de ambiente como fallback.")
        vip_channel_id = VIP_CHANNEL_ID_ENV
        # Opcionalmente, salva no banco para futuras consultas
        set_setting("VIP_CHANNEL_ID", vip_channel_id)
    
    return vip_channel_id

async def generate_vip_invite_link(context: ContextTypes.DEFAULT_TYPE):
    vip_channel_id = await get_vip_channel_id_from_db()
    if not vip_channel_id:
        logger.error("VIP_CHANNEL_ID não configurado no banco de dados nem em variáveis de ambiente.")
        return "#ERRO_CANAL_VIP_NAO_CONFIGURADO"
    
    # Limpa espaços extras
    vip_channel_id = vip_channel_id.strip()
    
    # Se já for um link completo do Telegram, retorna direto
    if vip_channel_id.startswith("https://t.me/"):
        return vip_channel_id
    elif vip_channel_id.startswith("t.me/"):
        return f"https://{vip_channel_id}"
    elif vip_channel_id.startswith("+"):
        return f"https://t.me/{vip_channel_id}"
    else:
        return f"https://t.me/+{vip_channel_id}"

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
        "/admin_setchannel [link_do_canal_VIP] - Configurar o link do canal VIP"
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
        "plan_vitalicio": {"title": "Plano Vitalício", "price": 197.00, "duration_days": 36500}, # Aproximadamente 100 anos
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
            message += f"Você tem acesso total aos palpites VIP! Acesse: {vip_invite_link}"
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
                        f"Acesse o canal VIP agora: {vip_invite_link}\n\n"\
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

    if subscriber and subscriber[5] == "active": # subscriber[5] é o status
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
            match_time_brt = match_time_utc - timedelta(hours=3) # Ajustar para BRT (GMT-3)

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

                    preview_prediction_text = f"⚡ ZEUS TIPS - PRÉVIA ⚡\n"
                    preview_prediction_text += f"🏆 Campeonato: {championship}\n"
                    preview_prediction_text += f"⚽ Jogo: {home_team_name} vs {away_team_name}\n"
                    preview_prediction_text += f"⏰ Horário: {match_time_brt.strftime('%H:%M BRT')}\n"
                    preview_prediction_text += f"📊 Análise: {analysis}\n"
                    preview_prediction_text += f"🎯 Palpite: {prediction} ({market})\n"
                    preview_prediction_text += f"📈 Confiança: {confidence * 100:.0f}%\n"
                    preview_prediction_text += f"💰 Odd sugerida: {suggested_odd:.2f}\n\n"
                    preview_prediction_text += "Para ter acesso a todos os palpites e análises completas, torne-se um membro VIP! Use /assinar."
            except Exception as e:
                logger.error(f"Erro ao gerar prévia de palpite: {e}")

        await update.message.reply_text(preview_prediction_text)

# --- Funções de Automação e Admin ---

async def send_daily_predictions(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Iniciando envio diário de palpites...")
    vip_channel_id = await get_vip_channel_id_from_db()
    if not vip_channel_id:
        logger.warning("VIP_CHANNEL_ID não configurado no banco de dados nem em variáveis de ambiente. Palpites não serão enviados.")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    fixtures_data = get_fixtures_by_date(today)

    if not fixtures_data:
        logger.info("Nenhum jogo encontrado para hoje.")
        return

    football_fixtures = [f for f in fixtures_data if f["league"]["type"] == "league" or f["league"]["type"] == "cup"]

    num_games = len(football_fixtures)
    predictions_to_send = 10 if num_games >= 6 else 3
    sent_count = 0
    all_predictions = []

    for fixture in football_fixtures:
        if sent_count >= predictions_to_send:
            break

        match_id = fixture["fixture"]["id"]
        championship = fixture["league"]["name"]
        home_team_name = fixture["teams"]["home"]["name"]
        away_team_name = fixture["teams"]["away"]["name"]
        match_time_utc = datetime.fromisoformat(fixture["fixture"]["date"].replace("Z", "+00:00"))
        match_time_brt = match_time_utc - timedelta(hours=3) # Ajustar para BRT (GMT-3)

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
                "market": market # Adicionar mercado para exibição
            })

    all_predictions.sort(key=lambda x: x["confidence"], reverse=True)

    for i, pred in enumerate(all_predictions):
        if i >= predictions_to_send:
            break

        message_text = f"⚡ ZEUS TIPS - PALPITE DO DIA ⚡\n"
        message_text += f"🏆 Campeonato: {pred['championship']}\n"
        message_text += f"⚽ Jogo: {pred['team_a']} vs {pred['team_b']}\n"
        message_text += f"⏰ Horário: {pred['match_time']}\n"
        message_text += f"📊 Análise: {pred['analysis']}\n"
        message_text += f"🎯 Palpite: {pred['prediction']} ({pred['market']})\n"
        message_text += f"📈 Confiança: {pred['confidence'] * 100:.0f}%\n"
        message_text += f"💰 Odd sugerida: {pred['suggested_odd']:.2f}\n"

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

    if sent_count == 0:
        logger.info("Nenhum palpite foi enviado hoje.")

async def admin_force_send_predictions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("Você não tem permissão para usar este comando.")
        return
    await update.message.reply_text("Forçando o envio de palpites agora...")
    await send_daily_predictions(context)
    await update.message.reply_text("Envio de palpites concluído (verifique os logs para detalhes).")

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

    await update.message.reply_text(f"Buscando jogos para a data: {date_str}...")
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
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("Você não tem permissão para usar este comando.")
        return

    conn = sqlite3.connect("zeus_tips.db")
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM subscribers WHERE status = 'active'")
    active_subscribers = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM predictions_history")
    total_predictions = cursor.fetchone()[0]

    conn.close()

    message = f"**Estatísticas do Bot Zeus Tips:**\n\n"\
              f"Assinantes Ativos: {active_subscribers}\n"\
              f"Total de Palpites Enviados: {total_predictions}\n"

    await update.message.reply_text(message)

async def admin_setchannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("Você não tem permissão para usar este comando.")
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Uso: /admin_setchannel [link_do_canal_VIP ou ID do canal]")
        return

    channel_input = context.args[0]
    # Tenta extrair o hash do link de convite ou usa o input diretamente como ID
    match = re.search(r"t.me/\+([a-zA-Z0-9_-]+)", channel_input)
    if match:
        vip_channel_id = match.group(1)
    elif channel_input.startswith("-100") and channel_input[1:].isdigit(): # Verifica se é um ID numérico de canal
        vip_channel_id = channel_input
    else:
        await update.message.reply_text("Formato de link ou ID de canal inválido. Use um link de convite (ex: t.me/+hash) ou o ID numérico do canal (ex: -1001234567890).")
        return

    set_setting("VIP_CHANNEL_ID", vip_channel_id)
    await update.message.reply_text(f"Canal VIP configurado com sucesso para: `{vip_channel_id}`")

# --- Agendamento de Tarefas com Job Queue ---

async def setup_jobs(application: Application) -> None:
    """Configura os jobs de agendamento usando o job_queue nativo do python-telegram-bot v20+"""
    job_queue = application.job_queue
    
    # Agendar envio diário de palpites para 12:00 BRT (15:00 UTC)
    job_queue.run_daily(
        send_daily_predictions,
        time=time(hour=15, minute=0),  # 15:00 UTC = 12:00 BRT (GMT-3)
        name="send_daily_predictions"
    )
    logger.info("Agendamento diário de palpites configurado para 12:00 BRT (15:00 UTC).")

    # Agendar verificação de expiração de assinaturas a cada 6 horas
    job_queue.run_repeating(
        check_subscriptions_expiration,
        interval=6 * 3600,  # 6 horas em segundos
        first=0,
        name="check_subscriptions_expiration"
    )
    logger.info("Agendamento de verificação de expiração de assinaturas configurado a cada 6 horas.")

async def post_init(application: Application) -> None:
    """Callback executado após a inicialização da aplicação"""
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

    # Iniciar o bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

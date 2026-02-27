# Zeus Tips Bot

Um bot para Telegram que funciona como um canal automatizado de palpites esportivos de futebol, utilizando integração com API-Football, análise de IA via OpenAI e sistema de assinatura com Pix via Mercado Pago.

## Funcionalidades

- **Coleta de dados esportivos**: Integração com API-Football para buscar jogos, estatísticas de times, confrontos diretos, etc.
- **Análise com IA**: Utiliza OpenAI (modelo `gpt-4.1-mini`) para analisar dados e gerar palpites com confiança, mercado e odds sugeridas.
- **Envio automático de palpites**: Envia palpites para o canal VIP em horários programados, priorizando os de maior confiança.
- **Formato profissional das mensagens**: Mensagens bem estruturadas e informativas no canal.
- **Sistema de assinatura com Pix via Mercado Pago**: Planos mensal, trimestral e vitalício com geração automática de QR Code Pix, verificação de pagamento e gerenciamento de acesso ao canal VIP.
- **Comandos do bot**: `/start`, `/palpites`, `/assinar`, `/status`, `/ajuda`.
- **Painel de gerenciamento (admin)**: Comandos para indicar jogos, forçar envio de palpites e ver estatísticas do bot.

## Instalação e Configuração

Siga os passos abaixo para configurar e executar o Zeus Tips Bot.

### 1. Pré-requisitos

- Python 3.8 ou superior
- Uma conta no Telegram e um bot criado via BotFather (obtenha o `TELEGRAM_BOT_TOKEN`).
- Uma conta na API-Football (obtenha a `API_FOOTBALL_KEY`).
- Uma conta na OpenAI (a `OPENAI_API_KEY` já está configurada no ambiente, mas você pode precisar configurá-la no `.env`).
- Uma conta no Mercado Pago para processar pagamentos (obtenha o `MERCADOPAGO_ACCESS_TOKEN`).
- Um canal VIP no Telegram para o bot enviar os palpites (obtenha o `VIP_CHANNEL_ID` - o hash do link de convite).

### 2. Configuração do Ambiente

1. **Clone o repositório (ou crie a estrutura de pastas):**
   ```bash
   mkdir -p /home/ubuntu/zeus-tips-bot
   cd /home/ubuntu/zeus-tips-bot
   ```

2. **Crie o arquivo `.env`:**
   Copie o conteúdo de `.env.example` para um novo arquivo chamado `.env` na raiz do projeto e preencha com suas credenciais:
   ```bash
   cp .env.example .env
   ```

   Edite o arquivo `.env` e preencha as variáveis:
   ```
   TELEGRAM_BOT_TOKEN=SEU_TELEGRAM_BOT_TOKEN
   ADMIN_USER_ID=SEU_ID_DE_USUARIO_TELEGRAM # ID numérico do seu usuário Telegram
   API_FOOTBALL_KEY=SUA_API_FOOTBALL_KEY
   MERCADOPAGO_ACCESS_TOKEN=SEU_MERCADOPAGO_ACCESS_TOKEN
   OPENAI_API_KEY=SUA_OPENAI_API_KEY # Geralmente já configurada no ambiente
   VIP_CHANNEL_ID=SEU_VIP_CHANNEL_INVITE_HASH # Ex: ABCdefGHIjklMNOpqrSTUvwxYz
   ```
   **Importante**: Para `VIP_CHANNEL_ID`, você precisa criar um link de convite para o seu canal VIP no Telegram e usar o hash (a parte final do link, após `t.me/+`).

### 3. Instalação das Dependências

Certifique-se de estar no diretório `/home/ubuntu/zeus-tips-bot` e instale as dependências usando `pip`:

```bash
python3 -m pip install -r requirements.txt
```

### 4. Inicialização do Banco de Dados

O bot utiliza SQLite para armazenar dados de assinantes e histórico de palpites. Execute o script `database.py` para criar o banco de dados:

```bash
python3 database.py
```

Isso criará o arquivo `zeus_tips.db` no diretório do projeto.

### 5. Executando o Bot

Para iniciar o bot, execute o arquivo `bot.py`:

```bash
python3 bot.py
```

O bot começará a escutar por comandos e os agendamentos diários serão configurados.

## Estrutura do Projeto

```
zeus-tips-bot/
├── .env.example
├── README.md
├── api_integrations.py
├── bot.py
├── database.py
├── requirements.txt
└── scheduler.py
```

- `bot.py`: Lógica principal do bot, comandos, handlers e integração com o scheduler.
- `api_integrations.py`: Funções para interagir com as APIs de terceiros (API-Football, OpenAI, Mercado Pago).
- `database.py`: Funções para inicializar e interagir com o banco de dados SQLite.
- `scheduler.py`: Lógica para agendamento de tarefas em segundo plano.
- `requirements.txt`: Lista de dependências Python.
- `.env.example`: Exemplo das variáveis de ambiente necessárias.
- `README.md`: Este arquivo.

## Notas Importantes

- **Webhook do Mercado Pago**: A integração com Mercado Pago (`api_integrations.py`) inclui um placeholder para `notification_url`. Em um ambiente de produção, você precisaria configurar um webhook real para receber notificações de pagamento e automatizar a ativação de assinaturas de forma mais robusta.
- **Remoção de Membros do Canal VIP**: A API do Telegram não permite que bots removam membros de canais privados diretamente. A lógica de expiração de assinatura apenas notifica o usuário. A remoção de membros expirados precisaria ser feita manualmente pelo administrador ou através de uma API de usuário (que está fora do escopo deste bot).
- **Geração de Link de Convite**: Para canais privados, o `VIP_CHANNEL_ID` deve ser o hash do link de convite gerado manualmente pelo administrador do canal. O bot não pode gerar esses links diretamente.

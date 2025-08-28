# olt_monitoring_system/config.py
# Este arquivo centraliza as configurações da aplicação, como as configurações de log,
# os detalhes de conexão com o banco de dados e a lista de equipamentos OLT a serem monitorados.

# --- Bloco de Importações ---
# Importação do módulo logging para configurar e usar o sistema de logs da aplicação
import logging

# Importação do módulo os para interagir com o sistema operacional
# Embora não seja utilizado diretamente neste arquivo, é uma boa prática tê-lo disponível
# para possíveis expansões futuras que possam requerer interação com o sistema de arquivos
import os

# --- Configuração do Logging ---
# Configuração do sistema de logs da aplicação
# Esta seção define como as mensagens de log serão formatadas, filtradas e exibidas
# O logging é essencial para depuração, monitoramento e auditoria da aplicação
logging.basicConfig(
    # Define o nível mínimo de severidade para as mensagens que serão registradas
    # logging.INFO captura mensagens de nível INFO, WARNING, ERROR e CRITICAL
    # Mensagens de nível DEBUG serão ignoradas
    level=logging.INFO,
    
    # Define o formato de cada mensagem de log
    # %(asctime)s: Data e hora do evento no formato YYYY-MM-DD HH:MM:SS,mmm
    # %(levelname)s: Nível da mensagem (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    # %(message)s: A mensagem de log em si
    format='%(asctime)s - %(levelname)s - %(message)s',
    
    # Define os destinos para onde as mensagens de log serão enviadas
    # Pode ser um ou mais handlers, como arquivo, console, email, etc.
    handlers=[
        # Handler para enviar os logs para um arquivo chamado 'olt_monitoring_debug.log'
        # Este arquivo será criado no mesmo diretório onde a aplicação está sendo executada
        # Útil para análise posterior e histórico de eventos
        logging.FileHandler('olt_monitoring_debug.log'),
        
        # Handler para enviar os logs também para o console (terminal)
        # Permite acompanhamento em tempo real durante o desenvolvimento e operação
        logging.StreamHandler()
    ]
)

# --- Configuração do Banco de Dados PostgreSQL ---
# Dicionário contendo todas as informações necessárias para se conectar ao banco de dados PostgreSQL
# Centralizar essas configurações facilita a manutenção e alteração sem modificar o código-fonte
DB_CONFIG = {
    'host': 'localhost',        # Endereço do servidor do banco de dados.
    'database': 'olt_monitoring', # Nome do banco de dados a ser utilizado.
    'user': 'olt_user',         # Nome do usuário para autenticação.
    'password': 'gigamatriz',   # Senha do usuário.
    'port': '5432',              # Porta padrão do PostgreSQL.
    'client_encoding': 'latin1'  # --- LINHA ADICIONADA PARA CORRIGIR O ERRO DE DECODIFICAÇÃO ---
}

# --- MODIFICAÇÃO: Lista de OLTs definida diretamente no código ---
# Lista de dicionários contendo as configurações dos equipamentos OLT a serem monitorados
# Cada dicionário representa uma OLT com suas propriedades de conexão
# Esta abordagem simplifica a configuração inicial, eliminando a necessidade de arquivos externos
OLT_CONFIGS = [
    # Configuração da OLT BURITI-95
    # name: Nome identificador da OLT
    # ip: Endereço IP para conexão via SSH/Telnet
    # username: Nome de usuário para autenticação
    # password: Senha para autenticação
    {'name': 'BURITI-95', 'ip': '10.0.0.95', 'username': 'huawei', 'password': 'ccmsai13'},
    
    # Configuração da OLT CARMO-93
    {'name': 'CARMO-93', 'ip': '10.0.0.93', 'username': 'huawei', 'password': 'ccmsai13'},
    
    # Configuração da OLT CERES-96
    {'name': 'CERES-96', 'ip': '10.0.0.96', 'username': 'huawei', 'password': 'ccmsai13'},
    
    # Configuração da OLT GOIANIA-98
    {'name': 'GOIANIA-98', 'ip': '10.0.0.98', 'username': 'huawei', 'password': 'ccmsai13'},
    
    # Configuração da OLT JARAGUA-99
    {'name': 'JARAGUA-99', 'ip': '10.0.0.99', 'username': 'huawei', 'password': 'ccmsai13'},
    
    # Configuração da OLT JARAGUA-XGPON-88
    {'name': 'JARAGUA-XGPON-88', 'ip': '10.0.0.88', 'username': 'huawei', 'password': 'ccmsai13'},
    
    # Configuração da OLT NOVAGLORIA-89
    {'name': 'NOVAGLORIA-89', 'ip': '10.0.0.89', 'username': 'huawei', 'password': 'ccmsai13'},
    
    # Configuração da OLT RIALMA-97
    {'name': 'RIALMA-97', 'ip': '10.0.0.97', 'username': 'huawei', 'password': 'ccmsai13'},
    
    # Configuração da OLT RIANAPOLIS-94
    {'name': 'RIANAPOLIS-94', 'ip': '10.0.0.94', 'username': 'huawei', 'password': 'ccmsai13'},
    
    # Configuração da OLT SAOXICO-90
    {'name': 'SAOXICO-90', 'ip': '10.0.0.90', 'username': 'huawei', 'password': 'ccmsai13'},
    
    # Configuração da OLT SAOXICO-XGPON-87
    {'name': 'SAOXICO-XGPON-87', 'ip': '10.0.0.87', 'username': 'huawei', 'password': 'ccmsai13'},
    
    # Configuração da OLT URUACU-91
    {'name': 'URUACU-91', 'ip': '10.0.0.91', 'username': 'huawei', 'password': 'ccmsai13'},
    
    # Configuração da OLT URUANA-92
    {'name': 'URUANA-92', 'ip': '10.0.0.92', 'username': 'huawei', 'password': 'ccmsai13'},
]

# --- Função para Acessar as Configurações das OLTs ---
def get_olt_configs():
    """
    Retorna a lista de configurações das OLTs definida estaticamente.
    
    Esta função foi criada para substituir a antiga lógica de carregar configurações
    de um arquivo externo (como um CSV), mantendo a compatibilidade com o resto do código
    que espera chamar uma função para obter essa lista.
    
    Returns:
        list: Lista de dicionários contendo as configurações de cada OLT.
              Cada dicionário contém as chaves: 'name', 'ip', 'username', 'password'.
    """
    # Registra no log uma mensagem informativa indicando quantas OLTs foram carregadas
    # Isso ajuda a verificar se todas as configurações foram corretamente processadas
    logging.info(f"{len(OLT_CONFIGS)} OLTs carregadas da configuração estática.")
    
    # Retorna a lista completa de configurações das OLTs
    return OLT_CONFIGS

# Mensagem de log para indicar que este arquivo de configuração foi carregado com sucesso
# quando a aplicação inicia. Isso serve como confirmação de que as configurações básicas
# (banco de dados e OLTs) estão disponíveis para o restante da aplicação
logging.info("Configurações carregadas: DB_CONFIG e OLT_CONFIGS.")
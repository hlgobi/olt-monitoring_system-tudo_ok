# -*- coding: utf-8 -*-

# ==============================================================================
# ARQUIVO DE CONFIGURAÇÃO DA APLICAÇÃO
# ==============================================================================
# Este arquivo centraliza todas as configurações da aplicação OLT Monitoring System,
# incluindo as configurações de logging, detalhes de conexão com o banco de dados
# e a lista de equipamentos OLT a serem monitorados.
#
# A centralização das configurações facilita a manutenção e permite alterações
# sem a necessidade de modificar o código-fonte principal da aplicação.

# ==============================================================================
# IMPORTAÇÕES DE MÓDULOS
# ==============================================================================
import logging  # Módulo para configuração e uso do sistema de logs da aplicação
import os  # Módulo para interações com o sistema operacional (disponível para expansões futuras)

# ==============================================================================
# CONFIGURAÇÃO DO SISTEMA DE LOGGING
# ==============================================================================
# Configuração do sistema de logs da aplicação, essencial para depuração,
# monitoramento e auditoria das operações realizadas.
logging.basicConfig(
    # Define o nível mínimo de severidade para as mensagens que serão registradas
    # Nível INFO: captura mensagens informativas, avisos, erros e críticos
    # Mensagens de nível DEBUG serão ignoradas neste ambiente
    level=logging.INFO,
    
    # Define o formato de cada mensagem de log, incluindo timestamp, nível e mensagem
    # %(asctime)s: Data e hora do evento no formato YYYY-MM-DD HH:MM:SS,mmm
    # %(levelname)s: Nível da mensagem (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    # %(message)s: A mensagem de log em si
    format='%(asctime)s - %(levelname)s - %(message)s',
    
    # Define os destinos para onde as mensagens de log serão enviadas
    handlers=[
        # Handler para envio dos logs para arquivo
        # Cria um arquivo 'olt_monitoring_debug.log' no diretório de execução
        # Útil para análise posterior e histórico de eventos
        logging.FileHandler('olt_monitoring_debug.log'),
        
        # Handler para envio dos logs também para o console (terminal)
        # Permite acompanhamento em tempo real durante desenvolvimento e operação
        logging.StreamHandler()
    ]
)

# ==============================================================================
# CONFIGURAÇÃO DO BANCO DE DADOS POSTGRESQL
# ==============================================================================
# Dicionário contendo todas as informações necessárias para se conectar ao banco
# de dados PostgreSQL. Centralizar essas configurações facilita a manutenção e
# permite alterações sem modificar o código-fonte da aplicação.
DB_CONFIG = {
    'host': '177.8.200.12',
    'database': 'Olt',
    'user': 'olt_user132',
    'password': 'yQAZgvodsWSDm25671&&&',
    'port': '5432'
}

# ==============================================================================
# CONFIGURAÇÃO DOS EQUIPAMENTOS OLT
# ==============================================================================
# Lista de dicionários contendo as configurações dos equipamentos OLT a serem monitorados.
# Cada dicionário representa uma OLT com suas propriedades de conexão.
# Esta abordagem simplifica a configuração inicial, eliminando a necessidade de
# arquivos externos para armazenar estas informações.
OLT_CONFIGS = [
    # Configuração da OLT BURITI-95
    # name: Nome identificador da OLT (usado para referências internas e exibição na GUI)
    # ip: Endereço IP para conexão via SSH/Telnet
    # username: Nome de usuário para autenticação no equipamento
    # password: Senha para autenticação no equipamento
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

# ==============================================================================
# FUNÇÕES DE ACESSO ÀS CONFIGURAÇÕES
# ==============================================================================

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

# ==============================================================================
# INICIALIZAÇÃO E VERIFICAÇÃO DAS CONFIGURAÇÕES
# ==============================================================================
# Mensagem de log para indicar que este arquivo de configuração foi carregado com sucesso
# quando a aplicação inicia. Isso serve como confirmação de que as configurações básicas
# (banco de dados e OLTs) estão disponíveis para o restante da aplicação
logging.info("Configurações carregadas: DB_CONFIG e OLT_CONFIGS.")
# main.py
import sys
import logging
import signal
import os
import psycopg2  # Importação necessária para check_postgresql_timezone
from datetime import datetime
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
from gui.main_window import OLTDatabaseGUI
from db.connection import create_tables, check_db_connection
from gui.signals import db_signals

# NOVO: Buffer para armazenar logs iniciais antes da GUI estar pronta
initial_logs = []


class BufferHandler(logging.Handler):
    """Handler que armazena logs em um buffer para exibição posterior."""
    def __init__(self, buffer):
        super().__init__()
        self.buffer = buffer
        
    def emit(self, record):
        """Adiciona a mensagem formatada ao buffer."""
        self.buffer.append(self.format(record))

class GuiLogHandler(logging.Handler):
    """Handler que envia logs para a GUI via sinais."""
    def __init__(self):
        super().__init__()
        # O formato será adicionado diretamente na mensagem para incluir a categoria
        formatter = logging.Formatter('%(asctime)s - %(message)s', datefmt='%H:%M:%S')
        self.setFormatter(formatter)
        
    def emit(self, record):
        """Envia a mensagem formatada via sinal."""
        try:
            msg = self.format(record)
            db_signals.log_message.emit(msg)
        except Exception:
            self.handleError(record)

def setup_logging():
    """Configura o sistema de logging com múltiplos handlers (console, arquivo, GUI)."""
    # Formato para console e arquivo
    log_formatter = logging.Formatter('%(asctime)s - %(message)s', datefmt='%H:%M:%S')

    # Configurar o logger raiz
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # Nível DEBUG para capturar tudo

    # Limpar handlers existentes para evitar duplicação
    if logger.hasHandlers():
        logger.handlers.clear()

    # 1. Handler para o Console (nível INFO)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(logging.INFO) # Mostra apenas INFO e acima no console
    logger.addHandler(console_handler)

    # 2. Handler para o Arquivo (nível DEBUG)
    # Cria um diretório 'logs' se não existir
    if not os.path.exists('logs'):
        os.makedirs('logs')
    file_handler = logging.FileHandler(f"logs/olt_monitor_{datetime.now().strftime('%Y%m%d')}.log", 'a', 'utf-8')
    file_handler.setFormatter(log_formatter)
    file_handler.setLevel(logging.DEBUG) # Salva tudo (incluindo [PARSE]) no arquivo
    logger.addHandler(file_handler)
    
    return logger

def check_postgresql_timezone():
    """Verifica e define o fuso horário do PostgreSQL"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            # Verifica o fuso horário atual
            cursor.execute("SHOW timezone;")
            current_tz = cursor.fetchone()[0]
            logging.info(f"Fuso horário atual do PostgreSQL: {current_tz}")
            
            # Define o fuso horário correto se necessário
            if current_tz != 'America/Sao_Paulo':
                cursor.execute("SET TIME ZONE 'America/Sao_Paulo';")
                cursor.execute("SHOW timezone;")
                new_tz = cursor.fetchone()[0]
                logging.info(f"Fuso horário do PostgreSQL alterado para: {new_tz}")
                
                # Torna a alteração permanente para a sessão
                cursor.execute("ALTER DATABASE Olt SET timezone TO 'America/Sao_Paulo';")
                logging.info("Fuso horário definido permanentemente para o banco de dados")
    except Exception as e:
        logging.error(f"Erro ao verificar/definir fuso horário do PostgreSQL: {e}")
    finally:
        if conn:
            conn.close()

def main():
    """
    Ponto de entrada principal da aplicação.
    
    Esta função inicializa a aplicação, verifica a conexão com o banco de dados,
    cria as tabelas necessárias e inicia a interface gráfica.
    """
    
    # Configurar handler de buffer para capturar logs iniciais
    buffer_handler = BufferHandler(initial_logs)
    logging.getLogger().addHandler(buffer_handler)
    
    # Registrar início da aplicação no log
    logging.info("[SYSTEM] Iniciando a aplicação OLT Monitoring System.")
    
    
    # Registrar uma mensagem informativa no log indicando o início da verificação do banco de dados
    logging.info("[SYSTEM] Verificando conexão com o banco de dados...")
    
    # Verifica a conexão com o banco de dados
    if not check_db_connection():
        logging.critical("[SYSTEM] Falha crítica ao conectar com o banco de dados. A aplicação será encerrada.")
        sys.exit(1)
    
    # Registrar uma mensagem informativa no log indicando que a conexão foi bem-sucedida
    logging.info("[SYSTEM] Conexão com o banco de dados verificada com sucesso.")
    
    # Registrar uma mensagem informativa no log indicando o início da verificação das tabelas
    logging.info("[SYSTEM] Verificando e criando tabelas se necessário...")
    
    # Verifica e cria as tabelas do banco de dados
    if not create_tables():
        logging.critical("[SYSTEM] Falha crítica ao criar/verificar tabelas do banco de dados. A aplicação será encerrada.")
        sys.exit(1)
    
    # Registrar uma mensagem informativa no log indicando que as tabelas foram verificadas/criadas com sucesso
    logging.info("[SYSTEM] Tabelas verificadas/criadas com sucesso.")
    
    # Criar instância do QApplication
    app = QApplication(sys.argv)
    
    # Instancia a janela principal da aplicação
    main_window = OLTDatabaseGUI()
    
    # Armazenar logs iniciais na janela principal para exibição posterior
    main_window.initial_logs = initial_logs
    
    # Conectar o sinal global de logs ao método da janela principal
    db_signals.log_message.connect(main_window.log_to_gui)
    
    # Criar e adicionar o handler de GUI ao logger
    gui_handler = GuiLogHandler()
    gui_handler.setLevel(logging.INFO) # A GUI mostrará INFO e acima
    logging.getLogger().addHandler(gui_handler)
    
    # Remover o handler de buffer, pois não é mais necessário
    logging.getLogger().removeHandler(buffer_handler)
    
    # Define uma função para lidar com o sinal de interrupção (Ctrl+C)
    def signal_handler(sig, frame):
        """
        Função para lidar com o sinal de interrupção (Ctrl+C).
        """
        logging.warning("[SYSTEM] Sinal de interrupção (Ctrl+C) recebido. Iniciando desligamento limpo...")
        main_window.shutdown_threads()
        app.quit()
    
    # Configura o manipulador de sinal para o sinal SIGINT (Ctrl+C)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Cria um temporizador para permitir que o interpretador Python processe os sinais
    timer = QTimer()
    timer.start(500)  # Inicia o temporizador com intervalo de 500ms
    timer.timeout.connect(lambda: None)  # Conecta o timeout a uma função vazia
    
    # Exibe a janela principal da aplicação
    main_window.show()
    
    # Registrar uma mensagem informativa no log indicando que a janela principal foi exibida
    logging.info("[SYSTEM] Janela principal da GUI exibida.")
    
    # Inicia o loop de eventos da aplicação PyQt5 e encerra com o código de saída retornado
    sys.exit(app.exec_())

# Verifica se o script está sendo executado diretamente (não importado como módulo)
if __name__ == '__main__':
    # Configura o fuso horário padrão para o sistema
    os.environ['TZ'] = 'America/Sao_Paulo'
    
    # Tenta configurar o fuso horário (funciona em sistemas Unix-like)
    try:
        import time
        time.tzset()
    except:
        pass
    
    # Configura o logging
    logger = setup_logging()
    
    # Tenta carregar as configurações de uplinks
    try:
        from uplinks_config import UPLINKS
        logging.info("[SYSTEM] Configurações de uplinks carregadas com sucesso.")
    except ImportError:
        logging.warning("[SYSTEM] Arquivo uplinks_config.py não encontrado. A funcionalidade de DDM não estará disponível.")
        UPLINKS = {}
    
    # Chama a função principal
    main()
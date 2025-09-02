# main.py

import sys
import logging
import signal
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
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        self.setFormatter(formatter)
        
    def emit(self, record):
        """Envia a mensagem formatada via sinal."""
        try:
            msg = self.format(record)
            db_signals.log_message.emit(msg)
        except Exception:
            self.handleError(record)

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
    logging.info("Iniciando a aplicação OLT Monitoring System.")
    
    # Criar instância do QApplication
    app = QApplication(sys.argv)
    
    # Registrar uma mensagem informativa no log indicando o início da verificação do banco de dados
    logging.info("Verificando conexão com o banco de dados...")
    
    # Verifica a conexão com o banco de dados
    if not check_db_connection():
        logging.critical("Falha crítica ao conectar com o banco de dados. A aplicação será encerrada.")
        sys.exit(1)
    
    # Registrar uma mensagem informativa no log indicando que a conexão foi bem-sucedida
    logging.info("Conexão com o banco de dados verificada com sucesso.")
    
    # Registrar uma mensagem informativa no log indicando o início da verificação das tabelas
    logging.info("Verificando e criando tabelas se necessário...")
    
    # Verifica e cria as tabelas do banco de dados
    if not create_tables():
        logging.critical("Falha crítica ao criar/verificar tabelas do banco de dados. A aplicação será encerrada.")
        sys.exit(1)
    
    # Registrar uma mensagem informativa no log indicando que as tabelas foram verificadas/criadas com sucesso
    logging.info("Tabelas verificadas/criadas com sucesso.")
    
    # Instancia a janela principal da aplicação
    main_window = OLTDatabaseGUI()
    
    # Armazenar logs iniciais na janela principal para exibição posterior
    main_window.initial_logs = initial_logs
    
    # Conectar o sinal global de logs ao método da janela principal
    db_signals.log_message.connect(main_window.log_to_gui)
    
    # Criar e adicionar o handler de GUI ao logger
    gui_handler = GuiLogHandler()
    gui_handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(gui_handler)
    
    # Remover o handler de buffer, pois não é mais necessário
    logging.getLogger().removeHandler(buffer_handler)
    
    # Define uma função para lidar com o sinal de interrupção (Ctrl+C)
    def signal_handler(sig, frame):
        """
        Função para lidar com o sinal de interrupção (Ctrl+C).
        """
        logging.warning("Sinal de interrupção (Ctrl+C) recebido. Iniciando desligamento limpo...")
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
    logging.info("Janela principal da GUI exibida.")
    
    # Inicia o loop de eventos da aplicação PyQt5 e encerra com o código de saída retornado
    sys.exit(app.exec_())

# Verifica se o script está sendo executado diretamente (não importado como módulo)
if __name__ == '__main__':
    # Se estiver, chama a função main() para iniciar a aplicação
    main()

# Em main.py, após as outras importações
try:
    from uplinks_config import UPLINKS
    logging.info("Configurações de uplinks carregadas com sucesso.")
except ImportError:
    logging.warning("Arquivo uplinks_config.py não encontrado. A funcionalidade de DDM não estará disponível.")
    UPLINKS = {}
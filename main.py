# olt_monitoring_system/main.py
# Arquivo principal que inicia a aplicação OLT Monitoring System.
# Este arquivo serve como ponto de entrada para a aplicação, configurando o ambiente,
# verificando a conexão com o banco de dados e iniciando a interface gráfica.

# Importação do módulo sys para acesso a funcionalidades específicas do sistema e manipulação de argumentos
import sys
# Importação do módulo logging para registrar eventos e mensagens da aplicação
import logging
# Importação do módulo signal para manipulação de sinais do sistema operacional, como Ctrl+C
import signal
# Importação da classe QApplication do PyQt5 para gerenciar a aplicação GUI
from PyQt5.QtWidgets import QApplication
# Importação da classe QTimer do PyQt5 para criar temporizadores e agendar eventos
from PyQt5.QtCore import QTimer
# Importação da classe OLTDatabaseGUI do módulo gui.main_window
# Esta classe representa a janela principal da aplicação
from gui.main_window import OLTDatabaseGUI
# Importação das funções create_tables e check_db_connection do módulo db.connection
# Estas funções são responsáveis por verificar e criar as tabelas do banco de dados
from db.connection import create_tables, check_db_connection

def main():
    """
    Ponto de entrada principal da aplicação.
    
    Esta função inicializa a aplicação, verifica a conexão com o banco de dados,
    cria as tabelas necessárias e inicia a interface gráfica.
    
    Fluxo de execução:
    1. Registra início da aplicação no log
    2. Cria instância do QApplication
    3. Verifica conexão com o banco de dados
    4. Verifica/cria tabelas do banco de dados
    5. Instancia a janela principal (OLTDatabaseGUI)
    6. Configura manipulador de sinal para Ctrl+C
    7. Configura timer para processamento de sinais
    8. Exibe a janela principal
    9. Inicia o loop de eventos da aplicação
    """
    
    # Registra uma mensagem informativa no log indicando que a aplicação está sendo iniciada
    logging.info("Iniciando a aplicação OLT Monitoring System.")
    
    # Cria uma instância da aplicação PyQt5, passando os argumentos da linha de comando
    app = QApplication(sys.argv)
    
    # Registra uma mensagem informativa no log indicando o início da verificação do banco de dados
    logging.info("Verificando conexão com o banco de dados...")
    
    # Verifica a conexão com o banco de dados usando a função check_db_connection
    # Esta função está definida em db/connection.py e retorna True se a conexão for bem-sucedida
    if not check_db_connection():
        # Se a conexão falhar, registra uma mensagem crítica e encerra a aplicação com código de erro 1
        logging.critical("Falha crítica ao conectar com o banco de dados. A aplicação será encerrada.")
        sys.exit(1)
    
    # Registra uma mensagem informativa no log indicando que a conexão foi bem-sucedida
    logging.info("Conexão com o banco de dados verificada com sucesso.")
    
    # Registra uma mensagem informativa no log indicando o início da verificação das tabelas
    logging.info("Verificando e criando tabelas se necessário...")
    
    # Verifica e cria as tabelas do banco de dados usando a função create_tables
    # Esta função está definida em db/connection.py e retorna True se as tabelas forem criadas/verificadas com sucesso
    if not create_tables():
        # Se a criação/verificação das tabelas falhar, registra uma mensagem crítica e encerra a aplicação
        logging.critical("Falha crítica ao criar/verificar tabelas do banco de dados. A aplicação será encerrada.")
        sys.exit(1)
    
    # Registra uma mensagem informativa no log indicando que as tabelas foram verificadas/criadas com sucesso
    logging.info("Tabelas verificadas/criadas com sucesso.")
    
    # Instancia a janela principal da aplicação (OLTDatabaseGUI) sem passar credenciais
    # A classe OLTDatabaseGUI está definida em gui/main_window.py e representa a interface gráfica principal
    main_window = OLTDatabaseGUI()
    
    # Define uma função para lidar com o sinal de interrupção (Ctrl+C)
    def signal_handler(sig, frame):
        """
        Função para lidar com o sinal de interrupção (Ctrl+C).
        
        Esta função é chamada quando o usuário pressiona Ctrl+C, garantindo 
        um desligamento limpo da aplicação, encerrando as threads e fechando 
        a aplicação corretamente.
        """
        # Registra uma mensagem de aviso no log indicando que o sinal de interrupção foi recebido
        logging.warning("Sinal de interrupção (Ctrl+C) recebido. Iniciando desligamento limpo...")
        
        # Chama o método shutdown_threads da janela principal para encerrar as threads de forma segura
        # Este método está definido na classe OLTDatabaseGUI em gui/main_window.py
        main_window.shutdown_threads()
        
        # Encerra a aplicação PyQt5
        app.quit()
    
    # Configura o manipulador de sinal para o sinal SIGINT (Ctrl+C)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Cria um temporizador para permitir que o interpretador Python processe os sinais
    # Isso é necessário para que o manipulador de sinal funcione corretamente em aplicações PyQt5
    timer = QTimer()
    timer.start(500)  # Inicia o temporizador com intervalo de 500ms
    timer.timeout.connect(lambda: None)  # Conecta o timeout a uma função vazia
    
    # Exibe a janela principal da aplicação
    main_window.show()
    
    # Registra uma mensagem informativa no log indicando que a janela principal foi exibida
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
# -*- coding: utf-8 -*-

# ==============================================================================
# IMPORTAÇÕES DE MÓDULOS
# ==============================================================================
import sys  # Módulo do sistema, usado para interagir com o interpretador Python (ex: para sair da aplicação com sys.exit).
import logging  # Módulo para registrar eventos, erros e informações durante a execução do programa.
import signal  # Módulo para lidar com sinais do sistema operacional, como Ctrl+C (SIGINT).
import os  # Módulo para interagir com o sistema operacional, como criar diretórios (os.makedirs).
import psycopg2  # Adaptador de banco de dados PostgreSQL para Python, usado para conectar e executar comandos no banco.
from datetime import datetime  # Módulo para manipulação de datas e horas, usado para nomear o arquivo de log.
from PyQt5.QtWidgets import QApplication  # Componente principal da biblioteca PyQt5 para gerenciar a aplicação GUI.
from PyQt5.QtCore import QTimer  # Classe do PyQt5 para criar temporizadores que executam ações em intervalos.
from gui.main_window import OLTDatabaseGUI  # Importa a classe da janela principal da interface gráfica.
from db.connection import create_tables, check_db_connection  # Importa funções para gerenciar o banco de dados.
from gui.signals import db_signals  # Importa os sinais personalizados para comunicação entre componentes.

# ==============================================================================
# CONFIGURAÇÃO INICIAL
# ==============================================================================
# Buffer para armazenar logs gerados antes da interface gráfica (GUI) ser iniciada.
# Isso garante que nenhuma mensagem de log inicial seja perdida.
initial_logs = []

# ==============================================================================
# CLASSES DE LOGGING PERSONALIZADAS
# ==============================================================================

class BufferHandler(logging.Handler):
    """
    Handler de logging que armazena temporariamente os registros em um buffer (uma lista).
    Útil para capturar logs antes que o destino final (como a GUI) esteja pronto para recebê-los.
    """
    def __init__(self, buffer):
        """Construtor da classe. Recebe o buffer (lista) onde os logs serão armazenados."""
        super().__init__()  # Chama o construtor da classe pai (logging.Handler).
        self.buffer = buffer  # Armazena a referência da lista que será usada como buffer.
        
    def emit(self, record):
        """
        Método chamado para processar um registro de log.
        Adiciona a mensagem de log, já formatada, ao final da lista de buffer.
        """
        self.buffer.append(self.format(record))

class GuiLogHandler(logging.Handler):
    """
    Handler de logging que envia os registros para a interface gráfica (GUI)
    através de um sinal personalizado do PyQt.
    """
    def __init__(self):
        """Construtor da classe. Configura o formato das mensagens de log."""
        super().__init__()  # Chama o construtor da classe pai.
        # Define o formato da mensagem de log, incluindo hora, minuto, segundo e a mensagem.
        formatter = logging.Formatter('%(asctime)s - %(message)s', datefmt='%H:%M:%S')
        self.setFormatter(formatter)  # Aplica o formatador ao handler.
        
    def emit(self, record):
        """
        Método chamado para processar um registro de log.
        Envia a mensagem formatada para a GUI através do sinal 'log_message'.
        """
        try:
            # Formata a mensagem de log de acordo com o formatter definido no construtor.
            msg = self.format(record)
            # Emite o sinal 'log_message' com a mensagem formatada como argumento.
            # A GUI, que está conectada a este sinal, receberá a mensagem.
            db_signals.log_message.emit(msg)
        except Exception:
            # Em caso de erro ao emitir o sinal, chama o tratador de erros padrão do logging.
            self.handleError(record)

# ==============================================================================
# FUNÇÕES AUXILIARES
# ==============================================================================

def setup_logging():
    """Configura o sistema de logging com múltiplos destinos (console, arquivo e GUI)."""
    # Define um formato padrão para as mensagens de log no console e no arquivo.
    log_formatter = logging.Formatter('%(asctime)s - %(message)s', datefmt='%H:%M:%S')

    # Obtém o logger raiz, que é a base de toda a hierarquia de loggers.
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # Define o nível mínimo de severidade para DEBUG, capturando todas as mensagens.

    # Limpa handlers existentes para evitar duplicação de mensagens de log se esta função for chamada mais de uma vez.
    if logger.hasHandlers():
        logger.handlers.clear()

    # 1. Handler para o Console: exibe logs no terminal.
    console_handler = logging.StreamHandler(sys.stdout)  # Cria um handler que escreve no console.
    console_handler.setFormatter(log_formatter)  # Aplica o formatador.
    console_handler.setLevel(logging.INFO)  # Define o nível para INFO, mostrando apenas mensagens de INFO ou mais graves.
    logger.addHandler(console_handler)  # Adiciona o handler de console ao logger raiz.

    # 2. Handler para o Arquivo: salva os logs em um arquivo.
    # Verifica se o diretório 'logs' existe; se não, cria-o.
    if not os.path.exists('logs'):
        os.makedirs('logs')
    # Cria um handler que escreve em um arquivo de log com a data atual no nome.
    # 'a' = modo append (adicionar ao final), 'utf-8' = codificação de caracteres.
    file_handler = logging.FileHandler(f"logs/olt_monitor_{datetime.now().strftime('%Y%m%d')}.log", 'a', 'utf-8')
    file_handler.setFormatter(log_formatter)  # Aplica o formatador.
    file_handler.setLevel(logging.DEBUG)  # Define o nível para DEBUG, salvando todas as mensagens no arquivo.
    logger.addHandler(file_handler)  # Adiciona o handler de arquivo ao logger raiz.
    
    return logger  # Retorna a instância do logger configurado.

def check_postgresql_timezone():
    """
    Verifica o fuso horário configurado no banco de dados PostgreSQL e o ajusta
    para 'America/Sao_Paulo' se for diferente, tornando a alteração permanente.
    """
    conn = None # Inicializa a variável de conexão como nula.
    try:
        # Tenta conectar ao banco de dados usando as configurações de DB_CONFIG (não definidas neste trecho).
        conn = psycopg2.connect(**DB_CONFIG)
        # Usa um bloco 'with' para garantir que o cursor seja fechado automaticamente.
        with conn.cursor() as cursor:
            # Executa o comando SQL para obter o fuso horário atual do banco.
            cursor.execute("SHOW timezone;")
            # Pega o primeiro resultado da consulta.
            current_tz = cursor.fetchone()[0]
            logging.info(f"Fuso horário atual do PostgreSQL: {current_tz}")
            
            # Compara o fuso horário atual com o desejado.
            if current_tz != 'America/Sao_Paulo':
                # Se for diferente, define o fuso horário para a sessão atual.
                cursor.execute("SET TIME ZONE 'America/Sao_Paulo';")
                # Verifica novamente para confirmar a alteração.
                cursor.execute("SHOW timezone;")
                new_tz = cursor.fetchone()[0]
                logging.info(f"Fuso horário do PostgreSQL alterado para: {new_tz}")
                
                # Torna a alteração permanente para todo o banco de dados.
                cursor.execute("ALTER DATABASE Olt SET timezone TO 'America/Sao_Paulo';")
                logging.info("Fuso horário definido permanentemente para o banco de dados")
    except Exception as e:
        # Se ocorrer qualquer erro durante o processo, registra uma mensagem de erro.
        logging.error(f"Erro ao verificar/definir fuso horário do PostgreSQL: {e}")
    finally:
        # O bloco 'finally' é sempre executado, garantindo que a conexão seja fechada.
        if conn:
            conn.close()

# ==============================================================================
# FUNÇÃO PRINCIPAL
# ==============================================================================

def main():
    """
    Ponto de entrada principal da aplicação.
    
    Esta função inicializa a aplicação, configura o logging, verifica a conexão
    com o banco de dados, cria as tabelas necessárias e, por fim, inicia a
    interface gráfica.
    """
    
    # Adiciona o handler de buffer ao logger raiz para capturar logs iniciais.
    buffer_handler = BufferHandler(initial_logs)
    logging.getLogger().addHandler(buffer_handler)
    
    # Registra a primeira mensagem de log, indicando o início da aplicação.
    logging.info("[SYSTEM] Iniciando a aplicação OLT Monitoring System.")
    
    
    # Registra o início da verificação da conexão com o banco de dados.
    logging.info("[SYSTEM] Verificando conexão com o banco de dados...")
    
    # Chama a função que verifica a conexão. Se retornar False (falha)...
    if not check_db_connection():
        # ...registra um erro crítico e encerra a aplicação com código de erro 1.
        logging.critical("[SYSTEM] Falha crítica ao conectar com o banco de dados. A aplicação será encerrada.")
        sys.exit(1)
    
    # Se a conexão for bem-sucedida, registra uma mensagem de sucesso.
    logging.info("[SYSTEM] Conexão com o banco de dados verificada com sucesso.")
    
    # Registra o início da verificação/criação das tabelas.
    logging.info("[SYSTEM] Verificando e criando tabelas se necessário...")
    
    # Chama a função que cria as tabelas. Se retornar False (falha)...
    if not create_tables():
        # ...registra um erro crítico e encerra a aplicação.
        logging.critical("[SYSTEM] Falha crítica ao criar/verificar tabelas do banco de dados. A aplicação será encerrada.")
        sys.exit(1)
    
    # Se as tabelas foram criadas/verificadas com sucesso, registra uma mensagem.
    logging.info("[SYSTEM] Tabelas verificadas/criadas com sucesso.")
    
    # Cria a instância principal da aplicação QApplication.
    app = QApplication(sys.argv)
    
    # Cria uma instância da janela principal da GUI.
    main_window = OLTDatabaseGUI()
    
    # Passa os logs capturados no buffer para a janela principal, para que possam ser exibidos.
    main_window.initial_logs = initial_logs
    
    # Conecta o sinal global 'log_message' ao método 'log_to_gui' da janela principal.
    # Agora, qualquer log emitido pelo GuiLogHandler será exibido na GUI.
    db_signals.log_message.connect(main_window.log_to_gui)
    
    # Cria o handler de log para a GUI.
    gui_handler = GuiLogHandler()
    gui_handler.setLevel(logging.INFO)  # Define que a GUI só mostrará logs de nível INFO e superiores.
    logging.getLogger().addHandler(gui_handler)  # Adiciona o handler da GUI ao logger raiz.
    
    # Remove o handler de buffer, pois a GUI já está pronta para receber os logs diretamente.
    logging.getLogger().removeHandler(buffer_handler)
    
    # Define uma função interna para lidar com o sinal de interrupção (Ctrl+C).
    def signal_handler(sig, frame):
        """Função para lidar com o sinal de interrupção (Ctrl+C) de forma limpa."""
        logging.warning("[SYSTEM] Sinal de interrupção (Ctrl+C) recebido. Iniciando desligamento limpo...")
        # Chama um método na janela principal para encerrar threads em execução.
        main_window.shutdown_threads()
        # Encerra a aplicação PyQt.
        app.quit()
    
    # Associa a função 'signal_handler' ao sinal SIGINT (gerado por Ctrl+C).
    signal.signal(signal.SIGINT, signal_handler)
    
    # Cria um QTimer para garantir que o interpretador Python possa processar sinais
    # do sistema operacional (como o Ctrl+C) enquanto o loop de eventos da GUI está em execução.
    timer = QTimer()
    timer.start(500)  # Dispara a cada 500ms.
    timer.timeout.connect(lambda: None)  # A ação é vazia, o objetivo é apenas manter o fluxo de eventos.
    
    # Exibe a janela principal.
    main_window.show()
    
    # Registra que a GUI foi exibida.
    logging.info("[SYSTEM] Janela principal da GUI exibida.")
    
    # Inicia o loop de eventos da aplicação. O programa ficará aqui até a janela ser fechada.
    # sys.exit() garante que o código de saída da aplicação seja retornado ao sistema operacional.
    sys.exit(app.exec_())

# ==============================================================================
# PONTO DE ENTRADA DO SCRIPT
# ==============================================================================

# Verifica se o script está sendo executado diretamente (e não importado como um módulo).
if __name__ == '__main__':
    # Define o fuso horário padrão para a aplicação. Importante para consistência de datas e horas.
    os.environ['TZ'] = 'America/Sao_Paulo'
    
    # Em sistemas Unix-like (Linux, macOS), time.tzset() atualiza as variáveis de fuso horário.
    try:
        import time
        time.tzset()
    except:
        # Ignora o erro se a função não estiver disponível (ex: em alguns sistemas Windows).
        pass
    
    # Chama a função para configurar o sistema de logging.
    logger = setup_logging()
    
    # Tenta importar as configurações de uplinks de um arquivo separado.
    try:
        from uplinks_config import UPLINKS
        logging.info("[SYSTEM] Configurações de uplinks carregadas com sucesso.")
    except ImportError:
        # Se o arquivo não existir, registra um aviso e continua com um dicionário vazio.
        logging.warning("[SYSTEM] Arquivo uplinks_config.py não encontrado. A funcionalidade de DDM não estará disponível.")
        UPLINKS = {}
    
    # Chama a função principal para iniciar a aplicação.
    main()

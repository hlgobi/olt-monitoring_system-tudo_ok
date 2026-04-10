# -*- coding: utf-8 -*-

# ==============================================================================
# MÓDULO DE COMUNICAÇÃO SSH COM EQUIPAMENTOS OLT
# ==============================================================================
# Este arquivo implementa a funcionalidade de comunicação SSH com equipamentos OLT
# (Optical Line Terminal), permitindo o envio de comandos e o processamento das respostas.
#
# Utiliza a biblioteca Paramiko para estabelecer conexões SSH seguras e inclui
# mecanismos robustos de tratamento de erros, timeouts e paginação de respostas.

# ==============================================================================
# IMPORTAÇÕES DE MÓDULOS
# ==============================================================================
import paramiko  # Biblioteca para implementação de protocolo SSHv2 em Python
import time  # Módulo para funções relacionadas a tempo (pausas, medições)
import logging  # Módulo para registro de eventos e mensagens do sistema
import re  # Módulo para operações com expressões regulares
from utils.helpers import clean_response  # Função utilitária para limpar respostas de comandos

# ==============================================================================
# FUNÇÕES DE COMUNICAÇÃO SSH
# ==============================================================================

def send_command(shell, command, wait_time=3.0, timeout=45):
    """
    Envia um comando SSH para a OLT e processa a resposta de forma robusta.
    
    Esta função implementa um mecanismo completo para envio de comandos e recebimento
    de respostas, incluindo tratamento de paginação, timeouts, prompts interativos
    e detecção de padrões de erro nas respostas.
    
    Args:
        shell: Objeto shell SSH ativo da conexão Paramiko
        command (str): Comando a ser enviado para a OLT
        wait_time (float, optional): Tempo de espera inicial após envio do comando. Padrão: 3.0
        timeout (int, optional): Tempo máximo em segundos para aguardar a resposta completa. Padrão: 45
    
    Returns:
        str: Resposta do comando já limpa e processada
    
    Raises:
        Exception: Se ocorrer erro durante a execução do comando, se a resposta for vazia
                  ou se forem detectados padrões de erro na resposta
    """
    full_response = ""  # Inicializa string para armazenar a resposta completa
    start_time = time.time()  # Marca o tempo de início para controle de timeout

    try:
        # Limpa o buffer de recebimento antes de enviar o novo comando
        while shell.recv_ready():
            shell.recv(4096)  # Lê e descarta quaisquer dados pendentes no buffer

        logging.debug(f"Enviando comando: {command}")  # Registra o comando enviado para debug
        shell.send(command + "\n")  # Envia o comando seguido de quebra de linha
        time.sleep(0.5)  # Espera breve para o processamento inicial do comando

        # Loop principal para receber a resposta do comando
        while (time.time() - start_time) < timeout:
            if shell.recv_ready():  # Verifica se há dados disponíveis para leitura
                # Lê um bloco de dados e decodifica de UTF-8, ignorando erros de codificação
                chunk = shell.recv(4096).decode('utf-8', errors='ignore')
                logging.debug(f"Chunk recebido: {chunk[:100]}...")  # Loga trecho do bloco recebido
                full_response += chunk  # Adiciona o bloco à resposta completa

                # Tratamento robusto de paginação de respostas longas
                if "---- More" in chunk:
                    shell.send(" ")  # Envia espaço para avançar para a próxima página
                    time.sleep(0.3)  # Espera breve para processamento
                    start_time = time.time()  # Reinicia o contador de timeout

                # Tratamento de prompts interativos que exigem Enter
                elif "{ <cr>||<K> }:" in chunk:
                    shell.send("\n")  # Envia quebra de linha para confirmar
                    time.sleep(0.3)  # Espera breve para processamento
                    start_time = time.time()  # Reinicia o contador de timeout

                # Verificação de marcadores de fim de comando
                elif any(marker in full_response.strip()[-30:] for marker in [">", "#"]):
                    # Garante que o buffer esteja vazio antes de finalizar
                    if not shell.recv_ready():
                        time.sleep(0.2)  # Espera adicional para garantir estabilidade
                        if not shell.recv_ready():  # Verificação final do buffer
                            break  # Encerra o loop de recebimento
            else:
                time.sleep(0.3)  # Pequena pausa antes da próxima verificação

        # Limpeza e processamento da resposta recebida
        cleaned = clean_response(full_response)
        logging.debug(f"Resposta completa (limpa): {cleaned[:200]}...")

        # Detecção robusta de padrões de erro na resposta
        error_patterns = [
            r"^\s*Error:",      # Linhas começando com "Error:"
            r"^\s*Failure:",    # Linhas começando com "Failure:"
            r"^\s*%",           # Linhas começando com "%"
            r"^\s*\^"           # Linhas começando com "^"
        ]
        
        found_error = False
        error_lines_found = []
        
        # Verifica cada linha da resposta em busca de padrões de erro
        for line in cleaned.splitlines():
            for pattern in error_patterns:
                if re.search(pattern, line):
                    found_error = True
                    error_lines_found.append(line.strip())
                    break  # Evita adicionar a mesma linha múltiplas vezes
                    
        # Se encontrou padrões de erro, verifica se são exceções conhecidas
        if found_error:
            # Lista de mensagens que parecem erros mas são respostas normais em certos contextos
            ok_messages = ["No ONT online", "board does not exist", "PON port does not exist"]
            
            # Se não for uma das mensagens aceitáveis, levanta exceção
            if not any(ok_msg in cleaned for ok_msg in ok_messages):
                error_detail = error_lines_found if error_lines_found else cleaned.strip().splitlines()[-2:]
                raise Exception(f"Comando retornou um erro: {error_detail}")

        # Verifica se a resposta está vazia após a limpeza
        if not cleaned.strip():
            raise Exception("Resposta vazia recebida")

        return cleaned  # Retorna a resposta limpa e validada

    except Exception as e:
        # Registra o erro com detalhes do comando que falhou
        logging.warning(f"Erro no comando '{command}': {str(e)}")
        raise  # Propaga a exceção para tratamento pelo chamador


def connect_to_olt(olt_ip, username, password, max_retries=3):
    """
    Estabelece uma conexão SSH com um equipamento OLT usando Paramiko.
    
    Implementa um mecanismo de reconexão automática com tentativas múltiplas e
    tratamento detalhado de diferentes tipos de falhas de conexão.
    
    Args:
        olt_ip (str): Endereço IP do equipamento OLT
        username (str): Nome de usuário para autenticação SSH
        password (str): Senha para autenticação SSH
        max_retries (int, optional): Número máximo de tentativas de conexão. Padrão: 3
    
    Returns:
        tuple: (client, shell) onde:
            - client: Instância do cliente SSH Paramiko ou None em caso de falha
            - shell: Objeto shell da conexão SSH ou None em caso de falha
    
    Raises:
        Não levanta exceções diretamente, mas registra todos os erros no log
    """
    client = None  # Inicializa a variável do cliente
    
    # Loop de tentativas de conexão
    for attempt in range(1, max_retries + 1):
        try:
            logging.info(f"[COMM] Tentativa {attempt}/{max_retries}: Conectando a {olt_ip}...")
            
            # Cria uma nova instância do cliente SSH
            client = paramiko.SSHClient()
            # Configura política para adicionar automaticamente chaves de host desconhecidas
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Tenta estabelecer a conexão com timeouts específicos
            client.connect(
                hostname=olt_ip,
                username=username,
                password=password,
                timeout=10,        # Timeout para estabelecimento da conexão
                auth_timeout=15,   # Timeout para processo de autenticação
                banner_timeout=15  # Timeout para recebimento do banner inicial
            )
            
            # Se a conexão for bem-sucedida, invoca um shell interativo
            shell = client.invoke_shell()
            shell.settimeout(15)  # Define timeout para operações no shell
            
            logging.info(f"[COMM] Conectado com sucesso a {olt_ip} (Shell OK)")
            return client, shell  # Retorna o cliente e o shell para uso
            
        except paramiko.AuthenticationException:
            # Falha específica de autenticação - não tenta novamente
            logging.error(f"[COMM] Falha de autenticação para {olt_ip}. Verifique as credenciais.")
            break  # Interrompe o loop de tentativas
            
        except paramiko.SSHException as e:
            # Erros específicos do protocolo SSH
            logging.error(f"[COMM] Erro SSH na tentativa {attempt} para {olt_ip}: {str(e)}")
            
            # Se atingiu o máximo de tentativas, interrompe
            if attempt == max_retries:
                logging.error(f"[COMM] Máximo de tentativas ({max_retries}) atingido para {olt_ip}.")
                break
                
            time.sleep(2)  # Espera antes da próxima tentativa
            
        except Exception as e:
            # Outros erros inesperados durante a conexão
            logging.error(f"[COMM] Erro inesperado ao conectar a {olt_ip} na tentativa {attempt}: {str(e)}")
            
            # Se atingiu o máximo de tentativas, interrompe
            if attempt == max_retries:
                break
                
            time.sleep(2)  # Espera antes da próxima tentativa
    
    # Se todas as tentativas falharam, garante que o cliente seja fechado se existir
    if client:
        try:
            client.close()
        except:
            pass  # Ignora erros ao fechar a conexão
    
    # Retorna None para ambos os componentes indicando falha na conexão
    return None, None
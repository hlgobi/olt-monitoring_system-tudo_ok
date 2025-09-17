# 8. olt_monitoring_system/olt/communication.py
# olt/communication.py
# Este arquivo lida com a comunicação SSH com a OLT, incluindo conexão e envio de comandos.

import paramiko # Importa a biblioteca Paramiko para conexões SSH.
import time # Importa o módulo time para pausas e timeouts.
import logging # Importa o módulo de logging.
import re # Importa o módulo de expressões regulares.
from utils.helpers import clean_response # Importa a função clean_response do módulo de helpers.

def send_command(shell, command, wait_time=3.0, timeout=45): # Define a função para enviar um comando via SSH.
    """
    Envia comando SSH com tratamento robusto.
    Retorna a saída do comando limpa.
    """ # Docstring da função.
    full_response = "" # Inicializa a string para armazenar a resposta completa.
    start_time = time.time() # Registra o tempo de início para controle de timeout.

    try: # Inicia o bloco try-except.
        # Limpa o buffer antes de enviar
        while shell.recv_ready(): # Enquanto houver dados para receber no buffer do shell.
            shell.recv(4096) # Lê e descarta os dados do buffer.

        logging.debug(f"Enviando comando: {command}") # Loga o comando que está sendo enviado.
        shell.send(command + "\n") # Envia o comando seguido de uma nova linha.
        time.sleep(0.5)  # Espera inicial para o comando ser processado.

        while (time.time() - start_time) < timeout: # Loop continua enquanto não exceder o timeout.
            if shell.recv_ready(): # Verifica se há dados prontos para serem lidos.
                chunk = shell.recv(4096).decode('utf-8', errors='ignore') # Lê um pedaço (chunk) da resposta.
                                                                        # Decodifica de UTF-8, ignorando erros.
                logging.debug(f"Chunk recebido: {chunk[:100]}...") # Loga os primeiros 100 caracteres do chunk.
                full_response += chunk # Adiciona o chunk à resposta completa.

                # Trata paginação de forma robusta
                if "---- More" in chunk: # Se encontrar o indicador de paginação "---- More".
                    shell.send(" ") # Envia um espaço para avançar para a próxima página.
                    time.sleep(0.3) # Espera um pouco.
                    start_time = time.time() # Reseta o timeout na interação.

                # Trata prompts potenciais <cr>
                elif "{ <cr>||<K> }:" in chunk: # Se encontrar um prompt que espera Enter.
                    shell.send("\n") # Envia uma nova linha.
                    time.sleep(0.3) # Espera um pouco.
                    start_time = time.time() # Reseta o timeout.

                # Verifica marcadores de fim
                # Verifica se os últimos 30 caracteres da resposta contêm um prompt ('>' ou '#').
                elif any(marker in full_response.strip()[-30:] for marker in [">", "#"]):
                     if not shell.recv_ready(): # Garante que o buffer esteja vazio antes de sair.
                        time.sleep(0.2) # Pequena espera para ter certeza.
                        if not shell.recv_ready(): # Verifica novamente.
                            break # Sai do loop se o prompt foi encontrado e o buffer está vazio.
            else: # Se não há dados prontos para ler.
                time.sleep(0.3) # Espera um pouco antes de verificar novamente.

        cleaned = clean_response(full_response) # Limpa a resposta completa.
        logging.debug(f"Resposta completa (limpa): {cleaned[:200]}...") # Loga os primeiros 200 caracteres da resposta limpa.

        # *** NOVO: Verifica padrões de erro específicos ***
        error_patterns = [ # Lista de padrões de expressão regular que indicam erro.
            r"^\s*Error:", # Linhas começando com "Error:".
            r"^\s*Failure:", # Linhas começando com "Failure:".
            r"^\s*%", # Linhas começando com "%".
            r"^\s*\^" # Linhas começando com "^".
        ]
        
        found_error = False # Flag para indicar se um erro foi encontrado.
        error_lines_found = [] # Lista para armazenar as linhas de erro encontradas.
        
        for line in cleaned.splitlines(): # Itera sobre cada linha da resposta limpa.
            for pattern in error_patterns: # Itera sobre cada padrão de erro.
                if re.search(pattern, line): # Se o padrão de erro for encontrado na linha.
                    found_error = True # Define a flag de erro como True.
                    error_lines_found.append(line.strip()) # Adiciona a linha de erro (sem espaços extras) à lista.
                    break # Não precisa adicionar a mesma linha duas vezes, então sai do loop interno.
                    
        if found_error: # Se um erro foi encontrado.
             # Verifica se é uma 'ok_msg' *antes* de levantar a exceção.
             # Lista de mensagens que, apesar de parecerem erros, são respostas normais em certos contextos.
             if not any(ok_msg in cleaned for ok_msg in ["No ONT online", "board does not exist", "PON port does not exist"]):
                 # Se linhas específicas foram encontradas, usa elas. Senão (não deve acontecer agora), usa o final como fallback.
                 # Levanta uma exceção com as linhas de erro ou, como fallback, as últimas duas linhas da resposta.
                 raise Exception(f"Comando retornou um erro: {error_lines_found if error_lines_found else cleaned.strip().splitlines()[-2:]}")

        if not cleaned.strip(): # Se a resposta limpa estiver vazia.
             raise Exception("Resposta vazia recebida") # Levanta uma exceção.

        return cleaned # Retorna a resposta limpa.

    except Exception as e: # Captura qualquer exceção.
        logging.warning(f"Erro no comando '{command}': {str(e)}") # Loga um aviso com o erro.
        raise # Relança a exceção para ser tratada pelo chamador.


# Em olt/communication.py, modifique a função connect_to_olt:

# olt/communication.py
def connect_to_olt(olt_ip, username, password, max_retries=3):
    """
    Estabelece uma conexão SSH com a OLT usando paramiko.
    Retorna o cliente SSH e o shell, ou (None, None) em caso de falha.
    """
    client = None
    for attempt in range(1, max_retries + 1):
        try:
            logging.info(f"[COMM] Tentativa {attempt}/{max_retries}: Conectando a {olt_ip}...")
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=olt_ip,
                username=username,
                password=password,
                timeout=10,  # Timeout de conexão
                auth_timeout=15,  # Timeout de autenticação
                banner_timeout=15  # Timeout para banner
            )
            shell = client.invoke_shell()
            shell.settimeout(15)  # Define timeout para operações no shell
            logging.info(f"[COMM] Conectado com sucesso a {olt_ip} (Shell OK)")
            return client, shell
        except paramiko.AuthenticationException:
            logging.error(f"[COMM] Falha de autenticação para {olt_ip}. Verifique as credenciais.")
            break
        except paramiko.SSHException as e:
            logging.error(f"[COMM] Erro SSH na tentativa {attempt} para {olt_ip}: {str(e)}")
            if attempt == max_retries:
                logging.error(f"[COMM] Máximo de tentativas ({max_retries}) atingido para {olt_ip}.")
                break
            time.sleep(2)
        except Exception as e:
            logging.error(f"[COMM] Erro inesperado ao conectar a {olt_ip} na tentativa {attempt}: {str(e)}")
            if attempt == max_retries:
                break
            time.sleep(2)
    if client:
        try:
            client.close()
        except:
            pass
    return None, None
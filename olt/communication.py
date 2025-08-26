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


def connect_to_olt(olt_ip, username, password, max_retries=3): # Define a função para conectar à OLT.
    """Estabelece conexão SSH com a OLT com lógica de nova tentativa""" # Docstring da função.
    for attempt in range(max_retries): # Loop para tentar a conexão várias vezes.
        client = None # Garante que o cliente seja None no início de cada tentativa.
        try: # Inicia o bloco try-except.
            client = paramiko.SSHClient() # Cria um objeto SSHClient.
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy()) # Política para adicionar automaticamente chaves de host desconhecidas.

            logging.info(f"Tentativa {attempt+1}: Conectando a {olt_ip}...") # Loga a tentativa de conexão.
            client.connect( # Tenta conectar ao servidor SSH.
                olt_ip, # Endereço IP da OLT.
                username=username, # Nome de usuário.
                password=password, # Senha.
                timeout=30, # Timeout para a conexão em segundos.
                look_for_keys=False, # Não procura por chaves SSH privadas.
                allow_agent=False, # Não permite o uso de um agente SSH.
                banner_timeout=30 # Timeout para receber o banner SSH.
            )
            # Loga o sucesso da conexão e a versão do servidor remoto.
            logging.info(f"Conectado (versão 2.0, cliente {client.get_transport().remote_version})")
            logging.info(f"Autenticação (senha) bem-sucedida!") # Loga o sucesso da autenticação.

            shell = client.invoke_shell() # Abre um shell interativo na conexão.
            time.sleep(2) # Espera aumentada para o shell estabilizar.

            # Envia nova linha para obter o prompt inicial e lê-lo
            shell.send("\n") # Envia uma nova linha para obter o prompt.
            time.sleep(1) # Espera pela resposta.
            response = "" # Inicializa a string de resposta.
            while shell.recv_ready(): # Enquanto houver dados para receber.
                 response += shell.recv(4096).decode('utf-8', errors='ignore') # Lê e decodifica a resposta.
                 time.sleep(0.2) # Pequena espera entre leituras.

            logging.debug(f"Resposta inicial da OLT: {response.strip()}") # Loga a resposta inicial.

            if ">" in response or "#" in response: # Verifica se o prompt esperado está na resposta.
                logging.info(f"Conexão SSH estabelecida com {olt_ip} após {attempt+1} tentativa(s)") # Loga o sucesso.
                # Envia comando para desabilitar paginação (melhor esforço)
                shell.send("scroll 512\n") # Comando para desabilitar paginação ou definir um scroll grande.
                time.sleep(1) # Espera o comando ser processado.
                while shell.recv_ready(): shell.recv(4096) # Limpa qualquer saída do comando scroll.
                return client, shell # Retorna o cliente SSH e o shell.
            else: # Se o prompt não for reconhecido.
                shell.close() # Fecha o shell.
                client.close() # Fecha o cliente.
                raise Exception(f"Prompt não reconhecido na resposta: '{response}'") # Levanta uma exceção.

        except Exception as e: # Captura qualquer exceção durante a conexão.
            logging.warning(f"Tentativa {attempt+1}/{max_retries}: Conexão SSH com {olt_ip} falhou: {str(e)}") # Loga um aviso.
            if client: client.close() # Garante que o cliente seja fechado em caso de falha.
            if attempt < max_retries - 1: # Se não for a última tentativa.
                time.sleep(10) # Espera 10 segundos antes de tentar novamente.
                continue # Continua para a próxima tentativa.
            raise # Relança a exceção se todas as tentativas falharem.

    # Levanta uma exceção se a conexão falhar após todas as tentativas.
    raise Exception(f"Falha ao estabelecer conexão SSH com {olt_ip} após múltiplas tentativas")
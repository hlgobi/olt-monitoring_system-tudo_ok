# 10. olt_monitoring_system/olt/processing.py
# Este módulo contém a lógica principal para processar os dados coletados das OLTs.
# Ele é responsável por orquestrar a coleta de dados em paralelo (usando threads),
# enviar comandos, processar as respostas e salvar os resultados no banco de dados.

import time
import logging
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed # Para executar tarefas em paralelo.
import random # Usado para adicionar um pequeno atraso aleatório e evitar que todas as threads iniciem exatamente ao mesmo tempo.
import json

# --- Importações de Módulos da Aplicação ---
from olt.communication import send_command, connect_to_olt # Funções para conectar e enviar comandos à OLT.
# --- MODIFICADO AQUI ---
# CÓDIGO CORRIGIDO
from olt.parsing import (extract_service_mac, extract_ont_info, parse_ont_info_details, 
                         parse_pon_port_state)
from db.operations import (save_ont_data, save_pon_status, save_temp_data, 
                           save_resource_data, save_pon_traffic_data, save_pon_port_state)
# --- FIM DA MODIFICAÇÃO ---
from gui.signals import db_signals

# Define o número de threads que serão usadas para processar as portas PON em paralelo.
NUM_THREADS = 4

# --- Mapeamento de Placas e Portas ---
# Dicionário que mapeia o nome de uma placa (board) ao seu número de portas.
# Essencial para saber quantas portas PON devem ser verificadas em cada slot.
# MODIFICADO: Foram adicionadas novas placas para suportar o modelo MA5800.
BOARD_PORT_MAP = {
    # Placas GPON (MA5683T)
    "GPFD": 16, "H805GPFD": 16, "GPBD": 8, "H805GPBD": 8,
    "H807GPBD": 8, "H808GPBH": 16,
    # Placas XG-PON (MA5683T)
    "XGPD": 8, "H801XGPD": 8, "H802XGBC": 4,
    # Placas GPON (MA5800)
    "H901GPUF": 16, "H902GPLF": 16, "H901GPLF": 16,
    "H903GPSF": 16, "H902GPSF": 16,
    "H902GPUF": 16, # <-- PLACA ADICIONADA PARA OLT-89
    # Placas Combo (MA5800)
    "H907CGHF": 16,
}

def send_command_with_pagination(shell, command, timeout=120):
    """
    Envia um comando e lida com múltiplos prompts e paginação de forma robusta.
    Esta é uma função crucial, pois a saída de comandos longos na OLT é paginada
    com "---- More ----" e alguns comandos pedem confirmação com "{ <cr>... }".
    """
    # Expressões regulares para detectar os diferentes tipos de prompts.
    prompt_re = re.compile(r"([\w.-]+[>#])\s*$") # Prompt final (ex: OLT-NOME#)
    more_re = re.compile(r'---\- More\s*\( Press \'Q\' to break \)\s*---\-') # Prompt de paginação
    cr_prompt_re = re.compile(r"\{\s*<cr>.*\}\s*:") # Prompt de confirmação

    # Limpa qualquer dado residual no buffer do shell antes de enviar um novo comando.
    while shell.recv_ready():
        shell.recv(4096)

    logging.debug(f"Executando comando: {command}")
    shell.send(command + "\n") # Envia o comando seguido de um Enter.

    full_response = ""
    end_time = time.time() + timeout # Define um tempo máximo para a execução do comando.
    
    # Loop principal para ler a resposta completa.
    while time.time() < end_time:
        # Se não houver dados prontos para ler, aguarda um pouco.
        if not shell.recv_ready():
            time.sleep(0.5)
            # Verifica se o prompt final já está na resposta, indicando que o comando terminou.
            if prompt_re.search(full_response.rstrip().splitlines()[-1] if full_response.strip() else ""):
                break
            continue

        try:
            # Lê um pedaço (chunk) da resposta do shell.
            chunk = shell.recv(8192).decode('utf-8', errors='ignore')
            logging.debug(f"RAW CHUNK RECEBIDO: ----\n{chunk}\n----")
            full_response += chunk

            # 1. Lida com o prompt de confirmação { <cr>... }
            if cr_prompt_re.search(full_response):
                logging.debug(f"Prompt {{ <cr> }} detectado para '{command}'. Enviando Enter.")
                shell.send("\n") # Envia um Enter para confirmar.
                full_response = "" # Limpa a resposta para não incluir o prompt de confirmação.
                time.sleep(2) # Espera a OLT processar a confirmação.
                continue

            # 2. Lida com a paginação "More"
            while more_re.search(full_response):
                logging.debug(f"Paginação detectada para '{command}'. Enviando espaço.")
                full_response = more_re.sub('', full_response) # Remove a linha "More" da resposta.
                shell.send(" ") # Envia um espaço para carregar a próxima página.
                time.sleep(0.8) # Espera a próxima página carregar.
                if shell.recv_ready():
                    full_response += shell.recv(8192).decode('utf-8', errors='ignore')

        except Exception as e:
            logging.error(f"Erro durante a leitura do shell: {e}", exc_info=True)
            break
            
    # Limpa a saída final, removendo o eco do comando que foi digitado e o prompt final.
    lines = full_response.splitlines()
    cleaned_lines = []
    for line in lines:
        # Ignora a linha que contém o próprio comando ou a mensagem de "executando".
        if line.strip() == command or "Command is being executed" in line:
            continue
        cleaned_lines.append(line)
    
    # Remove a última linha se ela for o prompt final.
    if cleaned_lines and prompt_re.search(cleaned_lines[-1].strip()):
        cleaned_lines.pop()
        
    return "\n".join(cleaned_lines).strip()

# Em olt/processing.py, substitua a função process_ont_details por esta:

def process_ont_details(shell, olt_ip, slot, port, ont_id, info):
    """
    Processa os detalhes de uma ÚNICA ONT, coletando MAC (se online)
    e todas as informações detalhadas de status.
    """
    # Importações necessárias dentro da função para evitar dependências circulares
    from olt.parsing import extract_service_mac, parse_ont_info_details
    from db.operations import save_ont_data, get_existing_ont_data  # Adicione esta importação
    import json
    
    mac = "N/A"
    # 1. Coleta de MAC (apenas para ONTs online)
    if info.get("run_state", "").lower() == "online":
        try:
            command_mac = f"display ont wan-info 0/{slot} {port} {ont_id}"
            response_mac = send_command_with_pagination(shell, command_mac, timeout=30)
            mac = extract_service_mac(response_mac)
        except Exception as e:
            logging.warning(f"Falha ao obter MAC para ONT {ont_id}: {str(e)}")

    # 2. Coleta de Detalhes Adicionais (para TODAS as ONTs)
    ont_details = {}
    try:
        command_details = f"display ont info 0 {slot} {port} {ont_id}"
        response_details = send_command_with_pagination(shell, command_details, timeout=45)
        logging.info(f"Resposta bruta para '{command_details}':\n---\n{response_details}\n---")
        ont_details = parse_ont_info_details(response_details)
    except Exception as e:
        logging.error(f"Falha ao obter detalhes para ONT {ont_id}: {str(e)}")

    # 3. Busca dados existentes no banco para preservar connection_code e client_name
    existing_data = get_existing_ont_data(olt_ip, info.get("sn", "N/A"))
    
    # 4. Monta o dicionário com os dados básicos.
    collected_data = {
        "fsp": f"0/{slot}/{port}",
        "ont_id": ont_id,
        "mac": mac,
        "sn": info.get("sn", "N/A"),
        "rx": info.get("rx_power", "N/A"),
        "tx": info.get("tx_power", "N/A"),
        "description": info.get("description", "N/A"),
        "status": info.get("run_state", "offline"),
        # Preserva valores existentes ou usa "N/A" como padrão
        "connection_code": existing_data.get('connection_code', "N/A") if existing_data else "N/A",
        "client_name": existing_data.get('client_name', "N/A") if existing_data else "N/A"
    }
    
    # 5. Combina os detalhes extraídos no dicionário final
    if ont_details:
        collected_data.update(ont_details)
        collected_data['services'] = json.dumps(ont_details.get('services', []))

    # 6. Salva o dicionário completo no banco de dados.
    save_ont_data(olt_ip, collected_data)
    return 1

def process_pon_worker(olt_ip, username, password, slot, port, gui_window_instance, log_callback):
    """
    Worker executado por uma thread. Ele conecta, processa *uma* porta PON completa e desconecta.
    """
    client = None
    processed_count = 0
    pon_fsp = f"0/{slot}/{port}"
    log_prefix = f"[{olt_ip}][Worker {slot}/{port}]"
    
    # Envia uma mensagem de log para a GUI informando o início do worker.
    log_callback(f"{log_prefix} Iniciando...")
    
    # Adiciona um atraso aleatório para evitar que todas as threads conectem ao mesmo tempo.
    time.sleep(random.uniform(0.5, 2.5))
    
    try:
        # Conecta-se à OLT. Tenta reconectar até 2 vezes em caso de falha.
        client, shell = connect_to_olt(olt_ip, username, password, max_retries=2)
        
        log_callback(f"{log_prefix} Conectado. Aguardando estabilização do shell...")
        time.sleep(3) 
        while shell.recv_ready(): # Limpa o buffer inicial de boas-vindas.
            shell.recv(4096)
        
        # Entra no modo de configuração (enable).
        log_callback(f"{log_prefix} Enviando 'enable'...")
        shell.send("enable\n")
        time.sleep(1) 
        
        # Loop para aguardar a resposta do comando 'enable', que pode ser um pedido de senha ou o prompt '#'.
        response_buffer = ""
        for _ in range(5):
            if shell.recv_ready():
                response_buffer += shell.recv(4096).decode('utf-8', errors='ignore')
            if "Password" in response_buffer or "#" in response_buffer:
                break
            time.sleep(0.5)

        # Se a OLT pedir senha para o modo 'enable', envia a senha.
        if "Password" in response_buffer:
            log_callback(f"{log_prefix} Senha solicitada. Enviando...")
            shell.send(f"{password}\n")
            time.sleep(2)
            while shell.recv_ready(): shell.recv(4096) # Limpa o buffer após enviar a senha.
        
        shell.send("\n") # Envia um Enter extra para garantir um prompt limpo.
        time.sleep(1)
        while shell.recv_ready(): shell.recv(4096)

        # Coletar dados de tráfego da PON
        log_callback(f"{log_prefix} Coletando dados de tráfego...")
        traffic_data = collect_pon_traffic(shell, slot, port)
        if traffic_data:
            save_pon_traffic_data(olt_ip, pon_fsp, traffic_data)
            log_callback(f"{log_prefix} Dados de tráfego salvos com sucesso.")

        # Coletar dados de estado da porta PON
        log_callback(f"{log_prefix} Coletando dados de estado da porta...")
        state_data = collect_pon_state(shell, slot, port) # Chamada para a função que agora está no mesmo arquivo
        if state_data:
            save_pon_port_state(olt_ip, pon_fsp, state_data)
            log_callback(f"{log_prefix} Dados de estado salvos com sucesso.")
        else:
            log_callback(f"{log_prefix} Falha ao coletar dados de estado da porta.")
        
        # Comando para obter um resumo de todas as ONTs na porta PON especificada.
        summary_cmd = f"display ont info summary 0/{slot}/{port}"
        summary_response = send_command_with_pagination(shell, summary_cmd, timeout=120)

        log_callback(f"{log_prefix} Resposta para '{summary_cmd}': {len(summary_response)} bytes recebidos.")
        logging.debug(f"{log_prefix} Resposta completa recebida:\n{summary_response}")

        # Tratamento de erros comuns na resposta.
        if "Failure: This board does not exist" in summary_response:
             log_callback(f"{log_prefix} Placa não existe. Pulando.")
             return 0
        
        if not summary_response.strip():
             log_callback(f"{log_prefix} Nenhuma resposta para o comando summary.")
             return 0
        
        if "Parameter error" in summary_response:
            log_callback(f"{log_prefix} PON vazia ou comando falhou.")
            save_pon_status(olt_ip, pon_fsp, 0, 0) # Salva no BD que a PON tem 0 ONTs.
            return 0

        # Extrai as informações das ONTs da resposta.
        ont_info_dict, online_count, total_count = extract_ont_info(summary_response)
        log_callback(f"{log_prefix} Encontradas {total_count} ONTs ({online_count} online).")

        # Itera sobre cada ONT encontrada para processar seus detalhes.
        for ont_id_str, info_dict in ont_info_dict.items():
            # Verifica se a coleta foi cancelada pelo usuário na GUI.
            if not gui_window_instance.collection_running: break
            processed_count += process_ont_details(shell, olt_ip, slot, port, ont_id_str, info_dict)
            time.sleep(0.1) # Pequena pausa entre o processamento de cada ONT.

        # Salva o status final da porta PON (total de ONTs online/offline).
        save_pon_status(olt_ip, pon_fsp, online_count, total_count)
        return processed_count

    except Exception as e:
        log_callback(f"{log_prefix} Erro: {e}")
        logging.error(f"{log_prefix} Erro: {e}", exc_info=True)
        return 0
    finally:
        # Garante que a conexão SSH seja sempre fechada, mesmo em caso de erro.
        if client:
            client.close()

def get_active_gpon_slots(shell):
    """
    Executa 'display board 0' para descobrir quais slots têm placas ativas
    e retorna uma lista com suas informações (slot, nome da placa, nº de portas).
    """
    active_boards_info = []
    try:
        # Executa o comando para listar todas as placas no chassi 0.
        board_output = send_command_with_pagination(shell, "display board 0", timeout=30)
        
        # Regex para encontrar linhas que representam uma placa em estado normal/ativo.
        pattern = re.compile(r'^\s*(\d+)\s+([A-Z0-9]+)\s+(Normal|Active_normal|Standby_normal)', re.IGNORECASE)
        
        for line in board_output.splitlines():
            match = pattern.search(line.strip())
            if match:
                slot_id, board_name = int(match.group(1)), match.group(2).upper()
                # Verifica se a placa encontrada está no nosso dicionário de placas conhecidas.
                if board_name in BOARD_PORT_MAP:
                    # Adiciona as informações da placa à lista de placas ativas.
                    active_boards_info.append({
                        "slot": slot_id, 
                        "board_name": board_name, 
                        "ports": BOARD_PORT_MAP[board_name] # Pega o nº de portas do dicionário.
                    })
        return active_boards_info
    except Exception as e:
        logging.error(f"Falha crítica ao obter informações das placas: {e}. Nenhum slot será processado.")
        return [] # Retorna uma lista vazia em caso de erro.

# Em olt/processing.py, substitua a função collect_pon_state inteira por esta:

def collect_pon_state(shell, slot, port):
    """Coleta dados de estado de uma porta PON específica com tratamento robusto de prompts e paginação."""
    fsp = f"0/{slot}/{port}"
    log_prefix = f"[PON State {fsp}]"
    
    try:
        logging.info(f"{log_prefix} Iniciando coleta de estado...")
        
        # Limpa o buffer para garantir que estamos lendo apenas a resposta do nosso comando
        while shell.recv_ready(): shell.recv(4096)

        # 1. Entra no modo de configuração global
        shell.send("config\n")
        time.sleep(0.5)
        
        # 2. Entra no modo de configuração da interface GPON
        command_interface = f"interface gpon 0/{slot}\n"
        shell.send(command_interface)
        time.sleep(0.5)
        
        # 3. Executa o comando de estado para a porta específica
        command_state = f"display port state {port}\n"
        logging.info(f"{log_prefix} Executando comando: {command_state.strip()}")
        shell.send(command_state)
        time.sleep(1) # Espera inicial para o comando começar a retornar dados

        # 4. Lê a resposta completa, lidando com a paginação "---- More ----"
        response = ""
        timeout = time.time() + 45 # Timeout de 45 segundos para a leitura completa
        while time.time() < timeout:
            if shell.recv_ready():
                chunk = shell.recv(8192).decode('utf-8', errors='ignore')
                response += chunk
                
                # Se encontrar o prompt de paginação, envia um espaço
                if "---- More" in chunk:
                    logging.debug(f"{log_prefix} Paginação detectada, enviando espaço.")
                    shell.send(" ")
                    time.sleep(0.8) # Pausa para a próxima página carregar
                    continue # Volta ao início do loop para ler mais
            
            # Condição de saída: se não há mais dados e a resposta contém um prompt de interface, terminamos
            if not shell.recv_ready() and f"(config-if-gpon-0/{slot})" in response:
                break
            
            time.sleep(0.2)
        
        logging.info(f"{log_prefix} Resposta completa recebida ({len(response)} bytes)")

        # 5. Sai dos modos de configuração para limpar o estado do shell para o próximo worker
        shell.send("quit\n")
        time.sleep(0.5)
        shell.send("quit\n")
        time.sleep(0.5)
        
        # 6. Faz o parsing da resposta
        state_data = parse_pon_port_state(response)
        logging.info(f"{log_prefix} Dados de estado parseados com sucesso.")
        return state_data
        
    except Exception as e:
        logging.error(f"{log_prefix} Erro CRÍTICO durante coleta de estado: {e}", exc_info=True)
        # Tenta sair do modo de configuração em caso de erro para não travar o shell
        try:
            shell.send("\nquit\nquit\n")
        except Exception as e_quit:
            logging.error(f"{log_prefix} Erro ao tentar sair do modo de configuração após falha: {e_quit}")
        return None
    
def run_data_collection(olt_ip, username, password, gui_window_instance, log_callback):
    """
    Executa o processo de coleta de dados principal para UMA OLT.
    Esta função roda em uma thread separada para cada OLT selecionada na GUI.
    """
    log_callback(f"[{olt_ip}] Thread de coleta iniciada.")
    main_client = None
    cycle_count = 0
    
    # Loop infinito que controla os ciclos de coleta. Só para se o usuário clicar em "Parar Coleta".
    while gui_window_instance.collection_running:
        cycle_count += 1
        log_callback(f"[{olt_ip}] Iniciando ciclo de coleta #{cycle_count}")
        start_cycle_time = time.time()
        
        try:
            # --- Etapa 1: Conectar e obter a lista de placas ativas ---
            log_callback(f"[{olt_ip}] Conectando para obter placas ativas...")
            main_client, main_shell = connect_to_olt(olt_ip, username, password)
            
            log_callback(f"[{olt_ip}] Conectado. Aguardando estabilização do shell...")
            time.sleep(3)
            while main_shell.recv_ready(): # Limpa o buffer.
                main_shell.recv(4096)
            
            # Entra no modo 'enable'.
            log_callback(f"[{olt_ip}] Enviando 'enable'...")
            main_shell.send("enable\n")
            time.sleep(1)
            
            # Lógica para lidar com o prompt de senha do 'enable'.
            response_buffer = ""
            for _ in range(5):
                if main_shell.recv_ready():
                    response_buffer += main_shell.recv(4096).decode('utf-8', errors='ignore')
                if "Password" in response_buffer or "#" in response_buffer:
                    break
                time.sleep(0.5)

            if "Password" in response_buffer:
                log_callback(f"[{olt_ip}] Senha solicitada. Enviando...")
                main_shell.send(f"{password}\n")
                time.sleep(2)
                while main_shell.recv_ready(): main_shell.recv(4096)
            
            main_shell.send("\n")
            time.sleep(1)
            while main_shell.recv_ready(): main_shell.recv(4096)
            
            # Obtém a lista de placas ativas.
            active_boards_info = get_active_gpon_slots(main_shell)
            main_client.close() # Fecha a conexão principal após obter a lista.
            log_callback(f"[{olt_ip}] Placas ativas encontradas: {len(active_boards_info)}")

            if not active_boards_info:
                log_callback(f"[{olt_ip}] Nenhuma placa GPON/XGPON ativa encontrada. Pulando ciclo.")
                time.sleep(30) # Espera antes de tentar novamente.
                continue

            # --- Etapa 2: Processar todas as portas PON em paralelo ---
            # Cria uma lista de todas as tarefas (uma para cada porta PON).
            pon_tasks = [(b['slot'], p) for b in active_boards_info for p in range(b['ports'])]
            log_callback(f"[{olt_ip}] Total de {len(pon_tasks)} PONs para processar com {NUM_THREADS} threads.")
            
            total_onts_processed_cycle = 0
            # Usa ThreadPoolExecutor para gerenciar as threads.
            with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
                # Submete cada tarefa (processar uma PON) para o executor.
                future_to_pon = {
                    executor.submit(process_pon_worker, olt_ip, username, password, s, p, gui_window_instance, log_callback): f"{s}/{p}" 
                    for s, p in pon_tasks
                }
                # Processa os resultados à medida que as threads terminam.
                for future in as_completed(future_to_pon):
                    if not gui_window_instance.collection_running: break # Para se o usuário cancelou.
                    try:
                        result = future.result() # Pega o resultado (número de ONTs processadas).
                        total_onts_processed_cycle += result
                    except Exception as exc:
                        log_callback(f'[{olt_ip}] PON {future_to_pon[future]} gerou uma exceção: {exc}')

            if not gui_window_instance.collection_running:
                log_callback(f"[{olt_ip}] Coleta interrompida durante o ciclo.")
                break

            # --- Etapa 3: Finalização do ciclo e espera ---
            end_cycle_time = time.time()
            cycle_duration = end_cycle_time - start_cycle_time
            
            # Emite sinais para a GUI atualizar as informações na tela.
            db_signals.ont_cycle_completed.emit(olt_ip, cycle_count, cycle_duration)
            db_signals.data_updated.emit()
            db_signals.pon_status_updated.emit()
            
            # Emitir sinal de atualização de tráfego PON
            db_signals.pon_traffic_updated.emit()
            
            db_signals.pon_port_state_updated.emit()

            # Define o tempo de espera para o próximo ciclo (5 minutos).
            wait_time_seconds = 60
            log_callback(f"[{olt_ip}] Aguardando {wait_time_seconds / 60:.1f} minuto(s) para o próximo ciclo.")
            # Loop de espera que pode ser interrompido a qualquer momento pelo usuário.
            for _ in range(wait_time_seconds):
                if not gui_window_instance.collection_running: break
                time.sleep(1)
                
        except Exception as e:
            log_callback(f"[{olt_ip}] ERRO CRÍTICO: {e}")
            logging.critical(f"[{olt_ip}] Erro CRÍTICO no ciclo de coleta: {str(e)}", exc_info=True)
            if main_client:
                main_client.close()
            break # Interrompe o loop principal em caso de erro crítico.
            
    log_callback(f"[{olt_ip}] Thread de coleta finalizada.")

def run_temp_monitoring(olt_ip, username, password, gui_window_instance):
    """
    Executa o monitoramento de temperatura da OLT em um loop contínuo.
    Esta função roda em sua própria thread.
    """
    client = None
    try:
        # Conecta-se à OLT para a sessão de monitoramento.
        client, shell = connect_to_olt(olt_ip, username, password)
        shell.send("enable\n") # Entra no modo privilegiado.
        time.sleep(1)
        response = shell.recv(1024).decode()
        if "Password" in response: # Lida com o prompt de senha, se houver.
            shell.send(f"{password}\n")
            time.sleep(1)
            shell.recv(1024)

        # Loop principal de monitoramento. Continua enquanto a flag na GUI estiver ativa.
        while gui_window_instance.temp_monitoring_running:
            start_time = time.time()
            gui_window_instance.execution_count += 1 # Incrementa o contador de execuções na GUI.

            # Emite um sinal para a GUI atualizar os contadores e o status.
            db_signals.update_status.emit(
                f"Execuções: {gui_window_instance.execution_count}",
                f"Última execução: {datetime.now().strftime('%H:%M:%S')}",
                "Coletando dados de temperatura..."
            )

            try:
                # Comando para obter as temperaturas das placas.
                temp_output = send_command(shell, "display temperature 0", wait_time=3, timeout=20)
                temp_data = []
                for line in temp_output.splitlines():
                    # Regex para extrair slot, nome da placa e temperatura.
                    match = re.search(
                        r"SlotID:\s+(\d+)\s+BoardName:\s+(\S+)\s+Temperature:\s+(\d+)C\(\s*(\d+)F\)",
                        line.strip()
                    )
                    if match:
                        try:
                            slot_id, board_name, temp_c, temp_f = int(match.group(1)), match.group(2), float(match.group(3)), float(match.group(4))
                            # Define um status (normal, warning, critical) baseado na temperatura.
                            status = "normal"
                            if temp_c > 70: status = "critical"
                            elif temp_c > 60: status = "warning"
                            temp_data.append({'slot_id': slot_id, 'board_name': board_name, 'temp_c': temp_c, 'temp_f': temp_f, 'status': status})
                        except (ValueError, IndexError): continue # Pula a linha se houver erro de conversão.

                if temp_data:
                    inserted = save_temp_data(olt_ip, temp_data) # Salva os dados no banco de dados.
                    db_signals.temp_data_collected.emit(temp_data) # Emite sinal para a GUI atualizar a tabela.
                    db_signals.update_status.emit(f"Execuções: {gui_window_instance.execution_count}", f"Última execução: {datetime.now().strftime('%H:%M:%S')}", f"Dados de temperatura inseridos: {inserted}")
                else:
                    db_signals.update_status.emit(f"Execuções: {gui_window_instance.execution_count}", f"Última execução: {datetime.now().strftime('%H:%M:%S')}", "Nenhum dado de temperatura coletado!")

            except Exception as e:
                 logging.error(f"Erro durante a coleta de temperatura: {e}")
                 db_signals.update_status.emit(f"Execuções: {gui_window_instance.execution_count}", f"Última execução: Erro!", f"Falha: {str(e)[:50]}")

            # Lógica para esperar até o próximo ciclo de 30 segundos.
            execution_time = time.time() - start_time
            sleep_time = max(30 - execution_time, 1)
            for _ in range(int(sleep_time)):
                if not gui_window_instance.temp_monitoring_running: break # Permite interrupção imediata.
                time.sleep(1)

    except Exception as e:
        logging.error(f"Thread de monitoramento de temperatura com erro: {str(e)}")
        db_signals.update_status.emit(f"Execuções: {gui_window_instance.execution_count}", f"Última execução: Erro!", f"Falha: {str(e)}")
    finally:
        if client: client.close() # Garante que a conexão seja fechada.
        db_signals.update_status.emit(f"Execuções: {gui_window_instance.execution_count} (Parado)", f"Última execução: {datetime.now().strftime('%H:%M:%S')}", "Monitoramento de Temperatura parado")

def parse_board_info(board_output):
    """Função auxiliar para extrair slots ativos e nomes de placas da saída do comando 'display board 0'."""
    active_boards = []
    for line in board_output.splitlines():
        match = re.search(r'^\s*(\d+)\s+(\S+)\s+(Normal|Active_normal|Standby_normal)', line.strip(), re.IGNORECASE)
        if match:
            active_boards.append({'slot': int(match.group(1)), 'board_name': match.group(2)})
    return active_boards

def get_slot_cpu_usage(shell, slot):
    """Obtém o uso de CPU para um slot específico."""
    try:
        cpu_output = send_command(shell, f"display cpu 0/{slot}", wait_time=2, timeout=10)
        match = re.search(r"CPU occupancy\s*:\s*(\d+)\s*%", cpu_output)
        return int(match.group(1)) if match else None
    except Exception as e:
        logging.warning(f"Falha ao obter CPU para o slot {slot}: {str(e)}")
        return None

def get_slot_memory_usage(shell, slot):
    """Obtém o uso de memória para um slot específico."""
    try:
        mem_output = send_command(shell, f"display mem 0/{slot}", wait_time=2, timeout=10)
        # Lista de padrões regex para compatibilidade com diferentes versões de firmware.
        patterns = [r"Memory occupancy:\s*(\d+)%", r"Memory Usage Rate:\s*(\d+)%", r"Mem Usage:\s*(\d+)%"]
        for pattern in patterns:
            match = re.search(pattern, mem_output)
            if match: return int(match.group(1))
        logging.warning(f"Nenhum padrão de memória correspondeu para o slot {slot}. Saída: {mem_output[:150]}...")
        return None
    except Exception as e:
        logging.warning(f"Falha ao obter memória para o slot {slot}: {str(e)}")
        return None

def get_resource_status(usage):
    """Determina o status (normal, warning, critical) com base na porcentagem de uso."""
    if usage >= 90: return "critical"
    elif usage >= 70: return "warning"
    return "normal"

def run_resource_monitoring(olt_ip, username, password, gui_window_instance):
    """Loop principal de monitoramento de recursos (CPU e Memória)."""
    client = None
    try:
        client, shell = connect_to_olt(olt_ip, username, password)
        shell.send("enable\n")
        time.sleep(2)
        response = shell.recv(1024).decode()
        if "Password" in response:
            shell.send(f"{password}\n")
            time.sleep(1)
            shell.recv(1024)

        # Loop principal de monitoramento de recursos.
        while gui_window_instance.resource_monitoring_running:
            start_time = time.time()
            gui_window_instance.resource_execution_count += 1
            # Atualiza os contadores na GUI.
            gui_window_instance.resource_execution_counter.setText(f"Execuções: {gui_window_instance.resource_execution_count}")
            gui_window_instance.resource_last_execution_label.setText(f"Última execução: {datetime.now().strftime('%H:%M:%S')}")
            resource_data = []

            try:
                # Obtém a lista de placas ativas.
                board_output = send_command(shell, "display board 0", wait_time=2, timeout=15)
                active_boards = parse_board_info(board_output)

                # Itera sobre cada placa ativa para coletar dados de CPU e memória.
                for board in active_boards:
                    if not gui_window_instance.resource_monitoring_running: break
                    slot, board_name = board['slot'], board['board_name']

                    cpu_usage = get_slot_cpu_usage(shell, slot)
                    if cpu_usage is not None:
                        resource_data.append({'slot': slot, 'board_name': board_name, 'type': 'CPU', 'usage': cpu_usage, 'status': get_resource_status(cpu_usage)})
                    time.sleep(0.5)

                    mem_usage = get_slot_memory_usage(shell, slot)
                    if mem_usage is not None:
                        resource_data.append({'slot': slot, 'board_name': board_name, 'type': 'Memory', 'usage': mem_usage, 'status': get_resource_status(mem_usage)})
                    time.sleep(0.5)

                if resource_data:
                    inserted = save_resource_data(olt_ip, resource_data) # Salva os dados no BD.
                    db_signals.resource_data_collected.emit(resource_data) # Emite sinal para a GUI.
                    status_msg = f"Dados de recursos inseridos: {inserted}"
                else:
                    status_msg = "Nenhum dado de recurso coletado!"

                db_signals.update_status.emit(f"Execuções: {gui_window_instance.resource_execution_count}", f"Última execução: {datetime.now().strftime('%H:%M:%S')}", status_msg)

            except Exception as e:
                 logging.error(f"Erro durante a coleta de recursos: {e}")
                 db_signals.update_status.emit(f"Execuções: {gui_window_instance.resource_execution_count}", f"Última execução: Erro!", f"Falha: {str(e)[:50]}")

            # Lógica de espera para o próximo ciclo de 30 segundos.
            execution_time = time.time() - start_time
            sleep_time = max(30 - execution_time, 1)
            for _ in range(int(sleep_time)):
                if not gui_window_instance.resource_monitoring_running: break
                time.sleep(2)

    except Exception as e:
        logging.error(f"Thread de monitoramento de recursos com erro: {str(e)}")
    finally:
        if client: client.close()
        db_signals.update_status.emit(f"Execuções: {gui_window_instance.resource_execution_count} (Parado)", f"Última execução: {datetime.now().strftime('%H:%M:%S')}", "Monitoramento de Recursos parado")

def collect_pon_traffic(shell, slot, port):
    """Coleta dados de tráfego de uma porta PON específica com logging detalhado."""
    fsp = f"0/{slot}/{port}"
    traffic_data = {}
    log_prefix = f"[PON Traffic {fsp}]"
    
    try:
        logging.info(f"{log_prefix} Iniciando coleta de tráfego...")
        
        # Verificar se estamos no modo correto
        shell.send("\n")
        time.sleep(0.5)
        response = ""
        while shell.recv_ready():
            response += shell.recv(4096).decode('utf-8', errors='ignore')
        
        logging.debug(f"{log_prefix} Prompt atual: {response.strip()}")
        
        # Se não estiver no modo enable, entrar
        if "#" not in response:
            logging.info(f"{log_prefix} Enviando 'enable'...")
            shell.send("enable\n")
            time.sleep(1)
            response = ""
            while shell.recv_ready():
                response += shell.recv(4096).decode('utf-8', errors='ignore')
            logging.debug(f"{log_prefix} Após enable: {response.strip()}")
        
        # Entrar no modo de configuração global
        logging.info(f"{log_prefix} Enviando 'config'...")
        shell.send("config\n")
        time.sleep(1)
        response = ""
        while shell.recv_ready():
            response += shell.recv(4096).decode('utf-8', errors='ignore')
        logging.debug(f"{log_prefix} Após config: {response.strip()}")
        
        if "(config)" not in response:
            logging.error(f"{log_prefix} Falha ao entrar no modo de configuração global. Resposta: {response}")
            return None
        
        # Entrar no modo de configuração da interface GPON
        logging.info(f"{log_prefix} Entrando no modo de configuração: interface gpon 0/{slot}")
        shell.send(f"interface gpon 0/{slot}\n")
        time.sleep(1)
        
        # Verificar se entrou no modo de configuração da interface
        shell.send("\n")
        time.sleep(0.5)
        response = ""
        while shell.recv_ready():
            response += shell.recv(4096).decode('utf-8', errors='ignore')
        
        expected_prompt = f"(config-if-gpon-0/{slot})"
        if expected_prompt not in response:
            logging.error(f"{log_prefix} Falha ao entrar no modo de configuração da interface. Resposta: {response}")
            return None
        
        logging.info(f"{log_prefix} Modo de configuração da interface ativado com sucesso")
        
        # Executar o comando de tráfego para a porta específica
        logging.info(f"{log_prefix} Executando comando: display port traffic {port}")
        shell.send(f"display port traffic {port}\n")
        time.sleep(2)
        
        # Ler a resposta completa
        response = ""
        start_time = time.time()
        timeout = 10  # segundos
        
        while time.time() - start_time < timeout:
            if shell.recv_ready():
                chunk = shell.recv(4096).decode('utf-8', errors='ignore')
                response += chunk
                logging.debug(f"{log_prefix} Recebido chunk ({len(chunk)} bytes)")
            else:
                time.sleep(0.1)
                if not shell.recv_ready():
                    break
        
        logging.info(f"{log_prefix} Resposta completa recebida ({len(response)} bytes)")
        logging.debug(f"{log_prefix} Resposta bruta:\n{response}")
        
        # Verificar se a resposta contém os dados esperados
        if "Traffic Information" not in response:
            logging.error(f"{log_prefix} Resposta não contém 'Traffic Information'")
            return None
        
        # Parse da resposta
        lines = response.splitlines()
        for line in lines:
            line = line.strip()
            logging.debug(f"{log_prefix} Processando linha: {line}")
            
            if "Up traffic (kbps)" in line:
                try:
                    traffic_data['up_traffic_kbps'] = float(line.split(':')[1].strip())
                    logging.info(f"{log_prefix} Up traffic: {traffic_data['up_traffic_kbps']} kbps")
                except (ValueError, IndexError) as e:
                    logging.error(f"{log_prefix} Erro ao parsear Up traffic: {e}")
            elif "Down traffic (kbps)" in line:
                try:
                    traffic_data['down_traffic_kbps'] = float(line.split(':')[1].strip())
                    logging.info(f"{log_prefix} Down traffic: {traffic_data['down_traffic_kbps']} kbps")
                except (ValueError, IndexError) as e:
                    logging.error(f"{log_prefix} Erro ao parsear Down traffic: {e}")
            elif "Traffic of upstream broadcast frames(packets/s)" in line:
                try:
                    traffic_data['upstream_broadcast_pps'] = int(line.split(':')[1].strip())
                    logging.info(f"{log_prefix} Upstream broadcast: {traffic_data['upstream_broadcast_pps']} pps")
                except (ValueError, IndexError) as e:
                    logging.error(f"{log_prefix} Erro ao parsear upstream broadcast: {e}")
            elif "Traffic of upstream multicast frames(packets/s)" in line:
                try:
                    traffic_data['upstream_multicast_pps'] = int(line.split(':')[1].strip())
                    logging.info(f"{log_prefix} Upstream multicast: {traffic_data['upstream_multicast_pps']} pps")
                except (ValueError, IndexError) as e:
                    logging.error(f"{log_prefix} Erro ao parsear upstream multicast: {e}")
            elif "Traffic of upstream unicast frames(packets/s)" in line:
                try:
                    traffic_data['upstream_unicast_pps'] = int(line.split(':')[1].strip())
                    logging.info(f"{log_prefix} Upstream unicast: {traffic_data['upstream_unicast_pps']} pps")
                except (ValueError, IndexError) as e:
                    logging.error(f"{log_prefix} Erro ao parsear upstream unicast: {e}")
            elif "Traffic of downstream broadcast frames(packets/s)" in line:
                try:
                    traffic_data['downstream_broadcast_pps'] = int(line.split(':')[1].strip())
                    logging.info(f"{log_prefix} Downstream broadcast: {traffic_data['downstream_broadcast_pps']} pps")
                except (ValueError, IndexError) as e:
                    logging.error(f"{log_prefix} Erro ao parsear downstream broadcast: {e}")
            elif "Traffic of downstream multicast frames(packets/s)" in line:
                try:
                    traffic_data['downstream_multicast_pps'] = int(line.split(':')[1].strip())
                    logging.info(f"{log_prefix} Downstream multicast: {traffic_data['downstream_multicast_pps']} pps")
                except (ValueError, IndexError) as e:
                    logging.error(f"{log_prefix} Erro ao parsear downstream multicast: {e}")
            elif "Traffic of downstream unicast frames(packets/s)" in line:
                try:
                    traffic_data['downstream_unicast_pps'] = int(line.split(':')[1].strip())
                    logging.info(f"{log_prefix} Downstream unicast: {traffic_data['downstream_unicast_pps']} pps")
                except (ValueError, IndexError) as e:
                    logging.error(f"{log_prefix} Erro ao parsear downstream unicast: {e}")
        
        # Verificar se coletou dados suficientes
        if len(traffic_data) < 8:
            logging.warning(f"{log_prefix} Dados incompletos coletados: {traffic_data}")
        else:
            logging.info(f"{log_prefix} Todos os dados de tráfego coletados com sucesso")
        
        # Sair do modo de configuração da interface
        logging.info(f"{log_prefix} Saindo do modo de configuração da interface...")
        shell.send("quit\n")
        time.sleep(1)
        
        # Sair do modo de configuração global
        logging.info(f"{log_prefix} Saindo do modo de configuração global...")
        shell.send("quit\n")
        time.sleep(1)
        
        return traffic_data
    except Exception as e:
        logging.error(f"{log_prefix} Erro durante coleta de tráfego: {e}", exc_info=True)
        return None
    

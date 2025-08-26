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
        logging.debug(f"Resposta bruta para '{command_details}':\n---\n{response_details}\n---")
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

# Em olt/processing.py, substitua a sua função process_pon_worker por esta:

def process_pon_worker(olt_ip, username, password, slot, port, gui_window_instance, log_callback):
    """
    (VERSÃO FINAL E ROBUSTA) Worker que conecta, gerencia a navegação com verificação de prompt
    e chama as funções de coleta de forma segura.
    """
    client = None
    processed_count = 0
    pon_fsp = f"0/{slot}/{port}"
    log_prefix = f"[{olt_ip}][Worker {slot}/{port}]"
    
    log_callback(f"{log_prefix} Iniciando...")
    time.sleep(random.uniform(0.5, 2.5))
    
    try:
        client, shell = connect_to_olt(olt_ip, username, password, max_retries=2)
        log_callback(f"{log_prefix} Conectado. Preparando para coleta...")
        time.sleep(2)
        while shell.recv_ready(): shell.recv(4096)
        
        # Entra no modo de configuração (enable)
        shell.send("enable\n")
        time.sleep(1)
        
        response_buffer = ""
        for _ in range(5):
            if shell.recv_ready():
                response_buffer += shell.recv(4096).decode('utf-8', errors='ignore')
            if "Password" in response_buffer or "#" in response_buffer:
                break
            time.sleep(0.5)

        if "Password" in response_buffer:
            shell.send(f"{password}\n")
            time.sleep(2)
            while shell.recv_ready(): shell.recv(4096)
        
        # --- INÍCIO DA LÓGICA DE NAVEGAÇÃO ROBUSTA ---

        # 1. Entra no modo de configuração global e VERIFICA
        shell.send("config\n")
        config_response = ""
        config_prompt_found = False
        timeout = time.time() + 10
        while time.time() < timeout:
            if shell.recv_ready():
                config_response += shell.recv(4096).decode('utf-8', errors='ignore')
                if "(config)" in config_response:
                    log_callback(f"{log_prefix} Modo 'config' confirmado.")
                    config_prompt_found = True
                    break
            time.sleep(0.2)
        
        if not config_prompt_found:
            log_callback(f"{log_prefix} ERRO: Falha ao entrar no modo 'config'. Abortando PON.")
            return 0

        # 2. Entra no modo de interface e VERIFICA
        shell.send(f"interface gpon 0/{slot}\n")
        interface_response = ""
        interface_prompt_found = False
        expected_prompt = f"(config-if-gpon-0/{slot})"
        timeout = time.time() + 10
        while time.time() < timeout:
            if shell.recv_ready():
                interface_response += shell.recv(4096).decode('utf-8', errors='ignore')
                if expected_prompt in interface_response:
                    log_callback(f"{log_prefix} Modo 'interface {slot}' confirmado.")
                    interface_prompt_found = True
                    break
            time.sleep(0.2)

        if not interface_prompt_found:
            log_callback(f"{log_prefix} ERRO: Falha ao entrar no modo 'interface {slot}'. Abortando PON.")
            shell.send("quit\n") # Tenta sair do modo config
            return 0

        # 3. Com a navegação confirmada, chama as funções de coleta
        traffic_data = collect_pon_traffic(shell, slot, port)
        if traffic_data:
            save_pon_traffic_data(olt_ip, pon_fsp, traffic_data)
            log_callback(f"{log_prefix} Dados de tráfego salvos.")
        else:
            log_callback(f"{log_prefix} Falha ao coletar dados de tráfego.")
        
        state_data = collect_pon_state(shell, slot, port)
        if state_data:
            save_pon_port_state(olt_ip, pon_fsp, state_data)
            log_callback(f"{log_prefix} Dados de estado salvos.")
        else:
            log_callback(f"{log_prefix} Falha ao coletar dados de estado.")
        
        # 4. Sai dos modos de configuração
        shell.send("quit\n")
        time.sleep(0.5)
        shell.send("quit\n")
        time.sleep(0.5)
        
        # --- FIM DA LÓGICA DE NAVEGAÇÃO ROBUSTA ---

        # A coleta de ONTs continua normalmente no prompt global
        summary_cmd = f"display ont info summary 0/{slot}/{port}"
        summary_response = send_command_with_pagination(shell, summary_cmd, timeout=120)

        if "Failure: This board does not exist" in summary_response:
            log_callback(f"{log_prefix} Placa não existe. Pulando.")
            return 0
        
        if not summary_response.strip() or "Parameter error" in summary_response:
            log_callback(f"{log_prefix} PON vazia ou comando summary falhou.")
            save_pon_status(olt_ip, pon_fsp, 0, 0)
            return 0

        ont_info_dict, online_count, total_count = extract_ont_info(summary_response)
        log_callback(f"{log_prefix} Encontradas {total_count} ONTs ({online_count} online).")
        
        for ont_id_str, info_dict in ont_info_dict.items():
            if not gui_window_instance.collection_running: break
            processed_count += process_ont_details(shell, olt_ip, slot, port, ont_id_str, info_dict)
            time.sleep(0.1)

        save_pon_status(olt_ip, pon_fsp, online_count, total_count)
        return processed_count

    except Exception as e:
        log_callback(f"{log_prefix} Erro no worker: {e}")
        logging.error(f"{log_prefix} Erro no worker: {e}", exc_info=True)
        return 0
    finally:
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

# Em olt/processing.py

def collect_pon_state(shell, slot, port):
    """(VERSÃO SIMPLIFICADA) Apenas executa o comando de estado e faz o parse da saída."""
    fsp = f"0/{slot}/{port}"
    log_prefix = f"[PON State {fsp}]"
    
    try:
        # 1. Executa o comando, assumindo que já está no modo de interface
        command = f"display port state {port}\n"
        logging.info(f"{log_prefix} Executando comando: {command.strip()}")
        shell.send(command)
        time.sleep(1)

        # 2. Lê a resposta completa, lidando com a paginação
        response = ""
        timeout = time.time() + 45
        while time.time() < timeout:
            if shell.recv_ready():
                chunk = shell.recv(8192).decode('utf-8', errors='ignore')
                response += chunk
                if "---- More" in chunk:
                    shell.send(" ")
                    time.sleep(0.8)
            
            # Sai se o prompt da interface for encontrado e não houver mais dados
            elif f"(config-if-gpon-0/{slot})" in response and not shell.recv_ready():
                break
            time.sleep(0.2)
            
        logging.info(f"{log_prefix} Resposta completa recebida ({len(response)} bytes)")

        # 3. Faz o parsing da resposta
        return parse_pon_port_state(response)
        
    except Exception as e:
        logging.error(f"{log_prefix} Erro CRÍTICO durante coleta de estado: {e}", exc_info=True)
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

# Em olt/processing.py

def collect_pon_traffic(shell, slot, port):
    """(VERSÃO SIMPLIFICADA) Apenas executa o comando de tráfego e faz o parse da saída."""
    fsp = f"0/{slot}/{port}"
    log_prefix = f"[PON Traffic {fsp}]"
    
    try:
        # 1. Executa o comando, assumindo que já está no modo de interface
        command = f"display port traffic {port}\n"
        logging.info(f"{log_prefix} Executando comando: {command.strip()}")
        shell.send(command)
        time.sleep(2) # Pausa para a resposta começar a chegar

        # 2. Lê a resposta
        response = ""
        timeout = time.time() + 15
        while time.time() < timeout:
            if shell.recv_ready():
                response += shell.recv(8192).decode('utf-8', errors='ignore')
            elif f"(config-if-gpon-0/{slot})" in response:
                break # Sai do loop se o prompt da interface aparecer no final
            time.sleep(0.2)
        
        logging.info(f"{log_prefix} Resposta recebida ({len(response)} bytes)")

        # 3. Faz o parse da resposta (lógica de parsing movida para cá)
        traffic_data = {}
        for line in response.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()
                try:
                    if "Up traffic (kbps)" in key:
                        traffic_data['up_traffic_kbps'] = float(value)
                    elif "Down traffic (kbps)" in key:
                        traffic_data['down_traffic_kbps'] = float(value)
                    elif "upstream broadcast" in key:
                        traffic_data['upstream_broadcast_pps'] = int(value)
                    elif "upstream multicast" in key:
                        traffic_data['upstream_multicast_pps'] = int(value)
                    elif "upstream unicast" in key:
                        traffic_data['upstream_unicast_pps'] = int(value)
                    elif "downstream broadcast" in key:
                        traffic_data['downstream_broadcast_pps'] = int(value)
                    elif "downstream multicast" in key:
                        traffic_data['downstream_multicast_pps'] = int(value)
                    elif "downstream unicast" in key:
                        traffic_data['downstream_unicast_pps'] = int(value)
                except (ValueError, IndexError):
                    continue
        
        return traffic_data

    except Exception as e:
        logging.error(f"{log_prefix} Erro durante coleta de tráfego: {e}", exc_info=True)
        return None
        
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
    

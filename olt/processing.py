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
import queue
import psycopg2
from config import DB_CONFIG
# --- Importações de Módulos da Aplicação ---
from olt.communication import send_command, connect_to_olt 
# --- INÍCIO DA MODIFICAÇÃO 1: Importações ---
# Substitua a importação existente por esta que inclui todas as funções
from olt.parsing import (extract_service_mac, extract_ont_info, parse_ont_info_details, 
                         parse_pon_port_state, parse_port_info, parse_pon_statistics_packets, 
                         parse_ont_traffic, parse_ont_statistics, parse_ont_eth_statistics,
                         parse_uplink_ddm_response, parse_ont_optical_info)

# Substitua a importação de operations para incluir a nova função
# Substitua a importação existente por esta que inclui todas as funções
from db.operations import (save_ont_data, save_pon_status, save_temp_data, 
                           save_resource_data, save_pon_traffic_data, save_pon_port_state, 
                           save_pon_statistics_packets, save_ont_traffic_bulk, 
                           save_ont_statistics_packets_bulk, save_ont_eth_statistics_bulk,
                           save_uplink_ddm_data)

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
    "XGPD": 8, "H801XGPD": 8, "H802XGBC": 4,
    # Placas GPON (MA5800)
    "H901GPUF": 16, "H902GPLF": 16, "H901GPLF": 16,
    "H903GPSF": 16, "H902GPSF": 16,
    "H902GPUF": 16, # <-- PLACA ADICIONADA PARA OLT-89
    # Placas Combo (MA5800)
    "H907CGHF": 16,
}

def send_command_with_pagination(shell, command, expected_prompt, timeout=30):
    """
    Envia comando SSH com tratamento robusto.
    Retorna a saída do comando limpa.
    """
    full_response = ""
    start_time = time.time()
    
    try:
        # Limpar o buffer antes de enviar
        while shell.recv_ready():
            shell.recv(4096)
        
        logging.debug(f"Enviando comando: {command}")
        shell.send(command + "\n")
        
        # Aguardar um pouco para o comando ser processado
        time.sleep(0.5)
        
        while (time.time() - start_time) < timeout:
            if shell.recv_ready():
                chunk = shell.recv(8192).decode('utf-8', errors='ignore')
                full_response += chunk
                
                # Trata paginação de forma robusta
                if "---- More" in chunk:
                    logging.debug("Paginação detectada. Enviando espaço.")
                    shell.send(" ")
                    time.sleep(0.5)
                    start_time = time.time()  # Reseta o timeout na interação.
                
                # Trata prompts potenciais <cr>
                elif "{ <cr>||<K> }:" in chunk:
                    logging.debug("Prompt <cr> detectado. Enviando Enter.")
                    shell.send("\n")
                    time.sleep(3)
                    start_time = time.time()  # Reseta o timeout na interação.
                    continue              # <<--- ADIÇÃO CRUCIAL


                elif olt_telnet_param_prompt_re.search(chunk.strip().splitlines()[-1]):
                    logging.debug("Prompt <cr> genérico detectado. Enviando Enter e continuando a escuta.")
                    shell.send("\n")
                    time.sleep(3)       # Pequena pausa para a OLT processar o Enter
                    start_time = time.time() # Reseta o timeout
                    continue              # <<--- ADIÇÃO CRUCIAL

                # Verifica marcadores de fim
                elif expected_prompt in full_response:
                    logging.debug(f"Prompt esperado '{expected_prompt}' detectado.")
                    # Espera um pouco mais para garantir que toda a resposta foi recebida
                    time.sleep(0.5)
                    # Limpa qualquer dado adicional que possa ter chegado
                    while shell.recv_ready():
                        full_response += shell.recv(4096).decode('utf-8', errors='ignore')
                    break
            else:
                time.sleep(0.1)

        cleaned = clean_response(full_response)
        logging.debug(f"Resposta completa (limpa): {cleaned[:200]}...")

        # Verifica padrões de erro específicos
        error_patterns = [
            r"^\s*Error:",
            r"^\s*Failure:",
            r"^\s*%",
            r"^\s*\^"
        ]
        
        found_error = False
        error_lines_found = []
        
        for line in cleaned.splitlines():
            for pattern in error_patterns:
                if re.search(pattern, line):
                    found_error = True
                    error_lines_found.append(line.strip())
                    break
                    
        if found_error:
             if not any(ok_msg in cleaned for ok_msg in ["No ONT online", "board does not exist", "PON port does not exist"]):
                 raise Exception(f"Comando retornou um erro: {error_lines_found if error_lines_found else cleaned.strip().splitlines()[-2:]}")

        if not cleaned.strip():
             raise Exception("Resposta vazia recebida")

        return cleaned

    except Exception as e:
        logging.warning(f"Erro no comando '{command}': {str(e)}")
        raise

# Em olt/processing.py, substitua a função process_ont_details por esta versão corrigida:

def process_ont_details(shell, olt_ip, slot, port, ont_id, info):
    """
    Processa os detalhes de uma ÚNICA ONT, coletando MAC (se online)
    e todas as informações detalhadas de status.
    """
    # Importações necessárias dentro da função para evitar dependências circulares
    from olt.parsing import extract_service_mac, parse_ont_info_details
    from db.operations import save_ont_data, get_existing_ont_data
    import json
    
    mac = "N/A"
    ont_details = {}
    fsp_log = f"0/{slot}/{port}/{ont_id}"
    
    try:
        # 1. Coleta de MAC (apenas para ONTs online)
        if info.get("run_state", "").lower() == "online":
            try:
                command_mac = f"display ont wan-info 0/{slot} {port} {ont_id}"
                logging.info(f"[SYSTEM] [{fsp_log}] Executando: {command_mac}")
                response_mac = send_command_with_pagination(shell, command_mac, "#", timeout=30)
                mac = extract_service_mac(response_mac)
            except Exception as e:
                logging.warning(f"[SYSTEM] [{fsp_log}] Falha ao obter MAC: {str(e)}")

        # 2. Coleta de Detalhes Adicionais (para TODAS as ONTs)
        command_details = f"display ont info 0 {slot} {port} {ont_id}"
        logging.info(f"[SYSTEM] [{fsp_log}] Executando: {command_details}")
        response_details = send_command_with_pagination(shell, command_details, "#", timeout=45)
        ont_details = parse_ont_info_details(response_details)
        
        # 3. Busca dados existentes no banco para preservar connection_code e client_name
        logging.debug(f"[DB] [{fsp_log}] Buscando dados existentes para S/N: {info.get('sn', 'N/A')}")
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
            "connection_code": existing_data.get('connection_code', "N/A") if existing_data else "N/A",
            "client_name": existing_data.get('client_name', "N/A") if existing_data else "N/A"
        }
        
        # 5. Combina os detalhes extraídos no dicionário final
        if ont_details:
            collected_data.update(ont_details)
            collected_data['services'] = json.dumps(ont_details.get('services', []))
        
        # 6. Salva o dicionário completo no banco de dados.
        logging.info(f"[DB] [{fsp_log}] Salvando dados na tabela 'ont_data'.")
        logging.debug(f"[DB] [{fsp_log}] Dados a serem salvos: {json.dumps(collected_data, indent=2)}")
        save_ont_data(olt_ip, collected_data)
        return 1
        
    except Exception as e:
        logging.error(f"[SYSTEM] [{fsp_log}] Erro ao processar detalhes da ONT: {str(e)}")
        return 0

def collect_port_info(shell, slot, port):
    """(VERSÃO SIMPLIFICADA) Apenas executa o comando de info e faz o parse da saída."""
    fsp = f"0/{slot}/{port}"
    log_prefix = f"[PON Info {fsp}]"

    try:
        command = f"display port info {port}\n"
        logging.info(f"{log_prefix} Executando comando: {command.strip()}")
        shell.send(command)
        time.sleep(1)

        response = ""
        timeout = time.time() + 10
        while time.time() < timeout:
            if shell.recv_ready():
                response += shell.recv(8192).decode('utf-8', errors='ignore')
            elif f"(config-if-gpon-0/{slot})" in response:
                break
            time.sleep(0.2)

        logging.info(f"{log_prefix} Resposta recebida ({len(response)} bytes)")
        return parse_port_info(response)

    except Exception as e:
        logging.error(f"{log_prefix} Erro durante coleta de info: {e}", exc_info=True)
        return None

# Em olt/processing.py, adicione esta função antes de process_pon_worker

def collect_pon_statistics_packets(shell, slot, port):
    """Apenas executa o comando de estatísticas de pacotes e faz o parse da saída."""
    fsp = f"0/{slot}/{port}"
    log_prefix = f"[PON Stats {fsp}]"

    try:
        command = f"display statistics port ethernet {port}\n"
        logging.info(f"{log_prefix} Executando comando: {command.strip()}")
        shell.send(command)
        time.sleep(1.5) # Este comando pode demorar um pouco mais

        response = ""
        timeout = time.time() + 20
        while time.time() < timeout:
            if shell.recv_ready():
                response += shell.recv(8192).decode('utf-8', errors='ignore')
            elif f"(config-if-gpon-0/{slot})" in response:
                break
            time.sleep(0.2)

        logging.info(f"{log_prefix} Resposta recebida ({len(response)} bytes)")
        return parse_pon_statistics_packets(response)

    except Exception as e:
        logging.error(f"{log_prefix} Erro durante coleta de estatísticas: {e}", exc_info=True)
        return None

# Em olt/processing.py, substitua a função collect_ont_traffic por esta versão corrigida:

def collect_ont_traffic(shell, slot, port):
    """Coleta dados de tráfego de todas as ONTs em uma porta PON."""
    fsp = f"0/{slot}/{port}"
    log_prefix = f"[ONT Traffic {fsp}]"
    
    try:
        # 1. Verificar e garantir que estamos no modo de interface correto
        logging.info(f"{log_prefix} Verificando modo de operação...")
        
        # Enviar um enter para garantir que temos o prompt atual
        shell.send("\n")
        time.sleep(0.5)
        
        # Ler o prompt atual
        prompt_response = ""
        while shell.recv_ready():
            prompt_response += shell.recv(4096).decode('utf-8', errors='ignore')
        
        expected_prompt = f"(config-if-gpon-0/{slot})"
        logging.debug(f"{log_prefix} Prompt atual: {prompt_response.strip()}")
        logging.debug(f"{log_prefix} Prompt esperado: {expected_prompt}")
        
        # Se não estiver no modo correto, tentar entrar
        if expected_prompt not in prompt_response:
            logging.warning(f"{log_prefix} Não estamos no modo de interface correto. Tentando entrar...")
            
            # Sair de qualquer modo de configuração atual
            shell.send("quit\n")
            time.sleep(1)
            
            # Entrar no modo config
            shell.send("config\n")
            time.sleep(1)
            
            # Entrar no modo de interface GPON
            shell.send(f"interface gpon 0/{slot}\n")
            time.sleep(2)
            
            # Verificar novamente o prompt
            shell.send("\n")
            time.sleep(0.5)
            
            prompt_response = ""
            while shell.recv_ready():
                prompt_response += shell.recv(4096).decode('utf-8', errors='ignore')
            
            if expected_prompt not in prompt_response:
                logging.error(f"{log_prefix} Falha ao entrar no modo de interface GPON. Prompt atual: {prompt_response.strip()}")
                return None
            else:
                logging.info(f"{log_prefix} Entrou com sucesso no modo de interface GPON")
        
        # 2. Executar o comando de tráfego
        command = f"display ont traffic {port} all"
        logging.info(f"{log_prefix} Executando comando: {command}")
        
        # Limpar o buffer antes de enviar o comando
        while shell.recv_ready():
            shell.recv(4096)
        
        # Enviar o comando
        shell.send(command + "\n")
        
        # Esperar um pouco para o comando começar a executar
        time.sleep(3)
        
        # 3. Ler a resposta completa com tratamento de paginação
        response = ""
        timeout = time.time() + 90  # Timeout aumentado para 90 segundos
        
        while time.time() < timeout:
            if shell.recv_ready():
                chunk = shell.recv(8192).decode('utf-8', errors='ignore')
                response += chunk
                
                # Verificar se há paginação
                if "---- More" in chunk:
                    logging.info(f"{log_prefix} Paginação detectada. Enviando espaço.")
                    shell.send(" ")
                    time.sleep(1)  # Aumentar o tempo de espera após paginação
                    continue
                
                # Verificar se a resposta está completa
                # A resposta está completa quando encontramos o prompt novamente
                if expected_prompt in response:
                    logging.info(f"{log_prefix} Prompt detectado. Resposta completa.")
                    break
            else:
                time.sleep(0.2)
        
        logging.info(f"{log_prefix} Resposta recebida ({len(response)} bytes)")
        
        # 4. Verificar se houve erro no comando
        if "Unknown command" in response or "Error" in response:
            logging.error(f"{log_prefix} Comando não reconhecido ou erro na execução.")
            logging.error(f"{log_prefix} Resposta: {response[:500]}...")
            return None
        
        # 5. Parsear a resposta
        traffic_data = parse_ont_traffic(response)
        
        if traffic_data:
            logging.info(f"{log_prefix} Parse bem-sucedido. Encontrados {len(traffic_data)} ONTs com dados de tráfego.")
            for item in traffic_data[:3]:  # Logar apenas os primeiros 3 para não poluir
                logging.info(f"{log_prefix} ONT {item['ont_id']}: Up={item['up_traffic']} kbps, Down={item['down_traffic']} kbps")
        else:
            logging.warning(f"{log_prefix} Parse falhou. Nenhum dado de tráfego encontrado.")
            # Logar as primeiras linhas para depuração
            lines = response.splitlines()
            logging.info(f"{log_prefix} Primeiras 10 linhas da resposta:")
            for i, line in enumerate(lines[:10]):
                logging.info(f"{log_prefix} Linha {i}: {line}")
        
        return traffic_data
        
    except Exception as e:
        logging.error(f"{log_prefix} Erro durante coleta de tráfego de ONT: {e}", exc_info=True)
        return None
    
def collect_ont_statistics(shell, slot, port, ont_ids, log_callback):
    """Coleta estatísticas de pacotes para uma lista de ONTs em uma PON, uma por uma."""
    fsp = f"0/{slot}/{port}"
    log_prefix = f"[ONT Stats {fsp}]"
    all_stats = []
    
    if not ont_ids:
        return all_stats
    log_callback(f"{log_prefix} Iniciando coleta de estatísticas para {len(ont_ids)} ONTs...")
    for ont_id in ont_ids:
        try:
            command = f"display statistics ont {port} {ont_id}\n"
            log_callback(f"{log_prefix} Executando comando para ONT ID {ont_id}: {command.strip()}")
            shell.send(command)
            # Pausa curta para não sobrecarregar a OLT com comandos rápidos
            time.sleep(1) 
            
            response = ""
            timeout = time.time() + 15
            while time.time() < timeout:
                if shell.recv_ready():
                    response += shell.recv(4096).decode('utf-8', 'ignore')
                # A saída deste comando é curta, então o prompt da interface é um bom sinal de fim
                elif f"(config-if-gpon-0/{slot})" in response and not shell.recv_ready():
                    break
                time.sleep(0.1)
            
            log_callback(f"{log_prefix} Resposta recebida para ONT ID {ont_id}: {len(response)} bytes")
            
            parsed_data = parse_ont_statistics(response)
            if parsed_data:
                parsed_data['ont_id'] = ont_id
                all_stats.append(parsed_data)
                log_callback(f"{log_prefix} Estatísticas coletadas com sucesso para ONT ID {ont_id}")
            else:
                log_callback(f"{log_prefix} Falha ao parsear estatísticas para ONT ID {ont_id}")
        except Exception as e:
            logging.error(f"{log_prefix} Erro ao coletar estatísticas para ONT ID {ont_id}: {e}")
            log_callback(f"{log_prefix} Erro ao coletar estatísticas para ONT ID {ont_id}: {str(e)}")
            continue # Continua para a próxima ONT em caso de erro
    
    log_callback(f"{log_prefix} Coleta de estatísticas finalizada. {len(all_stats)} ONTs processadas.")
    return all_stats

def process_ont_eth_worker(task_queue, main_window, log_callback):
    """Worker global que processa tarefas de coleta de estatísticas Ethernet das ONTs."""
    log_callback(f"[Worker ONT-ETH] Inicializando worker global...")
    
    while True:
        try:
            task = task_queue.get(timeout=60)  # Aumentado o timeout para 60 segundos
            if task is None:  # Sinal de parada
                log_callback(f"[Worker ONT-ETH] Sinal de parada recebido. Finalizando worker.")
                break
                
            olt_ip = task['olt_ip']
            username = task['username']
            password = task['password']
            slot = task['slot']
            port = task['port']
            ont_id = task['ont_id']
            eth_ports = task['eth_ports']
            
            log_callback(f"[Worker ONT-ETH] Processando tarefa para OLT {olt_ip}, PON {slot}/{port}, ONT ID {ont_id}")
            
            client = None
            try:
                # Conectar à OLT
                client, shell = connect_to_olt(olt_ip, username, password)
                if not client or not shell:
                    log_callback(f"[Worker ONT-ETH] Falha ao conectar à OLT {olt_ip}")
                    continue
                    
                log_callback(f"[Worker ONT-ETH] Conectado com sucesso à OLT {olt_ip}")
                
                # 1. Entrar no modo enable
                log_callback(f"[Worker ONT-ETH] Entrando no modo enable...")
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
                    while shell.recv_ready(): 
                        shell.recv(4096)
                
                # Verificar se estamos no modo enable
                shell.send("\n")
                time.sleep(0.5)
                response_buffer = ""
                while shell.recv_ready():
                    response_buffer += shell.recv(4096).decode('utf-8', errors='ignore')
                
                if "#" not in response_buffer:
                    log_callback(f"[Worker ONT-ETH] ERRO: Não foi possível entrar no modo enable")
                    continue
                
                log_callback(f"[Worker ONT-ETH] Modo enable confirmado")
                
                # 2. Entrar no modo config
                log_callback(f"[Worker ONT-ETH] Entrando no modo config...")
                shell.send("config\n")
                time.sleep(1)
                
                response_buffer = ""
                for _ in range(5):
                    if shell.recv_ready():
                        response_buffer += shell.recv(4096).decode('utf-8', errors='ignore')
                    if "(config)" in response_buffer:
                        break
                    time.sleep(0.5)
                
                if "(config)" not in response_buffer:
                    log_callback(f"[Worker ONT-ETH] ERRO: Não foi possível entrar no modo config")
                    continue
                
                log_callback(f"[Worker ONT-ETH] Modo config confirmado")
                
                # 3. Entrar no modo de interface GPON
                log_callback(f"[Worker ONT-ETH] Entrando no modo de interface GPON...")
                # Tentar diferentes formatos de interface
                interface_formats = [
                    f"interface gpon 0/{slot}"
                ]
                interface_success = False
                expected_prompt = None
                for interface_cmd in interface_formats:
                    log_callback(f"[Worker ONT-ETH] Tentando comando: {interface_cmd}")
                    shell.send(f"{interface_cmd}\n")
                    time.sleep(2)
                    
                    # Enviar um enter para garantir que temos o prompt atual
                    shell.send("\n")
                    time.sleep(1)
                    
                    response_buffer = ""
                    timeout = time.time() + 10
                    while time.time() < timeout:
                        if shell.recv_ready():
                            response_buffer += shell.recv(4096).decode('utf-8', errors='ignore')
                        time.sleep(0.2)
                    
                    # Verificar se estamos no modo de interface correto
                    # O prompt correto é (config-if-gpon-0/{slot})# onde slot é o número do frame
                    if f"(config-if-gpon-0/{slot})#" in response_buffer:
                        expected_prompt = f"(config-if-gpon-0/{slot})#"
                        interface_success = True
                        log_callback(f"[Worker ONT-ETH] Entrou no modo de interface com prompt: {expected_prompt}")
                        break
                if not interface_success:
                    log_callback(f"[Worker ONT-ETH] ERRO: Não foi possível entrar no modo de interface GPON")
                    log_callback(f"[Worker ONT-ETH] Resposta recebida: {response_buffer}")
                    continue
                log_callback(f"[Worker ONT-ETH] Modo de interface GPON confirmado com prompt: {expected_prompt}")
                
                # Lista para armazenar todos os dados coletados
                all_eth_data = []
                
                # Loop sobre as portas Ethernet - CORREÇÃO AQUI
                for eth_port in eth_ports:
                    log_callback(f"[Worker ONT-ETH] Coletando dados da porta Ethernet {eth_port} da ONT {ont_id}")
                    
                    # Tentar diferentes formatos de comando
                    command_formats = [
                        f"display statistics ont-eth {port} {ont_id} ont-port {eth_port}",
                        f"display ont ethernet-port statistics {ont_id} {eth_port}",
                        f"display ont ethernet statistics {ont_id} {eth_port}",
                        f"display ont ethernet-port state {ont_id} {eth_port}"
                    ]
                    
                    eth_data = None
                    for cmd in command_formats:
                        try:
                            log_callback(f"[Worker ONT-ETH] Tentando comando: {cmd}")
                            
                            # Usar a função com paginação
                            output = send_command_with_pagination(shell, cmd, expected_prompt, timeout=20)
                            
                            log_callback(f"[Worker ONT-ETH] Resposta recebida ({len(output)} bytes)")
                            
                            # Se a saída contém dados, tentar parsear
                            if output and "No information" not in output and "Error" not in output and "Unknown command" not in output:
                                # Adicionar log da saída bruta para depuração
                                log_callback(f"[Worker ONT-ETH] Saída bruta:\n{output[:500]}...")
                                
                                # Tentar parsear a saída
                                eth_data = parse_ont_ethernet_stats(output, eth_port)
                                if eth_data:
                                    log_callback(f"[Worker ONT-ETH] Dados parseados com sucesso para porta {eth_port}")
                                    break
                                else:
                                    log_callback(f"[Worker ONT-ETH] Falha ao parsear dados para porta {eth_port}")
                            else:
                                log_callback(f"[Worker ONT-ETH] Comando não retornou dados válidos")
                        except Exception as e:
                            log_callback(f"[Worker ONT-ETH] Erro ao executar comando {cmd}: {str(e)}")
                    
                    if eth_data:
                        all_eth_data.append(eth_data)
                    else:
                        log_callback(f"[Worker ONT-ETH] Nenhum dado coletado para porta {eth_port}")
                
                # Se temos dados, salvar no banco
                if all_eth_data:
                    log_callback(f"[Worker ONT-ETH] Salvando {len(all_eth_data)} registros no banco")
                    save_ont_ethernet_stats(all_eth_data, olt_ip, f"{slot}/{port}", ont_id)
                    log_callback(f"[Worker ONT-ETH] Dados salvos com sucesso no banco")
                else:
                    log_callback(f"[Worker ONT-ETH] Nenhum dado para salvar no banco")
                    
                # Sair dos modos de configuração
                shell.send("quit\n")
                time.sleep(0.5)
                shell.send("quit\n")
                time.sleep(0.5)
                
                # Fechar a conexão
                client.close()
                log_callback(f"[Worker ONT-ETH] Tarefa concluída para ONT {ont_id}")
                
            except Exception as e:
                log_callback(f"[Worker ONT-ETH] Erro ao processar tarefa: {str(e)}")
                if client:
                    client.close()
                    
        except queue.Empty:
            # Timeout ao obter tarefa da fila, continuar o loop
            continue
        except Exception as e:
            # Se ocorrer um erro ao obter a tarefa, continue o loop
            log_callback(f"[Worker ONT-ETH] Erro ao obter tarefa da fila: {str(e)}")
            continue
            
def get_active_gpon_slots(shell):
    """
    Executa 'display board 0' para descobrir quais slots têm placas ativas
    e retorna uma lista com suas informações (slot, nome da placa, nº de portas).
    """
    active_boards_info = []
    try:
        # Executa o comando para listar todas as placas no chassi 0.
        # Adicionando o prompt esperado como argumento (geralmente "#")
        board_output = send_command_with_pagination(shell, "display board 0", "#", timeout=30)
        
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

def process_pon_worker(olt_ip, username, password, slot, port, gui_window_instance, log_callback, eth_task_queue):
    """
    (VERSÃO FINAL E ROBUSTA) Worker que conecta, gerencia a navegação com verificação de prompt
    e chama as funções de coleta de forma segura e na ordem correta.
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
        while shell.recv_ready(): 
            shell.recv(4096)
        
        # --- Etapa 1: Entrar no modo 'enable' ---
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
            while shell.recv_ready(): 
                shell.recv(4096)
        
        # --- Etapa 2: Coleta de dados no prompt global (antes de entrar em 'config') ---
        summary_cmd = f"display ont info summary 0/{slot}/{port}"
        # Adicionando o prompt esperado como argumento
        summary_response = send_command_with_pagination(shell, summary_cmd, "#", timeout=120)
        
        if "Failure: This board does not exist" in summary_response or not summary_response.strip() or "Parameter error" in summary_response:
            log_callback(f"{log_prefix} Placa não existe ou PON vazia. Pulando.")
            save_pon_status(olt_ip, pon_fsp, 0, 0)
            return 0
            
        ont_info_dict, online_count, total_count = extract_ont_info(summary_response)
        log_callback(f"{log_prefix} Encontradas {total_count} ONTs ({online_count} online).")
        save_pon_status(olt_ip, pon_fsp, online_count, total_count)
        
        # Adiciona tarefas para as ONTs online na fila de coleta ETH
        for ont_id_str, info in ont_info_dict.items():
            if info.get("run_state", "").lower() == "online":
                task = {
                    "olt_ip": olt_ip,
                    "username": username,
                    "password": password,
                    "slot": slot,
                    "port": port,
                    "ont_id": int(ont_id_str),
                    "eth_ports": [1, 2, 3, 4] # Coleta das 4 portas padrão
                }
                eth_task_queue.put(task)
                logging.info(f"{log_prefix} Tarefa ETH adicionada à fila para ONT ID {ont_id_str}")
        
        # --- Etapa 3: Navegação para os modos de configuração com verificação ---
        log_callback(f"{log_prefix} Entrando nos modos de configuração...")
        
        # Entra no modo 'config' e verifica se o prompt mudou
        shell.send("config\n")
        config_response = ""
        config_prompt_found = False
        timeout = time.time() + 10
        while time.time() < timeout:
            if shell.recv_ready():
                config_response += shell.recv(4096).decode('utf-8', errors='ignore')
                if "(config)" in config_response:
                    config_prompt_found = True
                    break
            time.sleep(0.2)
        
        if not config_prompt_found:
            log_callback(f"{log_prefix} ERRO: Falha ao entrar no modo 'config'. Abortando PON.")
            return 0
            
        # Entra no modo 'interface' e verifica se o prompt mudou
        shell.send(f"interface gpon 0/{slot}\n")
        interface_response = ""
        interface_prompt_found = False
        expected_prompt = f"(config-if-gpon-0/{slot})"
        timeout = time.time() + 10
        while time.time() < timeout:
            if shell.recv_ready():
                interface_response += shell.recv(4096).decode('utf-8', errors='ignore')
                if expected_prompt in interface_response:
                    interface_prompt_found = True
                    break
            time.sleep(0.2)
            
        if not interface_prompt_found:
            log_callback(f"{log_prefix} ERRO: Falha ao entrar no modo 'interface {slot}'. Abortando PON.")
            shell.send("quit\n") # Tenta sair do modo config
            return 0
            
        # --- Etapa 4: Coleta de dados que exigem modo de interface ---
        
        # Coletar dados de tráfego das ONTs
        logging.info(f"{log_prefix} Coletando dados de tráfego das ONTs...")
        
        # Garantir que estamos no modo correto antes de coletar tráfego
        shell.send("\n")
        time.sleep(0.5)
        
        prompt_response = ""
        while shell.recv_ready():
            prompt_response += shell.recv(4096).decode('utf-8', errors='ignore')
        
        if expected_prompt not in prompt_response:
            logging.warning(f"{log_prefix} Tentando entrar no modo de interface para coleta de tráfego...")
            
            # Sair de qualquer modo de configuração atual
            shell.send("quit\n")
            time.sleep(1)
            
            # Entrar no modo config
            shell.send("config\n")
            time.sleep(1)
            
            # Entrar no modo de interface GPON
            shell.send(f"interface gpon 0/{slot}\n")
            time.sleep(2)
            
            # Verificar se entrou no modo correto
            shell.send("\n")
            time.sleep(0.5)
            
            prompt_response = ""
            while shell.recv_ready():
                prompt_response += shell.recv(4096).decode('utf-8', errors='ignore')
            
            if expected_prompt not in prompt_response:
                logging.error(f"{log_prefix} Falha ao entrar no modo de interface para coleta de tráfego")
                # Se falhar, vamos tentar coletar os outros dados mesmo assim
                log_callback(f"{log_prefix} Continuando com outras coletas mesmo sem tráfego...")
            else:
                log_callback(f"{log_prefix} Entrou no modo de interface corretamente")
        
        # Agora coletar o tráfego
        ont_traffic_list = collect_ont_traffic(shell, slot, port)
        if ont_traffic_list:
            logging.info(f"{log_prefix} Dados de tráfego coletados: {len(ont_traffic_list)} ONTs")
            # Logar os primeiros 3 registros para depuração
            for i, item in enumerate(ont_traffic_list[:3]):
                logging.info(f"{log_prefix} ONT {item['ont_id']}: Up={item['up_traffic']} kbps, Down={item['down_traffic']} kbps")
            save_ont_traffic_bulk(olt_ip, pon_fsp, ont_traffic_list)
        else:
            logging.warning(f"{log_prefix} Nenhum dado de tráfego coletado")
        
        # Coletar outros dados (estado, info, estatísticas)
        traffic_data = collect_pon_traffic(shell, slot, port)
        if traffic_data: 
            save_pon_traffic_data(olt_ip, pon_fsp, traffic_data)
        
        state_data = collect_pon_state(shell, slot, port)
        info_data = collect_port_info(shell, slot, port)
        if state_data and info_data: 
            state_data.update(info_data)
        if state_data: 
            save_pon_port_state(olt_ip, pon_fsp, state_data)
        
        stats_data = collect_pon_statistics_packets(shell, slot, port)
        if stats_data: 
            save_pon_statistics_packets(olt_ip, pon_fsp, stats_data)
            
        # Coleta as estatísticas de pacotes para cada ONT individualmente
        ont_ids_list = [int(ont_id) for ont_id in ont_info_dict.keys()]
        ont_statistics_list = collect_ont_statistics(shell, slot, port, ont_ids_list, log_callback)
        
        if ont_statistics_list:
            save_ont_statistics_packets_bulk(olt_ip, pon_fsp, ont_statistics_list)
        else:
            log_callback(f"{log_prefix} Falha ao coletar estatísticas de pacotes das ONTs.")
        
        # --- Etapa 5: Saída dos modos de configuração ---
        log_callback(f"{log_prefix} Saindo dos modos de configuração...")
        shell.send("quit\n")
        time.sleep(0.5)
        shell.send("quit\n")
        time.sleep(0.5)
        
        # --- Etapa 6: Processamento detalhado das ONTs ---
        for ont_id_str, info_dict in ont_info_dict.items():
            if not gui_window_instance.collection_running: 
                break
            processed_count += process_ont_details(shell, olt_ip, slot, port, ont_id_str, info_dict)
            time.sleep(0.1)
        return processed_count
    except Exception as e:
        log_callback(f"{log_prefix} Erro no worker: {e}")
        logging.error(f"{log_prefix} Erro no worker: {e}", exc_info=True)
        return 0
    finally:
        if client:
            client.close()

def parse_ont_ethernet_stats(output, eth_port):
    """
    Parseia a saída do comando de estatísticas Ethernet da ONT.
    
    Args:
        output (str): Saída bruta do comando
        eth_port (int): Número da porta Ethernet
        
    Returns:
        dict: Dicionário com os dados parseados ou None se falhar
    """
    try:
        # Inicializar dicionário de dados
        data = {
            'eth_port_id': eth_port,
            'rx_frames': 0,
            'tx_frames': 0,
            'rx_bytes': 0,
            'tx_bytes': 0,
            'rx_error_frames': 0,
            'tx_error_frames': 0,
            'tx_collision_frames': 0,
            'duration_seconds': 0
        }
        
        # Dividir a saída em linhas
        lines = output.strip().split('\n')
        
        # Procurar por padrões na saída
        for line in lines:
            line = line.strip()
            
            # Padrão para frames RX
            if "RX frames" in line or "Received frames" in line or "Rx frames" in line:
                match = re.search(r'(\d+)', line)
                if match:
                    data['rx_frames'] = int(match.group(1))
            
            # Padrão para frames TX
            elif "TX frames" in line or "Transmitted frames" in line or "Tx frames" in line:
                match = re.search(r'(\d+)', line)
                if match:
                    data['tx_frames'] = int(match.group(1))
            
            # Padrão para bytes RX
            elif "RX bytes" in line or "Received bytes" in line or "Rx bytes" in line:
                match = re.search(r'(\d+)', line)
                if match:
                    data['rx_bytes'] = int(match.group(1))
            
            # Padrão para bytes TX
            elif "TX bytes" in line or "Transmitted bytes" in line or "Tx bytes" in line:
                match = re.search(r'(\d+)', line)
                if match:
                    data['tx_bytes'] = int(match.group(1))
            
            # Padrão para erros RX
            elif "RX error frames" in line or "Receive error frames" in line or "Rx error frames" in line:
                match = re.search(r'(\d+)', line)
                if match:
                    data['rx_error_frames'] = int(match.group(1))
            
            # Padrão para erros TX
            elif "TX error frames" in line or "Transmit error frames" in line or "Tx error frames" in line:
                match = re.search(r'(\d+)', line)
                if match:
                    data['tx_error_frames'] = int(match.group(1))
            
            # Padrão para colisões TX
            elif "TX collision frames" in line or "Transmit collision frames" in line or "Tx collision frames" in line:
                match = re.search(r'(\d+)', line)
                if match:
                    data['tx_collision_frames'] = int(match.group(1))
            
            # Padrão para duração
            elif "Duration" in line or "Time" in line:
                # Procurar por padrão de tempo como 00:01:23
                time_match = re.search(r'(\d+):(\d+):(\d+)', line)
                if time_match:
                    hours, minutes, seconds = map(int, time_match.groups())
                    data['duration_seconds'] = hours * 3600 + minutes * 60 + seconds
        
        # Verificar se encontramos algum dado útil
        if any(data.values()):
            return data
        else:
            return None
            
    except Exception as e:
        logging.error(f"Erro ao parsear estatísticas Ethernet: {str(e)}")
        return None

def save_ont_ethernet_stats(eth_data_list, olt_ip, fsp, ont_id):
    """
    Salva as estatísticas Ethernet das ONTs no banco de dados.
    """
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # Obter o identificador da OLT
        olt_identifier = olt_ip.replace('.', '_')
        
        for eth_data in eth_data_list:
            # Inserir os dados no banco
            query = """
                INSERT INTO ont_eth_port_statistics (
                    olt_ip, olt_identifier, fsp, ont_id, eth_port_id, collection_time,
                    rx_frames, tx_frames, rx_bytes, tx_bytes,
                    rx_error_frames, tx_error_frames, tx_collision_frames,
                    duration_seconds
                ) VALUES (
                    %s, %s, %s, %s, %s, NOW(),
                    %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
            """
            
            cursor.execute(query, (
                olt_ip,
                olt_identifier, fsp, ont_id, eth_data['eth_port_id'],
                eth_data['rx_frames'], eth_data['tx_frames'],
                eth_data['rx_bytes'], eth_data['tx_bytes'],
                eth_data['rx_error_frames'], eth_data['tx_error_frames'],
                eth_data['tx_collision_frames'], eth_data['duration_seconds']
            ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logging.info(f"Estatísticas Ethernet salvas com sucesso para ONT {ont_id} na PON {fsp}")
        return True
        
    except Exception as e:
        logging.error(f"Erro ao salvar estatísticas Ethernet: {str(e)}")
        if 'conn' in locals():
            conn.rollback()
        return False

def run_data_collection(olt_ip, username, password, gui_window_instance, log_callback, eth_task_queue):
    """
    Executa o processo de coleta de dados principal para UMA OLT.
    Esta função roda em uma thread separada para cada OLT selecionada na GUI.
    """
    log_callback(f"[SYSTEM] [{olt_ip}] Thread de coleta iniciada.")
    main_client = None
    cycle_count = 0
    
    NUM_PON_THREADS = 3 
    while gui_window_instance.collection_running:
        cycle_count += 1
        log_callback(f"[SYSTEM] [{olt_ip}] Iniciando ciclo de coleta #{cycle_count}")
        start_cycle_time = time.time()
        
        try:
            # --- Etapa 1: Conectar e obter a lista de placas ativas ---
            log_callback(f"[SYSTEM] [{olt_ip}] Conectando para obter placas ativas...")
            main_client, main_shell = connect_to_olt(olt_ip, username, password)
            
            log_callback(f"[SYSTEM] [{olt_ip}] Conectado. Aguardando estabilização do shell...")
            time.sleep(3)
            while main_shell.recv_ready():
                main_shell.recv(4096)
            
            log_callback(f"[SYSTEM] [{olt_ip}] Enviando 'enable'...")
            main_shell.send("enable\n")
            time.sleep(1)
            
            response_buffer = ""
            for _ in range(5):
                if main_shell.recv_ready():
                    response_buffer += main_shell.recv(4096).decode('utf-8', errors='ignore')
                if "Password" in response_buffer or "#" in response_buffer:
                    break
                time.sleep(0.5)
            if "Password" in response_buffer:
                log_callback(f"[SYSTEM] [{olt_ip}] Senha solicitada. Enviando...")
                main_shell.send(f"{password}\n")
                time.sleep(2)
                while main_shell.recv_ready(): main_shell.recv(4096)
            
            main_shell.send("\n")
            time.sleep(1)
            while main_shell.recv_ready(): main_shell.recv(4096)
            
            active_boards_info = get_active_gpon_slots(main_shell)
            main_client.close()
            log_callback(f"[SYSTEM] [{olt_ip}] Placas ativas encontradas: {len(active_boards_info)}")
            if not active_boards_info:
                log_callback(f"[SYSTEM] [{olt_ip}] Nenhuma placa GPON/XGPON ativa encontrada. Pulando ciclo.")
                time.sleep(30)
                continue
            # --- Etapa 2: Processar todas as portas PON em paralelo ---
            pon_tasks = [(b['slot'], p) for b in active_boards_info for p in range(b['ports'])]
            log_callback(f"[SYSTEM] [{olt_ip}] Total de {len(pon_tasks)} PONs para processar com {NUM_PON_THREADS} threads.")
            
            total_onts_processed_cycle = 0
            
            # --- Coleta de dados DDM de uplink ---
            try:
                from uplinks_config import UPLINKS
                
                # Obter o nome da OLT a partir do IP
                olt_name = f"OLT {olt_ip.split('.')[-1]}"
                
                # Verificar se há configuração de uplink para esta OLT
                if olt_name in UPLINKS:
                    uplink_configs = UPLINKS[olt_name]
                    log_callback(f"[SYSTEM] [{olt_ip}] Coletando dados DDM de {len(uplink_configs)} uplinks...")
                    
                    # Coletar dados DDM
                    ddm_data_list = collect_uplink_ddm_data(olt_ip, username, password, uplink_configs)
                    
                    if ddm_data_list:
                        # Salvar no banco de dados
                        log_callback(f"[DB] [{olt_ip}] Salvando {len(ddm_data_list)} registros DDM no banco de dados...")
                        save_uplink_ddm_data(olt_ip, ddm_data_list)
                        log_callback(f"[SYSTEM] [{olt_ip}] {len(ddm_data_list)} registros DDM salvos.")
                    else:
                        log_callback(f"[SYSTEM] [{olt_ip}] Nenhum dado DDM coletado.")
                else:
                    log_callback(f"[SYSTEM] [{olt_ip}] Nenhuma configuração de uplink encontrada.")
                    
            except Exception as e:
                log_callback(f"[SYSTEM] [{olt_ip}] Erro na coleta DDM: {e}")
                logging.error(f"[SYSTEM] [{olt_ip}] Erro na coleta DDM: {e}", exc_info=True)


            with ThreadPoolExecutor(max_workers=NUM_PON_THREADS) as executor:
                future_to_pon = {
                    executor.submit(process_pon_worker, olt_ip, username, password, s, p, gui_window_instance, log_callback, eth_task_queue): f"{s}/{p}" 
                    for s, p in pon_tasks
                }
                for future in as_completed(future_to_pon):
                    if not gui_window_instance.collection_running: break
                    try:
                        result = future.result()
                        total_onts_processed_cycle += result
                    except Exception as exc:
                        log_callback(f'[SYSTEM] [{olt_ip}] PON {future_to_pon[future]} gerou uma exceção: {exc}')
            if not gui_window_instance.collection_running:
                log_callback(f"[SYSTEM] [{olt_ip}] Coleta interrompida durante o ciclo.")
                break
            # --- Etapa 3: Finalização do ciclo e espera ---
            end_cycle_time = time.time()
            cycle_duration = end_cycle_time - start_cycle_time
            
            db_signals.ont_cycle_completed.emit(olt_ip, cycle_count, cycle_duration)
            db_signals.data_updated.emit()
            db_signals.pon_status_updated.emit()
            db_signals.pon_traffic_updated.emit()
            db_signals.pon_port_state_updated.emit()
            db_signals.pon_stats_packets_updated.emit()
            db_signals.ont_traffic_data_updated.emit()
            wait_time_seconds = 60
            log_callback(f"[SYSTEM] [{olt_ip}] Aguardando {wait_time_seconds / 60:.1f} minuto(s) para o próximo ciclo.")
            for _ in range(wait_time_seconds):
                if not gui_window_instance.collection_running: break
                time.sleep(1)
                
        except Exception as e:
            log_callback(f"[SYSTEM] [{olt_ip}] ERRO CRÍTICO: {e}")
            logging.critical(f"[SYSTEM] [{olt_ip}] Erro CRÍTICO no ciclo de coleta: {str(e)}", exc_info=True)
            if main_client:
                main_client.close()
            break
            


    eth_task_queue.put(None)
    log_callback(f"[SYSTEM] [{olt_ip}] Thread de coleta finalizada.")

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
                # Adicionando o prompt esperado como argumento
                # Removendo o argumento wait_time
                temp_output = send_command_with_pagination(shell, "display temperature 0", "#", timeout=20)
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
        # Adicionando o prompt esperado como argumento
        # Removendo o argumento wait_time
        cpu_output = send_command_with_pagination(shell, f"display cpu 0/{slot}", "#", timeout=10)
        match = re.search(r"CPU occupancy\s*:\s*(\d+)\s*%", cpu_output)
        return int(match.group(1)) if match else None
    except Exception as e:
        logging.warning(f"Falha ao obter CPU para o slot {slot}: {str(e)}")
        return None

def get_slot_memory_usage(shell, slot):
    """Obtém o uso de memória para um slot específico."""
    try:
        # Adicionando o prompt esperado como argumento
        # Removendo o argumento wait_time
        mem_output = send_command_with_pagination(shell, f"display mem 0/{slot}", "#", timeout=10)
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
                # Obtém a lista de placas ativas.
                # Adicionando o prompt esperado como argumento
                board_output = send_command_with_pagination(shell, "display board 0", "#", timeout=15)
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
    
def collect_uplink_ddm_data(olt_ip, username, password, uplink_configs):
    """Coleta dados DDM das portas de uplink de uma OLT"""
    client = None
    ddm_data_list = []
    
    try:
        client, shell = connect_to_olt(olt_ip, username, password)
        if not client or not shell:
            logging.error(f"[{olt_ip}] Falha ao conectar para coleta DDM.")
            return []
        
        # Entrar no modo enable
        shell.send("enable\n")
        time.sleep(1)
        
        response = ""
        while shell.recv_ready():
            response += shell.recv(4096).decode('utf-8', errors='ignore')
        
        if "Password:" in response:
            shell.send(f"{password}\n")
            time.sleep(2)
            while shell.recv_ready():
                shell.recv(4096)
        
        # Entrar no modo config
        shell.send("config\n")
        time.sleep(1)
        
        response = ""
        while shell.recv_ready():
            response += shell.recv(4096).decode('utf-8', errors='ignore')
        
        if "(config)" not in response:
            logging.error(f"[{olt_ip}] Não foi possível entrar no modo config para coleta DDM.")
            return []
        
        # Para cada configuração de uplink
        for config in uplink_configs:
            placa = config['placa']
            slot = config['slot']
            port = config['port']
            
            try:
                # Determinar o comando de interface baseado no tipo de placa
                interface_cmd = None
                expected_prompt = None
                
                if placa.startswith("H801") or placa.startswith("H802"):
                    # Para placas H801 e H802, o formato é interface giu 0/slot
                    interface_cmd = f"interface giu 0/{slot}"
                    expected_prompt = f"(config-if-giu-0/{slot})"
                elif placa.startswith("H901") or placa.startswith("H902"):
                    # Para placas H901 e H902, o formato é interface xgigabitethernet 0/slot
                    interface_cmd = f"interface xgigabitethernet 0/{slot}"
                    expected_prompt = f"(config-if-xge-0/{slot})"
                else:
                    logging.warning(f"[{olt_ip}] Tipo de placa desconhecido: {placa}")
                    continue
                
                logging.info(f"[{olt_ip}] Tentando comando de interface: {interface_cmd}")
                
                shell.send(f"{interface_cmd}\n")
                time.sleep(1)
                
                response = ""
                while shell.recv_ready():
                    response += shell.recv(4096).decode('utf-8', errors='ignore')
                
                # Verificar se entrou no modo de interface
                if expected_prompt in response:
                    logging.info(f"[{olt_ip}] Entrou no modo de interface com sucesso: {interface_cmd}")
                else:
                    logging.error(f"[{olt_ip}] Não foi possível entrar no modo de interface para {placa} slot {slot}")
                    logging.debug(f"[{olt_ip}] Resposta após tentar entrar no modo de interface:\n{response}")
                    continue
                
                # Enviar o comando DDM - o número da porta é passado como parâmetro
                ddm_cmd = f"display port ddm-info {port}"
                logging.info(f"[{olt_ip}] Enviando comando DDM: {ddm_cmd}")
                shell.send(f"{ddm_cmd}\n")
                time.sleep(2)
                
                # Ler a resposta com tratamento de paginação
                response = ""
                timeout = time.time() + 15
                while time.time() < timeout:
                    if shell.recv_ready():
                        chunk = shell.recv(4096).decode('utf-8', errors='ignore')
                        response += chunk
                        
                        # Tratar paginação
                        if "---- More" in chunk:
                            shell.send(" ")
                            time.sleep(0.5)
                            continue
                        
                        # Verificar se o comando terminou
                        if expected_prompt in response:
                            break
                    time.sleep(0.2)
                
                # Parsear a resposta
                ddm_data = parse_uplink_ddm_response(response)
                if ddm_data:
                    ddm_data['placa'] = placa
                    ddm_data['slot'] = slot
                    ddm_data['port'] = port
                    ddm_data_list.append(ddm_data)
                    logging.info(f"[{olt_ip}] DDM coletado para {placa} slot {slot} port {port}")
                else:
                    logging.warning(f"[{olt_ip}] Falha ao parsear DDM para {placa} slot {slot} port {port}")
                    logging.debug(f"[{olt_ip}] Resposta DDM bruta:\n{response}")
                
                # Sair do modo de interface
                shell.send("quit\n")
                time.sleep(0.5)
                
            except Exception as e:
                logging.error(f"[{olt_ip}] Erro ao coletar DDM para {placa} slot {slot} port {port}: {e}")
                continue
        
        # Sair do modo config
        shell.send("quit\n")
        time.sleep(0.5)
        
        return ddm_data_list
        
    except Exception as e:
        logging.error(f"[{olt_ip}] Erro geral na coleta DDM: {e}")
        return []
    finally:
        if client:
            client.close()
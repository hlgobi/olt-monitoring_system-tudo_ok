# -*- coding: utf-8 -*-

# ==============================================================================
# MÓDULO DE PARSING DE RESPOSTAS DE COMANDOS OLT
# ==============================================================================
# Este arquivo implementa funções especializadas para análise (parsing) das respostas
# de comandos enviados aos equipamentos OLT (Optical Line Terminal). Cada função é
# projetada para extrair informações específicas de diferentes formatos de saída,
# convertendo dados textuais brutos em estruturas de dados organizadas para
# processamento pela aplicação.
#
# As funções utilizam expressões regulares e manipulação de strings para identificar
# e extrair padrões específicos nas respostas dos equipamentos, tratando variações
# de formato e garantindo a robustez do processo de extração de dados.

# ==============================================================================
# IMPORTAÇÕES DE MÓDULOS
# ==============================================================================
import re  # Módulo para operações com expressões regulares, essencial para parsing
import logging  # Módulo para registro de eventos e mensagens do sistema
import time  # Módulo para funções relacionadas a tempo e medições
from datetime import datetime  # Classe para manipulação de datas e horas
from utils.helpers import format_mac  # Função utilitária para formatação de endereços MAC
import json  # Módulo para manipulação de dados no formato JSON

# ==============================================================================
# FUNÇÕES DE PARSING DE RESPOSTAS DE COMANDOS OLT
# ==============================================================================

def extract_service_mac(response):
    """
    Extrai o endereço MAC da resposta do comando 'display ont wan-info'.
    
    Esta função analisa a resposta de um comando que exibe informações WAN da ONT,
    procurando especificamente pelo endereço MAC do serviço. A busca é realizada
    linha por linha para maior robustez, identificando a linha que contém o prefixo
    "MAC address" e extraindo o valor correspondente.
    
    Args:
        response (str): Resposta completa do comando 'display ont wan-info'
    
    Returns:
        str: Endereço MAC formatado ou "N/A" se não encontrado
    """
    # Nível DEBUG: Loga a resposta completa para análise detalhada
    logging.debug(f"[RAW] Resposta para extração de MAC:\n---\n{response}\n---")
    # Nível INFO: Loga um resumo para a GUI
    logging.info(f"[RAW] [extract_service_mac] Resposta recebida ({len(response)} bytes).")
    
    # Importação local para evitar dependência circular
    from utils.helpers import format_mac

    # Itera sobre cada linha da resposta
    for line in response.splitlines():
        clean_line = line.strip().lower()  # Normaliza a linha para busca
        
        # Verifica se a linha contém o prefixo "MAC address"
        if clean_line.startswith("mac address"):
            logging.debug(f"[PARSE] Linha candidata a MAC encontrada: '{line.strip()}'")
            try:
                # Extrai o valor após o caractere ':'
                raw_mac = line.split(":", 1)[1].strip()
                # Formata o MAC usando a função utilitária
                formatted_mac = format_mac(raw_mac)
                logging.debug(f"[PARSE]   -> MAC extraído e formatado: '{formatted_mac}'")
                # Retorna o MAC formatado se for válido
                if formatted_mac != "N/A":
                    logging.info(f"[PARSE] [extract_service_mac] MAC encontrado: {formatted_mac}")
                    return formatted_mac
            except IndexError:
                # Se a linha não contém ':', continua para a próxima
                logging.debug("[PARSE]   -> Falha: A linha não contém ':'.")
                continue
                
    # Se não encontrou nenhum MAC válido
    logging.warning("[PARSE] Endereço MAC não encontrado na resposta.")
    return "N/A"

def extract_ont_info(summary_response):
    """
    Analisa a saída complexa de 'display ont info summary', que contém duas tabelas
    distintas, e combina as informações em um único dicionário por ONT.
    
    Esta função processa uma resposta estruturada em duas seções: a primeira com
    informações de estado das ONTs e a segunda com detalhes como número de série,
    potências de sinal e descrições. A função combina essas informações em um
    único dicionário onde cada chave é o ID da ONT.
    
    Args:
        summary_response (str): Resposta completa do comando 'display ont info summary'
    
    Returns:
        tuple: (ont_data, online_count, total_count) onde:
            - ont_data (dict): Dicionário com informações combinadas por ONT ID
            - online_count (int): Número de ONTs online
            - total_count (int): Número total de ONTs
    """
    # Loga a resposta bruta para análise detalhada
    logging.debug(f"[RAW] Resposta para 'display ont info summary' ({len(summary_response)} bytes):\n---\n{summary_response}\n---")
    logging.info(f"[RAW] [extract_ont_info] Resposta recebida ({len(summary_response)} bytes).")
    
    # Inicializa estruturas de dados
    ont_data = {}
    online_count, total_count = 0, 0

    # Extrai a contagem total e online do cabeçalho da resposta
    summary_header_match = re.search(r"the total of ONTs are:\s*(\d+),\s*online:\s*(\d+)", summary_response)
    if summary_header_match:
        total_count = int(summary_header_match.group(1))
        online_count = int(summary_header_match.group(2))
        logging.debug(f"[PARSE] Contagem do cabeçalho: Total={total_count}, Online={online_count}")
    else:
        logging.warning("[PARSE] Não foi possível extrair a contagem do cabeçalho.")

    # Divide a resposta em duas seções: estado e detalhes
    try:
        parts = re.split(r"(\s*ONT\s+SN\s+Type\s+Distance)", summary_response, flags=re.IGNORECASE)
        state_section = parts[0]  # Primeira parte: informações de estado
        details_section = "".join(parts[1:]) if len(parts) > 1 else ""  # Segunda parte: detalhes
    except Exception as e:
        logging.error(f"[PARSE] Erro ao dividir a resposta em seções: {e}")
        state_section, details_section = summary_response, ""

    # Expressão regular para extrair informações de estado (ID e estado)
    state_pattern = re.compile(r"^\s*(\d+)\s+([a-zA-Z-]+)\s+.*$", re.MULTILINE)
    for match in state_pattern.finditer(state_section):
        logging.debug(f"[PARSE] Linha de Estado: '{match.group(0).strip()}'")
        ont_id, run_state = match.group(1), match.group(2).lower()
        logging.debug(f"[PARSE]   -> Dados extraídos: ONT ID={ont_id}, Estado={run_state}")
        # Armazena o estado da ONT
        ont_data[ont_id] = {"run_state": run_state}

    # Expressão regular para extrair detalhes das ONTs
    details_pattern = re.compile(r"^\s*(\d+)\s+([0-9A-F]{16})\s+(\S+)\s+(\S+)\s+(-?[\d.]+\/-?[\d.]+|\-|\-\/\-)\s+(.*)$", re.MULTILINE | re.IGNORECASE)
    for match in details_pattern.finditer(details_section):
        logging.debug(f"[PARSE] Linha de Detalhes: '{match.group(0).strip()}'")
        ont_id, sn, rx_tx, description = match.group(1), match.group(2), match.group(5), match.group(6).strip()
        # Inicializa valores de potência como N/A
        rx_power, tx_power = ("N/A", "N/A")
        # Se houver valores de potência, extrai-os
        if rx_tx not in ["-", "-/-"]:
            try: 
                rx_power, tx_power = rx_tx.split('/')
            except ValueError: 
                pass
        
        logging.debug(f"[PARSE]   -> Dados extraídos: ONT ID={ont_id}, SN={sn}, Rx/Tx={rx_tx}, Descrição='{description}'")
        # Se a ONT já existe no dicionário, atualiza com os detalhes
        if ont_id in ont_data:
            ont_data[ont_id].update({"sn": sn, "rx_power": rx_power, "tx_power": tx_power, "description": description})
        else:
            # Se não existe, cria um novo registro com estado desconhecido
            logging.warning(f"[PARSE] ONT ID {ont_id} encontrado nos detalhes mas não no estado.")
            ont_data[ont_id] = {"run_state": "unknown", "sn": sn, "rx_power": rx_power, "tx_power": tx_power, "description": description}
    
    # Garante que todas as ONTs tenham todos os campos preenchidos
    final_ont_data = {}
    for ont_id, data in ont_data.items():
        if "sn" not in data:
            logging.warning(f"[PARSE] ONT ID {ont_id} não encontrado nos detalhes. Preenchendo com N/A.")
            data.update({"sn": "N/A", "rx_power": "N/A", "tx_power": "N/A", "description": "N/A"})
        final_ont_data[ont_id] = data

    # Verificação de consistência: se havia ONTs no cabeçalho mas nenhuma foi parseada
    if not final_ont_data and total_count > 0:
        logging.error("[PARSE] Falha crítica: Nenhuma ONT foi parseada, mas o cabeçalho indicava ONTs presentes.")

    logging.info(f"[PARSE] [extract_ont_info] Extração concluída. {len(final_ont_data)} de {total_count} ONTs analisadas.")
    return final_ont_data, online_count, total_count

def parse_ont_info_details(output_text):
    """
    Analisa a saída do comando 'display ont info [f s p] [ont_id] all'
    e extrai informações detalhadas da ONT, limpando os valores.
    
    Esta função processa uma resposta detalhada sobre uma ONT específica, extraindo
    informações como causa da última queda, tempos de atividade, duração online,
    distância, uso de CPU/memória, temperatura, endereço IP e perfis de linha/serviço.
    Também extrai informações sobre os serviços configurados na ONT.
    
    Args:
        output_text (str): Resposta completa do comando 'display ont info ... all'
    
    Returns:
        dict: Dicionário contendo todas as informações detalhadas da ONT
    """
    # Loga a resposta bruta para análise detalhada
    logging.debug(f"[RAW] Resposta para 'display ont info all' ({len(output_text)} bytes):\n---\n{output_text}\n---")
    logging.info(f"[RAW] [parse_ont_info_details] Resposta recebida ({len(output_text)} bytes).")
    
    # Inicializa o dicionário de detalhes com valores padrão
    details = { 
        'last_down_cause': 'N/A', 
        'last_up_time': 'N/A', 
        'last_down_time': 'N/A', 
        'last_dying_gasp_time': 'N/A', 
        'ont_online_duration': 'N/A', 
        'services': [], 
        'ont_distance': 'N/A', 
        'memory_occupation': 'N/A', 
        'cpu_occupation': 'N/A', 
        'temperature': 'N/A', 
        'ont_ip_address': 'N/A', 
        'line_profile_id': 'N/A', 
        'line_profile_name': 'N/A', 
        'service_profile_id': 'N/A', 
        'service_profile_name': 'N/A' 
    }
    
    lines = output_text.splitlines()

    # Processa cada linha da resposta
    for line in lines:
        clean_line = line.strip()
        logging.debug(f"[PARSE] Processando linha de detalhe: '{clean_line}'") 
        # Verifica se a linha contém um separador ':'
        if ":" in clean_line:
            try:
                # Divide a linha em chave e valor
                key, value = clean_line.split(':', 1)
                key, value = key.strip(), value.strip()
                logging.debug(f"[PARSE]   -> Chave: '{key}', Valor: '{value}'")

                # Mapeamento de chaves da resposta para chaves do dicionário
                key_map = { 
                    "Last down cause": "last_down_cause", 
                    "Last up time": "last_up_time", 
                    "Last down time": "last_down_time", 
                    "Last dying gasp time": "last_dying_gasp_time", 
                    "ONT online duration": "ont_online_duration", 
                    "ONT distance(m)": "ont_distance", 
                    "Memory occupation": "memory_occupation", 
                    "CPU occupation": "cpu_occupation", 
                    "Temperature": "temperature", 
                    "ONT IP 0 address/mask": "ont_ip_address", 
                    "Line profile ID": "line_profile_id", 
                    "Line profile name": "line_profile_name", 
                    "Service profile ID": "service_profile_id", 
                    "Service profile name": "service_profile_name" 
                }
                
                # Se a chave está no mapeamento, processa o valor
                if key in key_map:
                    details_key = key_map[key]
                    # Para temperatura, remove caracteres não numéricos
                    if details_key == 'temperature': 
                        value = re.sub(r'[^0-9.]', '', value)
                    # Armazena o valor no dicionário
                    details[details_key] = value
                    logging.debug(f"[PARSE]   -> Mapeado e salvo: {details_key} = {value}")
            except ValueError: 
                continue
        # Verifica se a linha inicia com tipos de serviço (ETH, IPHOST, VEIP)
        elif clean_line.startswith(('ETH', 'IPHOST', 'VEIP')):
            parts = clean_line.split()
            if len(parts) >= 4:
                # Extrai informações do serviço
                service_info = { 
                    'type': parts[0], 
                    'port_id': parts[1], 
                    'service_type': parts[2], 
                    'vlan_id': parts[3] 
                }
                details['services'].append(service_info)
                logging.debug(f"[PARSE]   -> Serviço extraído: {service_info}")

    # Loga o resultado completo em formato JSON para análise
    logging.debug(f"[PARSE] [parse_ont_info_details] Resultado completo: {json.dumps(details, indent=2)}")
    logging.info(f"[PARSE] [parse_ont_info_details] Extração concluída. Chaves: {', '.join(k for k, v in details.items() if v != 'N/A' and v != [])}")
    return details

def parse_pon_port_state(response):
    """
    Analisa a saída do comando 'display port state <port>' e extrai as informações.
    
    Esta função processa informações de estado de uma porta PON, incluindo estado
    atual, causa da última queda, tempos de atividade/inatividade, detecção de sinal,
    status do módulo óptico, estado do laser, falhas de TX e diversos parâmetros
    operacionais como temperatura, corrente de polarização, tensão e potência.
    
    Args:
        response (str): Resposta completa do comando 'display port state <port>'
    
    Returns:
        dict: Dicionário contendo todas as informações de estado da porta PON
    """
    # Loga a resposta bruta para análise detalhada
    logging.debug(f"[RAW] Resposta para 'display port state' ({len(response)} bytes):\n---\n{response}\n---")
    logging.info(f"[RAW] [parse_pon_port_state] Resposta recebida ({len(response)} bytes).")
    state_data = {}
    
    # Mapeamento de chaves da resposta para chaves do dicionário
    key_map = {
        'Port state': 'port_state', 
        'Last down cause': 'last_down_cause',
        'Last up time': 'last_up_time', 
        'Last down time': 'last_down_time',
        'Signal detect': 'signal_detect', 
        'Available bandwidth(Kbps)': 'available_bandwidth_kbps',
        'Illegal rogue ONT': 'illegal_rogue_ont', 
        'Optical Module status': 'optical_module_status',
        'Laser state': 'laser_state', 
        'TX fault': 'tx_fault',
        'Temperature(C)': 'temperature_c', 
        'TX Bias current(mA)': 'tx_bias_current_ma',
        'Supply Voltage(V)': 'supply_voltage_v', 
        'TX power(dBm)': 'tx_power_dbm',
    }

    # Processa cada linha da resposta
    for line in response.splitlines():
        line = line.strip()
        # Ignora linhas vazias ou linhas de separação
        if not line or line.startswith("-"): 
            continue
            
        # Divide a linha em chave e valor usando múltiplos espaços como separador
        parts = re.split(r'\s{2,}', line, 1)
        if len(parts) == 2:
            key, value = parts[0].strip(), parts[1].strip()
            logging.debug(f"[PARSE] Processando linha de estado PON: '{line}' -> Chave: '{key}', Valor: '{value}'")
            
            # Se a chave está no mapeamento, processa o valor
            if key in key_map:
                db_key = key_map[key]
                
                # Trata valores especiais
                if value == '-': 
                    state_data[db_key] = None
                # Trata campos de data/hora
                elif db_key in ['last_up_time', 'last_down_time']:
                    try:
                        # Converte a string para objeto datetime
                        dt_obj = datetime.strptime(value.split('-')[0], '%d/%m/%Y %H:%M:%S')
                        state_data[db_key] = dt_obj
                    except (ValueError, IndexError): 
                        state_data[db_key] = None
                # Trata campo de banda (converte para inteiro)
                elif db_key == 'available_bandwidth_kbps':
                    try: 
                        state_data[db_key] = int(value)
                    except ValueError: 
                        state_data[db_key] = None
                # Trata campos numéricos (converte para float)
                elif db_key in ['temperature_c', 'tx_bias_current_ma', 'supply_voltage_v', 'tx_power_dbm']:
                    try: 
                        state_data[db_key] = float(value)
                    except ValueError: 
                        state_data[db_key] = None
                # Para outros campos, armazena como string
                else: 
                    state_data[db_key] = value
                    
                logging.debug(f"[PARSE]   -> Mapeado: {db_key} = {state_data[db_key]}")

    # Loga o resultado completo em formato JSON para análise
    logging.debug(f"[PARSE] [parse_pon_port_state] Resultado completo: {json.dumps(state_data, default=str, indent=2)}")
    logging.info(f"[PARSE] [parse_pon_port_state] Extração concluída. Chaves: {', '.join(state_data.keys())}")
    return state_data

def parse_port_info(response):
    """
    Analisa a saída do comando 'display port info <port>' e extrai informações.
    
    Esta função processa informações básicas de uma porta, incluindo a largura de banda
    garantida disponível e o estado administrativo da porta.
    
    Args:
        response (str): Resposta completa do comando 'display port info <port>'
    
    Returns:
        dict: Dicionário contendo as informações básicas da porta
    """
    # Loga a resposta bruta para análise detalhada
    logging.debug(f"[RAW] Resposta para 'display port info' ({len(response)} bytes):\n---\n{response}\n---")
    logging.info(f"[RAW] [parse_port_info] Resposta recebida ({len(response)} bytes).")
    
    # Inicializa o dicionário com valores padrão
    info_data = {
        'left_guaranteed_bandwidth_kbps': None,
        'admin_state': None
    }
    
    # Mapeamento de chaves da resposta para chaves do dicionário
    key_map = {
        "Left guaranteed bandwidth(kbps)": "left_guaranteed_bandwidth_kbps",
        "Admin State": "admin_state"
    }

    # Processa cada linha da resposta
    for line in response.splitlines():
        # Divide a linha em chave e valor usando múltiplos espaços como separador
        parts = re.split(r'\s{2,}', line.strip(), 1)
        if len(parts) == 2:
            key, value = parts[0].strip(), parts[1].strip()
            logging.debug(f"[PARSE] Processando linha de info da porta: '{line.strip()}' -> Chave: '{key}', Valor: '{value}'")
            
            # Se a chave está no mapeamento, processa o valor
            if key in key_map:
                db_key = key_map[key]
                
                # Trata campo de banda (converte para inteiro)
                if db_key == 'left_guaranteed_bandwidth_kbps':
                    try: 
                        info_data[db_key] = int(value)
                    except (ValueError, TypeError): 
                        info_data[db_key] = None
                # Para outros campos, armazena como string
                else: 
                    info_data[db_key] = value
                    
                logging.debug(f"[PARSE]   -> Mapeado: {db_key} = {info_data[db_key]}")

    # Loga o resultado completo em formato JSON para análise
    logging.debug(f"[PARSE] [parse_port_info] Resultado completo: {json.dumps(info_data, indent=2)}")
    logging.info(f"[PARSE] [parse_port_info] Extração concluída. Chaves: {', '.join(info_data.keys())}")
    return info_data

def parse_pon_statistics_packets(response):
    """
    Analisa a saída do 'display statistics port ethernet' e extrai os contadores.
    
    Esta função processa estatísticas de tráfego de uma porta Ethernet, incluindo
    contadores de frames e bytes recebidos/enviados, frames unicast/multicast/broadcast,
    frames por tamanho, frames descartados e frames com erro.
    
    Args:
        response (str): Resposta completa do comando 'display statistics port ethernet'
    
    Returns:
        dict: Dicionário contendo todas as estatísticas de tráfego da porta
    """
    # Loga a resposta bruta para análise detalhada
    logging.debug(f"[RAW] Resposta para 'display statistics port ethernet' ({len(response)} bytes):\n---\n{response}\n---")
    logging.info(f"[RAW] [parse_pon_statistics_packets] Resposta recebida ({len(response)} bytes).")
    stats_data = {}
    
    # Mapeamento de chaves da resposta para chaves do dicionário
    key_map = {
        'Received frames': 'rx_frames', 
        'Received bytes': 'rx_bytes',
        'Received unicast frames': 'rx_unicast_frames', 
        'Received multicast frames': 'rx_multicast_frames',
        'Received broadcast frames': 'rx_broadcast_frames', 
        'Received 64-byte frames': 'rx_64_byte_frames',
        'Received 65~127-byte frames': 'rx_65_127_byte_frames', 
        'Received 128~255-byte frames': 'rx_128_255_byte_frames',
        'Received 256~511-byte frames': 'rx_256_511_byte_frames', 
        'Received 512~1023-byte frames': 'rx_512_1023_byte_frames',
        'Received 1024~1518-byte frames': 'rx_1024_1518_byte_frames', 
        'Received over 1518-byte frames': 'rx_over_1518_byte_frames',
        'Received undersize discarded frames': 'rx_undersize_discarded_frames', 
        'Received oversize discarded frames': 'rx_oversize_discarded_frames',
        'Received CRC error frames': 'rx_crc_error_frames', 
        'Received discarded frames': 'rx_discarded_frames',
        'Received error frames': 'rx_error_frames',
        'Sent frames': 'tx_frames', 
        'Sent bytes': 'tx_bytes',
        'Sent unicast frames': 'tx_unicast_frames', 
        'Sent multicast frames': 'tx_multicast_frames',
        'Sent broadcast frames': 'tx_broadcast_frames', 
        'Sent 64-byte frames': 'tx_64_byte_frames',
        'Sent 65~127-byte frames': 'tx_65_127_byte_frames', 
        'Sent 128~255-byte frames': 'tx_128_255_byte_frames',
        'Sent 256~511-byte frames': 'tx_256_511_byte_frames', 
        'Sent 512~1023-byte frames': 'tx_512_1023_byte_frames',
        'Sent 1024~1518-byte frames': 'tx_1024_1518_byte_frames', 
        'Sent over 1518-byte frames': 'tx_over_1518_byte_frames',
        'Sent buffer overflow frames': 'tx_buffer_overflow_frames'
    }

    # Processa cada linha da resposta
    for line in response.splitlines():
        # Verifica se a linha contém um separador ':'
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            
            # Se a chave está no mapeamento, processa o valor
            if key in key_map:
                logging.debug(f"[PARSE] Processando linha de estatísticas PON: '{line.strip()}'")
                
                # Extrai o valor numérico usando expressão regular
                numeric_value = re.search(r'^\s*(\d+)', value.strip())
                if numeric_value:
                    try:
                        db_key = key_map[key]
                        # Converte para inteiro e armazena
                        stats_data[db_key] = int(numeric_value.group(1))
                        logging.debug(f"[PARSE]   -> Mapeado: {db_key} = {stats_data[db_key]}")
                    except (ValueError, TypeError): 
                        continue
    
    # Loga o resultado completo em formato JSON para análise
    logging.debug(f"[PARSE] [parse_pon_statistics_packets] Resultado completo: {json.dumps(stats_data, indent=2)}")
    logging.info(f"[PARSE] [parse_pon_statistics_packets] Extração concluída. {len(stats_data)} estatísticas encontradas.")
    return stats_data

def parse_ont_traffic(response, ont_id_target=None):
    """
    Analisa a saída do 'display ont traffic'.
    Lida com o formato de múltiplas ONTs ('all') e de ONT única.
    
    Esta função processa informações de tráfego de ONTs, podendo lidar com dois formatos
    de resposta: um formato tabular para múltiplas ONTs e um formato de pares chave-valor
    para uma única ONT. No formato tabular, extrai o ID da ONT e os tráfegos de upload
    e download. No formato de ONT única, utiliza o ID fornecido como parâmetro.
    
    Args:
        response (str): Resposta completa do comando 'display ont traffic'
        ont_id_target (int, optional): ID da ONT para formato de resposta única. Padrão: None
    
    Returns:
        list: Lista de dicionários, cada um contendo:
              - ont_id (int): ID da ONT
              - up_traffic (float): Tráfego de upload em kbps
              - down_traffic (float): Tráfego de download em kbps
    """
    # Loga a resposta bruta para análise detalhada
    logging.debug(f"[RAW] Resposta para 'display ont traffic' ({len(response)} bytes):\n---\n{response}\n---")
    logging.info(f"[RAW] [parse_ont_traffic] Resposta recebida ({len(response)} bytes).")
    traffic_list = []
    lines = response.splitlines()
    
    # Tenta identificar o formato de múltiplas ONTs (formato tabular)
    header_found = False
    for i, line in enumerate(lines):
        if "ONT ID" in line and "Up traffic" in line and "Down traffic" in line:
            header_found = True
            # Processa as linhas de dados após o cabeçalho
            for data_line in lines[i+1:]:
                # Ignora linhas de separação
                if data_line.strip().startswith("---"): 
                    continue
                    
                logging.debug(f"[PARSE] Processando linha de tráfego ONT (múltiplo): '{data_line.strip()}'")
                
                # Divide a linha usando espaços como separador
                parts = re.split(r'\s+', data_line.strip())
                if len(parts) >= 3:
                    try:
                        # Extrai os dados e converte para os tipos apropriados
                        data = { 
                            "ont_id": int(parts[0]), 
                            "up_traffic": float(parts[1]), 
                            "down_traffic": float(parts[2]) 
                        }
                        traffic_list.append(data)
                        logging.debug(f"[PARSE]   -> Tráfego extraído: {data}")
                    except (ValueError, IndexError): 
                        continue
            break
    
    # Se não encontrou o formato de múltiplas ONTs, tenta o formato de ONT única
    if not header_found:
        logging.debug("[PARSE] Cabeçalho de múltiplas ONTs não encontrado, tentando parse de ONT única.")
        up_traffic, down_traffic = None, None
        
        # Processa cada linha em busca dos campos de tráfego
        for line in lines:
            logging.debug(f"[PARSE] Processando linha de tráfego ONT (único): '{line.strip()}'")
            
            # Extrai tráfego de upload
            if "Up traffic (kbps)" in line:
                try: 
                    up_traffic = float(line.split(':')[1].strip())
                except (ValueError, IndexError): 
                    pass
                    
            # Extrai tráfego de download
            elif "Down traffic (kbps)" in line:
                try: 
                    down_traffic = float(line.split(':')[1].strip())
                except (ValueError, IndexError): 
                    pass
        
        # Se encontrou ambos os valores e tem um ID de ONT alvo
        if up_traffic is not None and down_traffic is not None and ont_id_target is not None:
            data = { 
                "ont_id": ont_id_target, 
                "up_traffic": up_traffic, 
                "down_traffic": down_traffic 
            }
            traffic_list.append(data)
            logging.debug(f"[PARSE]   -> Tráfego (único) extraído: {data}")

    # Verifica se encontrou algum dado de tráfego
    if not traffic_list:
        logging.warning("[PARSE] [parse_ont_traffic] Nenhum dado de tráfego de ONT pôde ser extraído.")
    else:
        # Loga o resultado completo em formato JSON para análise
        logging.debug(f"[PARSE] [parse_ont_traffic] Resultado completo: {json.dumps(traffic_list, indent=2)}")
        logging.info(f"[PARSE] [parse_ont_traffic] Extração concluída. {len(traffic_list)} registro(s) de tráfego encontrado(s).")
    
    return traffic_list

def parse_ont_statistics(response):
    """
    Analisa a saída do 'display statistics ont' e extrai os contadores.
    
    Esta função processa estatísticas de tráfego de uma ONT, incluindo contadores
    de frames e bytes upstream/downstream e frames descartados. A função utiliza
    um mapeamento flexível para lidar com variações na nomenclatura dos campos.
    
    Args:
        response (str): Resposta completa do comando 'display statistics ont'
    
    Returns:
        dict: Dicionário contendo todas as estatísticas da ONT
    """
    # Loga a resposta bruta para análise detalhada
    logging.debug(f"[RAW] Resposta para 'display statistics ont' ({len(response)} bytes):\n---\n{response}\n---")
    logging.info(f"[RAW] [parse_ont_statistics] Resposta recebida ({len(response)} bytes).")
    stats_data = {}
    
    # Mapeamento de chaves da resposta para chaves do dicionário
    # Inclui variações na nomenclatura para maior robustez
    key_map = {
        "Upstream frames": "upstream_frames", 
        "Upstream bytes": "upstream_bytes",
        "Upstream discarded frames": "upstream_discarded_frames", 
        "Downstream frames": "downstream_frames",
        "Downstream bytes": "downstream_bytes", 
        "Downstream discarded frames": "downstream_discarded_frames",
        # Variações de nomenclatura
        "Rx frames": "upstream_frames", 
        "Rx bytes": "upstream_bytes",
        "Rx discarded frames": "upstream_discarded_frames", 
        "Tx frames": "downstream_frames",
        "Tx bytes": "downstream_bytes", 
        "Tx discarded frames": "downstream_discarded_frames",
    }
    
    # Verifica se a resposta está vazia
    if not response:
        logging.warning("[PARSE] parse_ont_statistics: Resposta vazia recebida.")
        return {}
    
    # Processa cada linha da resposta
    for line in response.splitlines():
        line = line.strip()
        if not line: 
            continue
            
        # Verifica se a linha contém um separador ':'
        if ":" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                key, value_str = parts[0].strip(), parts[1].strip()
                logging.debug(f"[PARSE] Processando linha de estatísticas ONT: '{line.strip()}'")
                
                # Tenta encontrar uma correspondência no mapeamento (case insensitive)
                for map_key, db_key in key_map.items():
                    if map_key.lower() in key.lower():
                        try:
                            # Extrai o valor numérico usando expressão regular
                            numeric_match = re.search(r'(\d+)', value_str)
                            if numeric_match:
                                # Converte para inteiro e armazena
                                stats_data[db_key] = int(numeric_match.group(1))
                                logging.debug(f"[PARSE]   -> Mapeado: {db_key} = {stats_data[db_key]}")
                            break
                        except (ValueError, TypeError) as e:
                            logging.warning(f"[PARSE] Erro ao converter valor '{value_str}' para {db_key}: {e}")
                            break
    
    # Loga o resultado completo em formato JSON para análise
    logging.debug(f"[PARSE] [parse_ont_statistics] Resultado completo: {json.dumps(stats_data, indent=2)}")
    logging.info(f"[PARSE] [parse_ont_statistics] Extração concluída. Chaves: {', '.join(stats_data.keys())}")
    return stats_data
    
def parse_ont_eth_statistics(response):
    """
    Analisa a saída do comando 'display statistics ont-eth ...' e extrai os contadores.
    
    Esta função processa estatísticas de interface Ethernet de uma ONT, incluindo
    contadores de frames e bytes recebidos/enviados, frames unicast/multicast/broadcast,
    frames com erro, frames descartados, frames de colisão e duração da estatística.
    
    Args:
        response (str): Resposta completa do comando 'display statistics ont-eth ...'
    
    Returns:
        dict: Dicionário contendo todas as estatísticas Ethernet da ONT
    """
    # Loga a resposta bruta para análise detalhada
    logging.debug(f"[RAW] Resposta para 'display statistics ont-eth' ({len(response)} bytes):\n---\n{response}\n---")
    logging.info(f"[RAW] [parse_ont_eth_statistics] Resposta recebida ({len(response)} bytes).")
    stats_data = {}
    
    # Mapeamento de chaves da resposta para chaves do dicionário
    key_map = {
        "Received frames": "rx_frames", 
        "Received bytes": "rx_bytes",
        "Received unicast frames": "rx_unicast_frames", 
        "Received multicast frames": "rx_multicast_frames",
        "Received broadcast frames": "rx_broadcast_frames", 
        "Received error frames": "rx_error_frames",
        "Received discarded frames": "rx_discarded_frames", 
        "Sent frames": "tx_frames",
        "Sent bytes": "tx_bytes", 
        "Sent unicast frames": "tx_unicast_frames",
        "Sent multicast frames": "tx_multicast_frames", 
        "Sent broadcast frames": "tx_broadcast_frames",
        "Sent error frames": "tx_error_frames", 
        "Sent discarded frames": "tx_discarded_frames",
        "Sent collision frames": "tx_collision_frames", 
        "Statistics duration(s)": "duration_seconds",
    }
    
    # Verifica se a resposta está vazia
    if not response:
        logging.warning("[PARSE] parse_ont_eth_statistics: Resposta vazia recebida.")
        return {}
    
    # Processa cada linha da resposta
    for line in response.splitlines():
        line = line.strip()
        # Ignora linhas vazias ou linhas sem separador ':'
        if not line or ":" not in line: 
            continue
            
        parts = line.split(":", 1)
        if len(parts) == 2:
            key, value_str = parts[0].strip(), parts[1].strip()
            logging.debug(f"[PARSE] Processando linha de estatísticas ONT ETH: '{line.strip()}'")
            
            # Tenta encontrar uma correspondência no mapeamento (case insensitive)
            for map_key, db_key in key_map.items():
                if map_key.lower() in key.lower():
                    try:
                        # Extrai o valor numérico usando expressão regular
                        numeric_match = re.search(r'(\d+)', value_str)
                        if numeric_match:
                            # Converte para inteiro e armazena
                            stats_data[db_key] = int(numeric_match.group(1))
                            logging.debug(f"[PARSE]   -> Mapeado: {db_key} = {stats_data[db_key]}")
                        break
                    except (ValueError, TypeError) as e:
                        logging.warning(f"[PARSE] Erro ao converter valor '{value_str}' para {db_key}: {e}")
                        break
    
    # Loga o resultado completo em formato JSON para análise
    logging.debug(f"[PARSE] [parse_ont_eth_statistics] Resultado completo: {json.dumps(stats_data, indent=2)}")
    logging.info(f"[PARSE] [parse_ont_eth_statistics] Extração concluída. Chaves: {', '.join(stats_data.keys())}")
    return stats_data

def parse_uplink_ddm_response(response):
    """
    Analisa a saída do comando 'display port ddm-info'.
    
    Esta função processa informações de monitoramento digital de diagnóstico (DDM)
    de uma porta uplink, incluindo temperatura, tensão de alimentação, corrente de
    polarização do laser, potência de TX e RX.
    
    Args:
        response (str): Resposta completa do comando 'display port ddm-info'
    
    Returns:
        dict or None: Dicionário contendo as informações DDM ou None se não encontrar dados
    """
    # Loga a resposta bruta para análise detalhada
    logging.debug(f"[RAW] Resposta para 'display port ddm-info' ({len(response)} bytes):\n---\n{response}\n---")
    logging.info(f"[RAW] [parse_uplink_ddm_response] Resposta recebida ({len(response)} bytes).")
    ddm_data = {}
    
    try:
        # Processa cada linha da resposta
        for line in response.splitlines():
            line = line.strip()
            # Verifica se a linha contém um separador ':'
            if ":" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    key, value = parts[0].strip(), parts[1].strip()
                    logging.debug(f"[PARSE] Processando linha DDM: '{line}'")
                    
                    # Extrai e converte temperatura
                    if "Temperature(C)" in key:
                        if (m := re.search(r'([-+]?\d*\.?\d+)', value)): 
                            ddm_data['temperature_c'] = float(m.group(1))
                            
                    # Extrai e converte tensão de alimentação
                    elif "Supply voltage(V)" in key:
                        if (m := re.search(r'([-+]?\d*\.?\d+)', value)): 
                            ddm_data['supply_voltage_v'] = float(m.group(1))
                            
                    # Extrai e converte corrente de polarização
                    elif "TX bias current(mA)" in key:
                        if (m := re.search(r'([-+]?\d*\.?\d+)', value)): 
                            ddm_data['tx_bias_current_ma'] = float(m.group(1))
                            
                    # Extrai e converte potência de TX
                    elif "TX power(dBm)" in key:
                        if (m := re.search(r'([-+]?\d*\.?\d+)', value)): 
                            ddm_data['tx_power_dbm'] = float(m.group(1))
                            
                    # Extrai e converte potência de RX
                    elif "RX power(dBm)" in key:
                        if (m := re.search(r'([-+]?\d*\.?\d+)', value)): 
                            ddm_data['rx_power_dbm'] = float(m.group(1))
        
        # Verifica se encontrou algum dado DDM
        if ddm_data:
            # Loga o resultado completo em formato JSON para análise
            logging.debug(f"[PARSE] [parse_uplink_ddm_response] Resultado completo: {json.dumps(ddm_data, indent=2)}")
            logging.info(f"[PARSE] [parse_uplink_ddm_response] Extração concluída. Chaves: {', '.join(ddm_data.keys())}")
            return ddm_data
        else:
            return None
            
    except Exception as e:
        logging.error(f"[PARSE] Erro ao parsear resposta DDM: {e}")
        return None

def parse_ont_version_details(raw_output: str) -> dict:
    """
    Analisa a saída do comando 'display ont version' e extrai os detalhes da ONT.
    
    Esta função processa informações de versão de uma ONT, incluindo ID do fornecedor,
    versão da ONT, ID do produto, ID do equipamento, versões de software e descrição
    do produto. A descrição do produto é tratada especialmente para remover quebras
    de linha e espaços excessivos.
    
    Args:
        raw_output (str): Resposta completa do comando 'display ont version'
    
    Returns:
        dict: Dicionário contendo todas as informações de versão da ONT
    """
    # Loga a resposta bruta para análise detalhada
    logging.debug(f"[RAW] Resposta para 'display ont version' ({len(raw_output)} bytes):\n---\n{raw_output}\n---")
    logging.info(f"[RAW] [parse_ont_version_details] Resposta recebida ({len(raw_output)} bytes).")
    
    # Inicializa o dicionário com valores padrão
    details = { 
        'vendor_id': None, 
        'ont_version': None, 
        'product_id': None, 
        'equipment_id': None, 
        'main_software_version': None, 
        'standby_software_version': None, 
        'ont_product_description': None, 
        'support_xml_version': None 
    }

    # Extrai a descrição do produto usando expressão regular
    desc_match = re.search(r"OntProductDescription\s+:\s*(.*?)\s+Support XML Version", raw_output, re.DOTALL)
    if desc_match:
        description_raw = desc_match.group(1).strip()
        # Limpa a descrição: remove quebras de linha e espaços excessivos
        description_clean = re.sub(r'\s+', ' ', description_raw.replace('\r', '').replace('\n', ' '))
        details['ont_product_description'] = description_clean

    # Processa cada linha da resposta
    for line in raw_output.splitlines():
        # Verifica se a linha contém um separador ':'
        if ':' in line:
            key, value = map(str.strip, line.split(':', 1))
            logging.debug(f"[PARSE] Processando linha de versão: '{line.strip()}'")
            
            # Mapeamento de chaves da resposta para chaves do dicionário
            key_map = { 
                "Vendor-ID": "vendor_id", 
                "ONT Version": "ont_version", 
                "Product-ID": "product_id", 
                "Equipment-ID": "equipment_id", 
                "Main Software Version": "main_software_version", 
                "Standby Software Version": "standby_software_version", 
                "Support XML Version": "support_xml_version" 
            }
            
            # Se a chave está no mapeamento, armazena o valor
            if key in key_map:
                db_key = key_map[key]
                details[db_key] = value
                logging.debug(f"[PARSE]   -> Mapeado: {db_key} = {value}")

    # Loga o resultado completo em formato JSON para análise
    logging.debug(f"[PARSE] [parse_ont_version_details] Resultado completo: {json.dumps(details, indent=2)}")
    logging.info(f"[PARSE] [parse_ont_version_details] Extração concluída. Chaves: {', '.join(k for k, v in details.items() if v is not None)}")
    return details

def parse_ont_optical_info(raw_output: str) -> dict:
    """
    Analisa a saída do comando 'display ont optical-info' e extrai os detalhes ópticos.
    
    Esta função processa informações ópticas de uma ONT, incluindo tipo de módulo,
    subtipo, tipo de encapsulamento, nome do fornecedor, número de peça, número de série,
    código de data, potências, tensão, corrente de polarização e limites de alarme.
    
    Args:
        raw_output (str): Resposta completa do comando 'display ont optical-info'
    
    Returns:
        dict: Dicionário contendo todas as informações ópticas da ONT
    """
    # Loga a resposta bruta para análise detalhada
    logging.debug(f"[RAW] Resposta para 'display ont optical-info' ({len(raw_output)} bytes):\n---\n{raw_output}\n---")
    logging.info(f"[RAW] [parse_ont_optical_info] Resposta recebida ({len(raw_output)} bytes).")
    details = {}
    
    # Mapeamento de chaves da resposta para chaves do dicionário
    key_map = {
        "Module type": "optical_module_type", 
        "Module sub-type": "optical_module_subtype",
        "Encapsulation Type": "optical_encapsulation_type", 
        "Vendor name": "optical_vendor_name",
        "Vendor PN": "optical_vendor_pn", 
        "Vendor SN": "optical_vendor_sn", 
        "Date Code": "optical_date_code",
        "OLT Rx ONT optical power(dBm)": "optical_olt_rx_ont_power_dbm", 
        "Voltage(V)": "ont_voltage_v",
        "Laser bias current(mA)": "ont_tx_bias_current_ma", 
        "Rx power current alarm threshold(dBm)": "optical_rx_power_alarm",
        "Tx power current alarm threshold(dBm)": "optical_tx_power_alarm",
        "Tx bias current alarm threshold(mA)": "optical_bias_current_alarm",
        "Temperature alarm threshold(C)": "optical_temperature_alarm",
        "Supply voltage alarm threshold(V)": "optical_voltage_alarm"
    }

    # Processa cada linha da resposta
    for line in raw_output.splitlines():
        # Verifica se a linha contém um separador ':'
        if ":" in line:
            try:
                key, value = [x.strip() for x in line.split(":", 1)]
                logging.debug(f"[PARSE] Processando linha de info óptica: '{line.strip()}'")
                
                # Se a chave está no mapeamento, processa o valor
                if key in key_map:
                    db_key = key_map[key]
                    
                    # Trata valores especiais (indicadores de ausência de dados)
                    if value in ['-', 'N/A', '[-,-]']:
                        details[db_key] = None
                        continue

                    # Para campos numéricos específicos, extrai e converte o valor
                    if db_key in ['optical_olt_rx_ont_power_dbm', 'ont_voltage_v', 'ont_tx_bias_current_ma']:
                        numeric_match = re.search(r'([-+]?\d*\.?\d+)', value)
                        details[db_key] = float(numeric_match.group(1)) if numeric_match else None
                    else:
                        # Para outros campos, armazena como string
                        details[db_key] = value
                    
                    logging.debug(f"[PARSE]   -> Mapeado: {db_key} = {details[db_key]}")
            except (ValueError, IndexError): 
                continue

    # Loga o resultado completo em formato JSON para análise
    logging.debug(f"[PARSE] [parse_ont_optical_info] Resultado completo: {json.dumps(details, indent=2)}")
    logging.info(f"[PARSE] [parse_ont_optical_info] Extração concluída. Chaves: {', '.join(details.keys())}")
    return details
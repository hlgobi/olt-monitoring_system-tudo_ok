# olt/parsing.py

import re
import logging
import time
from datetime import datetime
from utils.helpers import format_mac 
# Em olt/parsing.py, substitua a função extract_service_mac por esta:

def extract_service_mac(response):
    """
    Extrai o endereço MAC da resposta do comando 'display ont wan-info'.
    Itera linha por linha para maior robustez.
    """
    # Importa a função de formatação necessária
    from utils.helpers import format_mac

    for line in response.splitlines():
        # Usa .strip() para remover espaços e .lower() para comparação sem case
        clean_line = line.strip().lower()
        
        # Procura pela linha que começa com "mac address"
        if clean_line.startswith("mac address"):
            try:
                # Pega tudo que vem depois do caractere ":"
                raw_mac = line.split(":", 1)[1].strip()
                
                # Usa a função auxiliar para limpar e formatar o MAC
                formatted_mac = format_mac(raw_mac)
                
                if formatted_mac != "N/A":
                    # Se encontrou e formatou com sucesso, retorna o valor
                    return formatted_mac
            except IndexError:
                # Caso a linha contenha "mac address" mas não tenha um ":"
                # Apenas continua para a próxima linha
                continue
                
    # Se o loop terminar e não encontrar nenhum MAC, retorna "N/A"
    return "N/A"

def extract_ont_info(summary_response):
    """
    Analisa a saída complexa de 'display ont info summary', que contém duas tabelas
    distintas, e combina as informações em um único dicionário por ONT.
    """
    logging.info("--- Iniciando função extract_ont_info ---")
    
    ont_data = {}
    online_count = 0
    total_count = 0

    # 1. Extrai a contagem total e online do cabeçalho principal da resposta.
    summary_header_match = re.search(r"the total of ONTs are:\s*(\d+),\s*online:\s*(\d+)", summary_response)
    if summary_header_match:
        total_count = int(summary_header_match.group(1))
        online_count = int(summary_header_match.group(2))
        logging.info(f"Contagem do cabeçalho extraída: Total={total_count}, Online={online_count}")
    else:
        logging.warning("Não foi possível extrair a contagem do cabeçalho da resposta.")

    # 2. Divide a resposta nas duas seções principais (estado e detalhes).
    try:
        parts = re.split(r"(\s*ONT\s+SN\s+Type\s+Distance)", summary_response, flags=re.IGNORECASE)
        state_section = parts[0]
        details_section = ""
        if len(parts) > 1:
            details_section = "".join(parts[1:])
    except Exception as e:
        logging.error(f"Erro ao dividir a resposta do summary em seções: {e}")
        state_section = summary_response
        details_section = ""

    # 3. Analisa a primeira seção (Run State, UpTime, DownTime).
    state_pattern = re.compile(r"^\s*(\d+)\s+([a-zA-Z-]+)\s+.*$", re.MULTILINE)
    for match in state_pattern.finditer(state_section):
        ont_id = match.group(1)
        run_state = match.group(2).lower()
        ont_data[ont_id] = {"run_state": run_state}

    # 4. Analisa a segunda seção (SN, Type, Power, Description).
    details_pattern = re.compile(
        r"^\s*(\d+)\s+"                      # 1: ONT ID
        r"([0-9A-F]{16})\s+"                  # 2: SN (hexadecimal - 16 caracteres)
        r"(\S+(?:-\d{1,2})?)\s+"              # 3: Type (pode ter hífens e números, como EG8145X6-10)
        r"(\S+)\s+"                          # 4: Distance
        r"(-?[\d.]+\/-?[\d.]+|\-|\-\/\-)\s+"  # 5: Rx/Tx power (ex: -12.34/2.56 ou - ou -/-)
        r"(.*)$",                            # 6: Description (o resto da linha)
        re.MULTILINE | re.IGNORECASE
    )
    
    for match in details_pattern.finditer(details_section):
        ont_id = match.group(1)
        sn = match.group(2)
        rx_tx = match.group(5)
        description = match.group(6).strip()

        rx_power, tx_power = "N/A", "N/A"
        if rx_tx not in ["-", "-/-"]:
            try:
                rx_power, tx_power = rx_tx.split('/')
            except ValueError:
                pass 

        if ont_id in ont_data:
            ont_data[ont_id].update({
                "sn": sn,
                "rx_power": rx_power,
                "tx_power": tx_power,
                "description": description
            })
        else:
            logging.warning(f"ONT ID {ont_id} encontrado na seção de detalhes, mas não na de estado.")
            ont_data[ont_id] = {
                "run_state": "unknown", "sn": sn, "rx_power": rx_power,
                "tx_power": tx_power, "description": description
            }
    
    # 5. Garante que todas as ONTs tenham todos os campos.
    final_ont_data = {}
    for ont_id, data in ont_data.items():
        if "sn" not in data:
            logging.warning(f"ONT ID {ont_id} não encontrado na seção de detalhes. Preenchendo com N/A.")
            data["sn"] = "N/A"
            data["rx_power"] = "N/A"
            data["tx_power"] = "N/A"
            data["description"] = "N/A"
        final_ont_data[ont_id] = data

    if not final_ont_data and total_count > 0:
        logging.error(f"Falha ao analisar qualquer dado de ONT da resposta, embora o cabeçalho indique {total_count} ONTs.")

    logging.info(f"Extração concluída. {len(final_ont_data)} ONTs analisadas. Contagem do cabeçalho: Total={total_count}, Online={online_count}")
    return final_ont_data, online_count, total_count
# Em olt/parsing.py, substitua a função parse_ont_info_details por esta:

def parse_ont_info_details(output_text):
    """
    Analisa a saída do comando 'display ont info [f s p] [ont_id] all'
    e extrai informações detalhadas da ONT, limpando os valores.
    """
    logging.debug("--- Iniciando função parse_ont_info_details (versão aprimorada) ---")
    details = {
        'last_down_cause': 'N/A',
        'last_up_time': 'N/A',
        'last_down_time': 'N/A',
        'last_dying_gasp_time': 'N/A',
        'services': [],
        'ont_distance': 'N/A',
        'memory_occupation': 'N/A',
        'cpu_occupation': 'N/A',
        'temperature': 'N/A',
        'ont_ip_address': 'N/A',
        'line_profile_id': 'N/A',
        'line_profile_name': 'N/A', # Já existia, mas mantemos para clareza
        'service_profile_id': 'N/A', # Adicionado
        'service_profile_name': 'N/A'
    }

    lines = output_text.splitlines()

    for line in lines:
        clean_line = line.strip()

        if ":" in clean_line:
            try:
                key, value = clean_line.split(':', 1)
                key = key.strip()
                value = value.strip()

                # Mapeamento de chaves para os nomes no nosso dicionário
                key_map = {
                    "Last down cause": "last_down_cause",
                    "Last up time": "last_up_time",
                    "Last down time": "last_down_time",
                    "Last dying gasp time": "last_dying_gasp_time",
                    "ONT distance(m)": "ont_distance",
                    "Memory occupation": "memory_occupation",
                    "CPU occupation": "cpu_occupation",
                    "Temperature": "temperature", # CORRIGIDO: Chave sem (C)
                    "ONT IP 0 address/mask": "ont_ip_address",
                    "Line profile ID": "line_profile_id",
                    "Line profile name": "line_profile_name",
                    "Service profile ID": "service_profile_id", # Chave adicionada
                    "Service profile name": "service_profile_name"
                }

                if key in key_map:
                    details_key = key_map[key]
                    
                    # Limpeza de valores específicos
                    if details_key == 'temperature':
                        # Remove '(C)' e outros caracteres não numéricos do valor
                        value = re.sub(r'[^0-9.]', '', value)
                    
                    details[details_key] = value

            except ValueError:
                # Ignora linhas que têm ":" mas não estão no formato chave: valor
                continue

        # Lógica para extrair serviços (VLANs)
        elif clean_line.startswith(('ETH', 'IPHOST', 'VEIP')):
            parts = clean_line.split()
            if len(parts) >= 4:
                service_info = {
                    'type': parts[0],
                    'port_id': parts[1],
                    'service_type': parts[2],
                    'vlan_id': parts[3]
                }
                details['services'].append(service_info)

    logging.debug(f"Detalhes da ONT extraídos (versão aprimorada): {details}")
    return details

def parse_pon_port_state(response):
    """
    Analisa a saída do comando 'display port state <port>' e extrai as informações.
    """
    state_data = {}
    
    # Mapeamento de chaves do output para chaves do nosso dicionário
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

    for line in response.splitlines():
        line = line.strip()
        if not line or line.startswith("-"):
            continue

        parts = re.split(r'\s{2,}', line, 1) # Divide em chave e valor onde há 2 ou mais espaços
        if len(parts) == 2:
            key, value = parts[0].strip(), parts[1].strip()
            
            if key in key_map:
                db_key = key_map[key]
                
                # Tratamento especial para cada tipo de dado
                if value == '-':
                    state_data[db_key] = None
                elif db_key in ['last_up_time', 'last_down_time']:
                    try:
                        # Formato: 16/08/2025 03:18:39-03:00
                        dt_obj = datetime.strptime(value.split('-')[0], '%d/%m/%Y %H:%M:%S')
                        state_data[db_key] = dt_obj
                    except (ValueError, IndexError):
                        state_data[db_key] = None
                elif db_key == 'available_bandwidth_kbps':
                    try:
                        state_data[db_key] = int(value)
                    except ValueError:
                        state_data[db_key] = None
                elif db_key in ['temperature_c', 'tx_bias_current_ma', 'supply_voltage_v', 'tx_power_dbm']:
                    try:
                        state_data[db_key] = float(value)
                    except ValueError:
                        state_data[db_key] = None
                else:
                    state_data[db_key] = value

    return state_data
# --- FIM DA MODIFICAÇÃO ---

# Em olt/parsing.py, adicione esta nova função

def parse_port_info(response):
    """
    Analisa a saída do comando 'display port info <port>' e extrai informações.
    """
    info_data = {
        'left_guaranteed_bandwidth_kbps': None,
        'admin_state': None
    }
    key_map = {
        "Left guaranteed bandwidth(kbps)": "left_guaranteed_bandwidth_kbps",
        "Admin State": "admin_state"
    }

    for line in response.splitlines():
        parts = re.split(r'\s{2,}', line.strip(), 1)
        if len(parts) == 2:
            key, value = parts[0].strip(), parts[1].strip()
            if key in key_map:
                db_key = key_map[key]
                if db_key == 'left_guaranteed_bandwidth_kbps':
                    try:
                        info_data[db_key] = int(value)
                    except (ValueError, TypeError):
                        info_data[db_key] = None
                else:
                    info_data[db_key] = value
    
    return info_data

# Em olt/parsing.py, adicione esta nova função

def parse_pon_statistics_packets(response):
    """Analisa a saída do 'display statistics port ethernet' e extrai os contadores."""
    stats_data = {}
    key_map = {
        'Received frames': 'rx_frames', 'Received bytes': 'rx_bytes',
        'Received unicast frames': 'rx_unicast_frames', 'Received multicast frames': 'rx_multicast_frames',
        'Received broadcast frames': 'rx_broadcast_frames', 'Received 64-byte frames': 'rx_64_byte_frames',
        'Received 65~127-byte frames': 'rx_65_127_byte_frames', 'Received 128~255-byte frames': 'rx_128_255_byte_frames',
        'Received 256~511-byte frames': 'rx_256_511_byte_frames', 'Received 512~1023-byte frames': 'rx_512_1023_byte_frames',
        'Received 1024~1518-byte frames': 'rx_1024_1518_byte_frames', 'Received over 1518-byte frames': 'rx_over_1518_byte_frames',
        'Received undersize discarded frames': 'rx_undersize_discarded_frames', 'Received oversize discarded frames': 'rx_oversize_discarded_frames',
        'Received CRC error frames': 'rx_crc_error_frames', 'Received discarded frames': 'rx_discarded_frames',
        'Received error frames': 'rx_error_frames',
        'Sent frames': 'tx_frames', 'Sent bytes': 'tx_bytes',
        'Sent unicast frames': 'tx_unicast_frames', 'Sent multicast frames': 'tx_multicast_frames',
        'Sent broadcast frames': 'tx_broadcast_frames', 'Sent 64-byte frames': 'tx_64_byte_frames',
        'Sent 65~127-byte frames': 'tx_65_127_byte_frames', 'Sent 128~255-byte frames': 'tx_128_255_byte_frames',
        'Sent 256~511-byte frames': 'tx_256_511_byte_frames', 'Sent 512~1023-byte frames': 'tx_512_1023_byte_frames',
        'Sent 1024~1518-byte frames': 'tx_1024_1518_byte_frames', 'Sent over 1518-byte frames': 'tx_over_1518_byte_frames',
        'Sent buffer overflow frames': 'tx_buffer_overflow_frames'
    }

    for line in response.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            if key in key_map:
                # O valor é o primeiro número encontrado na string de valor
                numeric_value = re.search(r'^\s*(\d+)', value.strip())
                if numeric_value:
                    try:
                        stats_data[key_map[key]] = int(numeric_value.group(1))
                    except (ValueError, TypeError):
                        continue
    return stats_data

# Em olt/parsing.py, adicione esta nova função ao final do arquivo

# Em olt/parsing.py, substitua a função parse_ont_traffic por esta versão corrigida:

def parse_ont_traffic(response):
    """Analisa a saída do 'display ont traffic' e retorna uma lista de dicionários."""
    traffic_list = []
    lines = response.splitlines()
    
    # Procurar pelo cabeçalho da tabela
    header_found = False
    header_line = ""
    
    for i, line in enumerate(lines):
        # Procurar pelo cabeçalho exato da OLT
        if "ONT ID" in line and "Up traffic" in line and "Down traffic" in line:
            header_found = True
            header_line = line
            logging.info(f"Cabeçalho encontrado na linha {i}: {line}")
            
            # As próximas linhas são os dados
            for data_line in lines[i+1:]:
                data_line = data_line.strip()
                if not data_line:
                    continue
                    
                # Pular linhas que não são dados (como separadores)
                if data_line.startswith("---") or "Command is being executed" in data_line:
                    continue
                    
                # Tentar extrair os números da linha
                # Padrão: número seguido de dois números
                parts = re.split(r'\s+', data_line)
                if len(parts) >= 3:
                    try:
                        ont_id = int(parts[0])
                        up_traffic = float(parts[1])
                        down_traffic = float(parts[2])
                        
                        traffic_list.append({
                            "ont_id": ont_id,
                            "up_traffic": up_traffic,
                            "down_traffic": down_traffic
                        })
                        
                        logging.debug(f"ONT {ont_id}: Up={up_traffic} kbps, Down={down_traffic} kbps")
                        
                    except (ValueError, IndexError) as e:
                        logging.warning(f"Erro ao parsear linha de tráfego: {data_line} - {e}")
                        continue
            break
    
    if not header_found:
        logging.warning("Cabeçalho da tabela de tráfego não encontrado na resposta.")
        # Logar as primeiras 20 linhas para depuração
        logging.info("=== INÍCIO DA RESPOSTA BRUTA ===")
        for i, line in enumerate(lines[:20]):
            logging.info(f"Linha {i}: {line}")
        logging.info("=== FIM DA RESPOSTA BRUTA ===")
    else:
        logging.info(f"Parse bem-sucedido. Encontrados {len(traffic_list)} ONTs com dados de tráfego.")
    
    return traffic_list

def parse_ont_statistics(response):
    """Analisa a saída do 'display statistics ont' e extrai os contadores."""
    stats_data = {}
    
    # Mapeamento mais completo de possíveis chaves
    key_map = {
        # Recebimento (RX)
        "Upstream frames": "upstream_frames",
        "Upstream bytes": "upstream_bytes",
        "Upstream discarded frames": "upstream_discarded_frames",
        "Downstream frames": "downstream_frames",
        "Downstream bytes": "downstream_bytes",
        "Downstream discarded frames": "downstream_discarded_frames",
        # Variações possíveis
        "Rx frames": "upstream_frames",
        "Rx bytes": "upstream_bytes",
        "Rx discarded frames": "upstream_discarded_frames",
        "Tx frames": "downstream_frames",
        "Tx bytes": "downstream_bytes",
        "Tx discarded frames": "downstream_discarded_frames",
    }
    
    if not response:
        logging.warning("parse_ont_statistics: Resposta vazia recebida")
        return {}
    
    logging.debug(f"parse_ont_statistics: Analisando resposta com {len(response)} caracteres")
    
    for line in response.splitlines():
        line = line.strip()
        if not line:
            continue
            
        # Tenta diferentes formatos de separador
        if ":" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                key = parts[0].strip()
                value_str = parts[1].strip()
                
                # Procura por correspondências no key_map
                for map_key, db_key in key_map.items():
                    if map_key.lower() in key.lower():
                        try:
                            # Extrai apenas o valor numérico
                            numeric_match = re.search(r'(\d+)', value_str)
                            if numeric_match:
                                stats_data[db_key] = int(numeric_match.group(1))
                                logging.debug(f"parse_ont_statistics: {db_key} = {stats_data[db_key]}")
                            break
                        except (ValueError, TypeError) as e:
                            logging.warning(f"parse_ont_statistics: Erro ao converter valor '{value_str}' para {db_key}: {e}")
                            break
    
    logging.debug(f"parse_ont_statistics: Dados extraídos: {stats_data}")
    return stats_data
    
def parse_ont_eth_statistics(response):
    """
    Analisa a saída do comando 'display statistics ont-eth ...' e extrai os contadores.
    Versão melhorada com mais robustez.
    """
    stats_data = {}
    
    # Mapeamento mais completo de possíveis chaves
    key_map = {
        # Recebimento (RX)
        "Received frames": "rx_frames",
        "Received bytes": "rx_bytes",
        "Received unicast frames": "rx_unicast_frames",
        "Received multicast frames": "rx_multicast_frames",
        "Received broadcast frames": "rx_broadcast_frames",
        "Received error frames": "rx_error_frames",
        "Received discarded frames": "rx_discarded_frames",
        # Envio (TX)
        "Sent frames": "tx_frames",
        "Sent bytes": "tx_bytes",
        "Sent unicast frames": "tx_unicast_frames",
        "Sent multicast frames": "tx_multicast_frames",
        "Sent broadcast frames": "tx_broadcast_frames",
        "Sent error frames": "tx_error_frames",
        "Sent discarded frames": "tx_discarded_frames",
        "Sent collision frames": "tx_collision_frames",
        # Outros
        "Statistics duration(s)": "duration_seconds",
    }
    
    if not response:
        logging.warning("parse_ont_eth_statistics: Resposta vazia recebida")
        return {}
    
    logging.debug(f"parse_ont_eth_statistics: Analisando resposta com {len(response)} caracteres")
    
    for line in response.splitlines():
        line = line.strip()
        if not line:
            continue
            
        # Tenta diferentes formatos de separador
        if ":" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                key = parts[0].strip()
                value_str = parts[1].strip()
                
                # Procura por correspondências no key_map
                for map_key, db_key in key_map.items():
                    if map_key.lower() in key.lower():
                        try:
                            # Extrai apenas o valor numérico
                            numeric_match = re.search(r'(\d+)', value_str)
                            if numeric_match:
                                stats_data[db_key] = int(numeric_match.group(1))
                                logging.debug(f"parse_ont_eth_statistics: {db_key} = {stats_data[db_key]}")
                            break
                        except (ValueError, TypeError) as e:
                            logging.warning(f"parse_ont_eth_statistics: Erro ao converter valor '{value_str}' para {db_key}: {e}")
                            break
    
    logging.debug(f"parse_ont_eth_statistics: Dados extraídos: {stats_data}")
    return stats_data

def parse_uplink_ddm_response(response):
    """Parseia a saída do comando 'display port ddm-info'"""
    ddm_data = {}
    
    try:
        lines = response.splitlines()
        
        for line in lines:
            line = line.strip()
            
            if ":" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip()
                    
                    if "Temperature(C)" in key:
                        temp_match = re.search(r'([-+]?\d*\.?\d+)', value)
                        if temp_match:
                            ddm_data['temperature_c'] = float(temp_match.group(1))
                    
                    elif "Supply voltage(V)" in key:
                        volt_match = re.search(r'([-+]?\d*\.?\d+)', value)
                        if volt_match:
                            ddm_data['supply_voltage_v'] = float(volt_match.group(1))
                    
                    elif "TX bias current(mA)" in key:
                        current_match = re.search(r'([-+]?\d*\.?\d+)', value)
                        if current_match:
                            ddm_data['tx_bias_current_ma'] = float(current_match.group(1))
                    
                    elif "TX power(dBm)" in key:
                        tx_power_match = re.search(r'([-+]?\d*\.?\d+)', value)
                        if tx_power_match:
                            ddm_data['tx_power_dbm'] = float(tx_power_match.group(1))
                    
                    elif "RX power(dBm)" in key:
                        rx_power_match = re.search(r'([-+]?\d*\.?\d+)', value)
                        if rx_power_match:
                            ddm_data['rx_power_dbm'] = float(rx_power_match.group(1))
        
        return ddm_data if ddm_data else None
            
    except Exception as e:
        logging.error(f"Erro ao parsear resposta DDM: {e}")
        return None
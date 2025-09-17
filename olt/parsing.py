# olt/parsing.py

import re
import logging
import time
from datetime import datetime
from utils.helpers import format_mac 
import json # <--- ADICIONE ESTA LINHA

def extract_service_mac(response):
    """
    Extrai o endereço MAC da resposta do comando 'display ont wan-info'.
    Itera linha por linha para maior robustez.
    """
    logging.info(f"[RAW] Resposta para extração de MAC:\n---\n{response}\n---")
    from utils.helpers import format_mac

    for line in response.splitlines():
        clean_line = line.strip().lower()
        
        if clean_line.startswith("mac address"):
            logging.debug(f"[PARSE] Linha candidata a MAC encontrada: '{line.strip()}'")
            try:
                raw_mac = line.split(":", 1)[1].strip()
                formatted_mac = format_mac(raw_mac)
                logging.debug(f"[PARSE]   -> MAC extraído e formatado: '{formatted_mac}'")
                if formatted_mac != "N/A":
                    logging.info(f"[PARSE] [extract_service_mac] MAC encontrado: {formatted_mac}")
                    return formatted_mac
            except IndexError:
                logging.debug("[PARSE]   -> Falha: A linha não contém ':'.")
                continue
                
    logging.debug("[PARSE] Endereço MAC não encontrado na resposta.")
    return "N/A"

def extract_ont_info(summary_response):
    """
    Analisa a saída complexa de 'display ont info summary', que contém duas tabelas
    distintas, e combina as informações em um único dicionário por ONT.
    """
    logging.info(f"[RAW] Resposta para 'display ont info summary' ({len(summary_response)} bytes):\n---\n{summary_response[:1000]}...\n---")
    
    ont_data = {}
    online_count, total_count = 0, 0

    summary_header_match = re.search(r"the total of ONTs are:\s*(\d+),\s*online:\s*(\d+)", summary_response)
    if summary_header_match:
        total_count = int(summary_header_match.group(1))
        online_count = int(summary_header_match.group(2))
        logging.debug(f"[PARSE] Contagem do cabeçalho: Total={total_count}, Online={online_count}")
    else:
        logging.warning("[PARSE] Não foi possível extrair a contagem do cabeçalho.")

    try:
        parts = re.split(r"(\s*ONT\s+SN\s+Type\s+Distance)", summary_response, flags=re.IGNORECASE)
        state_section = parts[0]
        details_section = "".join(parts[1:]) if len(parts) > 1 else ""
    except Exception as e:
        logging.error(f"[PARSE] Erro ao dividir a resposta em seções: {e}")
        state_section, details_section = summary_response, ""

    state_pattern = re.compile(r"^\s*(\d+)\s+([a-zA-Z-]+)\s+.*$", re.MULTILINE)
    for match in state_pattern.finditer(state_section):
        logging.debug(f"[PARSE] Linha de Estado: '{match.group(0).strip()}'")
        ont_id, run_state = match.group(1), match.group(2).lower()
        logging.debug(f"[PARSE]   -> Dados extraídos: ONT ID={ont_id}, Estado={run_state}")
        ont_data[ont_id] = {"run_state": run_state}

    details_pattern = re.compile(r"^\s*(\d+)\s+([0-9A-F]{16})\s+(\S+)\s+(\S+)\s+(-?[\d.]+\/-?[\d.]+|\-|\-\/\-)\s+(.*)$", re.MULTILINE | re.IGNORECASE)
    for match in details_pattern.finditer(details_section):
        logging.debug(f"[PARSE] Linha de Detalhes: '{match.group(0).strip()}'")
        ont_id, sn, rx_tx, description = match.group(1), match.group(2), match.group(5), match.group(6).strip()
        rx_power, tx_power = ("N/A", "N/A")
        if rx_tx not in ["-", "-/-"]:
            try: rx_power, tx_power = rx_tx.split('/')
            except ValueError: pass
        
        logging.debug(f"[PARSE]   -> Dados extraídos: ONT ID={ont_id}, SN={sn}, Rx/Tx={rx_tx}, Descrição='{description}'")
        if ont_id in ont_data:
            ont_data[ont_id].update({"sn": sn, "rx_power": rx_power, "tx_power": tx_power, "description": description})
        else:
            logging.warning(f"[PARSE] ONT ID {ont_id} encontrado nos detalhes mas não no estado.")
            ont_data[ont_id] = {"run_state": "unknown", "sn": sn, "rx_power": rx_power, "tx_power": tx_power, "description": description}
    
    final_ont_data = {}
    for ont_id, data in ont_data.items():
        if "sn" not in data:
            logging.warning(f"[PARSE] ONT ID {ont_id} não encontrado nos detalhes. Preenchendo com N/A.")
            data.update({"sn": "N/A", "rx_power": "N/A", "tx_power": "N/A", "description": "N/A"})
        final_ont_data[ont_id] = data

    if not final_ont_data and total_count > 0:
        logging.error("[PARSE] Falha crítica: Nenhuma ONT foi parseada, mas o cabeçalho indicava ONTs presentes.")

    logging.info(f"[PARSE] [extract_ont_info] Extração concluída. {len(final_ont_data)} ONTs analisadas.")
    return final_ont_data, online_count, total_count

def parse_ont_info_details(output_text):
    """
    Analisa a saída do comando 'display ont info [f s p] [ont_id] all'
    e extrai informações detalhadas da ONT, limpando os valores.
    """
    logging.info(f"[RAW] Resposta para 'display ont info all' ({len(output_text)} bytes):\n---\n{output_text[:1000]}...\n---")
    details = { 'last_down_cause': 'N/A', 'last_up_time': 'N/A', 'last_down_time': 'N/A', 'last_dying_gasp_time': 'N/A', 'ont_online_duration': 'N/A', 'services': [], 'ont_distance': 'N/A', 'memory_occupation': 'N/A', 'cpu_occupation': 'N/A', 'temperature': 'N/A', 'ont_ip_address': 'N/A', 'line_profile_id': 'N/A', 'line_profile_name': 'N/A', 'service_profile_id': 'N/A', 'service_profile_name': 'N/A' }
    lines = output_text.splitlines()

    for line in lines:
        clean_line = line.strip()
        # Este log fica em DEBUG, pois é muito verboso
        logging.debug(f"[PARSE] Processando linha de detalhe: '{clean_line}'") 
        if ":" in clean_line:
            try:
                key, value = clean_line.split(':', 1)
                key, value = key.strip(), value.strip()
                logging.debug(f"[PARSE]   -> Chave: '{key}', Valor: '{value}'")

                key_map = { "Last down cause": "last_down_cause", "Last up time": "last_up_time", "Last down time": "last_down_time", "Last dying gasp time": "last_dying_gasp_time", "ONT online duration": "ont_online_duration", "ONT distance(m)": "ont_distance", "Memory occupation": "memory_occupation", "CPU occupation": "cpu_occupation", "Temperature": "temperature", "ONT IP 0 address/mask": "ont_ip_address", "Line profile ID": "line_profile_id", "Line profile name": "line_profile_name", "Service profile ID": "service_profile_id", "Service profile name": "service_profile_name" }
                if key in key_map:
                    details_key = key_map[key]
                    if details_key == 'temperature': value = re.sub(r'[^0-9.]', '', value)
                    details[details_key] = value
                    logging.debug(f"[PARSE]   -> Mapeado e salvo: {details_key} = {value}")
            except ValueError: continue
        elif clean_line.startswith(('ETH', 'IPHOST', 'VEIP')):
            parts = clean_line.split()
            if len(parts) >= 4:
                service_info = { 'type': parts[0], 'port_id': parts[1], 'service_type': parts[2], 'vlan_id': parts[3] }
                details['services'].append(service_info)
                logging.debug(f"[PARSE]   -> Serviço extraído: {service_info}")

    # Este log fica em INFO, pois é o resumo final e importante
    logging.info(f"[PARSE] [parse_ont_info_details] Resultado final: {json.dumps(details, indent=2)}")
    return details

def parse_pon_port_state(response):
    """
    Analisa a saída do comando 'display port state <port>' e extrai as informações.
    """
    logging.info(f"[RAW] Resposta para 'display port state' ({len(response)} bytes):\n---\n{response}\n---")
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
            logging.debug(f"[PARSE] Processando linha de estado PON: '{line}' -> Chave: '{key}', Valor: '{value}'") # LOG ATUALIZADO
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
                
                logging.debug(f"[PARSE]   -> Mapeado: {db_key} = {state_data[db_key]}") # LOG ATUALIZADO

    # NOVO LOG: Mostra o resultado final do parsing
    logging.info(f"[PARSE] [parse_pon_port_state] Resultado final: {json.dumps(state_data, default=str, indent=2)}")
    return state_data

def parse_port_info(response):
    """
    Analisa a saída do comando 'display port info <port>' e extrai informações.
    """
    logging.info(f"[RAW] Resposta para 'display port info' ({len(response)} bytes):\n---\n{response}\n---")
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
            logging.debug(f"[PARSE] Processando linha de info da porta: '{line.strip()}' -> Chave: '{key}', Valor: '{value}'") # LOG ATUALIZADO
            if key in key_map:
                db_key = key_map[key]
                if db_key == 'left_guaranteed_bandwidth_kbps':
                    try:
                        info_data[db_key] = int(value)
                    except (ValueError, TypeError):
                        info_data[db_key] = None
                else:
                    info_data[db_key] = value
                
                logging.debug(f"[PARSE]   -> Mapeado: {db_key} = {info_data[db_key]}") # LOG ATUALIZADO

    logging.info(f"[PARSE] [parse_port_info] Resultado final: {json.dumps(info_data, indent=2)}")
    return info_data

def parse_pon_statistics_packets(response):
    """Analisa a saída do 'display statistics port ethernet' e extrai os contadores."""
    logging.info(f"[RAW] Resposta para 'display statistics port ethernet' ({len(response)} bytes):\n---\n{response}\n---")
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
                logging.debug(f"[PARSE] Processando linha de estatísticas PON: '{line.strip()}'") # LOG ATUALIZADO
                numeric_value = re.search(r'^\s*(\d+)', value.strip())
                if numeric_value:
                    try:
                        db_key = key_map[key]
                        stats_data[db_key] = int(numeric_value.group(1))
                        logging.debug(f"[PARSE]   -> Mapeado: {db_key} = {stats_data[db_key]}") # LOG ATUALIZADO
                    except (ValueError, TypeError):
                        continue
    
    logging.info(f"[PARSE] [parse_pon_statistics_packets] Resultado final: {json.dumps(stats_data, indent=2)}")
    return stats_data

def parse_ont_traffic(response, ont_id_target=None):
    """
    Analisa a saída do 'display ont traffic'.
    Lida com o formato de múltiplas ONTs ('all') e de ONT única.
    """
    logging.info(f"[RAW] Resposta para 'display ont traffic' ({len(response)} bytes):\n---\n{response[:1000]}...\n---")
    traffic_list = []
    lines = response.splitlines()
    
    header_found = False
    for i, line in enumerate(lines):
        if "ONT ID" in line and "Up traffic" in line and "Down traffic" in line:
            header_found = True
            for data_line in lines[i+1:]:
                if data_line.strip().startswith("---"):
                    continue
                logging.debug(f"[PARSE] Processando linha de tráfego ONT (múltiplo): '{data_line.strip()}'") # LOG ATUALIZADO
                parts = re.split(r'\s+', data_line.strip())
                if len(parts) >= 3:
                    try:
                        data = {
                            "ont_id": int(parts[0]),
                            "up_traffic": float(parts[1]),
                            "down_traffic": float(parts[2])
                        }
                        traffic_list.append(data)
                        logging.debug(f"[PARSE]   -> Tráfego extraído: {data}") # LOG ATUALIZADO
                    except (ValueError, IndexError):
                        continue
            break
    
    if not header_found:
        logging.info("[PARSE] Cabeçalho de múltiplas ONTs não encontrado, tentando parse de ONT única.")
        up_traffic, down_traffic = None, None
        for line in lines:
            logging.debug(f"[PARSE] Processando linha de tráfego ONT (único): '{line.strip()}'")
            if "Up traffic (kbps)" in line:
                try:
                    up_traffic = float(line.split(':')[1].strip())
                except (ValueError, IndexError):
                    pass
            elif "Down traffic (kbps)" in line:
                try:
                    down_traffic = float(line.split(':')[1].strip())
                except (ValueError, IndexError):
                    pass
        
        if up_traffic is not None and down_traffic is not None and ont_id_target is not None:
            data = {
                "ont_id": ont_id_target,
                "up_traffic": up_traffic,
                "down_traffic": down_traffic
            }
            traffic_list.append(data)
            logging.debug(f"[PARSE]   -> Tráfego (único) extraído: {data}")


    if not traffic_list:
        logging.warning("[PARSE] [parse_ont_traffic] Nenhum dado de tráfego de ONT pôde ser extraído.")
    else:
        logging.info(f"[PARSE] [parse_ont_traffic] Resultado final: {json.dumps(traffic_list, indent=2)}")
    
    return traffic_list

def parse_ont_statistics(response):
    """Analisa a saída do 'display statistics ont' e extrai os contadores."""
    logging.info(f"[RAW] Resposta para 'display statistics ont' ({len(response)} bytes):\n---\n{response}\n---")
    stats_data = {}
    
    key_map = {
        "Upstream frames": "upstream_frames", "Upstream bytes": "upstream_bytes",
        "Upstream discarded frames": "upstream_discarded_frames", "Downstream frames": "downstream_frames",
        "Downstream bytes": "downstream_bytes", "Downstream discarded frames": "downstream_discarded_frames",
        "Rx frames": "upstream_frames", "Rx bytes": "upstream_bytes",
        "Rx discarded frames": "upstream_discarded_frames", "Tx frames": "downstream_frames",
        "Tx bytes": "downstream_bytes", "Tx discarded frames": "downstream_discarded_frames",
    }
    
    if not response:
        logging.warning("[PARSE] parse_ont_statistics: Resposta vazia recebida.")
        return {}
    
    for line in response.splitlines():
        line = line.strip()
        if not line:
            continue
            
        if ":" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                key, value_str = parts[0].strip(), parts[1].strip()
                logging.debug(f"[PARSE] Processando linha de estatísticas ONT: '{line.strip()}'") # LOG ATUALIZADO
                
                for map_key, db_key in key_map.items():
                    if map_key.lower() in key.lower():
                        try:
                            numeric_match = re.search(r'(\d+)', value_str)
                            if numeric_match:
                                stats_data[db_key] = int(numeric_match.group(1))
                                logging.debug(f"[PARSE]   -> Mapeado: {db_key} = {stats_data[db_key]}") # LOG ATUALIZADO
                            break
                        except (ValueError, TypeError) as e:
                            logging.warning(f"[PARSE] Erro ao converter valor '{value_str}' para {db_key}: {e}")
                            break
    
    logging.info(f"[PARSE] [parse_ont_statistics] Resultado final: {json.dumps(stats_data, indent=2)}")
    return stats_data
    
def parse_ont_eth_statistics(response):
    """
    Analisa a saída do comando 'display statistics ont-eth ...' e extrai os contadores.
    """
    logging.info(f"[RAW] Resposta para 'display statistics ont-eth' ({len(response)} bytes):\n---\n{response}\n---")
    stats_data = {}
    
    key_map = {
        "Received frames": "rx_frames", "Received bytes": "rx_bytes",
        "Received unicast frames": "rx_unicast_frames", "Received multicast frames": "rx_multicast_frames",
        "Received broadcast frames": "rx_broadcast_frames", "Received error frames": "rx_error_frames",
        "Received discarded frames": "rx_discarded_frames", "Sent frames": "tx_frames",
        "Sent bytes": "tx_bytes", "Sent unicast frames": "tx_unicast_frames",
        "Sent multicast frames": "tx_multicast_frames", "Sent broadcast frames": "tx_broadcast_frames",
        "Sent error frames": "tx_error_frames", "Sent discarded frames": "tx_discarded_frames",
        "Sent collision frames": "tx_collision_frames", "Statistics duration(s)": "duration_seconds",
    }
    
    if not response:
        logging.warning("[PARSE] parse_ont_eth_statistics: Resposta vazia recebida.")
        return {}
    
    for line in response.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
            
        parts = line.split(":", 1)
        if len(parts) == 2:
            key, value_str = parts[0].strip(), parts[1].strip()
            logging.debug(f"[PARSE] Processando linha de estatísticas ONT ETH: '{line.strip()}'") # LOG ATUALIZADO
            for map_key, db_key in key_map.items():
                if map_key.lower() in key.lower():
                    try:
                        numeric_match = re.search(r'(\d+)', value_str)
                        if numeric_match:
                            stats_data[db_key] = int(numeric_match.group(1))
                            logging.debug(f"[PARSE]   -> Mapeado: {db_key} = {stats_data[db_key]}") # LOG ATUALIZADO
                        break
                    except (ValueError, TypeError) as e:
                        logging.warning(f"[PARSE] Erro ao converter valor '{value_str}' para {db_key}: {e}")
                        break
    
    logging.info(f"[PARSE] [parse_ont_eth_statistics] Resultado final: {json.dumps(stats_data, indent=2)}")
    return stats_data

def parse_uplink_ddm_response(response):
    """Parseia a saída do comando 'display port ddm-info'"""
    logging.info(f"[RAW] Resposta para 'display port ddm-info' ({len(response)} bytes):\n---\n{response}\n---")
    ddm_data = {}
    
    try:
        for line in response.splitlines():
            line = line.strip()
            if ":" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    key, value = parts[0].strip(), parts[1].strip()
                    logging.debug(f"[PARSE] Processando linha DDM: '{line}'")
                    
                    if "Temperature(C)" in key:
                        if (m := re.search(r'([-+]?\d*\.?\d+)', value)): ddm_data['temperature_c'] = float(m.group(1))
                    elif "Supply voltage(V)" in key:
                        if (m := re.search(r'([-+]?\d*\.?\d+)', value)): ddm_data['supply_voltage_v'] = float(m.group(1))
                    elif "TX bias current(mA)" in key:
                        if (m := re.search(r'([-+]?\d*\.?\d+)', value)): ddm_data['tx_bias_current_ma'] = float(m.group(1))
                    elif "TX power(dBm)" in key:
                        if (m := re.search(r'([-+]?\d*\.?\d+)', value)): ddm_data['tx_power_dbm'] = float(m.group(1))
                    elif "RX power(dBm)" in key:
                        if (m := re.search(r'([-+]?\d*\.?\d+)', value)): ddm_data['rx_power_dbm'] = float(m.group(1))
        
        if ddm_data:
            logging.info(f"[PARSE] [parse_uplink_ddm_response] Resultado final: {json.dumps(ddm_data, indent=2)}")
        return ddm_data if ddm_data else None
            
    except Exception as e:
        logging.error(f"[PARSE] Erro ao parsear resposta DDM: {e}")
        return None

def parse_ont_version_details(raw_output: str) -> dict:
    """
    Analisa a saída do comando 'display ont version' e extrai os detalhes da ONT.
    """
    logging.info(f"[RAW] Resposta para 'display ont version' ({len(raw_output)} bytes):\n---\n{raw_output}\n---")
    details = { 'vendor_id': None, 'ont_version': None, 'product_id': None, 'equipment_id': None, 'main_software_version': None, 'standby_software_version': None, 'ont_product_description': None, 'support_xml_version': None }

    desc_match = re.search(r"OntProductDescription\s+:\s*(.*?)\s+Support XML Version", raw_output, re.DOTALL)
    if desc_match:
        # --- LINHAS MODIFICADAS ---
        description_raw = desc_match.group(1).strip()
        # Remove quebras de linha e carriage returns, depois substitui múltiplos espaços por um só
        description_clean = re.sub(r'\s+', ' ', description_raw.replace('\r', '').replace('\n', ' '))
        details['ont_product_description'] = description_clean
        # --- FIM DA MODIFICAÇÃO ---

    for line in raw_output.splitlines():
        if ':' in line:
            key, value = map(str.strip, line.split(':', 1))
            logging.debug(f"[PARSE] Processando linha de versão: '{line.strip()}'")
            key_map = { "Vendor-ID": "vendor_id", "ONT Version": "ont_version", "Product-ID": "product_id", "Equipment-ID": "equipment_id", "Main Software Version": "main_software_version", "Standby Software Version": "standby_software_version", "Support XML Version": "support_xml_version" }
            if key in key_map:
                db_key = key_map[key]
                details[db_key] = value
                logging.debug(f"[PARSE]   -> Mapeado: {db_key} = {value}")

    logging.info(f"[PARSE] [parse_ont_version_details] Resultado final: {json.dumps(details, indent=2)}")
    return details

def parse_ont_optical_info(raw_output: str) -> dict:
    """
    Analisa a saída do comando 'display ont optical-info' e extrai os detalhes ópticos.
    """
    logging.info(f"[RAW] Resposta para 'display ont optical-info' ({len(raw_output)} bytes):\n---\n{raw_output}\n---")
    details = {}
    key_map = {
        "Module type": "optical_module_type", "Module sub-type": "optical_module_subtype",
        "Encapsulation Type": "optical_encapsulation_type", "Vendor name": "optical_vendor_name",
        "Vendor PN": "optical_vendor_pn", "Vendor SN": "optical_vendor_sn", "Date Code": "optical_date_code",
        "OLT Rx ONT optical power(dBm)": "optical_olt_rx_ont_power_dbm", "Voltage(V)": "ont_voltage_v",
        "Laser bias current(mA)": "ont_tx_bias_current_ma", "Rx power current alarm threshold(dBm)": "optical_rx_power_alarm",
        "Tx power current alarm threshold(dBm)": "optical_tx_power_alarm",
        "Tx bias current alarm threshold(mA)": "optical_bias_current_alarm",
        "Temperature alarm threshold(C)": "optical_temperature_alarm",
        "Supply voltage alarm threshold(V)": "optical_voltage_alarm"
    }

    for line in raw_output.splitlines():
        if ":" in line:
            try:
                key, value = [x.strip() for x in line.split(":", 1)]
                logging.debug(f"[PARSE] Processando linha de info óptica: '{line.strip()}'")
                if key in key_map:
                    db_key = key_map[key]
                    if value in ['-', 'N/A', '[-,-]']:
                        details[db_key] = None
                        continue

                    if db_key in ['optical_olt_rx_ont_power_dbm', 'ont_voltage_v', 'ont_tx_bias_current_ma']:
                        numeric_match = re.search(r'([-+]?\d*\.?\d+)', value)
                        details[db_key] = float(numeric_match.group(1)) if numeric_match else None
                    else:
                        details[db_key] = value
                    
                    logging.debug(f"[PARSE]   -> Mapeado: {db_key} = {details[db_key]}")
            except (ValueError, IndexError):
                continue

    logging.info(f"[PARSE] [parse_ont_optical_info] Resultado final: {json.dumps(details, indent=2)}")
    return details
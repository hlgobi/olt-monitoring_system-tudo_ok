# db/operations.py
# Este arquivo contém funções para operações no banco de dados PostgreSQL relacionadas ao monitoramento de OLTs e ONTs.
# Ele implementa a persistência de dados coletados das OLTs, incluindo informações de ONTs, status de PONs,
# dados de temperatura e recursos, além de histórico de diagnósticos.

from datetime import datetime, timezone, timedelta
import json
import logging
import psycopg2
from psycopg2.extras import execute_batch
from PyQt5.QtCore import QObject, pyqtSignal

from config import DB_CONFIG
from gui.signals import db_signals
from utils.helpers import parse_descricao_avancada


# Em operations.py, verifique a função get_current_brasilia_time
def get_current_brasilia_time():
    """
    Retorna a data e hora atual no fuso horário de Brasília (America/Sao_Paulo)
    """
    from datetime import datetime
    import pytz
    
    # Obtém a hora atual no fuso de Brasília
    brasilia_tz = pytz.timezone('America/Sao_Paulo')
    current_time = datetime.now(brasilia_tz)
    logging.debug(f"get_current_brasilia_time: {current_time} (fuso: {current_time.tzinfo})")
    return current_time

# Em operations.py, verifique se a função to_db_timestamp está correta
def to_db_timestamp(ts_str):
    """
    Converte string de timestamp para objeto datetime com fuso horário de Brasília (America/Sao_Paulo)
    """
    if ts_str in ['N/A', '-', None, '']:
        return None
    try:
        # Tenta converter no formato dd/mm/yyyy HH:MM:SS
        dt = datetime.strptime(ts_str, '%d/%m/%Y %H:%M:%S')
        # Define o fuso horário de Brasília (America/Sao_Paulo)
        import pytz
        brasilia_tz = pytz.timezone('America/Sao_Paulo')
        dt = brasilia_tz.localize(dt)
        return dt
    except ValueError:
        try:
            # Formato: yyyy-mm-dd HH:MM:SS
            dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
            import pytz
            brasilia_tz = pytz.timezone('America/Sao_Paulo')
            dt = brasilia_tz.localize(dt)
            return dt
        except ValueError:
            try:
                # Formato: dd/mm/yyyy HH:MM:SS-03:00 (já com fuso)
                dt = datetime.strptime(ts_str.split('-')[0], '%d/%m/%Y %H:%M:%S')
                import pytz
                brasilia_tz = pytz.timezone('America/Sao_Paulo')
                dt = brasilia_tz.localize(dt)
                return dt
            except ValueError:
                logging.error(f"Não foi possível converter o timestamp: {ts_str}")
                return None

# db/operations.py

# Substitua a função save_ont_data inteira por esta versão atualizada

def save_ont_data(olt_ip, ont_info):
    """
    Salva ou atualiza os dados de uma ONT no banco de dados, incluindo detalhes de status
    e preservando o nome do cliente existente.
    """
    logging.info(f"[DB] [save_ont_data] Iniciando salvamento para ONT S/N: {ont_info.get('sn', 'N/A')} na OLT {olt_ip}")
    conn = None
    try:
        olt_identifier = olt_ip.split('.')[-1]
        
        description = ont_info.get('description', 'N/A')
        parsed_desc = parse_descricao_avancada(description)
        primaria = parsed_desc.get('primaria', 'N/A')
        secundaria = parsed_desc.get('secundaria', 'N/A')
        porta_secundaria = parsed_desc.get('porta_secundaria', 'N/A')
        
        conn = psycopg2.connect(**DB_CONFIG)
        
        with conn.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'America/Sao_Paulo';")
            cursor.execute("SHOW timezone;")
            tz = cursor.fetchone()[0]
            logging.info(f"Fuso horário da sessão PostgreSQL: {tz}")
        
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT fsp, ont_id, mac_address, client_name
                FROM public.ont_data
                WHERE serial_number = %s
                ORDER BY collection_time DESC
                LIMIT 1
            """, (ont_info['sn'],))
            previous_record = cursor.fetchone()
            
            fsp_changed = False
            ont_id_changed = False
            mac_changed = False
            previous_fsp = None
            previous_ont_id = None
            previous_mac = None
            existing_client_name = None
            
            if previous_record:
                previous_fsp, previous_ont_id, previous_mac, existing_client_name = previous_record
                fsp_changed = previous_fsp != ont_info['fsp']
                ont_id_changed = previous_ont_id != int(ont_info['ont_id'])
                mac_changed = previous_mac and previous_mac != ont_info['mac'] and ont_info['mac'] != 'N/A'
            
            current_time = get_current_brasilia_time()
            
            # --- INÍCIO DA CORREÇÃO ---
            # Garante que o campo 'services' seja uma string JSON antes de inserir
            services_data = ont_info.get('services')
            if isinstance(services_data, (list, dict)):
                services_json = json.dumps(services_data)
            else:
                services_json = services_data  # Assume que já é uma string JSON ou None
            # --- FIM DA CORREÇÃO ---

            sql = """
                INSERT INTO public.ont_data (
                    olt_ip, olt_identifier, fsp, ont_id, mac_address, client_name,
                    previous_mac_address, serial_number, rx_power, tx_power,
                    description, primaria, secundaria, porta_secundaria, 
                    fsp_changed, ont_id_changed,
                    previous_fsp, previous_ont_id, status,
                    last_down_cause, last_up_time, last_down_time,
                    last_dying_gasp_time, line_profile_name, services,
                    ont_distance, memory_occupation, cpu_occupation, temperature,
                    ont_ip_address, line_profile_id, service_profile_id, service_profile_name,
                    connection_code,
                    vendor_id, ont_version, product_id, equipment_id,
                    main_software_version, standby_software_version,
                    ont_product_description, support_xml_version,
                    ont_online_duration,
                    optical_module_type, optical_module_subtype, optical_encapsulation_type,
                    optical_vendor_name, optical_vendor_pn, optical_vendor_sn,
                    optical_date_code, optical_olt_rx_ont_power_dbm, ont_voltage_v,
                    ont_tx_bias_current_ma, optical_rx_power_alarm, optical_tx_power_alarm,
                    optical_bias_current_alarm, optical_temperature_alarm, optical_voltage_alarm,
                    collection_time
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    CAST(%s AS TIMESTAMP WITH TIME ZONE))
            """
            
            params = (
                olt_ip, olt_identifier, ont_info['fsp'], int(ont_info['ont_id']), 
                ont_info['mac'] if ont_info['mac'] != 'N/A' else None, existing_client_name,
                previous_mac if mac_changed else None, ont_info['sn'], 
                float(ont_info['rx']) if ont_info['rx'] not in ['N/A', '-'] else None, 
                float(ont_info['tx']) if ont_info['tx'] not in ['N/A', '-'] else None,
                ont_info['description'], primaria, secundaria, porta_secundaria,
                fsp_changed, ont_id_changed, previous_fsp if fsp_changed else None, 
                previous_ont_id if ont_id_changed else None, ont_info['status'],
                ont_info.get('last_down_cause'), to_db_timestamp(ont_info.get('last_up_time')),
                to_db_timestamp(ont_info.get('last_down_time')), to_db_timestamp(ont_info.get('last_dying_gasp_time')),
                ont_info.get('line_profile_name'), ont_info.get('services'),
                ont_info.get('ont_distance'), ont_info.get('memory_occupation'), 
                ont_info.get('cpu_occupation'), ont_info.get('temperature'),
                ont_info.get('ont_ip_address'), ont_info.get('line_profile_id'),
                ont_info.get('service_profile_id'), ont_info.get('service_profile_name'),
                ont_info.get('connection_code'), ont_info.get('vendor_id'),
                ont_info.get('ont_version'), ont_info.get('product_id'),
                ont_info.get('equipment_id'), ont_info.get('main_software_version'),
                ont_info.get('standby_software_version'), ont_info.get('ont_product_description'),
                ont_info.get('support_xml_version'), ont_info.get('ont_online_duration'),
                ont_info.get('optical_module_type'), ont_info.get('optical_module_subtype'),
                ont_info.get('optical_encapsulation_type'), ont_info.get('optical_vendor_name'),
                ont_info.get('optical_vendor_pn'), ont_info.get('optical_vendor_sn'),
                ont_info.get('optical_date_code'), ont_info.get('optical_olt_rx_ont_power_dbm'),
                ont_info.get('ont_voltage_v'), ont_info.get('ont_tx_bias_current_ma'),
                ont_info.get('optical_rx_power_alarm'), ont_info.get('optical_tx_power_alarm'),
                ont_info.get('optical_bias_current_alarm'), ont_info.get('optical_temperature_alarm'),
                ont_info.get('optical_voltage_alarm'),
                current_time.isoformat()
            )
            
            cursor.execute(sql, params)
            conn.commit()
            
            cursor.execute("""
                SELECT collection_time 
                FROM public.ont_data 
                WHERE serial_number = %s 
                ORDER BY collection_time DESC 
                LIMIT 1
            """, (ont_info['sn'],))
            inserted_time = cursor.fetchone()[0]
            logging.info(f"Timestamp inserido no banco: {inserted_time}")
            
            logging.info(f"[DB] [save_ont_data] Sucesso ao salvar dados da ONT {ont_info['sn']}.")
            
    except Exception as e:
        logging.error(f"Erro ao salvar ONT {ont_info.get('sn', 'N/A')}: {str(e)}", exc_info=True)
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

def save_pon_status(olt_ip, fsp, online_count, total_count):
    """Salva o status da PON no banco de dados."""
    logging.info(f"[DB] [save_pon_status] Salvando status para OLT {olt_ip}, PON {fsp} (Online: {online_count}/{total_count})")
    conn = None
    try:
        olt_identifier = olt_ip.split('.')[-1]
        
        conn = psycopg2.connect(**DB_CONFIG)
        
        # Definir o fuso horário da sessão
        with conn.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'America/Sao_Paulo';")
        
        with conn.cursor() as cursor:
            # Determina o status da PON
            if total_count == 0:
                status = "empty"
            elif online_count == total_count:
                status = "operational"
            elif online_count >= total_count * 0.7:
                status = "degraded"
            else:
                status = "faulty"
                
            cursor.execute("""
                INSERT INTO pon_status
                (olt_ip, olt_identifier, fsp, online_count, total_count, status)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                olt_ip, olt_identifier, fsp, online_count, total_count, status
            ))
            
            conn.commit()
            logging.info(f"[DB] [save_pon_status] Sucesso ao salvar status da PON {fsp}.")
            
    except Exception as e:
        logging.error(f"Erro ao salvar status da PON {fsp}: {str(e)}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
def save_temp_data(olt_ip, temp_data):
    """Salva dados de temperatura no banco de dados."""
    logging.info(f"[DB] [save_temp_data] Iniciando salvamento de {len(temp_data)} registros de temperatura para OLT {olt_ip}")
    conn = None
    try:
        olt_identifier = olt_ip.split('.')[-1]
        
        conn = psycopg2.connect(**DB_CONFIG)
        
        # Definir o fuso horário da sessão
        with conn.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'America/Sao_Paulo';")
        
        with conn.cursor() as cursor:
            for data in temp_data:
                cursor.execute("""
                    INSERT INTO temperature_monitoring
                    (olt_ip, olt_identifier, slot_id, board_name, temperature_c, temperature_f, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    olt_ip, olt_identifier, data['slot_id'], data['board_name'],
                    data['temp_c'], data['temp_f'], data['status']
                ))
                
                logging.info(
                    f"[TEMP] OLT {olt_ip} | Slot {data['slot_id']} | "
                    f"{data['board_name']} | {data['temp_c']}°C / {data['temp_f']}°F | "
                    f"Status: {data['status']}"
                )
            
            conn.commit()
            logging.info(f"[DB] [save_temp_data] Sucesso ao salvar {len(temp_data)} registros de temperatura.")
            
            db_signals.temperature_updated.emit()
            return len(temp_data)
            
    except Exception as e:
        logging.error(f"Erro ao salvar dados de temperatura: {str(e)}")
        if conn:
            conn.rollback()
        return 0
    finally:
        if conn:
            conn.close()

def save_resource_data(olt_ip, resource_data):
    """Salva dados de monitoramento de recursos no banco de dados."""
    logging.info(f"[DB] [Recursos] Salvando {len(resource_data)} registros de recursos para OLT {olt_ip}")
    conn = None
    try:
        olt_identifier = olt_ip.split('.')[-1]
        
        conn = psycopg2.connect(**DB_CONFIG)
        
        # Definir o fuso horário da sessão
        with conn.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'America/Sao_Paulo';")
        
        with conn.cursor() as cursor:
            for data in resource_data:
                cursor.execute("""
                    INSERT INTO resource_monitoring
                    (olt_ip, olt_identifier, slot_id, board_name, resource_type, usage_percentage, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    olt_ip, olt_identifier, int(data['slot']), data.get('board_name', 'N/A'),
                    data['type'], data['usage'], data['status']
                ))
                
                logging.info(
                    f"[{data['type'].upper()}] OLT {olt_ip} | Slot {data['slot']} | "
                    f"{data.get('board_name', 'N/A')} | Uso: {data['usage']}% | "
                    f"Status: {data['status']}"
                )
            
            conn.commit()
            logging.info(f"[DB] [Recursos] {len(resource_data)} registros de recursos para OLT {olt_ip} salvos com sucesso.")
            return len(resource_data)
            
    except Exception as e:
        logging.error(f"Erro ao salvar dados de recursos: {str(e)}")
        if conn:
            conn.rollback()
        return 0
    finally:
        if conn:
            conn.close()

def get_ont_diagnostic_history(ont_serial_number: str, olt_identifier: str = None):
    """
    Busca o histórico de diagnósticos de uma ONT específica no banco de dados.
    
    Args:
        ont_serial_number (str): Número de série da ONT
        olt_identifier (str, optional): Identificador da OLT. Se fornecido, filtra os resultados por OLT
        
    Returns:
        list: Lista de tuplas contendo os registros de histórico de diagnóstico encontrados
    """
    conn = None
    records = []
    
    # SQL base para buscar o histórico de diagnósticos
    sql = """
        SELECT diag_timestamp, diag_section_id, raw_output, parsed_data, 
               manufacturer, model_name, uptime, firmware_version 
        FROM ont_diagnostics_history
        WHERE ont_serial_number = %s
    """
    
    # Lista de parâmetros para a consulta SQL
    params = [ont_serial_number]
    
    # Se o identificador da OLT foi fornecido, adiciona à consulta
    if olt_identifier:
        sql += " AND olt_identifier = %s"
        params.append(olt_identifier)
    
    # Adiciona ordenação e limite de registros
    sql += " ORDER BY diag_timestamp DESC LIMIT 500;"
    
    try:
        # Estabelece conexão com o banco de dados
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # Executa a consulta SQL
        cursor.execute(sql, tuple(params))
        
        # Recupera todos os registros encontrados
        records = cursor.fetchall()
        
        # Registra no log o número de registros encontrados
        logging.info(f"Encontrados {len(records)} registros de histórico de diagnóstico para S/N {ont_serial_number}" + (f" na OLT {olt_identifier}" if olt_identifier else ""))
        
    except Exception as e:
        # Em caso de erro, registra a exceção
        logging.error(f"Erro ao buscar histórico de diagnóstico para S/N {ont_serial_number}: {e}", exc_info=True)
    finally:
        # Garante que a conexão seja fechada
        if conn:
            conn.close()
    
    # Retorna os registros encontrados
    return records
def save_ont_diagnostic_data(diag_info: dict):
    """Salva os dados de diagnóstico de uma ONT no banco de dados."""
    conn = None
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        
        # Definir o fuso horário da sessão
        with conn.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'America/Sao_Paulo';")
        
        cursor = conn.cursor()
        
        p_data = diag_info.get('parsed_data_dict', {})
        
        cursor.execute("""
            INSERT INTO ont_diagnostics_history (
                ont_serial_number, olt_identifier, fsp, ont_id_on_pon, 
                diag_section_id, raw_output, parsed_data,
                manufacturer, model_name, uptime, firmware_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
        """, (
            diag_info.get('ont_serial_number'),
            diag_info.get('olt_identifier'),
            diag_info.get('fsp'),
            diag_info.get('ont_id_on_pon'),
            diag_info.get('diag_section_id'),
            diag_info.get('raw_output'),
            json.dumps(p_data) if p_data else None,
            p_data.get('Manufacturer'),
            p_data.get('ModelName'),
            p_data.get('UpTime'),
            p_data.get('main software version')
        ))
        
        conn.commit()
        logging.info(f"Dados de diagnóstico para ONT S/N {diag_info.get('ont_serial_number')} salvos com sucesso.")
        
    except Exception as e:
        logging.error(f"Erro ao salvar dados de diagnóstico da ONT S/N {diag_info.get('ont_serial_number')}: {e}", exc_info=True)
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def get_existing_ont_data(olt_ip, serial_number):
    """
    Busca dados existentes de uma ONT específica no banco de dados.
    Retorna um dicionário com os dados ou None se não encontrado.
    """
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        query = """
            SELECT connection_code, client_name 
            FROM ont_data 
            WHERE olt_ip = %s AND serial_number = %s 
            ORDER BY collection_time DESC 
            LIMIT 1
        """
        cursor.execute(query, (olt_ip, serial_number))
        result = cursor.fetchone()
        
        if result:
            return {
                'connection_code': result[0],
                'client_name': result[1]
            }
        return None
    except Exception as e:
        logging.error(f"Erro ao buscar dados existentes da ONT: {e}")
        return None
    finally:
        if conn:
            conn.close()
# Em db/operations.py, adicione paginação
def get_paginated_ont_data(olt_ip=None, limit=1000, offset=0):
    """Busca dados de ONTs com paginação para evitar travamentos."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        query = """
            SELECT * FROM ont_data 
            WHERE olt_ip = %s 
            ORDER BY collection_time DESC 
            LIMIT %s OFFSET %s
        """
        cursor.execute(query, (olt_ip, limit, offset))
        return cursor.fetchall()
    except Exception as e:
        logging.error(f"Erro ao buscar dados paginados: {e}")
        return []
    finally:
        if conn:
            conn.close()
            
# Em db/operations.py, função save_pon_traffic_data

def save_pon_traffic_data(olt_ip, fsp, traffic_data):
    """Salva os dados de tráfego de uma porta PON no banco de dados."""
    logging.info(f"[DB] [Tráfego PON] Salvando dados para OLT {olt_ip}, PON {fsp}") #
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        
        # Definir o fuso horário da sessão
        with conn.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'America/Sao_Paulo';")
        
        cursor = conn.cursor()
        
        query = """
            INSERT INTO pon_traffic_data (
                olt_ip, fsp, up_traffic_kbps, down_traffic_kbps,
                upstream_broadcast_pps, upstream_multicast_pps, upstream_unicast_pps,
                downstream_broadcast_pps, downstream_multicast_pps, downstream_unicast_pps
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        cursor.execute(query, (
            olt_ip, fsp,
            traffic_data.get('up_traffic_kbps'),
            traffic_data.get('down_traffic_kbps'),
            traffic_data.get('upstream_broadcast_pps'),
            traffic_data.get('upstream_multicast_pps'),
            traffic_data.get('upstream_unicast_pps'),
            traffic_data.get('downstream_broadcast_pps'),
            traffic_data.get('downstream_multicast_pps'),
            traffic_data.get('downstream_unicast_pps')
        ))
        
        conn.commit()
        logging.info(f"[DB] [Tráfego PON] Dados para OLT {olt_ip}, PON {fsp} salvos com sucesso.") #
        return True
    except Exception as e:
        logging.error(f"[DB] [Tráfego PON] Erro ao salvar dados para OLT {olt_ip}, PON {fsp}: {e}") #
        return False
    finally:
        if conn:
            conn.close()

def save_pon_port_state(olt_ip, fsp, state_data):
    """Salva os dados de estado da porta PON no banco de dados."""
    conn = None
    logging.info(f"[DB] [Estado PON] Salvando estado da porta para OLT {olt_ip}, PON {fsp}") #
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        
        # Definir o fuso horário da sessão
        with conn.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'America/Sao_Paulo';")
        
        olt_identifier = olt_ip.split('.')[-1]
        
        query = """
            INSERT INTO pon_port_state (
                olt_ip, olt_identifier, fsp, port_state, last_down_cause, last_up_time, last_down_time,
                signal_detect, available_bandwidth_kbps, illegal_rogue_ont,
                optical_module_status, laser_state, tx_fault, temperature_c,
                tx_bias_current_ma, supply_voltage_v, tx_power_dbm,
                left_guaranteed_bandwidth_kbps, admin_state
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        # Processa os campos de data/hora
        last_up_time = state_data.get('last_up_time')
        last_down_time = state_data.get('last_down_time')
        
        # Se já for um objeto datetime, usa diretamente, senão tenta converter
        if isinstance(last_up_time, datetime):
            last_up_time_processed = last_up_time
        else:
            last_up_time_processed = to_db_timestamp(last_up_time)
            
        if isinstance(last_down_time, datetime):
            last_down_time_processed = last_down_time
        else:
            last_down_time_processed = to_db_timestamp(last_down_time)
        
        with conn.cursor() as cursor:
            cursor.execute(query, (
                olt_ip, olt_identifier, fsp,
                state_data.get('port_state'),
                state_data.get('last_down_cause'),
                last_up_time_processed,
                last_down_time_processed,
                state_data.get('signal_detect'),
                state_data.get('available_bandwidth_kbps'),
                state_data.get('illegal_rogue_ont'),
                state_data.get('optical_module_status'),
                state_data.get('laser_state'),
                state_data.get('tx_fault'),
                state_data.get('temperature_c'),
                state_data.get('tx_bias_current_ma'),
                state_data.get('supply_voltage_v'),
                state_data.get('tx_power_dbm'),
                state_data.get('left_guaranteed_bandwidth_kbps'),
                state_data.get('admin_state')
            ))
        
        conn.commit()
        logging.info(f"[DB] [Estado PON] Dados de estado da porta PON {fsp} salvos com sucesso.") #
        return True
    except Exception as e:
        logging.error(f"Erro ao salvar dados de estado da porta PON {fsp}: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

def save_pon_statistics_packets(olt_ip, fsp, stats_data):
    """Salva as estatísticas de pacotes de uma porta PON no banco de dados."""
    logging.info(f"[DB] [Stats PON] Salvando estatísticas de pacotes para OLT {olt_ip}, PON {fsp}")
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        
        # Definir o fuso horário da sessão
        with conn.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'America/Sao_Paulo';")
        
        olt_identifier = olt_ip.split('.')[-1]
        
        columns = [
            'olt_ip', 'olt_identifier', 'fsp',
            'rx_frames', 'rx_bytes', 'rx_unicast_frames', 'rx_multicast_frames',
            'rx_broadcast_frames', 'rx_64_byte_frames', 'rx_65_127_byte_frames',
            'rx_128_255_byte_frames', 'rx_256_511_byte_frames', 'rx_512_1023_byte_frames',
            'rx_1024_1518_byte_frames', 'rx_over_1518_byte_frames', 'rx_undersize_discarded_frames',
            'rx_oversize_discarded_frames', 'rx_crc_error_frames', 'rx_discarded_frames',
            'rx_error_frames', 'tx_frames', 'tx_bytes', 'tx_unicast_frames',
            'tx_multicast_frames', 'tx_broadcast_frames', 'tx_64_byte_frames',
            'tx_65_127_byte_frames', 'tx_128_255_byte_frames', 'tx_256_511_byte_frames',
            'tx_512_1023_byte_frames', 'tx_1024_1518_byte_frames', 'tx_over_1518_byte_frames',
            'tx_buffer_overflow_frames'
        ]
        
        values = [
            olt_ip, olt_identifier, fsp,
            stats_data.get('rx_frames'), stats_data.get('rx_bytes'), stats_data.get('rx_unicast_frames'),
            stats_data.get('rx_multicast_frames'), stats_data.get('rx_broadcast_frames'),
            stats_data.get('rx_64_byte_frames'), stats_data.get('rx_65_127_byte_frames'),
            stats_data.get('rx_128_255_byte_frames'), stats_data.get('rx_256_511_byte_frames'),
            stats_data.get('rx_512_1023_byte_frames'), stats_data.get('rx_1024_1518_byte_frames'),
            stats_data.get('rx_over_1518_byte_frames'), stats_data.get('rx_undersize_discarded_frames'),
            stats_data.get('rx_oversize_discarded_frames'), stats_data.get('rx_crc_error_frames'),
            stats_data.get('rx_discarded_frames'), stats_data.get('rx_error_frames'),
            stats_data.get('tx_frames'), stats_data.get('tx_bytes'), stats_data.get('tx_unicast_frames'),
            stats_data.get('tx_multicast_frames'), stats_data.get('tx_broadcast_frames'),
            stats_data.get('tx_64_byte_frames'), stats_data.get('tx_65_127_byte_frames'),
            stats_data.get('tx_128_255_byte_frames'), stats_data.get('tx_256_511_byte_frames'),
            stats_data.get('tx_512_1023_byte_frames'), stats_data.get('tx_1024_1518_byte_frames'),
            stats_data.get('tx_over_1518_byte_frames'), stats_data.get('tx_buffer_overflow_frames')
        ]
        query = f"INSERT INTO pon_statistics_packets ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(values))})"
        
        with conn.cursor() as cursor:
            cursor.execute(query, tuple(values))
            conn.commit()
            logging.info(f"[DB] [Stats PON] Estatísticas para OLT {olt_ip}, PON {fsp} salvas com sucesso.")
            return True
    except Exception as e:
        logging.error(f"Erro ao salvar estatísticas de pacotes da PON {fsp}: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

# Em db/operations.py, função save_ont_traffic_bulk

def save_ont_traffic_bulk(olt_ip, fsp, traffic_list):
    """Salva uma lista de registros de tráfego de ONT no banco de dados."""
    if not traffic_list:
        # logging.warning(f"[{olt_ip}][{fsp}] Nenhum dado de tráfego para salvar.") # Opcional: pode ser muito verboso
        return 0
    
    logging.info(f"[DB] [Tráfego ONT] Salvando {len(traffic_list)} registros para OLT {olt_ip}, PON {fsp}") #
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        olt_identifier = olt_ip.split('.')[-1]
        
        # Prepara os dados para uma inserção em lote
        args_list = [
            (
                olt_ip,
                olt_identifier,
                fsp,
                item['ont_id'],
                item['up_traffic'],
                item['down_traffic']
            ) for item in traffic_list
        ]
        
        query = """
            INSERT INTO ont_traffic_data (
                olt_ip, olt_identifier, fsp, ont_id, collection_time,
                up_traffic_kbps, down_traffic_kbps
            ) VALUES (%s, %s, %s, %s, NOW(), %s, %s)
        """
        
        # Usar execute_batch para melhor performance
        from psycopg2.extras import execute_batch
        execute_batch(cursor, query, args_list)
        
        conn.commit()
        logging.info(f"[DB] [Tráfego ONT] {len(args_list)} registros para OLT {olt_ip}, PON {fsp} salvos com sucesso.") #
        return len(args_list)
        
    except Exception as e:
        logging.error(f"[{olt_ip}][{fsp}] Erro ao salvar tráfego de ONT em lote: {e}")
        if conn:
            conn.rollback()
        raise # <-- ADICIONADO: Força o erro a ser reportado para a GUI
    finally:
        if conn:
            conn.close()

def save_ont_statistics_packets_bulk(olt_ip, fsp, stats_list):
    """Salva uma lista de registros de estatísticas de pacotes de ONTs."""
    if not stats_list:
        return 0
    logging.info(f"[DB] [Stats ONT] Salvando {len(stats_list)} registros de estatísticas de pacotes para OLT {olt_ip}, PON {fsp}")
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        
        # Definir o fuso horário da sessão
        with conn.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'America/Sao_Paulo';")
        
        cursor = conn.cursor()
        olt_identifier = olt_ip.split('.')[-1]
        
        args_list = [
            (
                olt_ip, olt_identifier, fsp, item['ont_id'],
                item.get('upstream_frames'), item.get('upstream_bytes'), item.get('upstream_discarded_frames'),
                item.get('downstream_frames'), item.get('downstream_bytes'), item.get('downstream_discarded_frames')
            ) for item in stats_list
        ]
        
        query = """
            INSERT INTO ont_statistics_packets (
                olt_ip, olt_identifier, fsp, ont_id,
                upstream_frames, upstream_bytes, upstream_discarded_frames,
                downstream_frames, downstream_bytes, downstream_discarded_frames
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        from psycopg2.extras import execute_batch
        execute_batch(cursor, query, args_list)
        conn.commit()
        logging.info(f"[DB] [Stats ONT] {len(args_list)} registros para OLT {olt_ip}, PON {fsp} salvos com sucesso.")
        return len(args_list)
    except Exception as e:
        logging.error(f"Erro ao salvar estatísticas de pacotes de ONT para a PON {fsp}: {e}")
        if conn: conn.rollback()
        raise # <-- ADICIONADO: Força o erro a ser reportado para a GUI
    finally:
        if conn: conn.close()

def save_ont_eth_statistics_bulk(olt_ip, fsp, ont_id, stats_list_per_port):
    """Salva uma lista de registros de estatísticas de portas Ethernet de uma ONT."""
    if not stats_list_per_port:
        return 0
    logging.info(f"[DB] [Stats ETH] Salvando {len(stats_list_per_port)} registros de estatísticas Ethernet para OLT {olt_ip}, PON {fsp}, ONT {ont_id}")
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        
        # Definir o fuso horário da sessão para America/Sao_Paulo
        with conn.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'America/Sao_Paulo';")
            # Verifica se o fuso foi definido corretamente
            cursor.execute("SHOW timezone;")
            tz = cursor.fetchone()[0]
            logging.info(f"Fuso horário da sessão PostgreSQL: {tz}")
        
        cursor = conn.cursor()
        olt_identifier = olt_ip.split('.')[-1]
        
        # Obtém a hora atual no fuso de Brasília
        current_time = get_current_brasilia_time()
        
        args_list = []
        for item in stats_list_per_port:
            stats = item['stats']
            eth_port_id = item['eth_port_id']
            
            logging.debug(f"save_ont_eth_statistics_bulk: Preparando dados para porta {eth_port_id}: {stats}")
            
            # Converter duration_seconds para número se for string
            duration_seconds = stats.get('duration_seconds')
            if isinstance(duration_seconds, str):
                try:
                    duration_seconds = int(duration_seconds)
                except (ValueError, TypeError):
                    duration_seconds = None
            
            # Parâmetros na ordem correta
            params = (
                olt_ip,                                    # 1
                olt_identifier,                            # 2
                fsp,                                       # 3
                ont_id,                                    # 4
                eth_port_id,                               # 5
                stats.get('rx_frames'),                    # 6
                stats.get('tx_frames'),                    # 7
                stats.get('rx_bytes'),                     # 8
                stats.get('tx_bytes'),                     # 9
                stats.get('rx_unicast_frames'),            # 10
                stats.get('tx_unicast_frames'),            # 11
                stats.get('rx_multicast_frames'),          # 12
                stats.get('tx_multicast_frames'),          # 13
                stats.get('rx_broadcast_frames'),           # 14
                stats.get('tx_broadcast_frames'),           # 15
                stats.get('rx_error_frames'),              # 16
                stats.get('tx_error_frames'),              # 17
                stats.get('rx_discarded_frames'),          # 18
                stats.get('tx_discarded_frames'),          # 19
                stats.get('tx_collision_frames'),          # 20
                duration_seconds,                          # 21
                current_time.isoformat()                   # 22 - como string ISO com fuso
            )
            
            args_list.append(params)
        
        # SQL com placeholders correspondentes e CAST explícito
        query = """
            INSERT INTO ont_eth_port_statistics (
                olt_ip, olt_identifier, fsp, ont_id, eth_port_id,
                rx_frames, tx_frames, rx_bytes, tx_bytes,
                rx_unicast_frames, tx_unicast_frames,
                rx_multicast_frames, tx_multicast_frames,
                rx_broadcast_frames, tx_broadcast_frames,
                rx_error_frames, tx_error_frames,
                rx_discarded_frames, tx_discarded_frames,
                tx_collision_frames, duration_seconds, collection_time
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 
                CAST(%s AS TIMESTAMP WITH TIME ZONE))
        """
        
        logging.info(f"save_ont_eth_statistics_bulk: Salvando {len(args_list)} registros no banco. Timestamp: {current_time}")
        
        from psycopg2.extras import execute_batch
        execute_batch(cursor, query, args_list)
        conn.commit()
        
        # Verifica o timestamp que foi realmente inserido
        cursor.execute("""
            SELECT collection_time 
            FROM ont_eth_port_statistics 
            WHERE olt_ip = %s AND fsp = %s AND ont_id = %s 
            ORDER BY collection_time DESC 
            LIMIT 1
        """, (olt_ip, fsp, ont_id))
        inserted_time = cursor.fetchone()[0]
        logging.info(f"Timestamp inserido no banco (ont_eth_port_statistics): {inserted_time}")
        
        logging.info(f"[DB] [Stats ETH] {len(args_list)} registros para OLT {olt_ip}, PON {fsp}, ONT {ont_id} salvos com sucesso.")
        
        # Emite sinal para atualizar a GUI
        if 'db_signals' in globals():
            db_signals.ont_eth_stats_updated.emit()
        
        return len(args_list)
    except Exception as e:
        logging.error(f"save_ont_eth_statistics_bulk: Erro ao salvar estatísticas ETH para ONT {fsp}/{ont_id}: {e}", exc_info=True)
        if conn: 
            conn.rollback()
        return 0
    finally:
        if conn: 
            conn.close()

def save_uplink_ddm_data(olt_ip, ddm_data_list):
    """Salva dados DDM de uplink no banco de dados"""
    logging.info(f"[DB] [DDM Uplink] Salvando {len(ddm_data_list)} registros DDM para OLT {olt_ip}")
    conn = None
    try:
        olt_identifier = olt_ip.split('.')[-1]
        conn = psycopg2.connect(**DB_CONFIG)
        
        # Definir o fuso horário da sessão
        with conn.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'America/Sao_Paulo';")
        
        with conn.cursor() as cursor:
            args_list = []
            for data in ddm_data_list:
                # Determina status com base nos valores
                status = 'normal'
                if data.get('temperature_c', 0) > 80:
                    status = 'warning'
                if data.get('temperature_c', 0) > 85:
                    status = 'critical'
                
                args_list.append((
                    olt_ip, olt_identifier, data['placa'], data['slot'], data['port'],
                    data.get('temperature_c'), data.get('supply_voltage_v'),
                    data.get('tx_bias_current_ma'), data.get('tx_power_dbm'),
                    data.get('rx_power_dbm'), status
                ))
            
            query = """
                INSERT INTO uplink_ddm_data (
                    olt_ip, olt_identifier, placa, slot, port,
                    temperature_c, supply_voltage_v, tx_bias_current_ma,
                    tx_power_dbm, rx_power_dbm, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            from psycopg2.extras import execute_batch
            execute_batch(cursor, query, args_list)
            conn.commit()
            
            logging.info(f"[DB] [DDM Uplink] {len(args_list)} registros DDM para OLT {olt_ip} salvos com sucesso.")
            
            # Emitir o sinal para atualizar a GUI
            try:
                db_signals.data_updated.emit()
                logging.info(f"[{olt_ip}] Sinal data_updated emitido com sucesso para atualizar a GUI.")
            except Exception as e:
                logging.error(f"[{olt_ip}] Erro ao emitir sinal data_updated: {e}")
            
            return len(args_list)
            
    except Exception as e:
        logging.error(f"Erro ao salvar dados DDM para OLT {olt_ip}: {e}")
        if conn:
            conn.rollback()
        return 0
    finally:
        if conn:
            conn.close()
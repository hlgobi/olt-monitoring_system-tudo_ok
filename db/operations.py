# db/operations.py
# Este arquivo contém funções para operações no banco de dados PostgreSQL relacionadas ao monitoramento de OLTs e ONTs.
# Ele implementa a persistência de dados coletados das OLTs, incluindo informações de ONTs, status de PONs,
# dados de temperatura e recursos, além de histórico de diagnósticos.

# Importação do módulo psycopg2, que é o adaptador PostgreSQL para Python
import psycopg2

# Importação do módulo logging para registrar eventos e mensagens da aplicação
import logging

# Importação do módulo json para lidar com dados em formato JSON, especialmente os serviços das ONTs
import json

# Importação do dicionário DB_CONFIG do módulo config, que contém as configurações de conexão com o banco de dados
from config import DB_CONFIG

# Importação dos sinais do banco de dados para comunicação com a interface gráfica (GUI)
from gui.signals import db_signals

# Importação da função auxiliar para parsing avançado de descrições
from utils.helpers import parse_descricao_avancada

from PyQt5.QtCore import QObject, pyqtSignal

def save_ont_data(olt_ip, ont_info):
    """
    Salva ou atualiza os dados de uma ONT no banco de dados, incluindo detalhes de status
    e preservando o nome do cliente existente.
    
    Args:
        olt_ip (str): Endereço IP da OLT onde a ONT está conectada
        ont_info (dict): Dicionário contendo todas as informações da ONT coletadas da OLT
        
    Returns:
        None: A função não retorna valor, apenas salva os dados no banco
    """
    # Inicializa a variável de conexão como None
    conn = None
    try:
        # --- FUNÇÃO AUXILIAR PARA TRATAR TIMESTAMPS INVÁLIDOS ---
        def to_db_timestamp(ts_str):
            if ts_str in ['N/A', '-', None, '']:
                return None
            return ts_str
            
        # Extrai o identificador da OLT a partir do último octeto do endereço IP
        olt_identifier = olt_ip.split('.')[-1]
        
        # Parseia a descrição para obter primária, secundária e porta_secundária
        # utilizando a função auxiliar importada
        parsed_desc = parse_descricao_avancada(ont_info.get('description', 'N/A'))
        primaria = parsed_desc['primaria']
        secundaria = parsed_desc['secundaria']
        porta_secundaria = parsed_desc['porta_secundaria']
        
        # Estabelece conexão com o banco de dados usando as configurações do DB_CONFIG
        conn = psycopg2.connect(**DB_CONFIG)
        
        # Utiliza um cursor para executar comandos SQL
        with conn.cursor() as cursor:
            # Verifica o registro anterior desta ONT para detectar mudanças e preservar o nome do cliente
            cursor.execute("""
                SELECT fsp, ont_id, mac_address, client_name
                FROM public.ont_data
                WHERE serial_number = %s
                ORDER BY collection_time DESC
                LIMIT 1
            """, (ont_info['sn'],))
            previous_record = cursor.fetchone()
            
            # Inicializa variáveis para controle de mudanças
            fsp_changed = False
            ont_id_changed = False
            mac_changed = False
            previous_fsp = None
            previous_ont_id = None
            previous_mac = None
            existing_client_name = None
            
            # Se existe um registro anterior, extrai as informações e verifica se houve mudanças
            if previous_record:
                previous_fsp, previous_ont_id, previous_mac, existing_client_name = previous_record
                fsp_changed = previous_fsp != ont_info['fsp']
                ont_id_changed = previous_ont_id != int(ont_info['ont_id'])
                mac_changed = previous_mac and previous_mac != ont_info['mac'] and ont_info['mac'] != 'N/A'
            
            # Comando SQL para inserir os dados da ONT na tabela ont_data
            sql = """
                INSERT INTO public.ont_data
                (olt_ip, olt_identifier, fsp, ont_id, mac_address, client_name,
                previous_mac_address, serial_number, rx_power, tx_power,
                description, primaria, secundaria, porta_secundaria, 
                fsp_changed, ont_id_changed,
                previous_fsp, previous_ont_id, status,
                last_down_cause, last_up_time, last_down_time,
                last_dying_gasp_time, line_profile_name, services,
                ont_distance, memory_occupation, cpu_occupation, temperature,
                ont_ip_address, line_profile_id, service_profile_id, service_profile_name,
                connection_code)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            # Tupla de parâmetros correspondentes aos placeholders no SQL
            params = (
                olt_ip,
                olt_identifier,
                ont_info['fsp'],
                int(ont_info['ont_id']),
                ont_info['mac'] if ont_info['mac'] != 'N/A' else None,
                existing_client_name, # Preserva o nome do cliente existente
                previous_mac if mac_changed else None,
                ont_info['sn'],
                float(ont_info['rx']) if ont_info['rx'] not in ['N/A', '-'] else None,
                float(ont_info['tx']) if ont_info['tx'] not in ['N/A', '-'] else None,
                ont_info['description'],
                primaria,
                secundaria,
                porta_secundaria,
                fsp_changed,
                ont_id_changed,
                previous_fsp if fsp_changed else None,
                previous_ont_id if ont_id_changed else None,
                ont_info['status'],
                ont_info.get('last_down_cause'),
                # --- CORREÇÃO APLICADA AQUI ---
                to_db_timestamp(ont_info.get('last_up_time')),
                to_db_timestamp(ont_info.get('last_down_time')),
                to_db_timestamp(ont_info.get('last_dying_gasp_time')),
                ont_info.get('line_profile_name'),
                ont_info.get('services'),
                ont_info.get('ont_distance'),
                ont_info.get('memory_occupation'),
                ont_info.get('cpu_occupation'),
                ont_info.get('temperature'),
                ont_info.get('ont_ip_address'),
                ont_info.get('line_profile_id'),
                ont_info.get('service_profile_id'),
                ont_info.get('service_profile_name'),
                ont_info.get('connection_code')
            )
            
            log_details = (
                f"[DETALHES COLETADOS] S/N: {ont_info.get('sn', 'N/A')} | "
                f"Causa Queda: '{ont_info.get('last_down_cause', 'N/A')}' | "
                f"Temp: '{ont_info.get('temperature', 'N/A')}' | "
                f"CPU: '{ont_info.get('cpu_occupation', 'N/A')}' | "
                f"Perfil: '{ont_info.get('line_profile_name', 'N/A')}'"
            )
            logging.info(log_details)
            
            cursor.execute(sql, params)
            conn.commit()
            
            logging.info(f"Dados da ONT {ont_info['sn']} (Cliente: {existing_client_name}) inseridos com sucesso no banco.")
            
            if fsp_changed or ont_id_changed or mac_changed:
                change_msg = f"Mudança detectada para ONT {ont_info['sn']}:"
                if fsp_changed:
                    change_msg += f"\n  FSP mudou de {previous_fsp} para {ont_info['fsp']}"
                if ont_id_changed:
                    change_msg += f"\n  ONT-ID mudou de {previous_ont_id} para {ont_info['ont_id']}"
                if mac_changed:
                    change_msg += f"\n  MAC mudou de {previous_mac} para {ont_info['mac']}"
                logging.warning(change_msg)
                
    except Exception as e:
        logging.error(f"Erro ao salvar ONT {ont_info.get('sn', 'N/A')} ({ont_info.get('fsp', 'N/A')}/{ont_info.get('ont_id', 'N/A')}): {str(e)}", exc_info=True)
        if conn:
            conn.rollback()
    finally:
        if conn is not None:
            conn.close()
            
def save_pon_status(olt_ip, fsp, online_count, total_count):
    """
    Salva o status da PON no banco de dados.
    
    Args:
        olt_ip (str): Endereço IP da OLT
        fsp (str): Identificador Frame/Slot/Porta da PON
        online_count (int): Número de ONTs online na PON
        total_count (int): Número total de ONTs na PON
        
    Returns:
        None: A função não retorna valor, apenas salva os dados no banco
    """
    conn = None
    try:
        # Extrai o identificador da OLT a partir do último octeto do endereço IP
        olt_identifier = olt_ip.split('.')[-1]
        
        # Estabelece conexão com o banco de dados
        conn = psycopg2.connect(**DB_CONFIG)
        
        # Determina o status da PON com base na proporção de ONTs online
        if total_count == 0:
            status = "empty"
        elif online_count == total_count:
            status = "operational"
        elif online_count >= total_count * 0.7:
            status = "degraded"
        else:
            status = "faulty"
            
        # Utiliza um cursor para executar comandos SQL
        with conn.cursor() as cursor:
            # Comando SQL para inserir os dados de status da PON
            cursor.execute("""
                INSERT INTO pon_status
                (olt_ip, olt_identifier, fsp, online_count, total_count, status)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                olt_ip,
                olt_identifier,
                fsp,
                online_count,
                total_count,
                status
            ))
            
            # Confirma as alterações no banco de dados
            conn.commit()
            
            # Registra no log que o status foi inserido com sucesso
            logging.info(f"Status da PON {fsp} inserido com sucesso para OLT {olt_ip}.")
            
    except Exception as e:
        # Em caso de erro, registra a exceção
        logging.error(f"Erro ao salvar status da PON {fsp}: {str(e)}")
        # Se houver uma conexão ativa, desfaz as alterações
        if conn:
            conn.rollback()
    finally:
        # Garante que a conexão seja fechada
        if conn is not None:
            conn.close()

def save_temp_data(olt_ip, temp_data):
    """
    Salva dados de temperatura no banco de dados e gera logs detalhados por slot.
    
    Args:
        olt_ip (str): Endereço IP da OLT
        temp_data (list): Lista de dicionários contendo dados de temperatura por slot
        
    Returns:
        int: Número de registros inseridos com sucesso, ou 0 em caso de erro
    """
    conn = None
    try:
        # Extrai o identificador da OLT a partir do último octeto do endereço IP
        olt_identifier = olt_ip.split('.')[-1]
        
        # Estabelece conexão com o banco de dados
        conn = psycopg2.connect(**DB_CONFIG)
        
        # Utiliza um cursor para executar comandos SQL
        with conn.cursor() as cursor:
            # Itera sobre cada conjunto de dados de temperatura
            for data in temp_data:
                # Comando SQL para inserir os dados de temperatura
                cursor.execute("""
                    INSERT INTO temperature_monitoring
                    (olt_ip, olt_identifier, slot_id, board_name, temperature_c, temperature_f, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    olt_ip,
                    olt_identifier,
                    data['slot_id'],
                    data['board_name'],
                    data['temp_c'],
                    data['temp_f'],
                    data['status']
                ))
                
                # Registra no log os detalhes da temperatura para este slot
                logging.info(
                    f"[TEMP] OLT {olt_ip} | Slot {data['slot_id']} | "
                    f"{data['board_name']} | {data['temp_c']}°C / {data['temp_f']}°F | "
                    f"Status: {data['status']}"
                )
            
            # Confirma as alterações no banco de dados
            conn.commit()
            
            # Registra no log o total de registros inseridos
            logging.info(f"{len(temp_data)} registros de temperatura inseridos com sucesso para OLT {olt_ip}.")
            
            # Emite um sinal para a GUI indicando que os dados de temperatura foram atualizados
            db_signals.temperature_updated.emit()
            
            # Retorna o número de registros inseridos
            return len(temp_data)
            
    except Exception as e:
        # Em caso de erro, registra a exceção
        logging.error(f"Erro ao salvar dados de temperatura para OLT {olt_ip}: {str(e)}")
        # Se houver uma conexão ativa, desfaz as alterações
        if conn:
            conn.rollback()
        # Retorna 0 indicando que nenhum registro foi inserido
        return 0
    finally:
        # Garante que a conexão seja fechada
        if conn is not None:
            conn.close()

def save_resource_data(olt_ip, resource_data):
    """
    Salva dados de monitoramento de recursos no banco de dados e gera logs detalhados por slot e tipo.
    
    Args:
        olt_ip (str): Endereço IP da OLT
        resource_data (list): Lista de dicionários contendo dados de recursos por slot
        
    Returns:
        int: Número de registros inseridos com sucesso, ou 0 em caso de erro
    """
    conn = None
    try:
        # Extrai o identificador da OLT a partir do último octeto do endereço IP
        olt_identifier = olt_ip.split('.')[-1]
        
        # Estabelece conexão com o banco de dados
        conn = psycopg2.connect(**DB_CONFIG)
        
        # Utiliza um cursor para executar comandos SQL
        with conn.cursor() as cursor:
            # Itera sobre cada conjunto de dados de recursos
            for data in resource_data:
                # Comando SQL para inserir os dados de recursos
                cursor.execute("""
                    INSERT INTO resource_monitoring
                    (olt_ip, olt_identifier, slot_id, board_name, resource_type, usage_percentage, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    olt_ip,
                    olt_identifier,
                    int(data['slot']),
                    data.get('board_name', 'N/A'),
                    data['type'],
                    data['usage'],
                    data['status']
                ))
                
                # Registra no log os detalhes do recurso para este slot
                logging.info(
                    f"[{data['type'].upper()}] OLT {olt_ip} | Slot {data['slot']} | "
                    f"{data.get('board_name', 'N/A')} | Uso: {data['usage']}% | "
                    f"Status: {data['status']}"
                )
            
            # Confirma as alterações no banco de dados
            conn.commit()
            
            # Registra no log o total de registros inseridos
            logging.info(f"{len(resource_data)} registros de recurso inseridos com sucesso para OLT {olt_ip}.")
            
            # Retorna o número de registros inseridos
            return len(resource_data)
            
    except Exception as e:
        # Em caso de erro, registra a exceção
        logging.error(f"Erro ao salvar dados de recursos para OLT {olt_ip}: {str(e)}")
        # Se houver uma conexão ativa, desfaz as alterações
        if conn:
            conn.rollback()
        # Retorna 0 indicando que nenhum registro foi inserido
        return 0
    finally:
        # Garante que a conexão seja fechada
        if conn is not None:
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
    """
    Salva os dados de diagnóstico de uma ONT no banco de dados.
    
    Args:
        diag_info (dict): Dicionário contendo todas as informações de diagnóstico da ONT
        
    Returns:
        None: A função não retorna valor, apenas salva os dados no banco
    """
    conn = None
    
    # Comando SQL para inserir os dados de diagnóstico
    sql = """
        INSERT INTO ont_diagnostics_history (
            ont_serial_number, olt_identifier, fsp, ont_id_on_pon, 
            diag_section_id, raw_output, parsed_data,
            manufacturer, model_name, uptime, firmware_version
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
    """
    
    try:
        # Estabelece conexão com o banco de dados
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # Extrai os dados parseados do dicionário de informações de diagnóstico
        p_data = diag_info.get('parsed_data_dict', {})
        
        # Extrai informações específicas do dicionário de dados parseados
        manufacturer = p_data.get('Manufacturer')
        model_name = p_data.get('ModelName')
        uptime = p_data.get('UpTime')
        firmware_version = p_data.get('main software version') 
        
        # Executa o comando SQL com os parâmetros
        cursor.execute(sql, (
            diag_info.get('ont_serial_number'),
            diag_info.get('olt_identifier'),
            diag_info.get('fsp'),
            diag_info.get('ont_id_on_pon'),
            diag_info.get('diag_section_id'),
            diag_info.get('raw_output'),
            json.dumps(p_data) if p_data else None,  # Converte o dicionário para JSON se existir
            manufacturer,
            model_name,
            uptime,
            firmware_version
        ))
        
        # Confirma as alterações no banco de dados
        conn.commit()
        
        # Registra no log que os dados foram salvos com sucesso
        logging.info(f"Dados de diagnóstico para ONT S/N {diag_info.get('ont_serial_number')}, seção {diag_info.get('diag_section_id')} salvos com sucesso.")
        
    except Exception as e:
        # Em caso de erro, registra a exceção
        logging.error(f"Erro ao salvar dados de diagnóstico da ONT S/N {diag_info.get('ont_serial_number')}: {e}", exc_info=True)
        # Se houver uma conexão ativa, desfaz as alterações
        if conn:
            conn.rollback()
    finally:
        # Garante que a conexão seja fechada
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
            
def save_pon_traffic_data(olt_ip, fsp, traffic_data):
    """Salva os dados de tráfego de uma porta PON no banco de dados."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
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
        # Emitir sinal de status
        db_signals.pon_traffic_status_changed.emit(olt_ip, fsp, "Dados salvos com sucesso")
        return True
    except Exception as e:
        logging.error(f"Erro ao salvar dados de tráfego PON: {e}")
        # Emitir sinal de erro
        db_signals.pon_traffic_status_changed.emit(olt_ip, fsp, f"Erro: {str(e)}")
        return False
    finally:
        if conn:
            conn.close()

class DatabaseSignals(QObject):
    # Sinais existentes
    data_updated = pyqtSignal()
    pon_status_updated = pyqtSignal()
    temperature_updated = pyqtSignal()
    temp_data_collected = pyqtSignal(object)
    resource_data_collected = pyqtSignal(object)
    update_status = pyqtSignal(str, str, str)
    ont_connection_status_changed = pyqtSignal(bool, str)
    ont_command_output_received = pyqtSignal(str, str, bool)
    ont_cycle_completed = pyqtSignal(str, int, float)
    
    # Sinais para tráfego PON
    pon_traffic_updated = pyqtSignal()
    pon_traffic_status_changed = pyqtSignal(str, str, str)  # olt_ip, fsp, status

# Instância global para uso em todo o aplicativo
db_signals = DatabaseSignals()

# Em db/operations.py, substitua a função save_pon_port_state

def save_pon_port_state(olt_ip, fsp, state_data):
    """Salva os dados de estado da porta PON no banco de dados."""
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        olt_identifier = olt_ip.split('.')[-1]
        
        # --- INÍCIO DA MODIFICAÇÃO ---
        query = """
            INSERT INTO pon_port_state (
                olt_ip, olt_identifier, fsp, port_state, last_down_cause, last_up_time, last_down_time,
                signal_detect, available_bandwidth_kbps, illegal_rogue_ont,
                optical_module_status, laser_state, tx_fault, temperature_c,
                tx_bias_current_ma, supply_voltage_v, tx_power_dbm,
                left_guaranteed_bandwidth_kbps, admin_state
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        cursor.execute(query, (
            olt_ip,
            olt_identifier,
            fsp,
            state_data.get('port_state'),
            state_data.get('last_down_cause'),
            state_data.get('last_up_time'),
            state_data.get('last_down_time'),
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
            state_data.get('left_guaranteed_bandwidth_kbps'), # Novo campo
            state_data.get('admin_state')                     # Novo campo
        ))
        # --- FIM DA MODIFICAÇÃO ---
        
        conn.commit()
        logging.info(f"Dados de estado da porta PON {fsp} salvos com sucesso.")
        return True
    except Exception as e:
        logging.error(f"Erro ao salvar dados de estado da porta PON {fsp}: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

# Em db/operations.py, adicione esta função ao final do arquivo

def save_pon_statistics_packets(olt_ip, fsp, stats_data):
    """Salva as estatísticas de pacotes de uma porta PON no banco de dados."""
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        olt_identifier = olt_ip.split('.')[-1]
        
        columns = [
            'olt_ip', 'olt_identifier', 'fsp',
            'rx_frames', 'rx_bytes', 'rx_unicast_frames', 'rx_multicast_frames', 'rx_broadcast_frames',
            'rx_64_byte_frames', 'rx_65_127_byte_frames', 'rx_128_255_byte_frames',
            'rx_256_511_byte_frames', 'rx_512_1023_byte_frames', 'rx_1024_1518_byte_frames',
            'rx_over_1518_byte_frames', 'rx_undersize_discarded_frames',
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
        
        cursor.execute(query, tuple(values))
        conn.commit()
        logging.info(f"Estatísticas de pacotes da PON {fsp} salvas com sucesso.")
        return True
    except Exception as e:
        logging.error(f"Erro ao salvar estatísticas de pacotes da PON {fsp}: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

# Em db/operations.py, adicione esta função ao final do arquivo

def save_ont_traffic_bulk(olt_ip, fsp, traffic_list):
    """Salva uma lista de registros de tráfego de ONT no banco de dados."""
    if not traffic_list:
        logging.warning(f"[{olt_ip}][{fsp}] Nenhum dado de tráfego para salvar.")
        return 0

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
        logging.info(f"[{olt_ip}][{fsp}] {len(args_list)} registros de tráfego inseridos com sucesso no banco de dados.")
        return len(args_list)
        
    except Exception as e:
        logging.error(f"[{olt_ip}][{fsp}] Erro ao salvar tráfego de ONT em lote: {e}")
        if conn:
            conn.rollback()
        return 0
    finally:
        if conn:
            conn.close()

# --- INÍCIO DA MODIFICAÇÃO ---
def save_ont_statistics_packets_bulk(olt_ip, fsp, stats_list):
    """Salva uma lista de registros de estatísticas de pacotes de ONTs."""
    if not stats_list:
        return 0
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
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
        logging.info(f"{len(args_list)} registros de estatísticas de pacotes de ONT para a PON {fsp} salvos.")
        return len(args_list)
    except Exception as e:
        logging.error(f"Erro ao salvar estatísticas de pacotes de ONT para a PON {fsp}: {e}")
        if conn: conn.rollback()
        return 0
    finally:
        if conn: conn.close()
# --- FIM DA MODIFICAÇÃO ---

# --- INÍCIO DA MODIFICAÇÃO ---
def save_ont_eth_statistics_bulk(olt_ip, fsp, ont_id, stats_list_per_port):
    """
    Salva uma lista de registros de estatísticas de portas Ethernet de uma ONT.
    Versão melhorada com mais logs e tratamento de erros.
    """
    if not stats_list_per_port:
        logging.warning(f"save_ont_eth_statistics_bulk: Nenhum dado para salvar para ONT {fsp}/{ont_id}")
        return 0

    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        olt_identifier = olt_ip.split('.')[-1]
        
        args_list = []
        for item in stats_list_per_port:
            stats = item['stats']
            eth_port_id = item['eth_port_id']
            
            # Log dos dados que serão salvos
            logging.debug(f"save_ont_eth_statistics_bulk: Preparando dados para porta {eth_port_id}: {stats}")
            
            args_list.append((
                olt_ip, olt_identifier, fsp, ont_id, eth_port_id,
                stats.get('rx_frames'), stats.get('tx_frames'),
                stats.get('rx_bytes'), stats.get('tx_bytes'),
                stats.get('rx_unicast_frames'), stats.get('tx_unicast_frames'),
                stats.get('rx_multicast_frames'), stats.get('tx_multicast_frames'),
                stats.get('rx_broadcast_frames'), stats.get('tx_broadcast_frames'),
                stats.get('rx_error_frames'), stats.get('tx_error_frames'),
                stats.get('rx_discarded_frames'), stats.get('tx_discarded_frames'),
                stats.get('tx_collision_frames'), stats.get('duration_seconds')
            ))
        
        query = """
            INSERT INTO ont_eth_port_statistics (
                olt_ip, olt_identifier, fsp, ont_id, eth_port_id,
                rx_frames, tx_frames, rx_bytes, tx_bytes,
                rx_unicast_frames, tx_unicast_frames,
                rx_multicast_frames, tx_multicast_frames,
                rx_broadcast_frames, tx_broadcast_frames,
                rx_error_frames, tx_error_frames,
                rx_discarded_frames, tx_discarded_frames,
                tx_collision_frames, duration_seconds
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        logging.info(f"save_ont_eth_statistics_bulk: Salvando {len(args_list)} registros no banco")
        
        from psycopg2.extras import execute_batch
        execute_batch(cursor, query, args_list)
        conn.commit()
        
        logging.info(f"save_ont_eth_statistics_bulk: {len(args_list)} registros de estatísticas ETH para ONT {fsp}/{ont_id} salvos com sucesso.")
        
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
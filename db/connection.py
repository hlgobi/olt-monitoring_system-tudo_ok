# olt_monitoring_system/db/connection.py
import psycopg2
import logging
import time
from config import DB_CONFIG

def create_tables():
    """Cria ou atualiza todas as tabelas necessárias no banco de dados PostgreSQL."""
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            # Tabela de Dados ONT (Optical Network Terminal)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.ont_data (
                    id SERIAL PRIMARY KEY,
                    olt_identifier VARCHAR(50) NOT NULL,
                    fsp VARCHAR(20) NOT NULL,
                    ont_id INTEGER NOT NULL,
                    serial_number VARCHAR(64),
                    mac_address VARCHAR(18),
                    rx_power VARCHAR(10),
                    tx_power VARCHAR(10),
                    description TEXT,
                    status VARCHAR(20),
                    primaria VARCHAR(100),
                    secundaria VARCHAR(100),
                    porta_secundaria VARCHAR(20),
                    last_down_cause TEXT,
                    last_up_time TIMESTAMP WITH TIME ZONE,
                    last_down_time TIMESTAMP WITH TIME ZONE,
                    last_dying_gasp_time TIMESTAMP WITH TIME ZONE,
                    services JSONB,
                    ont_distance VARCHAR(20),
                    memory_occupation VARCHAR(20),
                    cpu_occupation VARCHAR(20),
                    temperature VARCHAR(20),
                    ont_ip_address VARCHAR(20),
                    line_profile_id VARCHAR(20),
                    line_profile_name VARCHAR(50),
                    service_profile_id VARCHAR(20),
                    service_profile_name VARCHAR(50),
                    collection_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    connection_code VARCHAR(50),
                    client_name VARCHAR(100)
                );
            """)
            logging.info("Tabela 'public.ont_data' verificada/criada.")
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.pon_traffic_data (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(50) NOT NULL,
                    fsp VARCHAR(20) NOT NULL,
                    collection_time TIMESTAMP NOT NULL DEFAULT NOW(),
                    up_traffic_kbps FLOAT,
                    down_traffic_kbps FLOAT,
                    upstream_broadcast_pps INTEGER,
                    upstream_multicast_pps INTEGER,
                    upstream_unicast_pps INTEGER,
                    downstream_broadcast_pps INTEGER,
                    downstream_multicast_pps INTEGER,
                    downstream_unicast_pps INTEGER
                );
            """)
            logging.info("Tabela 'public.pon_traffic_data' verificada/criada.")
            
            # Índices para melhor performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pon_traffic_olt_fsp ON public.pon_traffic_data (olt_ip, fsp);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pon_traffic_time ON public.pon_traffic_data (collection_time);")

            # --- CORREÇÃO: Garante que as colunas de data/hora usem o tipo correto ---
            alter_commands = [
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS olt_ip VARCHAR(15);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS previous_mac_address VARCHAR(18);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS fsp_changed BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS ont_id_changed BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS previous_fsp VARCHAR(20);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS previous_ont_id INTEGER;",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS olt_identifier VARCHAR(10);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS primaria VARCHAR(100);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS secundaria VARCHAR(100);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS porta_secundaria VARCHAR(10);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS client_name TEXT;",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS status VARCHAR(10) DEFAULT 'offline';",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS connection_code VARCHAR(50);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS last_down_cause VARCHAR(100);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS last_up_time TIMESTAMP WITH TIME ZONE;",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS last_down_time TIMESTAMP WITH TIME ZONE;",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS last_dying_gasp_time TIMESTAMP WITH TIME ZONE;",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS line_profile_name VARCHAR(100);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS services JSONB;",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS ont_distance VARCHAR(20);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS memory_occupation VARCHAR(10);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS cpu_occupation VARCHAR(10);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS temperature VARCHAR(10);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS ont_ip_address VARCHAR(50);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS line_profile_id VARCHAR(20);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS service_profile_name VARCHAR(100);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS service_profile_id VARCHAR(20);",
            ]
            
            for command in alter_commands:
                cursor.execute(command)
            logging.info("Colunas da tabela 'public.ont_data' verificadas/adicionadas.")
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_sn ON public.ont_data(serial_number);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_fsp ON public.ont_data(fsp);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_mac ON public.ont_data(mac_address);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_time ON public.ont_data(collection_time);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_olt ON public.ont_data(olt_identifier);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_primaria ON public.ont_data(primaria);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_secundaria ON public.ont_data(secundaria);")
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.pon_status (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(15) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL,
                    collection_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    fsp VARCHAR(10) NOT NULL,
                    online_count INTEGER NOT NULL,
                    total_count INTEGER NOT NULL,
                    status VARCHAR(15) NOT NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pon_status_olt_fsp_time ON public.pon_status(olt_identifier, fsp, collection_time DESC);")
            logging.info("Tabela 'public.pon_status' verificada/criada.")
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.temperature_monitoring (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(15) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL,
                    collection_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    slot_id VARCHAR(10) NOT NULL,
                    board_name VARCHAR(50),
                    temperature_c FLOAT NOT NULL,
                    temperature_f FLOAT NOT NULL,
                    status VARCHAR(20) DEFAULT 'normal'
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_temp_monitoring_olt_slot_time ON public.temperature_monitoring(olt_identifier, slot_id, collection_time DESC);")
            logging.info("Tabela 'public.temperature_monitoring' verificada/criada.")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.pon_port_state (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(50) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL,
                    fsp VARCHAR(20) NOT NULL,
                    collection_time TIMESTAMP NOT NULL DEFAULT NOW(),
                    port_state VARCHAR(20),
                    last_down_cause VARCHAR(100),
                    last_up_time TIMESTAMP,
                    last_down_time TIMESTAMP,
                    signal_detect VARCHAR(20),
                    available_bandwidth_kbps INTEGER,
                    illegal_rogue_ont VARCHAR(50),
                    optical_module_status VARCHAR(20),
                    laser_state VARCHAR(20),
                    tx_fault VARCHAR(20),
                    temperature_c FLOAT,
                    tx_bias_current_ma FLOAT,
                    supply_voltage_v FLOAT,
                    tx_power_dbm FLOAT,
                    left_guaranteed_bandwidth_kbps INTEGER,
                    admin_state VARCHAR(20)
                );
            """)
            logging.info("Tabela 'public.pon_port_state' verificada/criada.")
            
            cursor.execute("ALTER TABLE public.pon_port_state ADD COLUMN IF NOT EXISTS olt_identifier VARCHAR(10);")
            cursor.execute("ALTER TABLE public.pon_port_state ADD COLUMN IF NOT EXISTS left_guaranteed_bandwidth_kbps INTEGER;")
            cursor.execute("ALTER TABLE public.pon_port_state ADD COLUMN IF NOT EXISTS admin_state VARCHAR(20);")

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pon_port_state_olt_fsp ON public.pon_port_state (olt_ip, fsp);")
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.resource_monitoring (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(15) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL,
                    collection_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    slot_id VARCHAR(10) NOT NULL,
                    board_name VARCHAR(50),
                    resource_type VARCHAR(10) NOT NULL,
                    usage_percentage FLOAT NOT NULL,
                    status VARCHAR(20) DEFAULT 'normal'
                );
            """)
            cursor.execute("ALTER TABLE public.resource_monitoring ADD COLUMN IF NOT EXISTS board_name VARCHAR(50);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_monitoring_olt_slot_type_time ON public.resource_monitoring(olt_identifier, slot_id, resource_type, collection_time DESC);")
            logging.info("Tabela 'public.resource_monitoring' verificada/criada.")
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.ont_diagnostics_history (
                    id SERIAL PRIMARY KEY,
                    ont_serial_number VARCHAR(50) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL,
                    fsp VARCHAR(20),
                    ont_id_on_pon INT,
                    diag_section_id VARCHAR(50) NOT NULL,
                    diag_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    raw_output TEXT,
                    parsed_data JSONB,
                    manufacturer VARCHAR(255) DEFAULT NULL,
                    model_name VARCHAR(100) DEFAULT NULL,
                    uptime VARCHAR(100) DEFAULT NULL,
                    firmware_version VARCHAR(100) DEFAULT NULL
                );
            """)
            logging.info("Tabela 'public.ont_diagnostics_history' verificada/criada.")
        
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.ont_statistics_packets (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(50) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL,
                    fsp VARCHAR(20) NOT NULL,
                    ont_id INTEGER NOT NULL,
                    collection_time TIMESTAMP NOT NULL DEFAULT NOW(),
                    upstream_frames BIGINT,
                    upstream_bytes BIGINT,
                    upstream_discarded_frames BIGINT,
                    downstream_frames BIGINT,
                    downstream_bytes BIGINT,
                    downstream_discarded_frames BIGINT
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_stats_packets_fsp_ont_id_time ON public.ont_statistics_packets(fsp, ont_id, collection_time DESC);")
            logging.info("Tabela 'public.ont_statistics_packets' verificada/criada.")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.pon_statistics_packets (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(50) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL,
                    fsp VARCHAR(20) NOT NULL,
                    collection_time TIMESTAMP NOT NULL DEFAULT NOW(),
                    rx_frames BIGINT, rx_bytes BIGINT, rx_unicast_frames BIGINT, rx_multicast_frames BIGINT,
                    rx_broadcast_frames BIGINT, rx_64_byte_frames BIGINT, rx_65_127_byte_frames BIGINT,
                    rx_128_255_byte_frames BIGINT, rx_256_511_byte_frames BIGINT, rx_512_1023_byte_frames BIGINT,
                    rx_1024_1518_byte_frames BIGINT, rx_over_1518_byte_frames BIGINT, rx_undersize_discarded_frames BIGINT,
                    rx_oversize_discarded_frames BIGINT, rx_crc_error_frames BIGINT, rx_discarded_frames BIGINT,
                    rx_error_frames BIGINT, tx_frames BIGINT, tx_bytes BIGINT, tx_unicast_frames BIGINT,
                    tx_multicast_frames BIGINT, tx_broadcast_frames BIGINT, tx_64_byte_frames BIGINT,
                    tx_65_127_byte_frames BIGINT, tx_128_255_byte_frames BIGINT, tx_256_511_byte_frames BIGINT,
                    tx_512_1023_byte_frames BIGINT, tx_1024_1518_byte_frames BIGINT, tx_over_1518_byte_frames BIGINT,
                    tx_buffer_overflow_frames BIGINT
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pon_stats_packets_fsp_time ON public.pon_statistics_packets(fsp, collection_time DESC);")
            logging.info("Tabela 'public.pon_statistics_packets' verificada/criada.")
        
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.ont_traffic_data (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(50) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL,
                    fsp VARCHAR(20) NOT NULL,
                    ont_id INTEGER NOT NULL,
                    collection_time TIMESTAMP NOT NULL DEFAULT NOW(),
                    up_traffic_kbps INTEGER,
                    down_traffic_kbps INTEGER
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_traffic_fsp_ont_id_time ON public.ont_traffic_data(fsp, ont_id, collection_time DESC);")
            logging.info("Tabela 'public.ont_traffic_data' verificada/criada.")
        
            # Tabela de Estatísticas de Porta Ethernet por ONT
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ont_eth_port_statistics (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(50) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL,
                    fsp VARCHAR(20) NOT NULL,
                    ont_id INTEGER NOT NULL,
                    eth_port_id INTEGER NOT NULL,
                    collection_time TIMESTAMP NOT NULL DEFAULT NOW(),
                    rx_frames BIGINT,
                    tx_frames BIGINT,
                    rx_bytes BIGINT,
                    tx_bytes BIGINT,
                    rx_unicast_frames BIGINT,
                    tx_unicast_frames BIGINT,
                    rx_multicast_frames BIGINT,
                    tx_multicast_frames BIGINT,
                    rx_broadcast_frames BIGINT,
                    tx_broadcast_frames BIGINT,
                    rx_error_frames BIGINT,
                    tx_error_frames BIGINT,
                    rx_discarded_frames BIGINT,
                    tx_discarded_frames BIGINT,
                    tx_collision_frames BIGINT,
                    duration_seconds BIGINT
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_eth_stats_fsp_ont_eth_time ON ont_eth_port_statistics(fsp, ont_id, eth_port_id, collection_time DESC);")
            logging.info("Tabela 'ont_eth_port_statistics' verificada/criada.")
            
        conn.commit()
        logging.info("Todas as tabelas e colunas foram verificadas/criadas com sucesso no esquema 'public'.")
        return True
    except Exception as e: 
        logging.error(f"ERRO CRÍTICO: Falha ao criar tabelas: {str(e)}", exc_info=True) 
        if conn:
            conn.rollback()
        return False 
    finally: 
        if conn: 
            conn.close()

def check_db_connection():
    """Verifica a conexão com o banco de dados PostgreSQL com lógica de nova tentativa."""
    max_retries = 3
    for attempt in range(max_retries):
        conn = None
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            return True
        except Exception as e:
            logging.warning(f"Tentativa {attempt+1}/{max_retries}: Conexão PostgreSQL falhou: {e}")
            time.sleep(2)
        finally:
            if conn is not None:
                conn.close()
    return False
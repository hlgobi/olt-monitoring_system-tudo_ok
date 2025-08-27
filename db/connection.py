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
                CREATE TABLE IF NOT EXISTS ont_data (
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
                    last_up_time TIMESTAMP,
                    last_down_time TIMESTAMP,
                    last_dying_gasp_time TIMESTAMP,
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
                    connection_code VARCHAR(50),  -- NOVA COLUNA
                    client_name VARCHAR(100)  -- Se precisar armazenar o nome também                
                           );
            """)
            logging.info("Tabela 'ont_data' verificada/criada.")
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pon_traffic_data (
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
            
            # Índices para melhor performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pon_traffic_olt_fsp ON pon_traffic_data (olt_ip, fsp);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pon_traffic_time ON pon_traffic_data (collection_time);")

            # Comandos para adicionar colunas se não existirem (migração de schema)
            # Esta abordagem garante que o script possa ser executado em bancos de dados novos ou existentes.
            alter_commands = [
                # Colunas faltantes no CREATE TABLE original
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS olt_ip VARCHAR(15);",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS previous_mac_address VARCHAR(18);",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS fsp_changed BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS ont_id_changed BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS previous_fsp VARCHAR(20);",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS previous_ont_id INTEGER;",
                
                # Colunas existentes
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS olt_identifier VARCHAR(10);",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS primaria VARCHAR(100);",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS secundaria VARCHAR(100);",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS porta_secundaria VARCHAR(10);",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS client_name TEXT;",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS status VARCHAR(10) DEFAULT 'offline';",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS connection_code VARCHAR(50);",
                
                # Colunas de detalhes da primeira fase
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS last_down_cause VARCHAR(100);",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS last_up_time VARCHAR(50);",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS last_down_time VARCHAR(50);",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS last_dying_gasp_time VARCHAR(50);",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS line_profile_name VARCHAR(100);",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS services JSONB;",
                
                # --- NOVAS COLUNAS DE DETALHES ADICIONADAS AQUI ---
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS ont_distance VARCHAR(20);",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS memory_occupation VARCHAR(10);",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS cpu_occupation VARCHAR(10);",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS temperature VARCHAR(10);",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS ont_ip_address VARCHAR(50);",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS line_profile_id VARCHAR(20);",
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS service_profile_name VARCHAR(100);",
                # COLUNA FALTANTE ADICIONADA AQUI
                "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS service_profile_id VARCHAR(20);",
            ]
            
            for command in alter_commands:
                cursor.execute(command)
            logging.info("Colunas da tabela 'ont_data' verificadas/adicionadas.")
            
            # Índices para a tabela ont_data
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_sn ON ont_data(serial_number);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_fsp ON ont_data(fsp);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_mac ON ont_data(mac_address);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_time ON ont_data(collection_time);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_olt ON ont_data(olt_identifier);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_primaria ON ont_data(primaria);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_secundaria ON ont_data(secundaria);")
            
            # Tabela de Status da PON
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pon_status (
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
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pon_status_olt_fsp_time ON pon_status(olt_identifier, fsp, collection_time DESC);")
            logging.info("Tabela 'pon_status' verificada/criada.")
            
            # Tabela de Monitoramento de Temperatura
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS temperature_monitoring (
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
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_temp_monitoring_olt_slot_time ON temperature_monitoring(olt_identifier, slot_id, collection_time DESC);")
            logging.info("Tabela 'temperature_monitoring' verificada/criada.")

            # Tabela de Estado da Porta PON
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pon_port_state (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(50) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL, -- Adicionado para consistência
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
                    -- --- INÍCIO DA MODIFICAÇÃO ---
                    left_guaranteed_bandwidth_kbps INTEGER,
                    admin_state VARCHAR(20)
                    -- --- FIM DA MODIFICAÇÃO ---
                );
            """)
            
            # --- INÍCIO DA MODIFICAÇÃO (ALTER TABLE) ---
            # Adiciona as colunas se a tabela já existir
            cursor.execute("ALTER TABLE pon_port_state ADD COLUMN IF NOT EXISTS olt_identifier VARCHAR(10);")
            cursor.execute("ALTER TABLE pon_port_state ADD COLUMN IF NOT EXISTS left_guaranteed_bandwidth_kbps INTEGER;")
            cursor.execute("ALTER TABLE pon_port_state ADD COLUMN IF NOT EXISTS admin_state VARCHAR(20);")
            # --- FIM DA MODIFICAÇÃO (ALTER TABLE) ---

            # Índices para melhor performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pon_port_state_olt_fsp ON pon_port_state (olt_ip, fsp);")
            # ... (resto da função)
            
            # Tabela de Monitoramento de Recursos
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS resource_monitoring (
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
            cursor.execute("ALTER TABLE resource_monitoring ADD COLUMN IF NOT EXISTS board_name VARCHAR(50);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_monitoring_olt_slot_type_time ON resource_monitoring(olt_identifier, slot_id, resource_type, collection_time DESC);")
            logging.info("Tabela 'resource_monitoring' verificada/criada.")
            
            # Tabela de Histórico de Diagnósticos
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ont_diagnostics_history (
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
            logging.info("Tabela 'ont_diagnostics_history' verificada/criada.")
        
        conn.commit()
        logging.info("Todas as tabelas e colunas foram verificadas/criadas com sucesso.")
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
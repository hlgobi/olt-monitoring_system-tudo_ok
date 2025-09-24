# -*- coding: utf-8 -*-

# ==============================================================================
# MÓDULO DE CONEXÃO E GERENCIAMENTO DO BANCO DE DADOS
# ==============================================================================
# Este arquivo implementa as funcionalidades de conexão com o banco de dados PostgreSQL
# e criação/manutenção da estrutura de tabelas necessárias para a aplicação OLT
# Monitoring System.
#
# Inclui funções para:
# - Verificar a conexão com o banco de dados
# - Criar e atualizar todas as tabelas necessárias
# - Garantir a configuração adequada de fuso horário
# - Criar índices para otimizar consultas
# - Tratar erros de conexão e operações no banco

# ==============================================================================
# IMPORTAÇÕES DE MÓDULOS
# ==============================================================================
import psycopg2  # Adaptador PostgreSQL para Python
import logging  # Sistema de logging da aplicação
import time  # Funções de tempo para tratamento de retries
from config import DB_CONFIG  # Configurações de conexão com o banco de dados

# ==============================================================================
# FUNÇÕES DE GERENCIAMENTO DO BANCO DE DADOS
# ==============================================================================

def create_tables():
    """
    Cria ou atualiza todas as tabelas necessárias no banco de dados PostgreSQL.
    
    Esta função estabelece uma conexão com o banco de dados e verifica/cria todas
    as tabelas necessárias para o funcionamento da aplicação. Além disso, garante
    que as colunas estejam com os tipos de dados corretos e cria índices para
    otimizar o desempenho das consultas.
    
    A função também configura o fuso horário do banco de dados para 'America/Sao_Paulo'
    para garantir consistência nos registros de data/hora.
    
    Returns:
        bool: True se todas as operações foram concluídas com sucesso, False caso contrário
    """
    conn = None  # Inicializa a variável de conexão como None
    
    try:
        # Estabelece conexão com o banco de dados usando as configurações
        conn = psycopg2.connect(**DB_CONFIG)
        
        # Cria um cursor para executar comandos SQL
        with conn.cursor() as cursor:
            # Verifica e configura o fuso horário do banco de dados
            cursor.execute("SHOW timezone;")
            tz = cursor.fetchone()[0]
            logging.info(f"Fuso horário atual do banco: {tz}")
            
            # Define o fuso horário para America/Sao_Paulo
            cursor.execute("SET TIME ZONE 'America/Sao_Paulo';")
            logging.info("Fuso horário definido para America/Sao_Paulo")
            
            # ==================================================================
            # Tabela de Dados ONT (Optical Network Terminal)
            # ==================================================================
            # Armazena informações detalhadas sobre as ONTs conectadas ao sistema
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
                    collection_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    connection_code VARCHAR(50),
                    client_name VARCHAR(100)
                );
            """)
            logging.info("Tabela 'public.ont_data' verificada/criada.")
            
            # ==================================================================
            # Tabela de Dados de Tráfego PON
            # ==================================================================
            # Armazena informações de tráfego das interfaces PON
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.pon_traffic_data (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(50) NOT NULL,
                    fsp VARCHAR(20) NOT NULL,
                    collection_time TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
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
            
            # Índices para melhor performance na tabela pon_traffic_data
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pon_traffic_olt_fsp ON public.pon_traffic_data (olt_ip, fsp);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pon_traffic_time ON public.pon_traffic_data (collection_time);")
            
            # ==================================================================
            # Atualização da Estrutura da Tabela ONT
            # ==================================================================
            # Comandos para adicionar colunas que podem não existir na tabela ont_data
            alter_commands = [
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS olt_ip VARCHAR(15);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS previous_mac_address VARCHAR(18);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS fsp_changed BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS ont_id_changed BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS previous_fsp VARCHAR(20);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS previous_ont_id INTEGER;",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS olt_identifier VARCHAR(10);",
                "ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS ont_online_duration VARCHAR(100);",
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
            
            # Executa todos os comandos de alteração
            for command in alter_commands:
                cursor.execute(command)
            logging.info("Colunas da tabela 'public.ont_data' verificadas/adicionadas.")
            
            # Garante que a coluna collection_time use o tipo correto (TIMESTAMP WITH TIME ZONE)
            cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'ont_data' AND column_name = 'collection_time') THEN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'ont_data' AND column_name = 'collection_time' AND data_type = 'timestamp with time zone') THEN
                            ALTER TABLE public.ont_data ALTER COLUMN collection_time TYPE TIMESTAMP WITH TIME ZONE;
                            RAISE NOTICE 'Coluna collection_time alterada para TIMESTAMP WITH TIME ZONE';
                        END IF;
                    END IF;
                END $$;
            """)
            
            # ==================================================================
            # Índices para a Tabela ONT
            # ==================================================================
            # Cria índices para otimizar consultas frequentes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_sn ON public.ont_data(serial_number);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_fsp ON public.ont_data(fsp);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_mac ON public.ont_data(mac_address);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_time ON public.ont_data(collection_time);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_olt ON public.ont_data(olt_identifier);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_primaria ON public.ont_data(primaria);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_data_secundaria ON public.ont_data(secundaria);")
            
            # ==================================================================
            # Adição de Colunas para Detalhes da Versão da ONT
            # ==================================================================
            # Adiciona colunas para armazenar informações de versão e firmware
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS vendor_id VARCHAR(50);")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS ont_version VARCHAR(50);")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS product_id VARCHAR(50);")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS equipment_id VARCHAR(50);")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS main_software_version VARCHAR(100);")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS standby_software_version VARCHAR(100);")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS ont_product_description TEXT;")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS support_xml_version VARCHAR(50);")
            
            # ==================================================================
            # Adição de Colunas para Dados Ópticos da ONT
            # ==================================================================
            # Adiciona colunas para armazenar informações detalhadas do módulo óptico
            logging.info("Adicionando colunas para detalhes ópticos da ONT...")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS optical_module_type VARCHAR(50);")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS optical_module_subtype VARCHAR(50);")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS optical_encapsulation_type VARCHAR(50);")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS optical_vendor_name VARCHAR(50);")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS optical_vendor_pn VARCHAR(50);")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS optical_vendor_sn VARCHAR(50);")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS optical_date_code VARCHAR(20);")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS optical_olt_rx_ont_power_dbm FLOAT;")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS ont_voltage_v FLOAT;")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS ont_tx_bias_current_ma FLOAT;")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS optical_rx_power_alarm VARCHAR(50);")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS optical_tx_power_alarm VARCHAR(50);")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS optical_bias_current_alarm VARCHAR(50);")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS optical_temperature_alarm VARCHAR(50);")
            cursor.execute("ALTER TABLE public.ont_data ADD COLUMN IF NOT EXISTS optical_voltage_alarm VARCHAR(50);")
            
            # ==================================================================
            # Tabela de Status PON
            # ==================================================================
            # Armazena informações de status das interfaces PON
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.pon_status (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(15) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL,
                    collection_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    fsp VARCHAR(10) NOT NULL,
                    online_count INTEGER NOT NULL,
                    total_count INTEGER NOT NULL,
                    status VARCHAR(15) NOT NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pon_status_olt_fsp_time ON public.pon_status(olt_identifier, fsp, collection_time DESC);")
            logging.info("Tabela 'public.pon_status' verificada/criada.")
            
            # ==================================================================
            # Tabela de Monitoramento de Temperatura
            # ==================================================================
            # Armazena dados de temperatura dos slots das OLTs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.temperature_monitoring (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(15) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL,
                    collection_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    slot_id VARCHAR(10) NOT NULL,
                    board_name VARCHAR(50),
                    temperature_c FLOAT NOT NULL,
                    temperature_f FLOAT NOT NULL,
                    status VARCHAR(20) DEFAULT 'normal'
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_temp_monitoring_olt_slot_time ON public.temperature_monitoring(olt_identifier, slot_id, collection_time DESC);")
            logging.info("Tabela 'public.temperature_monitoring' verificada/criada.")
            
            # ==================================================================
            # Tabela de Estado da Porta PON
            # ==================================================================
            # Armazena informações detalhadas sobre o estado das portas PON
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.pon_port_state (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(50) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL,
                    fsp VARCHAR(20) NOT NULL,
                    collection_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    port_state VARCHAR(20),
                    last_down_cause VARCHAR(100),
                    last_up_time TIMESTAMP WITH TIME ZONE,
                    last_down_time TIMESTAMP WITH TIME ZONE,
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
            
            # Adiciona colunas que podem não existir na tabela pon_port_state
            cursor.execute("ALTER TABLE public.pon_port_state ADD COLUMN IF NOT EXISTS olt_identifier VARCHAR(10);")
            cursor.execute("ALTER TABLE public.pon_port_state ADD COLUMN IF NOT EXISTS left_guaranteed_bandwidth_kbps INTEGER;")
            cursor.execute("ALTER TABLE public.pon_port_state ADD COLUMN IF NOT EXISTS admin_state VARCHAR(20);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pon_port_state_olt_fsp ON public.pon_port_state (olt_ip, fsp);")
            
            # ==================================================================
            # Tabela de Monitoramento de Recursos
            # ==================================================================
            # Armazena dados de utilização de recursos (CPU, memória) das OLTs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.resource_monitoring (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(15) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL,
                    collection_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
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
            
            # ==================================================================
            # Tabela de Histórico de Diagnóstico de ONT
            # ==================================================================
            # Armazena o histórico de diagnósticos realizados nas ONTs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.ont_diagnostics_history (
                    id SERIAL PRIMARY KEY,
                    ont_serial_number VARCHAR(50) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL,
                    fsp VARCHAR(20),
                    ont_id_on_pon INT,
                    diag_section_id VARCHAR(50) NOT NULL,
                    diag_timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    raw_output TEXT,
                    parsed_data JSONB,
                    manufacturer VARCHAR(255) DEFAULT NULL,
                    model_name VARCHAR(100) DEFAULT NULL,
                    uptime VARCHAR(100) DEFAULT NULL,
                    firmware_version VARCHAR(100) DEFAULT NULL
                );
            """)
            logging.info("Tabela 'public.ont_diagnostics_history' verificada/criada.")
            
            # ==================================================================
            # Tabela de Estatísticas de Pacotes da ONT
            # ==================================================================
            # Armazena estatísticas de tráfego de pacotes das ONTs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.ont_statistics_packets (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(50) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL,
                    fsp VARCHAR(20) NOT NULL,
                    ont_id INTEGER NOT NULL,
                    collection_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
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
            
            # ==================================================================
            # Tabela de Estatísticas de Pacotes da PON
            # ==================================================================
            # Armazena estatísticas detalhadas de tráfego das interfaces PON
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.pon_statistics_packets (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(50) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL,
                    fsp VARCHAR(20) NOT NULL,
                    collection_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
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
            
            # ==================================================================
            # Tabela de Dados de Tráfego da ONT
            # ==================================================================
            # Armazena informações de tráfego (up/down) das ONTs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.ont_traffic_data (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(50) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL,
                    fsp VARCHAR(20) NOT NULL,
                    ont_id INTEGER NOT NULL,
                    collection_time TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    up_traffic_kbps INTEGER,
                    down_traffic_kbps INTEGER
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ont_traffic_fsp_ont_id_time ON public.ont_traffic_data(fsp, ont_id, collection_time DESC);")
            logging.info("Tabela 'public.ont_traffic_data' verificada/criada.")
            
            # ==================================================================
            # Tabela de Estatísticas de Porta Ethernet por ONT
            # ==================================================================
            # Armazena estatísticas das interfaces Ethernet das ONTs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ont_eth_port_statistics (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(50) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL,
                    fsp VARCHAR(20) NOT NULL,
                    ont_id INTEGER NOT NULL,
                    eth_port_id INTEGER NOT NULL,
                    collection_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
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
            
            # Garante que a coluna collection_time use o tipo correto na tabela ont_eth_port_statistics
            cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'ont_eth_port_statistics' AND column_name = 'collection_time') THEN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'ont_eth_port_statistics' AND column_name = 'collection_time' AND data_type = 'timestamp with time zone') THEN
                            ALTER TABLE public.ont_eth_port_statistics ALTER COLUMN collection_time TYPE TIMESTAMP WITH TIME ZONE;
                            RAISE NOTICE 'Coluna collection_time da tabela ont_eth_port_statistics alterada para TIMESTAMP WITH TIME ZONE';
                        END IF;
                    END IF;
                END $$;
            """)
            
            # ==================================================================
            # Tabela de Dados DDM de Uplink
            # ==================================================================
            # Armazena informações de monitoramento digital de diagnóstico dos uplinks
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.uplink_ddm_data (
                    id SERIAL PRIMARY KEY,
                    olt_ip VARCHAR(50) NOT NULL,
                    olt_identifier VARCHAR(10) NOT NULL,
                    collection_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    placa VARCHAR(50) NOT NULL,
                    slot INTEGER NOT NULL,
                    port INTEGER NOT NULL,
                    temperature_c FLOAT,
                    supply_voltage_v FLOAT,
                    tx_bias_current_ma FLOAT,
                    tx_power_dbm FLOAT,
                    rx_power_dbm FLOAT,
                    status VARCHAR(20) DEFAULT 'normal'
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_uplink_ddm_olt_slot_port_time ON public.uplink_ddm_data(olt_identifier, slot, port, collection_time DESC);")
            logging.info("Tabela 'public.uplink_ddm_data' verificada/criada.")
            
        # Confirma todas as alterações no banco de dados
        conn.commit()
        logging.info("Todas as tabelas e colunas foram verificadas/criadas com sucesso no esquema 'public'.")
        return True
        
    except Exception as e: 
        # Em caso de erro, registra no log e desfaz alterações
        logging.error(f"ERRO CRÍTICO: Falha ao criar tabelas: {str(e)}", exc_info=True) 
        if conn:
            conn.rollback()
        return False 
        
    finally: 
        # Garante que a conexão seja fechada, mesmo em caso de erro
        if conn: 
            conn.close()

def check_db_connection():
    """
    Verifica a conexão com o banco de dados PostgreSQL com lógica de nova tentativa.
    
    Esta função tenta estabelecer uma conexão com o banco de dados usando as
    configurações definidas em DB_CONFIG. Em caso de falha, realiza novas tentativas
    até um máximo definido por max_retries, com um intervalo entre as tentativas.
    
    Se a conexão for bem-sucedida, também configura o fuso horário da sessão para
    'America/Sao_Paulo' para garantir consistência nos registros de data/hora.
    
    Returns:
        bool: True se a conexão foi estabelecida com sucesso, False caso contrário
    """
    max_retries = 3  # Número máximo de tentativas de conexão
    
    # Loop de tentativas de conexão
    for attempt in range(max_retries):
        conn = None  # Inicializa a variável de conexão como None
        
        try:
            # Tenta estabelecer a conexão com o banco de dados
            conn = psycopg2.connect(**DB_CONFIG)
            
            # Se a conexão for bem-sucedida, configura o fuso horário
            with conn.cursor() as cursor:
                cursor.execute("SET TIME ZONE 'America/Sao_Paulo';")
                # Verifica se o fuso foi definido corretamente
                cursor.execute("SHOW timezone;")
                tz = cursor.fetchone()[0]
                logging.info(f"Fuso horário da sessão PostgreSQL: {tz}")
            
            # Se chegou aqui, a conexão foi bem-sucedida
            return True
            
        except Exception as e:
            # Registra o aviso sobre a falha na tentativa atual
            logging.warning(f"Tentativa {attempt+1}/{max_retries}: Conexão PostgreSQL falhou: {e}")
            
            # Se não for a última tentativa, aguarda antes de tentar novamente
            if attempt < max_retries - 1:
                time.sleep(2)  # Espera 2 segundos antes da próxima tentativa
            
        finally:
            # Garante que a conexão seja fechada, mesmo em caso de erro
            if conn is not None:
                conn.close()
    
    # Se todas as tentativas falharam, retorna False
    return False
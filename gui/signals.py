# gui/signals.py
from PyQt5.QtCore import QObject, pyqtSignal


class DatabaseSignals(QObject):
    """
    Sinais personalizados para comunicação com o banco de dados entre threads.
    Esses sinais permitem que threads de segundo plano atualizem a GUI com segurança.
    """
    data_updated = pyqtSignal()     # Sinal emitido quando os dados da ONT são atualizados.
    pon_status_updated = pyqtSignal()   # Sinal emitido quando o status da PON muda.
    temperature_updated = pyqtSignal()  # Sinal emitido quando os dados de temperatura são atualizados.
    temp_data_collected = pyqtSignal(list)  # Sinal para dados de temperatura (transporta uma lista).
    resource_data_collected = pyqtSignal(list)  # Sinal para dados de recursos (transporta uma lista).
    update_status = pyqtSignal(str, str, str)  # Sinal para atualizar status (Contador, tempo, status).

    pon_traffic_updated = pyqtSignal()
    pon_traffic_status_changed = pyqtSignal(str, str, str)  # olt_ip, fsp, status
    
    # Sinais para estado da porta PON
    pon_port_state_updated = pyqtSignal()
    pon_stats_packets_updated = pyqtSignal()
    ont_traffic_data_updated = pyqtSignal()
    ont_stats_packets_updated = pyqtSignal()
    ont_eth_stats_updated = pyqtSignal()

    # Sinal para Alarmes de Caixa Parada
    caixa_parada_alarms_updated = pyqtSignal(list)

    # Sinais para Diagnóstico de ONT
    ont_connection_status_changed = pyqtSignal(bool, str)  # (isConnected, message)
    ont_command_output_received = pyqtSignal(str, str, bool) # (section_id, output, is_error)
    ont_cycle_completed = pyqtSignal(str, int, float)
    
    # Sinal para atualização de dados DDM
    uplink_ddm_updated = pyqtSignal()  # Sinal emitido quando os dados DDM são atualizados
    
    # NOVO: Sinal para mensagens de log
    log_message = pyqtSignal(str)  # Sinal para enviar mensagens de log para a GUI

# Instância global de sinais
db_signals = DatabaseSignals()
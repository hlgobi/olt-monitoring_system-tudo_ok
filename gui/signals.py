# 12. olt_monitoring_system/gui/signals.py
# gui/signals.py
# Define sinais personalizados para comunicação entre threads e a GUI,
# permitindo que threads de segundo plano atualizem a GUI de forma segura.
# MODIFICADO: Corrigida a assinatura do sinal ont_cycle_completed.

from PyQt5.QtCore import QObject, pyqtSignal # Importa QObject e pyqtSignal do PyQt5.QtCore.

class DatabaseSignals(QObject): # Define a classe DatabaseSignals que herda de QObject.
    """
    Sinais personalizados para comunicação com o banco de dados entre threads.
    Esses sinais permitem que threads de segundo plano atualizem a GUI com segurança.
    """ # Docstring da classe.
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

    # Sinal para Alarmes de Caixa Parada
    caixa_parada_alarms_updated = pyqtSignal(list)

    # Sinais para Diagnóstico de ONT
    ont_connection_status_changed = pyqtSignal(bool, str)  # (isConnected, message)
    ont_command_output_received = pyqtSignal(str, str, bool) # (section_id, output, is_error)

    # --- INÍCIO DA MODIFICAÇÃO ---
    # O sinal agora carrega o IP (str), a contagem (int) e a duração (float).
    ont_cycle_completed = pyqtSignal(str, int, float)
    # --- FIM DA MODIFICAÇÃO ---

# Instância global de sinais
db_signals = DatabaseSignals()

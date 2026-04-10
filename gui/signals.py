# -*- coding: utf-8 -*-

# ==============================================================================
# ARQUIVO DE SINAIS PERSONALIZADOS PARA COMUNICAÇÃO ENTRE THREADS
# ==============================================================================
# Este arquivo define sinais personalizados do PyQt5 que são usados para comunicação
# segura entre threads (especialmente threads de segundo plano e a thread principal da GUI).
# 
# Em aplicações PyQt, a GUI deve ser atualizada apenas pela thread principal. Sinais
# permitem que threads de trabalho (como as que coletam dados de OLTs) enviem informações
# para a GUI de forma thread-safe, sem causar problemas de concorrência.

# ==============================================================================
# IMPORTAÇÕES DE MÓDULOS
# ==============================================================================
from PyQt5.QtCore import QObject, pyqtSignal  # QObject é a classe base para objetos PyQt, pyqtSignal cria sinais personalizados

# ==============================================================================
# CLASSE DE SINAIS DO BANCO DE DADOS
# ==============================================================================

class DatabaseSignals(QObject):
    """
    Classe que define todos os sinais personalizados usados na aplicação para comunicação
    entre threads de segundo plano e a interface gráfica (GUI).
    
    Estes sinais são emitidos por threads que realizam operações demoradas (como coleta de dados)
    e são conectados a slots (métodos) na GUI para atualizar a interface de forma segura.
    
    Herda de QObject para permitir o uso do sistema de sinais e slots do PyQt.
    """
    
    # --- Sinais para Atualização de Dados Gerais ---
    data_updated = pyqtSignal()
    """
    Sinal emitido quando os dados da ONT (Optical Network Terminal) são atualizados no banco de dados.
    Usado para notificar a GUI que deve atualizar a exibição dos dados das ONTs.
    """
    
    pon_status_updated = pyqtSignal()
    """
    Sinal emitido quando o status da PON (Passive Optical Network) muda.
    Notifica a GUI sobre alterações no estado das redes ópticas passivas.
    """
    
    temperature_updated = pyqtSignal()
    """
    Sinal emitido quando os dados de temperatura dos equipamentos são atualizados.
    Indica que novas medições de temperatura estão disponíveis para exibição.
    """
    
    # --- Sinais para Transporte de Dados Específicos ---
    temp_data_collected = pyqtSignal(list)
    """
    Sinal emitido quando uma nova coleta de dados de temperatura é concluída.
    Transporta uma lista com os dados de temperatura coletados.
    Argumentos:
        list: Lista contendo os dados de temperatura coletados.
    """
    
    resource_data_collected = pyqtSignal(list)
    """
    Sinal emitido quando uma nova coleta de dados de recursos (utilização) é concluída.
    Transporta uma lista com os dados de recursos coletados.
    Argumentos:
        list: Lista contendo os dados de recursos coletados.
    """
    
    update_status = pyqtSignal(str, str, str)
    """
    Sinal para atualizar o status geral da aplicação na barra de status da GUI.
    Transporta três strings: contador, tempo decorrido e status atual.
    Argumentos:
        str: Texto para o contador (ex: "ONTs: 42/100")
        str: Texto para o tempo (ex: "Tempo: 00:05:23")
        str: Texto para o status (ex: "Coletando dados...")
    """
    
    # --- Sinais para Tráfego da PON ---
    pon_traffic_updated = pyqtSignal()
    """
    Sinal emitido quando os dados de tráfego da PON são atualizados.
    Notifica a GUI que deve atualizar os gráficos ou tabelas de tráfego.
    """
    
    pon_traffic_status_changed = pyqtSignal(str, str, str)
    """
    Sinal emitido quando o status de tráfego de uma PON específica muda.
    Transporta o IP da OLT, o FSP (Frame Slot Port) e o novo status.
    Argumentos:
        str: Endereço IP da OLT
        str: Identificador FSP (Frame/Slot/Porta)
        str: Novo status do tráfego (ex: "Normal", "Congestionado")
    """
    
    # --- Sinais para Estado da Porta PON e Estatísticas ---
    pon_port_state_updated = pyqtSignal()
    """
    Sinal emitido quando o estado de uma porta PON é atualizado.
    Notifica a GUI sobre mudanças no estado operacional das portas.
    """
    
    pon_stats_packets_updated = pyqtSignal()
    """
    Sinal emitido quando as estatísticas de pacotes da PON são atualizadas.
    Indica que novos dados de contagem de pacotes estão disponíveis.
    """
    
    # --- Sinais para Dados de Tráfego e Estatísticas da ONT ---
    ont_traffic_data_updated = pyqtSignal()
    """
    Sinal emitido quando os dados de tráfego de uma ONT são atualizados.
    Notifica a GUI sobre mudanças no tráfego de terminais ópticos.
    """
    
    ont_stats_packets_updated = pyqtSignal()
    """
    Sinal emitido quando as estatísticas de pacotes de uma ONT são atualizadas.
    Indica que novos dados de contagem de pacotes da ONT estão disponíveis.
    """
    
    ont_eth_stats_updated = pyqtSignal()
    """
    Sinal emitido quando as estatísticas de interface Ethernet da ONT são atualizadas.
    Notifica sobre mudanças nas métricas de rede Ethernet das ONTs.
    """
    
    # --- Sinais para Alarmes de Caixa Parada ---
    caixa_parada_alarms_updated = pyqtSignal(list)
    """
    Sinal emitido quando há atualizações nos alarmes de caixas paradas.
    Transporta uma lista com os alarmes ativos ou recentes.
    Argumentos:
        list: Lista contendo os alarmes de caixas paradas.
    """
    
    # --- Sinais para Diagnóstico de ONT ---
    ont_connection_status_changed = pyqtSignal(bool, str)
    """
    Sinal emitido quando o status de conexão com uma ONT muda durante diagnóstico.
    Transporta um booleano indicando se está conectado e uma mensagem descritiva.
    Argumentos:
        bool: True se conectado, False caso contrário
        str: Mensagem descritiva do status da conexão
    """
    
    ont_command_output_received = pyqtSignal(str, str, bool)
    """
    Sinal emitido quando a saída de um comando de diagnóstico de ONT é recebida.
    Transporta o ID da seção, a saída do comando e um flag de erro.
    Argumentos:
        str: ID da seção de diagnóstico (ex: "ont_info")
        str: Saída do comando executado
        bool: True se houve erro, False caso contrário
    """
    
    ont_cycle_completed = pyqtSignal(str, int, float)
    """
    Sinal emitido quando um ciclo completo de diagnóstico de ONT é concluído.
    Transporta o IP da OLT, o número de ONTs diagnosticadas e o tempo decorrido.
    Argumentos:
        str: Endereço IP da OLT
        int: Número de ONTs diagnosticadas no ciclo
        float: Tempo total do ciclo em segundos
    """
    
    # --- Sinais para Dados DDM (Digital Diagnostics Monitoring) ---
    uplink_ddm_updated = pyqtSignal()
    """
    Sinal emitido quando os dados DDM dos uplinks são atualizados.
    Notifica a GUI que deve atualizar as informações de diagnóstico dos uplinks.
    """
    
    # --- Sinais para Sistema de Logs ---
    log_message = pyqtSignal(str)
    """
    Sinal para enviar mensagens de log para a GUI.
    Permite que threads de segundo plano enviem mensagens de log para serem exibidas
    na interface gráfica de forma segura e sincronizada.
    Argumentos:
        str: Mensagem de log formatada para exibição
    """

# ==============================================================================
# INSTÂNCIA GLOBAL DE SINAIS
# ==============================================================================
# Instância global da classe DatabaseSignals que será usada em toda a aplicação.
# Esta instância permite que qualquer parte do código possa emitir ou conectar-se
# aos sinais definidos, facilitando a comunicação entre componentes.
db_signals = DatabaseSignals()
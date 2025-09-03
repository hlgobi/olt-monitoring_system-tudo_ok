
import json
import psycopg2
import sys
import csv
import threading
from datetime import datetime, timedelta
import logging
import re
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QTableWidget,
                             QTableWidgetItem, QLabel, QLineEdit,
                             QMessageBox, QComboBox, QDialog, QFormLayout,
                             QInputDialog, QGroupBox, QTabWidget, QTextEdit, QSplitter,
                             QFileDialog, QScrollArea, QSizePolicy, QGridLayout,
                             QListWidget, QAbstractItemView, QCheckBox)  # NOVO: QCheckBox
from PyQt5.QtCore import (QObject, pyqtSignal, QTimer, Qt, QEvent, QMetaObject, 
                          pyqtSlot, Q_ARG, QPropertyAnimation, pyqtProperty)
from PyQt5 import QtGui
from PyQt5.QtGui import QColor, QFont, QIcon, QPalette, QPixmap
import pyqtgraph as pg
import queue
from config import DB_CONFIG, get_olt_configs
from gui.dialogs import CleanupDialog, OntDiagnosticsHistoryDialog
# --- INÍCIO DA CORREÇÃO ---
from olt.processing import (run_data_collection, process_ont_eth_worker,
                            run_temp_monitoring, run_resource_monitoring,
                            get_active_gpon_slots, parse_board_info as olt_parse_board_info,
                            get_slot_cpu_usage, get_slot_memory_usage, get_resource_status)
# --- FIM DA CORREÇÃO ---
# Em gui/main_window.py, verifique a importação
from gui.signals import db_signals
from db.connection import create_tables, check_db_connection
from db.operations import (save_ont_data, save_pon_status, save_temp_data,
                           save_resource_data, save_ont_diagnostic_data)
from olt.communication import connect_to_olt, send_command as send_olt_command
from utils.helpers import (clean_response, parse_ont_device_info, parse_ont_optic_status, 
                           parse_ont_wan_status, parse_lan_wifi_devices, parse_wifi_neighbors, 
                           parse_wifi_config, parse_connectivity_tests, parse_voip_status, parse_ip_routes)


class OLTDatabaseGUI(QMainWindow):
    log_message_received = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        
        self.olt_configs = get_olt_configs()
        self.collection_threads = {}
        # --- INÍCIO DA MODIFICAÇÃO ---
        # Inicializa os dicionários para as novas threads e filas
        self.eth_collection_threads = {}
        self.eth_task_queues = {}
        # --- FIM DA MODIFICAÇÃO ---
        self.olt_ip = None
        self.username = None
        self.password = None

        self.last_update_time = None
        self.collection_running = False
        self.temp_monitoring_running = False
        self.resource_monitoring_running = False
        self.execution_count = 0
        self.last_execution_time = None
        self.last_insert_count = 0
        self.resource_execution_count = 0
        self.olt_filters_to_update = []
        self.ont_cycle_count = 0
        self.access_ont_btn = None
        self.disconnect_ont_btn = None
        self.diag_ont_tab = None
        self.current_diagnosed_ont_info = {}
        self.diag_ont_status_label = None
        self.diag_widgets = {}
        self.caixa_stats_update_timer = None 
        self.long_offline_update_timer = None # Timer para a nova aba
        self.long_offline_tab = None # Referência para a nova aba
        self.collection_thread = None
        self.ont_connection_thread = None
        self.ont_command_thread = None
        self.active_ont_olt_client = None
        self.active_ont_olt_shell = None
        self.is_ont_session_active = None
        self.olt_checkboxes = {}  # Dicionário para armazenar os checkboxes das OLTs

        # NOVO: Widget para exibição de logs
        self.log_text_edit = None
        
        self.common_ont_credentials = [
            ('root', '@gigabgtR'), ('admin', 'admin'),
            ('telecomadmin', 'admintelecom'), ('user', 'user'),
            ('admin', 'password'), ('root', 'root'),
        ]
        self.common_su_passwords = ['@gigabgtR', 'admin', 'root', 'admintelecom', 'password']
        self.ont_login_prompt_user_re = re.compile(r"Login:", re.I)
        self.ont_login_prompt_pass_re = re.compile(r"Password:", re.I)
        self.ont_shell_prompt_re = re.compile(r"(WAP>)\s*$")
        self.ont_root_prompt_re = re.compile(r"(SU_WAP>)\s*$")
        self.olt_telnet_param_prompt_re = re.compile(r"\{\\s*<cr>.*\}\\s*:\\s*$")
        self.olt_diagnose_prompt_re = re.compile(r"\(diagnose\)\\s*[>#]\\s*$")
        self.olt_standard_prompt_re = re.compile(r"[>#]\\s*$")
        self.diag_sections_config = [
            {"title": "1. Informações Básicas da ONT", "id": "device_info", "commands": "display deviceInfo\\ndisplay version"},
            {"title": "2. Status da Conexão Óptica", "id": "optic_status", "commands": "display optic\\ndisplay board-temperatures"},
            {"title": "3. Status da WAN/PPPoE", "id": "wan_status", "commands": "display pppoe client all\\ndisplay wan layer all"},
            {"title": "4. Dispositivos Conectados (LAN/Wi-Fi)", "id": "lan_wifi_devices", "commands": "display dhcp server user all\\ndisplay wifi associate"},
            {"title": "5. Redes Wi-Fi Vizinhas", "id": "wifi_neighbors", "commands": "display wifi neighbor"},
            {"title": "6. Configurações Wi-Fi da ONT", "id": "wifi_config", "commands": "display wifi information\\ndisplay wifi radio"},
            {"title": "7. Telefonia (VoIP)", "id": "voip_status", "commands": "display voice hs status\\ndisplay voip info"},
            {"title": "8. Rotas e Vizinhos IP", "id": "ip_routes", "commands": "display ip route\\ndisplay ip neigh"},
            {"title": "9. Testes de Conectividade", "id": "connectivity_tests", "commands": "(Executado por worker dedicado)"},
            {"title": "10. Logs e Eventos", "id": "logs_events", "commands": "display log info"},
            {"title": "11. TR-069 (Gestão Remota)", "id": "tr069_status", "commands": "display tr069 info"},
        ]

        self.setWindowTitle("Sistema de Monitoramento OLT - Multi-OLT")
        self.setGeometry(100, 100, 1600, 900)

        self.connect_to_db()
        self.init_ui()
        self.load_olt_list_to_filters()
        self.load_data()
        self.setup_timers()
        self.init_eth_workers()

        db_signals.data_updated.connect(self.safe_update)
        db_signals.pon_status_updated.connect(self.update_pon_status_display)
        db_signals.temperature_updated.connect(self.update_temperature_display)
        db_signals.temp_data_collected.connect(self.update_temp_display_with_data)
        db_signals.resource_data_collected.connect(self.update_resource_display_with_data)
        db_signals.update_status.connect(self.update_status_display)
        db_signals.ont_connection_status_changed.connect(self._handle_ont_connection_status_changed)
        db_signals.ont_command_output_received.connect(self._handle_ont_command_output_received)
        db_signals.ont_cycle_completed.connect(self.update_ont_cycle_stats)
        db_signals.pon_port_state_updated.connect(self.update_pon_port_state_display)
        db_signals.pon_stats_packets_updated.connect(self.update_pon_stats_display)
        db_signals.ont_traffic_data_updated.connect(self.update_ont_traffic_display)
        db_signals.pon_port_state_updated.connect(self.update_pon_port_state_display)
        db_signals.ont_eth_stats_updated.connect(self.update_ont_eth_display) # Conecta o novo sinal
        db_signals.uplink_ddm_updated.connect(self.load_uplink_ddm_data)
        # Conectar o sinal para atualizar a aba DDM
        try:
            db_signals.data_updated.connect(self.load_uplink_ddm_data)
            logging.info("Sinal data_updated conectado ao método load_uplink_ddm_data com sucesso.")
        except Exception as e:
            logging.error(f"Erro ao conectar sinal data_updated: {e}")
        self.log_message_received.connect(self.log_to_gui)
        
        # NOVO: Conectar o sinal global de logs
        db_signals.log_message.connect(self.log_to_gui)

# Em gui/main_window.py, modifique o método init_eth_workers:

    def init_eth_workers(self):
        """Inicializa as filas e threads para coleta Ethernet."""
        self.log_to_gui("Inicializando worker Ethernet global...")
        
        # Cria uma única fila global para todas as OLTs
        self.eth_task_queue = queue.Queue()
        
        # Cria e inicia um único worker global
        self.eth_collection_thread = threading.Thread(
            target=process_ont_eth_worker,
            args=(self.eth_task_queue, self, self.log_message_received.emit),
            daemon=True,
            name="GlobalEthWorker"
        )
        self.eth_collection_thread.start()
        
        self.log_to_gui("Worker ETH global inicializado")

    def connect_to_db(self):
        """Estabelece conexão com o banco de dados PostgreSQL."""
        try:
            self.conn = psycopg2.connect(**DB_CONFIG)
            self.cursor = self.conn.cursor()
            
            # Verify schema before proceeding
            if not self.verify_database_schema():
                raise Exception("Schema do banco de dados está incompleto")
            
            # Verify if connection_code column exists
            self.cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'ont_data' AND column_name = 'connection_code'
            """)
            if not self.cursor.fetchone():
                logging.info("Coluna 'connection_code' não encontrada. Adicionando...")
                self.cursor.execute("ALTER TABLE ont_data ADD COLUMN connection_code VARCHAR(50)")
                self.conn.commit()
                logging.info("Coluna 'connection_code' adicionada com sucesso.")
            
            logging.info("Conexão com o banco de dados estabelecida com sucesso.")
        except Exception as e:
            QMessageBox.critical(self, "Erro Crítico de Conexão com Banco de Dados",
                                f"Não foi possível conectar ou inicializar o banco de dados:\n{str(e)}\n\nA aplicação será encerrada.")
            sys.exit(1)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.tab_widget = QTabWidget()
        central_widget.setLayout(QVBoxLayout())
        central_widget.layout().addWidget(self.tab_widget)
    
        self.logs_tab = QWidget()
        self.tab_widget.addTab(self.logs_tab, "Logs")
        self.setup_logs_tab()

        self.data_tab = QWidget()
        self.tab_widget.addTab(self.data_tab, "Dados ONT")
        self.setup_data_tab()

        self.temp_tab = QWidget()
        self.tab_widget.addTab(self.temp_tab, "Temperatura")
        self.setup_temp_tab()

        self.resource_tab = QWidget()
        self.tab_widget.addTab(self.resource_tab, "Recursos")
        self.setup_resource_tab()

        self.caixa_stats_tab = QWidget()
        self.tab_widget.addTab(self.caixa_stats_tab, "Estatísticas por Caixa")
        self.setup_caixa_stats_tab()
        
        self.long_offline_tab = QWidget()
        self.tab_widget.addTab(self.long_offline_tab, "Longo Tempo Offline")
        self.setup_long_offline_tab()

        self.diag_ont_tab = QWidget()
        self.tab_widget.addTab(self.diag_ont_tab, "Diagnóstico ONT")
        self.setup_diag_ont_tab()

        # Após a criação das outras abas
        self.pon_state_tab = QWidget()
        self.tab_widget.addTab(self.pon_state_tab, "Estado PON")
        self.setup_pon_state_tab()
    
        self.pon_traffic_tab = QWidget()
        self.tab_widget.addTab(self.pon_traffic_tab, "Dados PON")
        self.setup_pon_traffic_tab()

        # --- INÍCIO DA MODIFICAÇÃO ---
        self.pon_stats_tab = QWidget()
        self.tab_widget.addTab(self.pon_stats_tab, "Estatísticas da PON")
        self.setup_pon_stats_tab()
        # --- FIM DA MODIFICAÇÃO ---

        # --- INÍCIO DA MODIFICAÇÃO ---
        self.ont_traffic_tab = QWidget()
        self.tab_widget.addTab(self.ont_traffic_tab, "Dados ONT por PON")
        self.setup_ont_traffic_tab()
        # --- FIM DA MODIFICAÇÃO ---

        # --- INÍCIO DA MODIFICAÇÃO ---
        self.ont_stats_tab = QWidget()
        self.tab_widget.addTab(self.ont_stats_tab, "Estatísticas de ONT")
        self.setup_ont_stats_tab()
        # --- FIM DA MODIFICAÇÃO ---

        # --- INÍCIO DA MODIFICAÇÃO ---
        # Adicione a criação da nova aba
        self.ont_eth_tab = QWidget()
        self.tab_widget.addTab(self.ont_eth_tab, "ONT Ethernet")
        self.setup_ont_eth_tab()
        # --- FIM DA MODIFICAÇÃO ---

        # No método init_ui, após a criação das outras abas
        self.uplink_ddm_tab = QWidget()
        self.tab_widget.addTab(self.uplink_ddm_tab, "Uplink DDM")
        self.setup_uplink_ddm_tab()

        self.caixa_stats_update_timer = QTimer(self)
        self.caixa_stats_update_timer.setInterval(30000)
        self.caixa_stats_update_timer.timeout.connect(self.load_caixa_stats_data)

        self.long_offline_update_timer = QTimer(self)
        self.long_offline_update_timer.setInterval(60000)
        self.long_offline_update_timer.timeout.connect(self.load_long_offline_data)

        self.tab_widget.currentChanged.connect(self.handle_tab_change)

    def handle_tab_change(self, index):
        """Manipula eventos de mudança de aba, controlando timers e sessões."""
        current_tab = self.tab_widget.widget(index)
        
        # No método handle_tab_change, adicione ou modifique este trecho:

        if current_tab == self.ont_traffic_tab:
            logging.info("Aba 'Dados ONT por PON' ativada. Iniciando timer.")
            # Carrega as OLTs disponíveis no filtro
            self.load_ont_traffic_olt_list()
            # Carrega os dados imediatamente
            QTimer.singleShot(100, self.load_ont_traffic_data)
            self.ont_traffic_timer.start()
        else:
            if hasattr(self, 'ont_traffic_timer') and self.ont_traffic_timer.isActive():
                logging.info("Saindo da aba de tráfego ONT. Parando timer.")
                self.ont_traffic_timer.stop()
        
        # --- NOVA LÓGICA PARA A NOVA ABA ---
        # Lógica para a aba de Longo Tempo Offline
        if current_tab == self.long_offline_tab:
            QTimer.singleShot(100, self.load_long_offline_data)
            logging.info("Aba 'Longo Tempo Offline' ativada. Iniciando timer.")
            self.load_long_offline_data()
            self.long_offline_update_timer.start()
        else:
            if self.long_offline_update_timer and self.long_offline_update_timer.isActive():
                logging.info("Saindo da aba de longa inatividade. Parando timer.")
                self.long_offline_update_timer.stop()
    

        # --- INÍCIO DA MODIFICAÇÃO ---
        # Lógica para a aba de Estado PON
        if current_tab == self.pon_state_tab:
            logging.info("Aba 'Estado PON' ativada. Iniciando timer.")
            QTimer.singleShot(100, self.load_pon_state_data) # Carrega imediatamente
            self.pon_state_timer.start()
        else:
            if hasattr(self, 'pon_state_timer') and self.pon_state_timer.isActive():
                logging.info("Saindo da aba de estado PON. Parando timer.")
                self.pon_state_timer.stop()
        # --- FIM DA MODIFICAÇÃO ---

        # Lógica para a aba de Diagnóstico ONT
        if self.is_ont_session_active and current_tab != self.diag_ont_tab:
            logging.info("Saindo da aba de diagnóstico com sessão ONT ativa. Desconectando...")
            self.disconnect_from_ont()

        # Lógica para a aba de Dados PON
        if current_tab == self.pon_traffic_tab:
            logging.info("Aba 'Dados PON' ativada. Iniciando timer.")
            self.load_pon_traffic_data()
            self.pon_traffic_timer.start()
        else:
            if self.pon_traffic_timer and self.pon_traffic_timer.isActive():
                logging.info("Saindo da aba de dados PON. Parando timer.")
                self.pon_traffic_timer.stop()

        # --- INÍCIO DA MODIFICAÇÃO ---
        if current_tab == self.pon_stats_tab:
            logging.info("Aba 'Estatísticas da PON' ativada. Iniciando timer.")
            self.load_pon_stats_data()
            self.pon_stats_timer.start()
        else:
            if hasattr(self, 'pon_stats_timer') and self.pon_stats_timer.isActive():
                logging.info("Saindo da aba de estatísticas PON. Parando timer.")
                self.pon_stats_timer.stop()
        # --- FIM DA MODIFICAÇÃO ---

        # --- INÍCIO DA MODIFICAÇÃO ---
        if current_tab == self.ont_stats_tab:
            logging.info("Aba 'Estatísticas de ONT' ativada. Iniciando timer.")
            self.load_ont_stats_data()
            if hasattr(self, 'ont_stats_timer'):
                self.ont_stats_timer.start()
        else:
            if hasattr(self, 'ont_stats_timer') and self.ont_stats_timer.isActive():
                logging.info("Saindo da aba de estatísticas de ONT. Parando timer.")
                self.ont_stats_timer.stop()
        # --- FIM DA MODIFICAÇÃO ---

        # Em handle_tab_change, adicione esta parte
        if current_tab == self.ont_eth_tab:
            logging.info("Aba 'ONT Ethernet' ativada. Iniciando timer.")
            # Carrega as OLTs disponíveis no filtro
            self.load_ont_eth_olt_list()
            # Carrega os dados imediatamente
            QTimer.singleShot(100, self.load_ont_eth_data)
            self.ont_eth_timer.start()
        else:
            if hasattr(self, 'ont_eth_timer') and self.ont_eth_timer.isActive():
                logging.info("Saindo da aba de Ethernet ONT. Parando timer.")
                self.ont_eth_timer.stop()

        # Lógica para a aba de Uplink DDM
        # Em handle_tab_change, na parte da aba Uplink DDM
        if current_tab == self.uplink_ddm_tab:
            logging.info("Aba 'Uplink DDM' ativada. Iniciando timer.")
            QTimer.singleShot(100, self.load_uplink_ddm_data)
            self.load_uplink_ddm_data()
            self.uplink_ddm_timer.start()
        else:
            if hasattr(self, 'uplink_ddm_timer') and self.uplink_ddm_timer.isActive():
                logging.info("Saindo da aba de DDM. Parando timer.")
                self.uplink_ddm_timer.stop()


    def setup_long_offline_tab(self):
        """Configura a interface da aba 'Longo Tempo Offline'."""
        layout = QVBoxLayout(self.long_offline_tab)

        # -- Painel de Controle (Filtro e Ações) --
        control_panel = QWidget()
        control_layout = QHBoxLayout(control_panel)

        self.long_offline_olt_filter_label = QLabel("Filtrar por OLT:")
        self.long_offline_olt_filter = QComboBox()
        if self.long_offline_olt_filter not in self.olt_filters_to_update:
            self.olt_filters_to_update.append(self.long_offline_olt_filter)
        
        self.long_offline_olt_filter.currentTextChanged.connect(self.load_long_offline_data)

        export_btn = QPushButton("Exportar CSV")
        export_btn.clicked.connect(self.export_long_offline_to_csv)

        control_layout.addWidget(self.long_offline_olt_filter_label)
        control_layout.addWidget(self.long_offline_olt_filter)
        control_layout.addStretch()
        control_layout.addWidget(export_btn)
        layout.addWidget(control_panel)

        # -- Tabela de ONTs com Longa Inatividade --
        self.long_offline_onts_table = QTableWidget()
        # --- CORREÇÃO: Aumentado para 7 colunas ---
        self.long_offline_onts_table.setColumnCount(7)
        # --- CORREÇÃO: Adicionada a coluna "ONT ID" ---
        self.long_offline_onts_table.setHorizontalHeaderLabels(["OLT", "F/S/P", "ONT ID", "S/N", "CLIENTE", "Última Vez Online", "Dias Offline"])
        self.long_offline_onts_table.setSortingEnabled(True)
        self.long_offline_onts_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.long_offline_onts_table)

    def update_ddm_status(self, message, is_error=False):
        """Atualiza o label de status na aba DDM"""
        if hasattr(self, 'ddm_status_label'):
            self.ddm_status_label.setText(f"Status: {message}")
            if is_error:
                self.ddm_status_label.setStyleSheet("color: red; font-weight: bold;")
            else:
                self.ddm_status_label.setStyleSheet("color: green; font-weight: bold;")


    def check_ddm_table(self):
        """Verifica se a tabela uplink_ddm_data existe e contém dados"""
        try:
            if not self.conn or self.conn.closed:
                logging.warning("Conexão com o banco fechada, tentando reconectar...")
                self.connect_to_db()
                if not self.conn or self.conn.closed:
                    raise Exception("Não foi possível estabelecer conexão com o banco de dados")
            
            cursor = self.conn.cursor()
            
            # Verifica se a tabela existe
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'uplink_ddm_data'
                )
            """)
            table_exists = cursor.fetchone()[0]
            
            if not table_exists:
                logging.error("A tabela uplink_ddm_data não existe no banco de dados!")
                return False
            
            # Verifica quantos registros existem
            cursor.execute("SELECT COUNT(*) FROM uplink_ddm_data")
            total_count = cursor.fetchone()[0]
            
            logging.info(f"Tabela uplink_ddm_data existe com {total_count} registros.")
            
            if total_count == 0:
                return False
            
            # Mostra alguns dados de exemplo
            cursor.execute("SELECT * FROM uplink_ddm_data LIMIT 1")
            sample_data = cursor.fetchone()
            logging.info(f"Exemplo de dados na tabela: {sample_data}")
            
            return True
            
        except Exception as e:
            logging.error(f"Erro ao verificar tabela DDM: {e}", exc_info=True)
            return False

    def setup_logs_tab(self):
        """Configura a aba de logs."""
        layout = QVBoxLayout(self.logs_tab)
        
        # Criar widget para exibição de logs
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setReadOnly(True)
        self.log_text_edit.setFont(QtGui.QFont("Courier New", 9))
        
        # Adicionar botões de controle
        control_layout = QHBoxLayout()
        
        clear_btn = QPushButton("Limpar Logs")
        clear_btn.clicked.connect(self.clear_logs)
        
        save_btn = QPushButton("Salvar Logs")
        save_btn.clicked.connect(self.save_logs)
        
        auto_scroll_cb = QCheckBox("Rolagem Automática")
        auto_scroll_cb.setChecked(True)
        auto_scroll_cb.stateChanged.connect(self.toggle_auto_scroll)
        self.auto_scroll = True
        
        control_layout.addWidget(clear_btn)
        control_layout.addWidget(save_btn)
        control_layout.addWidget(auto_scroll_cb)
        control_layout.addStretch()
        
        layout.addLayout(control_layout)
        layout.addWidget(self.log_text_edit)
        
        # Adicionar logs iniciais se houver
        if hasattr(self, 'initial_logs'):
            for log_msg in self.initial_logs:
                self.log_text_edit.append(log_msg)
    
    def log_to_gui(self, message):
        """Adiciona uma mensagem de log ao widget de logs."""
        if self.log_text_edit:
            self.log_text_edit.append(message)
            
            # Rolar automaticamente para o final se ativado
            if self.auto_scroll:
                scrollbar = self.log_text_edit.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
    
    def clear_logs(self):
        """Limpa o conteúdo do widget de logs."""
        if self.log_text_edit:
            self.log_text_edit.clear()
    
    def save_logs(self):
        """Salva o conteúdo dos logs em um arquivo."""
        if not self.log_text_edit:
            return
            
        filename, _ = QFileDialog.getSaveFileName(
            self, 
            "Salvar Logs", 
            f"olt_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Arquivos de Texto (*.txt);;Todos os Arquivos (*)"
        )
        
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.log_text_edit.toPlainText())
                QMessageBox.information(self, "Sucesso", f"Logs salvos em:\n{filename}")
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Não foi possível salvar os logs:\n{str(e)}")
    
    def toggle_auto_scroll(self, state):
        """Ativa/desativa a rolagem automática dos logs."""
        self.auto_scroll = (state == Qt.Checked)
    

    def setup_diag_ont_tab(self):
        """Configura a interface da aba 'Diagnóstico ONT'."""
        main_layout = QVBoxLayout(self.diag_ont_tab)

        status_control_panel = QWidget()
        status_control_layout = QHBoxLayout()
        status_control_panel.setLayout(status_control_layout)

        self.diag_ont_status_label = QLabel("Nenhuma ONT selecionada para diagnóstico.")
        self.diag_ont_status_label.setStyleSheet("font-weight: bold; padding: 5px; background-color: lightgray; border-radius: 3px;")
        status_control_layout.addWidget(self.diag_ont_status_label, 1)

        self.diag_history_btn = QPushButton("Histórico Diagnósticos")
        self.diag_history_btn.clicked.connect(self.show_ont_diagnostics_history)
        self.diag_history_btn.setEnabled(False)
        status_control_layout.addWidget(self.diag_history_btn)

        self.disconnect_ont_btn = QPushButton("Desconectar da ONT")
        self.disconnect_ont_btn.clicked.connect(self.disconnect_from_ont)
        self.disconnect_ont_btn.setEnabled(False)
        self.disconnect_ont_btn.setStyleSheet("background-color: #f44336; color: white;")
        status_control_layout.addWidget(self.disconnect_ont_btn)

        main_layout.addWidget(status_control_panel)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        main_layout.addWidget(scroll_area)

        scroll_content_widget = QWidget()
        scroll_area.setWidget(scroll_content_widget)
        sections_layout = QVBoxLayout(scroll_content_widget)

        self.diag_widgets.clear()

        for section_config in self.diag_sections_config:
            group_box = QGroupBox(section_config["title"])
            group_layout = QVBoxLayout(group_box)

            control_layout = QHBoxLayout()
            load_button = QPushButton(f"Carregar {section_config['id'].replace('_', ' ').title()}")
            load_button.setProperty("section_id", section_config["id"])
            load_button.clicked.connect(self.handle_load_diag_data)
            load_button.setEnabled(False)

            control_layout.addWidget(load_button)
            control_layout.addStretch()
            group_layout.addLayout(control_layout)

            commands_display_text = section_config['commands'].replace('\n', ', ')
            commands_label = QLabel(f"<i>Comandos: {commands_display_text}</i>")
            commands_label.setWordWrap(True)
            group_layout.addWidget(commands_label)

            output_area = QTextEdit()
            output_area.setReadOnly(True)
            output_area.setPlaceholderText("Dados da ONT aparecerão aqui após carregar...")
            output_area.setMinimumHeight(100)
            output_area.setFont(QtGui.QFont("Courier New", 9))
            group_layout.addWidget(output_area)

            sections_layout.addWidget(group_box)

            self.diag_widgets[section_config["id"]] = {
                "button": load_button,
                "output_area": output_area,
                "group_box": group_box,
                "commands": section_config["commands"]
            }
        sections_layout.addStretch()

    @pyqtSlot(bool, str)
    def _handle_ont_connection_status_changed(self, is_connected, message):
        self.is_ont_session_active = is_connected
        if self.diag_ont_status_label:
            self.diag_ont_status_label.setText(message)
            if is_connected:
                self.diag_ont_status_label.setStyleSheet("font-weight: bold; padding: 5px; background-color: lightgreen; border-radius: 3px;")
                if self.disconnect_ont_btn: self.disconnect_ont_btn.setEnabled(True)
                if self.diag_history_btn: self.diag_history_btn.setEnabled(True)
                if self.access_ont_btn: self.access_ont_btn.setEnabled(False)
            else:
                self.diag_ont_status_label.setStyleSheet("font-weight: bold; padding: 5px; background-color: #ffcdd2; border-radius: 3px;")
                if self.disconnect_ont_btn: self.disconnect_ont_btn.setEnabled(False)
                if self.diag_history_btn: self.diag_history_btn.setEnabled(False)
                if self.access_ont_btn: self.access_ont_btn.setEnabled(bool(self.table.selectedItems()))

        for section_id in self.diag_widgets:
            button = self.diag_widgets[section_id].get("button")
            output_area = self.diag_widgets[section_id].get("output_area")
            if button: button.setEnabled(is_connected)
            if not is_connected and output_area:
                output_area.setPlaceholderText("Conecte-se a uma ONT para carregar dados.")
                output_area.clear()

    @pyqtSlot(str, str, bool)
    def _handle_ont_command_output_received(self, section_id, raw_output, is_error):
        """
        Recebe a saída, faz o parsing apropriado, salva no BD e atualiza a GUI.
        """
        logging.debug(f"[_handle_ont_command_output_received] Recebido sinal para seção: {section_id}")
        if section_id not in self.diag_widgets:
            logging.error(f"Seção de diagnóstico '{section_id}' não encontrada nos widgets.")
            return

        widget_config = self.diag_widgets[section_id]
        output_to_display = raw_output
        parsed_data_dict = {}

        if is_error:
            logging.error(f"Recebido erro da thread worker para a seção {section_id}: {raw_output}")
        else:
            cleaned_output = clean_response(raw_output)
            
            if section_id == "device_info":
                output_to_display, parsed_data_dict = parse_ont_device_info(cleaned_output)
            elif section_id == "optic_status":
                output_to_display, parsed_data_dict = parse_ont_optic_status(cleaned_output)
            elif section_id == "wan_status":
                output_to_display, parsed_data_dict = parse_ont_wan_status(cleaned_output)
            elif section_id == "wifi_neighbors":
                output_to_display, parsed_data_dict = parse_wifi_neighbors(cleaned_output)
            elif section_id == "wifi_config":
                output_to_display, parsed_data_dict = parse_wifi_config(cleaned_output)
            elif section_id == "voip_status":
                output_to_display, parsed_data_dict = parse_voip_status(raw_output)
            elif section_id == "ip_routes":
                output_to_display, parsed_data_dict = parse_ip_routes(raw_output)
            elif section_id == "connectivity_tests":
                output_to_display, parsed_data_dict = parse_connectivity_tests(raw_output)
            elif section_id == "lan_wifi_devices":
                output_to_display = raw_output
                parsed_data_dict = {"report_data": raw_output}
            else:
                output_to_display = cleaned_output

            if parsed_data_dict:
                ont_info = self.current_diagnosed_ont_info
                ont_info_to_save = {
                    'ont_serial_number': ont_info.get('ont_serial_number'),
                    'olt_identifier': ont_info.get('olt_identifier'),
                    'fsp': ont_info.get('fsp'),
                    'ont_id_on_pon': int(ont_info.get('ont_id_on_pon', 0)),
                    'diag_section_id': section_id,
                    'raw_output': raw_output,
                    'parsed_data_dict': parsed_data_dict
                }
                if ont_info_to_save['ont_serial_number']:
                    db_thread = threading.Thread(target=save_ont_diagnostic_data, args=(ont_info_to_save,), daemon=True)
                    db_thread.start()
                else:
                    logging.warning(f"S/N não encontrado. Não salvando diagnóstico para seção {section_id}.")

        if widget_config.get("output_area"):
            widget_config["output_area"].setText(output_to_display)
            widget_config["output_area"].setStyleSheet("color: red;" if is_error else "")
        if widget_config.get("button"):
            widget_config["button"].setText(f"Carregar {section_id.replace('_', ' ').title()}")
            widget_config["button"].setEnabled(self.is_ont_session_active)

    def handle_load_diag_data(self):
        """
        Manipulador para os botões 'Carregar Dados' na aba de Diagnóstico ONT.
        Atua como um direcionador, iniciando o worker apropriado para cada seção.
        """
        sender_button = self.sender()
        if not sender_button:
            return

        section_id = sender_button.property("section_id")

        if not self.is_ont_session_active or not self.active_ont_olt_shell:
            QMessageBox.warning(self, "Conexão Inativa", "Nenhuma conexão ativa com uma ONT para carregar dados.")
            return

        section_config = self.diag_widgets.get(section_id)
        if not section_config:
            logging.error(f"Configuração de widget não encontrada para a seção {section_id}")
            return

        output_widget = section_config["output_area"]
        output_widget.clear()
        output_widget.setText(f"Carregando dados para '{section_id}'...")
        sender_button.setText("Carregando...")
        sender_button.setEnabled(False)

        if section_id == "lan_wifi_devices":
            logging.info(f"Direcionando '{section_id}' para o worker dedicado de LAN/Wi-Fi.")
            self.ont_command_thread = threading.Thread(
                target=self._lan_wifi_command_worker,
                args=(section_id,),
                daemon=True
            )
        elif section_id == "connectivity_tests":
            logging.info(f"Direcionando '{section_id}' para o worker de Testes de Conectividade.")
            self.ont_command_thread = threading.Thread(
                target=self._connectivity_tests_worker,
                args=(section_id,),
                daemon=True
            )
        else:
            commands_to_run = section_config["commands"]
            logging.info(f"Direcionando '{section_id}' para o worker genérico.")
            self.ont_command_thread = threading.Thread(
                target=self._send_ont_command_worker,
                args=(section_id, commands_to_run),
                daemon=True
            )

        self.ont_command_thread.start()
            
    def _connect_to_ont_worker(self, ont_gateway_olt_ip, ont_gateway_olt_user, ont_gateway_olt_pass, fsp, ont_id_str):
        target_ont_id = ont_id_str
        log_prefix = f"[ONT Connect {fsp}/{target_ont_id}]"
        logging.info(f"{log_prefix} Iniciando thread de conexão...")

        if self.active_ont_olt_client:
            try: self.active_ont_olt_client.close()
            except Exception: pass
        self.active_ont_olt_client, self.active_ont_olt_shell = None, None

        try:
            logging.info(f"{log_prefix} Conectando à OLT gateway {ont_gateway_olt_ip}...")
            self.active_ont_olt_client, self.active_ont_olt_shell = connect_to_olt(
                ont_gateway_olt_ip, ont_gateway_olt_user, ont_gateway_olt_pass, max_retries=2
            )
            logging.info(f"{log_prefix} Conectado à OLT gateway. Shell obtido.")

            time.sleep(0.5)
            while self.active_ont_olt_shell.recv_ready():
                self.active_ont_olt_shell.recv(4096)
            
            logging.info(f"{log_prefix} Enviando 'enable' para a OLT.")
            self.active_ont_olt_shell.send("enable\n")
            time.sleep(0.5)
            
            response_enable_buffer = ""
            for _ in range(10):
                if self.active_ont_olt_shell.recv_ready():
                    response_enable_buffer += self.active_ont_olt_shell.recv(4096).decode('utf-8', errors='ignore')
                if "Password:" in response_enable_buffer or self.olt_standard_prompt_re.search(response_enable_buffer.strip().splitlines()[-1] if response_enable_buffer.strip() else ""):
                    break
                time.sleep(0.3)

            if "Password:" in response_enable_buffer:
                logging.info(f"{log_prefix} OLT pediu senha de enable.")
                self.active_ont_olt_shell.send(f"{ont_gateway_olt_pass}\n")
                time.sleep(1)
                while self.active_ont_olt_shell.recv_ready(): self.active_ont_olt_shell.recv(4096)

            logging.info(f"{log_prefix} Enviando 'diagnose' para a OLT.")
            self.active_ont_olt_shell.send("diagnose\n")
            time.sleep(1)
            
            diag_response_buffer = ""
            for _ in range(15):
                if self.active_ont_olt_shell.recv_ready():
                    diag_response_buffer += self.active_ont_olt_shell.recv(4096).decode('utf-8', 'ignore')
                if self.olt_diagnose_prompt_re.search(diag_response_buffer.strip().splitlines()[-1] if diag_response_buffer.strip() else ""):
                    logging.info(f"{log_prefix} Modo diagnose ativado.")
                    break
                time.sleep(0.3)

            if not self.olt_diagnose_prompt_re.search(diag_response_buffer.strip().splitlines()[-1] if diag_response_buffer.strip() else ""):
                logging.warning(f"{log_prefix} Prompt de diagnose não confirmado.")
            
            while self.active_ont_olt_shell.recv_ready(): self.active_ont_olt_shell.recv(4096)
            
            telnet_command = f"telnet {fsp} {target_ont_id}\n"
            logging.info(f"{log_prefix} Enviando comando Telnet: {telnet_command.strip()}")
            self.active_ont_olt_shell.send(telnet_command)
            time.sleep(0.5)

            full_response_after_telnet_cmd = ""
            param_prompt_found = False
            for _ in range(15):
                if self.active_ont_olt_shell.recv_ready():
                    chunk = self.active_ont_olt_shell.recv(4096).decode('utf-8', errors='ignore')
                    full_response_after_telnet_cmd += chunk
                    if self.olt_telnet_param_prompt_re.search(full_response_after_telnet_cmd):
                        param_prompt_found = True
                        break
                if "Trying" in full_response_after_telnet_cmd and "Connected to" in full_response_after_telnet_cmd:
                    logging.info(f"{log_prefix} OLT pulou prompt de param. telnet.")
                    break
                time.sleep(0.5)

            if param_prompt_found:
                logging.info(f"{log_prefix} Prompt de param. Telnet OLT detectado. Enviando <cr>.")
                self.active_ont_olt_shell.send("\n")
                time.sleep(7)
            
            ont_login_successful = False
            full_telnet_response = full_response_after_telnet_cmd

            for _ in range(25):
                if self.active_ont_olt_shell.recv_ready():
                    full_telnet_response += self.active_ont_olt_shell.recv(8192).decode('utf-8', errors='ignore')

                if self.ont_shell_prompt_re.search(full_telnet_response):
                    logging.info(f"{log_prefix} Prompt 'WAP>' detectado, login sem credenciais.")
                    ont_login_successful = True
                    break

                for user, pwd in self.common_ont_credentials:
                    if self.ont_login_prompt_user_re.search(full_telnet_response):
                        logging.info(f"{log_prefix} Prompt 'Login:' detectado. Enviando '{user}'")
                        self.active_ont_olt_shell.send(f"{user}\n")
                        full_telnet_response = ""
                        time.sleep(1.5)
                        for _p_loop in range(10):
                            if self.active_ont_olt_shell.recv_ready():
                                full_telnet_response += self.active_ont_olt_shell.recv(4096).decode('utf-8', errors='ignore')
                            if self.ont_login_prompt_pass_re.search(full_telnet_response):
                                break
                            time.sleep(0.5)

                    if self.ont_login_prompt_pass_re.search(full_telnet_response):
                        logging.info(f"{log_prefix} Prompt 'Password:' detectado. Enviando senha para '{user}'")
                        self.active_ont_olt_shell.send(f"{pwd}\n")
                        full_telnet_response = ""
                        time.sleep(1.5)
                        for _sh_loop in range(15):
                            if self.active_ont_olt_shell.recv_ready():
                                full_telnet_response += self.active_ont_olt_shell.recv(4096).decode('utf-8', errors='ignore')
                            if self.ont_shell_prompt_re.search(full_telnet_response):
                                ont_login_successful = True
                                break
                            time.sleep(0.4)
                        
                    if ont_login_successful: break
                if ont_login_successful: break
                time.sleep(0.5)

            if ont_login_successful:
                logging.info(f"{log_prefix} Login na ONT bem-sucedido.")
                self.active_ont_olt_shell.send("su\n")
                time.sleep(1)
                su_response = ""
                su_successful = False
                while self.active_ont_olt_shell.recv_ready():
                    su_response += self.active_ont_olt_shell.recv(4096).decode('utf-8', 'ignore')

                if "success!" in su_response.lower() or self.ont_root_prompt_re.search(su_response):
                    su_successful = True
                    logging.info(f"{log_prefix} 'su' bem-sucedido.")
                else:
                    logging.warning(f"{log_prefix} 'su' falhou ou não detectou o prompt root.")
                db_signals.ont_connection_status_changed.emit(True, f"Conectado: {fsp}/{target_ont_id} (su: {'OK' if su_successful else 'Não OK'})")
            else:
                logging.error(f"{log_prefix} Falha no login da ONT.")
                db_signals.ont_connection_status_changed.emit(False, f"Falha no login da ONT {fsp} ID {target_ont_id}.")
                if self.active_ont_olt_client: self.active_ont_olt_client.close()

        except Exception as e:
            logging.error(f"{log_prefix} Erro Geral na Conexão com a ONT: {e}", exc_info=True)
            db_signals.ont_connection_status_changed.emit(False, f"Erro na Conexão com a ONT: {e}")
            if self.active_ont_olt_client:
                try: self.active_ont_olt_client.close()
                except: pass
            self.active_ont_olt_client, self.active_ont_olt_shell = None, None

    def _send_ont_command_worker(self, section_id, commands_str):
        """
        Worker genérico que envia uma sequência de comandos para a ONT.
        """
        log_prefix = f"[ONT CMD {section_id}]"
        logging.info(f"{log_prefix} Iniciando worker para comandos: {commands_str.replace(chr(10), '; ')}")

        if not self.is_ont_session_active or not self.active_ont_olt_shell:
            logging.error(f"{log_prefix} Tentativa de enviar comando sem sessão ONT ativa.")
            db_signals.ont_command_output_received.emit(section_id, "Erro: Sem sessão ativa com a ONT.", True)
            return

        full_raw_output = ""
        commands = [cmd.strip() for cmd in commands_str.split('\n') if cmd.strip()]
        
        try:
            time.sleep(0.1)
            while self.active_ont_olt_shell.recv_ready(): self.active_ont_olt_shell.recv(4096)
            
            for command in commands:
                logging.info(f"{log_prefix} Enviando: {command}")
                full_raw_output += self._execute_single_ont_command(command)
                
            logging.info(f"{log_prefix} Comandos executados. Comprimento total da saída bruta: {len(full_raw_output)}")
            db_signals.ont_command_output_received.emit(section_id, full_raw_output, False)
            
        except Exception as e:
            logging.error(f"{log_prefix} Erro no worker ao enviar comando: {e}", exc_info=True)
            db_signals.ont_command_output_received.emit(section_id, f"Erro ao executar comando: {e}", True)

    def access_selected_ont(self):
        if self.is_ont_session_active:
            QMessageBox.information(self, "Sessão Ativa", "Já existe uma sessão de diagnóstico ONT ativa.\nPor favor, desconecte primeiro para acessar outra ONT.")
            return

        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "Nenhuma Seleção", "Por favor, selecione uma ONT na tabela para acessar.")
            return

        selected_row_index = selected_rows[0].row()

        olt_identifier_item = self.table.item(selected_row_index, 1)
        fsp_item = self.table.item(selected_row_index, 3)
        ont_id_item = self.table.item(selected_row_index, 4)
        serial_number_item = self.table.item(selected_row_index, 6)

        if not (fsp_item and ont_id_item and serial_number_item and olt_identifier_item):
            QMessageBox.critical(self, "Dados Incompletos na Tabela", "Não foi possível obter todos os dados necessários (FSP, ONT ID, S/N, OLT ID) da linha selecionada.")
            return

        fsp_val = fsp_item.text()
        ont_id_str_val = ont_id_item.text()
        serial_val = serial_number_item.text()
        olt_id_val = olt_identifier_item.text()

        if serial_val == "N/A" or not serial_val.strip():
            QMessageBox.critical(self, "S/N Inválido", f"Número de série da ONT ('{serial_val}') é inválido ou N/A.")
            return

        ont_gateway_olt_ip = self.olt_ip
        ont_gateway_olt_user = self.username
        ont_gateway_olt_pass = self.password

        if not ont_gateway_olt_ip or not ont_gateway_olt_user:
            QMessageBox.critical(self, "Credenciais da OLT Gateway Faltando", "As credenciais da OLT principal não foram fornecidas.")
            return

        self.current_diagnosed_ont_info = {
            'fsp': fsp_val,
            'ont_id_on_pon': ont_id_str_val,
            'ont_serial_number': serial_val,
            'olt_identifier': olt_id_val,
            'olt_gateway_ip': ont_gateway_olt_ip
        }
        
        logging.info(f"Tentando acessar ONT S/N: {serial_val} via OLT Gateway {ont_gateway_olt_ip}")
        
        if self.diag_ont_status_label:
            self.diag_ont_status_label.setText(f"Conectando à ONT: {fsp_val} ID {ont_id_str_val}...")
            self.diag_ont_status_label.setStyleSheet("font-weight: bold; padding: 5px; background-color: orange; border-radius: 3px;")
        
        self.tab_widget.setCurrentWidget(self.diag_ont_tab)

        self.ont_connection_thread = threading.Thread(
            target=self._connect_to_ont_worker,
            args=(ont_gateway_olt_ip, ont_gateway_olt_user, ont_gateway_olt_pass, fsp_val, ont_id_str_val),
            daemon=True
        )
        self.ont_connection_thread.start()

    def disconnect_from_ont(self):
        """Desconecta da sessão ONT ativa."""
        if self.active_ont_olt_client:
            try:
                self.active_ont_olt_client.close()
                logging.info("[ONT Disconnect] Conexão com OLT gateway fechada.")
            except Exception as e:
                logging.error(f"[ONT Disconnect] Erro ao fechar cliente OLT gateway: {e}")

        self.active_ont_olt_client = None
        self.active_ont_olt_shell = None
        self.is_ont_session_active = False
        self.current_diagnosed_ont_info = {}
        self._handle_ont_connection_status_changed(False, "Desconectado da ONT.")
        
        if not self.isClosing():
            QMessageBox.information(self, "Desconectado", "Sessão de diagnóstico com a ONT foi encerrada.")

    def isClosing(self):
        app = QApplication.instance()
        return app and hasattr(app, '_app_closing') and app._app_closing

    def _lan_wifi_command_worker(self, section_id):
        """
        Worker thread dedicado para a seção "Dispositivos Conectados", que
        executa múltiplos comandos e os processa em conjunto.
        """
        log_prefix = f"[ONT CMD {section_id}]"
        logging.info(f"{log_prefix} Iniciando worker dedicado...")

        if not self.is_ont_session_active or not self.active_ont_olt_shell:
            db_signals.ont_command_output_received.emit(section_id, "Erro: Sem sessão ativa com a ONT.", True)
            return

        try:
            # 1. Obter dados brutos de DHCP e Wi-Fi
            logging.info(f"{log_prefix} Coletando dados de DHCP e Wi-Fi...")
            dhcp_raw = self._execute_single_ont_command("display dhcp server user all")
            wifi_raw = self._execute_single_ont_command("display wifi associate")

            # 2. Extrair IPs para pingar
            ips_to_ping = re.findall(r"^\s*\d+\s+\S+\s+([\d\.]+)", dhcp_raw, re.MULTILINE)
            logging.info(f"{log_prefix} Encontrados {len(ips_to_ping)} IPs para testar.")

            # 3. Executar pings e armazenar resultados
            ping_results = {}
            for ip in ips_to_ping:
                logging.info(f"{log_prefix} -> Testando ping para {ip}...")
                # Emitir atualização para a GUI (opcional, mas bom para feedback)
                QMetaObject.invokeMethod(self.diag_widgets[section_id]["output_area"], "append", Qt.QueuedConnection, Q_ARG(str, f"\nTestando conectividade para {ip}..."))
                
                ping_output = self._execute_single_ont_command(f"ping {ip} -c 3")
                ping_results[ip] = ping_output
            
            # 4. Chamar a função de parsing do helper com todos os dados coletados
            logging.info(f"{log_prefix} Todos os dados coletados. Gerando relatório final...")
            formatted_report, _ = parse_lan_wifi_devices(
                dhcp_output=dhcp_raw,
                wifi_output=wifi_raw,
                ping_results=ping_results
            )

            # 5. Emitir o relatório JÁ FORMATADO para a GUI
            db_signals.ont_command_output_received.emit(section_id, formatted_report, False)

        except Exception as e:
            logging.error(f"{log_prefix} Erro no worker de LAN/Wi-Fi: {e}", exc_info=True)
            db_signals.ont_command_output_received.emit(section_id, f"Erro ao executar a rotina de LAN/Wi-Fi: {e}", True)

    def _execute_single_ont_command(self, command: str, timeout: int = 45) -> str:
        """
        Função auxiliar para executar um único comando na shell da ONT ativa.
        Usado pelos workers para simplificar a execução.
        """
        if not self.active_ont_olt_shell:
            raise ConnectionError("Shell da ONT não está ativa.")

        # Limpa o buffer de recepção antes de enviar o comando
        while self.active_ont_olt_shell.recv_ready():
            self.active_ont_olt_shell.recv(4096)

        # Determina o prompt esperado (root ou normal)
        self.active_ont_olt_shell.send("\n")
        time.sleep(0.3)
        prompt_buffer = ""
        while self.active_ont_olt_shell.recv_ready():
            prompt_buffer += self.active_ont_olt_shell.recv(1024).decode('utf-8', 'ignore')
        
        current_prompt_re = self.ont_root_prompt_re if self.ont_root_prompt_re.search(prompt_buffer) else self.ont_shell_prompt_re

        # Envia o comando real
        self.active_ont_olt_shell.send(command + "\n")

    def setup_caixa_stats_tab(self):
        """Configura a interface da aba 'Estatísticas por Caixa' com uma visualização em tabela."""
        layout = QVBoxLayout(self.caixa_stats_tab)

        # -- Painel de Controle (Filtro) --
        control_panel = QWidget()
        control_layout = QHBoxLayout(control_panel)

        self.caixa_olt_filter_label = QLabel("Filtrar por OLT:")
        self.caixa_olt_filter = QComboBox()
        if self.caixa_olt_filter not in self.olt_filters_to_update:
            self.olt_filters_to_update.append(self.caixa_olt_filter)
        
        self.caixa_olt_filter.currentTextChanged.connect(self.load_caixa_stats_data)

        control_layout.addWidget(self.caixa_olt_filter_label)
        control_layout.addWidget(self.caixa_olt_filter)
        control_layout.addStretch()
        layout.addWidget(control_panel)

        # -- Tabela de Estatísticas --
        self.caixa_stats_table = QTableWidget()
        self.caixa_stats_table.setColumnCount(5)
        self.caixa_stats_table.setHorizontalHeaderLabels(["Tipo", "Nome da Caixa", "Total de ONTs", "ONTs Offline", "% Offline"])
        self.caixa_stats_table.setSortingEnabled(True)
        self.caixa_stats_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.caixa_stats_table)




    def load_caixa_stats_data(self):
        """Carrega os dados das caixas e os exibe em uma tabela, destacando caixas com problemas."""
        logging.info("Carregando estatísticas por caixa para visualização em tabela.")
        
        self.caixa_stats_table.setSortingEnabled(False)
        self.caixa_stats_table.setRowCount(0)

        selected_olt = self.caixa_olt_filter.currentText()
        params = []
        olt_condition = ""
        if selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
            try:
                olt_identifier = selected_olt.split()[-1]
                olt_condition = "AND lo.olt_identifier = %s"
                params.append(olt_identifier)
            except IndexError:
                logging.warning(f"Formato de OLT inesperado no filtro: {selected_olt}")

        query = f"""
            WITH latest_onts AS (
                SELECT
                    olt_identifier, serial_number, primaria, secundaria, status,
                    ROW_NUMBER() OVER(PARTITION BY serial_number, olt_identifier ORDER BY collection_time DESC) as rn
                FROM ont_data
            ),
            caixas_union AS (
                SELECT olt_identifier, primaria as caixa_nome, 'Primária' as caixa_tipo
                FROM latest_onts WHERE rn = 1 AND primaria IS NOT NULL AND primaria <> '' AND primaria <> 'N/A'
                UNION
                SELECT olt_identifier, secundaria as caixa_nome, 'Secundária' as caixa_tipo
                FROM latest_onts WHERE rn = 1 AND secundaria IS NOT NULL AND secundaria <> '' AND secundaria <> 'N/A'
            )
            SELECT
                c.caixa_tipo,
                c.caixa_nome,
                COUNT(lo.serial_number) as total_onts,
                SUM(CASE WHEN lo.status = 'offline' THEN 1 ELSE 0 END) as onts_offline
            FROM latest_onts lo
            JOIN caixas_union c ON (lo.olt_identifier = c.olt_identifier AND
                ( (c.caixa_tipo = 'Primária' AND lo.primaria = c.caixa_nome) OR
                (c.caixa_tipo = 'Secundária' AND lo.secundaria = c.caixa_nome) )
            )
            WHERE lo.rn = 1 {olt_condition}
            GROUP BY c.caixa_tipo, c.caixa_nome
            ORDER BY
                CASE
                    WHEN COUNT(lo.serial_number) > 0 AND SUM(CASE WHEN lo.status = 'offline' THEN 1 ELSE 0 END) = COUNT(lo.serial_number) THEN 0
                    ELSE 1
                END ASC,
                (SUM(CASE WHEN lo.status = 'offline' THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(lo.serial_number), 0)) DESC,
                SUM(CASE WHEN lo.status = 'offline' THEN 1 ELSE 0 END) DESC;
        """
        
        try:
            self.cursor.execute(query, tuple(params))
            results = self.cursor.fetchall()
            
            self.caixa_stats_table.setRowCount(len(results))
            
            for row_idx, (caixa_tipo, caixa_nome, total_onts, onts_offline) in enumerate(results):
                onts_offline = onts_offline or 0
                percent_offline = (onts_offline / total_onts * 100) if total_onts > 0 else 0

                items = [
                    QTableWidgetItem(caixa_tipo),
                    QTableWidgetItem(caixa_nome),
                    QTableWidgetItem(str(total_onts)),
                    QTableWidgetItem(str(onts_offline)),
                    QTableWidgetItem(f"{percent_offline:.1f}%")
                ]
                
                color = None
                if onts_offline > 0:
                    if total_onts == onts_offline:
                        color = QColor("#E53935") # Vermelho para 100% offline
                    else:
                        color = QColor("#FFC107") # Amarelo para parcialmente offline

                for col_idx, item in enumerate(items):
                    if color:
                        item.setBackground(color)
                    self.caixa_stats_table.setItem(row_idx, col_idx, item)

            self.caixa_stats_table.resizeColumnsToContents()
            self.caixa_stats_table.setSortingEnabled(True)
            logging.info(f"{len(results)} registros de estatísticas de caixa carregados.")

        except psycopg2.Error as e:
            self.conn.rollback() # Desfaz a transação em caso de erro
            QMessageBox.critical(self, "Erro de Banco de Dados", f"Não foi possível carregar as estatísticas:\n{e}")
            logging.error(f"Erro ao carregar estatísticas por caixa: {e}", exc_info=True)
        except Exception as e:
            QMessageBox.critical(self, "Erro ao Carregar Estatísticas", f"Não foi possível carregar os dados das caixas: {str(e)}")
            logging.error(f"Erro ao carregar estatísticas por caixa: {e}", exc_info=True)
    

    def load_long_offline_data(self):
        """Carrega os dados das ONTs com mais de 30 dias de inatividade."""
        logging.info("Carregando dados de ONTs com longa inatividade.")
        
        self.long_offline_onts_table.setSortingEnabled(False)
        self.long_offline_onts_table.setRowCount(0)
        selected_olt = self.long_offline_olt_filter.currentText()
        params = []
        olt_condition = ""
        if selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
            try:
                olt_identifier = selected_olt.split()[-1]
                olt_condition = "AND ld.olt_identifier = %s"
                params.append(olt_identifier)
            except IndexError:
                logging.warning(f"Formato de OLT inesperado no filtro: {selected_olt}")
        
        # Abordagem 1: Tentar converter diretamente para timestamp
        # Isso funcionará se os dados estiverem em um formato reconhecível pelo PostgreSQL
        query_direct = f"""
            WITH latest_records AS (
                SELECT *, ROW_NUMBER() OVER(PARTITION BY serial_number, olt_identifier ORDER BY collection_time DESC) as rn
                FROM ont_data
                WHERE status = 'offline' AND last_up_time IS NOT NULL
            )
            SELECT
                olt_identifier, fsp, ont_id, serial_number, client_name, last_up_time,
                (NOW() - last_up_time) as offline_duration
            FROM latest_records
            WHERE rn = 1 AND last_up_time < NOW() - INTERVAL '30 days'
            {olt_condition}
            ORDER BY last_up_time ASC;
        """
        
        try:
            self.cursor.execute(query_direct, tuple(params))
            results = self.cursor.fetchall()
            
            if results:
                self.long_offline_onts_table.setRowCount(len(results))
                
                for row_idx, (olt, fsp, ont_id, sn, client, last_up, duration) in enumerate(results):
                    days_offline = duration.days if duration else 0
                    items = [
                        QTableWidgetItem(str(olt)),
                        QTableWidgetItem(fsp),
                        QTableWidgetItem(str(ont_id)),
                        QTableWidgetItem(sn),
                        QTableWidgetItem(client if client else "N/A"),
                        QTableWidgetItem(last_up.strftime('%d/%m/%Y %H:%M') if last_up else "N/A"),
                        QTableWidgetItem(str(days_offline))
                    ]
                    for col_idx, item in enumerate(items):
                        self.long_offline_onts_table.setItem(row_idx, col_idx, item)
                
                self.long_offline_onts_table.resizeColumnsToContents()
                self.long_offline_onts_table.setSortingEnabled(True)
                logging.info(f"{len(results)} ONTs com longa inatividade carregadas (método direto).")
                return
        except Exception as e:
            logging.warning(f"Método direto falhou: {e}")
            # Se o método direto falhar, tentar a abordagem de conversão de texto
            if self.conn:
                self.conn.rollback()
        
        # Abordagem 2: Converter texto para timestamp (se o método direto falhar)
        logging.info("Tentando método alternativo de conversão de data...")
        
        # Primeiro, verificar os formatos de data presentes no banco
        check_format_query = """
            SELECT DISTINCT last_up_time 
            FROM ont_data 
            WHERE last_up_time IS NOT NULL 
            LIMIT 10;
        """
        
        try:
            self.cursor.execute(check_format_query)
            date_formats = self.cursor.fetchall()
            logging.info(f"Formatos de data encontrados: {[row[0] for row in date_formats]}")
        except Exception as e:
            logging.error(f"Erro ao verificar formatos de data: {e}")
        
        # Query alternativa usando conversão de texto
        query_alternative = f"""
            WITH latest_records AS (
                SELECT *, ROW_NUMBER() OVER(PARTITION BY serial_number, olt_identifier ORDER BY collection_time DESC) as rn
                FROM ont_data
                WHERE status = 'offline' AND last_up_time IS NOT NULL
            ),
            converted_times AS (
                SELECT
                    *,
                    CASE
                        WHEN last_up_time ~ '^\\d{{2}}/\\d{{2}}/\\d{{4}} \\d{{2}}:\\d{{2}}:\\d{{2}}' 
                            THEN TO_TIMESTAMP(last_up_time, 'DD/MM/YYYY HH24:MI:SS')
                        WHEN last_up_time ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}} \\d{{2}}:\\d{{2}}:\\d{{2}}' 
                            THEN TO_TIMESTAMP(last_up_time, 'YYYY-MM-DD HH24:MI:SS')
                        ELSE NULL
                    END as last_up_time_ts
                FROM latest_records
            )
            SELECT
                olt_identifier, fsp, ont_id, serial_number, client_name, last_up_time,
                (NOW() - last_up_time_ts) as offline_duration
            FROM converted_times
            WHERE rn = 1 AND last_up_time_ts IS NOT NULL AND last_up_time_ts < NOW() - INTERVAL '30 days'
            {olt_condition}
            ORDER BY last_up_time_ts ASC;
        """
        
        try:
            self.cursor.execute(query_alternative, tuple(params))
            results = self.cursor.fetchall()
            
            self.long_offline_onts_table.setRowCount(len(results))
            
            for row_idx, (olt, fsp, ont_id, sn, client, last_up, duration) in enumerate(results):
                days_offline = duration.days if duration else 0
                items = [
                    QTableWidgetItem(str(olt)),
                    QTableWidgetItem(fsp),
                    QTableWidgetItem(str(ont_id)),
                    QTableWidgetItem(sn),
                    QTableWidgetItem(client if client else "N/A"),
                    QTableWidgetItem(last_up.strftime('%d/%m/%Y %H:%M') if last_up else "N/A"),
                    QTableWidgetItem(str(days_offline))
                ]
                for col_idx, item in enumerate(items):
                    self.long_offline_onts_table.setItem(row_idx, col_idx, item)
            
            self.long_offline_onts_table.resizeColumnsToContents()
            self.long_offline_onts_table.setSortingEnabled(True)
            logging.info(f"{len(results)} ONTs com longa inatividade carregadas (método alternativo).")
            
        except psycopg2.Error as e:
            if self.conn:
                self.conn.rollback()
            QMessageBox.critical(self, "Erro de Banco de Dados", f"Não foi possível carregar ONTs inativas:\n{e}")
            logging.error(f"Erro ao carregar ONTs com longa inatividade: {e}", exc_info=True)
            
            # Se ambos os métodos falharem, mostrar uma mensagem mais informativa
            error_msg = f"""
            <b>Erro ao carregar dados de ONTs inativas</b><br><br>
            Erro técnico: {str(e)}<br><br>
            <b>Possíveis causas:</b><br>
            1. Formato de data/hora não reconhecido pelo PostgreSQL<br>
            2. Dados corrompidos ou inconsistentes na tabela<br>
            3. Problemas com a conexão do banco de dados<br><br>
            <b>Soluções sugeridas:</b><br>
            1. Verificar o formato dos dados na coluna 'last_up_time'<br>
            2. Executar uma consulta manual para diagnosticar o problema
            """
            QMessageBox.critical(self, "Erro Crítico", error_msg)
            
        except Exception as e:
            QMessageBox.critical(self, "Erro ao Carregar ONTs Inativas", f"Erro inesperado: {str(e)}")
            logging.error(f"Erro inesperado ao carregar ONTs com longa inatividade: {e}", exc_info=True)


    def setup_data_tab(self):
        # Remove qualquer layout existente para evitar duplicação
        if self.data_tab.layout():
            # Cria um novo layout temporário para transferir os widgets
            temp_widget = QWidget()
            temp_layout = QVBoxLayout(temp_widget)
            
            # Transfere todos os widgets do layout antigo para o novo
            while self.data_tab.layout().count():
                item = self.data_tab.layout().takeAt(0)
                if item.widget():
                    temp_layout.addWidget(item.widget())
            
            # Remove o layout antigo
            QWidget().setLayout(self.data_tab.layout())
        
        # Cria o novo layout
        layout = QVBoxLayout(self.data_tab)
        layout.setContentsMargins(5, 5, 5, 5)  # Reduz as margens
        layout.setSpacing(5)  # Reduz o espaçamento entre widgets
        
        # Adiciona o painel de seleção de OLTs no topo
        olt_selection_panel = self.create_multi_olt_control_panel()
        layout.addWidget(olt_selection_panel)
        
        # Cria o painel principal com a tabela e controles
        main_panel = QWidget()
        main_layout = QVBoxLayout(main_panel)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(5)
        
        action_filter_panel = self.create_action_filter_panel()
        self.status_panel = self.create_status_panel()
        self.setup_data_table()  # Garante que a tabela seja configurada corretamente
        
        main_layout.addWidget(action_filter_panel)
        main_layout.addWidget(self.status_panel)
        main_layout.addWidget(self.table)
        
        layout.addWidget(main_panel)

    def create_multi_olt_control_panel(self):
        """Cria o painel de controle para seleção de OLTs com checkboxes."""
        panel = QGroupBox("OLTs")
        panel.setMaximumHeight(100)  # Altura reduzida
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 3, 5, 3)  # Margens reduzidas
        layout.setSpacing(2)  # Espaçamento mínimo
        
        # Layout horizontal para os checkboxes
        checkboxes_layout = QHBoxLayout()
        checkboxes_layout.setSpacing(10)  # Espaçamento entre checkboxes
        
        # Adiciona checkbox "Todos"
        self.select_all_checkbox = QCheckBox("Todos")
        self.select_all_checkbox.setStyleSheet("font-size: 9px; font-weight: bold;")
        self.select_all_checkbox.stateChanged.connect(self.toggle_all_olts)
        checkboxes_layout.addWidget(self.select_all_checkbox)
        
        # Limpa o dicionário de checkboxes
        self.olt_checkboxes.clear()
        
        # Cria um checkbox para cada OLT
        for olt in self.olt_configs:
            checkbox = QCheckBox(f"{olt['name']}")
            checkbox.setStyleSheet("font-size: 9px;")  # Fonte menor
            checkboxes_layout.addWidget(checkbox)
            self.olt_checkboxes[olt['ip']] = checkbox
        
        checkboxes_layout.addStretch()  # Empurra os checkboxes para a esquerda
        
        # Botões de controle
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(5)
        
        self.start_selected_btn = QPushButton("Iniciar")
        self.start_selected_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; font-size: 9px;")
        self.start_selected_btn.clicked.connect(self.start_selected_collections)
        
        self.stop_all_btn = QPushButton("Parar")
        self.stop_all_btn.setStyleSheet("background-color: #f44336; color: white; font-weight: bold; font-size: 9px;")
        self.stop_all_btn.clicked.connect(self.stop_all_collections)
        self.stop_all_btn.setEnabled(False)
        
        buttons_layout.addWidget(self.start_selected_btn)
        buttons_layout.addWidget(self.stop_all_btn)
        buttons_layout.addStretch()
        
        layout.addLayout(checkboxes_layout)
        layout.addLayout(buttons_layout)
        
        return panel
    
# Em gui/main_window.py, modifique o método start_selected_collections:

    def start_selected_collections(self):
        """Inicia threads de coleta para cada OLT selecionada via checkbox."""
        selected_olts = []
        
        # Verifica quais checkboxes estão marcados
        for ip, checkbox in self.olt_checkboxes.items():
            if checkbox.isChecked():
                selected_olts.append(ip)
        
        if not selected_olts:
            QMessageBox.warning(self, "Nenhuma OLT Selecionada", "Por favor, selecione pelo menos uma OLT.")
            return
                
        self.collection_running = True
        self.stop_all_btn.setEnabled(True)
        self.start_selected_btn.setEnabled(False)
        self.log_to_gui("--- Iniciando coletas... ---")
        
        # Inicializa o worker ETH global se ainda não foi inicializado
        if not hasattr(self, 'eth_task_queue'):
            self.init_eth_workers()
        
        for olt_ip in selected_olts:
            olt_config = next((olt for olt in self.olt_configs if olt['ip'] == olt_ip), None)
            
            if not olt_config:
                self.log_to_gui(f"ERRO: Configuração não encontrada para o IP {olt_ip}")
                continue
                    
            if olt_ip in self.collection_threads and self.collection_threads[olt_ip].is_alive():
                self.log_to_gui(f"AVISO: A coleta para a OLT {olt_config['name']} já está em execução.")
                continue
            
            # Inicia a thread orquestradora principal
            thread = threading.Thread(
                target=run_data_collection,
                args=(
                    olt_config['ip'], 
                    olt_config['username'], 
                    olt_config['password'], 
                    self, 
                    self.log_message_received.emit,
                    self.eth_task_queue  # Passa a fila global para o orquestrador
                ),
                daemon=True,
                name=f"PonWorker-{olt_ip}"
            )
            self.collection_threads[olt_ip] = thread
            thread.start()
            self.log_to_gui(f"Thread de coleta iniciada para {olt_config['name']} ({olt_ip})")


    def toggle_all_olts(self, checked):
        """Seleciona ou desmarca todos os checkboxes de OLTs."""
        for checkbox in self.olt_checkboxes.values():
            checkbox.setChecked(checked)
# Em gui/main_window.py, modifique o método stop_all_collections:

    def stop_all_collections(self):
        """Sinaliza para todas as threads de coleta pararem."""
        if not self.collection_running: 
            return
            
        self.log_to_gui("--- Sinal de parada enviado para todas as coletas. ---")
        self.collection_running = False
        
        # Envia sinal de parada para o worker ETH global
        if hasattr(self, 'eth_task_queue'):
            try:
                self.eth_task_queue.put(None)  # Sinal de parada para o worker ETH
                self.log_to_gui("Sinal de parada enviado para thread ETH global")
            except Exception as e:
                self.log_to_gui(f"ERRO ao enviar sinal de parada para thread ETH: {e}")
        
        self.start_selected_btn.setEnabled(True)
        self.stop_all_btn.setEnabled(False)



    def load_olt_list_to_filters(self):
        """Carrega a lista de OLTs disponíveis do banco para os ComboBoxes de filtro."""
        try:
            self.cursor.execute("SELECT DISTINCT olt_identifier FROM ont_data WHERE olt_identifier IS NOT NULL ORDER BY olt_identifier")
            olts = self.cursor.fetchall()
            for combo_box in self.olt_filters_to_update:
                if combo_box is None: continue
                current_selection = combo_box.currentText()
                combo_box.blockSignals(True)
                combo_box.clear()
                combo_box.addItem("Todas as OLTs")
                for olt in olts:
                    combo_box.addItem(f"OLT {olt[0]}")
                index = combo_box.findText(current_selection)
                if index != -1:
                    combo_box.setCurrentIndex(index)
                else:
                    combo_box.setCurrentIndex(0)
                combo_box.blockSignals(False)
        except Exception as e:
            logging.error(f"Erro ao carregar lista de OLTs para filtros: {e}")
            for combo_box in self.olt_filters_to_update:
                if combo_box:
                    combo_box.clear(); combo_box.addItem("Erro ao carregar OLTs")
                
    def create_action_filter_panel(self):
        """Cria o painel que contém os filtros da tabela e os botões de ação."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)  # Reduz o espaçamento entre seções
        
        # Seção de ações
        action_box = QGroupBox("Ações na Tabela")
        action_layout = QHBoxLayout(action_box)
        action_layout.setContentsMargins(5, 5, 5, 5)
        action_layout.setSpacing(5)
        
        self.access_ont_btn = QPushButton("Acessar ONT")
        self.access_ont_btn.clicked.connect(self.access_selected_ont)
        self.access_ont_btn.setEnabled(False)
        action_layout.addWidget(self.access_ont_btn)
        
        action_buttons_config = [
            ("Histórico", self.show_history),
            ("Exportar CSV", self.export_to_csv),
            ("Importar Clientes (CSV)", self.import_clients_from_csv),
            ("Limpar Dados", self.show_cleanup_dialog)
        ]
        
        for text, handler in action_buttons_config:
            btn = QPushButton(text)
            btn.clicked.connect(handler)
            action_layout.addWidget(btn)
        
        action_layout.addStretch()
        
        # Seção de filtros
        filter_box = QGroupBox("Filtros e Visualização")
        filter_layout = QGridLayout(filter_box)
        filter_layout.setContentsMargins(5, 5, 5, 5)
        filter_layout.setHorizontalSpacing(5)
        filter_layout.setVerticalSpacing(3)
        
        self.olt_filter_label = QLabel("Filtrar por OLT:")
        self.olt_filter = QComboBox()
        if self.olt_filter not in self.olt_filters_to_update:
            self.olt_filters_to_update.append(self.olt_filter)
        
        self.filter_field_label = QLabel("Filtrar por:")
        self.filter_field = QComboBox()
        self.filter_field.addItems(["Todos", "FSP", "ONT ID", "Endereço MAC", "S/N", "CLIENTE",
                                    "Primária", "Secundária", "Descrição", "Status", "Sinal RX"])
        self.filter_value = QLineEdit()
        self.filter_value.setPlaceholderText("Digite o valor do filtro")
        
        filter_layout.addWidget(self.olt_filter_label, 0, 0)
        filter_layout.addWidget(self.olt_filter, 0, 1)
        filter_layout.addWidget(self.filter_field_label, 0, 2)
        filter_layout.addWidget(self.filter_field, 0, 3)
        filter_layout.addWidget(self.filter_value, 0, 4, 1, 2)
        
        filter_btn = QPushButton("Filtrar")
        filter_btn.clicked.connect(self.apply_filter)
        filter_layout.addWidget(filter_btn, 0, 6)
        
        self.fsp_filter_label = QLabel("FSP Específico:")
        self.fsp_filter = QLineEdit()
        self.fsp_filter.setPlaceholderText("ex: 0/1/1")
        self.fsp_filter_label.setVisible(False)
        self.fsp_filter.setVisible(False)
        
        self.desc_filter = QComboBox()
        self.desc_filter.setVisible(False)
        
        self.signal_filter_options = QComboBox()
        self.signal_filter_options.addItems([
            "Todos os Sinais", "Sinal Bom (>= -22.0 dBm)",
            "Sinal Alerta (-22.0 dBm > RX >= -24.99 dBm)", "Sinal Crítico (RX < -25.0 dBm)"
        ])
        self.signal_filter_options.setVisible(False)
        
        filter_layout.addWidget(self.fsp_filter_label, 1, 0)
        filter_layout.addWidget(self.fsp_filter, 1, 1)
        filter_layout.addWidget(self.desc_filter, 1, 4, 1, 2)
        filter_layout.addWidget(self.signal_filter_options, 1, 4, 1, 2)
        
        filter_layout.setColumnStretch(5, 1)
        self.filter_field.currentTextChanged.connect(self.update_filter_ui)
        
        layout.addWidget(action_box)
        layout.addWidget(filter_box)
        return panel
    
    def on_ont_selection_changed(self):
        """Habilita ou desabilita o botão 'Acessar ONT' baseado na seleção da tabela."""
        if self.access_ont_btn:
            selected_items = self.table.selectedItems()
            self.access_ont_btn.setEnabled(bool(selected_items) and not self.is_ont_session_active)

    def _start_blinking_animation(self, widget: QWidget):
        """Aplica uma animação de 'pulsar' no fundo de um widget."""
        
        # Define as cores da animação
        start_color = QColor("#FFCDD2")  # Vermelho bem claro
        end_color = QColor("#E53935")    # Vermelho forte

        # Para animar uma cor de stylesheet, precisamos de um truque:
        # animar uma propriedade 'color' customizada e usar um slot para aplicá-la.
        def _set_background_color(color):
            widget.setStyleSheet(f"""
                QGroupBox {{
                    background-color: {color.name()};
                    font-weight: bold;
                    color: white;
                    border: 1px solid #B71C1C;
                    border-radius: 5px;
                    margin-top: 10px;
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    subcontrol-position: top left;
                    padding: 0 3px;
                    color: white;
                    background-color: #B71C1C;
                    border-radius: 3px;
                }}
                QGroupBox QLabel {{
                    color: white;
                    background-color: transparent;
                }}
            """)

        # Animação de ida (claro -> escuro)
        anim_forward = QPropertyAnimation(widget, b"color")
        anim_forward.setDuration(1000) # 1 segundo
        anim_forward.setStartValue(start_color)
        anim_forward.setEndValue(end_color)

        # Animação de volta (escuro -> claro)
        anim_backward = QPropertyAnimation(widget, b"color")
        anim_backward.setDuration(1000)
        anim_backward.setStartValue(end_color)
        anim_backward.setEndValue(start_color)

        # A animação é um objeto customizado que o Python não reconhece,
        # então o conectamos ao nosso setter de cor.
        anim_forward.valueChanged.connect(_set_background_color)
        anim_backward.valueChanged.connect(_set_background_color)
        
        # Organiza as animações para ocorrerem em sequência e em loop
        from PyQt5.QtCore import QSequentialAnimationGroup
        anim_group = QSequentialAnimationGroup()
        anim_group.addAnimation(anim_forward)
        anim_group.addAnimation(anim_backward)
        anim_group.setLoopCount(-1) # Loop infinito
        
        anim_group.start()
        

    def setup_data_table(self):
        """Configura a tabela principal de exibição de dados ONT."""
        self.table = QTableWidget()
        # FIXED: Set column count to match headers (17 columns)
        self.table.setColumnCount(17)
        
        # FIXED: Ensure headers list has 17 elements
        headers = [
            "ID", "OLT", "Hora", "F/S/P", "ONT ID", "MAC", "S/N", "CLIENTE", 
            "RX (dBm)", "TX (dBm)", "Status", "Primária", "Secundária", "Porta Sec.", 
            "Descrição OLT", "Cod.", "Mudanças"
        ]
        self.table.setHorizontalHeaderLabels(headers)
        
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.AnyKeyPressed | QTableWidget.DoubleClicked)
        
        self.table.doubleClicked.connect(self.show_ont_details)
        self.table.cellChanged.connect(self._handle_client_name_changed)
        self.table.selectionModel().selectionChanged.connect(self.on_ont_selection_changed)
        
        # Ajuste de largura das colunas
        widths = [50, 60, 140, 70, 60, 120, 130, 200, 80, 80, 80, 100, 120, 70, 200, 70, 70]
        for i, width in enumerate(widths):
            self.table.setColumnWidth(i, width)
    
    @pyqtSlot(str, int, float)
    def update_ont_cycle_stats(self, olt_ip, count, duration):
        """
        Recebe o sinal de conclusão de ciclo e registra a informação
        na área de log da GUI.
        """
        self.log_to_gui(f"[{olt_ip}] Ciclo #{count} finalizado em {duration:.2f}s.")
    # --- Fim da Modificação ---
    def create_status_panel(self):
        """Cria o painel de status simplificado, contendo apenas os resumos."""
        panel = QWidget()
        status_labels_layout = QHBoxLayout(panel)
        status_labels_layout.setContentsMargins(0, 5, 0, 5)

        self.olt_status_label = QLabel("OLT: Não selecionada")
        self.total_onts_label = QLabel("Total ONTs (PONs): 0")
        self.online_onts_label = QLabel("Online (PONs): 0")
        self.offline_onts_label = QLabel("Offline (PONs): 0")
        self.percent_label = QLabel("Disponibilidade: 0%")

        status_labels_layout.addWidget(self.olt_status_label)
        status_labels_layout.addWidget(self.total_onts_label)
        status_labels_layout.addWidget(self.online_onts_label)
        status_labels_layout.addWidget(self.offline_onts_label)
        status_labels_layout.addWidget(self.percent_label)
        status_labels_layout.addStretch()

        return panel
    
    def setup_temp_tab(self):
        """Configura a interface da aba de 'Temperatura'."""
        layout = QVBoxLayout()
        self.temp_tab.setLayout(layout)
        status_panel = QWidget()
        status_layout = QHBoxLayout()
        status_panel.setLayout(status_layout)
        self.execution_counter = QLabel("Execuções: 0")
        self.execution_counter.setStyleSheet("font-weight: bold;")
        self.last_execution_label = QLabel("Última execução: Nunca")
        self.insert_status_label = QLabel("Dados inseridos: 0")
        self.insert_status_label.setStyleSheet("color: green;")
        verify_btn = QPushButton("Verificar Banco de Dados")
        verify_btn.setStyleSheet("background-color: #2196F3; color: white;")
        verify_btn.clicked.connect(self.verify_database_entries)
        status_layout.addWidget(self.execution_counter)
        status_layout.addWidget(self.last_execution_label)
        status_layout.addWidget(self.insert_status_label)
        status_layout.addStretch()
        status_layout.addWidget(verify_btn)
        self.temp_table = QTableWidget()
        self.temp_table.setColumnCount(5)
        self.temp_table.setHorizontalHeaderLabels(["Slot", "Placa", "Temp (°C)", "Temp (°F)", "Status"])
        self.temp_table.setSortingEnabled(True)
        self.temp_table.doubleClicked.connect(self.show_temp_history)
        control_panel = QWidget()
        control_layout = QHBoxLayout()
        control_panel.setLayout(control_layout)
        self.start_temp_btn = QPushButton("Iniciar Monitoramento (30s)")
        self.start_temp_btn.setStyleSheet("background-color: #4CAF50; color: white;")
        self.start_temp_btn.clicked.connect(self.start_temp_monitoring)
        self.stop_temp_btn = QPushButton("Parar Monitoramento")
        self.stop_temp_btn.setStyleSheet("background-color: #f44336; color: white;")
        self.stop_temp_btn.setEnabled(False)
        self.stop_temp_btn.clicked.connect(self.stop_temp_monitoring)
        control_layout.addWidget(self.start_temp_btn)
        control_layout.addWidget(self.stop_temp_btn)
        layout.addWidget(status_panel)
        layout.addWidget(self.temp_table)
        layout.addWidget(control_panel)
        self.temp_update_timer = QTimer()
        self.temp_update_timer.timeout.connect(self.update_temperature_display)
        self.temp_update_timer.start(5000)

    def setup_resource_tab(self):
        """Configura a interface da aba de 'Recursos'."""
        layout = QVBoxLayout()
        self.resource_tab.setLayout(layout)
        status_panel = QWidget()
        status_layout = QHBoxLayout()
        status_panel.setLayout(status_layout)
        self.resource_execution_counter = QLabel("Execuções: 0")
        self.resource_last_execution_label = QLabel("Última execução: Nunca")
        self.resource_status_label = QLabel("Status: Parado")
        self.resource_status_label.setStyleSheet("color: red;")
        verify_btn = QPushButton("Verificar Banco de Dados")
        verify_btn.setStyleSheet("background-color: #2196F3; color: white;")
        verify_btn.clicked.connect(self.verify_resource_entries)
        status_layout.addWidget(self.resource_execution_counter)
        status_layout.addWidget(self.resource_last_execution_label)
        status_layout.addWidget(self.resource_status_label)
        status_layout.addStretch()
        status_layout.addWidget(verify_btn)
        self.resource_table = QTableWidget()
        self.resource_table.setColumnCount(5)
        self.resource_table.setHorizontalHeaderLabels(["Slot", "Placa", "Tipo", "Uso", "Status"])
        self.resource_table.setSortingEnabled(True)
        self.resource_table.doubleClicked.connect(self.show_resource_history)

        control_panel = QWidget()
        control_layout = QHBoxLayout()
        control_panel.setLayout(control_layout)
        self.start_resource_btn = QPushButton("Iniciar Monitoramento (30s)")
        self.start_resource_btn.setStyleSheet("background-color: #4CAF50; color: white;")
        self.start_resource_btn.clicked.connect(self.start_resource_monitoring)
        self.stop_resource_btn = QPushButton("Parar Monitoramento")
        self.stop_resource_btn.setStyleSheet("background-color: #f44336; color: white;")
        self.stop_resource_btn.setEnabled(False)
        self.stop_resource_btn.clicked.connect(self.stop_resource_monitoring)
        control_layout.addWidget(self.start_resource_btn)
        control_layout.addWidget(self.stop_resource_btn)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.resource_table)
        splitter.setStretchFactor(0, 3)

        layout.addWidget(status_panel)
        layout.addWidget(splitter)
        layout.addWidget(control_panel)

        self.resource_update_timer = QTimer()
        self.resource_update_timer.timeout.connect(self.update_resource_display)
        self.resource_update_timer.start(5000)

    def setup_timers(self):
        """Configura timers para atualizações periódicas da GUI."""
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.check_for_updates)
        self.update_timer.start(10000)

        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_pon_status_and_alarms)
        self.status_timer.start(15000)

    def update_status_display(self, count_str, time_str, status_str):
        """Atualiza os rótulos de status nas abas de Temperatura e Recursos."""
        current_tab = self.tab_widget.currentWidget()
        if current_tab == self.temp_tab:
            self.execution_counter.setText(count_str)
            self.last_execution_label.setText(time_str)
            self.insert_status_label.setText(status_str)
            if "Erro" in status_str or "Falha" in status_str: self.insert_status_label.setStyleSheet("color: red; font-weight: bold;")
            elif "Nenhum" in status_str: self.insert_status_label.setStyleSheet("color: orange;")
            else: self.insert_status_label.setStyleSheet("color: green;")
        elif current_tab == self.resource_tab:
            self.resource_execution_counter.setText(count_str)
            self.resource_last_execution_label.setText(time_str)
            self.resource_status_label.setText(status_str)
            if "Erro" in status_str or "Falha" in status_str or "Parado" in status_str : self.resource_status_label.setStyleSheet("color: red; font-weight: bold;")
            elif "Nenhum" in status_str or "Coletando" in status_str : self.resource_status_label.setStyleSheet("color: orange;")
            else: self.resource_status_label.setStyleSheet("color: green;")

    def update_filter_ui(self, filter_type):
        """Atualiza a visibilidade dos campos de filtro baseada na seleção do usuário."""
        self.fsp_filter.setVisible(filter_type == "ONT ID")
        self.fsp_filter_label.setVisible(filter_type == "ONT ID")
        self.desc_filter.setVisible(filter_type == "Descrição")
        self.signal_filter_options.setVisible(filter_type == "Sinal RX")

        self.filter_value.setVisible(filter_type not in ["Todos", "Descrição", "Sinal RX"])

        if filter_type == "Descrição":
            self.load_description_filter()

    def load_description_filter(self):
        """Carrega as opções para o filtro de descrição (Primárias e Secundárias)."""
        try:
            self.desc_filter.clear()
            self.desc_filter.addItem("Todas as descrições")
            olt_filter_text = self.olt_filter.currentText()
            olt_condition = ""
            params = []
            if olt_filter_text != "Todas as OLTs" and olt_filter_text != "Erro ao carregar OLTs":
                olt_num = olt_filter_text.split()[-1]
                olt_condition = "WHERE olt_identifier = %s"
                params.append(olt_num)

            query_primarias = f"SELECT DISTINCT primaria FROM ont_data {olt_condition} AND primaria IS NOT NULL AND primaria <> 'N/A' ORDER BY primaria"
            self.cursor.execute(query_primarias, tuple(params) if params else None)
            primaries = [row[0] for row in self.cursor.fetchall()]

            query_secundarias = f"SELECT DISTINCT secundaria FROM ont_data {olt_condition} AND secundaria IS NOT NULL AND secundaria <> 'N/A' ORDER BY secundaria"
            self.cursor.execute(query_secundarias, tuple(params) if params else None)
            secondaries = [row[0] for row in self.cursor.fetchall()]

            if primaries:
                self.desc_filter.addItem("--- Primárias ---")
                for primary in primaries: self.desc_filter.addItem(f"Primária: {primary}")
            if secondaries:
                self.desc_filter.addItem("--- Secundárias ---")
                for secondary in secondaries: self.desc_filter.addItem(f"Secundária: {secondary}")
        except Exception as e:
            logging.error(f"Erro ao carregar descrições para filtro: {str(e)}")
            self.desc_filter.addItem("Erro ao carregar descrições")

    def check_for_updates(self):
        """Verifica periodicamente se há novos dados no banco e atualiza a GUI se necessário."""
        try:
            # --- INÍCIO DA CORREÇÃO ---
            # Inicializa a variável como None para garantir que ela sempre exista.
            current_max_time = None
            # --- FIM DA CORREÇÃO ---

            query = "SELECT MAX(collection_time) FROM ont_data"
            self.cursor.execute(query)
            result = self.cursor.fetchone()
            
            # Se a consulta for bem-sucedida, a variável é atualizada.
            if result and result[0] is not None:
                current_max_time = result[0]

            if current_max_time and (self.last_update_time is None or current_max_time > self.last_update_time):
                logging.debug(f"Novos dados detectados no banco (Hora máxima: {current_max_time}). Atualizando GUI.")
                self.last_update_time = current_max_time
                self.safe_update()
            elif self.last_update_time is None and current_max_time is None:
                logging.debug("Nenhum dado no banco ainda, ou nenhuma atualização desde a última verificação.")
        except Exception as e:
            logging.error(f"Erro ao verificar atualizações no banco de dados: {str(e)}")
            if "connection" in str(e).lower():
                logging.warning("Conexão com o banco de dados pode estar perdida. Tentando reconectar...")
                self.connect_to_db()

    def apply_filter(self):
        """Aplica os filtros selecionados e recarrega os dados da tabela ONT."""
        filter_field_text = self.filter_field.currentText()
        filter_value_text = self.filter_value.text().strip()
        desc_value_text = self.desc_filter.currentText()
        signal_option_text = self.signal_filter_options.currentText()

        if filter_field_text == "Todos":
            self.load_data()
        elif filter_field_text == "Descrição":
            self.load_data(filter_field=filter_field_text, filter_value=desc_value_text)
        elif filter_field_text == "Sinal RX":
            self.load_data(filter_field=filter_field_text, filter_value=signal_option_text)
        elif filter_value_text or filter_field_text == "ONT ID":
            self.load_data(filter_field=filter_field_text, filter_value=filter_value_text)
        else:
            self.load_data()

    @pyqtSlot(str, int, float)
    def update_ont_cycle_stats(self, olt_ip, count, duration):
        """
        Recebe o sinal de conclusão de ciclo e registra a informação
        na área de log da GUI.
        """
        self.log_to_gui(f"[{olt_ip}] Ciclo #{count} finalizado em {duration:.2f}s.")

# Em main_window.py, adicione este método

    def run_in_thread(self, func, callback=None):
        """Executa uma função em uma thread separada e opcionalmente chama um callback."""
        def worker():
            try:
                result = func()
                if callback:
                    # Usar QMetaObject.invokeMethod para chamadas seguras à GUI
                    QMetaObject.invokeMethod(self, callback, 
                                            Qt.QueuedConnection, 
                                            Q_ARG(object, result))
            except Exception as e:
                logging.error(f"Erro na thread: {e}")
        
        thread = threading.Thread(target=worker)
        thread.daemon = True
        thread.start()

# Em gui/main_window.py, substitua a sua função load_data inteira por esta:

    def load_data(self, filter_field=None, filter_value=None):
        """Carrega os dados das ONTs do banco, aplicando filtros e atualizando alarmes."""
        current_olt_filter_text = self.olt_filter.currentText()
        
        try:
            # --- PONTO CRÍTICO DA SOLUÇÃO AUTOMÁTICA ---
            # 1. Bloqueia os sinais ANTES de qualquer modificação na tabela.
            #    Isso impede que o 'cellChanged' seja emitido durante o recarregamento.
            self.table.blockSignals(True)
            
            self.table.setSortingEnabled(False)
            self.table.clearSelection()
            self.table.setRowCount(0)
            
            self.table.setUpdatesEnabled(False)
            
            conditions = ["ld.rn = 1"]
            params = []
            
            if current_olt_filter_text != "Todas as OLTs" and "Erro" not in current_olt_filter_text:
                olt_id_filter = current_olt_filter_text.split()[-1]
                conditions.append("ld.olt_identifier = %s")
                params.append(olt_id_filter)
                
            if filter_field and filter_value:
                field_map = {
                    "FSP": "ld.fsp LIKE %s",
                    "MAC": "ld.mac_address ILIKE %s",
                    "S/N": "ld.serial_number ILIKE %s",
                    "Status": "ld.status ILIKE %s",
                    "CLIENTE": "ld.client_name ILIKE %s",
                    "Primária": "ld.primaria ILIKE %s",
                    "Secundária": "ld.secundaria ILIKE %s"
                }
                if filter_field in field_map:
                    conditions.append(field_map[filter_field])
                    params.append(f"%{filter_value}%")
                elif filter_field == "Sinal RX":
                    if "Bom" in filter_value: 
                        conditions.append("ld.rx_power >= -22.0")
                    elif "Alerta" in filter_value: 
                        conditions.append("ld.rx_power < -22.0 AND ld.rx_power >= -25.0")
                    elif "Crítico" in filter_value: 
                        conditions.append("ld.rx_power < -25.0")
                        
            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            
            query = f"""
                WITH latest_records AS (
                    SELECT *, ROW_NUMBER() OVER(PARTITION BY serial_number, olt_identifier ORDER BY collection_time DESC) as rn
                    FROM ont_data
                )
                SELECT
                    ld.id, ld.olt_identifier, ld.collection_time, ld.fsp, ld.ont_id, ld.mac_address, ld.serial_number,
                    ld.client_name, ld.rx_power, ld.tx_power, ld.status, ld.primaria, ld.secundaria, ld.porta_secundaria,
                    ld.description, ld.connection_code,
                    CASE WHEN ld.fsp_changed OR ld.ont_id_changed OR ld.previous_mac_address IS NOT NULL THEN 'Sim' ELSE 'Não' END as has_changes
                FROM latest_records ld {where_clause}
                ORDER BY ld.olt_identifier, ld.fsp, ld.ont_id;
            """
            
            self.cursor.execute(query, tuple(params))
            data_for_table = self.cursor.fetchall()
            
            expected_columns = 17
            headers = [
                "ID", "OLT", "Hora", "F/S/P", "ONT ID", "MAC", "S/N", "CLIENTE", 
                "RX (dBm)", "TX (dBm)", "Status", "Primária", "Secundária", "Porta Sec.", 
                "Descrição OLT", "Cod.", "Mudanças"
            ]
            
            self.table.setColumnCount(expected_columns)
            self.table.setHorizontalHeaderLabels(headers)
            
            self.table.setRowCount(len(data_for_table))
            
            for row_idx, row_data in enumerate(data_for_table):
                row_data = list(row_data)
                while len(row_data) < expected_columns:
                    row_data.append(None)
                
                for col_idx, col_data in enumerate(row_data):
                    item = QTableWidgetItem(str(col_data) if col_data is not None else "")
                    header_text = headers[col_idx]
                    
                    if header_text == "Status" and "online" in item.text().lower():
                        item.setBackground(QtGui.QColor(144, 238, 144))
                    elif header_text == "Status" and "offline" in item.text().lower():
                        item.setBackground(QtGui.QColor(255, 153, 153))
                    elif header_text == "RX (dBm)":
                        try:
                            rx_val = float(col_data)
                            if rx_val >= -22.0: item.setBackground(QtGui.QColor(144, 238, 144))
                            elif -25.0 <= rx_val < -22.0: item.setBackground(QtGui.QColor(255, 255, 153))
                            else: item.setBackground(QtGui.QColor(255, 153, 153))
                        except (ValueError, TypeError): pass
                    
                    if header_text != "CLIENTE":
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    
                    self.table.setItem(row_idx, col_idx, item)
            
            self.table.resizeColumnsToContents()
            
        except psycopg2.Error as e:
            self.conn.rollback()
            QMessageBox.critical(self, "Erro de Banco de Dados", f"Ocorreu um erro ao carregar os dados das ONTs:\n{str(e)}")
            logging.error("Erro ao carregar dados das ONTs", exc_info=True)
        except Exception as e:
            QMessageBox.critical(self, "Erro ao Carregar Dados", f"Ocorreu um erro ao carregar os dados das ONTs:\n{str(e)}")
            logging.error("Erro ao carregar dados das ONTs", exc_info=True)
        finally:
            if hasattr(self, 'table'):
                self.table.setUpdatesEnabled(True)
                self.table.setSortingEnabled(True)
                # --- PONTO CRÍTICO DA SOLUÇÃO AUTOMÁTICA ---
                # 2. Religa os sinais APÓS a tabela estar completamente preenchida.
                #    Agora, o 'cellChanged' só será disparado por edições manuais do usuário.
                self.table.blockSignals(False)

    def verify_database_schema(self):
        """Verifica se todas as colunas necessárias existem no banco"""
        required_columns = [
            'id', 'olt_identifier', 'collection_time', 'fsp', 'ont_id', 
            'mac_address', 'serial_number', 'client_name', 'rx_power', 'tx_power',
            'status', 'primaria', 'secundaria', 'porta_secundaria', 'description',
            'connection_code', 'fsp_changed', 'ont_id_changed', 'previous_mac_address'
        ]
        
        try:
            self.cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'ont_data'
            """)
            existing_columns = [row[0] for row in self.cursor.fetchall()]
            
            missing_columns = set(required_columns) - set(existing_columns)
            if missing_columns:
                logging.error(f"Colunas faltando no banco: {missing_columns}")
                return False
            return True
        except Exception as e:
            logging.error(f"Erro ao verificar schema: {e}")
            return False


    def update_pon_status_and_alarms(self):
        """Atualiza o status agregado das PONs e força o recarregamento dos dados para atualizar alarmes."""
        logging.debug("Timer `update_pon_status_and_alarms` (status_timer) disparado para atualizar status e alarmes.")
        self.update_pon_status_display()

        current_filter_field = self.filter_field.currentText()
        current_filter_value = ""
        if self.filter_field.isVisible():
            if current_filter_field == "Descrição" and self.desc_filter.isVisible():
                current_filter_value = self.desc_filter.currentText()
            elif current_filter_field == "Sinal RX" and self.signal_filter_options.isVisible():
                current_filter_value = self.signal_filter_options.currentText()
            elif self.filter_value.isVisible():
                current_filter_value = self.filter_value.text().strip()

        self.load_data(
            filter_field=current_filter_field if current_filter_field != "Todos" else None,
            filter_value=current_filter_value
        )
    def update_pon_status_display(self):
        """Atualiza o painel de status com informações agregadas de todas as PONs."""
        try:
            olt_filter_from_combo = self.olt_filter.currentText()
            olt_condition = ""
            params = []
            if olt_filter_from_combo != "Todas as OLTs" and olt_filter_from_combo != "Erro ao carregar OLTs":
                try:
                    olt_num = olt_filter_from_combo.split()[-1]
                    olt_condition = f"WHERE latest_pon.olt_identifier = %s"
                    params.append(olt_num)
                except IndexError:
                    logging.warning(f"Formato de OLT inválido para filtro de status PON: {olt_filter_from_combo}")

            query = f"""
                WITH latest_pon_records AS (
                    SELECT DISTINCT ON (fsp, olt_identifier)
                           olt_identifier, online_count, total_count
                    FROM pon_status
                    ORDER BY fsp, olt_identifier, collection_time DESC
                )
                SELECT
                    SUM(latest_pon.online_count) as online_sum,
                    SUM(latest_pon.total_count) as total_sum
                FROM latest_pon_records latest_pon
                {olt_condition};
            """
            self.cursor.execute(query, tuple(params))
            result = self.cursor.fetchone()

            if result and result[0] is not None and result[1] is not None:
                online_sum, total_sum = result[0], result[1]
                offline_sum = total_sum - online_sum
                percent = (online_sum / total_sum * 100) if total_sum > 0 else 0

                display_olt_filter = olt_filter_from_combo if olt_filter_from_combo != "Todas as OLTs" else "Global"
                self.olt_status_label.setText(f"OLT: {display_olt_filter}")
                self.total_onts_label.setText(f"Total ONTs (PONs): {total_sum}")
                self.online_onts_label.setText(f"Online (PONs): {online_sum}")
                self.offline_onts_label.setText(f"Offline (PONs): {offline_sum}")
                self.percent_label.setText(f"Disponibilidade: {percent:.1f}%")

                color = QtGui.QColor(200,200,200)
                if total_sum > 0:
                    if percent >= 90: color = QtGui.QColor(144, 238, 144)
                    elif percent >= 70: color = QtGui.QColor(255, 255, 153)
                    else: color = QtGui.QColor(255, 153, 153)
                self.percent_label.setStyleSheet(f"background-color: {color.name()}; padding: 3px; border-radius: 3px;")
            else:
                display_olt_filter = olt_filter_from_combo if olt_filter_from_combo != "Todas as OLTs" else "Global"
                self.olt_status_label.setText(f"OLT: {display_olt_filter}")
                self.total_onts_label.setText("Total ONTs (PONs): 0")
                self.online_onts_label.setText("Online (PONs): 0")
                self.offline_onts_label.setText("Offline (PONs): 0")
                self.percent_label.setText("Disponibilidade: N/A")
                self.percent_label.setStyleSheet("background-color: Gainsboro; padding: 3px; border-radius: 3px;")

        except Exception as e:
            logging.error(f"Erro ao atualizar status agregado da PON: {str(e)}", exc_info=True)
            self.total_onts_label.setText("Total ONTs (PONs): Erro")
            self.online_onts_label.setText("Online (PONs): Erro")

    def load_olt_list(self):
        """Carrega a lista de OLTs disponíveis do banco para os ComboBoxes de filtro."""
        try:
            self.cursor.execute("SELECT DISTINCT olt_identifier FROM ont_data WHERE olt_identifier IS NOT NULL ORDER BY olt_identifier")
            olts = self.cursor.fetchall()

            for combo_box in self.olt_filters_to_update:
                if combo_box is None: continue

                current_selection = combo_box.currentText()
                combo_box.blockSignals(True)
                combo_box.clear()
                combo_box.addItem("Todas as OLTs")
                for olt in olts:
                    combo_box.addItem(f"OLT {olt[0]}")

                index = combo_box.findText(current_selection)
                if index != -1:
                    combo_box.setCurrentIndex(index)
                else:
                    combo_box.setCurrentIndex(0)
                combo_box.blockSignals(False)

        except Exception as e:
            logging.error(f"Erro ao carregar lista de OLTs para filtros: {str(e)}")
            for combo_box in self.olt_filters_to_update:
                if combo_box:
                    combo_box.clear(); combo_box.addItem("Erro ao carregar OLTs")

    def show_history(self):
        """Exibe o histórico de uma ONT selecionada em uma nova janela de diálogo."""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "Aviso", "Por favor, selecione uma ONT na tabela para ver o histórico.")
            return

        selected_row_index = selected_rows[0].row()

        try:
            headers = [self.table.horizontalHeaderItem(c).text() for c in range(self.table.columnCount())]
            sn_col_index = headers.index("S/N")
        except ValueError:
            QMessageBox.critical(self, "Erro de Configuração", "A coluna 'S/N' não foi encontrada na tabela principal.")
            return

        serial_number_item = self.table.item(selected_row_index, sn_col_index)
        if not serial_number_item:
            QMessageBox.warning(self, "Aviso", "Não foi possível obter o S/N da ONT selecionada.")
            return
        serial_number = serial_number_item.text()

        history_dialog = QDialog(self)
        history_dialog.setWindowTitle(f"Histórico da ONT {serial_number}")
        history_dialog.setGeometry(200, 200, 1100, 600)
        layout = QVBoxLayout(history_dialog)

        table_history = QTableWidget()
        history_headers = [
            "Hora", "OLT", "F/S/P", "ONT ID", "MAC", "S/N", "CLIENTE", "RX (dBm)",
            "TX (dBm)", "Status", "Descrição", "FSP Anterior", "ONT ID Anterior"
        ]
        table_history.setColumnCount(len(history_headers))
        table_history.setHorizontalHeaderLabels(history_headers)
        table_history.setSortingEnabled(True)
        table_history.setEditTriggers(QTableWidget.NoEditTriggers)

        try:
            self.cursor.execute("""
                SELECT collection_time, olt_identifier, fsp, ont_id, mac_address, serial_number, client_name,
                       rx_power, tx_power, status, description,
                       previous_fsp, previous_ont_id
                FROM ont_data
                WHERE serial_number = %s
                ORDER BY collection_time DESC
                LIMIT 500
            """, (serial_number,))
            history_data = self.cursor.fetchall()

            table_history.setRowCount(len(history_data))
            for row_idx, row_data_tuple in enumerate(history_data):
                for col_idx, col_data_val in enumerate(row_data_tuple):
                    item_text = str(col_data_val) if col_data_val is not None else ""
                    item = QTableWidgetItem(item_text)
                    table_history.setItem(row_idx, col_idx, item)

            table_history.resizeColumnsToContents()
        except Exception as e:
            QMessageBox.critical(history_dialog, "Erro ao Carregar Histórico", f"Não foi possível carregar o histórico da ONT:\n{str(e)}")

        layout.addWidget(table_history)
        history_dialog.exec_()
		
    def show_ont_details(self, index):
        """
        Exibe todos os detalhes de um registro específico da ONT em uma nova janela,
        incluindo os novos campos de diagnóstico com nomes amigáveis.
        """
        row = index.row()
        db_id_item = self.table.item(row, 0)
        if not db_id_item:
            QMessageBox.warning(self, "Aviso", "Não foi possível obter o ID do registro da ONT.")
            return

        db_id_str = db_id_item.text()
        try:
            db_id = int(db_id_str)
        except ValueError:
            QMessageBox.critical(self, "Erro de ID", f"O ID do registro '{db_id_str}' não é válido.")
            return

        details_dialog = QDialog(self)
        details_dialog.setWindowTitle(f"Detalhes do Registro ONT (ID BD: {db_id})")
        details_dialog.setGeometry(200, 200, 800, 700) # Aumentado para mais detalhes
        layout_main_dialog = QVBoxLayout(details_dialog)

        try:
            self.cursor.execute("SELECT * FROM ont_data WHERE id = %s", (db_id,))
            ont_data_tuple = self.cursor.fetchone()

            if ont_data_tuple:
                column_names = [desc[0] for desc in self.cursor.description]
                ont_data_dict = dict(zip(column_names, ont_data_tuple))

                # Mapeamento de nomes de colunas do BD para nomes amigáveis na GUI
                friendly_names_map = {
                    'ont_distance': 'Distância até a central',
                    'memory_occupation': 'Uso de memória',
                    'cpu_occupation': 'Uso do processador',
                    'temperature': 'Temperatura interna',
                    'ont_ip_address': 'Endereço IP da ONT',
                    'line_profile_id': 'Código do perfil',
                    'line_profile_name': 'Nome do perfil',
                    'service_profile_name': 'Perfil de serviço',
                    'last_down_cause': 'Última Causa da Queda',
                    'last_up_time': 'Última Vez Online',
                    'last_down_time': 'Última Vez Offline',
                    'last_dying_gasp_time': 'Último Dying Gasp'
                }

                details_tab_widget = QTabWidget()
                layout_main_dialog.addWidget(details_tab_widget)

                # --- Aba 1: Detalhes de Diagnóstico (com nomes amigáveis) ---
                diag_details_widget = QWidget()
                diag_layout = QFormLayout(diag_details_widget)
                
                # Adiciona os campos com nomes amigáveis em uma ordem específica
                for key, friendly_name in friendly_names_map.items():
                    value = ont_data_dict.get(key)
                    display_value = str(value) if value is not None else "N/A"
                    
                    # Adiciona unidades para clareza
                    if key == 'ont_distance' and display_value != "N/A":
                        display_value += " m"
                    elif key == 'temperature' and display_value != "N/A":
                        display_value += " °C"

                    diag_layout.addRow(QLabel(f"<b>{friendly_name}:</b>"), QLabel(display_value))

                details_tab_widget.addTab(diag_details_widget, "Detalhes de Diagnóstico")

                # --- Aba 2: Informações Gerais (Todos os dados brutos) ---
                general_info_widget = QWidget()
                form_layout_general = QFormLayout()
                
                for col_name, value in ont_data_dict.items():
                    if col_name == 'services': continue # Pula a coluna de serviços aqui
                    
                    display_col_name = col_name.replace('_', ' ').title()
                    display_value = str(value) if value is not None else "N/A"
                    form_layout_general.addRow(QLabel(f"<b>{display_col_name}:</b>"), QLabel(display_value))

                scroll_area_general = QScrollArea()
                scroll_area_general.setWidgetResizable(True)
                scroll_content_general = QWidget()
                scroll_content_general.setLayout(form_layout_general)
                scroll_area_general.setWidget(scroll_content_general)
                
                general_info_layout = QVBoxLayout(general_info_widget)
                general_info_layout.addWidget(scroll_area_general)
                
                details_tab_widget.addTab(general_info_widget, "Todos os Dados")

                # --- Aba 3: Serviços (VLANs) ---
                services_widget = QWidget()
                services_layout = QVBoxLayout(services_widget)
                
                services_data = ont_data_dict.get('services')
                services_list = []

                if isinstance(services_data, list):
                    services_list = services_data
                elif isinstance(services_data, str):
                    try:
                        services_list = json.loads(services_data)
                    except json.JSONDecodeError:
                        logging.error(f"Erro ao decodificar JSON de serviços para o registro ID {db_id}")
                        services_list = []
                
                if services_list:
                    services_table = QTableWidget()
                    services_table.setColumnCount(4)
                    services_table.setHorizontalHeaderLabels(["Tipo", "Porta ID", "Tipo de Serviço", "VLAN ID"])
                    services_table.setRowCount(len(services_list))
                    
                    for i, service in enumerate(services_list):
                        services_table.setItem(i, 0, QTableWidgetItem(service.get('type', 'N/A')))
                        services_table.setItem(i, 1, QTableWidgetItem(str(service.get('port_id', 'N/A'))))
                        services_table.setItem(i, 2, QTableWidgetItem(service.get('service_type', 'N/A')))
                        services_table.setItem(i, 3, QTableWidgetItem(str(service.get('vlan_id', 'N/A'))))
                    
                    services_table.resizeColumnsToContents()
                    services_layout.addWidget(services_table)
                else:
                    services_layout.addWidget(QLabel("Nenhum serviço (VLAN) registrado para esta ONT."))
                
                details_tab_widget.addTab(services_widget, "Serviços e VLANs")

            else:
                layout_main_dialog.addWidget(QLabel(f"Não foram encontrados detalhes para o registro com ID {db_id}."))

        except Exception as e:
            QMessageBox.critical(details_dialog, "Erro ao Carregar Detalhes", f"Não foi possível carregar os detalhes do registro:\n{str(e)}")
            logging.error(f"Erro em show_ont_details para o registro ID {db_id}", exc_info=True)

        details_dialog.exec_()
        
    def export_to_csv(self):
        """Exporta os dados atualmente exibidos na tabela principal para um arquivo CSV."""
        if self.table.rowCount() == 0:
            QMessageBox.information(self, "Nada para Exportar", "A tabela está vazia. Não há dados para exportar.")
            return

        try:
            default_filename = f"export_olt_dados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            filename, _ = QFileDialog.getSaveFileName(self, "Salvar Exportação CSV", default_filename,
                                                      "Arquivos CSV (*.csv);;Todos os Arquivos (*)")
            if not filename: return

            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f, delimiter=';')
                header = [self.table.horizontalHeaderItem(col).text() for col in range(self.table.columnCount())]
                writer.writerow(header)
                for row in range(self.table.rowCount()):
                    row_data = [self.table.item(row, col).text() if self.table.item(row, col) else ""
                                for col in range(self.table.columnCount())]
                    writer.writerow(row_data)
            QMessageBox.information(self, "Exportação Concluída", f"Dados exportados com sucesso para:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "Erro de Exportação", f"Ocorreu um erro ao exportar os dados para CSV:\n{str(e)}")
            logging.error(f"Erro ao exportar CSV: {e}", exc_info=True)
                
    def export_long_offline_to_csv(self):
        """Exporta os dados da tabela de ONTs com longa inatividade para um arquivo CSV."""
        if self.long_offline_onts_table.rowCount() == 0:
            QMessageBox.information(self, "Nada para Exportar", "A tabela de ONTs inativas está vazia.")
            return

        try:
            default_filename = f"export_onts_inativas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            filename, _ = QFileDialog.getSaveFileName(self, "Salvar Exportação CSV", default_filename,
                                                    "Arquivos CSV (*.csv);;Todos os Arquivos (*)")
            if not filename:
                return

            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f, delimiter=';')
                header = [self.long_offline_onts_table.horizontalHeaderItem(col).text() for col in range(self.long_offline_onts_table.columnCount())]
                writer.writerow(header)
                for row in range(self.long_offline_onts_table.rowCount()):
                    row_data = [self.long_offline_onts_table.item(row, col).text() if self.long_offline_onts_table.item(row, col) else ""
                                for col in range(self.long_offline_onts_table.columnCount())]
                    writer.writerow(row_data)
            QMessageBox.information(self, "Exportação Concluída", f"Dados exportados com sucesso para:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "Erro de Exportação", f"Ocorreu um erro ao exportar os dados para CSV:\n{str(e)}")
            logging.error(f"Erro ao exportar CSV de ONTs inativas: {e}", exc_info=True)

    def show_cleanup_dialog(self):
        """Exibe o diálogo para limpeza de dados históricos do banco."""
        dialog = CleanupDialog(self)
        dialog.exec_()

    def verify_database_entries(self): # Para aba Temperatura
        """Exibe um resumo das entradas de monitoramento de temperatura no banco."""
        try:
            olt_filter_text = self.olt_filter.currentText()
            olt_condition = ""
            params = []
            if olt_filter_text != "Todas as OLTs" and olt_filter_text != "Erro ao carregar OLTs":
                olt_num = olt_filter_text.split()[-1]
                olt_condition = "WHERE olt_identifier = %s"
                params.append(olt_num)

            query = f"""SELECT slot_id, COUNT(*) as total_entries,
                               MAX(collection_time) as last_entry,
                               MIN(temperature_c) as min_temp, MAX(temperature_c) as max_temp
                         FROM temperature_monitoring {olt_condition}
                         GROUP BY slot_id ORDER BY slot_id"""
            self.cursor.execute(query, tuple(params))
            results = self.cursor.fetchall()

            dialog = QDialog(self)
            dialog.setWindowTitle("Verificação do Banco de Dados (Temperatura)")
            dialog.setGeometry(400, 300, 800, 500)
            layout = QVBoxLayout()
            table_verify = QTableWidget()
            table_verify.setColumnCount(5)
            table_verify.setHorizontalHeaderLabels(["Slot", "Total de Registros", "Última Leitura", "Temp Mín (°C)", "Temp Máx (°C)"])
            table_verify.setRowCount(len(results))
            table_verify.setEditTriggers(QTableWidget.NoEditTriggers)

            for row_idx, (slot, count, last_time, min_temp, max_temp) in enumerate(results):
                table_verify.setItem(row_idx, 0, QTableWidgetItem(str(slot)))
                table_verify.setItem(row_idx, 1, QTableWidgetItem(str(count)))
                table_verify.setItem(row_idx, 2, QTableWidgetItem(str(last_time.strftime('%Y-%m-%d %H:%M:%S')) if last_time else "N/A"))
                table_verify.setItem(row_idx, 3, QTableWidgetItem(f"{min_temp:.1f}" if min_temp is not None else "N/A"))
                table_verify.setItem(row_idx, 4, QTableWidgetItem(f"{max_temp:.1f}" if max_temp is not None else "N/A"))
            table_verify.resizeColumnsToContents()
            layout.addWidget(table_verify)
            dialog.setLayout(layout)
            dialog.exec_()
        except Exception as e:
            QMessageBox.critical(self, "Erro na Verificação", f"A verificação de dados de temperatura falhou:\n{str(e)}")

    def verify_resource_entries(self): # Para aba Recursos
        """Exibe um resumo das entradas de monitoramento de recursos no banco."""
        try:
            olt_filter_text = self.olt_filter.currentText()
            olt_condition = ""
            params = []
            if olt_filter_text != "Todas as OLTs" and olt_filter_text != "Erro ao carregar OLTs":
                olt_num = olt_filter_text.split()[-1]
                olt_condition = "WHERE olt_identifier = %s"
                params.append(olt_num)

            query = f"""SELECT slot_id, resource_type, COUNT(*) as total_entries,
                               MAX(collection_time) as last_entry,
                               MIN(usage_percentage) as min_usage, MAX(usage_percentage) as max_usage
                         FROM resource_monitoring {olt_condition}
                         GROUP BY slot_id, resource_type ORDER BY slot_id, resource_type"""
            self.cursor.execute(query, tuple(params))
            results = self.cursor.fetchall()

            dialog = QDialog(self)
            dialog.setWindowTitle("Verificação do Banco de Dados (Recursos)")
            dialog.setGeometry(400, 300, 800, 500)
            layout = QVBoxLayout()
            table_verify_res = QTableWidget()
            table_verify_res.setColumnCount(6)
            table_verify_res.setHorizontalHeaderLabels(["Slot", "Tipo Recurso", "Total Registros", "Última Leitura", "Uso Mín (%)", "Uso Máx (%)"])
            table_verify_res.setRowCount(len(results))
            table_verify_res.setEditTriggers(QTableWidget.NoEditTriggers)

            for row_idx, (slot, rtype, count, last_time, min_usage, max_usage) in enumerate(results):
                table_verify_res.setItem(row_idx, 0, QTableWidgetItem(str(slot)))
                table_verify_res.setItem(row_idx, 1, QTableWidgetItem(rtype))
                table_verify_res.setItem(row_idx, 2, QTableWidgetItem(str(count)))
                table_verify_res.setItem(row_idx, 3, QTableWidgetItem(str(last_time.strftime('%Y-%m-%d %H:%M:%S')) if last_time else "N/A"))
                table_verify_res.setItem(row_idx, 4, QTableWidgetItem(f"{min_usage:.1f}" if min_usage is not None else "N/A"))
                table_verify_res.setItem(row_idx, 5, QTableWidgetItem(f"{max_usage:.1f}" if max_usage is not None else "N/A"))
            table_verify_res.resizeColumnsToContents()
            layout.addWidget(table_verify_res)
            dialog.setLayout(layout)
            dialog.exec_()
        except Exception as e:
            QMessageBox.critical(self, "Erro na Verificação", f"A verificação de dados de recursos falhou:\n{str(e)}")

    def update_temperature_display(self):
        """Atualiza a tabela de exibição de temperatura com os dados mais recentes do banco."""
        try:
            olt_filter_text = self.olt_filter.currentText()
            olt_condition = ""
            params = []
            if olt_filter_text != "Todas as OLTs" and olt_filter_text != "Erro ao carregar OLTs":
                olt_num = olt_filter_text.split()[-1]
                olt_condition = "WHERE tm.olt_identifier = %s"
                params.append(olt_num)

            query = f"""
                SELECT tm.slot_id, tm.board_name, tm.temperature_c, tm.temperature_f, tm.status
                FROM (
                    SELECT DISTINCT ON (slot_id, olt_identifier) * FROM temperature_monitoring
                    ORDER BY slot_id, olt_identifier, collection_time DESC
                ) tm
                {olt_condition} ORDER BY tm.slot_id;
            """
            self.cursor.execute(query, tuple(params))
            temp_data = self.cursor.fetchall()

            self.temp_table.setSortingEnabled(False)
            self.temp_table.setRowCount(len(temp_data))
            for row_idx, (slot_id, board_name, temp_c, temp_f, status_val) in enumerate(temp_data):
                items = [ QTableWidgetItem(str(slot_id)),
                          QTableWidgetItem(board_name if board_name else "N/A"),
                          QTableWidgetItem(f"{temp_c:.1f}" if temp_c is not None else "N/A"),
                          QTableWidgetItem(f"{temp_f:.1f}" if temp_f is not None else "N/A"),
                          QTableWidgetItem(status_val if status_val else "N/A") ]

                color = QtGui.QColor(220, 220, 220)
                if status_val == "normal": color = QtGui.QColor(144, 238, 144)
                elif status_val == "critical": color = QtGui.QColor(255, 153, 153)
                elif status_val == "warning": color = QtGui.QColor(255, 255, 153)

                for item in items: item.setBackground(color)
                for col_idx, item in enumerate(items): self.temp_table.setItem(row_idx, col_idx, item)

            self.temp_table.resizeColumnsToContents()
            self.temp_table.setSortingEnabled(True)
        except Exception as e: logging.error(f"Erro ao atualizar display de temperatura: {str(e)}", exc_info=True)

    def update_temp_display_with_data(self, temp_data_list):
        """Atualiza a tabela de temperatura com dados recebidos via sinal (da thread de coleta)."""
        try:
            self.temp_table.setSortingEnabled(False)
            self.temp_table.setRowCount(len(temp_data_list))
            for row_idx, data_dict in enumerate(temp_data_list):
                items = [ QTableWidgetItem(str(data_dict['slot_id'])),
                          QTableWidgetItem(data_dict.get('board_name', 'N/A')),
                          QTableWidgetItem(f"{data_dict.get('temp_c', 0.0):.1f}"),
                          QTableWidgetItem(f"{data_dict.get('temp_f', 0.0):.1f}"),
                          QTableWidgetItem(data_dict.get('status', 'N/A')) ]
                color = QtGui.QColor(220, 220, 220)
                status_val = data_dict.get('status')
                if status_val == "normal": color = QtGui.QColor(144, 238, 144)
                elif status_val == "critical": color = QtGui.QColor(255, 153, 153)
                elif status_val == "warning": color = QtGui.QColor(255, 255, 153)
                for item in items: item.setBackground(color)
                for col_idx, item in enumerate(items): self.temp_table.setItem(row_idx, col_idx, item)
            self.temp_table.resizeColumnsToContents()
            self.temp_table.setSortingEnabled(True)
        except Exception as e: logging.error(f"Erro ao atualizar tabela de temperatura com dados do sinal: {str(e)}", exc_info=True)

    def update_resource_display(self):
        """Atualiza a tabela de exibição de recursos com os dados mais recentes do banco."""
        try:
            olt_filter_text = self.olt_filter.currentText()
            olt_condition = ""
            params = []
            if olt_filter_text != "Todas as OLTs" and olt_filter_text != "Erro ao carregar OLTs":
                olt_num = olt_filter_text.split()[-1]
                olt_condition = "WHERE rm.olt_identifier = %s"
                params.append(olt_num)

            query = f"""
                SELECT rm.slot_id, rm.board_name, rm.resource_type, rm.usage_percentage, rm.status
                FROM (
                    SELECT DISTINCT ON (slot_id, resource_type, olt_identifier) * FROM resource_monitoring
                    ORDER BY slot_id, resource_type, olt_identifier, collection_time DESC
                ) rm
                {olt_condition} ORDER BY rm.slot_id, rm.resource_type;
            """
            self.cursor.execute(query, tuple(params))
            resource_data = self.cursor.fetchall()

            self.resource_table.setSortingEnabled(False)
            self.resource_table.setRowCount(len(resource_data))
            for row_idx, (slot_id, board_name, rtype, usage, status_val) in enumerate(resource_data):
                items = [ QTableWidgetItem(str(slot_id)),
                          QTableWidgetItem(board_name if board_name else "N/A"),
                          QTableWidgetItem(rtype if rtype else "N/A"),
                          QTableWidgetItem(f"{usage:.1f}%" if usage is not None else "N/A"),
                          QTableWidgetItem(status_val if status_val else "N/A") ]
                color = QtGui.QColor(220,220,220)
                if status_val == "normal": color = QtGui.QColor(144, 238, 144)
                elif status_val == "critical": color = QtGui.QColor(255, 153, 153)
                elif status_val == "warning": color = QtGui.QColor(255, 255, 153)
                for item in items: item.setBackground(color)
                for col_idx, item in enumerate(items): self.resource_table.setItem(row_idx, col_idx, item)
            self.resource_table.resizeColumnsToContents()
            self.resource_table.setSortingEnabled(True)
        except Exception as e: logging.error(f"Erro ao atualizar display de recursos: {str(e)}", exc_info=True)

    def update_resource_display_with_data(self, resource_data_list):
        """Atualiza a tabela de recursos com dados recebidos via sinal (da thread de coleta)."""
        try:
            self.resource_table.setSortingEnabled(False)
            self.resource_table.setRowCount(len(resource_data_list))
            for row_idx, data_dict in enumerate(resource_data_list):
                items = [ QTableWidgetItem(str(data_dict['slot'])),
                          QTableWidgetItem(data_dict.get('board_name', 'N/A')),
                          QTableWidgetItem(data_dict.get('type', 'N/A')),
                          QTableWidgetItem(f"{data_dict.get('usage', 0.0):.1f}%"),
                          QTableWidgetItem(data_dict.get('status', 'N/A')) ]
                color = QtGui.QColor(220,220,220)
                status_val = data_dict.get('status')
                if status_val == "normal": color = QtGui.QColor(144, 238, 144)
                elif status_val == "critical": color = QtGui.QColor(255, 153, 153)
                elif status_val == "warning": color = QtGui.QColor(255, 255, 153)
                for item in items: item.setBackground(color)
                for col_idx, item in enumerate(items): self.resource_table.setItem(row_idx, col_idx, item)
            self.resource_table.resizeColumnsToContents()
            self.resource_table.setSortingEnabled(True)
        except Exception as e: logging.error(f"Erro ao atualizar tabela de recursos com dados do sinal: {str(e)}", exc_info=True)


# Em olt_monitoring_system/gui/main_window.py

    def start_collection(self):
        """Inicia a coleta de dados da OLT em uma thread separada."""
        if not self.olt_ip or not self.username or not self.password:
            QMessageBox.warning(self, "Credenciais da OLT Faltando", "IP da OLT, nome de usuário ou senha não foram fornecidos.\nNão é possível iniciar a coleta.")
            return
        if self.collection_running:
            QMessageBox.information(self, "Coleta em Andamento", "A coleta de dados da OLT já está em execução.")
            return

        self.ont_cycle_count = 0
        if self.ont_cycle_time_label:
            self.ont_cycle_time_label.setText("Último Ciclo: N/A")

        self.collection_running = True
        self.update_collection_status_indicator()

        self.collection_thread = threading.Thread(target=run_data_collection,
                                                  args=(self.olt_ip, self.username, self.password, self),
                                                  daemon=True)
        self.collection_thread.start()

        self.session_timer.start(self.session_duration_ms)
        logging.info(f"Thread de coleta de dados iniciada para OLT {self.olt_ip}. Sessão expira em {self.session_duration_ms / 60000:.0f} minutos.")

        # --- LINHA ADICIONADA ---
        # Dispara a atualização da aba de estatísticas imediatamente após iniciar a coleta.
        logging.info("Início da coleta disparando atualização das estatísticas por caixa.")
        self.load_caixa_stats_data()

    def start_temp_monitoring(self):
        """Inicia o monitoramento de temperatura da OLT em uma thread separada."""
        if not self.olt_ip or not self.username or not self.password:
            QMessageBox.warning(self, "Credenciais da OLT Faltando", "IP da OLT, usuário ou senha não configurados para monitoramento de temperatura.")
            return
        if self.temp_monitoring_running:
            QMessageBox.information(self, "Monitoramento Ativo", "O monitoramento de temperatura já está em execução.")
            return

        self.temp_monitoring_running = True
        self.update_temp_monitoring_status()
        self.execution_count = 0

        self.temp_thread = threading.Thread(target=run_temp_monitoring,
                                            args=(self.olt_ip, self.username, self.password, self),
                                            daemon=True)
        self.temp_thread.start()
        logging.info(f"Thread de monitoramento de temperatura iniciada para OLT {self.olt_ip}.")

    def stop_temp_monitoring(self):
        """Para o monitoramento de temperatura."""
        if self.temp_monitoring_running:
            self.temp_monitoring_running = False
            logging.info("Sinal de parada enviado para a thread de monitoramento de temperatura.")
        else:
            logging.info("Tentativa de parar monitoramento de temperatura, mas não estava em execução.")
        self.update_temp_monitoring_status()

    def update_temp_monitoring_status(self):
        """Atualiza os botões e rótulos de status do monitoramento de temperatura."""
        if hasattr(self, 'start_temp_btn'): self.start_temp_btn.setEnabled(not self.temp_monitoring_running)
        if hasattr(self, 'stop_temp_btn'): self.stop_temp_btn.setEnabled(self.temp_monitoring_running)

    def show_temp_history(self, index):
        """Exibe o histórico de temperatura de um slot específico em um gráfico."""
        row = index.row()
        try:
            slot_id_item = self.temp_table.item(row, 0)
            board_name_item = self.temp_table.item(row, 1)
            if not slot_id_item:
                QMessageBox.warning(self, "Seleção Inválida", "Não foi possível obter o ID do slot da linha selecionada.")
                return

            slot_id_str = slot_id_item.text()
            try:
                slot_id = int(slot_id_str)
            except ValueError:
                QMessageBox.warning(self, "ID de Slot Inválido", f"O ID do slot '{slot_id_str}' não é um número válido.")
                return

            board_name = board_name_item.text() if board_name_item and board_name_item.text() != "N/A" else ""

            history_dialog = QDialog(self)
            title = f"Histórico de Temperatura - Slot {slot_id}"
            if board_name: title += f" ({board_name})"
            history_dialog.setWindowTitle(title)
            history_dialog.setGeometry(200, 200, 800, 500)
            layout = QVBoxLayout()
            history_dialog.setLayout(layout)

            plot_widget = pg.PlotWidget()
            layout.addWidget(plot_widget)

            olt_identifier_param = None
            current_olt_filter_on_main_tab = self.olt_filter.currentText()
            if current_olt_filter_on_main_tab != "Todas as OLTs" and current_olt_filter_on_main_tab != "Erro ao carregar OLTs":
                try:
                    olt_identifier_param = current_olt_filter_on_main_tab.split()[-1]
                except IndexError:
                    logging.warning(f"Não foi possível extrair ID da OLT para histórico de temp de: {current_olt_filter_on_main_tab}")

            query = "SELECT collection_time, temperature_c FROM temperature_monitoring WHERE slot_id = %s "
            params = [slot_id]
            if olt_identifier_param:
                query += "AND olt_identifier = %s "
                params.append(olt_identifier_param)
            query += "ORDER BY collection_time DESC LIMIT 100"

            self.cursor.execute(query, tuple(params))
            data = self.cursor.fetchall()

            if data:
                times = [datetime.timestamp(row[0]) for row in reversed(data)]
                temps_c = [row[1] for row in reversed(data)]

                plot_widget.plot(times, temps_c, pen='r', symbol='o', symbolBrush='r', name="Temp °C")
                plot_widget.setLabel('left', "Temperatura (°C)")
                plot_widget.setLabel('bottom', "Tempo")
                axis = pg.DateAxisItem(orientation='bottom')
                plot_widget.setAxisItems({'bottom': axis})
                plot_widget.addLegend()
            else:
                layout.addWidget(QLabel(f"Nenhum histórico de temperatura encontrado para Slot {slot_id}" +
                                      (f" na OLT {olt_identifier_param}" if olt_identifier_param else "") + "."))

            history_dialog.exec_()
        except Exception as e:
            QMessageBox.critical(self, "Erro ao Exibir Histórico", f"Ocorreu um erro ao mostrar o histórico de temperatura:\n{str(e)}")
            logging.error(f"Erro ao mostrar histórico de temperatura: {e}", exc_info=True)

    def start_resource_monitoring(self):
        """Inicia o monitoramento de recursos da OLT em uma thread separada."""
        if not self.olt_ip or not self.username or not self.password:
            QMessageBox.warning(self, "Credenciais da OLT Faltando", "IP da OLT, usuário ou senha não configurados para monitoramento de recursos.")
            return
        if self.resource_monitoring_running:
            QMessageBox.information(self, "Monitoramento Ativo", "O monitoramento de recursos já está em execução.")
            return

        self.resource_monitoring_running = True
        self.update_resource_monitoring_status()
        self.resource_execution_count = 0

        self.resource_thread = threading.Thread(target=run_resource_monitoring,
                                                args=(self.olt_ip, self.username, self.password, self),
                                                daemon=True)
        self.resource_thread.start()
        logging.info(f"Thread de monitoramento de recursos iniciada para OLT {self.olt_ip}.")

    def stop_resource_monitoring(self):
        """Para o monitoramento de recursos."""
        if self.resource_monitoring_running:
            self.resource_monitoring_running = False
            logging.info("Sinal de parada enviado para a thread de monitoramento de recursos.")
        else:
            logging.info("Tentativa de parar monitoramento de recursos, mas não estava em execução.")
        self.update_resource_monitoring_status()

    def update_resource_monitoring_status(self):
        """Atualiza os botões e rótulos de status do monitoramento de recursos."""
        is_running = self.resource_monitoring_running
        if hasattr(self, 'start_resource_btn'): self.start_resource_btn.setEnabled(not is_running)
        if hasattr(self, 'stop_resource_btn'): self.stop_resource_btn.setEnabled(is_running)
        if hasattr(self, 'resource_status_label'):
            if is_running:
                self.resource_status_label.setText("Status: Coletando...")
                self.resource_status_label.setStyleSheet("color: orange;")
            else:
                self.resource_status_label.setText(f"Status: Parado")
                self.resource_status_label.setStyleSheet("color: red;")

    def show_ont_diagnostics_history(self):
        if not self.current_diagnosed_ont_info or \
           not self.current_diagnosed_ont_info.get('ont_serial_number'):
            QMessageBox.warning(self, "Informação Incompleta", 
                                "Não há informações suficientes da ONT atual para buscar o histórico.\n"
                                "Acesse uma ONT primeiro.")
            logging.warning("[Histórico Diag] Tentativa de ver histórico sem S/N da ONT em current_diagnosed_ont_info.")
            return

        s_n = self.current_diagnosed_ont_info.get('ont_serial_number')
        olt_id = self.current_diagnosed_ont_info.get('olt_identifier')
        fsp = self.current_diagnosed_ont_info.get('fsp')
        ont_id_pon = self.current_diagnosed_ont_info.get('ont_id_on_pon')

        logging.info(f"Abrindo histórico de diagnóstico para ONT S/N: {s_n}, OLT: {olt_id}")
        
        # Cria e exibe a janela de diálogo do histórico
        history_dialog = OntDiagnosticsHistoryDialog(s_n, olt_id, fsp, ont_id_pon, self)
        history_dialog.exec_()

    def show_resource_history(self, index):
        """Exibe o histórico de uso de um recurso específico (CPU/Memória) em um gráfico."""
        row = index.row()
        try:
            slot_id_item = self.resource_table.item(row, 0)
            board_name_item = self.resource_table.item(row, 1)
            resource_type_item = self.resource_table.item(row, 2)

            if not slot_id_item or not resource_type_item:
                QMessageBox.warning(self, "Seleção Inválida", "Não foi possível obter ID do slot ou tipo de recurso.")
                return

            slot_id_str = slot_id_item.text()
            try:
                slot_id = int(slot_id_str)
            except ValueError:
                QMessageBox.warning(self, "ID de Slot Inválido", f"O ID do slot '{slot_id_str}' não é um número válido.")
                return

            board_name = board_name_item.text() if board_name_item and board_name_item.text() != "N/A" else ""
            resource_type = resource_type_item.text()
            if not resource_type or resource_type == "N/A":
                QMessageBox.warning(self, "Tipo de Recurso Inválido", "Tipo de recurso não especificado.")
                return

            history_dialog = QDialog(self)
            title = f"Histórico {resource_type} - Slot {slot_id}"
            if board_name: title += f" ({board_name})"
            history_dialog.setWindowTitle(title)
            history_dialog.setGeometry(200, 200, 800, 500)
            layout = QVBoxLayout()
            history_dialog.setLayout(layout)

            plot_widget = pg.PlotWidget()
            layout.addWidget(plot_widget)

            olt_identifier_param = None
            current_olt_filter_on_main_tab = self.olt_filter.currentText()
            if current_olt_filter_on_main_tab != "Todas as OLTs" and current_olt_filter_on_main_tab != "Erro ao carregar OLTs":
                try:
                    olt_identifier_param = current_olt_filter_on_main_tab.split()[-1]
                except IndexError:
                    logging.warning(f"Não foi possível extrair ID da OLT para histórico de recurso de: {current_olt_filter_on_main_tab}")

            query = "SELECT collection_time, usage_percentage FROM resource_monitoring WHERE slot_id = %s AND resource_type = %s "
            params = [slot_id, resource_type]
            if olt_identifier_param:
                query += "AND olt_identifier = %s "
                params.append(olt_identifier_param)
            query += "ORDER BY collection_time DESC LIMIT 100"

            self.cursor.execute(query, tuple(params))
            data = self.cursor.fetchall()

            if data:
                times = [datetime.timestamp(row[0]) for row in reversed(data)]
                usages = [row[1] for row in reversed(data)]

                plot_widget.plot(times, usages, pen='b', symbol='x', symbolBrush='b', name=f"{resource_type} Usage")
                plot_widget.setLabel('left', f"Uso {resource_type} (%)")
                plot_widget.setLabel('bottom', "Tempo")
                axis = pg.DateAxisItem(orientation='bottom')
                plot_widget.setAxisItems({'bottom': axis})
                plot_widget.setYRange(0, 100)
                plot_widget.addLegend()
            else:
                layout.addWidget(QLabel(f"Nenhum histórico de {resource_type} encontrado para Slot {slot_id}" +
                                      (f" na OLT {olt_identifier_param}" if olt_identifier_param else "") + "."))

            history_dialog.exec_()
        except Exception as e:
            QMessageBox.critical(self, "Erro ao Exibir Histórico", f"Ocorreu um erro ao mostrar o histórico de recursos:\n{str(e)}")
            logging.error(f"Erro ao mostrar histórico de recursos: {e}", exc_info=True)

    def test_db_connection(self):
        """Testa a conexão com o banco de dados e exibe uma mensagem de status."""
        if check_db_connection():
            QMessageBox.information(self, "Conexão com Banco de Dados", "Conexão com o banco de dados PostgreSQL bem-sucedida!")
        else:
            QMessageBox.critical(self, "Falha na Conexão com Banco de Dados",
                                 "Não foi possível conectar ao banco de dados.\n"
                                 "Verifique as configurações em 'config.py' e se o serviço PostgreSQL está em execução.")

    def safe_update(self):
        """Slot para atualizar a GUI de forma segura (geralmente chamado por sinais de outras threads)."""
        logging.debug("safe_update chamado para recarregar dados e lista de OLTs.")

        current_filter_field = self.filter_field.currentText()
        current_filter_value = ""

        if self.filter_field.isVisible():
            if current_filter_field == "Descrição" and self.desc_filter.isVisible():
                current_filter_value = self.desc_filter.currentText()
            elif current_filter_field == "Sinal RX" and self.signal_filter_options.isVisible():
                current_filter_value = self.signal_filter_options.currentText()
            elif self.filter_value.isVisible():
                current_filter_value = self.filter_value.text().strip()

        self.load_data(
            filter_field=current_filter_field if current_filter_field != "Todos" else None,
            filter_value=current_filter_value
        )
        self.load_olt_list()

        # DENTRO da classe OLTDatabaseGUI em gui/main_window.py
# Em gui/main_window.py, modifique o método closeEvent:

    def closeEvent(self, event: QEvent):
        """Manipula o evento de fechamento da janela principal."""
        logging.info("Fechando a aplicação OLT Monitoring System...")
        
        # Para todos os timers da GUI
        if hasattr(self, 'update_timer'): self.update_timer.stop()
        if hasattr(self, 'status_timer'): self.status_timer.stop()
        if hasattr(self, 'temp_update_timer'): self.temp_update_timer.stop()
        if hasattr(self, 'resource_update_timer'): self.resource_update_timer.stop()
        if hasattr(self, 'caixa_stats_update_timer'): self.caixa_stats_update_timer.stop()
        
        app = QApplication.instance()
        if app: app._app_closing = True
        
        # Para todas as threads de background
        self.stop_all_collections()  # Isso já cuida das threads ETH
        
        self.stop_temp_monitoring()
        self.stop_resource_monitoring()
        
        if self.is_ont_session_active:
            self.disconnect_from_ont() 
        
        threads_to_join = list(self.collection_threads.values())
        
        if hasattr(self, 'temp_thread'): threads_to_join.append(self.temp_thread)
        if hasattr(self, 'resource_thread'): threads_to_join.append(self.resource_thread)
        if hasattr(self, 'ont_connection_thread'): threads_to_join.append(self.ont_connection_thread)
        if hasattr(self, 'ont_command_thread'): threads_to_join.append(self.ont_command_thread)
        
        # Adicionar o worker ETH global à lista de threads para aguardar
        if hasattr(self, 'eth_collection_thread'):
            threads_to_join.append(self.eth_collection_thread)
        
        for thread in threads_to_join:
            if thread and thread.is_alive():
                logging.info(f"Aguardando a thread {thread.name} finalizar...")
                thread.join(timeout=5.0)
                if thread.is_alive():
                    logging.warning(f"A thread {thread.name} não finalizou dentro do tempo esperado.")
            
        if hasattr(self, 'conn') and self.conn:
            try:
                self.conn.close()
                logging.info("Conexão com o banco de dados fechada com sucesso.")
            except Exception as e:
                logging.error(f"Erro ao fechar a conexão com o banco de dados: {e}")
            
        if app and hasattr(app, '_app_closing'):
            delattr(app, '_app_closing')
        event.accept()

    def _connectivity_tests_worker(self, section_id):
        """
        Worker dedicado para a seção "Testes de Conectividade", que executa
        uma série de testes de rede sequencialmente com a sintaxe e pausas corretas.
        """
        log_prefix = f"[ONT CMD {section_id}]"
        logging.info(f"{log_prefix} Iniciando worker dedicado com lista de comandos final...")

        if not self.is_ont_session_active or not self.active_ont_olt_shell:
            db_signals.ont_command_output_received.emit(section_id, "Erro: Sem sessão ativa com a ONT.", True)
            return

        # <<<--- O PROBLEMA ESTÁ AQUI: ESTA LISTA PRECISA SER SUBSTITUÍDA ---<<<
        # A lista abaixo contém a sintaxe CORRETA para todos os comandos,
        # especialmente 'nslookup domain ...'
        tests_to_run = [
            {"type": "Ping para IP (Google)", "cmd": "ping 8.8.8.8 -c 10", "timeout": 25},
            {"type": "Ping para Domínio (Google)", "cmd": "ping www.google.com -c 10", "timeout": 25},
            {"type": "DNS (Provedor 1)", "cmd": "nslookup domain www.google.com server 177.8.195.10", "timeout": 20},
            {"type": "DNS (Provedor 2)", "cmd": "nslookup domain www.google.com server 177.8.200.10", "timeout": 20},
            {"type": "DNS (Google)", "cmd": "nslookup domain www.google.com server 8.8.8.8", "timeout": 20},
            {"type": "DNS (Google Secundário)", "cmd": "nslookup domain www.google.com server 8.8.4.4", "timeout": 20},
            {"type": "DNS (Gateway Padrão)", "cmd": "nslookup domain www.google.com", "timeout": 20},
            {"type": "Traceroute (Google)", "cmd": "traceroute www.google.com", "timeout": 90},
        ]
        
        full_raw_output = ""
        try:
            for i, test in enumerate(tests_to_run):
                # Emite um feedback para a GUI para o usuário saber o que está acontecendo
                QMetaObject.invokeMethod(
                    self.diag_widgets[section_id]["output_area"], 
                    "append", 
                    Qt.QueuedConnection, 
                    Q_ARG(str, f"\nExecutando teste {i+1}/{len(tests_to_run)}: {test['type']}...")
                )
                
                # Executa o comando
                command_output = self._execute_single_ont_command(test['cmd'], timeout=test['timeout'])
                
                # Anexa a saída ao resultado completo
                full_raw_output += f"\n\n--- Start of cmd: {test['cmd']} ---\n"
                full_raw_output += command_output

                # Pausa entre os testes para não sobrecarregar
                if i < len(tests_to_run) - 1:
                    logging.info(f"{log_prefix} Pausando por 15 segundos antes do próximo teste.")
                    time.sleep(15)

            # Envia a saída bruta completa de todos os testes para ser processada
            db_signals.ont_command_output_received.emit(section_id, full_raw_output, False)

        except Exception as e:
            logging.error(f"{log_prefix} Erro no worker de testes de conectividade: {e}", exc_info=True)
            db_signals.ont_command_output_received.emit(section_id, f"Erro ao executar a rotina de testes: {e}", True)

    @pyqtSlot(int, int)
    def _handle_client_name_changed(self, row, column):
        """
        Chamado quando uma célula na tabela é editada. Salva o nome do cliente no banco.
        """
        # Verifica se a coluna editada é a "CLIENTE" (índice 6)
        if self.table.horizontalHeaderItem(column).text() != "CLIENTE":
            return

        # Pega os dados da linha
        client_name_item = self.table.item(row, column)
        serial_number_item = self.table.item(row, 7) # S/N está agora na coluna 7

        if not client_name_item or not serial_number_item:
            logging.warning("Não foi possível salvar o nome do cliente: S/N não encontrado na linha.")
            return

        new_name = client_name_item.text()
        serial_number = serial_number_item.text()

        logging.debug(f"Atualizando nome do cliente para a ONT S/N {serial_number} para '{new_name}'")

        # Executa a atualização do banco em uma thread para não bloquear a GUI
        db_thread = threading.Thread(
            target=self._update_client_name_in_db,
            args=(serial_number, new_name),
            daemon=True
        )
        db_thread.start()

    def _update_client_name_in_db(self, serial_number, new_name):
        """Worker que executa o UPDATE no banco de dados."""
        try:
            # É importante usar uma nova conexão para a thread
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()
            query = "UPDATE ont_data SET client_name = %s WHERE serial_number = %s"
            cursor.execute(query, (new_name, serial_number))
            conn.commit()
            cursor.close()
            conn.close()
            logging.debug(f"Nome do cliente para S/N {serial_number} atualizado com sucesso.")
        except Exception as e:
            logging.error(f"Erro ao atualizar nome do cliente no banco de dados: {e}")

    def import_clients_from_csv(self):
        """Abre um diálogo para o usuário selecionar um arquivo CSV para importar."""
        options = QFileDialog.Options()
        filepath, _ = QFileDialog.getOpenFileName(self, "Importar Clientes de CSV", "", "Arquivos CSV (*.csv);;Todos os Arquivos (*)", options=options)
        if not filepath:
            return

        # Inicia o processamento do arquivo em uma thread separada
        self.import_thread = threading.Thread(
            target=self._import_csv_worker,
            args=(filepath,),
            daemon=True
        )
        self.import_thread.start()
        QMessageBox.information(self, "Importação Iniciada", "A importação dos dados do CSV foi iniciada em segundo plano. Você será notificado ao final.")
            
    def _import_csv_worker(self, filepath):
        """Worker que lê o CSV e atualiza o banco de dados (com tratamento robusto de erros)."""
        logging.info("--- INICIANDO WORKER DE IMPORTAÇÃO (MODO DEBUG) ---")
        logging.info(f"Arquivo selecionado: {filepath}")
        updated_count = 0
        failed_count = 0
        not_found_count = 0
        
        try:
            # FIXED: Handle file access with proper error handling
            try:
                with open(filepath, mode='r', encoding='utf-8-sig', errors='ignore') as infile:
                    # Read the first line for analysis
                    header_line = infile.readline().strip()
                    # FIXED: Remove BOM and handle encoding safely for logging
                    clean_header = header_line.replace('\ufeff', '').replace('\ufeff', '')
                    logging.info(f"Linha de cabeçalho lida do arquivo: '{clean_header}'")
            except PermissionError:
                error_msg = f"Não foi possível acessar o arquivo '{filepath}'. Verifique se o arquivo não está aberto em outro programa (como Excel) e se você tem permissão de leitura."
                logging.error(error_msg)
                # FIXED: Use QTimer.singleShot for thread-safe GUI updates
                QTimer.singleShot(0, lambda: QMessageBox.critical(self, "Erro de Permissão", error_msg))
                return
            except Exception as e:
                error_msg = f"Erro ao abrir o arquivo: {str(e)}"
                logging.error(error_msg)
                QTimer.singleShot(0, lambda: QMessageBox.critical(self, "Erro ao Abrir Arquivo", error_msg))
                return
            
            # Reopen the file with proper encoding
            with open(filepath, mode='r', encoding='utf-8-sig', errors='ignore') as infile:
                # Detecta o delimitador mais provável
                if ';' in header_line:
                    delimiter = ';'
                    logging.info("Delimitador detectado: Ponto e vírgula (;)")
                else:
                    delimiter = ','
                    logging.info("Delimitador provável: Vírgula (,)")
                
                # Volta para o início do arquivo para o leitor CSV
                infile.seek(0)
                reader = csv.reader(infile, delimiter=delimiter)
                header = next(reader)
                # FIXED: Clean BOM from header elements
                header = [col.strip().replace('\ufeff', '') for col in header]
                logging.info(f"Cabeçalho interpretado como lista: {header}")
                
                # Mapeamento das colunas necessárias (baseado no seu CSV)
                column_mapping = {
                    'S/N': None,
                    'CLIENTE': None,
                    'Cód.': None,
                    'OLT': None,
                    'F/S/P': None,
                    'ONT ID': None,
                    'MAC': None
                }
                
                # Encontra os índices das colunas (case-insensitive)
                for idx, col_name in enumerate(header):
                    clean_name = col_name.strip()
                    # Mapeamento alternativo para nomes de colunas
                    if clean_name.upper() == 'S/N':
                        column_mapping['S/N'] = idx
                    elif clean_name.upper() == 'CLIENTE':
                        column_mapping['CLIENTE'] = idx
                    elif clean_name.upper() == 'CÓD.' or clean_name == 'COD.':
                        column_mapping['Cód.'] = idx
                    elif clean_name.upper() == 'OLT':
                        column_mapping['OLT'] = idx
                    elif clean_name.upper() == 'F/S/P':
                        column_mapping['F/S/P'] = idx
                    elif clean_name.upper() == 'ONT ID':
                        column_mapping['ONT ID'] = idx
                    elif clean_name.upper() == 'MAC':
                        column_mapping['MAC'] = idx
                
                # Verifica se as colunas obrigatórias foram encontradas
                required_columns = ['S/N', 'CLIENTE', 'Cód.']
                missing_columns = [col for col in required_columns if column_mapping[col] is None]
                
                if missing_columns:
                    error_msg = f"Colunas obrigatórias não encontradas: {', '.join(missing_columns)}"
                    logging.error(error_msg)
                    QTimer.singleShot(0, lambda: QMessageBox.critical(self, "Erro no Formato do CSV", error_msg))
                    return
                
                sn_index = column_mapping['S/N']
                client_index = column_mapping['CLIENTE']
                code_index = column_mapping['Cód.']
                olt_index = column_mapping['OLT']
                fsp_index = column_mapping['F/S/P']
                ont_id_index = column_mapping['ONT ID']
                mac_index = column_mapping['MAC']
                
                logging.info(f"Índices mapeados: S/N={sn_index}, CLIENTE={client_index}, Cód.={code_index}")
                logging.info(f"Índices opcionais: OLT={olt_index}, F/S/P={fsp_index}, ONT ID={ont_id_index}, MAC={mac_index}")
                
                # Conexão com o banco de dados
                conn = psycopg2.connect(**DB_CONFIG)
                with conn.cursor() as cursor:
                    for i, row in enumerate(reader):
                        # FIXED: Skip empty rows
                        if not row or all(not cell.strip() for cell in row):
                            continue
                            
                        # Verifica se a linha tem colunas suficientes
                        max_needed_index = max(sn_index, client_index, code_index)
                        if len(row) > max_needed_index:
                            serial_number = row[sn_index].strip()
                            client_name = row[client_index].strip()
                            connection_code = row[code_index].strip()
                            
                            # Dados opcionais para melhor matching
                            olt_identifier = row[olt_index].strip() if olt_index is not None and len(row) > olt_index else None
                            fsp = row[fsp_index].strip() if fsp_index is not None and len(row) > fsp_index else None
                            ont_id = row[ont_id_index].strip() if ont_id_index is not None and len(row) > ont_id_index else None
                            mac_address = row[mac_index].strip() if mac_index is not None and len(row) > mac_index else None
                            
                            if serial_number:
                                logging.debug(f"Processando linha {i+2}: S/N={serial_number}, Cliente={client_name}, Cod.={connection_code}")
                                
                                # Constrói a cláusula WHERE com múltiplos critérios para matching mais preciso
                                where_conditions = ["serial_number = %s"]
                                where_params = [serial_number]
                                
                                if olt_identifier:
                                    where_conditions.append("olt_identifier = %s")
                                    where_params.append(olt_identifier.split()[-1])  # Pega só o número
                                
                                if fsp:
                                    where_conditions.append("fsp = %s")
                                    where_params.append(fsp)
                                
                                if ont_id and ont_id.isdigit():
                                    where_conditions.append("ont_id = %s")
                                    where_params.append(int(ont_id))
                                
                                if mac_address and mac_address != '':
                                    where_conditions.append("mac_address = %s")
                                    where_params.append(mac_address)
                                
                                # Atualiza os campos
                                cursor.execute(f"""
                                    UPDATE ont_data 
                                    SET client_name = %s, connection_code = %s 
                                    WHERE {' AND '.join(where_conditions)}
                                    AND (olt_identifier, serial_number, collection_time) IN (
                                        SELECT olt_identifier, serial_number, MAX(collection_time)
                                        FROM ont_data
                                        GROUP BY olt_identifier, serial_number
                                    )
                                """, [client_name if client_name else None, connection_code if connection_code else None] + where_params)
                                
                                if cursor.rowcount > 0:
                                    updated_count += cursor.rowcount
                                    logging.debug(f"ONT {serial_number} atualizada com sucesso")
                                else:
                                    not_found_count += 1
                                    logging.warning(f"ONT {serial_number} não encontrada no banco de dados")
                                    # Log detalhado para depuração
                                    logging.warning(f"  Critérios usados: OLT={olt_identifier}, FSP={fsp}, ONT ID={ont_id}, MAC={mac_address}")
                            else:
                                failed_count += 1
                                logging.warning(f"Linha {i+2} ignorada: S/N vazio")
                
                conn.commit()
                conn.close()
                logging.info(f"Banco de dados atualizado. {updated_count} registros modificados.")
                
        except Exception as e:
            logging.error(f"ERRO CRÍTICO DURANTE A IMPORTAÇÃO: {e}", exc_info=True)
            error_msg = f"Ocorreu um erro durante a importação:\n\n{str(e)}"
            QTimer.singleShot(0, lambda: QMessageBox.critical(self, "Erro na Importação", error_msg))
            return
        
        db_signals.data_updated.emit()
        
        # FIXED: Use QTimer.singleShot for thread-safe GUI updates
        summary_message = f"""Importação concluída!

    📊 Resumo da Importação:
    ✅ Registros atualizados: {updated_count}
    ❌ Falhas: {failed_count}
    🔍 ONTs não encontradas: {not_found_count}

    💡 Informações:
    - Foram processadas apenas as linhas com número de série (S/N) preenchido
    - A atualização foi feita apenas nos registros mais recentes de cada ONT
    - O sistema usou múltiplos critérios (OLT, F/S/P, ONT ID, MAC) para encontrar as ONTs

    📋 Formato do CSV esperado:
    - Delimitador: Ponto e vírgula (;)
    - Colunas obrigatórias: S/N, CLIENTE, Cód.
    - Colunas opcionais usadas para matching: OLT, F/S/P, ONT ID, MAC
    """
        
        QTimer.singleShot(0, lambda: QMessageBox.information(self, "Importação Finalizada", summary_message))

    def shutdown_threads(self):
        """Método chamado ao fechar a janela para garantir que tudo pare."""
        # --- Inicio da Modificação ---
        if self.collection_running:
            self.log_to_gui("Desligando a aplicação, parando todas as threads...")
            self.collection_running = False
        # --- Fim da Modificação ---


    def setup_pon_traffic_tab(self):
        """Configura a interface da aba 'Dados PON'."""
        layout = QVBoxLayout(self.pon_traffic_tab)
        
        # Painel de controle
        control_panel = QWidget()
        control_layout = QHBoxLayout(control_panel)
        
        self.pon_traffic_olt_filter_label = QLabel("Filtrar por OLT:")
        self.pon_traffic_olt_filter = QComboBox()
        if self.pon_traffic_olt_filter not in self.olt_filters_to_update:
            self.olt_filters_to_update.append(self.pon_traffic_olt_filter)
        
        self.pon_traffic_olt_filter.currentTextChanged.connect(self.load_pon_traffic_data)
        
        self.pon_traffic_refresh_btn = QPushButton("Atualizar")
        self.pon_traffic_refresh_btn.clicked.connect(self.load_pon_traffic_data)
        
        # Status da coleta
        self.pon_traffic_status = QLabel("Status: Aguardando...")
        self.pon_traffic_status.setStyleSheet("padding: 3px; background-color: #f0f0f0; border-radius: 3px;")
        
        control_layout.addWidget(self.pon_traffic_olt_filter_label)
        control_layout.addWidget(self.pon_traffic_olt_filter)
        control_layout.addWidget(self.pon_traffic_refresh_btn)
        control_layout.addWidget(self.pon_traffic_status)
        control_layout.addStretch()
        layout.addWidget(control_panel)
        
        # Tabela de dados
        self.pon_traffic_table = QTableWidget()
        self.pon_traffic_table.setColumnCount(11)
        self.pon_traffic_table.setHorizontalHeaderLabels([
            "OLT", "F/S/P", "Hora", "Tráfego Subida (kbps)", "Tráfego Descida (kbps)",
            "Broadcast Subida (p/s)", "Multicast Subida (p/s)", "Unicast Subida (p/s)",
            "Broadcast Descida (p/s)", "Multicast Descida (p/s)", "Unicast Descida (p/s)"
        ])
        self.pon_traffic_table.setSortingEnabled(True)
        self.pon_traffic_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.pon_traffic_table)
        
        # Timer para atualização automática
        self.pon_traffic_timer = QTimer(self)
        self.pon_traffic_timer.setInterval(600000)  # 10 minutos
        self.pon_traffic_timer.timeout.connect(self.load_pon_traffic_data)
        
        # Conectar sinal de atualização
        db_signals.pon_traffic_updated.connect(self.update_pon_traffic_display)
        db_signals.pon_traffic_status_changed.connect(self.update_pon_traffic_status)

    # Em gui/main_window.py, adicione estes métodos no final da classe

    # --- INÍCIO DA MODIFICAÇÃO (NOVOS MÉTODOS) ---

    def setup_pon_state_tab(self):
        """Configura a interface da aba 'Estado PON'."""
        layout = QVBoxLayout(self.pon_state_tab)

        # -- Painel de Controle (Filtro e Ações) --
        control_panel = QWidget()
        control_layout = QHBoxLayout(control_panel)

        self.pon_state_olt_filter_label = QLabel("Filtrar por OLT:")
        self.pon_state_olt_filter = QComboBox()
        if self.pon_state_olt_filter not in self.olt_filters_to_update:
            self.olt_filters_to_update.append(self.pon_state_olt_filter)

        self.pon_state_olt_filter.currentTextChanged.connect(self.load_pon_state_data)

        export_btn = QPushButton("Exportar CSV")
        export_btn.clicked.connect(self.export_pon_state_to_csv)

        control_layout.addWidget(self.pon_state_olt_filter_label)
        control_layout.addWidget(self.pon_state_olt_filter)
        control_layout.addStretch()
        control_layout.addWidget(export_btn)
        layout.addWidget(control_panel)

        # -- Tabela de Estado da Porta PON --
        self.pon_state_table = QTableWidget()
        # --- INÍCIO DA MODIFICAÇÃO ---
        self.pon_state_table.setColumnCount(18) # Aumentado para 18
        self.pon_state_table.setHorizontalHeaderLabels([
            "OLT", "F/S/P", "Hora da Coleta", "Estado Porta", "Estado Admin", "Causa Queda", "Última Subida", "Última Queda",
            "Detecção Sinal", "Banda Disp. (Kbps)", "Banda Garantida Disp.", "ONT Rogue", "Status Módulo",
            "Estado Laser", "Falha TX", "Temperatura (°C)", "Corrente TX (mA)", "Potência TX (dBm)"
        ])
        self.pon_state_table.setSortingEnabled(True)
        self.pon_state_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.pon_state_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.pon_state_table.setAlternatingRowColors(True)
        layout.addWidget(self.pon_state_table)

        # Timer para atualização automática
        self.pon_state_timer = QTimer(self)
        self.pon_state_timer.setInterval(60000)  # 60 segundos
        self.pon_state_timer.timeout.connect(self.load_pon_state_data)

    def load_pon_state_data(self):
        """Carrega os dados de estado da porta PON e os exibe na tabela."""
        logging.info("Carregando dados de estado da porta PON.")
        
        self.pon_state_table.setSortingEnabled(False)
        self.pon_state_table.setRowCount(0)
        selected_olt = self.pon_state_olt_filter.currentText()
        params = []
        olt_condition = ""
        if selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
            try:
                # --- INÍCIO DA CORREÇÃO ---
                # A string é "OLT 96", então pegamos o identificador
                olt_identifier = selected_olt.split()[-1] 
                # A consulta deve filtrar pela coluna 'olt_identifier'
                olt_condition = "WHERE pps.olt_identifier = %s" 
                params.append(olt_identifier)
                # --- FIM DA CORREÇÃO ---
            except IndexError:
                logging.warning(f"Formato de OLT inesperado no filtro: {selected_olt}")

        query = f"""
            SELECT pps.*
            FROM pon_port_state pps
            INNER JOIN (
                SELECT olt_identifier, fsp, MAX(collection_time) as max_time
                FROM pon_port_state
                GROUP BY olt_identifier, fsp
            ) latest ON pps.olt_identifier = latest.olt_identifier AND pps.fsp = latest.fsp AND pps.collection_time = latest.max_time
            {olt_condition}
            ORDER BY pps.olt_ip, pps.fsp
        """
        
        try:
            self.cursor.execute(query, tuple(params))
            results = self.cursor.fetchall()
            
            self.pon_state_table.setRowCount(len(results))
            

            col_map = {desc[0]: i for i, desc in enumerate(self.cursor.description)}

            for row_idx, row in enumerate(results):
                # --- INÍCIO DA MODIFICAÇÃO ---
                collection_time = row[col_map['collection_time']].strftime('%d/%m/%Y %H:%M:%S') if row[col_map['collection_time']] else "-"

                # Formata os novos campos
                guaranteed_bw = row[col_map['left_guaranteed_bandwidth_kbps']]
                formatted_guaranteed_bw = f"{guaranteed_bw:,}" if guaranteed_bw is not None else "-"
                admin_state = str(row[col_map['admin_state']]) if row[col_map['admin_state']] is not None else "-"

                items = [
                    QTableWidgetItem(str(row[col_map['olt_ip']])),
                    QTableWidgetItem(str(row[col_map['fsp']])),
                    QTableWidgetItem(collection_time),
                    QTableWidgetItem(str(row[col_map['port_state']])),
                    QTableWidgetItem(admin_state), # Nova coluna
                    QTableWidgetItem(str(row[col_map['last_down_cause']]) if row[col_map['last_down_cause']] is not None else "-"),
                    QTableWidgetItem(row[col_map['last_up_time']].strftime('%d/%m/%Y %H:%M') if row[col_map['last_up_time']] is not None else "-"),
                    QTableWidgetItem(row[col_map['last_down_time']].strftime('%d/%m/%Y %H:%M') if row[col_map['last_down_time']] is not None else "-"),
                    QTableWidgetItem(str(row[col_map['signal_detect']])),
                    QTableWidgetItem(f"{row[col_map['available_bandwidth_kbps']]:,}" if row[col_map['available_bandwidth_kbps']] is not None else "-"),
                    QTableWidgetItem(formatted_guaranteed_bw), # Nova coluna
                    QTableWidgetItem(str(row[col_map['illegal_rogue_ont']])),
                    QTableWidgetItem(str(row[col_map['optical_module_status']])),
                    QTableWidgetItem(str(row[col_map['laser_state']])),
                    QTableWidgetItem(str(row[col_map['tx_fault']])),
                    QTableWidgetItem(f"{row[col_map['temperature_c']]:.1f}" if row[col_map['temperature_c']] is not None else "-"),
                    QTableWidgetItem(f"{row[col_map['tx_bias_current_ma']]:.1f}" if row[col_map['tx_bias_current_ma']] is not None else "-"),
                    QTableWidgetItem(f"{row[col_map['tx_power_dbm']]:.2f}" if row[col_map['tx_power_dbm']] is not None else "-")
                ]

                # Destacar linhas com problemas
                has_problem = (row[col_map['port_state']] != "Online" or 
                            row[col_map['signal_detect']] != "Normal" or
                            row[col_map['tx_fault']] != "Normal" or
                            (row[col_map['temperature_c']] is not None and not (0 < row[col_map['temperature_c']] < 70)))

                if has_problem:
                    for item in items:
                        item.setBackground(QColor("#FFCDD2")) # Vermelho claro

                for col_idx, item in enumerate(items):
                    self.pon_state_table.setItem(row_idx, col_idx, item)

                if admin_state.lower() != 'on':
                    items[4].setBackground(QColor("#FFCDD2")) # Coluna "Estado Admin"


            self.pon_state_table.resizeColumnsToContents()
            self.pon_state_table.setSortingEnabled(True)
            logging.info(f"{len(results)} registros de estado PON carregados.")

        except psycopg2.Error as e:
            if self.conn: self.conn.rollback()
            QMessageBox.critical(self, "Erro de Banco de Dados", f"Não foi possível carregar os dados de estado PON:\n{e}")
        except Exception as e:
            QMessageBox.critical(self, "Erro ao Carregar Dados", f"Não foi possível carregar os dados: {str(e)}")

    def update_pon_port_state_display(self):
        """Atualiza a exibição de dados de estado da PON se a aba estiver ativa."""
        if self.tab_widget.currentWidget() == self.pon_state_tab:
            logging.info("Sinal recebido. Atualizando exibição de estado da porta PON.")
            self.load_pon_state_data()

    def export_pon_state_to_csv(self):
        """Exporta os dados da tabela de estado PON para um arquivo CSV."""
        if self.pon_state_table.rowCount() == 0:
            QMessageBox.information(self, "Nada para Exportar", "A tabela de estado PON está vazia.")
            return

        filename, _ = QFileDialog.getSaveFileName(self, "Exportar Estado PON", f"estado_pon_{datetime.now().strftime('%Y%m%d')}.csv", "Arquivos CSV (*.csv)")

        if not filename: return

        try:
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile, delimiter=';')
                headers = [self.pon_state_table.horizontalHeaderItem(col).text() for col in range(self.pon_state_table.columnCount())]
                writer.writerow(headers)

                for row in range(self.pon_state_table.rowCount()):
                    row_data = [self.pon_state_table.item(row, col).text() for col in range(self.pon_state_table.columnCount())]
                    writer.writerow(row_data)
            QMessageBox.information(self, "Exportação Concluída", f"Dados exportados com sucesso para:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "Erro de Exportação", f"Não foi possível exportar os dados:\n{str(e)}")

    def update_pon_traffic_status(self, olt_ip, fsp, status):
        """Atualiza o status da coleta de tráfego PON na GUI."""
        if hasattr(self, 'pon_traffic_status') and self.tab_widget.currentWidget() == self.pon_traffic_tab:
            status_text = f"Status: {olt_ip} {fsp} - {status}"
            self.pon_traffic_status.setText(status_text)
            
            # Colorir por status
            if "sucesso" in status.lower():
                self.pon_traffic_status.setStyleSheet("padding: 3px; background-color: #c8e6c9; border-radius: 3px;")
            elif "erro" in status.lower():
                self.pon_traffic_status.setStyleSheet("padding: 3px; background-color: #ffcdd2; border-radius: 3px;")
            else:
                self.pon_traffic_status.setStyleSheet("padding: 3px; background-color: #fff9c4; border-radius: 3px;")

    def load_pon_traffic_data(self):
        """Carrega os dados de tráfego PON do banco de dados."""
        selected_olt = self.pon_traffic_olt_filter.currentText()
        
        try:
            self.pon_traffic_table.setSortingEnabled(False)
            self.pon_traffic_table.setRowCount(0)
            
            query = """
                SELECT olt_ip, fsp, collection_time, up_traffic_kbps, down_traffic_kbps,
                    upstream_broadcast_pps, upstream_multicast_pps, upstream_unicast_pps,
                    downstream_broadcast_pps, downstream_multicast_pps, downstream_unicast_pps
                FROM pon_traffic_data
                WHERE collection_time >= NOW() - INTERVAL '24 hours'
            """
            params = []
            
            if selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
                olt_identifier = selected_olt.split()[-1]
                query += " AND olt_ip = %s"
                params.append(olt_identifier)
            
            query += " ORDER BY collection_time DESC"
            
            self.cursor.execute(query, tuple(params))
            data = self.cursor.fetchall()
            
            self.pon_traffic_table.setRowCount(len(data))
            
            for row_idx, row_data in enumerate(data):
                for col_idx, col_data in enumerate(row_data):
                    item_text = str(col_data) if col_data is not None else ""
                    item = QTableWidgetItem(item_text)
                    
                    # Destacar valores altos
                    if col_idx in [3, 4]:  # Tráfego em kbps
                        try:
                            value = float(col_data)
                            if value > 100000:  # Mais de 100 Mbps
                                item.setBackground(QtGui.QColor(255, 200, 200))
                        except (ValueError, TypeError):
                            pass
                    
                    self.pon_traffic_table.setItem(row_idx, col_idx, item)
            
            self.pon_traffic_table.resizeColumnsToContents()
            
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Não foi possível carregar os dados de tráfego PON: {str(e)}")
            logging.error(f"Erro ao carregar dados de tráfego PON: {e}", exc_info=True)
        finally:
            self.pon_traffic_table.setSortingEnabled(True)

    def update_pon_traffic_display(self):
        """Atualiza a exibição dos dados de tráfego PON."""
        if hasattr(self, 'pon_traffic_table') and self.tab_widget.currentWidget() == self.pon_traffic_tab:
            self.load_pon_traffic_data()

    def setup_pon_stats_tab(self):
        """Configura a interface da aba 'Estatísticas da PON' com uma única tabela completa."""
        layout = QVBoxLayout(self.pon_stats_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Painel de controle com filtros
        control_panel = QWidget()
        control_panel.setMaximumHeight(45)
        control_layout = QHBoxLayout(control_panel)
        control_layout.setContentsMargins(5, 2, 5, 2)
        control_layout.setSpacing(5)
        
        # Filtro de OLT
        self.pon_stats_olt_filter = QComboBox()
        self.pon_stats_olt_filter.setMaximumWidth(100)
        self.pon_stats_olt_filter.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        if self.pon_stats_olt_filter not in self.olt_filters_to_update:
            self.olt_filters_to_update.append(self.pon_stats_olt_filter)
        
        # Filtro de F/S/P
        self.pon_stats_fsp_filter = QComboBox()
        self.pon_stats_fsp_filter.addItem("Todas as PONs")
        self.pon_stats_fsp_filter.setEnabled(False)
        self.pon_stats_fsp_filter.setMaximumWidth(80)
        self.pon_stats_fsp_filter.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        
        # Filtro de Direção (RX/TX/Todos)
        self.pon_stats_direction_filter = QComboBox()
        self.pon_stats_direction_filter.addItem("Todos")
        self.pon_stats_direction_filter.addItems(["RX", "TX"])
        self.pon_stats_direction_filter.setMaximumWidth(60)
        
        # Filtro de Métrica
        self.pon_stats_metric_filter = QComboBox()
        self.pon_stats_metric_filter.addItem("Todas as Métricas")
        self.pon_stats_metric_filter.setEnabled(False)
        self.pon_stats_metric_filter.setMaximumWidth(150)
        self.pon_stats_metric_filter.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        
        # Filtro de Categoria
        self.pon_stats_category_filter = QComboBox()
        self.pon_stats_category_filter.addItem("Todas as Categorias")
        self.pon_stats_category_filter.addItems(["Normal ✅", "Atenção ⚠️", "Crítico 🚨"])
        self.pon_stats_category_filter.setMaximumWidth(120)
        self.pon_stats_category_filter.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        
        # Conecta sinais
        self.pon_stats_olt_filter.currentTextChanged.connect(self.update_pon_stats_filters)
        self.pon_stats_fsp_filter.currentTextChanged.connect(self.load_pon_stats_data)
        self.pon_stats_direction_filter.currentTextChanged.connect(self.load_pon_stats_data)
        self.pon_stats_metric_filter.currentTextChanged.connect(self.load_pon_stats_data)
        self.pon_stats_category_filter.currentTextChanged.connect(self.load_pon_stats_data)
        
        # Labels mínimos
        olt_label = QLabel("OLT:")
        olt_label.setStyleSheet("font-size: 9px; padding: 0px;")
        fsp_label = QLabel("F/S/P:")
        fsp_label.setStyleSheet("font-size: 9px; padding: 0px;")
        dir_label = QLabel("Dir.:")
        dir_label.setStyleSheet("font-size: 9px; padding: 0px;")
        metric_label = QLabel("Métrica:")
        metric_label.setStyleSheet("font-size: 9px; padding: 0px;")
        cat_label = QLabel("Cat.:")
        cat_label.setStyleSheet("font-size: 9px; padding: 0px;")
        
        # Adiciona elementos
        control_layout.addWidget(olt_label)
        control_layout.addWidget(self.pon_stats_olt_filter)
        control_layout.addWidget(fsp_label)
        control_layout.addWidget(self.pon_stats_fsp_filter)
        control_layout.addWidget(dir_label)
        control_layout.addWidget(self.pon_stats_direction_filter)
        control_layout.addWidget(metric_label)
        control_layout.addWidget(self.pon_stats_metric_filter)
        control_layout.addWidget(cat_label)
        control_layout.addWidget(self.pon_stats_category_filter)
        control_layout.addStretch()
        
        # Botão de legenda
        legend_btn = QPushButton("Legenda")
        legend_btn.setMaximumWidth(50)
        legend_btn.setStyleSheet("font-size: 8px; padding: 1px; background-color: #e1f5fe;")
        legend_btn.clicked.connect(self.show_pon_stats_legend)
        control_layout.addWidget(legend_btn)
        
        # Status
        self.pon_stats_status_label = QLabel("0 regs")
        self.pon_stats_status_label.setStyleSheet("color: green; font-weight: bold; font-size: 8px;")
        self.pon_stats_status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        control_layout.addWidget(self.pon_stats_status_label)
        
        layout.addWidget(control_panel)
        
        # Tabela única com todas as estatísticas
        self.pon_stats_table = QTableWidget()
        self.pon_stats_table.setColumnCount(7)  # F/S/P, Hora, Direção, Métrica, Valor, %, Cat.
        self.pon_stats_table.setHorizontalHeaderLabels(["F/S/P", "Hora", "Dir.", "Métrica", "Valor", "%", "Cat."])
        self.pon_stats_table.horizontalHeader().setMinimumHeight(20)
        self.pon_stats_table.verticalHeader().setDefaultSectionSize(18)
        
        # Ajuste de largura das colunas
        self.pon_stats_table.setColumnWidth(0, 60)   # F/S/P
        self.pon_stats_table.setColumnWidth(1, 70)   # Hora
        self.pon_stats_table.setColumnWidth(2, 35)   # Direção
        self.pon_stats_table.setColumnWidth(3, 220)  # Métrica
        self.pon_stats_table.setColumnWidth(4, 100)  # Valor
        self.pon_stats_table.setColumnWidth(5, 50)   # Porcentagem
        self.pon_stats_table.setColumnWidth(6, 30)   # Categoria
        
        layout.addWidget(self.pon_stats_table)
        
        # Timer
        self.pon_stats_timer = QTimer(self)
        self.pon_stats_timer.setInterval(60000)
        self.pon_stats_timer.timeout.connect(self.load_pon_stats_data)

    def update_pon_stats_filters(self):
        """Atualiza os filtros de F/S/P e Métrica com base na OLT selecionada."""
        selected_olt = self.pon_stats_olt_filter.currentText()
        
        # Bloqueia sinais para evitar chamadas recursivas
        self.pon_stats_fsp_filter.blockSignals(True)
        self.pon_stats_fsp_filter.clear()
        self.pon_stats_fsp_filter.addItem("Todas as PONs")
        self.pon_stats_fsp_filter.setEnabled(False)
        
        self.pon_stats_metric_filter.blockSignals(True)
        self.pon_stats_metric_filter.clear()
        self.pon_stats_metric_filter.addItem("Todas as Métricas")
        self.pon_stats_metric_filter.setEnabled(False)
        
        if selected_olt and selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
            try:
                # Extrai o identificador da OLT
                olt_identifier = selected_olt.split()[-1] if "OLT" in selected_olt else selected_olt
                
                # Busca F/S/P distintos para essa OLT
                query_fsp = "SELECT DISTINCT fsp FROM pon_statistics_packets WHERE olt_identifier = %s ORDER BY fsp;"
                self.cursor.execute(query_fsp, (olt_identifier,))
                fsps = [row[0] for row in self.cursor.fetchall()]
                
                for fsp in fsps:
                    self.pon_stats_fsp_filter.addItem(fsp)
                
                # Busca métricas distintas para essa OLT
                query_metrics = """
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'pon_statistics_packets' 
                    AND (column_name LIKE 'rx_%' OR column_name LIKE 'tx_%')
                    ORDER BY column_name;
                """
                self.cursor.execute(query_metrics)
                metrics = [row[0] for row in self.cursor.fetchall()]
                
                # Mapeamento de nomes amigáveis para as métricas
                metric_names = {
                    # Métricas RX
                    'rx_frames': 'Quadros recebidos (total)',
                    'rx_bytes': 'Bytes recebidos (total)',
                    'rx_unicast_frames': 'Quadros unicast recebidos',
                    'rx_multicast_frames': 'Quadros multicast recebidos',
                    'rx_broadcast_frames': 'Quadros broadcast recebidos',
                    'rx_64_byte_frames': 'Quadros de 64 bytes recebidos',
                    'rx_65_127_byte_frames': 'Quadros de 65-127 bytes recebidos',
                    'rx_128_255_byte_frames': 'Quadros de 128-255 bytes recebidos',
                    'rx_256_511_byte_frames': 'Quadros de 256-511 bytes recebidos',
                    'rx_512_1023_byte_frames': 'Quadros de 512-1023 bytes recebidos',
                    'rx_1024_1518_byte_frames': 'Quadros de 1024-1518 bytes recebidos',
                    'rx_over_1518_byte_frames': 'Quadros maiores que 1518 bytes recebidos',
                    'rx_undersize_discarded_frames': 'Quadros menores que 64 bytes descartados',
                    'rx_oversize_discarded_frames': 'Quadros maiores que permitido descartados',
                    'rx_crc_error_frames': 'Quadros com erro de CRC recebidos',
                    'rx_discarded_frames': 'Quadros descartados recebidos',
                    'rx_error_frames': 'Quadros com erros (total) recebidos',
                    # Métricas TX
                    'tx_frames': 'Quadros enviados (total)',
                    'tx_bytes': 'Bytes enviados (total)',
                    'tx_unicast_frames': 'Quadros unicast enviados',
                    'tx_multicast_frames': 'Quadros multicast enviados',
                    'tx_broadcast_frames': 'Quadros broadcast enviados',
                    'tx_64_byte_frames': 'Quadros de 64 bytes enviados',
                    'tx_65_127_byte_frames': 'Quadros de 65-127 bytes enviados',
                    'tx_128_255_byte_frames': 'Quadros de 128-255 bytes enviados',
                    'tx_256_511_byte_frames': 'Quadros de 256-511 bytes enviados',
                    'tx_512_1023_byte_frames': 'Quadros de 512-1023 bytes enviados',
                    'tx_1024_1518_byte_frames': 'Quadros de 1024-1518 bytes enviados',
                    'tx_over_1518_byte_frames': 'Quadros maiores que 1518 bytes enviados',
                    'tx_multicast_bytes': 'Bytes multicast enviados',
                    'tx_buffer_overflow_frames': 'Quadros descartados por overflow de buffer'
                }
                
                # Adiciona métricas formatadas
                for metric in metrics:
                    formatted_name = metric_names.get(metric, metric.replace('_', ' ').title())
                    self.pon_stats_metric_filter.addItem(formatted_name, metric)
                
                # Habilita os filtros
                self.pon_stats_fsp_filter.setEnabled(True)
                self.pon_stats_metric_filter.setEnabled(True)
                
                logging.info(f"F/S/P carregados para {olt_identifier}: {fsps}")
                logging.info(f"Métricas carregadas para {olt_identifier}: {len(metrics)}")
                
            except Exception as e:
                logging.error(f"Erro ao carregar filtros para estatísticas PON: {e}")
                if self.conn:
                    self.conn.rollback()
        else:
            logging.info("Nenhuma OLT selecionada, filtros desabilitados")
        
        self.pon_stats_fsp_filter.blockSignals(False)
        self.pon_stats_metric_filter.blockSignals(False)
        
        # Carrega os dados após atualizar os filtros
        self.load_pon_stats_data()


    def show_pon_stats_legend(self):
        """Exibe uma janela com a legenda atualizada de categorias dos contadores PON."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Legenda - Estatísticas PON")
        dialog.setMinimumSize(800, 600)
        dialog.setModal(True)
        
        layout = QVBoxLayout(dialog)
        
        # Criar um widget com abas para organizar as informações
        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)
        
        # Aba 1: Visão Geral
        overview_tab = QWidget()
        overview_layout = QVBoxLayout(overview_tab)
        
        overview_title = QLabel("<h2>📊 Visão Geral das Estatísticas PON</h2>")
        overview_layout.addWidget(overview_title)
        
        overview_info = QLabel("""
        <p>Esta aba mostra todas as estatísticas da porta PON em uma única tabela, seguindo o mesmo padrão do comando 
        <code>display statistics port ethernet</code> dos equipamentos Huawei OLT.</p>
        
        <h3>Colunas da Tabela:</h3>
        <ul>
            <li><b>F/S/P:</b> Frame/Slot/Porta - identificação da porta PON</li>
            <li><b>Hora:</b> Timestamp da coleta dos dados</li>
            <li><b>Dir.:</b> Direção do tráfego (RX = Recebido, TX = Enviado)</li>
            <li><b>Métrica:</b> Nome amigável do contador</li>
            <li><b>Valor:</b> Valor absoluto do contador</li>
            <li><b>%:</b> Porcentagem em relação ao total (quando aplicável)</li>
            <li><b>Cat.:</b> Categoria do contador (✅ Normal, ⚠️ Atenção, 🚨 Crítico)</li>
        </ul>
        """)
        overview_layout.addWidget(overview_info)
        
        tab_widget.addTab(overview_tab, "Visão Geral")
        
        # Aba 2: Contadores Normais (Verde)
        normal_tab = QWidget()
        normal_layout = QVBoxLayout(normal_tab)
        
        normal_title = QLabel("<h2 style='color: #2e7d32;'>✅ Contadores que é normal crescer bastante</h2>")
        normal_layout.addWidget(normal_title)
        
        normal_info = QLabel("""
        <p><b>Esses crescem o tempo todo, não são problema em si. O que importa é a taxa de crescimento e se bate com o uso real:</b></p>
        <ul>
            <li><b>Frames / Bytes (RX e TX)</b> → indicam tráfego total</li>
            <li><b>Unicast Frames</b> → tráfego normal da rede</li>
            <li><b>Multicast Frames</b> → depende da rede (IGMP, IPTV etc.)</li>
            <li><b>Broadcast Frames</b> → deve existir, mas em baixa quantidade</li>
            <li><b>Frames por faixa de tamanho</b> → apenas estatística, esperado</li>
        </ul>
        <br>
        <p><b>Regras de coloração:</b></p>
        <ul>
            <li><span style='color: #2e7d32;'>Verde:</span> Valores normais, mesmo que altos</li>
            <li><span style='color: #f57c00;'>Amarelo:</span> Broadcast > 1000 frames ou Multicast > 5000 frames</li>
        </ul>
        """)
        normal_layout.addWidget(normal_info)
        
        tab_widget.addTab(normal_tab, "Contadores Normais")
        
        # Aba 3: Contadores de Atenção (Amarelo)
        warning_tab = QWidget()
        warning_layout = QVBoxLayout(warning_tab)
        
        warning_title = QLabel("<h2 style='color: #f57c00;'>⚠️ Contadores que devem ficar sempre baixos ou zero</h2>")
        warning_layout.addWidget(warning_title)
        
        warning_info = QLabel("""
        <p><b>Se começarem a subir, já é observância (Warning):</b></p>
        <ul>
            <li><b>Over 1518 Byte Frames</b> → quadros maiores que o MTU normal</li>
            <li><b>Broadcast Frames > 1000</b> → pode causar lentidão</li>
            <li><b>Multicast Frames > 5000</b> → se não há IPTV, deveria ser quase zero</li>
        </ul>
        <br>
        <p><b>Regras de coloração:</b></p>
        <ul>
            <li><span style='color: #c8e6c9;'>Verde:</span> Valores dentro do limite (Broadcast ≤ 1000, Multicast ≤ 5000)</li>
            <li><span style='color: #f57c00;'>Amarelo:</span> Valores acima do limite</li>
        </ul>
        """)
        warning_layout.addWidget(warning_info)
        
        tab_widget.addTab(warning_tab, "Contadores de Atenção")
        
        # Aba 4: Contadores Críticos (Vermelho)
        critical_tab = QWidget()
        critical_layout = QVBoxLayout(critical_tab)
        
        critical_title = QLabel("<h2 style='color: #c62828;'>🚨 Contadores que devem ser sempre ZERO</h2>")
        critical_layout.addWidget(critical_title)
        
        critical_info = QLabel("""
        <p><b>Esses apontam problemas reais de rede ou hardware. Qualquer número > 0 já merece atenção:</b></p>
        <ul>
            <li><b>Undersize Discarded Frames</b> → pacote abaixo do tamanho mínimo</li>
            <li><b>Oversize Discarded Frames</b> → pacote acima do permitido</li>
            <li><b>Crc Error Frames</b> → erro de integridade</li>
            <li><b>Error Frames</b> → pacotes corrompidos</li>
            <li><b>Discarded Frames (genérico)</b> → perda de pacotes</li>
            <li><b>Buffer Overflow Frames</b> → congestionamento de buffer</li>
        </ul>
        <br>
        <p><b>Regras de coloração:</b></p>
        <ul>
            <li><span style='color: #c8e6c9;'>Verde:</span> Valor = 0 (normal)</li>
            <li><span style='color: #c62828;'>Vermelho:</span> Valor > 0 (crítico)</li>
        </ul>
        <br>
        <p><b>Se for poucos e isolados:</b> pode ser normal (picos)</p>
        <p><b>Se for constante:</b> precisa investigar (cabo, porta, congestionamento, mau contato)</p>
        """)
        critical_layout.addWidget(critical_info)
        
        tab_widget.addTab(critical_tab, "Contadores Críticos")
        
        # Aba 5: Exemplos Práticos
        examples_tab = QWidget()
        examples_layout = QVBoxLayout(examples_tab)
        
        examples_title = QLabel("<h2>📋 Exemplos Práticos</h2>")
        examples_layout.addWidget(examples_title)
        
        examples_info = QLabel("""
        <p><b>Análise de exemplos baseada no comando real:</b></p>
        <table border='1' cellpadding='5' style='border-collapse: collapse; width: 100%;'>
            <tr style='background-color: #c8e6c9;'>
                <td><b>Received frames: 24.075.989.140</b></td>
                <td>✅ Normal - tráfego esperado</td>
            </tr>
            <tr style='background-color: #c8e6c9;'>
                <td><b>Received bytes: 7.093.872.660.861</b></td>
                <td>✅ Normal - tráfego esperado</td>
            </tr>
            <tr style='background-color: #c8e6c9;'>
                <td><b>Received unicast frames: 24.075.946.528 (99%)</b></td>
                <td>✅ Normal - tráfego unicast dominante</td>
            </tr>
            <tr style='background-color: #c8e6c9;'>
                <td><b>Received broadcast frames: 34.626 (0%)</b></td>
                <td>✅ Normal - abaixo do limite de 1000</td>
            </tr>
            <tr style='background-color: #fff9c4;'>
                <td><b>Received over 1518-byte frames: 143.310.953 (0%)</b></td>
                <td>⚠️ Atenção - quadros acima do MTU padrão</td>
            </tr>
            <tr style='background-color: #ffcdd2;'>
                <td><b>Received CRC error frames: 7.664</b></td>
                <td>🚨 Crítico - qualquer valor > 0 indica problemas</td>
            </tr>
            <tr style='background-color: #ffcdd2;'>
                <td><b>Sent buffer overflow frames: 931.296</b></td>
                <td>🚨 Crítico - buffer da ONT saturado</td>
            </tr>
            <tr style='background-color: #c8e6c9;'>
                <td><b>Sent 1024-1518-byte frames: 79.093.096.744 (92%)</b></td>
                <td>✅ Normal - maioria dos pacotes em tamanho padrão</td>
            </tr>
        </table>
        <br>
        <p><b>Investigação necessária para valores críticos:</b></p>
        <ul>
            <li><b>Buffer Overflow:</b> verificar se a ONT está saturada, gargalo na rede, configuração da porta</li>
            <li><b>CRC Error:</b> verificar cabos, conectores, interferências, qualidade do sinal óptico</li>
            <li><b>Discarded Frames:</b> verificar congestionamento, buffer, processamento da ONT</li>
        </ul>
        """)
        examples_layout.addWidget(examples_info)
        
        tab_widget.addTab(examples_tab, "Exemplos Práticos")
        
        # Aba 6: Mapeamento Completo
        mapping_tab = QWidget()
        mapping_layout = QVBoxLayout(mapping_tab)
        
        mapping_title = QLabel("<h2>🗺️ Mapeamento Completo das Métricas</h2>")
        mapping_layout.addWidget(mapping_title)
        
        mapping_info = QLabel("""
        <table border='1' cellpadding='3' style='border-collapse: collapse; width: 100%; font-size: 11px;'>
            <tr style='background-color: #e3f2fd;'>
                <th><b>Campo BD</b></th>
                <th><b>Nome Amigável</b></th>
                <th><b>Categoria</b></th>
                <th><b>Explicação</b></th>
            </tr>
            <tr>
                <td>rx_frames</td>
                <td>Quadros recebidos (total)</td>
                <td>✅ Normal</td>
                <td>Total de pacotes recebidos</td>
            </tr>
            <tr>
                <td>rx_bytes</td>
                <td>Bytes recebidos (total)</td>
                <td>✅ Normal</td>
                <td>Total de dados recebidos</td>
            </tr>
            <tr>
                <td>rx_unicast_frames</td>
                <td>Quadros unicast recebidos</td>
                <td>✅ Normal</td>
                <td>Pacotes para um único destino</td>
            </tr>
            <tr>
                <td>rx_multicast_frames</td>
                <td>Quadros multicast recebidos</td>
                <td>⚠️ Atenção</td>
                <td>Pacotes para múltiplos destinos</td>
            </tr>
            <tr>
                <td>rx_broadcast_frames</td>
                <td>Quadros broadcast recebidos</td>
                <td>⚠️ Atenção</td>
                <td>Pacotes para todos na rede</td>
            </tr>
            <tr>
                <td>rx_crc_error_frames</td>
                <td>Quadros com erro de CRC recebidos</td>
                <td>🚨 Crítico</td>
                <td>Erros de integridade dos dados</td>
            </tr>
            <tr>
                <td>rx_discarded_frames</td>
                <td>Quadros descartados recebidos</td>
                <td>🚨 Crítico</td>
                <td>Pacotes descartados pela OLT</td>
            </tr>
            <tr>
                <td>tx_frames</td>
                <td>Quadros enviados (total)</td>
                <td>✅ Normal</td>
                <td>Total de pacotes enviados</td>
            </tr>
            <tr>
                <td>tx_bytes</td>
                <td>Bytes enviados (total)</td>
                <td>✅ Normal</td>
                <td>Total de dados enviados</td>
            </tr>
            <tr>
                <td>tx_buffer_overflow_frames</td>
                <td>Quadros descartados por overflow de buffer</td>
                <td>🚨 Crítico</td>
                <td>Saturação do buffer de envio</td>
            </tr>
        </table>
        """)
        mapping_layout.addWidget(mapping_info)
        
        tab_widget.addTab(mapping_tab, "Mapeamento Completo")
        
        # Botão de fechar
        close_button = QPushButton("Fechar")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        
        # Exibir o diálogo
        dialog.exec_()

    def update_pon_stats_fsp_filter(self):
        """Atualiza o filtro de F/S/P com base na OLT selecionada para a aba de estatísticas PON."""
        selected_olt = self.pon_stats_olt_filter.currentText()
        
        # Bloqueia sinais para evitar chamadas recursivas
        self.pon_stats_fsp_filter.blockSignals(True)
        self.pon_stats_fsp_filter.clear()
        self.pon_stats_fsp_filter.addItem("Todas as PONs")
        
        if selected_olt and selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
            try:
                # Extrai o identificador da OLT
                olt_identifier = selected_olt.split()[-1] if "OLT" in selected_olt else selected_olt
                
                # Busca F/S/P distintos para essa OLT na tabela de estatísticas
                query = "SELECT DISTINCT fsp FROM pon_statistics_packets WHERE olt_identifier = %s ORDER BY fsp;"
                self.cursor.execute(query, (olt_identifier,))
                fsps = [row[0] for row in self.cursor.fetchall()]
                
                for fsp in fsps:
                    self.pon_stats_fsp_filter.addItem(fsp)
                
                # Habilita o filtro de F/S/P
                self.pon_stats_fsp_filter.setEnabled(True)
                
                logging.info(f"F/S/P carregados para {olt_identifier}: {fsps}")
            except Exception as e:
                logging.error(f"Erro ao carregar F/S/P para o filtro de estatísticas PON: {e}")
                if self.conn:
                    self.conn.rollback()
        else:
            # Desabilita o filtro de F/S/P se nenhuma OLT for selecionada
            self.pon_stats_fsp_filter.setEnabled(False)
            logging.info("Nenhuma OLT selecionada, filtro de F/S/P desabilitado")
        
        self.pon_stats_fsp_filter.blockSignals(False)
        
        # Carrega os dados após atualizar os filtros
        self.load_pon_stats_data()


    def load_pon_stats_data(self):
        """Carrega os dados de estatísticas de pacotes em uma única tabela completa."""
        logging.info("Carregando estatísticas de pacotes da PON.")
        self.pon_stats_table.setRowCount(0)
        
        # Obter valores dos filtros
        selected_olt = self.pon_stats_olt_filter.currentText()
        selected_fsp = self.pon_stats_fsp_filter.currentText()
        selected_direction = self.pon_stats_direction_filter.currentText()
        selected_metric = self.pon_stats_metric_filter.currentText()
        selected_category = self.pon_stats_category_filter.currentText()
        
        # Obter o nome original da métrica
        metric_name = None
        if selected_metric != "Todas as Métricas":
            index = self.pon_stats_metric_filter.currentIndex()
            if index > 0:
                metric_name = self.pon_stats_metric_filter.itemData(index)
        
        # Mapear categoria selecionada
        category_map = {
            "Todas as Categorias": None,
            "Normal ✅": "normal",
            "Atenção ⚠️": "warning",
            "Crítico 🚨": "critical"
        }
        filter_category = category_map.get(selected_category)
        
        params = []
        where_conditions = []
        
        # Filtro de OLT
        if selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
            olt_identifier = selected_olt.split()[-1]
            where_conditions.append("olt_identifier = %s")
            params.append(olt_identifier)
        
        # Filtro de F/S/P
        if selected_fsp != "Todas as PONs":
            where_conditions.append("fsp = %s")
            params.append(selected_fsp)
        
        # Construir cláusula WHERE
        where_clause = ""
        if where_conditions:
            where_clause = "WHERE " + " AND ".join(where_conditions)
        
        query = f"SELECT * FROM pon_statistics_packets {where_clause} ORDER BY collection_time DESC LIMIT 500;"
        
        try:
            self.cursor.execute(query, tuple(params))
            results = self.cursor.fetchall()
            
            col_map = {desc[0]: i for i, desc in enumerate(self.cursor.description)}
            
            # Mapeamento de nomes amigáveis
            metric_names = {
                # Métricas RX
                'rx_frames': 'Quadros recebidos (total)',
                'rx_bytes': 'Bytes recebidos (total)',
                'rx_unicast_frames': 'Quadros unicast recebidos',
                'rx_multicast_frames': 'Quadros multicast recebidos',
                'rx_broadcast_frames': 'Quadros broadcast recebidos',
                'rx_64_byte_frames': 'Quadros de 64 bytes recebidos',
                'rx_65_127_byte_frames': 'Quadros de 65-127 bytes recebidos',
                'rx_128_255_byte_frames': 'Quadros de 128-255 bytes recebidos',
                'rx_256_511_byte_frames': 'Quadros de 256-511 bytes recebidos',
                'rx_512_1023_byte_frames': 'Quadros de 512-1023 bytes recebidos',
                'rx_1024_1518_byte_frames': 'Quadros de 1024-1518 bytes recebidos',
                'rx_over_1518_byte_frames': 'Quadros maiores que 1518 bytes recebidos',
                'rx_undersize_discarded_frames': 'Quadros menores que 64 bytes descartados',
                'rx_oversize_discarded_frames': 'Quadros maiores que permitido descartados',
                'rx_crc_error_frames': 'Quadros com erro de CRC recebidos',
                'rx_discarded_frames': 'Quadros descartados recebidos',
                'rx_error_frames': 'Quadros com erros (total) recebidos',
                # Métricas TX
                'tx_frames': 'Quadros enviados (total)',
                'tx_bytes': 'Bytes enviados (total)',
                'tx_unicast_frames': 'Quadros unicast enviados',
                'tx_multicast_frames': 'Quadros multicast enviados',
                'tx_broadcast_frames': 'Quadros broadcast enviados',
                'tx_64_byte_frames': 'Quadros de 64 bytes enviados',
                'tx_65_127_byte_frames': 'Quadros de 65-127 bytes enviados',
                'tx_128_255_byte_frames': 'Quadros de 128-255 bytes enviados',
                'tx_256_511_byte_frames': 'Quadros de 256-511 bytes enviados',
                'tx_512_1023_byte_frames': 'Quadros de 512-1023 bytes enviados',
                'tx_1024_1518_byte_frames': 'Quadros de 1024-1518 bytes enviados',
                'tx_over_1518_byte_frames': 'Quadros maiores que 1518 bytes enviados',
                'tx_multicast_bytes': 'Bytes multicast enviados',
                'tx_buffer_overflow_frames': 'Quadros descartados por overflow de buffer'
            }
            
            # Definir categorias com base no nome E valor da métrica
            def get_metric_category(metric_name, value):
                if value is None:
                    value = 0
                    
                metric_lower = metric_name.lower()
                
                # 🚨 Contadores críticos - QUALQUER valor > 0 já é crítico
                if any(x in metric_lower for x in [
                    'discarded', 'error', 'crc', 'undersize', 'oversize', 'buffer_overflow'
                ]):
                    return "critical" if value > 0 else "normal"
                
                # ⚠️ Contadores de atenção - valores acima do esperado
                elif 'over_1518_byte' in metric_lower:
                    return "warning" if value > 0 else "normal"
                
                # ⚠️ Broadcast - atenção se for muito alto (limite: 1000 frames)
                elif 'broadcast' in metric_lower:
                    return "warning" if value > 1000 else "normal"
                
                # ⚠️ Multicast - atenção se for muito alto e não for rede com IPTV
                elif 'multicast' in metric_lower and 'bytes' not in metric_lower:
                    return "warning" if value > 5000 else "normal"
                
                # ✅ Contadores normais - crescem naturalmente
                else:
                    return "normal"
            
            # Obter todas as métricas
            all_metrics = [k for k in col_map if k.startswith('rx_') or k.startswith('tx_')]
            
            # Filtrar métricas se necessário
            if metric_name:
                all_metrics = [metric_name] if metric_name in all_metrics else []
            
            # Filtrar por direção se necessário
            if selected_direction != "Todos":
                prefix = selected_direction.lower() + '_'
                all_metrics = [m for m in all_metrics if m.startswith(prefix)]
            
            # Preparar lista para dados filtrados
            table_data = []
            
            for record in results:
                fsp = record[col_map['fsp']]
                timestamp = record[col_map['collection_time']].strftime('%H:%M:%S')
                
                # Processar todas as métricas
                for metric in all_metrics:
                    value = record[col_map[metric]]
                    category = get_metric_category(metric, value)
                    
                    # Aplicar filtro de categoria se necessário
                    if filter_category and category != filter_category:
                        continue
                    
                    # Determinar direção
                    direction = "RX" if metric.startswith('rx_') else "TX"
                    
                    # Obter nome amigável
                    friendly_name = metric_names.get(metric, metric.replace('_', ' ').title())
                    
                    # Calcular porcentagem para métricas que têm total
                    percentage = ""
                    if value is not None and value > 0:
                        if metric in ['rx_unicast_frames', 'rx_multicast_frames', 'rx_broadcast_frames']:
                            total = record[col_map['rx_frames']] or 1
                            percentage = f"{(value/total*100):.0f}%"
                        elif metric in ['tx_unicast_frames', 'tx_multicast_frames', 'tx_broadcast_frames']:
                            total = record[col_map['tx_frames']] or 1
                            percentage = f"{(value/total*100):.0f}%"
                        elif any(x in metric for x in ['64_byte', '65_127_byte', '128_255_byte', '256_511_byte', '512_1023_byte', '1024_1518_byte', 'over_1518_byte']):
                            if metric.startswith('rx_'):
                                total = record[col_map['rx_frames']] or 1
                            else:
                                total = record[col_map['tx_frames']] or 1
                            percentage = f"{(value/total*100):.0f}%"
                    
                    table_data.append((fsp, timestamp, direction, friendly_name, value, percentage, category))
            
            # Preencher tabela com dados filtrados
            self.pon_stats_table.setRowCount(len(table_data))
            
            for row_idx, (fsp, timestamp, direction, metric, value, percentage, category) in enumerate(table_data):
                items = [
                    QTableWidgetItem(fsp),
                    QTableWidgetItem(timestamp),
                    QTableWidgetItem(direction),
                    QTableWidgetItem(metric),
                    QTableWidgetItem(f"{value:,}" if value is not None else "0"),
                    QTableWidgetItem(percentage),
                    QTableWidgetItem("✅" if category == "normal" else "⚠️" if category == "warning" else "🚨")
                ]
                
                # Aplicar cores
                color = None
                if category == "normal":
                    color = QColor('#c8e6c9')
                elif category == "warning":
                    color = QColor('#fff9c4')
                elif category == "critical":
                    color = QColor('#ffcdd2')
                
                for col_idx, item in enumerate(items):
                    if color:
                        item.setBackground(color)
                    self.pon_stats_table.setItem(row_idx, col_idx, item)
            
            # Ajustar colunas
            self.pon_stats_table.resizeColumnsToContents()
            
            # Atualizar status
            self.pon_stats_status_label.setText(f"{len(table_data)} regs")
            self.pon_stats_status_label.setStyleSheet("color: green; font-weight: bold; font-size: 8px;")
            
            # Log de estatísticas para depuração
            critical_count = sum(1 for _, _, _, _, _, _, cat in table_data if cat == "critical")
            warning_count = sum(1 for _, _, _, _, _, _, cat in table_data if cat == "warning")
            normal_count = sum(1 for _, _, _, _, _, _, cat in table_data if cat == "normal")
            
            logging.info(f"Estatísticas de categorização - Normal: {normal_count}, Atenção: {warning_count}, Crítico: {critical_count}")
            
        except Exception as e:
            logging.error(f"Erro ao carregar estatísticas de pacotes: {e}", exc_info=True)
            self.pon_stats_status_label.setText("Erro")
            self.pon_stats_status_label.setStyleSheet("color: red; font-weight: bold; font-size: 8px;")


    def update_pon_stats_display(self):
        """Atualiza a exibição de estatísticas de pacotes se a aba estiver ativa."""
        if self.tab_widget.currentWidget() == self.pon_stats_tab:
            self.load_pon_stats_data()

    # Em gui/main_window.py, adicione estas novas funções no final da classe

    def setup_ont_traffic_tab(self):
        """Configura a interface da aba 'Dados ONT por PON'."""
        layout = QVBoxLayout(self.ont_traffic_tab)
        
        # --- PAINEL DE CONTROLE COM FILTROS ---
        control_panel = QWidget()
        control_layout = QHBoxLayout(control_panel)
        
        # Filtro de OLT
        self.ont_traffic_olt_filter = QComboBox()
        self.ont_traffic_olt_filter.addItem("Todas as OLTs")
        
        # Filtro de F/S/P
        self.ont_traffic_fsp_filter = QComboBox()
        self.ont_traffic_fsp_filter.addItem("Todas as PONs")
        self.ont_traffic_fsp_filter.setEnabled(False)  # Inicialmente desabilitado
        
        # Filtro de ONT ID
        self.ont_traffic_ont_id_filter = QComboBox()
        self.ont_traffic_ont_id_filter.addItem("Todas as ONTs")
        self.ont_traffic_ont_id_filter.setEnabled(False)  # Inicialmente desabilitado
        
        # Conecta os sinais para atualização dinâmica
        self.ont_traffic_olt_filter.currentTextChanged.connect(self.update_ont_traffic_fsp_filter)
        self.ont_traffic_fsp_filter.currentTextChanged.connect(self.update_ont_traffic_ont_id_filter)
        self.ont_traffic_ont_id_filter.currentTextChanged.connect(self.load_ont_traffic_data)
        
        control_layout.addWidget(QLabel("OLT:"))
        control_layout.addWidget(self.ont_traffic_olt_filter)
        control_layout.addWidget(QLabel("F/S/P:"))
        control_layout.addWidget(self.ont_traffic_fsp_filter)
        control_layout.addWidget(QLabel("ONT ID:"))
        control_layout.addWidget(self.ont_traffic_ont_id_filter)
        
        # Botões de ação
        refresh_btn = QPushButton("Atualizar")
        refresh_btn.clicked.connect(self.load_ont_traffic_data)
        
        export_btn = QPushButton("Exportar CSV")
        export_btn.clicked.connect(self.export_ont_traffic_to_csv)
        
        control_layout.addWidget(refresh_btn)
        control_layout.addWidget(export_btn)
        control_layout.addStretch()
        layout.addWidget(control_panel)
        
        # Tabela de dados
        self.ont_traffic_table = QTableWidget()
        self.ont_traffic_table.setColumnCount(6)
        self.ont_traffic_table.setHorizontalHeaderLabels([
            "OLT", "F/S/P", "ONT ID", "Upload (kbps/Mbps)", "Download (kbps/Mbps)", "Hora"
        ])
        self.ont_traffic_table.setSortingEnabled(True)
        self.ont_traffic_table.setEditTriggers(QTableWidget.NoEditTriggers)
        
        # Ajusta a altura das linhas para acomodar duas linhas de texto
        self.ont_traffic_table.verticalHeader().setDefaultSectionSize(40)
        
        layout.addWidget(self.ont_traffic_table)
        
        # --- RODAPÉ COM CONTADOR DE REGISTROS ---
        footer_panel = QWidget()
        footer_layout = QHBoxLayout(footer_panel)
        footer_layout.setContentsMargins(0, 5, 0, 0)
        
        # Adiciona o contador de registros
        self.ont_traffic_record_count = QLabel("Status: 0 registros")
        self.ont_traffic_record_count.setStyleSheet("color: #666; font-size: 10px;")
        footer_layout.addWidget(self.ont_traffic_record_count)
        footer_layout.addStretch()
        
        layout.addWidget(footer_panel)
        
        # Timer para atualização automática
        self.ont_traffic_timer = QTimer(self)
        self.ont_traffic_timer.setInterval(60000)  # 1 minuto
        
        # Carrega as OLTs disponíveis
        self.load_ont_traffic_olt_list()

    def load_ont_traffic_olt_list(self):
        """Carrega a lista de OLTs disponíveis na tabela de tráfego ONT"""
        try:
            self.ont_traffic_olt_filter.blockSignals(True)
            self.ont_traffic_olt_filter.clear()
            self.ont_traffic_olt_filter.addItem("Todas as OLTs")
            
            # Verifica se a conexão está ativa
            if not self.conn or self.conn.closed:
                logging.warning("Conexão com o banco fechada, tentando reconectar...")
                self.connect_to_db()
                if not self.conn or self.conn.closed:
                    raise Exception("Não foi possível estabelecer conexão com o banco de dados")
            
            # Busca OLTs distintas na tabela de tráfego
            query = "SELECT DISTINCT olt_ip FROM ont_traffic_data ORDER BY olt_ip"
            self.cursor.execute(query)
            olts = [row[0] for row in self.cursor.fetchall()]
            
            for olt_ip in olts:
                self.ont_traffic_olt_filter.addItem(f"OLT {olt_ip}")
            
            self.ont_traffic_olt_filter.blockSignals(False)
            logging.info(f"OLTs carregadas para filtro de tráfego ONT: {olts}")
            
            # Se houver OLTs, seleciona a primeira por padrão
            if olts and self.ont_traffic_olt_filter.count() > 1:
                self.ont_traffic_olt_filter.setCurrentIndex(1)  # Pula "Todas as OLTs"
                logging.info(f"OLT padrão selecionada: {self.ont_traffic_olt_filter.currentText()}")
                
        except Exception as e:
            logging.error(f"Erro ao carregar OLTs para filtro de tráfego ONT: {e}", exc_info=True)
            if self.conn:
                self.conn.rollback()
            self.ont_traffic_olt_filter.addItem("Erro ao carregar")
            self.ont_traffic_olt_filter.blockSignals(False)


    def update_ont_traffic_fsp_filter(self):
        """Atualiza o filtro de F/S/P com base na OLT selecionada."""
        self.ont_traffic_fsp_filter.blockSignals(True)
        self.ont_traffic_fsp_filter.clear()
        self.ont_traffic_fsp_filter.addItem("Todas as PONs")
        
        # Bloqueia os filtros dependentes
        self.ont_traffic_ont_id_filter.blockSignals(True)
        self.ont_traffic_ont_id_filter.clear()
        self.ont_traffic_ont_id_filter.addItem("Todas as ONTs")
        self.ont_traffic_ont_id_filter.setEnabled(False)
        self.ont_traffic_ont_id_filter.blockSignals(False)
        
        selected_olt = self.ont_traffic_olt_filter.currentText()
        logging.info(f"Atualizando F/S/P para OLT: {selected_olt}")
        
        if selected_olt and selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
            try:
                # Extrai o IP da OLT do formato "OLT X.X.X.X" ou "X.X.X.X"
                olt_ip = selected_olt.split()[-1]
                
                # Busca os F/S/P distintos para essa OLT na tabela de tráfego
                query = "SELECT DISTINCT fsp FROM ont_traffic_data WHERE olt_ip = %s ORDER BY fsp;"
                self.cursor.execute(query, (olt_ip,))
                fsps = [row[0] for row in self.cursor.fetchall()]
                
                logging.info(f"F/S/P encontrados para {olt_ip}: {fsps}")
                
                self.ont_traffic_fsp_filter.addItems(fsps)
                
                # Habilita o filtro de F/S/P
                self.ont_traffic_fsp_filter.setEnabled(True)
                
                # Se houver F/S/P, seleciona o primeiro
                if fsps:
                    self.ont_traffic_fsp_filter.setCurrentIndex(0)
            except Exception as e:
                logging.error(f"Erro ao carregar FSPs para o filtro de tráfego ONT: {e}")
                if self.conn:
                    self.conn.rollback()
        else:
            logging.info("Nenhuma OLT selecionada, F/S/P não será filtrado")
            # Desabilita o filtro de F/S/P se nenhuma OLT for selecionada
            self.ont_traffic_fsp_filter.setEnabled(False)
        
        self.ont_traffic_fsp_filter.blockSignals(False)
        
        # Carrega os dados após atualizar os filtros
        self.load_ont_traffic_data()

    def update_ont_traffic_ont_id_filter(self):
        """Atualiza o filtro de ONT ID com base na OLT e F/S/P selecionados para a aba de tráfego ONT."""
        selected_olt = self.ont_traffic_olt_filter.currentText()
        selected_fsp = self.ont_traffic_fsp_filter.currentText()
        
        # Bloqueia sinais
        self.ont_traffic_ont_id_filter.blockSignals(True)
        self.ont_traffic_ont_id_filter.clear()
        self.ont_traffic_ont_id_filter.addItem("Todas as ONTs")
        
        if selected_olt and selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
            try:
                # Extrai o IP da OLT
                olt_ip = selected_olt.split()[-1] if "OLT" in selected_olt else selected_olt
                
                if selected_fsp and selected_fsp != "Todas as PONs":
                    # Busca ONT IDs distintos para essa OLT e F/S/P
                    query = "SELECT DISTINCT ont_id FROM ont_traffic_data WHERE olt_ip = %s AND fsp = %s ORDER BY ont_id"
                    self.cursor.execute(query, (olt_ip, selected_fsp))
                    ont_ids = [row[0] for row in self.cursor.fetchall()]
                    
                    for ont_id in ont_ids:
                        self.ont_traffic_ont_id_filter.addItem(str(ont_id))
                    
                    # Habilita o filtro de ONT ID
                    self.ont_traffic_ont_id_filter.setEnabled(True)
                    
                    logging.info(f"ONT IDs carregados para {olt_ip}, F/S/P {selected_fsp}: {ont_ids}")
                else:
                    # Se "Todas as PONs" for selecionado, busca todos os ONT IDs da OLT
                    query = "SELECT DISTINCT ont_id FROM ont_traffic_data WHERE olt_ip = %s ORDER BY ont_id"
                    self.cursor.execute(query, (olt_ip,))
                    ont_ids = [row[0] for row in self.cursor.fetchall()]
                    
                    for ont_id in ont_ids:
                        self.ont_traffic_ont_id_filter.addItem(str(ont_id))
                    
                    self.ont_traffic_ont_id_filter.setEnabled(True)
                    
                    logging.info(f"ONT IDs carregados para {olt_ip} (todas as PONs): {ont_ids}")
            except Exception as e:
                logging.error(f"Erro ao carregar ONT IDs para filtro de tráfego ONT: {e}")
                if self.conn:
                    self.conn.rollback()
        else:
            # Desabilita o filtro de ONT ID se nenhuma OLT for selecionada
            self.ont_traffic_ont_id_filter.setEnabled(False)
            logging.info("Nenhuma OLT selecionada, filtro de ONT ID desabilitado")
        
        self.ont_traffic_ont_id_filter.blockSignals(False)
        
        # Carrega os dados após atualizar os filtros
        self.load_ont_traffic_data()

    def export_ont_traffic_to_csv(self):
        """Exporta os dados da tabela de tráfego ONT para um arquivo CSV"""
        if self.ont_traffic_table.rowCount() == 0:
            QMessageBox.information(self, "Nada para Exportar", "A tabela de tráfego ONT está vazia.")
            return
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Exportar Tráfego ONT", 
            f"ont_traffic_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "Arquivos CSV (*.csv);;Todos os Arquivos (*)"
        )
        
        if not filename:
            return
        
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile, delimiter=';')
                
                # Escreve cabeçalho com ambas as unidades
                headers = [
                    "OLT", 
                    "F/S/P", 
                    "ONT ID", 
                    "Upload (kbps)", 
                    "Upload (Mbps)", 
                    "Download (kbps)", 
                    "Download (Mbps)", 
                    "Hora"
                ]
                writer.writerow(headers)
                
                # Escreve dados
                for row in range(self.ont_traffic_table.rowCount()):
                    # Obtém os valores básicos
                    olt_ip = self.ont_traffic_table.item(row, 0).text()
                    fsp = self.ont_traffic_table.item(row, 1).text()
                    ont_id = self.ont_traffic_table.item(row, 2).text()
                    hora = self.ont_traffic_table.item(row, 5).text()
                    
                    # Processa o valor de Upload
                    upload_text = self.ont_traffic_table.item(row, 3).text()
                    if upload_text != "N/A":
                        # Extrai o valor em kbps (primeiro número antes do espaço)
                        upload_kbps = float(upload_text.split()[0])
                        upload_mbps = upload_kbps / 1000
                    else:
                        upload_kbps = "N/A"
                        upload_mbps = "N/A"
                    
                    # Processa o valor de Download
                    download_text = self.ont_traffic_table.item(row, 4).text()
                    if download_text != "N/A":
                        # Extrai o valor em kbps (primeiro número antes do espaço)
                        download_kbps = float(download_text.split()[0])
                        download_mbps = download_kbps / 1000
                    else:
                        download_kbps = "N/A"
                        download_mbps = "N/A"
                    
                    # Escreve a linha no CSV
                    row_data = [
                        olt_ip,
                        fsp,
                        ont_id,
                        upload_kbps,
                        upload_mbps,
                        download_kbps,
                        download_mbps,
                        hora
                    ]
                    writer.writerow(row_data)
            
            QMessageBox.information(self, "Exportação Concluída", 
                                f"Dados exportados com sucesso para:\n{filename}")
            logging.info(f"Dados de tráfego ONT exportados para {filename}")
            
        except Exception as e:
            logging.error(f"Erro ao exportar dados de tráfego ONT: {e}")
            QMessageBox.critical(self, "Erro de Exportação", 
                            f"Não foi possível exportar os dados:\n{str(e)}")

    def update_ont_traffic_ont_id_filter(self):
        """Atualiza o filtro de ONT ID com base na OLT e F/S/P selecionados para a aba de tráfego ONT."""
        selected_olt = self.ont_traffic_olt_filter.currentText()
        selected_fsp = self.ont_traffic_fsp_filter.currentText()
        
        # Bloqueia sinais
        self.ont_traffic_ont_id_filter.blockSignals(True)
        self.ont_traffic_ont_id_filter.clear()
        self.ont_traffic_ont_id_filter.addItem("Todas as ONTs")
        
        if selected_olt and selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
            try:
                # Extrai o IP da OLT
                olt_ip = selected_olt.split()[-1] if "OLT" in selected_olt else selected_olt
                
                if selected_fsp and selected_fsp != "Todas as PONs":
                    # Busca ONT IDs distintos para essa OLT e F/S/P
                    query = "SELECT DISTINCT ont_id FROM ont_traffic_data WHERE olt_ip = %s AND fsp = %s ORDER BY ont_id"
                    self.cursor.execute(query, (olt_ip, selected_fsp))
                    ont_ids = [row[0] for row in self.cursor.fetchall()]
                    
                    for ont_id in ont_ids:
                        self.ont_traffic_ont_id_filter.addItem(str(ont_id))
                    
                    # Habilita o filtro de ONT ID
                    self.ont_traffic_ont_id_filter.setEnabled(True)
                    
                    logging.info(f"ONT IDs carregados para {olt_ip}, F/S/P {selected_fsp}: {ont_ids}")
                else:
                    # Se "Todas as PONs" for selecionado, busca todos os ONT IDs da OLT
                    query = "SELECT DISTINCT ont_id FROM ont_traffic_data WHERE olt_ip = %s ORDER BY ont_id"
                    self.cursor.execute(query, (olt_ip,))
                    ont_ids = [row[0] for row in self.cursor.fetchall()]
                    
                    for ont_id in ont_ids:
                        self.ont_traffic_ont_id_filter.addItem(str(ont_id))
                    
                    self.ont_traffic_ont_id_filter.setEnabled(True)
                    
                    logging.info(f"ONT IDs carregados para {olt_ip} (todas as PONs): {ont_ids}")
            except Exception as e:
                logging.error(f"Erro ao carregar ONT IDs para filtro de tráfego ONT: {e}")
                if self.conn:
                    self.conn.rollback()
        else:
            # Desabilita o filtro de ONT ID se nenhuma OLT for selecionada
            self.ont_traffic_ont_id_filter.setEnabled(False)
            logging.info("Nenhuma OLT selecionada, filtro de ONT ID desabilitado")
        
        self.ont_traffic_ont_id_filter.blockSignals(False)
        
        # Carrega os dados após atualizar os filtros
        self.load_ont_traffic_data()

    def load_ont_traffic_data(self):
        """Carrega os dados de tráfego por ONT para exibição na tabela."""
        # Verifica se já está em execução para evitar chamadas duplicadas
        if hasattr(self, '_loading_ont_traffic') and self._loading_ont_traffic:
            return
        
        self._loading_ont_traffic = True
        logging.info("Carregando dados de tráfego por ONT.")
        
        try:
            # Mostrar indicador de carregamento
            if hasattr(self, 'traffic_loading_label'):
                self.traffic_loading_label.setVisible(True)
                QApplication.processEvents()  # Força atualização da UI
            
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()
            
            # Obter os filtros selecionados
            selected_olt = self.ont_traffic_olt_filter.currentText()
            selected_fsp = self.ont_traffic_fsp_filter.currentText()
            selected_ont_id = self.ont_traffic_ont_id_filter.currentText()
            
            # Construir a consulta SQL com base nos filtros
            query = """
                SELECT olt_ip, fsp, ont_id, up_traffic_kbps, down_traffic_kbps, collection_time
                FROM ont_traffic_data
                WHERE collection_time >= NOW() - INTERVAL '24 hours'
            """
            
            params = []
            
            # Aplicar filtro de OLT se selecionado
            if selected_olt and selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
                # Extrai o IP da OLT do formato "OLT X.X.X.X" ou "X.X.X.X"
                olt_ip = selected_olt.split()[-1]
                query += " AND olt_ip = %s"
                params.append(olt_ip)
                logging.info(f"Filtrando por OLT: {olt_ip}")
            
            # Aplicar filtro de F/S/P se selecionado
            if selected_fsp and selected_fsp != "Todas as PONs":
                query += " AND fsp = %s"
                params.append(selected_fsp)
                logging.info(f"Filtrando por F/S/P: {selected_fsp}")
            
            # Aplicar filtro de ONT ID se selecionado
            if selected_ont_id and selected_ont_id != "Todas as ONTs":
                try:
                    ont_id_num = int(selected_ont_id)
                    query += " AND ont_id = %s"
                    params.append(ont_id_num)
                    logging.info(f"Filtrando por ONT ID: {ont_id_num}")
                except ValueError:
                    logging.warning(f"ONT ID inválido: {selected_ont_id}")
            
            query += " ORDER BY collection_time DESC LIMIT 5000"
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            
            logging.info(f"Consulta executada: {query}")
            logging.info(f"Parâmetros: {params}")
            logging.info(f"Resultados encontrados: {len(results)}")
            
            # Atualizar a tabela com os resultados
            self.ont_traffic_table.setSortingEnabled(False)
            self.ont_traffic_table.setRowCount(len(results))
            
            for row_idx, row_data in enumerate(results):
                olt_ip, fsp, ont_id, up_traffic, down_traffic, collection_time = row_data
                
                # Preenche as colunas básicas
                self.ont_traffic_table.setItem(row_idx, 0, QTableWidgetItem(olt_ip))
                self.ont_traffic_table.setItem(row_idx, 1, QTableWidgetItem(fsp))
                self.ont_traffic_table.setItem(row_idx, 2, QTableWidgetItem(str(ont_id)))
                
                # Formata o Upload com conversão para Mbps
                if up_traffic is not None:
                    up_mbps = up_traffic / 1000  # Converte kbps para Mbps
                    up_text = f"{up_traffic:.2f} kbps\n({up_mbps:.2f} Mbps)"
                    self.ont_traffic_table.setItem(row_idx, 3, QTableWidgetItem(up_text))
                else:
                    self.ont_traffic_table.setItem(row_idx, 3, QTableWidgetItem("N/A"))
                
                # Formata o Download com conversão para Mbps
                if down_traffic is not None:
                    down_mbps = down_traffic / 1000  # Converte kbps para Mbps
                    down_text = f"{down_traffic:.2f} kbps\n({down_mbps:.2f} Mbps)"
                    self.ont_traffic_table.setItem(row_idx, 4, QTableWidgetItem(down_text))
                else:
                    self.ont_traffic_table.setItem(row_idx, 4, QTableWidgetItem("N/A"))
                
                # Formata a data/hora para exibição
                formatted_time = collection_time.strftime('%d/%m/%Y %H:%M:%S') if collection_time else "N/A"
                self.ont_traffic_table.setItem(row_idx, 5, QTableWidgetItem(formatted_time))
            
            self.ont_traffic_table.setSortingEnabled(True)
            self.ont_traffic_table.resizeColumnsToContents()
            
            # Ajusta a altura das linhas para acomodar duas linhas de texto
            for row in range(self.ont_traffic_table.rowCount()):
                self.ont_traffic_table.setRowHeight(row, 40)
            
            logging.info(f"Tabela de tráfego ONT atualizada com {len(results)} registros.")
            
            # Atualiza o contador de registros com estilo normal
            if hasattr(self, 'ont_traffic_record_count'):
                self.ont_traffic_record_count.setText(f"Status: {len(results)} registros carregados")
                self.ont_traffic_record_count.setStyleSheet("color: green; font-weight: bold;")
            
        except Exception as e:
            logging.error(f"Erro ao carregar dados de tráfego por ONT: {str(e)}", exc_info=True)
            
            # Atualiza o contador para mostrar erro com estilo vermelho e negrito
            if hasattr(self, 'ont_traffic_record_count'):
                self.ont_traffic_record_count.setText("Status: Erro ao carregar dados")
                self.ont_traffic_record_count.setStyleSheet("color: red; font-weight: bold;")
            
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
            # Esconder indicador de carregamento
            if hasattr(self, 'traffic_loading_label'):
                self.traffic_loading_label.setVisible(False)
            self._loading_ont_traffic = False  # Libera o flag

    def update_ont_traffic_display(self):
        """Atualiza a exibição de tráfego de ONT se a aba estiver ativa."""
        if self.tab_widget.currentWidget() == self.ont_traffic_tab:
            self.load_ont_traffic_data()

    def load_olt_list_for_traffic_tab(self):
        """Carrega a lista de OLTs disponíveis na tabela de tráfego para o filtro."""
        try:
            self.ont_traffic_olt_filter.blockSignals(True)
            self.ont_traffic_olt_filter.clear()
            self.ont_traffic_olt_filter.addItem("Todas as OLTs")
            
            # Busca OLTs distintas na tabela de tráfego
            query = "SELECT DISTINCT olt_ip FROM ont_traffic_data ORDER BY olt_ip;"
            self.cursor.execute(query)
            olts = [row[0] for row in self.cursor.fetchall()]
            
            for olt_ip in olts:
                self.ont_traffic_olt_filter.addItem(f"OLT {olt_ip}")
            
            self.ont_traffic_olt_filter.blockSignals(False)
            logging.info(f"OLTs carregadas para filtro de tráfego: {olts}")
        except Exception as e:
            logging.error(f"Erro ao carregar lista de OLTs para filtro de tráfego: {e}")
            if self.conn:
                self.conn.rollback()

    def setup_ont_stats_tab(self):
        """Configura a interface da aba 'Estatísticas de ONT'."""
        layout = QVBoxLayout(self.ont_stats_tab)
        
        # --- PAINEL DE CONTROLE COM FILTROS ---
        control_panel = QWidget()
        control_layout = QHBoxLayout(control_panel)
        
        # Filtro de OLT
        self.ont_stats_olt_filter = QComboBox()
        if self.ont_stats_olt_filter not in self.olt_filters_to_update:
            self.olt_filters_to_update.append(self.ont_stats_olt_filter)
        
        # Filtro de F/S/P
        self.ont_stats_fsp_filter = QComboBox()
        self.ont_stats_fsp_filter.addItem("Todas as PONs")
        self.ont_stats_fsp_filter.setEnabled(False)  # Inicialmente desabilitado
        
        # Filtro de ONT ID
        self.ont_stats_ont_id_filter = QComboBox()
        self.ont_stats_ont_id_filter.addItem("Todas as ONTs")
        self.ont_stats_ont_id_filter.setEnabled(False)  # Inicialmente desabilitado
        
        # Conecta os sinais para atualização dinâmica
        self.ont_stats_olt_filter.currentTextChanged.connect(self.update_ont_stats_fsp_filter)
        self.ont_stats_fsp_filter.currentTextChanged.connect(self.update_ont_stats_ont_id_filter)
        self.ont_stats_ont_id_filter.currentTextChanged.connect(self.load_ont_stats_data)
        
        control_layout.addWidget(QLabel("Filtrar por OLT:"))
        control_layout.addWidget(self.ont_stats_olt_filter)
        control_layout.addWidget(QLabel("Filtrar por F/S/P:"))
        control_layout.addWidget(self.ont_stats_fsp_filter)
        control_layout.addWidget(QLabel("Filtrar por ONT ID:"))
        control_layout.addWidget(self.ont_stats_ont_id_filter)
        
        # Botões de ação
        refresh_btn = QPushButton("Atualizar")
        refresh_btn.clicked.connect(self.load_ont_stats_data)
        
        export_btn = QPushButton("Exportar CSV")
        export_btn.clicked.connect(self.export_ont_stats_to_csv)
        
        control_layout.addWidget(refresh_btn)
        control_layout.addWidget(export_btn)
        control_layout.addStretch()
        layout.addWidget(control_panel)
        
        # --- TABELA DE DADOS ---
        self.ont_stats_table = QTableWidget()
        self.ont_stats_table.setColumnCount(9)
        self.ont_stats_table.setHorizontalHeaderLabels([
            "F/S/P", "ONT ID", "Hora", "Up Frames", "Up Bytes", "Up Discard",
            "Down Frames", "Down Bytes", "Down Discard"
        ])
        self.ont_stats_table.setSortingEnabled(True)
        self.ont_stats_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.ont_stats_table)
        
        # --- RODAPÉ COM CONTADOR DE REGISTROS ---
        footer_panel = QWidget()
        footer_layout = QHBoxLayout(footer_panel)
        footer_layout.setContentsMargins(0, 5, 0, 0)
        
        # Adiciona o contador de registros
        self.ont_stats_record_count = QLabel("Status: 0 registros")
        self.ont_stats_record_count.setStyleSheet("color: green; font-weight: bold;")
        footer_layout.addWidget(self.ont_stats_record_count)
        footer_layout.addStretch()
        
        layout.addWidget(footer_panel)
        
        # --- TIMER PARA ATUALIZAÇÃO AUTOMÁTICA ---
        self.ont_stats_timer = QTimer(self)
        self.ont_stats_timer.setInterval(60000) # Atualiza a cada 60 segundos
        self.ont_stats_timer.timeout.connect(self.load_ont_stats_data)
        
        # Carrega as OLTs disponíveis
        self.load_ont_stats_olt_list()

    def load_ont_stats_olt_list(self):
        """Carrega a lista de OLTs disponíveis na tabela de estatísticas de ONT"""
        try:
            self.ont_stats_olt_filter.blockSignals(True)
            self.ont_stats_olt_filter.clear()
            self.ont_stats_olt_filter.addItem("Todas as OLTs")
            
            # Verifica se a conexão está ativa
            if not self.conn or self.conn.closed:
                logging.warning("Conexão com o banco fechada, tentando reconectar...")
                self.connect_to_db()
                if not self.conn or self.conn.closed:
                    raise Exception("Não foi possível estabelecer conexão com o banco de dados")
            
            # Busca OLTs distintas na tabela de estatísticas
            query = "SELECT DISTINCT olt_identifier FROM ont_statistics_packets ORDER BY olt_identifier"
            self.cursor.execute(query)
            olts = [row[0] for row in self.cursor.fetchall()]
            
            for olt in olts:
                self.ont_stats_olt_filter.addItem(f"OLT {olt}")
            
            self.ont_stats_olt_filter.blockSignals(False)
            logging.info(f"OLTs carregadas para filtro de estatísticas de ONT: {olts}")
            
            # Se houver OLTs, seleciona a primeira por padrão
            if olts and self.ont_stats_olt_filter.count() > 1:
                self.ont_stats_olt_filter.setCurrentIndex(1)  # Pula "Todas as OLTs"
                logging.info(f"OLT padrão selecionada: {self.ont_stats_olt_filter.currentText()}")
                
        except Exception as e:
            logging.error(f"Erro ao carregar OLTs para filtro de estatísticas de ONT: {e}", exc_info=True)
            if self.conn:
                self.conn.rollback()
            self.ont_stats_olt_filter.addItem("Erro ao carregar")
            self.ont_stats_olt_filter.blockSignals(False)

    def update_ont_stats_fsp_filter(self):
        """Atualiza o filtro de F/S/P com base na OLT selecionada para a aba de estatísticas de ONT."""
        selected_olt = self.ont_stats_olt_filter.currentText()
        
        # Bloqueia sinais para evitar chamadas recursivas
        self.ont_stats_fsp_filter.blockSignals(True)
        self.ont_stats_fsp_filter.clear()
        self.ont_stats_fsp_filter.addItem("Todas as PONs")
        
        # Bloqueia os filtros dependentes
        self.ont_stats_ont_id_filter.blockSignals(True)
        self.ont_stats_ont_id_filter.clear()
        self.ont_stats_ont_id_filter.addItem("Todas as ONTs")
        self.ont_stats_ont_id_filter.setEnabled(False)
        self.ont_stats_ont_id_filter.blockSignals(False)
        
        if selected_olt and selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
            try:
                # Extrai o identificador da OLT
                olt_identifier = selected_olt.split()[-1] if "OLT" in selected_olt else selected_olt
                
                # Busca F/S/P distintos para essa OLT
                query = "SELECT DISTINCT fsp FROM ont_statistics_packets WHERE olt_identifier = %s ORDER BY fsp;"
                self.cursor.execute(query, (olt_identifier,))
                fsps = [row[0] for row in self.cursor.fetchall()]
                
                for fsp in fsps:
                    self.ont_stats_fsp_filter.addItem(fsp)
                
                # Habilita o filtro de F/S/P
                self.ont_stats_fsp_filter.setEnabled(True)
                
                logging.info(f"F/S/P carregados para {olt_identifier}: {fsps}")
            except Exception as e:
                logging.error(f"Erro ao carregar F/S/P para o filtro de estatísticas de ONT: {e}")
                if self.conn:
                    self.conn.rollback()
        else:
            # Desabilita o filtro de F/S/P se nenhuma OLT for selecionada
            self.ont_stats_fsp_filter.setEnabled(False)
            logging.info("Nenhuma OLT selecionada, filtro de F/S/P desabilitado")
        
        self.ont_stats_fsp_filter.blockSignals(False)
        
        # Carrega os dados após atualizar os filtros
        self.load_ont_stats_data()

    def update_ont_stats_ont_id_filter(self):
        """Atualiza o filtro de ONT ID com base na OLT e F/S/P selecionados para a aba de estatísticas de ONT."""
        selected_olt = self.ont_stats_olt_filter.currentText()
        selected_fsp = self.ont_stats_fsp_filter.currentText()
        
        # Bloqueia sinais
        self.ont_stats_ont_id_filter.blockSignals(True)
        self.ont_stats_ont_id_filter.clear()
        self.ont_stats_ont_id_filter.addItem("Todas as ONTs")
        
        if selected_olt and selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
            try:
                # Extrai o identificador da OLT
                olt_identifier = selected_olt.split()[-1] if "OLT" in selected_olt else selected_olt
                
                if selected_fsp and selected_fsp != "Todas as PONs":
                    # Busca ONT IDs distintos para essa OLT e F/S/P
                    query = "SELECT DISTINCT ont_id FROM ont_statistics_packets WHERE olt_identifier = %s AND fsp = %s ORDER BY ont_id"
                    self.cursor.execute(query, (olt_identifier, selected_fsp))
                    ont_ids = [row[0] for row in self.cursor.fetchall()]
                    
                    for ont_id in ont_ids:
                        self.ont_stats_ont_id_filter.addItem(str(ont_id))
                    
                    # Habilita o filtro de ONT ID
                    self.ont_stats_ont_id_filter.setEnabled(True)
                    
                    logging.info(f"ONT IDs carregados para {olt_identifier}, F/S/P {selected_fsp}: {ont_ids}")
                else:
                    # Se "Todas as PONs" for selecionado, busca todos os ONT IDs da OLT
                    query = "SELECT DISTINCT ont_id FROM ont_statistics_packets WHERE olt_identifier = %s ORDER BY ont_id"
                    self.cursor.execute(query, (olt_identifier,))
                    ont_ids = [row[0] for row in self.cursor.fetchall()]
                    
                    for ont_id in ont_ids:
                        self.ont_stats_ont_id_filter.addItem(str(ont_id))
                    
                    self.ont_stats_ont_id_filter.setEnabled(True)
                    
                    logging.info(f"ONT IDs carregados para {olt_identifier} (todas as PONs): {ont_ids}")
            except Exception as e:
                logging.error(f"Erro ao carregar ONT IDs para filtro de estatísticas de ONT: {e}")
                if self.conn:
                    self.conn.rollback()
        else:
            # Desabilita o filtro de ONT ID se nenhuma OLT for selecionada
            self.ont_stats_ont_id_filter.setEnabled(False)
            logging.info("Nenhuma OLT selecionada, filtro de ONT ID desabilitado")
        
        self.ont_stats_ont_id_filter.blockSignals(False)
        
        # Carrega os dados após atualizar os filtros
        self.load_ont_stats_data()


    def load_ont_stats_data(self):
        """Carrega os dados de estatísticas de pacotes por ONT com base nos filtros selecionados."""
        if not self.isVisible() or self.tab_widget.currentWidget() != self.ont_stats_tab:
            return
        
        logging.info("Carregando estatísticas de pacotes de ONT.")
        self.ont_stats_table.setSortingEnabled(False)
        self.ont_stats_table.setRowCount(0)
        
        selected_olt = self.ont_stats_olt_filter.currentText()
        selected_fsp = self.ont_stats_fsp_filter.currentText()
        selected_ont_id = self.ont_stats_ont_id_filter.currentText()
        
        conditions = []
        params = []
        
        # Aplicar filtro de OLT se selecionado
        if selected_olt and selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
            olt_identifier = selected_olt.split()[-1] if "OLT" in selected_olt else selected_olt
            conditions.append("olt_identifier = %s")
            params.append(olt_identifier)
        
        # Aplicar filtro de F/S/P se selecionado
        if selected_fsp and selected_fsp != "Todas as PONs":
            conditions.append("fsp = %s")
            params.append(selected_fsp)
        
        # Aplicar filtro de ONT ID se selecionado
        if selected_ont_id and selected_ont_id != "Todas as ONTs":
            try:
                ont_id_num = int(selected_ont_id)
                conditions.append("ont_id = %s")
                params.append(ont_id_num)
            except ValueError:
                logging.warning(f"ONT ID inválido: {selected_ont_id}")
        
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        
        query = f"""
            SELECT fsp, ont_id, collection_time, upstream_frames, upstream_bytes,
                upstream_discarded_frames, downstream_frames, downstream_bytes,
                downstream_discarded_frames
            FROM ont_statistics_packets {where_clause} ORDER BY collection_time DESC LIMIT 1000;
        """
        
        try:
            self.cursor.execute(query, tuple(params))
            results = self.cursor.fetchall()
            
            self.ont_stats_table.setRowCount(len(results))
            for row_idx, record in enumerate(results):
                (fsp, ont_id, ts, up_f, up_b, up_d, down_f, down_b, down_d) = record
                
                # Cria os itens da tabela
                items = [
                    QTableWidgetItem(fsp),
                    QTableWidgetItem(str(ont_id)),
                    QTableWidgetItem(ts.strftime('%d/%m %H:%M:%S')),
                    QTableWidgetItem(f"{up_f:,}" if up_f is not None else "0"),
                    QTableWidgetItem(f"{up_b:,}" if up_b is not None else "0"),
                    QTableWidgetItem(f"{up_d:,}" if up_d is not None else "0"),
                    QTableWidgetItem(f"{down_f:,}" if down_f is not None else "0"),
                    QTableWidgetItem(f"{down_b:,}" if down_b is not None else "0"),
                    QTableWidgetItem(f"{down_d:,}" if down_d is not None else "0")
                ]
                
                # Preenche a linha na tabela
                for col_idx, item in enumerate(items):
                    self.ont_stats_table.setItem(row_idx, col_idx, item)
                
                # Colore a linha inteira se houver pacotes descartados
                if (up_d and up_d > 0) or (down_d and down_d > 0):
                    for col in range(self.ont_stats_table.columnCount()):
                        self.ont_stats_table.item(row_idx, col).setBackground(QColor("#FFCDD2")) # Vermelho claro
            
            self.ont_stats_table.resizeColumnsToContents()
            
            # Atualiza o contador de registros com estilo normal
            if hasattr(self, 'ont_stats_record_count'):
                self.ont_stats_record_count.setText(f"Status: {len(results)} registros carregados")
                self.ont_stats_record_count.setStyleSheet("color: green; font-weight: bold;")
            
            logging.info(f"{len(results)} registros de estatísticas de ONT carregados.")
            
        except Exception as e:
            logging.error(f"Erro ao carregar estatísticas de pacotes de ONT: {e}", exc_info=True)
            if self.conn: 
                self.conn.rollback() # Limpa a transação em caso de erro
            
            # Atualiza o contador para mostrar erro com estilo vermelho e negrito
            if hasattr(self, 'ont_stats_record_count'):
                self.ont_stats_record_count.setText("Status: Erro ao carregar dados")
                self.ont_stats_record_count.setStyleSheet("color: red; font-weight: bold;")
        finally:
            self.ont_stats_table.setSortingEnabled(True)

    def export_ont_stats_to_csv(self):
        """Exporta os dados da tabela de estatísticas de ONT para um arquivo CSV"""
        if self.ont_stats_table.rowCount() == 0:
            QMessageBox.information(self, "Nada para Exportar", "A tabela de estatísticas de ONT está vazia.")
            return
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Exportar Estatísticas de ONT", 
            f"ont_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "Arquivos CSV (*.csv);;Todos os Arquivos (*)"
        )
        
        if not filename:
            return
        
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile, delimiter=';')
                
                # Escreve cabeçalho
                headers = [self.ont_stats_table.horizontalHeaderItem(col).text() 
                        for col in range(self.ont_stats_table.columnCount())]
                writer.writerow(headers)
                
                # Escreve dados
                for row in range(self.ont_stats_table.rowCount()):
                    row_data = [self.ont_stats_table.item(row, col).text() 
                            for col in range(self.ont_stats_table.columnCount())]
                    writer.writerow(row_data)
            
            QMessageBox.information(self, "Exportação Concluída", 
                                f"Dados exportados com sucesso para:\n{filename}")
            logging.info(f"Dados de estatísticas de ONT exportados para {filename}")
            
        except Exception as e:
            logging.error(f"Erro ao exportar dados de estatísticas de ONT: {e}")
            QMessageBox.critical(self, "Erro de Exportação", 
                            f"Não foi possível exportar os dados:\n{str(e)}")

    def update_ont_stats_display(self):
        """Atualiza a exibição de estatísticas de pacotes de ONT se a aba estiver ativa."""
        if hasattr(self, 'ont_stats_tab') and self.tab_widget.currentWidget() == self.ont_stats_tab:
            self.load_ont_stats_data()

    def setup_ont_eth_tab(self):
        layout = QVBoxLayout(self.ont_eth_tab)
        
        # Painel de controle
        control_panel = QWidget()
        control_layout = QHBoxLayout(control_panel)
        
        # Filtro de OLT
        self.ont_eth_olt_filter_label = QLabel("OLT:")
        self.ont_eth_olt_filter = QComboBox()
        self.ont_eth_olt_filter.addItem("Todas as OLTs")
        
        # Filtro de F/S/P
        self.ont_eth_fsp_filter_label = QLabel("F/S/P:")
        self.ont_eth_fsp_filter = QComboBox()
        self.ont_eth_fsp_filter.addItem("Todas as PONs")
        self.ont_eth_fsp_filter.setEnabled(False)  # Inicialmente desabilitado
        
        # Filtro de ONT ID
        self.ont_eth_ont_id_filter_label = QLabel("ONT ID:")
        self.ont_eth_ont_id_filter = QComboBox()
        self.ont_eth_ont_id_filter.addItem("Todas as ONTs")
        self.ont_eth_ont_id_filter.setEnabled(False)  # Inicialmente desabilitado
        
        # Filtro de Porta Ethernet
        self.ont_eth_port_filter_label = QLabel("Porta ETH:")
        self.ont_eth_port_filter = QComboBox()
        self.ont_eth_port_filter.addItem("Todas as Portas")
        self.ont_eth_port_filter.setEnabled(False)  # Inicialmente desabilitado
        
        # Conecta os sinais
        self.ont_eth_olt_filter.currentTextChanged.connect(self.update_ont_eth_fsp_filter)
        self.ont_eth_fsp_filter.currentTextChanged.connect(self.update_ont_eth_ont_id_filter)
        self.ont_eth_ont_id_filter.currentTextChanged.connect(self.update_ont_eth_port_filter)
        self.ont_eth_port_filter.currentTextChanged.connect(self.load_ont_eth_data)
        
        control_layout.addWidget(self.ont_eth_olt_filter_label)
        control_layout.addWidget(self.ont_eth_olt_filter)
        control_layout.addWidget(self.ont_eth_fsp_filter_label)
        control_layout.addWidget(self.ont_eth_fsp_filter)
        control_layout.addWidget(self.ont_eth_ont_id_filter_label)
        control_layout.addWidget(self.ont_eth_ont_id_filter)
        control_layout.addWidget(self.ont_eth_port_filter_label)
        control_layout.addWidget(self.ont_eth_port_filter)
        
        # Botões de ação
        refresh_btn = QPushButton("Atualizar")
        refresh_btn.clicked.connect(self.load_ont_eth_data)
        
        export_btn = QPushButton("Exportar CSV")
        export_btn.clicked.connect(self.export_ont_eth_to_csv)
        
        # Botão para verificar estrutura
        debug_btn = QPushButton("Debug")
        debug_btn.clicked.connect(self.check_ont_eth_table_structure)
        
        control_layout.addWidget(refresh_btn)
        control_layout.addWidget(export_btn)
        control_layout.addWidget(debug_btn)
        control_layout.addStretch()
        layout.addWidget(control_panel)
        
        # Tabela de dados
        self.ont_eth_table = QTableWidget()
        self.ont_eth_table.setColumnCount(12)
        self.ont_eth_table.setHorizontalHeaderLabels([
            "F/S/P", "ONT ID", "Porta ETH", "Hora", "RX Frames", "TX Frames", 
            "RX Bytes", "TX Bytes", "RX Erros", "TX Erros", "TX Colisões", "Duração (s)"
        ])
        self.ont_eth_table.setSortingEnabled(True)
        self.ont_eth_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.ont_eth_table)
        
        # Timer para atualização automática
        self.ont_eth_timer = QTimer(self)
        self.ont_eth_timer.setInterval(60000)  # 1 minuto
        
        # Adiciona um label de status
        self.ont_eth_status_label = QLabel("Status: Pronto")
        self.ont_eth_status_label.setStyleSheet("color: green; font-weight: bold;")
        layout.addWidget(self.ont_eth_status_label)
        
        # Verifica a estrutura da tabela para debug
        logging.info("Verificando estrutura da tabela ont_eth_port_statistics...")
        self.check_ont_eth_table_structure()
        
        # Carrega as OLTs disponíveis
        self.load_ont_eth_olt_list()
        
        # Carrega os dados iniciais
        logging.info("Configuração da aba ONT Ethernet concluída. Carregando dados iniciais...")
        QTimer.singleShot(500, self.load_ont_eth_data)
        
    def load_ont_eth_olt_list(self):
        """Carrega a lista de OLTs disponíveis na tabela Ethernet"""
        try:
            self.ont_eth_olt_filter.blockSignals(True)
            self.ont_eth_olt_filter.clear()
            self.ont_eth_olt_filter.addItem("Todas as OLTs")
            
            # Verifica se a conexão está ativa
            if not self.conn or self.conn.closed:
                logging.warning("Conexão com o banco fechada, tentando reconectar...")
                self.connect_to_db()
                if not self.conn or self.conn.closed:
                    raise Exception("Não foi possível estabelecer conexão com o banco de dados")
            
            # Primeiro, verifica se a tabela existe e tem dados
            check_table_query = """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'ont_eth_port_statistics'
                )
            """
            self.cursor.execute(check_table_query)
            table_exists = self.cursor.fetchone()[0]
            
            if not table_exists:
                logging.error("A tabela 'ont_eth_port_statistics' não existe!")
                self.ont_eth_olt_filter.addItem("Tabela não encontrada")
                self.ont_eth_olt_filter.blockSignals(False)
                return
            
            # Verifica quantos registros existem
            count_query = "SELECT COUNT(*) FROM ont_eth_port_statistics"
            self.cursor.execute(count_query)
            total_count = self.cursor.fetchone()[0]
            logging.info(f"Total de registros na tabela ont_eth_port_statistics: {total_count}")
            
            if total_count == 0:
                logging.warning("A tabela ont_eth_port_statistics está vazia")
                self.ont_eth_olt_filter.addItem("Sem dados")
                self.ont_eth_olt_filter.blockSignals(False)
                return
            
            # Busca OLTs distintas na tabela Ethernet
            query = "SELECT DISTINCT olt_identifier FROM ont_eth_port_statistics ORDER BY olt_identifier"
            logging.info(f"Buscando OLTs com consulta: {query}")
            
            self.cursor.execute(query)
            olts = [row[0] for row in self.cursor.fetchall()]
            
            logging.info(f"OLTs encontradas: {olts}")
            
            for olt in olts:
                self.ont_eth_olt_filter.addItem(f"OLT {olt}")
            
            self.ont_eth_olt_filter.blockSignals(False)
            logging.info(f"OLTs carregadas para filtro Ethernet: {olts}")
            
            # Se houver OLTs, seleciona a primeira por padrão
            if olts and self.ont_eth_olt_filter.count() > 1:
                self.ont_eth_olt_filter.setCurrentIndex(1)  # Pula "Todas as OLTs"
                logging.info(f"OLT padrão selecionada: {self.ont_eth_olt_filter.currentText()}")
                
        except Exception as e:
            logging.error(f"Erro ao carregar OLTs para filtro Ethernet: {e}", exc_info=True)
            if self.conn:
                self.conn.rollback()
            self.ont_eth_olt_filter.addItem("Erro ao carregar")
            self.ont_eth_olt_filter.blockSignals(False)

    def check_ont_eth_table_structure(self):
        """Verifica a estrutura da tabela ont_eth_port_statistics"""
        try:
            # Verifica se a conexão está ativa
            if not self.conn or self.conn.closed:
                logging.warning("Conexão com o banco fechada, tentando reconectar...")
                self.connect_to_db()
                if not self.conn or self.conn.closed:
                    raise Exception("Não foi possível estabelecer conexão com o banco de dados")
            
            # Busca informações sobre as colunas
            query = """
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'ont_eth_port_statistics' 
                ORDER BY ordinal_position
            """
            self.cursor.execute(query)
            columns = self.cursor.fetchall()
            
            logging.info("Estrutura da tabela ont_eth_port_statistics:")
            for col in columns:
                logging.info(f"  {col[0]}: {col[1]}")
            
            # Busca alguns dados de exemplo
            query = "SELECT * FROM ont_eth_port_statistics LIMIT 3"
            self.cursor.execute(query)
            sample_data = self.cursor.fetchall()
            
            logging.info("Exemplo de dados na tabela:")
            for i, row in enumerate(sample_data):
                logging.info(f"  Registro {i+1}: {row}")
                
        except Exception as e:
            logging.error(f"Erro ao verificar estrutura da tabela: {e}", exc_info=True)
            if self.conn:
                self.conn.rollback()

    def update_ont_eth_fsp_filter(self):
        """Atualiza o filtro de F/S/P com base na OLT selecionada"""
        selected_olt = self.ont_eth_olt_filter.currentText()
        
        # Bloqueia sinais para evitar chamadas recursivas
        self.ont_eth_fsp_filter.blockSignals(True)
        self.ont_eth_fsp_filter.clear()
        self.ont_eth_fsp_filter.addItem("Todas as PONs")
        
        # Bloqueia os filtros dependentes
        self.ont_eth_ont_id_filter.blockSignals(True)
        self.ont_eth_ont_id_filter.clear()
        self.ont_eth_ont_id_filter.addItem("Todas as ONTs")
        self.ont_eth_ont_id_filter.setEnabled(False)
        self.ont_eth_ont_id_filter.blockSignals(False)
        
        self.ont_eth_port_filter.blockSignals(True)
        self.ont_eth_port_filter.clear()
        self.ont_eth_port_filter.addItem("Todas as Portas")
        self.ont_eth_port_filter.setEnabled(False)
        self.ont_eth_port_filter.blockSignals(False)
        
        if selected_olt and selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
            try:
                # Extrai o identificador da OLT
                olt_id = selected_olt.split()[-1] if "OLT" in selected_olt else selected_olt
                
                # Busca F/S/P distintos para essa OLT
                query = "SELECT DISTINCT fsp FROM ont_eth_port_statistics WHERE olt_identifier = %s ORDER BY fsp"
                self.cursor.execute(query, (olt_id,))
                fsps = [row[0] for row in self.cursor.fetchall()]
                
                for fsp in fsps:
                    self.ont_eth_fsp_filter.addItem(fsp)
                
                # Habilita o filtro de F/S/P
                self.ont_eth_fsp_filter.setEnabled(True)
                
                logging.info(f"F/S/P carregados para {olt_id}: {fsps}")
            except Exception as e:
                logging.error(f"Erro ao carregar F/S/P para filtro Ethernet: {e}")
                if self.conn:
                    self.conn.rollback()
        else:
            # Desabilita o filtro de F/S/P se nenhuma OLT for selecionada
            self.ont_eth_fsp_filter.setEnabled(False)
            logging.info("Nenhuma OLT selecionada, filtro de F/S/P desabilitado")
        
        self.ont_eth_fsp_filter.blockSignals(False)
        
        # Carrega os dados após atualizar os filtros
        self.load_ont_eth_data()

    def update_ont_eth_ont_id_filter(self):
        """Atualiza o filtro de ONT ID com base na OLT e F/S/P selecionados"""
        selected_olt = self.ont_eth_olt_filter.currentText()
        selected_fsp = self.ont_eth_fsp_filter.currentText()
        
        # Bloqueia sinais
        self.ont_eth_ont_id_filter.blockSignals(True)
        self.ont_eth_ont_id_filter.clear()
        self.ont_eth_ont_id_filter.addItem("Todas as ONTs")
        
        # Bloqueia o filtro de porta
        self.ont_eth_port_filter.blockSignals(True)
        self.ont_eth_port_filter.clear()
        self.ont_eth_port_filter.addItem("Todas as Portas")
        self.ont_eth_port_filter.setEnabled(False)
        self.ont_eth_port_filter.blockSignals(False)
        
        if selected_olt and selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
            try:
                # Extrai o identificador da OLT
                olt_id = selected_olt.split()[-1] if "OLT" in selected_olt else selected_olt
                
                if selected_fsp and selected_fsp != "Todas as PONs":
                    # Busca ONT IDs distintos para essa OLT e F/S/P
                    query = "SELECT DISTINCT ont_id FROM ont_eth_port_statistics WHERE olt_identifier = %s AND fsp = %s ORDER BY ont_id"
                    self.cursor.execute(query, (olt_id, selected_fsp))
                    ont_ids = [row[0] for row in self.cursor.fetchall()]
                    
                    for ont_id in ont_ids:
                        self.ont_eth_ont_id_filter.addItem(str(ont_id))
                    
                    # Habilita o filtro de ONT ID
                    self.ont_eth_ont_id_filter.setEnabled(True)
                    
                    logging.info(f"ONT IDs carregados para {olt_id}, F/S/P {selected_fsp}: {ont_ids}")
                else:
                    # Se "Todas as PONs" for selecionado, busca todos os ONT IDs da OLT
                    query = "SELECT DISTINCT ont_id FROM ont_eth_port_statistics WHERE olt_identifier = %s ORDER BY ont_id"
                    self.cursor.execute(query, (olt_id,))
                    ont_ids = [row[0] for row in self.cursor.fetchall()]
                    
                    for ont_id in ont_ids:
                        self.ont_eth_ont_id_filter.addItem(str(ont_id))
                    
                    self.ont_eth_ont_id_filter.setEnabled(True)
                    
                    logging.info(f"ONT IDs carregados para {olt_id} (todas as PONs): {ont_ids}")
            except Exception as e:
                logging.error(f"Erro ao carregar ONT IDs para filtro Ethernet: {e}")
                if self.conn:
                    self.conn.rollback()
        else:
            # Desabilita o filtro de ONT ID se nenhuma OLT for selecionada
            self.ont_eth_ont_id_filter.setEnabled(False)
            logging.info("Nenhuma OLT selecionada, filtro de ONT ID desabilitado")
        
        self.ont_eth_ont_id_filter.blockSignals(False)
        
        # Carrega os dados após atualizar os filtros
        self.load_ont_eth_data()

    def update_ont_eth_port_filter(self):
        """Atualiza o filtro de Porta Ethernet com base na OLT, F/S/P e ONT ID selecionados"""
        selected_olt = self.ont_eth_olt_filter.currentText()
        selected_fsp = self.ont_eth_fsp_filter.currentText()
        selected_ont_id = self.ont_eth_ont_id_filter.currentText()
        
        # Bloqueia sinais
        self.ont_eth_port_filter.blockSignals(True)
        self.ont_eth_port_filter.clear()
        self.ont_eth_port_filter.addItem("Todas as Portas")
        
        if selected_olt and selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
            try:
                # Extrai o identificador da OLT
                olt_id = selected_olt.split()[-1] if "OLT" in selected_olt else selected_olt
                
                if selected_ont_id and selected_ont_id != "Todas as ONTs":
                    ont_id_num = int(selected_ont_id)
                    
                    if selected_fsp and selected_fsp != "Todas as PONs":
                        # Busca portas Ethernet distintas para essa OLT, F/S/P e ONT ID
                        query = "SELECT DISTINCT eth_port_id FROM ont_eth_port_statistics WHERE olt_identifier = %s AND fsp = %s AND ont_id = %s ORDER BY eth_port_id"
                        self.cursor.execute(query, (olt_id, selected_fsp, ont_id_num))
                    else:
                        # Busca portas Ethernet distintas para essa OLT e ONT ID (todas as PONs)
                        query = "SELECT DISTINCT eth_port_id FROM ont_eth_port_statistics WHERE olt_identifier = %s AND ont_id = %s ORDER BY eth_port_id"
                        self.cursor.execute(query, (olt_id, ont_id_num))
                    
                    ports = [row[0] for row in self.cursor.fetchall()]
                    
                    for port in ports:
                        self.ont_eth_port_filter.addItem(str(port))
                    
                    # Habilita o filtro de porta
                    self.ont_eth_port_filter.setEnabled(True)
                    
                    logging.info(f"Portas Ethernet carregadas para {olt_id}, ONT {selected_ont_id}: {ports}")
                else:
                    # Se "Todas as ONTs" for selecionado, busca todas as portas da OLT
                    if selected_fsp and selected_fsp != "Todas as PONs":
                        query = "SELECT DISTINCT eth_port_id FROM ont_eth_port_statistics WHERE olt_identifier = %s AND fsp = %s ORDER BY eth_port_id"
                        self.cursor.execute(query, (olt_id, selected_fsp))
                    else:
                        query = "SELECT DISTINCT eth_port_id FROM ont_eth_port_statistics WHERE olt_identifier = %s ORDER BY eth_port_id"
                        self.cursor.execute(query, (olt_id,))
                    
                    ports = [row[0] for row in self.cursor.fetchall()]
                    
                    for port in ports:
                        self.ont_eth_port_filter.addItem(str(port))
                    
                    self.ont_eth_port_filter.setEnabled(True)
                    
                    logging.info(f"Portas Ethernet carregadas para {olt_id} (todas as ONTs): {ports}")
            except Exception as e:
                logging.error(f"Erro ao carregar portas Ethernet para filtro: {e}")
                if self.conn:
                    self.conn.rollback()
        else:
            # Desabilita o filtro de porta se nenhuma OLT for selecionada
            self.ont_eth_port_filter.setEnabled(False)
            logging.info("Nenhuma OLT selecionada, filtro de porta Ethernet desabilitado")
        
        self.ont_eth_port_filter.blockSignals(False)
        
        # Carrega os dados após atualizar os filtros
        self.load_ont_eth_data()
        
    def load_ont_eth_data(self):
        """Carrega os dados Ethernet das ONTs do banco de dados"""
        if not self.isVisible() or self.tab_widget.currentWidget() != self.ont_eth_tab: 
            return
        
        logging.info("Carregando dados Ethernet das ONTs.")
        
        selected_olt = self.ont_eth_olt_filter.currentText()
        selected_fsp = self.ont_eth_fsp_filter.currentText()
        selected_ont_id = self.ont_eth_ont_id_filter.currentText()
        selected_port = self.ont_eth_port_filter.currentText()
        
        logging.info(f"Filtros selecionados - OLT: '{selected_olt}', F/S/P: '{selected_fsp}', ONT ID: '{selected_ont_id}', Porta: '{selected_port}'")
        
        # Atualiza status
        if hasattr(self, 'ont_eth_status_label'):
            self.ont_eth_status_label.setText("Status: Carregando...")
            self.ont_eth_status_label.setStyleSheet("color: orange; font-weight: bold;")
        
        try:
            self.ont_eth_table.setSortingEnabled(False)
            self.ont_eth_table.setRowCount(0)
            
            conditions, params = [], []
            
            # Aplicar filtro de OLT se selecionado
            if selected_olt and selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
                olt_id = selected_olt.split()[-1] if "OLT" in selected_olt else selected_olt
                conditions.append("olt_identifier = %s")
                params.append(olt_id)
            
            # Aplicar filtro de F/S/P se selecionado
            if selected_fsp and selected_fsp != "Todas as PONs":
                conditions.append("fsp = %s")
                params.append(selected_fsp)
            
            # Aplicar filtro de ONT ID se selecionado
            if selected_ont_id and selected_ont_id != "Todas as ONTs":
                try:
                    ont_id_num = int(selected_ont_id)
                    conditions.append("ont_id = %s")
                    params.append(ont_id_num)
                except ValueError:
                    logging.warning(f"ONT ID inválido: {selected_ont_id}")
            
            # Aplicar filtro de Porta Ethernet se selecionado
            if selected_port and selected_port != "Todas as Portas":
                try:
                    port_num = int(selected_port)
                    conditions.append("eth_port_id = %s")
                    params.append(port_num)
                except ValueError:
                    logging.warning(f"Porta Ethernet inválida: {selected_port}")
            
            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            query = f"""
                SELECT fsp, ont_id, eth_port_id, collection_time, rx_frames, tx_frames,
                    rx_bytes, tx_bytes, rx_error_frames, tx_error_frames,
                    tx_collision_frames, duration_seconds
                FROM ont_eth_port_statistics {where_clause} 
                ORDER BY collection_time DESC LIMIT 2000;
            """
            
            logging.info(f"Executando consulta: {query}")
            logging.info(f"Parâmetros: {params}")
            
            self.cursor.execute(query, tuple(params))
            for row_idx, row in enumerate(self.cursor.fetchall()):
                self.ont_eth_table.insertRow(row_idx)
                for col_idx, data in enumerate(row):
                    item = QTableWidgetItem(str(data) if data is not None else "")
                    
                    # Aplica cores baseado em erros
                    if col_idx == 8 and data and int(data) > 0:  # RX Erros
                        item.setBackground(QColor('#ffcdd2'))
                    elif col_idx == 9 and data and int(data) > 0:  # TX Erros
                        item.setBackground(QColor('#ffcdd2'))
                    elif col_idx == 10 and data and int(data) > 0:  # TX Colisões
                        item.setBackground(QColor('#fff9c4'))
                    
                    self.ont_eth_table.setItem(row_idx, col_idx, item)
            
            self.ont_eth_table.resizeColumnsToContents()
            logging.info(f"Tabela Ethernet atualizada com {self.ont_eth_table.rowCount()} registros.")
            
            # Atualiza status
            if hasattr(self, 'ont_eth_status_label'):
                self.ont_eth_status_label.setText(f"Status: {self.ont_eth_table.rowCount()} registros carregados")
                self.ont_eth_status_label.setStyleSheet("color: green; font-weight: bold;")
                
        except Exception as e:
            logging.error(f"Erro ao carregar dados de ETH ONT: {e}")
            if self.conn:
                self.conn.rollback()
            
            # Atualiza status de erro
            if hasattr(self, 'ont_eth_status_label'):
                self.ont_eth_status_label.setText(f"Status: Erro")
                self.ont_eth_status_label.setStyleSheet("color: red; font-weight: bold;")
        
        finally:
            self.ont_eth_table.setSortingEnabled(True)
                
    def export_ont_eth_to_csv(self):
        """Exporta os dados da tabela Ethernet para um arquivo CSV"""
        if self.ont_eth_table.rowCount() == 0:
            QMessageBox.information(self, "Nada para Exportar", "A tabela Ethernet está vazia.")
            return
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Exportar Dados Ethernet", 
            f"ont_ethernet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "Arquivos CSV (*.csv);;Todos os Arquivos (*)"
        )
        
        if not filename:
            return
        
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile, delimiter=';')
                
                # Escreve cabeçalho
                headers = [self.ont_eth_table.horizontalHeaderItem(col).text() 
                        for col in range(self.ont_eth_table.columnCount())]
                writer.writerow(headers)
                
                # Escreve dados
                for row in range(self.ont_eth_table.rowCount()):
                    row_data = [self.ont_eth_table.item(row, col).text() 
                            for col in range(self.ont_eth_table.columnCount())]
                    writer.writerow(row_data)
            
            QMessageBox.information(self, "Exportação Concluída", 
                                f"Dados exportados com sucesso para:\n{filename}")
            logging.info(f"Dados Ethernet exportados para {filename}")
            
        except Exception as e:
            logging.error(f"Erro ao exportar dados Ethernet: {e}")
            QMessageBox.critical(self, "Erro de Exportação", 
                            f"Não foi possível exportar os dados:\n{str(e)}")

    # Adicione este novo método para ser o slot do sinal
    def update_ont_eth_display(self):
        if self.tab_widget.currentWidget() == self.ont_eth_tab:
            self.load_ont_eth_data()

    def setup_uplink_ddm_tab(self):
        """Configura a interface da aba 'Uplink DDM'"""
        layout = QVBoxLayout(self.uplink_ddm_tab)
        
        # Painel de controle
        control_panel = QWidget()
        control_layout = QHBoxLayout(control_panel)
        
        # Filtro de OLT
        self.uplink_ddm_olt_filter_label = QLabel("OLT:")
        self.uplink_ddm_olt_filter = QComboBox()
        self.uplink_ddm_olt_filter.addItem("Todas as OLTs")
        
        # Filtro de Slot
        self.uplink_ddm_slot_filter_label = QLabel("Slot:")
        self.uplink_ddm_slot_filter = QComboBox()
        self.uplink_ddm_slot_filter.addItem("Todos os Slots")
        self.uplink_ddm_slot_filter.setEnabled(False)  # Inicialmente desabilitado
        
        # Filtro de Porta
        self.uplink_ddm_port_filter_label = QLabel("Porta:")
        self.uplink_ddm_port_filter = QComboBox()
        self.uplink_ddm_port_filter.addItem("Todas as Portas")
        self.uplink_ddm_port_filter.setEnabled(False)  # Inicialmente desabilitado
        
        # Conecta os sinais
        self.uplink_ddm_olt_filter.currentTextChanged.connect(self.update_ddm_slot_filter)
        self.uplink_ddm_slot_filter.currentTextChanged.connect(self.update_ddm_port_filter)
        self.uplink_ddm_port_filter.currentTextChanged.connect(self.load_uplink_ddm_data)
        
        control_layout.addWidget(self.uplink_ddm_olt_filter_label)
        control_layout.addWidget(self.uplink_ddm_olt_filter)
        control_layout.addWidget(self.uplink_ddm_slot_filter_label)
        control_layout.addWidget(self.uplink_ddm_slot_filter)
        control_layout.addWidget(self.uplink_ddm_port_filter_label)
        control_layout.addWidget(self.uplink_ddm_port_filter)
        
        # Botões de ação
        refresh_btn = QPushButton("Atualizar")
        refresh_btn.clicked.connect(self.load_uplink_ddm_data)
        
        export_btn = QPushButton("Exportar CSV")
        export_btn.clicked.connect(self.export_uplink_ddm_to_csv)
        
        # Botão de legenda
        legend_btn = QPushButton("Legenda de Cores")
        legend_btn.clicked.connect(self.show_ddm_legend)
        legend_btn.setStyleSheet("background-color: #e1f5fe; font-weight: bold;")
        
        control_layout.addWidget(refresh_btn)
        control_layout.addWidget(export_btn)
        control_layout.addWidget(legend_btn)
        control_layout.addStretch()
        layout.addWidget(control_panel)
        
        # Tabela de dados DDM
        self.uplink_ddm_table = QTableWidget()
        self.uplink_ddm_table.setColumnCount(11)  # 11 colunas incluindo data/hora
        self.uplink_ddm_table.setHorizontalHeaderLabels([
            "OLT", "Placa", "Slot", "Porta", 
            "Temperatura (°C)", "Tensão (V)", 
            "Corrente Bias (mA)", "Potência TX (dBm)", 
            "Potência RX (dBm)", "Status", "Data/Hora"
        ])
        self.uplink_ddm_table.setSortingEnabled(True)
        self.uplink_ddm_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.uplink_ddm_table.setAlternatingRowColors(True)
        layout.addWidget(self.uplink_ddm_table)
        
        # Timer para atualização periódica
        self.uplink_ddm_timer = QTimer(self)
        self.uplink_ddm_timer.setInterval(300000)  # 5 minutos
        
        # Adiciona um label de status
        self.ddm_status_label = QLabel("Status: Pronto")
        self.ddm_status_label.setStyleSheet("color: green; font-weight: bold;")
        layout.addWidget(self.ddm_status_label)
        
        # Carrega as OLTs disponíveis
        self.load_ddm_olt_list()
        
        # Carrega os dados iniciais
        logging.info("Configuração da aba Uplink DDM concluída. Carregando dados iniciais...")
        QTimer.singleShot(500, self.load_uplink_ddm_data)

    def show_ddm_legend(self):
        """Exibe uma janela com a legenda de cores para os valores DDM"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Legenda de Cores - Valores DDM")
        dialog.setMinimumSize(800, 600)
        dialog.setModal(True)
        
        layout = QVBoxLayout(dialog)
        
        # Criar um widget com abas para organizar as informações
        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)
        
        # Aba 1: Temperatura
        temp_tab = QWidget()
        temp_layout = QVBoxLayout(temp_tab)
        
        temp_title = QLabel("<h2>Temperatura do Transceiver (°C)</h2>")
        temp_layout.addWidget(temp_title)
        
        temp_info = QLabel("""
        <p><b>Faixa típica de operação (comercial):</b> 0 a 70 °C</p>
        <p><b>Módulos "industrial":</b> -40 a 85 °C</p>
        <br>
        <p><b>Classificação prática (comercial):</b></p>
        <ul>
            <li><span style='background-color: #c8e6c9; padding: 2px 5px; border-radius: 3px;'>OK:</span> 10–55 °C</li>
            <li><span style='background-color: #fff9c4; padding: 2px 5px; border-radius: 3px;'>Observância:</span> 55–65 °C (verificar ventilação/poeira/fluxo de ar)</li>
            <li><span style='background-color: #ffcdd2; padding: 2px 5px; border-radius: 3px;'>Crítico:</span> ≥ 70 °C (ou ≤ 0 °C) — agir imediatamente</li>
        </ul>
        <br>
        <p><i>Baseado nos ratings de operação dos módulos 10G SR/LR comuns.</i></p>
        """)
        temp_layout.addWidget(temp_info)
        
        tab_widget.addTab(temp_tab, "Temperatura")
        
        # Aba 2: Tensão
        voltage_tab = QWidget()
        voltage_layout = QVBoxLayout(voltage_tab)
        
        voltage_title = QLabel("<h2>Tensão de Alimentação do Módulo (V)</h2>")
        voltage_layout.addWidget(voltage_title)
        
        voltage_info = QLabel("""
        <p><b>Nominal:</b> 3,3 V</p>
        <p><b>Faixa usual aceitável (DOM):</b> 3,135–3,465 V</p>
        <p><b>Alguns datasheets admitem:</b> 3,0–3,6 V</p>
        <br>
        <p><b>Classificação prática:</b></p>
        <ul>
            <li><span style='background-color: #c8e6c9; padding: 2px 5px; border-radius: 3px;'>OK:</span> 3,20–3,45 V</li>
            <li><span style='background-color: #fff9c4; padding: 2px 5px; border-radius: 3px;'>Observância:</span> 3,10–3,19 V ou 3,46–3,50 V</li>
            <li><span style='background-color: #ffcdd2; padding: 2px 5px; border-radius: 3px;'>Crítico:</span> &lt; 3,10 V (típico "low alarm") ou &gt; 3,50–3,60 V (típico "high alarm")</li>
        </ul>
        <br>
        <p><i>Use sempre os thresholds do próprio módulo exibidos no display transceiver ... verbose.</i></p>
        """)
        voltage_layout.addWidget(voltage_info)
        
        tab_widget.addTab(voltage_tab, "Tensão")
        
        # Aba 3: Corrente de Bias
        bias_tab = QWidget()
        bias_layout = QVBoxLayout(bias_tab)
        
        bias_title = QLabel("<h2>Corrente de Bias (mA)</h2>")
        bias_layout.addWidget(bias_title)
        
        bias_info = QLabel("""
        <p><b>Varia por tipo de laser/módulo</b> (VCSEL/DFB etc.) e sobe aos poucos com a idade do laser</p>
        <p><b>O que importa são os limiares DOM do módulo e a tendência</b></p>
        <br>
        <p><b>Classificação prática:</b></p>
        <ul>
            <li><span style='background-color: #c8e6c9; padding: 2px 5px; border-radius: 3px;'>OK:</span> valor estável, longe do High Warn/Alarm do módulo</li>
            <li><span style='background-color: #fff9c4; padding: 2px 5px; border-radius: 3px;'>Observância:</span> tendência de subida contínua (ex.: +20–30% vs. baseline histórico)</li>
            <li><span style='background-color: #ffcdd2; padding: 2px 5px; border-radius: 3px;'>Crítico:</span> atingiu High Alarm de bias (risco de degradação de laser; planeje troca)</li>
        </ul>
        <br>
        <p><i>O que importa é a tendência; subida contínua = laser envelhecendo. Planeje substituição quando chegar a High Warn do DOM.</i></p>
        """)
        bias_layout.addWidget(bias_info)
        
        tab_widget.addTab(bias_tab, "Corrente de Bias")
        
        # Aba 4: Potência Óptica
        power_tab = QWidget()
        power_layout = QVBoxLayout(power_tab)
        
        power_title = QLabel("<h2>Potência Óptica TX/RX (dBm)</h2>")
        power_layout.addWidget(power_title)
        
        power_info = QLabel("""
        <p><b>Faixas típicas por tipo de link:</b></p>
        
        <h3>(A) GICF – 1 GbE SFP 1310 nm 10 km</h3>
        <ul>
            <li><b>TX:</b> −9,5 a −3 dBm (datasheet comum de SFP 10 km)</li>
            <li><b>RX (sensibilidade):</b> ≤ −20 dBm; Overload: por volta de −3 dBm</li>
            <li><b>OK (RX):</b> entre −18 e −5 dBm (boa margem)</li>
            <li><b>Observância (RX):</b> próximo de −20 dBm (margem pequena) ou próximo de −3 dBm (risco de saturar)</li>
            <li><b>Crítico (RX):</b> &lt; sensibilidade (link instável) ou ≥ overload (saturação/erros)</li>
        </ul>
        
        <h3>(B) X2CS – 10 GbE SFP+ LR (1310 nm ~10 km)</h3>
        <ul>
            <li><b>TX típico:</b> −8,2 a +0,5 dBm</li>
            <li><b>RX (sensibilidade):</b> ~−14,4 dBm; Overload: ~+0,5 dBm</li>
            <li><b>OK (RX):</b> −12 a −2 dBm</li>
            <li><b>Observância (RX):</b> ≤ −13,5 dBm (margem curta) ou ≥ 0 dBm (risco de overload)</li>
            <li><b>Crítico (RX):</b> &lt; −14,4 dBm ou ≥ +0,5 dBm</li>
        </ul>
        
        <h3>(C) X2CS – 10 GbE SFP+ SR (850 nm MMF)</h3>
        <ul>
            <li><b>TX típico:</b> −7,3 a −1,2 dBm (varia por fabricante; muitos listam −7,3 a −1)</li>
            <li><b>RX (faixa):</b> ≈ −9,9 a −1,0 dBm (sensibilidade/overload)</li>
            <li><b>OK (RX):</b> −8 a −2 dBm</li>
            <li><b>Observância (RX):</b> muito próximo de −9,9 dBm (pouca margem) ou de −1 dBm (overload)</li>
            <li><b>Crítico (RX):</b> &lt; −9,9 dBm (abaixo da sensibilidade) ou ≥ −1 dBm (overload)</li>
        </ul>
        
        <br>
        <p><i>Observação: a placa H801X2CS pode usar SFP+ ou XFP/variações conforme a OLT e versão; os limiares DOM exatos são do módulo, então sempre confira no ... verbose da porta em questão.</i></p>
        """)
        power_layout.addWidget(power_info)
        
        tab_widget.addTab(power_tab, "Potência Óptica")
        
        # Aba 5: Regras de bolso
        rules_tab = QWidget()
        rules_layout = QVBoxLayout(rules_tab)
        
        rules_title = QLabel("<h2>Regras de Bolso (ajudam no dia a dia)</h2>")
        rules_layout.addWidget(rules_title)
        
        rules_info = QLabel("""
        <ul>
            <li><b>Temperatura:</b> mantenha &lt; 60 °C; acima disso investigue refrigeração/poeira/fluxo de ar</li>
            <li><b>Tensão:</b> espere ~3,3 V; &lt; 3,1 ou &gt; 3,5–3,6 V costuma gerar alarms</li>
            <li><b>Bias:</b> o que importa é a tendência; subida contínua = laser envelhecendo. Planeje substituição quando chegar a High Warn do DOM</li>
            <li><b>RX:</b> mantenha dentro de sensibilidade…overload do módulo. Se muito alto, use atenuador; se baixo, verifique limpeza dos conectores, perdas, curva de orçamento óptico</li>
            <li><b>TX fora da faixa:</b> se TX &lt; mínimo, verifique bias e sujeira/conexões; se TX &gt; máximo, pode indicar configuração/medição anômala ou módulo com APC/controle descalibrado</li>
        </ul>
        """)
        rules_layout.addWidget(rules_info)
        
        tab_widget.addTab(rules_tab, "Regras de Bolso")
        
        # Aba 6: Referência Rápida
        ref_tab = QWidget()
        ref_layout = QVBoxLayout(ref_tab)
        
        ref_title = QLabel("<h2>Exemplos de Referência Rápida (comparativo)</h2>")
        ref_layout.addWidget(ref_title)
        
        ref_table = QTableWidget()
        ref_table.setColumnCount(4)
        ref_table.setHorizontalHeaderLabels(["Tipo de link", "TX típico (dBm)", "RX sensib./overload (dBm)", "Fonte"])
        ref_table.setRowCount(3)
        
        # Linha 1: 1G 1310 nm
        ref_table.setItem(0, 0, QTableWidgetItem("1G 1310 nm 10 km (GICF)"))
        ref_table.setItem(0, 1, QTableWidgetItem("−9,5 … −3"))
        ref_table.setItem(0, 2, QTableWidgetItem("sens. ≤ −20 / overload ≈ −3"))
        ref_table.setItem(0, 3, QTableWidgetItem(""))
        
        # Linha 2: 10G LR 1310 nm
        ref_table.setItem(1, 0, QTableWidgetItem("10G LR 1310 nm 10 km (X2CS)"))
        ref_table.setItem(1, 1, QTableWidgetItem("−8,2 … +0,5"))
        ref_table.setItem(1, 2, QTableWidgetItem("sens. ≈ −14,4 / overload ≈ +0,5"))
        ref_table.setItem(1, 3, QTableWidgetItem("EDGE Optical Solutions"))
        
        # Linha 3: 10G SR 850 nm
        ref_table.setItem(2, 0, QTableWidgetItem("10G SR 850 nm MMF (X2CS)"))
        ref_table.setItem(2, 1, QTableWidgetItem("−7,3 … −1,2"))
        ref_table.setItem(2, 2, QTableWidgetItem("faixa ≈ −9,9 … −1,0"))
        ref_table.setItem(2, 3, QTableWidgetItem("Router-Switch.com"))
        
        ref_table.resizeColumnsToContents()
        ref_layout.addWidget(ref_table)
        
        tab_widget.addTab(ref_tab, "Referência Rápida")
        
        # Botão de fechar
        close_button = QPushButton("Fechar")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        
        # Exibir o diálogo
        dialog.exec_()

    def load_ddm_olt_list(self):
        """Carrega a lista de OLTs disponíveis na tabela DDM"""
        try:
            self.uplink_ddm_olt_filter.blockSignals(True)
            self.uplink_ddm_olt_filter.clear()
            self.uplink_ddm_olt_filter.addItem("Todas as OLTs")
            
            # Busca OLTs distintas na tabela DDM
            self.cursor.execute("SELECT DISTINCT olt_ip FROM uplink_ddm_data ORDER BY olt_ip")
            olts = [row[0] for row in self.cursor.fetchall()]
            
            for olt_ip in olts:
                self.uplink_ddm_olt_filter.addItem(f"OLT {olt_ip}")
            
            self.uplink_ddm_olt_filter.blockSignals(False)
            logging.info(f"OLTs carregadas para filtro DDM: {olts}")
        except Exception as e:
            logging.error(f"Erro ao carregar OLTs para filtro DDM: {e}")
            if self.conn:
                self.conn.rollback()

    def update_ddm_slot_filter(self):
        """Atualiza o filtro de Slot com base na OLT selecionada"""
        selected_olt = self.uplink_ddm_olt_filter.currentText()
        
        # Bloqueia sinais para evitar chamadas recursivas
        self.uplink_ddm_slot_filter.blockSignals(True)
        self.uplink_ddm_slot_filter.clear()
        self.uplink_ddm_slot_filter.addItem("Todos os Slots")
        
        # Bloqueia o filtro de porta até que um slot seja selecionado
        self.uplink_ddm_port_filter.blockSignals(True)
        self.uplink_ddm_port_filter.clear()
        self.uplink_ddm_port_filter.addItem("Todas as Portas")
        self.uplink_ddm_port_filter.setEnabled(False)
        self.uplink_ddm_port_filter.blockSignals(False)
        
        if selected_olt and selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
            try:
                # Extrai o IP da OLT
                olt_ip = selected_olt.split()[-1] if "OLT" in selected_olt else selected_olt
                
                # Busca slots distintos para essa OLT
                query = "SELECT DISTINCT slot FROM uplink_ddm_data WHERE olt_ip = %s ORDER BY slot"
                self.cursor.execute(query, (olt_ip,))
                slots = [row[0] for row in self.cursor.fetchall()]
                
                for slot in slots:
                    self.uplink_ddm_slot_filter.addItem(str(slot))
                
                # Habilita o filtro de slot
                self.uplink_ddm_slot_filter.setEnabled(True)
                
                logging.info(f"Slots carregados para {olt_ip}: {slots}")
            except Exception as e:
                logging.error(f"Erro ao carregar slots para filtro DDM: {e}")
                if self.conn:
                    self.conn.rollback()
        else:
            # Desabilita o filtro de slot se nenhuma OLT for selecionada
            self.uplink_ddm_slot_filter.setEnabled(False)
            logging.info("Nenhuma OLT selecionada, filtro de slot desabilitado")
        
        self.uplink_ddm_slot_filter.blockSignals(False)
        
        # Carrega os dados após atualizar os filtros
        self.load_uplink_ddm_data()

    def update_ddm_port_filter(self):
        """Atualiza o filtro de Porta com base na OLT e Slot selecionados"""
        selected_olt = self.uplink_ddm_olt_filter.currentText()
        selected_slot = self.uplink_ddm_slot_filter.currentText()
        
        # Bloqueia sinais
        self.uplink_ddm_port_filter.blockSignals(True)
        self.uplink_ddm_port_filter.clear()
        self.uplink_ddm_port_filter.addItem("Todas as Portas")
        
        if selected_olt and selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
            if selected_slot and selected_slot != "Todos os Slots":
                try:
                    # Extrai o IP da OLT
                    olt_ip = selected_olt.split()[-1] if "OLT" in selected_olt else selected_olt
                    
                    # Busca portas distintas para essa OLT e slot
                    query = "SELECT DISTINCT port FROM uplink_ddm_data WHERE olt_ip = %s AND slot = %s ORDER BY port"
                    self.cursor.execute(query, (olt_ip, selected_slot))
                    ports = [row[0] for row in self.cursor.fetchall()]
                    
                    for port in ports:
                        self.uplink_ddm_port_filter.addItem(str(port))
                    
                    # Habilita o filtro de porta
                    self.uplink_ddm_port_filter.setEnabled(True)
                    
                    logging.info(f"Portas carregadas para {olt_ip}, slot {selected_slot}: {ports}")
                except Exception as e:
                    logging.error(f"Erro ao carregar portas para filtro DDM: {e}")
                    if self.conn:
                        self.conn.rollback()
            else:
                # Se "Todos os Slots" for selecionado, busca todas as portas da OLT
                try:
                    olt_ip = selected_olt.split()[-1] if "OLT" in selected_olt else selected_olt
                    
                    query = "SELECT DISTINCT port FROM uplink_ddm_data WHERE olt_ip = %s ORDER BY port"
                    self.cursor.execute(query, (olt_ip,))
                    ports = [row[0] for row in self.cursor.fetchall()]
                    
                    for port in ports:
                        self.uplink_ddm_port_filter.addItem(str(port))
                    
                    self.uplink_ddm_port_filter.setEnabled(True)
                    
                    logging.info(f"Portas carregadas para {olt_ip} (todos os slots): {ports}")
                except Exception as e:
                    logging.error(f"Erro ao carregar portas para filtro DDM: {e}")
                    if self.conn:
                        self.conn.rollback()
        else:
            # Desabilita o filtro de porta se nenhuma OLT for selecionada
            self.uplink_ddm_port_filter.setEnabled(False)
            logging.info("Nenhuma OLT selecionada, filtro de porta desabilitado")
        
        self.uplink_ddm_port_filter.blockSignals(False)
        
        # Carrega os dados após atualizar os filtros
        self.load_uplink_ddm_data()

    def load_uplink_ddm_data(self):
        """Carrega os dados DDM do banco de dados e exibe na tabela"""
        logging.info("Método load_uplink_ddm_data chamado para atualizar a tabela DDM.")
        
        selected_olt = self.uplink_ddm_olt_filter.currentText()
        selected_slot = self.uplink_ddm_slot_filter.currentText()
        selected_port = self.uplink_ddm_port_filter.currentText()
        
        logging.info(f"Filtros selecionados - OLT: '{selected_olt}', Slot: '{selected_slot}', Porta: '{selected_port}'")
        
        # Atualiza status de carregamento
        self.update_ddm_status("Carregando dados...")
        
        try:
            # Verifica se a conexão está ativa
            if not self.conn or self.conn.closed:
                logging.warning("Conexão com o banco fechada, tentando reconectar...")
                self.connect_to_db()
                if not self.conn or self.conn.closed:
                    raise Exception("Não foi possível estabelecer conexão com o banco de dados")
            
            # Usa a conexão existente
            cursor = self.conn.cursor()
            
            # Verifica se a tabela existe antes de executar a consulta
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'uplink_ddm_data'
                )
            """)
            table_exists = cursor.fetchone()[0]
            
            if not table_exists:
                logging.error("A tabela uplink_ddm_data não existe no banco de dados!")
                self.update_ddm_status("Tabela não encontrada", True)
                QMessageBox.warning(self, "Tabela Ausente", 
                                "A tabela uplink_ddm_data não existe no banco de dados.\n"
                                "Verifique se a coleta de dados DDM está ativada.")
                return
            
            # Constrói a consulta SQL com base nos filtros
            base_query = """
                SELECT olt_ip, placa, slot, port, 
                    temperature_c, supply_voltage_v, tx_bias_current_ma,
                    tx_power_dbm, rx_power_dbm, status, collection_time
                FROM uplink_ddm_data
            """
            
            # Inicializa parâmetros e condições
            params = []
            conditions = []
            
            # Adiciona filtro de OLT se selecionado
            if selected_olt and selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
                # Extrai o IP da OLT
                olt_ip = selected_olt.split()[-1] if "OLT" in selected_olt else selected_olt
                # Verifica se o IP é válido
                if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', olt_ip):
                    conditions.append("olt_ip = %s")
                    params.append(olt_ip)
                    logging.info(f"Adicionando filtro para OLT: {olt_ip}")
                else:
                    logging.warning(f"IP de OLT inválido: {olt_ip}. Ignorando filtro.")
            
            # Adiciona filtro de Slot se selecionado
            if selected_slot and selected_slot != "Todos os Slots":
                try:
                    slot_num = int(selected_slot)
                    conditions.append("slot = %s")
                    params.append(slot_num)
                    logging.info(f"Adicionando filtro para Slot: {slot_num}")
                except ValueError:
                    logging.warning(f"Valor de slot inválido: {selected_slot}. Ignorando filtro.")
            
            # Adiciona filtro de Porta se selecionado
            if selected_port and selected_port != "Todas as Portas":
                try:
                    port_num = int(selected_port)
                    conditions.append("port = %s")
                    params.append(port_num)
                    logging.info(f"Adicionando filtro para Porta: {port_num}")
                except ValueError:
                    logging.warning(f"Valor de porta inválido: {selected_port}. Ignorando filtro.")
            
            # Constrói a consulta final
            query = base_query
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            query += " ORDER BY collection_time DESC LIMIT 1000"
            
            logging.info(f"Executando consulta: {query.replace('\n', ' ').strip()}")
            logging.info(f"Parâmetros: {params}")
            
            # Executa a consulta
            cursor.execute(query, params)
            records = cursor.fetchall()
            
            logging.info(f"Consulta executada com sucesso. Encontrados {len(records)} registros DDM.")
            
            # Se não encontrou registros, verifica se há dados na tabela
            if len(records) == 0:
                logging.warning("Nenhum registro encontrado com os filtros atuais.")
                # Verifica quantos registros totais existem
                cursor.execute("SELECT COUNT(*) FROM uplink_ddm_data")
                total_count = cursor.fetchone()[0]
                logging.info(f"Total de registros na tabela uplink_ddm_data: {total_count}")
                
                if total_count == 0:
                    self.update_ddm_status("Tabela vazia", True)
                    QMessageBox.information(self, "Sem Dados", 
                                        "A tabela uplink_ddm_data existe mas não contém registros.\n"
                                        "Verifique se a coleta de dados DDM está funcionando.")
                    return
                else:
                    self.update_ddm_status("Nenhum registro encontrado com os filtros atuais")
            
            # Limpa a tabela antes de preencher
            self.uplink_ddm_table.setRowCount(0)
            self.uplink_ddm_table.setSortingEnabled(False)
            
            # Preenche a tabela com os dados
            for row_idx, record in enumerate(records):
                self.uplink_ddm_table.insertRow(row_idx)
                
                for col_idx, value in enumerate(record):
                    item = None
                    try:
                        if col_idx == 10:  # Data/hora
                            item = QTableWidgetItem(value.strftime('%d/%m/%Y %H:%M:%S') if value else "N/A")
                        elif col_idx >= 4 and col_idx <= 8:  # Valores numéricos
                            item = QTableWidgetItem(f"{value:.2f}" if value is not None else "N/A")
                        else:
                            item = QTableWidgetItem(str(value) if value is not None else "N/A")
                        
                        # Aplica cores de acordo com os critérios
                        if col_idx == 4 and value is not None:  # Temperatura
                            if value < 10 or value > 65:  # Crítico
                                item.setBackground(QColor('#ffcdd2'))
                            elif value >= 55 or value <= 0:  # Observação
                                item.setBackground(QColor('#fff9c4'))
                            else:  # OK
                                item.setBackground(QColor('#c8e6c9'))
                        
                        elif col_idx == 5 and value is not None:  # Tensão
                            if value < 3.10 or value > 3.50:  # Crítico
                                item.setBackground(QColor('#ffcdd2'))
                            elif (value >= 3.10 and value < 3.20) or (value > 3.45 and value <= 3.50):  # Observação
                                item.setBackground(QColor('#fff9c4'))
                            else:  # OK
                                item.setBackground(QColor('#c8e6c9'))
                        
                        elif col_idx == 6 and value is not None:  # Corrente de Bias
                            # Para bias, precisaríamos de histórico para determinar tendência
                            # Por enquanto, vamos usar um valor fixo como exemplo
                            if value > 20:  # Exemplo de valor crítico (ajustar conforme necessário)
                                item.setBackground(QColor('#ffcdd2'))
                            elif value > 15:  # Exemplo de valor de observação (ajustar conforme necessário)
                                item.setBackground(QColor('#fff9c4'))
                            else:  # OK
                                item.setBackground(QColor('#c8e6c9'))
                        
                        elif col_idx == 7 and value is not None:  # Potência TX
                            # Valores típicos para TX: -9.5 a -3 dBm (1G), -8.2 a +0.5 dBm (10G)
                            if value < -10.0 or value > 1.0:  # Crítico
                                item.setBackground(QColor('#ffcdd2'))
                            elif value < -8.0 or value > 0.0:  # Observação
                                item.setBackground(QColor('#fff9c4'))
                            else:  # OK
                                item.setBackground(QColor('#c8e6c9'))
                        
                        elif col_idx == 8 and value is not None:  # Potência RX
                            # Valores típicos para RX: -18 a -5 dBm (1G), -12 a -2 dBm (10G)
                            if value < -20.0 or value > -1.0:  # Crítico
                                item.setBackground(QColor('#ffcdd2'))
                            elif value < -15.0 or value > -3.0:  # Observação
                                item.setBackground(QColor('#fff9c4'))
                            else:  # OK
                                item.setBackground(QColor('#c8e6c9'))
                        
                        # Destacar linhas com status diferente de normal
                        if col_idx == 9 and value and str(value).lower() != 'normal':
                            item.setBackground(QColor('#ffdddd'))
                        
                        self.uplink_ddm_table.setItem(row_idx, col_idx, item)
                    except Exception as cell_error:
                        logging.error(f"Erro ao processar célula {row_idx},{col_idx}: {cell_error}")
                        # Insere um item de erro
                        error_item = QTableWidgetItem("ERRO")
                        error_item.setBackground(QColor('#ff0000'))
                        self.uplink_ddm_table.setItem(row_idx, col_idx, error_item)
                
                # Força a atualização da interface a cada 100 linhas para não travar
                if row_idx % 100 == 0:
                    QApplication.processEvents()
            
            self.uplink_ddm_table.setSortingEnabled(True)
            self.uplink_ddm_table.resizeColumnsToContents()
            
            # Ajusta a largura da coluna de data/hora
            self.uplink_ddm_table.setColumnWidth(10, 150)  # Coluna de data/hora
            
            logging.info(f"Tabela DDM atualizada com {len(records)} registros.")
            self.update_ddm_status(f"{len(records)} registros carregados")
            
        except psycopg2.Error as db_error:
            logging.error(f"Erro de banco de dados ao carregar dados DDM: {db_error}", exc_info=True)
            self.update_ddm_status(f"Erro no banco: {db_error}", True)
            QMessageBox.critical(self, "Erro de Banco de Dados", 
                            f"Erro ao acessar o banco de dados:\n{str(db_error)}")
            
            # Tenta reconectar em caso de erro de banco
            try:
                if self.conn:
                    self.conn.close()
                self.connect_to_db()
            except Exception as reconnect_error:
                logging.error(f"Falha ao reconectar ao banco: {reconnect_error}")
                
        except Exception as e:
            logging.error(f"Erro inesperado ao carregar dados DDM: {str(e)}", exc_info=True)
            self.update_ddm_status(f"Erro: {str(e)}", True)
            QMessageBox.critical(self, "Erro", f"Erro ao carregar dados DDM:\n{str(e)}")
            
            # Em caso de erro geral, tenta reconectar
            try:
                if self.conn:
                    self.conn.close()
                self.connect_to_db()
            except Exception as reconnect_error:
                logging.error(f"Falha ao reconectar ao banco: {reconnect_error}")

    def export_uplink_ddm_to_csv(self):
        """Exporta os dados da tabela DDM para um arquivo CSV"""
        filename, _ = QFileDialog.getSaveFileName(
            self, "Exportar DDM", "", "Arquivos CSV (*.csv)"
        )
        
        if filename:
            try:
                with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
                    
                    # Escrever cabeçalho
                    headers = []
                    for col in range(self.uplink_ddm_table.columnCount()):
                        headers.append(self.uplink_ddm_table.horizontalHeaderItem(col).text())
                    writer.writerow(headers)
                    
                    # Escrever dados
                    for row in range(self.uplink_ddm_table.rowCount()):
                        row_data = []
                        for col in range(self.uplink_ddm_table.columnCount()):
                            item = self.uplink_ddm_table.item(row, col)
                            row_data.append(item.text() if item else "")
                        writer.writerow(row_data)
                
                QMessageBox.information(self, "Sucesso", "Dados exportados com sucesso!")
                
            except Exception as e:
                logging.error(f"Erro ao exportar dados DDM: {e}")
                QMessageBox.critical(self, "Erro", f"Erro ao exportar dados: {str(e)}")
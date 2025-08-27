# olt_monitoring_system/gui/main_window.py

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
                             QListWidget, QAbstractItemView)
from PyQt5.QtCore import (QObject, pyqtSignal, QTimer, Qt, QEvent, QMetaObject, 
                          pyqtSlot, Q_ARG, QPropertyAnimation, pyqtProperty)
from PyQt5 import QtGui
from PyQt5.QtGui import QColor
import pyqtgraph as pg

from config import DB_CONFIG, get_olt_configs
from gui.dialogs import CleanupDialog, OntDiagnosticsHistoryDialog
from olt.processing import run_data_collection
from gui.signals import db_signals
from db.connection import create_tables, check_db_connection
from olt.processing import (run_temp_monitoring, run_resource_monitoring,
                            get_active_gpon_slots, parse_board_info as olt_parse_board_info,
                            get_slot_cpu_usage, get_slot_memory_usage, get_resource_status)
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
        self.is_ont_session_active = False
        
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
        self.olt_telnet_param_prompt_re = re.compile(r"\{\s*<cr>.*\}\s*:\s*$")
        self.olt_diagnose_prompt_re = re.compile(r"\(diagnose\)\s*[>#]\s*$")
        self.olt_standard_prompt_re = re.compile(r"[>#]\s*$")
        self.diag_sections_config = [
            {"title": "1. Informações Básicas da ONT", "id": "device_info", "commands": "display deviceInfo\ndisplay version"},
            {"title": "2. Status da Conexão Óptica", "id": "optic_status", "commands": "display optic\ndisplay board-temperatures"},
            {"title": "3. Status da WAN/PPPoE", "id": "wan_status", "commands": "display pppoe client all\ndisplay wan layer all"},
            {"title": "4. Dispositivos Conectados (LAN/Wi-Fi)", "id": "lan_wifi_devices", "commands": "display dhcp server user all\ndisplay wifi associate"},
            {"title": "5. Redes Wi-Fi Vizinhas", "id": "wifi_neighbors", "commands": "display wifi neighbor"},
            {"title": "6. Configurações Wi-Fi da ONT", "id": "wifi_config", "commands": "display wifi information\ndisplay wifi radio"},
            {"title": "7. Telefonia (VoIP)", "id": "voip_status", "commands": "display voice hs status\ndisplay voip info"},
            {"title": "8. Rotas e Vizinhos IP", "id": "ip_routes", "commands": "display ip route\ndisplay ip neigh"},
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
        self.log_message_received.connect(self.log_to_gui)

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
        
        # Lógica para a aba de Estatísticas por Caixa
        if current_tab == self.caixa_stats_tab:
            QTimer.singleShot(100, self.load_caixa_stats_data)
            logging.info("Aba 'Estatísticas por Caixa' ativada. Iniciando timer.")
            self.load_caixa_stats_data()
            self.caixa_stats_update_timer.start()
        else:
            if self.caixa_stats_update_timer and self.caixa_stats_update_timer.isActive():
                logging.info("Saindo da aba de estatísticas. Parando timer.")
                self.caixa_stats_update_timer.stop()
        
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
        if current_tab == self.ont_traffic_tab:
            logging.info("Aba 'Dados ONT por PON' ativada. Iniciando timer.")
            self.load_ont_traffic_data()
            self.ont_traffic_timer.start()
        else:
            if hasattr(self, 'ont_traffic_timer') and self.ont_traffic_timer.isActive():
                logging.info("Saindo da aba de tráfego ONT. Parando timer.")
                self.ont_traffic_timer.stop()
        # --- FIM DA MODIFICAÇÃO ---

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
            
    def setup_logs_tab(self):
        """Configura a aba de logs."""
        layout = QVBoxLayout(self.logs_tab)

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
                    # --- CORREÇÃO: A condição agora aplica-se à tabela final ---
                    olt_condition = "AND olt_identifier = %s"
                    params.append(olt_identifier)
                except IndexError:
                    logging.warning(f"Formato de OLT inesperado no filtro: {selected_olt}")
            
            thirty_days_ago = datetime.now() - timedelta(days=30)
            params.append(thirty_days_ago)

            # --- CORREÇÃO: Adicionado olt_identifier e ont_id ao SELECT ---
            query = f"""
                WITH latest_records AS (
                    SELECT *, ROW_NUMBER() OVER(PARTITION BY serial_number, olt_identifier ORDER BY collection_time DESC) as rn
                    FROM ont_data
                ),
                converted_times AS (
                    SELECT
                        *,
                        CASE
                            WHEN last_up_time ~ '^\\d{{2}}/\\d{{2}}/\\d{{4}}' THEN TO_TIMESTAMP(SUBSTRING(last_up_time FROM 1 FOR 19), 'DD/MM/YYYY HH24:MI:SS')
                            WHEN last_up_time ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}' THEN TO_TIMESTAMP(SUBSTRING(last_up_time FROM 1 FOR 19), 'YYYY-MM-DD HH24:MI:SS')
                            ELSE NULL
                        END as last_up_time_ts
                    FROM latest_records
                    WHERE rn = 1 AND status = 'offline' AND last_up_time IS NOT NULL
                )
                SELECT
                    olt_identifier, fsp, ont_id, serial_number, client_name, last_up_time,
                    (NOW() - last_up_time_ts) as offline_duration
                FROM converted_times
                WHERE last_up_time_ts IS NOT NULL AND last_up_time_ts < %s
                {olt_condition}
                ORDER BY last_up_time_ts ASC;
            """
            
            try:
                self.cursor.execute(query, tuple(params))
                results = self.cursor.fetchall()
                
                self.long_offline_onts_table.setRowCount(len(results))
                
                # --- CORREÇÃO: Loop atualizado para incluir os novos campos 'olt' e 'ont_id' ---
                for row_idx, (olt, fsp, ont_id, sn, client, last_up, duration) in enumerate(results):
                    days_offline = duration.days if duration else 0
                    items = [
                        QTableWidgetItem(str(olt)),
                        QTableWidgetItem(fsp),
                        QTableWidgetItem(str(ont_id)),
                        QTableWidgetItem(sn),
                        QTableWidgetItem(client if client else "N/A"),
                        QTableWidgetItem(last_up if last_up else "N/A"),
                        QTableWidgetItem(str(days_offline))
                    ]
                    for col_idx, item in enumerate(items):
                        self.long_offline_onts_table.setItem(row_idx, col_idx, item)

                self.long_offline_onts_table.resizeColumnsToContents()
                self.long_offline_onts_table.setSortingEnabled(True)
                logging.info(f"{len(results)} ONTs com longa inatividade carregadas.")

            except psycopg2.Error as e:
                self.conn.rollback() # Desfaz a transação em caso de erro
                QMessageBox.critical(self, "Erro de Banco de Dados", f"Não foi possível carregar ONTs inativas:\n{e}")
                logging.error(f"Erro ao carregar ONTs com longa inatividade: {e}", exc_info=True)
            except Exception as e:
                QMessageBox.critical(self, "Erro ao Carregar ONTs Inativas", f"{str(e)}")
                logging.error(f"Erro ao carregar ONTs com longa inatividade: {e}", exc_info=True)

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
        layout = QHBoxLayout(self.data_tab)
        
        splitter = QSplitter(Qt.Horizontal)
        
        control_panel = self.create_multi_olt_control_panel()
        splitter.addWidget(control_panel)
        
        data_panel = QWidget()
        data_layout = QVBoxLayout(data_panel)
        
        action_filter_panel = self.create_action_filter_panel()
        self.status_panel = self.create_status_panel()
        self.setup_data_table()  # Garante que a tabela seja configurada corretamente
        
        data_layout.addWidget(action_filter_panel)
        data_layout.addWidget(self.status_panel)
        data_layout.addWidget(self.table)
        
        splitter.addWidget(data_panel)
        splitter.setSizes([300, 1300]) 
        layout.addWidget(splitter)

    def create_multi_olt_control_panel(self):
        """Cria o novo painel de controle para seleção e início da coleta de múltiplas OLTs."""
        panel = QGroupBox("Controle de Coleta")
        layout = QVBoxLayout(panel)

        list_label = QLabel("<b>OLTs Disponíveis:</b>")
        self.olt_list_widget = QListWidget()
        self.olt_list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for olt in self.olt_configs:
            self.olt_list_widget.addItem(f"{olt['name']} ({olt['ip']})")
        
        self.start_selected_btn = QPushButton("Iniciar Coleta Selecionada(s)")
        self.start_selected_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.start_selected_btn.clicked.connect(self.start_selected_collections)
        
        self.stop_all_btn = QPushButton("Parar Todas as Coletas")
        self.stop_all_btn.setStyleSheet("background-color: #f44336; color: white; font-weight: bold;")
        self.stop_all_btn.clicked.connect(self.stop_all_collections)
        self.stop_all_btn.setEnabled(False)

        log_label = QLabel("<b>Logs da Coleta:</b>")
        self.log_output_area = QTextEdit()
        self.log_output_area.setReadOnly(True)
        self.log_output_area.setFont(QtGui.QFont("Courier New", 8))

        layout.addWidget(list_label)
        layout.addWidget(self.olt_list_widget)
        layout.addWidget(self.start_selected_btn)
        layout.addWidget(self.stop_all_btn)
        layout.addWidget(log_label)
        layout.addWidget(self.log_output_area)
        
        return panel

    def start_selected_collections(self):
        """Inicia threads de coleta para cada OLT selecionada na lista."""
        selected_items = self.olt_list_widget.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Nenhuma OLT Selecionada", "Por favor, selecione pelo menos uma OLT da lista.")
            return

        self.collection_running = True
        self.stop_all_btn.setEnabled(True)
        self.start_selected_btn.setEnabled(False)
        self.log_to_gui("--- Iniciando coletas... ---")

        for item in selected_items:
            ip_match = re.search(r'\((\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\)', item.text())
            if not ip_match: continue
            
            olt_ip = ip_match.group(1)
            olt_config = next((olt for olt in self.olt_configs if olt['ip'] == olt_ip), None)
            
            if not olt_config:
                self.log_to_gui(f"ERRO: Configuração não encontrada para o IP {olt_ip}")
                continue

            if olt_ip in self.collection_threads and self.collection_threads[olt_ip].is_alive():
                self.log_to_gui(f"AVISO: A coleta para a OLT {olt_config['name']} já está em execução.")
                continue

            self.log_to_gui(f"Iniciando thread para OLT: {olt_config['name']}...")
            thread = threading.Thread(
                target=run_data_collection,
                args=(
                    olt_config['ip'], 
                    olt_config['username'], 
                    olt_config['password'], 
                    self, 
                    self.log_message_received.emit
                ),
                daemon=True
            )
            self.collection_threads[olt_ip] = thread
            thread.start()

    def stop_all_collections(self):
        """Sinaliza para todas as threads de coleta pararem."""
        if not self.collection_running: return
            
        self.log_to_gui("--- Sinal de parada enviado para todas as coletas. ---")
        self.collection_running = False
        self.start_selected_btn.setEnabled(True)
        self.stop_all_btn.setEnabled(False)

    @pyqtSlot(str)
    def log_to_gui(self, message):
        """Adiciona uma mensagem à área de log da GUI de forma segura."""
        self.log_output_area.append(f"{datetime.now().strftime('%H:%M:%S')} - {message}")
        # --- Fim da Modificação ---

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
        layout.setContentsMargins(0,0,0,0)

        action_box = QGroupBox("Ações na Tabela")
        action_layout = QHBoxLayout(action_box)
        
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
        
        filter_box = QGroupBox("Filtros e Visualização")
        filter_layout = QGridLayout(filter_box)
        
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
        self.stop_all_collections() # CORRIGIDO: Chama a função correta
        self.stop_temp_monitoring()
        self.stop_resource_monitoring()
        if self.is_ont_session_active:
            self.disconnect_from_ont() 

        threads_to_join = list(self.collection_threads.values())
        if hasattr(self, 'temp_thread'): threads_to_join.append(self.temp_thread)
        if hasattr(self, 'resource_thread'): threads_to_join.append(self.resource_thread)
        if hasattr(self, 'ont_connection_thread'): threads_to_join.append(self.ont_connection_thread)
        if hasattr(self, 'ont_command_thread'): threads_to_join.append(self.ont_command_thread)

        for thread in threads_to_join:
            if thread and thread.is_alive():
                logging.info(f"Aguardando a thread {thread.name} finalizar...")
                thread.join(timeout=2.0)
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
        """Configura a interface da aba 'Estatísticas da PON'."""
        layout = QVBoxLayout(self.pon_stats_tab)

        # Painel de controle
        control_panel = QWidget()
        control_layout = QHBoxLayout(control_panel)
        self.pon_stats_olt_filter = QComboBox()
        if self.pon_stats_olt_filter not in self.olt_filters_to_update:
            self.olt_filters_to_update.append(self.pon_stats_olt_filter)
        self.pon_stats_olt_filter.currentTextChanged.connect(self.load_pon_stats_data)

        control_layout.addWidget(QLabel("Filtrar por OLT:"))
        control_layout.addWidget(self.pon_stats_olt_filter)
        control_layout.addStretch()
        layout.addWidget(control_panel)

        # Usaremos duas tabelas lado a lado para melhor visualização
        splitter = QSplitter(Qt.Horizontal)

        # Tabela de Recebimento (RX)
        rx_group = QGroupBox("Estatísticas de Recebimento (RX)")
        rx_layout = QVBoxLayout(rx_group)
        self.pon_stats_rx_table = QTableWidget()
        self.pon_stats_rx_table.setColumnCount(4)
        self.pon_stats_rx_table.setHorizontalHeaderLabels(["F/S/P", "Hora", "Métrica", "Valor"])
        rx_layout.addWidget(self.pon_stats_rx_table)
        splitter.addWidget(rx_group)

        # Tabela de Envio (TX)
        tx_group = QGroupBox("Estatísticas de Envio (TX)")
        tx_layout = QVBoxLayout(tx_group)
        self.pon_stats_tx_table = QTableWidget()
        self.pon_stats_tx_table.setColumnCount(4)
        self.pon_stats_tx_table.setHorizontalHeaderLabels(["F/S/P", "Hora", "Métrica", "Valor"])
        tx_layout.addWidget(self.pon_stats_tx_table)
        splitter.addWidget(tx_group)

        layout.addWidget(splitter)

        self.pon_stats_timer = QTimer(self)
        self.pon_stats_timer.setInterval(60000)
        self.pon_stats_timer.timeout.connect(self.load_pon_stats_data)

# Em gui/main_window.py, substitua a sua função load_pon_stats_data por esta:

    def load_pon_stats_data(self):
        """Carrega os dados de estatísticas de pacotes e os exibe nas tabelas."""
        logging.info("Carregando estatísticas de pacotes da PON.")
        self.pon_stats_rx_table.setRowCount(0)
        self.pon_stats_tx_table.setRowCount(0)
        
        selected_olt = self.pon_stats_olt_filter.currentText()
        params = []
        where_clause = ""
        if selected_olt != "Todas as OLTs" and "Erro" not in selected_olt:
            olt_identifier = selected_olt.split()[-1]
            where_clause = "WHERE olt_identifier = %s"
            params.append(olt_identifier)
            
        query = f"SELECT * FROM pon_statistics_packets {where_clause} ORDER BY collection_time DESC LIMIT 500;"

        try:
            self.cursor.execute(query, tuple(params))
            results = self.cursor.fetchall()
            
            # --- INÍCIO DA CORREÇÃO ---
            # Adiciona a função enumerate() para obter o índice (i) e o item (desc) corretamente.
            col_map = {desc[0]: i for i, desc in enumerate(self.cursor.description)}
            # --- FIM DA CORREÇÃO ---
            
            rx_metrics = [k for k in col_map if k.startswith('rx_')]
            tx_metrics = [k for k in col_map if k.startswith('tx_')]
            
            self.pon_stats_rx_table.setRowCount(len(results) * len(rx_metrics))
            self.pon_stats_tx_table.setRowCount(len(results) * len(tx_metrics))
            
            rx_row, tx_row = 0, 0
            for record in results:
                fsp = record[col_map['fsp']]
                timestamp = record[col_map['collection_time']].strftime('%H:%M:%S')
                
                for metric in rx_metrics:
                    value = record[col_map[metric]]
                    self.pon_stats_rx_table.setItem(rx_row, 0, QTableWidgetItem(fsp))
                    self.pon_stats_rx_table.setItem(rx_row, 1, QTableWidgetItem(timestamp))
                    self.pon_stats_rx_table.setItem(rx_row, 2, QTableWidgetItem(metric.replace('rx_', '').replace('_', ' ').title()))
                    self.pon_stats_rx_table.setItem(rx_row, 3, QTableWidgetItem(f"{value:,}" if value is not None else "0"))
                    rx_row += 1
                
                for metric in tx_metrics:
                    value = record[col_map[metric]]
                    self.pon_stats_tx_table.setItem(tx_row, 0, QTableWidgetItem(fsp))
                    self.pon_stats_tx_table.setItem(tx_row, 1, QTableWidgetItem(timestamp))
                    self.pon_stats_tx_table.setItem(tx_row, 2, QTableWidgetItem(metric.replace('tx_', '').replace('_', ' ').title()))
                    self.pon_stats_tx_table.setItem(tx_row, 3, QTableWidgetItem(f"{value:,}" if value is not None else "0"))
                    tx_row += 1

            self.pon_stats_rx_table.resizeColumnsToContents()
            self.pon_stats_tx_table.resizeColumnsToContents()

        except Exception as e:
            logging.error(f"Erro ao carregar estatísticas de pacotes: {e}", exc_info=True)

    def update_pon_stats_display(self):
        """Atualiza a exibição de estatísticas de pacotes se a aba estiver ativa."""
        if self.tab_widget.currentWidget() == self.pon_stats_tab:
            self.load_pon_stats_data()

    # Em gui/main_window.py, adicione estas novas funções no final da classe

    def setup_ont_traffic_tab(self):
        """Configura a interface da aba 'Dados ONT por PON'."""
        layout = QVBoxLayout(self.ont_traffic_tab)

        # Painel de controle
        control_panel = QWidget()
        control_layout = QHBoxLayout(control_panel)
        self.ont_traffic_olt_filter = QComboBox()
        if self.ont_traffic_olt_filter not in self.olt_filters_to_update:
            self.olt_filters_to_update.append(self.ont_traffic_olt_filter)

        self.ont_traffic_fsp_filter = QComboBox()
        self.ont_traffic_olt_filter.currentTextChanged.connect(self.update_ont_traffic_fsp_filter)
        self.ont_traffic_fsp_filter.currentTextChanged.connect(self.load_ont_traffic_data)

        control_layout.addWidget(QLabel("Filtrar por OLT:"))
        control_layout.addWidget(self.ont_traffic_olt_filter)
        control_layout.addWidget(QLabel("Filtrar por F/S/P:"))
        control_layout.addWidget(self.ont_traffic_fsp_filter)
        control_layout.addStretch()
        layout.addWidget(control_panel)

        self.ont_traffic_table = QTableWidget()
        self.ont_traffic_table.setColumnCount(5)
        self.ont_traffic_table.setHorizontalHeaderLabels(["F/S/P", "ONT ID", "Hora da Coleta", "Upload (kbps)", "Download (kbps)"])
        self.ont_traffic_table.setSortingEnabled(True)
        layout.addWidget(self.ont_traffic_table)

        self.ont_traffic_timer = QTimer(self)
        self.ont_traffic_timer.setInterval(60000) # Atualiza a cada minuto
        self.ont_traffic_timer.timeout.connect(self.load_ont_traffic_data)

    def update_ont_traffic_fsp_filter(self):
        """Atualiza o filtro de F/S/P com base na OLT selecionada."""
        self.ont_traffic_fsp_filter.blockSignals(True)
        self.ont_traffic_fsp_filter.clear()
        self.ont_traffic_fsp_filter.addItem("Todas as PONs")

        selected_olt = self.ont_traffic_olt_filter.currentText()
        if selected_olt != "Todas as OLTs":
            try:
                olt_identifier = selected_olt.split()[-1]
                query = "SELECT DISTINCT fsp FROM ont_traffic_data WHERE olt_identifier = %s ORDER BY fsp;"
                self.cursor.execute(query, (olt_identifier,))
                fsps = [row[0] for row in self.cursor.fetchall()]
                self.ont_traffic_fsp_filter.addItems(fsps)
            except Exception as e:
                logging.error(f"Erro ao carregar FSPs para o filtro de tráfego ONT: {e}")
        self.ont_traffic_fsp_filter.blockSignals(False)
        self.load_ont_traffic_data()

    def load_ont_traffic_data(self):
        """Carrega os dados de tráfego por ONT e os exibe na tabela."""
        if not self.isVisible() or self.tab_widget.currentWidget() != self.ont_traffic_tab:
            return

        logging.info("Carregando dados de tráfego por ONT.")
        self.ont_traffic_table.setSortingEnabled(False)
        self.ont_traffic_table.setRowCount(0)

        selected_olt = self.ont_traffic_olt_filter.currentText()
        selected_fsp = self.ont_traffic_fsp_filter.currentText()

        conditions = []
        params = []

        if selected_olt != "Todas as OLTs":
            olt_identifier = selected_olt.split()[-1]
            conditions.append("olt_identifier = %s")
            params.append(olt_identifier)

        if selected_fsp != "Todas as PONs":
            conditions.append("fsp = %s")
            params.append(selected_fsp)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query = f"SELECT fsp, ont_id, collection_time, up_traffic_kbps, down_traffic_kbps FROM ont_traffic_data {where_clause} ORDER BY collection_time DESC LIMIT 2000;"

        try:
            self.cursor.execute(query, tuple(params))
            results = self.cursor.fetchall()

            self.ont_traffic_table.setRowCount(len(results))
            for row_idx, record in enumerate(results):
                fsp, ont_id, timestamp, up, down = record
                self.ont_traffic_table.setItem(row_idx, 0, QTableWidgetItem(fsp))
                self.ont_traffic_table.setItem(row_idx, 1, QTableWidgetItem(str(ont_id)))
                self.ont_traffic_table.setItem(row_idx, 2, QTableWidgetItem(timestamp.strftime('%d/%m %H:%M:%S')))
                self.ont_traffic_table.setItem(row_idx, 3, QTableWidgetItem(str(up)))
                self.ont_traffic_table.setItem(row_idx, 4, QTableWidgetItem(str(down)))

            self.ont_traffic_table.resizeColumnsToContents()
        except Exception as e:
            logging.error(f"Erro ao carregar dados de tráfego de ONT: {e}", exc_info=True)
        finally:
            self.ont_traffic_table.setSortingEnabled(True)

    def update_ont_traffic_display(self):
        """Atualiza a exibição de tráfego de ONT se a aba estiver ativa."""
        if self.tab_widget.currentWidget() == self.ont_traffic_tab:
            self.load_ont_traffic_data()
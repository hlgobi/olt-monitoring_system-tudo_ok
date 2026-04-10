# -*- coding: utf-8 -*-

# ==============================================================================
# MÓDULO DE DIÁLOGOS DA INTERFACE GRÁFICA (GUI)
# ==============================================================================
# Este arquivo contém as classes para as caixas de diálogo usadas na aplicação OLT
# Monitoring System. Implementa diálogos para login em equipamentos OLT, limpeza
# de dados históricos do banco de dados e visualização de histórico de diagnóstico
# de ONTs.
#
# Cada classe de diálogo herda de QDialog do PyQt5 e implementa uma interface
# específica para sua funcionalidade, com validações de entrada, interação com
# o banco de dados e emissão de sinais para atualização da interface principal.

# ==============================================================================
# IMPORTAÇÕES DE MÓDULOS
# ==============================================================================
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QGroupBox, QComboBox,  # Widgets básicos e layouts
    QLabel, QPushButton, QFormLayout, QLineEdit,  # Widgets de formulário e botões
    QMessageBox, QHBoxLayout, QTextEdit,         # Caixas de mensagem e áreas de texto
    QTableWidget, QTableWidgetItem, QSplitter    # Tabelas e divisores de layout
)
from PyQt5.QtCore import Qt, QTimer  # Constantes do Qt e temporizadores
from PyQt5.QtGui import QFont  # Para manipulação de fontes

# Importações específicas da aplicação
from config import DB_CONFIG  # Configurações do banco de dados
from db.operations import get_ont_diagnostic_history  # Função para obter histórico de diagnóstico
from gui.signals import db_signals  # Sinais para comunicação entre componentes
import psycopg2  # Adaptador PostgreSQL para Python
import logging  # Sistema de logging
import json  # Manipulação de dados JSON

# ==============================================================================
# CLASSE DE DIÁLOGO PARA LIMPEZA DE DADOS HISTÓRICOS
# ==============================================================================

class CleanupDialog(QDialog):
    """
    Diálogo para limpar dados históricos do banco de dados.
    
    Esta classe implementa uma interface que permite ao usuário selecionar diferentes
    níveis de limpeza de dados históricos, desde todas as OLTs até uma ONT específica.
    O diálogo inclui filtros dinâmicos que se adaptam conforme a seleção do nível
    de limpeza, e executa operações de exclusão no banco de dados com confirmação
    prévia do usuário.
    
    Attributes:
        parent: Referência para a janela principal da aplicação
        cleanup_level (QComboBox): Widget para seleção do nível de limpeza
        filter_group (QGroupBox): Grupo de widgets para filtros dinâmicos
    """
    
    def __init__(self, parent=None):
        """
        Construtor da classe CleanupDialog.
        
        Args:
            parent: Referência para a janela principal da aplicação (padrão: None)
        """
        super().__init__(parent)  # Chama o construtor da classe pai (QDialog)
        self.setWindowTitle("Limpeza de Dados Históricos")  # Define o título da janela
        self.setGeometry(300, 300, 600, 500)  # Define posição e tamanho (x, y, largura, altura)
        self.parent = parent  # Armazena referência para a janela pai
        self.init_ui()  # Inicializa a interface do usuário

    def init_ui(self):
        """
        Inicializa a interface do usuário para o diálogo de limpeza.
        
        Cria e organiza todos os widgets necessários para o diálogo, incluindo:
        - Grupo de seleção de nível de limpeza
        - Grupo de filtros dinâmicos
        - Grupo de botões de ação
        """
        layout = QVBoxLayout()  # Cria layout vertical principal

        # Grupo de seleção de nível de limpeza
        level_group = QGroupBox("Nível de Limpeza")  # Cria grupo para widgets de nível
        level_layout = QVBoxLayout()  # Layout vertical para o grupo

        # ComboBox para seleção do nível de limpeza
        self.cleanup_level = QComboBox()
        self.cleanup_level.addItems([
            "Todas as OLTs",      # Opção para limpar dados de todas as OLTs
            "OLT Específica",    # Opção para limpar dados de uma OLT específica
            "Slot Específico",    # Opção para limpar dados de um slot específico
            "PON Específica",     # Opção para limpar dados de uma PON específica
            "ONT Específica"      # Opção para limpar dados de uma ONT específica
        ])

        level_layout.addWidget(QLabel("Selecione o nível de limpeza:"))  # Rótulo para o ComboBox
        level_layout.addWidget(self.cleanup_level)  # Adiciona ComboBox ao layout
        level_group.setLayout(level_layout)  # Define layout para o grupo

        # Grupo de filtros (dinâmico com base na seleção)
        self.filter_group = QGroupBox("Filtros")  # Grupo para filtros dinâmicos
        self.filter_layout = QVBoxLayout()  # Layout vertical para filtros
        self.filter_group.setLayout(self.filter_layout)  # Define layout para o grupo

        # Grupo de botões de ação
        action_group = QGroupBox("Ações")  # Grupo para botões de ação
        action_layout = QVBoxLayout()  # Layout vertical para o grupo

        # Botão para executar a limpeza
        btn_cleanup = QPushButton("Executar Limpeza")
        btn_cleanup.setStyleSheet("background-color: #ff6666; color: white;")  # Estilo visual
        btn_cleanup.clicked.connect(self.execute_cleanup)  # Conecta ao método de execução

        action_layout.addWidget(btn_cleanup)  # Adiciona botão ao layout
        action_group.setLayout(action_layout)  # Define layout para o grupo

        # Layout principal
        layout.addWidget(level_group)  # Adiciona grupo de nível ao layout principal
        layout.addWidget(self.filter_group)  # Adiciona grupo de filtros ao layout principal
        layout.addWidget(action_group)  # Adiciona grupo de ações ao layout principal

        self.setLayout(layout)  # Define layout principal para o diálogo
        
        # Conecta mudança de seleção ao método de atualização de filtros
        self.cleanup_level.currentIndexChanged.connect(self.update_filters)
        self.update_filters()  # Atualiza filtros inicialmente

    def update_filters(self):
        """
        Atualiza a interface dos filtros com base no nível de limpeza selecionado.
        
        Este método é chamado sempre que o usuário altera a seleção no ComboBox
        de nível de limpeza. Ele remove todos os filtros existentes e cria novos
        filtros apropriados para o nível selecionado.
        """
        # Limpa filtros anteriores
        while self.filter_layout.count():  # Enquanto houver widgets no layout
            child = self.filter_layout.takeAt(0)  # Remove widget do layout
            if child.widget():  # Se o item for um widget
                child.widget().deleteLater()  # Agenda exclusão do widget

        level = self.cleanup_level.currentText()  # Obtém nível selecionado
        self.filter_group.setTitle(f"Filtros para: {level}")  # Atualiza título do grupo

        # Configura filtros específicos conforme o nível selecionado
        if level == "OLT Específica":
            self.setup_olt_filter()  # Configura filtro de OLT
        elif level == "Slot Específico":
            self.setup_slot_filter()  # Configura filtro de slot
        elif level == "PON Específica":
            self.setup_pon_filter()  # Configura filtro de PON
        elif level == "ONT Específica":
            self.setup_ont_filter()  # Configura filtro de ONT

    def setup_olt_filter(self):
        """
        Configura a interface para limpeza específica de OLT.
        
        Cria um ComboBox para seleção da OLT e o adiciona ao layout de filtros.
        Carrega a lista de OLTs a partir da janela principal.
        """
        self.olt_combo = QComboBox()  # ComboBox para seleção de OLT
        try:
            # Obtém lista de OLTs da janela principal
            olts = self.parent.get_all_olts()
            self.olt_combo.addItem("Selecione OLT")  # Item placeholder
            self.olt_combo.addItems(olts)  # Adiciona OLTs ao ComboBox
            self.filter_layout.addWidget(self.olt_combo)  # Adiciona ao layout
        except Exception as e:
            # Exibe mensagem de erro em caso de falha
            QMessageBox.warning(self, "Erro", f"Falha ao carregar OLTs: {str(e)}")

    def setup_slot_filter(self):
        """
        Configura a interface para limpeza específica de slot.
        
        Cria ComboBoxes para seleção de OLT e slot, com atualização dinâmica
        da lista de slots quando uma OLT é selecionada.
        """
        self.olt_combo = QComboBox()  # ComboBox para OLT
        self.slot_combo = QComboBox()  # ComboBox para slot

        try:
            olts = self.parent.get_all_olts()  # Obtém lista de OLTs
            self.olt_combo.addItem("Selecione OLT")  # Item placeholder
            self.olt_combo.addItems(olts)  # Adiciona OLTs

            # Adiciona widgets ao layout
            self.filter_layout.addWidget(QLabel("OLT:"))
            self.filter_layout.addWidget(self.olt_combo)
            self.filter_layout.addWidget(QLabel("Slot:"))
            self.filter_layout.addWidget(self.slot_combo)

            # Conecta mudança de OLT à atualização da lista de slots
            self.olt_combo.currentTextChanged.connect(self.update_slot_list)
            self.update_slot_list()  # Atualiza lista inicial
        except Exception as e:
            QMessageBox.warning(self, "Erro", f"Falha ao carregar slots: {str(e)}")

    def setup_pon_filter(self):
        """
        Configura a interface para limpeza específica de PON.
        
        Cria ComboBoxes para seleção de OLT, slot e PON, com atualização dinâmica
        das listas de slots e PONs quando os itens anteriores são selecionados.
        """
        self.olt_combo = QComboBox()  # ComboBox para OLT
        self.slot_combo = QComboBox()  # ComboBox para slot
        self.pon_combo = QComboBox()  # ComboBox para PON

        try:
            olts = self.parent.get_all_olts()  # Obtém lista de OLTs
            self.olt_combo.addItem("Selecione OLT")  # Item placeholder
            self.olt_combo.addItems(olts)  # Adiciona OLTs

            # Adiciona widgets ao layout
            self.filter_layout.addWidget(QLabel("OLT:"))
            self.filter_layout.addWidget(self.olt_combo)
            self.filter_layout.addWidget(QLabel("Slot:"))
            self.filter_layout.addWidget(self.slot_combo)
            self.filter_layout.addWidget(QLabel("PON:"))
            self.filter_layout.addWidget(self.pon_combo)

            # Conecta mudanças para atualização dinâmica das listas
            self.olt_combo.currentTextChanged.connect(self.update_slot_list)  # OLT -> Slot
            self.slot_combo.currentTextChanged.connect(self.update_pon_list)   # Slot -> PON
            self.update_slot_list()  # Atualiza lista inicial
        except Exception as e:
            QMessageBox.warning(self, "Erro", f"Falha ao carregar PONs: {str(e)}")

    def setup_ont_filter(self):
        """
        Configura a interface para limpeza específica de ONT.
        
        Cria um campo de texto para inserção do número de série da ONT.
        """
        self.serial_input = QLineEdit()  # Campo de texto para número de série
        self.serial_input.setPlaceholderText("Digite o número de série da ONT")  # Texto de ajuda

        # Adiciona widgets ao layout
        self.filter_layout.addWidget(QLabel("Número de Série da ONT:"))
        self.filter_layout.addWidget(self.serial_input)

    def update_slot_list(self):
        """
        Atualiza a lista de slots com base na OLT selecionada.
        
        Este método é chamado quando o usuário seleciona uma OLT no ComboBox
        correspondente. Ele limpa a lista atual de slots e a preenche com os
        slots disponíveis para a OLT selecionada.
        """
        self.slot_combo.clear()  # Limpa itens atuais
        
        # Verifica se o nível de limpeza requer seleção de slot
        if self.cleanup_level.currentText() in ["Slot Específico", "PON Específica"]:
            olt = self.olt_combo.currentText()  # Obtém OLT selecionada
            if olt != "Selecione OLT":  # Se uma OLT válida foi selecionada
                try:
                    # Obtém slots para a OLT selecionada
                    slots = self.parent.get_slots_for_olt(olt)
                    self.slot_combo.addItem("Selecione slot")  # Item placeholder
                    self.slot_combo.addItems(slots)  # Adiciona slots
                except Exception as e:
                    QMessageBox.warning(self, "Erro", f"Falha ao carregar slots: {str(e)}")

    def update_pon_list(self):
        """
        Atualiza a lista de PONs com base no slot selecionado.
        
        Este método é chamado quando o usuário seleciona um slot no ComboBox
        correspondente. Ele limpa a lista atual de PONs e a preenche com as
        PONs disponíveis para o slot selecionado.
        """
        self.pon_combo.clear()  # Limpa itens atuais
        
        # Verifica se o nível de limpeza requer seleção de PON
        if self.cleanup_level.currentText() == "PON Específica":
            olt = self.olt_combo.currentText()  # Obtém OLT selecionada
            slot = self.slot_combo.currentText()  # Obtém slot selecionado
            
            # Se OLT e slot válidos foram selecionados
            if olt != "Selecione OLT" and slot != "Selecione slot":
                try:
                    # Obtém PONs para o slot selecionado
                    pons = self.parent.get_pons_for_slot(olt, slot)
                    self.pon_combo.addItem("Selecione PON")  # Item placeholder
                    self.pon_combo.addItems(pons)  # Adiciona PONs
                except Exception as e:
                    QMessageBox.warning(self, "Erro", f"Falha ao carregar PONs: {str(e)}")

    def execute_cleanup(self):
        """
        Executa a operação de limpeza com base nas opções selecionadas.
        
        Este método é chamado quando o usuário clica no botão "Executar Limpeza".
        Ele estabelece conexão com o banco de dados e chama o método específico
        para o nível de limpeza selecionado, tratando possíveis erros.
        """
        level = self.cleanup_level.currentText()  # Obtém nível selecionado
        conn = None  # Inicializa variável de conexão
        
        try:
            # Conecta ao banco de dados
            conn = psycopg2.connect(**DB_CONFIG)
            
            # Chama método específico conforme o nível selecionado
            if level == "Todas as OLTs":
                self.cleanup_all_olts(conn)
            elif level == "OLT Específica":
                self.cleanup_specific_olt(conn)
            elif level == "Slot Específico":
                self.cleanup_specific_slot(conn)
            elif level == "PON Específica":
                self.cleanup_specific_pon(conn)
            elif level == "ONT Específica":
                self.cleanup_specific_ont(conn)
                
        except Exception as e:
            # Exibe mensagem de erro em caso de falha
            QMessageBox.critical(self, "Erro", f"Limpeza falhou: {str(e)}")
            if conn:
                conn.rollback()  # Desfaz alterações em caso de erro
        finally:
            # Fecha conexão se existir
            if conn:
                conn.close()

    def cleanup_all_olts(self, conn):
        """
        Limpa dados de todas as OLTs do banco de dados.
        
        Args:
            conn: Conexão ativa com o banco de dados PostgreSQL
        """
        # Solicita confirmação do usuário
        confirm = QMessageBox.question(
            self, "Confirmar",
            "Tem certeza que deseja excluir TODOS os dados históricos de TODAS as OLTs?\nIsso não pode ser desfeito!",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if confirm == QMessageBox.Yes:  # Se o usuário confirmar
            with conn.cursor() as cursor:
                # Executa comando TRUNCATE para limpar todas as tabelas
                cursor.execute("TRUNCATE TABLE ont_data, pon_status, temperature_monitoring, resource_monitoring RESTART IDENTITY")
                conn.commit()  # Confirma a transação
                QMessageBox.information(self, "Sucesso", "Todos os dados foram excluídos!")
                db_signals.data_updated.emit()  # Emite sinal para atualizar a GUI

    def cleanup_specific_olt(self, conn):
        """
        Limpa dados de uma OLT específica do banco de dados.
        
        Args:
            conn: Conexão ativa com o banco de dados PostgreSQL
        """
        olt = self.olt_combo.currentText()  # Obtém OLT selecionada
        
        if olt != "Selecione OLT":  # Se uma OLT válida foi selecionada
            # Solicita confirmação do usuário
            confirm = QMessageBox.question(
                self, "Confirmar",
                f"Tem certeza que deseja excluir todos os dados de {olt}?\nIsso não pode ser desfeito!",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if confirm == QMessageBox.Yes:  # Se o usuário confirmar
                olt_num = olt.split()[-1]  # Extrai número identificador da OLT
                
                with conn.cursor() as cursor:
                    # Executa comandos DELETE para cada tabela, filtrando pela OLT
                    cursor.execute("DELETE FROM ont_data WHERE olt_identifier = %s", (olt_num,))
                    cursor.execute("DELETE FROM pon_status WHERE olt_identifier = %s", (olt_num,))
                    cursor.execute("DELETE FROM temperature_monitoring WHERE olt_identifier = %s", (olt_num,))
                    cursor.execute("DELETE FROM resource_monitoring WHERE olt_identifier = %s", (olt_num,))
                    conn.commit()  # Confirma a transação
                    QMessageBox.information(self, "Sucesso", f"Dados de {olt} excluídos com sucesso!")
                    db_signals.data_updated.emit()  # Emite sinal para atualizar a GUI

    def cleanup_specific_slot(self, conn):
        """
        Limpa dados de um slot específico do banco de dados.
        
        Args:
            conn: Conexão ativa com o banco de dados PostgreSQL
        """
        olt = self.olt_combo.currentText()  # Obtém OLT selecionada
        slot = self.slot_combo.currentText()  # Obtém slot selecionado
        
        # Se OLT e slot válidos foram selecionados
        if olt != "Selecione OLT" and slot != "Selecione slot":
            # Solicita confirmação do usuário
            confirm = QMessageBox.question(
                self, "Confirmar",
                f"Tem certeza que deseja excluir dados do slot {slot} em {olt}?\nIsso não pode ser desfeito!",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if confirm == QMessageBox.Yes:  # Se o usuário confirmar
                olt_num = olt.split()[-1]  # Extrai número da OLT
                slot_num = int(slot)  # Converte número do slot para inteiro
                
                with conn.cursor() as cursor:
                    # Executa comandos DELETE com filtros apropriados
                    cursor.execute("DELETE FROM ont_data WHERE olt_identifier = %s AND fsp LIKE %s", 
                                 (olt_num, f"0/{slot_num}/%"))
                    cursor.execute("DELETE FROM pon_status WHERE olt_identifier = %s AND fsp LIKE %s", 
                                 (olt_num, f"0/{slot_num}/%"))
                    cursor.execute("DELETE FROM temperature_monitoring WHERE olt_identifier = %s AND slot_id = %s", 
                                 (olt_num, slot_num))
                    cursor.execute("DELETE FROM resource_monitoring WHERE olt_identifier = %s AND slot_id = %s", 
                                 (olt_num, slot_num))
                    conn.commit()  # Confirma a transação
                    QMessageBox.information(self, "Sucesso", f"Dados do slot {slot} excluídos com sucesso!")
                    db_signals.data_updated.emit()  # Emite sinal para atualizar a GUI

    def cleanup_specific_pon(self, conn):
        """
        Limpa dados de uma PON específica do banco de dados.
        
        Args:
            conn: Conexão ativa com o banco de dados PostgreSQL
        """
        olt = self.olt_combo.currentText()  # Obtém OLT selecionada
        slot = self.slot_combo.currentText()  # Obtém slot selecionado
        pon = self.pon_combo.currentText()  # Obtém PON selecionada
        
        # Se todos os campos válidos foram selecionados
        if olt != "Selecione OLT" and slot != "Selecione slot" and pon != "Selecione PON":
            # Solicita confirmação do usuário
            confirm = QMessageBox.question(
                self, "Confirmar",
                f"Tem certeza que deseja excluir dados da PON {slot}/{pon} em {olt}?\nIsso não pode ser desfeito!",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if confirm == QMessageBox.Yes:  # Se o usuário confirmar
                olt_num = olt.split()[-1]  # Extrai número da OLT
                fsp_val = f"0/{slot}/{pon}"  # Constrói valor FSP completo
                
                with conn.cursor() as cursor:
                    # Executa comandos DELETE com filtros apropriados
                    cursor.execute("DELETE FROM ont_data WHERE olt_identifier = %s AND fsp = %s", 
                                 (olt_num, fsp_val))
                    cursor.execute("DELETE FROM pon_status WHERE olt_identifier = %s AND fsp = %s", 
                                 (olt_num, fsp_val))
                    conn.commit()  # Confirma a transação
                    QMessageBox.information(self, "Sucesso", f"Dados da PON {slot}/{pon} excluídos com sucesso!")
                    db_signals.data_updated.emit()  # Emite sinal para atualizar a GUI

    def cleanup_specific_ont(self, conn):
        """
        Limpa dados de uma ONT específica do banco de dados.
        
        Args:
            conn: Conexão ativa com o banco de dados PostgreSQL
        """
        serial = self.serial_input.text().strip()  # Obtém número de série inserido
        
        if serial:  # Se um número de série foi inserido
            # Solicita confirmação do usuário
            confirm = QMessageBox.question(
                self, "Confirmar",
                f"Tem certeza que deseja excluir o histórico da ONT {serial}?\nIsso não pode ser desfeito!",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if confirm == QMessageBox.Yes:  # Se o usuário confirmar
                with conn.cursor() as cursor:
                    # Executa comando DELETE filtrando pelo número de série
                    cursor.execute("DELETE FROM ont_data WHERE serial_number = %s", (serial,))
                    conn.commit()  # Confirma a transação
                    QMessageBox.information(self, "Sucesso", f"Histórico da ONT {serial} excluído com sucesso!")
                    db_signals.data_updated.emit()  # Emite sinal para atualizar a GUI


# ==============================================================================
# CLASSE DE DIÁLOGO PARA LOGIN EM OLT
# ==============================================================================

class OLTLoginDialog(QDialog):
    """
    Diálogo de login para conectar a uma OLT.
    
    Esta classe implementa uma interface simples para coleta de credenciais
    (IP, nome de usuário e senha) para estabelecimento de conexão SSH com
    equipamentos OLT. Os campos possuem valores padrão para facilitar o uso.
    """
    
    def __init__(self, parent=None):
        """
        Construtor da classe OLTLoginDialog.
        
        Args:
            parent: Referência para a janela principal da aplicação (padrão: None)
        """
        super().__init__(parent)  # Chama o construtor da classe pai
        self.setWindowTitle("Conectar à OLT")  # Define o título da janela
        self.setGeometry(300, 300, 400, 200)  # Define posição e tamanho
        self.init_ui()  # Inicializa a interface do usuário

    def init_ui(self):
        """
        Inicializa a interface do usuário do diálogo de login.
        
        Cria campos para entrada de IP, usuário e senha, com valores padrão
        para os campos de usuário e senha, e botões para conectar ou cancelar.
        """
        layout = QVBoxLayout()  # Layout vertical principal
        form_layout = QFormLayout()  # Layout de formulário para organização

        # Campo para entrada do IP da OLT
        self.olt_ip_input = QLineEdit()
        self.olt_ip_input.setPlaceholderText("Exemplo: 192.168.1.100")  # Texto de ajuda
        form_layout.addRow("IP da OLT:", self.olt_ip_input)  # Adiciona ao formulário

        # Campo para entrada do nome de usuário
        self.username_input = QLineEdit()
        self.username_input.setText("huawei")  # Valor padrão
        form_layout.addRow("Usuário:", self.username_input)  # Adiciona ao formulário

        # Campo para entrada da senha
        self.password_input = QLineEdit()
        self.password_input.setText("ccmsai13")  # Valor padrão
        self.password_input.setEchoMode(QLineEdit.Password)  # Modo de senha (oculta caracteres)
        form_layout.addRow("Senha:", self.password_input)  # Adiciona ao formulário

        layout.addLayout(form_layout)  # Adiciona formulário ao layout principal

        # Layout para botões
        button_box = QHBoxLayout()
        
        # Botão para conectar
        self.connect_btn = QPushButton("Conectar")
        self.connect_btn.clicked.connect(self.accept)  # Conecta ao método accept do QDialog
        
        # Botão para cancelar
        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.clicked.connect(self.reject)  # Conecta ao método reject do QDialog

        button_box.addWidget(self.connect_btn)  # Adiciona botão ao layout
        button_box.addWidget(self.cancel_btn)  # Adiciona botão ao layout
        layout.addLayout(button_box)  # Adiciona layout de botões ao layout principal
        
        self.setLayout(layout)  # Define layout principal para o diálogo

    def get_credentials(self):
        """
        Retorna as credenciais inseridas pelo usuário como um dicionário.
        
        Returns:
            dict: Dicionário contendo as chaves 'ip', 'username' e 'password'
                  com os valores inseridos nos campos correspondentes
        """
        return {
            'ip': self.olt_ip_input.text().strip(),      # IP da OLT
            'username': self.username_input.text().strip(), # Nome de usuário
            'password': self.password_input.text().strip()  # Senha
        }


# ==============================================================================
# CLASSE DE DIÁLOGO PARA HISTÓRICO DE DIAGNÓSTICO DE ONT
# ==============================================================================

class OntDiagnosticsHistoryDialog(QDialog):
    """
    Diálogo para exibir histórico de diagnóstico de uma ONT específica.
    
    Esta classe implementa uma interface que permite visualizar o histórico de
    diagnósticos realizados em uma ONT, incluindo saídas brutas de comandos e
    dados parseados. A interface é organizada em uma tabela de registros e áreas
    para visualização detalhada dos dados.
    
    Attributes:
        ont_serial_number (str): Número de série da ONT
        olt_identifier (str): Identificador da OLT
        fsp (str): Identificador Frame/Slot/Porta da PON
        ont_id_on_pon (str): ID da ONT na PON
        history_table (QTableWidget): Tabela para exibição do histórico
        detail_view_raw (QTextEdit): Área para exibição de saída bruta
        detail_view_parsed (QTextEdit): Área para exibição de dados parseados
    """
    
    def __init__(self, ont_serial_number, olt_identifier, fsp, ont_id_on_pon, parent=None):
        """
        Construtor da classe OntDiagnosticsHistoryDialog.
        
        Args:
            ont_serial_number (str): Número de série da ONT
            olt_identifier (str): Identificador da OLT
            fsp (str): Identificador Frame/Slot/Porta da PON
            ont_id_on_pon (str): ID da ONT na PON
            parent: Referência para a janela principal (padrão: None)
        """
        super().__init__(parent)
        
        # Armazena informações da ONT
        self.ont_serial_number = ont_serial_number
        self.olt_identifier = olt_identifier
        self.fsp = fsp
        self.ont_id_on_pon = ont_id_on_pon

        # Configura título e tamanho da janela
        self.setWindowTitle(f"Histórico de Diagnóstico - ONT S/N: {self.ont_serial_number} ({self.fsp} ID:{self.ont_id_on_pon} OLT:{self.olt_identifier})")
        self.setGeometry(150, 150, 1000, 1000)
        
        # Inicializa layout principal
        self.layout = QVBoxLayout(self)

        # Cria tabela para exibição do histórico
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(5)  # Número de colunas
        self.history_table.setHorizontalHeaderLabels([
            "Data/Hora", "Seção", "Detalhes Principais", "Ver Saída Bruta", "Ver Dados Parseados"
        ])
        self.history_table.setEditTriggers(QTableWidget.NoEditTriggers)  # Desabilita edição
        self.history_table.setSelectionBehavior(QTableWidget.SelectRows)  # Seleção por linha
        self.history_table.setSelectionMode(QTableWidget.SingleSelection)  # Seleção única
        self.history_table.doubleClicked.connect(self.show_detail_view)  # Conecta duplo clique

        # Cria áreas para exibição de detalhes
        self.detail_view_raw = QTextEdit()
        self.detail_view_raw.setReadOnly(True)
        self.detail_view_raw.setPlaceholderText("Selecione um registro e clique em 'Ver Saída Bruta' ou dê duplo clique na linha.")
        self.detail_view_raw.setFont(QFont("Courier New", 9))  # Fonte monoespaçada

        self.detail_view_parsed = QTextEdit()
        self.detail_view_parsed.setReadOnly(True)
        self.detail_view_parsed.setPlaceholderText("Selecione um registro e clique em 'Ver Dados Parseados'.")
        self.detail_view_parsed.setFont(QFont("Courier New", 9))  # Fonte monoespaçada

        # Cria divisores para organização do layout
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.history_table)
        
        detail_splitter = QSplitter(Qt.Horizontal)  # Divisor horizontal para detalhes
        detail_splitter.addWidget(self.detail_view_raw)
        detail_splitter.addWidget(self.detail_view_parsed)
        detail_splitter.setSizes([500, 500])  # Tamanhos iniciais

        splitter.addWidget(detail_splitter)
        splitter.setSizes([400, 300])  # Tamanhos iniciais

        self.layout.addWidget(splitter)  # Adiciona divisor ao layout

        self.load_history()  # Carrega histórico de diagnóstico

    def load_history(self):
        """
        Carrega o histórico de diagnóstico da ONT do banco de dados.
        
        Consulta o banco de dados para obter todos os registros de diagnóstico
        para a ONT específica e os exibe na tabela.
        """
        # Obtém registros do banco de dados
        records = get_ont_diagnostic_history(self.ont_serial_number, self.olt_identifier)
        self.history_table.setRowCount(len(records))  # Define número de linhas
        self.history_table.setSortingEnabled(False)  # Desabilita ordenação durante carregamento

        # Processa cada registro
        for row_idx, record_tuple in enumerate(records):
            # Desestrutura a tupla do registro
            diag_timestamp, diag_section_id, raw_output, parsed_data_json, manuf, model, upt, fw = record_tuple
            
            # Formata timestamp
            timestamp_str = diag_timestamp.strftime('%d/%m/%Y %H:%M:%S') if diag_timestamp else "N/A"
            
            # Cria resumo para "Detalhes Principais"
            details_summary = []
            if diag_section_id == "device_info":
                if manuf: details_summary.append(f"Fabr: {manuf}")
                if model: details_summary.append(f"Modelo: {model}")
                if upt: details_summary.append(f"Uptime: {upt}")
                if fw: details_summary.append(f"FW: {fw}")
            
            # Preenche células da tabela
            self.history_table.setItem(row_idx, 0, QTableWidgetItem(timestamp_str))
            self.history_table.setItem(row_idx, 1, QTableWidgetItem(diag_section_id))
            self.history_table.setItem(row_idx, 2, QTableWidgetItem("; ".join(details_summary) if details_summary else "N/A"))

            # Armazena dados completos no item para recuperação posterior
            item_data_payload = {
                "raw": raw_output,
                "parsed": parsed_data_json  # String JSON ou dict (se o driver converter)
            }
            self.history_table.item(row_idx, 0).setData(Qt.UserRole, item_data_payload)
            
            # Adiciona botões de visualização
            btn_raw = QPushButton("Ver Bruto")
            btn_raw.setProperty("row_data", item_data_payload)  # Passa dados para o botão
            btn_raw.clicked.connect(self.show_raw_data_from_button)
            self.history_table.setCellWidget(row_idx, 3, btn_raw)

            btn_parsed = QPushButton("Ver Parseado")
            btn_parsed.setProperty("row_data", item_data_payload)
            btn_parsed.clicked.connect(self.show_parsed_data_from_button)
            self.history_table.setCellWidget(row_idx, 4, btn_parsed)

        # Ajusta colunas e habilita ordenação
        self.history_table.resizeColumnsToContents()
        self.history_table.setSortingEnabled(True)

    def show_detail_view(self, model_index):
        """
        Exibe os detalhes de um registro quando o usuário dá duplo clique na tabela.
        
        Args:
            model_index: Índice do modelo que representa a célula clicada
        """
        row = model_index.row()  # Obtém linha clicada
        item_data = self.history_table.item(row, 0).data(Qt.UserRole)  # Obtém dados armazenados
        
        if item_data:
            # Exibe dados brutos
            self.detail_view_raw.setText(item_data.get("raw", "Saída bruta não disponível."))
            
            # Processa e exibe dados parseados
            parsed_content = item_data.get("parsed")
            if parsed_content:
                try:
                    # Se for string JSON, converte para dicionário
                    if isinstance(parsed_content, str):
                        parsed_dict = json.loads(parsed_content)
                    else:  # Se já for dicionário (conversão automática do psycopg2)
                        parsed_dict = parsed_content
                    self.detail_view_parsed.setText(json.dumps(parsed_dict, indent=4, ensure_ascii=False))
                except json.JSONDecodeError:
                    self.detail_view_parsed.setText(f"Erro ao decodificar dados parseados (JSON inválido):\n{str(parsed_content)}")
                except Exception as e:
                    self.detail_view_parsed.setText(f"Erro ao processar dados parseados:\n{str(e)}\n\nDados: {str(parsed_content)}")
            else:
                self.detail_view_parsed.setText("Dados parseados não disponíveis.")

    def show_raw_data_from_button(self):
        """
        Exibe os dados brutos quando o usuário clica no botão correspondente.
        
        Este método é chamado quando o usuário clica em um botão "Ver Bruto"
        na tabela de histórico.
        """
        button = self.sender()  # Obtém o botão que enviou o sinal
        if button:
            item_data = button.property("row_data")  # Obtém dados armazenados
            if item_data:
                self.detail_view_raw.setText(item_data.get("raw", "Saída bruta não disponível."))

    def show_parsed_data_from_button(self):
        """
        Exibe os dados parseados quando o usuário clica no botão correspondente.
        
        Este método é chamado quando o usuário clica em um botão "Ver Parseado"
        na tabela de histórico.
        """
        button = self.sender()  # Obtém o botão que enviou o sinal
        if button:
            item_data = button.property("row_data")  # Obtém dados armazenados
            if item_data:
                parsed_content = item_data.get("parsed")
                if parsed_content:
                    try:
                        # Se for string JSON, converte para dicionário
                        if isinstance(parsed_content, str):
                            parsed_dict = json.loads(parsed_content)
                        else:  # Se já for dicionário
                            parsed_dict = parsed_content
                        self.detail_view_parsed.setText(json.dumps(parsed_dict, indent=4, ensure_ascii=False))
                    except Exception as e:
                        self.detail_view_parsed.setText(f"Erro ao processar dados parseados:\n{str(e)}\n\nDados: {str(parsed_content)}")
                else:
                    self.detail_view_parsed.setText("Dados parseados não disponíveis.")
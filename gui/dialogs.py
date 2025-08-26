# 13. olt_monitoring_system/gui/dialogs.py
# gui/dialogs.py
# Este arquivo contém as classes para as caixas de diálogo usadas na aplicação,
# como a de login na OLT e a de limpeza de dados históricos.

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QGroupBox, QComboBox, # Widgets básicos.
                           QLabel, QPushButton, QFormLayout, QLineEdit, # Widgets de formulário e botões.
                           QMessageBox, QHBoxLayout, QTextEdit, QTextEdit,
                           QTableWidget, QTableWidgetItem,
                           QTextEdit, QSplitter) # Caixas de mensagem e layouts.
from PyQt5.QtCore import Qt, QTimer # Importa Qt para constantes (não usado diretamente aqui, mas bom ter).
from PyQt5.QtGui import QFont # <<< IMPORTAÇÃO MAIS ESPECÍFICA
from config import DB_CONFIG # Importa a configuração do banco de dados.
from db.operations import get_ont_diagnostic_history
from gui.signals import db_signals # Importa os sinais do banco de dados.
import psycopg2 # Importa o adaptador PostgreSQL.
import logging # Importa o módulo de logging.
import json

class CleanupDialog(QDialog): # Define a classe para o diálogo de limpeza de dados.
    """
    Diálogo para limpar dados históricos do banco de dados.
    Permite a exclusão seletiva de dados por OLT, slot, PON ou ONT específica.
    """ # Docstring da classe.
    def __init__(self, parent=None): # Construtor da classe.
        super().__init__(parent) # Chama o construtor da classe pai (QDialog).
        self.setWindowTitle("Limpeza de Dados Históricos") # Define o título da janela.
        self.setGeometry(300, 300, 600, 500) # Define a posição e o tamanho da janela (x, y, largura, altura).
        self.parent = parent # Armazena a referência da janela pai (a janela principal da GUI).
        self.init_ui() # Chama o método para inicializar a interface do usuário do diálogo.

    def init_ui(self): # Método para inicializar os componentes da UI.
        """Inicializa a interface do usuário para o diálogo de limpeza""" # Docstring do método.
        layout = QVBoxLayout() # Cria um layout vertical principal para o diálogo.

        # Grupo de seleção de nível de limpeza
        level_group = QGroupBox("Nível de Limpeza") # Cria um QGroupBox para agrupar widgets relacionados ao nível de limpeza.
        level_layout = QVBoxLayout() # Cria um layout vertical para o QGroupBox.

        self.cleanup_level = QComboBox() # Cria um QComboBox para o usuário selecionar o nível de limpeza.
        self.cleanup_level.addItems([ # Adiciona os itens (opções) ao QComboBox.
            "Todas as OLTs", # Opção para limpar dados de todas as OLTs.
            "OLT Específica", # Opção para limpar dados de uma OLT específica.
            "Slot Específico", # Opção para limpar dados de um slot específico.
            "PON Específica", # Opção para limpar dados de uma PON específica.
            "ONT Específica" # Opção para limpar dados de uma ONT específica.
        ])

        level_layout.addWidget(QLabel("Selecione o nível de limpeza:")) # Adiciona um QLabel como rótulo para o QComboBox.
        level_layout.addWidget(self.cleanup_level) # Adiciona o QComboBox ao layout do grupo.
        level_group.setLayout(level_layout) # Define o layout para o QGroupBox.

        # Grupo de filtros (dinâmico com base na seleção)
        self.filter_group = QGroupBox("Filtros") # Cria um QGroupBox para os filtros, que mudarão dinamicamente.
        self.filter_layout = QVBoxLayout() # Cria um layout vertical para o grupo de filtros.
        self.filter_group.setLayout(self.filter_layout) # Define o layout para o grupo de filtros.

        # Grupo de botões de ação
        action_group = QGroupBox("Ações") # Cria um QGroupBox para os botões de ação.
        action_layout = QVBoxLayout() # Cria um layout vertical para o grupo de ações.

        btn_cleanup = QPushButton("Executar Limpeza") # Cria um QPushButton para iniciar a limpeza.
        btn_cleanup.setStyleSheet("background-color: #ff6666; color: white;") # Define o estilo do botão (cor de fundo e texto).
        btn_cleanup.clicked.connect(self.execute_cleanup) # Conecta o sinal 'clicked' do botão ao método 'execute_cleanup'.

        action_layout.addWidget(btn_cleanup) # Adiciona o botão ao layout do grupo de ações.
        action_group.setLayout(action_layout) # Define o layout para o grupo de ações.

        # Layout principal
        layout.addWidget(level_group) # Adiciona o grupo de nível de limpeza ao layout principal.
        layout.addWidget(self.filter_group) # Adiciona o grupo de filtros ao layout principal.
        layout.addWidget(action_group) # Adiciona o grupo de ações ao layout principal.

        self.setLayout(layout) # Define o layout principal para o diálogo.
        self.cleanup_level.currentIndexChanged.connect(self.update_filters) # Conecta a mudança de índice do QComboBox ao método 'update_filters'.
        self.update_filters() # Chama 'update_filters' para configurar os filtros iniciais.

    def update_filters(self): # Método para atualizar a UI dos filtros com base no nível de limpeza selecionado.
        """Atualiza a UI dos filtros com base no nível de limpeza selecionado""" # Docstring do método.
        # Limpa filtros anteriores
        while self.filter_layout.count(): # Enquanto houver widgets no layout de filtros.
            child = self.filter_layout.takeAt(0) # Remove o widget do layout.
            if child.widget(): # Se o item removido for um widget.
                child.widget().deleteLater() # Agenda a exclusão do widget para evitar problemas.

        level = self.cleanup_level.currentText() # Obtém o texto do item selecionado no QComboBox de nível.
        self.filter_group.setTitle(f"Filtros para: {level}") # Define o título do grupo de filtros.

        if level == "OLT Específica": # Se o nível for "OLT Específica".
            self.setup_olt_filter() # Chama o método para configurar o filtro de OLT.
        elif level == "Slot Específico": # Se o nível for "Slot Específico".
            self.setup_slot_filter() # Chama o método para configurar o filtro de slot.
        elif level == "PON Específica": # Se o nível for "PON Específica".
            self.setup_pon_filter() # Chama o método para configurar o filtro de PON.
        elif level == "ONT Específica": # Se o nível for "ONT Específica".
            self.setup_ont_filter() # Chama o método para configurar o filtro de ONT.

    def setup_olt_filter(self): # Método para configurar a UI para limpeza específica de OLT.
        """Configura a UI para limpeza específica de OLT""" # Docstring do método.
        self.olt_combo = QComboBox() # Cria um QComboBox para selecionar a OLT.
        try: # Inicia um bloco try-except.
            olts = self.parent.get_all_olts() # Obtém a lista de todas as OLTs da janela pai.
            self.olt_combo.addItem("Selecione OLT") # Adiciona um item placeholder.
            self.olt_combo.addItems(olts) # Adiciona as OLTs ao QComboBox.
            self.filter_layout.addWidget(self.olt_combo) # Adiciona o QComboBox ao layout de filtros.
        except Exception as e: # Captura exceções.
            QMessageBox.warning(self, "Erro", f"Falha ao carregar OLTs: {str(e)}") # Mostra uma mensagem de aviso.

    def setup_slot_filter(self): # Método para configurar a UI para limpeza específica de slot.
        """Configura a UI para limpeza específica de slot""" # Docstring do método.
        self.olt_combo = QComboBox() # Cria um QComboBox para selecionar a OLT.
        self.slot_combo = QComboBox() # Cria um QComboBox para selecionar o slot.

        try: # Inicia um bloco try-except.
            olts = self.parent.get_all_olts() # Obtém a lista de OLTs.
            self.olt_combo.addItem("Selecione OLT") # Placeholder para OLT.
            self.olt_combo.addItems(olts) # Adiciona OLTs.

            self.filter_layout.addWidget(QLabel("OLT:")) # Adiciona rótulo "OLT:".
            self.filter_layout.addWidget(self.olt_combo) # Adiciona QComboBox de OLT.
            self.filter_layout.addWidget(QLabel("Slot:")) # Adiciona rótulo "Slot:".
            self.filter_layout.addWidget(self.slot_combo) # Adiciona QComboBox de Slot.

            # Conecta a mudança de texto do QComboBox de OLT ao método para atualizar a lista de slots.
            self.olt_combo.currentTextChanged.connect(self.update_slot_list)
            self.update_slot_list() # Atualiza a lista de slots inicialmente.
        except Exception as e: # Captura exceções.
            QMessageBox.warning(self, "Erro", f"Falha ao carregar slots: {str(e)}") # Mensagem de aviso.

    def setup_pon_filter(self): # Método para configurar a UI para limpeza específica de PON.
        """Configura a UI para limpeza específica de PON""" # Docstring do método.
        self.olt_combo = QComboBox() # QComboBox para OLT.
        self.slot_combo = QComboBox() # QComboBox para Slot.
        self.pon_combo = QComboBox() # QComboBox para PON.

        try: # Inicia um bloco try-except.
            olts = self.parent.get_all_olts() # Obtém lista de OLTs.
            self.olt_combo.addItem("Selecione OLT") # Placeholder OLT.
            self.olt_combo.addItems(olts) # Adiciona OLTs.

            self.filter_layout.addWidget(QLabel("OLT:")) # Rótulo OLT.
            self.filter_layout.addWidget(self.olt_combo) # QComboBox OLT.
            self.filter_layout.addWidget(QLabel("Slot:")) # Rótulo Slot.
            self.filter_layout.addWidget(self.slot_combo) # QComboBox Slot.
            self.filter_layout.addWidget(QLabel("PON:")) # Rótulo PON.
            self.filter_layout.addWidget(self.pon_combo) # QComboBox PON.

            # Conecta sinais para atualizar as listas dinamicamente.
            self.olt_combo.currentTextChanged.connect(self.update_slot_list) # OLT -> Slot.
            self.slot_combo.currentTextChanged.connect(self.update_pon_list) # Slot -> PON.
            self.update_slot_list() # Atualiza slots inicialmente.
        except Exception as e: # Captura exceções.
            QMessageBox.warning(self, "Erro", f"Falha ao carregar PONs: {str(e)}") # Mensagem de aviso.

    def setup_ont_filter(self): # Método para configurar a UI para limpeza específica de ONT.
        """Configura a UI para limpeza específica de ONT""" # Docstring do método.
        self.serial_input = QLineEdit() # Cria um QLineEdit para o usuário inserir o número de série da ONT.
        self.serial_input.setPlaceholderText("Digite o número de série da ONT") # Define um texto placeholder.

        self.filter_layout.addWidget(QLabel("Número de Série da ONT:")) # Adiciona um rótulo.
        self.filter_layout.addWidget(self.serial_input) # Adiciona o QLineEdit.

    def update_slot_list(self): # Método para atualizar a lista de slots com base na OLT selecionada.
        """Atualiza a lista de slots com base na OLT selecionada""" # Docstring do método.
        self.slot_combo.clear() # Limpa os itens atuais do QComboBox de slots.
        # Verifica se o nível de limpeza requer seleção de slot.
        if self.cleanup_level.currentText() in ["Slot Específico", "PON Específica"]:
            olt = self.olt_combo.currentText() # Obtém a OLT selecionada.
            if olt != "Selecione OLT": # Se uma OLT válida foi selecionada.
                try: # Inicia um bloco try-except.
                    slots = self.parent.get_slots_for_olt(olt) # Obtém os slots para a OLT selecionada.
                    self.slot_combo.addItem("Selecione slot") # Adiciona um placeholder.
                    self.slot_combo.addItems(slots) # Adiciona os slots ao QComboBox.
                except Exception as e: # Captura exceções.
                    QMessageBox.warning(self, "Erro", f"Falha ao carregar slots: {str(e)}") # Mensagem de aviso.

    def update_pon_list(self): # Método para atualizar a lista de PONs com base no slot selecionado.
        """Atualiza a lista de PONs com base no slot selecionado""" # Docstring do método.
        self.pon_combo.clear() # Limpa os itens atuais do QComboBox de PONs.
        if self.cleanup_level.currentText() == "PON Específica": # Se o nível de limpeza for "PON Específica".
            olt = self.olt_combo.currentText() # Obtém a OLT selecionada.
            slot = self.slot_combo.currentText() # Obtém o slot selecionado.
            if olt != "Selecione OLT" and slot != "Selecione slot": # Se OLT e slot válidos foram selecionados.
                try: # Inicia um bloco try-except.
                    pons = self.parent.get_pons_for_slot(olt, slot) # Obtém as PONs para o slot.
                    self.pon_combo.addItem("Selecione PON") # Adiciona placeholder.
                    self.pon_combo.addItems(pons) # Adiciona as PONs ao QComboBox.
                except Exception as e: # Captura exceções.
                    QMessageBox.warning(self, "Erro", f"Falha ao carregar PONs: {str(e)}") # Mensagem de aviso.

    def execute_cleanup(self): # Método para executar a operação de limpeza.
        """Executa a operação de limpeza com base nas opções selecionadas""" # Docstring do método.
        level = self.cleanup_level.currentText() # Obtém o nível de limpeza selecionado.
        conn = None # Inicializa a variável de conexão com o banco de dados como None.
        try: # Inicia um bloco try-except para tratamento de erros durante a conexão e execução SQL.
            conn = psycopg2.connect(**DB_CONFIG) # Conecta ao banco de dados usando as configurações globais.
            if level == "Todas as OLTs": # Se a opção for limpar todas as OLTs.
                self.cleanup_all_olts(conn) # Chama o método específico.
            elif level == "OLT Específica": # Se for para uma OLT específica.
                self.cleanup_specific_olt(conn) # Chama o método específico.
            elif level == "Slot Específico": # Se for para um slot específico.
                self.cleanup_specific_slot(conn) # Chama o método específico.
            elif level == "PON Específica": # Se for para uma PON específica.
                self.cleanup_specific_pon(conn) # Chama o método específico.
            elif level == "ONT Específica": # Se for para uma ONT específica.
                self.cleanup_specific_ont(conn) # Chama o método específico.

        except Exception as e: # Captura qualquer exceção durante o processo.
            QMessageBox.critical(self, "Erro", f"Limpeza falhou: {str(e)}") # Exibe uma mensagem de erro crítica.
            if conn: conn.rollback() # Se a conexão existir, desfaz quaisquer alterações (rollback).
        finally: # Bloco finally, executado sempre.
            if conn: conn.close() # Se a conexão existir, fecha-a.


    def cleanup_all_olts(self, conn): # Método para limpar dados de todas as OLTs.
        """Limpa dados de todas as OLTs""" # Docstring do método.
        # Pede confirmação ao usuário.
        confirm = QMessageBox.question(
            self, "Confirmar", # Título da caixa de diálogo de confirmação.
            "Tem certeza que deseja excluir TODOS os dados históricos de TODAS as OLTs?\nIsso não pode ser desfeito!", # Mensagem de confirmação.
            QMessageBox.Yes | QMessageBox.No # Botões Yes e No.
        )
        if confirm == QMessageBox.Yes: # Se o usuário confirmar.
            with conn.cursor() as cursor: # Cria um cursor para executar comandos SQL.
                # Executa o comando TRUNCATE para remover todos os dados das tabelas e reiniciar as sequências de ID.
                cursor.execute("TRUNCATE TABLE ont_data, pon_status, temperature_monitoring, resource_monitoring RESTART IDENTITY")
                conn.commit() # Confirma a transação.
                QMessageBox.information(self, "Sucesso", "Todos os dados foram excluídos!") # Mensagem de sucesso.
                db_signals.data_updated.emit() # Emite um sinal para atualizar a GUI.

    def cleanup_specific_olt(self, conn): # Método para limpar dados de uma OLT específica.
        """Limpa dados de uma OLT específica""" # Docstring do método.
        olt = self.olt_combo.currentText() # Obtém a OLT selecionada no QComboBox.
        if olt != "Selecione OLT": # Se uma OLT válida foi selecionada.
            # Pede confirmação.
            confirm = QMessageBox.question(
                self, "Confirmar", # Título.
                f"Tem certeza que deseja excluir todos os dados de {olt}?\nIsso não pode ser desfeito!", # Mensagem.
                QMessageBox.Yes | QMessageBox.No # Botões.
            )
            if confirm == QMessageBox.Yes: # Se confirmado.
                olt_num = olt.split()[-1] # Extrai o número identificador da OLT (ex: "OLT 192" -> "192").
                with conn.cursor() as cursor: # Cria um cursor.
                    # Executa comandos DELETE para cada tabela, filtrando pelo identificador da OLT.
                    cursor.execute("DELETE FROM ont_data WHERE olt_identifier = %s", (olt_num,))
                    cursor.execute("DELETE FROM pon_status WHERE olt_identifier = %s", (olt_num,))
                    cursor.execute("DELETE FROM temperature_monitoring WHERE olt_identifier = %s", (olt_num,))
                    cursor.execute("DELETE FROM resource_monitoring WHERE olt_identifier = %s", (olt_num,))
                    conn.commit() # Confirma a transação.
                    QMessageBox.information(self, "Sucesso", f"Dados de {olt} excluídos com sucesso!") # Mensagem de sucesso.
                    db_signals.data_updated.emit() # Emite sinal para atualizar a GUI.

    def cleanup_specific_slot(self, conn): # Método para limpar dados de um slot específico.
        """Limpa dados de um slot específico""" # Docstring do método.
        olt = self.olt_combo.currentText() # Obtém a OLT selecionada.
        slot = self.slot_combo.currentText() # Obtém o slot selecionado.
        if olt != "Selecione OLT" and slot != "Selecione slot": # Se OLT e slot válidos foram selecionados.
            # Pede confirmação.
            confirm = QMessageBox.question(
                self, "Confirmar", # Título.
                f"Tem certeza que deseja excluir dados do slot {slot} em {olt}?\nIsso não pode ser desfeito!", # Mensagem.
                QMessageBox.Yes | QMessageBox.No # Botões.
            )
            if confirm == QMessageBox.Yes: # Se confirmado.
                olt_num = olt.split()[-1] # Extrai o número da OLT.
                slot_num = int(slot) # Converte o número do slot para inteiro.
                with conn.cursor() as cursor: # Cria um cursor.
                    # Deleta de ont_data onde olt_identifier e fsp (usando LIKE para o slot) correspondem.
                    cursor.execute("DELETE FROM ont_data WHERE olt_identifier = %s AND fsp LIKE %s", (olt_num, f"0/{slot_num}/%"))
                    # Deleta de pon_status onde olt_identifier e fsp (usando LIKE para o slot) correspondem.
                    cursor.execute("DELETE FROM pon_status WHERE olt_identifier = %s AND fsp LIKE %s", (olt_num, f"0/{slot_num}/%"))
                    # Deleta de temperature_monitoring onde olt_identifier e slot_id correspondem.
                    cursor.execute("DELETE FROM temperature_monitoring WHERE olt_identifier = %s AND slot_id = %s", (olt_num, slot_num))
                    # Deleta de resource_monitoring onde olt_identifier e slot_id correspondem.
                    cursor.execute("DELETE FROM resource_monitoring WHERE olt_identifier = %s AND slot_id = %s", (olt_num, slot_num))
                    conn.commit() # Confirma a transação.
                    QMessageBox.information(self, "Sucesso", f"Dados do slot {slot} excluídos com sucesso!") # Mensagem de sucesso.
                    db_signals.data_updated.emit() # Emite sinal para atualizar a GUI.

    def cleanup_specific_pon(self, conn): # Método para limpar dados de uma PON específica.
        """Limpa dados de uma PON específica""" # Docstring do método.
        olt = self.olt_combo.currentText() # Obtém a OLT selecionada.
        slot = self.slot_combo.currentText() # Obtém o slot selecionado.
        pon = self.pon_combo.currentText() # Obtém a PON selecionada.
        if olt != "Selecione OLT" and slot != "Selecione slot" and pon != "Selecione PON": # Se todos os campos válidos foram selecionados.
            # Pede confirmação.
            confirm = QMessageBox.question(
                self, "Confirmar", # Título.
                f"Tem certeza que deseja excluir dados da PON {slot}/{pon} em {olt}?\nIsso não pode ser desfeito!", # Mensagem.
                QMessageBox.Yes | QMessageBox.No # Botões.
            )
            if confirm == QMessageBox.Yes: # Se confirmado.
                olt_num = olt.split()[-1] # Extrai o número da OLT.
                fsp_val = f"0/{slot}/{pon}" # Constrói o valor FSP completo.
                with conn.cursor() as cursor: # Cria um cursor.
                    # Deleta de ont_data onde olt_identifier e fsp exato correspondem.
                    cursor.execute("DELETE FROM ont_data WHERE olt_identifier = %s AND fsp = %s", (olt_num, fsp_val))
                    # Deleta de pon_status onde olt_identifier e fsp exato correspondem.
                    cursor.execute("DELETE FROM pon_status WHERE olt_identifier = %s AND fsp = %s", (olt_num, fsp_val))
                    conn.commit() # Confirma a transação.
                    QMessageBox.information(self, "Sucesso", f"Dados da PON {slot}/{pon} excluídos com sucesso!") # Mensagem de sucesso.
                    db_signals.data_updated.emit() # Emite sinal para atualizar a GUI.

    def cleanup_specific_ont(self, conn): # Método para limpar dados de uma ONT específica.
        """Limpa dados de uma ONT específica""" # Docstring do método.
        serial = self.serial_input.text().strip() # Obtém o número de série do QLineEdit e remove espaços extras.
        if serial: # Se um número de série foi inserido.
            # Pede confirmação.
            confirm = QMessageBox.question(
                self, "Confirmar", # Título.
                f"Tem certeza que deseja excluir o histórico da ONT {serial}?\nIsso não pode ser desfeito!", # Mensagem.
                QMessageBox.Yes | QMessageBox.No # Botões.
            )
            if confirm == QMessageBox.Yes: # Se confirmado.
                with conn.cursor() as cursor: # Cria um cursor.
                    # Deleta de ont_data onde serial_number corresponde.
                    cursor.execute("DELETE FROM ont_data WHERE serial_number = %s", (serial,))
                    conn.commit() # Confirma a transação.
                    QMessageBox.information(self, "Sucesso", f"Histórico da ONT {serial} excluído com sucesso!") # Mensagem de sucesso.
                    db_signals.data_updated.emit() # Emite sinal para atualizar a GUI.


class OLTLoginDialog(QDialog): # Define a classe para o diálogo de login da OLT.
    """
    Diálogo de login para conectar a uma OLT.
    Coleta IP, nome de usuário e senha para conexão SSH.
    """ # Docstring da classe.
    def __init__(self, parent=None): # Construtor da classe.
        super().__init__(parent) # Chama o construtor da classe pai.
        self.setWindowTitle("Conectar à OLT") # Define o título da janela.
        self.setGeometry(300, 300, 400, 200) # Define a posição e o tamanho da janela.
        self.init_ui() # Chama o método para inicializar a UI.

    def init_ui(self): # Método para inicializar os componentes da UI.
        """Inicializa a UI do diálogo de login""" # Docstring do método.
        layout = QVBoxLayout() # Cria um layout vertical principal.

        form_layout = QFormLayout() # Cria um layout de formulário para organizar rótulos e campos de entrada.

        self.olt_ip_input = QLineEdit() # Cria um QLineEdit para a entrada do IP da OLT.
        self.olt_ip_input.setPlaceholderText("Exemplo: 192.168.1.100") # Define um texto placeholder.
        form_layout.addRow("IP da OLT:", self.olt_ip_input) # Adiciona uma linha ao formulário com rótulo e campo de entrada.

        self.username_input = QLineEdit() # Cria um QLineEdit para o nome de usuário.
        self.username_input.setText("huawei")  # Define um valor padrão para o nome de usuário.
        form_layout.addRow("Usuário:", self.username_input) # Adiciona a linha ao formulário.

        self.password_input = QLineEdit() # Cria um QLineEdit para a senha.
        self.password_input.setText("ccmsai13")  # Define um valor padrão para a senha.
        self.password_input.setEchoMode(QLineEdit.Password) # Define o modo de eco para ocultar a senha (mostrar asteriscos).
        form_layout.addRow("Senha:", self.password_input) # Adiciona a linha ao formulário.

        layout.addLayout(form_layout) # Adiciona o layout de formulário ao layout principal.

        button_box = QHBoxLayout() # Cria um layout horizontal para os botões.
        self.connect_btn = QPushButton("Conectar") # Cria o botão "Conectar".
        self.connect_btn.clicked.connect(self.accept) # Conecta o clique do botão ao método 'accept' do QDialog (fecha com resultado Accepted).
        self.cancel_btn = QPushButton("Cancelar") # Cria o botão "Cancelar".
        self.cancel_btn.clicked.connect(self.reject) # Conecta o clique do botão ao método 'reject' do QDialog (fecha com resultado Rejected).

        button_box.addWidget(self.connect_btn) # Adiciona o botão "Conectar" ao layout de botões.
        button_box.addWidget(self.cancel_btn) # Adiciona o botão "Cancelar" ao layout de botões.

        layout.addLayout(button_box) # Adiciona o layout de botões ao layout principal.
        self.setLayout(layout) # Define o layout principal para o diálogo.

    def get_credentials(self): # Método para obter as credenciais inseridas pelo usuário.
        """Retorna as credenciais inseridas como um dicionário""" # Docstring do método.
        return { # Retorna um dicionário.
            'ip': self.olt_ip_input.text().strip(), # Obtém o texto do campo de IP, removendo espaços extras.
            'username': self.username_input.text().strip(), # Obtém o texto do campo de usuário, removendo espaços extras.
            'password': self.password_input.text().strip() # Obtém o texto do campo de senha, removendo espaços extras.
        }

class OntDiagnosticsHistoryDialog(QDialog):
    def __init__(self, ont_serial_number, olt_identifier, fsp, ont_id_on_pon, parent=None):
        super().__init__(parent)
        self.ont_serial_number = ont_serial_number
        self.olt_identifier = olt_identifier
        self.fsp = fsp
        self.ont_id_on_pon = ont_id_on_pon

        self.setWindowTitle(f"Histórico de Diagnóstico - ONT S/N: {self.ont_serial_number} ({self.fsp} ID:{self.ont_id_on_pon} OLT:{self.olt_identifier})")
        self.setGeometry(150, 150, 1000, 1000) # Tamanho maior para o histórico
        
        self.layout = QVBoxLayout(self)

        self.history_table = QTableWidget()
        self.history_table.setColumnCount(5) # Timestamp, Seção, Fabricante, Modelo, Uptime (Exemplo inicial)
                                            # Podemos adicionar mais ou um visualizador de detalhes
        self.history_table.setHorizontalHeaderLabels([
            "Data/Hora", "Seção", "Detalhes Principais", "Ver Saída Bruta", "Ver Dados Parseados"
        ])
        self.history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.history_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.SingleSelection)
        self.history_table.doubleClicked.connect(self.show_detail_view) # Ou um botão por linha

        # Área para exibir detalhes da saída bruta ou parseada
        self.detail_view_raw = QTextEdit()
        self.detail_view_raw.setReadOnly(True)
        self.detail_view_raw.setPlaceholderText("Selecione um registro e clique em 'Ver Saída Bruta' ou dê duplo clique na linha.")
        self.detail_view_raw.setFont(QFont("Courier New", 9)) # <<< USA QFont DIRETAMENTE

        self.detail_view_parsed = QTextEdit()
        self.detail_view_parsed.setReadOnly(True)
        self.detail_view_parsed.setPlaceholderText("Selecione um registro e clique em 'Ver Dados Parseados'.")
        self.detail_view_parsed.setFont(QFont("Courier New", 9)) # <<< USA QFont DIRETAMENTE

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.history_table)
        
        detail_splitter = QSplitter(Qt.Horizontal) # Para mostrar raw e parsed lado a lado
        detail_splitter.addWidget(self.detail_view_raw)
        detail_splitter.addWidget(self.detail_view_parsed)
        detail_splitter.setSizes([500,500]) # Tamanhos iniciais

        splitter.addWidget(detail_splitter)
        splitter.setSizes([400, 300]) # Tamanhos iniciais para tabela e área de detalhes

        self.layout.addWidget(splitter)

        self.load_history()

    def load_history(self):
        records = get_ont_diagnostic_history(self.ont_serial_number, self.olt_identifier)
        self.history_table.setRowCount(len(records))
        self.history_table.setSortingEnabled(False)

        for row_idx, record_tuple in enumerate(records):
            # (diag_timestamp, diag_section_id, raw_output, parsed_data, manufacturer, model_name, uptime, firmware_version)
            diag_timestamp, diag_section_id, raw_output, parsed_data_json, manuf, model, upt, fw = record_tuple
            
            timestamp_str = diag_timestamp.strftime('%d/%m/%Y %H:%M:%S') if diag_timestamp else "N/A"
            
            # Cria um resumo para "Detalhes Principais"
            details_summary = []
            if diag_section_id == "device_info":
                if manuf: details_summary.append(f"Fabr: {manuf}")
                if model: details_summary.append(f"Modelo: {model}")
                if upt: details_summary.append(f"Uptime: {upt}")
                if fw: details_summary.append(f"FW: {fw}")
            # Adicione mais resumos para outras seções se desejar
            
            self.history_table.setItem(row_idx, 0, QTableWidgetItem(timestamp_str))
            self.history_table.setItem(row_idx, 1, QTableWidgetItem(diag_section_id))
            self.history_table.setItem(row_idx, 2, QTableWidgetItem("; ".join(details_summary) if details_summary else "N/A"))

            # Botões ou apenas armazena os dados para visualização por duplo clique
            # Por simplicidade, vamos usar o duplo clique na linha para popular as textEdits
            # ou podemos adicionar botões "Ver" em cada linha se preferir
            # Para o exemplo, vamos armazenar os dados completos no item da primeira coluna
            # para recuperá-los no duplo clique.
            item_data_payload = {
                "raw": raw_output,
                "parsed": parsed_data_json # Vem como string JSON do BD, ou dict se o driver converter
            }
            self.history_table.item(row_idx, 0).setData(Qt.UserRole, item_data_payload)
            
            # Adiciona botões de visualização (opcional, se não usar duplo clique)
            btn_raw = QPushButton("Ver Bruto")
            btn_raw.setProperty("row_data", item_data_payload) # Passa os dados para o botão
            btn_raw.clicked.connect(self.show_raw_data_from_button)
            self.history_table.setCellWidget(row_idx, 3, btn_raw)

            btn_parsed = QPushButton("Ver Parseado")
            btn_parsed.setProperty("row_data", item_data_payload)
            btn_parsed.clicked.connect(self.show_parsed_data_from_button)
            self.history_table.setCellWidget(row_idx, 4, btn_parsed)


        self.history_table.resizeColumnsToContents()
        self.history_table.setSortingEnabled(True)

    def show_detail_view(self, model_index):
        """Chamado por duplo clique na tabela."""
        row = model_index.row()
        item_data = self.history_table.item(row, 0).data(Qt.UserRole)
        if item_data:
            self.detail_view_raw.setText(item_data.get("raw", "Saída bruta não disponível."))
            parsed_content = item_data.get("parsed")
            if parsed_content:
                try:
                    # Se parsed_content é uma string JSON, carrega. Se já é dict, usa direto.
                    if isinstance(parsed_content, str):
                        parsed_dict = json.loads(parsed_content)
                    else: # Assume que já é um dict (psycopg2 pode converter JSONB para dict)
                        parsed_dict = parsed_content
                    self.detail_view_parsed.setText(json.dumps(parsed_dict, indent=4, ensure_ascii=False))
                except json.JSONDecodeError:
                    self.detail_view_parsed.setText(f"Erro ao decodificar dados parseados (JSON inválido):\n{str(parsed_content)}")
                except Exception as e:
                    self.detail_view_parsed.setText(f"Erro ao processar dados parseados:\n{str(e)}\n\nDados: {str(parsed_content)}")

            else:
                self.detail_view_parsed.setText("Dados parseados não disponíveis.")

    def show_raw_data_from_button(self):
        button = self.sender()
        if button:
            item_data = button.property("row_data")
            if item_data:
                self.detail_view_raw.setText(item_data.get("raw", "Saída bruta não disponível."))

    def show_parsed_data_from_button(self):
        button = self.sender()
        if button:
            item_data = button.property("row_data")
            if item_data:
                parsed_content = item_data.get("parsed")
                if parsed_content:
                    try:
                        if isinstance(parsed_content, str): parsed_dict = json.loads(parsed_content)
                        else: parsed_dict = parsed_content
                        self.detail_view_parsed.setText(json.dumps(parsed_dict, indent=4, ensure_ascii=False))
                    except Exception as e:
                        self.detail_view_parsed.setText(f"Erro ao processar dados parseados:\n{str(e)}\n\nDados: {str(parsed_content)}")
                else:
                    self.detail_view_parsed.setText("Dados parseados não disponíveis.")

# >>> FIM DA NOVA CLASSE DE DIÁLOGO <<<
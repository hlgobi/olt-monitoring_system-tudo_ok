import tkinter
from tkinter import filedialog, messagebox, ttk
import customtkinter
import pandas as pd
import fitz  # PyMuPDF
import re
import os
import platform
import pyperclip
import threading
import queue
from datetime import datetime
import math
import numpy as np

# --- APLICAÇÃO DO TEMA PERSONALIZADO ---
theme_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gigabyte-theme.json")
if os.path.exists(theme_path):
    customtkinter.set_default_color_theme(theme_path)
else:
    customtkinter.set_appearance_mode("Dark")
    customtkinter.set_default_color_theme("blue")

# --- JANELA DE BARRA DE PROGRESSO ---
class ProgressWindow(customtkinter.CTkToplevel):
    def __init__(self, master, total_steps):
        super().__init__(master)
        self.title("Processando...")
        self.geometry("450x130")
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.after(50, self.grab_set)
        self.grid_columnconfigure(0, weight=1)
        self.progress_label = customtkinter.CTkLabel(self, text="Iniciando extração...", font=customtkinter.CTkFont(size=14))
        self.progress_label.grid(row=0, column=0, padx=20, pady=(15, 0), sticky="w")
        self.percentage_label = customtkinter.CTkLabel(self, text="0.0%", font=customtkinter.CTkFont(size=14))
        self.percentage_label.grid(row=0, column=1, padx=20, pady=(15, 0), sticky="e")
        self.progressbar = customtkinter.CTkProgressBar(self, orientation="horizontal", mode="determinate")
        self.progressbar.set(0)
        self.progressbar.grid(row=1, column=0, columnspan=2, padx=20, pady=(5, 20), sticky="ew")
        self.total_steps = total_steps
        self.last_update = 0
        self.update()
    def on_closing(self):
        if messagebox.askokcancel("Fechar", "Deseja realmente cancelar o processamento?"):
            self.destroy()
    def update_progress(self, progress_value, text):
        current_time = datetime.now().timestamp()
        # Limitar atualizações da UI a no máximo 10 por segundo
        if current_time - self.last_update < 0.1:
            return
            
        if self.total_steps > 0:
            self.progressbar.set(progress_value)
            self.percentage_label.configure(text=f"{progress_value:.1%}")
        self.progress_label.configure(text=text)
        self.update_idletasks()
        self.last_update = current_time

# --- CLASSES POP-UP ---
class FilterWindow(customtkinter.CTkToplevel):
    def __init__(self, master, column_name, unique_values, current_selections):
        super().__init__(master)
        self.title(f"Filtro para '{column_name}'")
        self.geometry("400x500")
        self.transient(master)
        self.selections = None
        
        def _set_all_states(new_state):
            for var in self.checkbox_vars.values(): 
                var.set(new_state)
        
        action_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        action_frame.pack(fill="x", padx=10, pady=(10, 0))
        action_frame.grid_columnconfigure((0, 1), weight=1)
        
        marcar_todos_button = customtkinter.CTkButton(action_frame, text="Marcar Todos", command=lambda: _set_all_states("on"))
        marcar_todos_button.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        
        desmarcar_todos_button = customtkinter.CTkButton(action_frame, text="Desmarcar Todos", command=lambda: _set_all_states("off"))
        desmarcar_todos_button.grid(row=0, column=1, padx=(5, 0), sticky="ew")
        
        scrollable_frame = customtkinter.CTkScrollableFrame(self, label_text="Selecione os valores")
        scrollable_frame.pack(expand=True, fill="both", padx=10, pady=10)
        
        self.checkbox_vars = {}
        for value in sorted(list(unique_values)):
            var = customtkinter.StringVar(value="on" if value in current_selections else "off")
            cb = customtkinter.CTkCheckBox(scrollable_frame, text=str(value), variable=var, onvalue="on", offvalue="off")
            cb.pack(anchor="w", padx=10, pady=2)
            self.checkbox_vars[value] = var
        
        apply_button = customtkinter.CTkButton(self, text="Aplicar Filtro", command=self.apply_filter)
        apply_button.pack(pady=10, padx=10)
        
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.grab_set()
        self.focus_set()
    def apply_filter(self):
        self.selections = [value for value, var in self.checkbox_vars.items() if var.get() == "on"]
        self.destroy()
    def cancel(self): 
        self.destroy()

class DisambiguationWindow(customtkinter.CTkToplevel):
    def __init__(self, master, csv_row_data, ambiguous_rows, callback):
        super().__init__(master)
        self.title("Resolver Ambiguidade de MAC")
        self.geometry("850x750")
        self.transient(master)
        self.after(50, self.grab_set)
        self.callback = callback
        self.table_columns = list(ambiguous_rows.columns)
        self.original_client_name = csv_row_data.get('CLIENTE', 'N/A')
        self.mac_address = csv_row_data.get(next((col for col in csv_row_data.index if 'mac' in str(col).lower()), None), 'N/A')
        self.choice_var = customtkinter.StringVar(value="")
        
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("Treeview", background="#1C003D", foreground="white", fieldbackground="#3A1078", bordercolor="#4E218E", rowheight=25)
        style.configure("Treeview.Heading", background="#E60965", foreground="white", font=('Calibri', 10, 'bold'))
        style.map("Treeview", background=[("selected", "#4E218E")])
        style.map("Treeview.Heading", background=[('active', '#4E218E')])
        
        csv_info_frame = customtkinter.CTkFrame(self)
        csv_info_frame.pack(fill="x", padx=10, pady=10)
        customtkinter.CTkLabel(csv_info_frame, text=f"Nome Atual: {self.original_client_name}", font=customtkinter.CTkFont(weight="bold")).pack(anchor="w")
        customtkinter.CTkLabel(csv_info_frame, text=f"MAC Ambíguo: {self.mac_address}").pack(anchor="w")
        
        choice_frame = customtkinter.CTkFrame(self)
        choice_frame.pack(fill="x", padx=10, pady=10)
        customtkinter.CTkLabel(choice_frame, text="O que deseja fazer?").pack(anchor="w")
        
        self.radio_use_pdf = customtkinter.CTkRadioButton(choice_frame, text="Usar um nome da lista do PDF abaixo", variable=self.choice_var, value="use_pdf", command=self.on_choice_made)
        self.radio_use_pdf.pack(anchor="w", padx=10)
        
        self.radio_keep_original = customtkinter.CTkRadioButton(choice_frame, text=f"Manter o nome original: '{self.original_client_name}'", variable=self.choice_var, value="keep_original", command=self.on_choice_made)
        self.radio_keep_original.pack(anchor="w", padx=10)
        
        self.radio_use_manual = customtkinter.CTkRadioButton(choice_frame, text="Digitar um novo nome manualmente", variable=self.choice_var, value="use_manual", command=self.on_choice_made)
        self.radio_use_manual.pack(anchor="w", padx=10, pady=5)
        
        self.manual_entry = customtkinter.CTkEntry(self, placeholder_text="Digite o nome correto aqui...")
        self.manual_entry.pack(fill="x", padx=10, pady=(5,10))
        
        self.table = ttk.Treeview(self, show="headings", columns=self.table_columns, selectmode="browse")
        self.table.pack(expand=True, fill="both", padx=10, pady=10)
        
        for column in self.table_columns:
            self.table.heading(column, text=column)
            self.table.column(column, width=100, anchor="w")
        
        # Otimização: inserir dados em lote em vez de linha por linha
        values_list = [list(row.fillna('')) for _, row in ambiguous_rows.iterrows()]
        for values in values_list:
            self.table.insert("", "end", values=values)
        
        button_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        button_frame.pack(fill="x", padx=10, pady=10)
        
        self.confirm_button = customtkinter.CTkButton(button_frame, text="Confirmar", command=self.confirm_choice, state="disabled")
        self.confirm_button.pack()
        
        self.on_choice_made()
    def on_choice_made(self):
        self.confirm_button.configure(state="normal")
        if self.choice_var.get() == "use_manual": 
            self.manual_entry.configure(state="normal")
        else: 
            self.manual_entry.configure(state="disabled")
    def confirm_choice(self):
        choice = self.choice_var.get()
        if choice == "use_pdf":
            selected_item = self.table.selection()
            if not selected_item:
                messagebox.showwarning("Seleção Necessária", "Por favor, selecione uma linha da tabela do PDF.", parent=self)
                return
            nome_idx = self.table_columns.index('Nome')
            cod_idx = self.table_columns.index('Cód.')
            selected_name = self.table.item(selected_item[0])['values'][nome_idx]
            selected_cod = self.table.item(selected_item[0])['values'][cod_idx]
            self.callback('UPDATE', selected_name, selected_cod)
        elif choice == "use_manual":
            manual_name = self.manual_entry.get().strip()
            if not manual_name:
                messagebox.showwarning("Nome Necessário", "Por favor, digite um nome no campo.", parent=self)
                return
            self.callback('UPDATE', manual_name, None)
        else: 
            self.callback('KEEP', None, None)
        self.destroy()

# --- CLASSE PRINCIPAL DA APLICAÇÃO ---
class App(customtkinter.CTk):
    @staticmethod
    def extrair_dados_do_pdf(caminho_pdf, progress_queue, paginas_para_processar):
        try:
            print(f"Opening PDF: {caminho_pdf}")
            doc = fitz.open(caminho_pdf)
            total_paginas = len(doc)
            lista_de_dataframes = []
            nomes_colunas = ['Cód.', 'Nome', 'Data Cad.', 'Username', 'Mac', 'Servidor', 'Ponto de Acesso', 'Plano de Acesso', 'Status', 'Contrato']
            print(f"Starting extraction for pages: {paginas_para_processar}")
            
            # Pré-alocar lista para melhor performance
            batch_size = 10
            batch_dataframes = []
            
            for i, page_num in enumerate(paginas_para_processar):
                print(f"Processing page {page_num + 1} of {total_paginas}")
                progress_queue.put(("progress", (i + 1) / len(paginas_para_processar), f"Lendo tabela da página {page_num + 1} de {total_paginas}..."))
                page = doc.load_page(page_num)
                tabelas_encontradas = page.find_tables()
                
                for table in tabelas_encontradas:
                    raw_data = table.extract()
                    if not raw_data:
                        continue
                    
                    df_pagina = pd.DataFrame(raw_data)
                    
                    # Otimização: tratamento de colunas inconsistentes
                    if len(df_pagina.columns) == 11:
                        # Verificar se primeira coluna é vazia usando numpy para melhor performance
                        first_col = df_pagina.iloc[:, 0]
                        if (pd.isna(first_col) | (first_col.astype(str).str.strip() == '')).all():
                            df_pagina = df_pagina.iloc[:, 1:]
                    
                    if not df_pagina.empty and len(df_pagina.columns) == len(nomes_colunas):
                        df_pagina.columns = nomes_colunas
                        batch_dataframes.append(df_pagina)
                        
                        # Processar em lotes para reduzir uso de memória
                        if len(batch_dataframes) >= batch_size:
                            lista_de_dataframes.extend(batch_dataframes)
                            batch_dataframes = []
            
            # Adicionar quaisquer dataframes restantes
            if batch_dataframes:
                lista_de_dataframes.extend(batch_dataframes)
            
            doc.close()
            print("PDF document closed")
            
            if not lista_de_dataframes:
                progress_queue.put(("done", pd.DataFrame(), "Nenhuma tabela de registros foi encontrada nas páginas selecionadas."))
                return
            
            # Otimização: concatenar todos os dataframes de uma vez
            df_final = pd.concat(lista_de_dataframes, ignore_index=True)
            print(f"Concatenated {len(df_final)} rows")
            
            # Otimização: remover linhas completamente vazias de forma mais eficiente
            df_final = df_final.dropna(how='all')
            
            # Otimização: processar todas as colunas de texto de uma vez
            str_cols = df_final.select_dtypes(include=['object']).columns
            if len(str_cols) > 0:
                df_final[str_cols] = df_final[str_cols].apply(lambda x: x.str.replace('\n', ' ', regex=False).str.strip())
            
            if 'Cód.' in df_final.columns:
                # Otimização: filtragem mais eficiente
                mask = ~df_final['Cód.'].astype(str).str.contains('Cód', na=False, case=False)
                df_final = df_final[mask]
                
                # Converter para numérico de forma mais eficiente
                df_final['Cód.'] = pd.to_numeric(df_final['Cód.'], errors='coerce')
                df_final = df_final.dropna(subset=['Cód.'])
                
                if not df_final.empty:
                    df_final['Cód.'] = df_final['Cód.'].astype(int).astype(str)
            else:
                progress_queue.put(("done", pd.DataFrame(), "A coluna 'Cód.' não foi encontrada na tabela extraída."))
                return
            
            print(f"Final dataframe size: {len(df_final)} rows")
            progress_queue.put(("done", df_final[nomes_colunas], None))
        except Exception as e:
            print(f"Exception occurred: {str(e)}")
            import traceback
            traceback.print_exc()
            progress_queue.put(("done", None, f"Erro ao processar o arquivo PDF: {str(e)}"))

    def __init__(self):
        super().__init__()
        self.title("Analisador e Reconciliador de Dados - Gigabyte Telecom")
        self.geometry("1200x800")
        self.pdf_full_dataframe = pd.DataFrame()
        self.pdf_filtered_dataframe = pd.DataFrame()
        self.csv_dataframe = pd.DataFrame()
        self.active_filters = {}
        self.disambiguation_queue = []
        self.current_disambiguation_task = None
        self.edit_entry = None
        self.ambiguity_log_df = pd.DataFrame()
        self.pdf_current_page = 0
        self.pdf_rows_per_page = 200
        self.style = ttk.Style(self)
        self.style.theme_use("default")
        self.style.configure("Treeview", background="#1C003D", foreground="white", fieldbackground="#3A1078", bordercolor="#4E218E", rowheight=25)
        self.style.configure("Treeview.Heading", background="#E60965", foreground="white", font=('Calibri', 10, 'bold'))
        self.style.map("Treeview", background=[("selected", "#4E218E")])
        self.style.map("Treeview.Heading", background=[('active', '#4E218E')])
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        self.tab_view = customtkinter.CTkTabview(self, anchor="w")
        self.tab_view.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        
        self.tab_pdf = self.tab_view.add("Dados do PDF")
        self.tab_csv = self.tab_view.add("Dados do CSV")
        self.tab_log = self.tab_view.add("Log de Eventos")
        
        self.pdf_tab_setup()
        self.csv_tab_setup()
        self.log_tab_setup()
        
        self.log("Aplicação iniciada.")

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_message = f"[{timestamp}] {message}\n"
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", log_message)
        self.log_textbox.configure(state="disabled")
        self.log_textbox.see("end")

    def carregar_pdf(self):
        path = filedialog.askopenfilename(title="Selecione o PDF", filetypes=[("Arquivos PDF", "*.pdf")])
        if not path:
            self.log("Carregamento de PDF cancelado.")
            return
        
        self.log(f"Arquivo PDF selecionado: {os.path.basename(path)}")
        try:
            with fitz.open(path) as doc:
                total_paginas = len(doc)
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível abrir o arquivo PDF.\nErro: {e}")
            self.log(f"Falha ao abrir PDF: {e}")
            return
        
        dialog = customtkinter.CTkInputDialog(
            text=f"O PDF tem {total_paginas} páginas.\nDigite as páginas a analisar (ex: 1-10, 15, 20-25).\nDeixe em branco para analisar todas.",
            title="Definir Páginas para Análise"
        )
        input_str = dialog.get_input()
        if input_str is None:
            self.log("Análise de páginas cancelada.")
            return
        
        try:
            if input_str.strip() == "":
                paginas_para_analisar = list(range(total_paginas))
            else:
                paginas_para_analisar = []
                partes = input_str.split(',')
                for parte in partes:
                    if '-' in parte:
                        inicio, fim = map(int, parte.split('-'))
                        if inicio > fim or inicio < 1 or fim > total_paginas:
                            raise ValueError("Intervalo de páginas inválido.")
                        paginas_para_analisar.extend(range(inicio - 1, fim))
                    else:
                        num_pagina = int(parte)
                        if not (0 < num_pagina <= total_paginas):
                             raise ValueError("Número de página inválido.")
                        paginas_para_analisar.append(num_pagina - 1)
                paginas_para_analisar = sorted(list(set(paginas_para_analisar)))
        except ValueError as e:
            messagebox.showerror("Entrada Inválida", f"Formato de página inválido: {e}. Use números, vírgulas e hífens (ex: 1-10, 15).")
            return
        
        if not paginas_para_analisar:
            messagebox.showinfo("Aviso", "Nenhuma página selecionada para análise.")
            return
        
        self.progress_queue = queue.Queue()
        self.progress_win = ProgressWindow(self, len(paginas_para_analisar))
        self.log(f"Iniciando extração de {len(paginas_para_analisar)} página(s) do PDF...")
        
        # Otimização: passar cópia da lista para evitar problemas de concorrência
        self.extraction_thread = threading.Thread(
            target=App.extrair_dados_do_pdf, 
            args=(path, self.progress_queue, paginas_para_analisar.copy())
        )
        self.extraction_thread.start()
        self.after(100, self.monitorar_progresso_pdf)

    def monitorar_progresso_pdf(self):
        try:
            if hasattr(self, 'progress_queue'):
                # Processar todas as mensagens disponíveis de uma vez
                messages_processed = 0
                while not self.progress_queue.empty() and messages_processed < 10:  # Limitar a 10 mensagens por ciclo
                    message = self.progress_queue.get_nowait()
                    msg_type, data, text_or_error = message
                    messages_processed += 1
                    
                    if msg_type == "progress":
                        self.progress_win.update_progress(data, text_or_error)
                    elif msg_type == "done":
                        self.progress_win.destroy()
                        df, error = data, text_or_error
                        if error:
                            messagebox.showerror("Erro na Extração", error)
                            self.log(f"Erro na extração: {error}")
                        else:
                            self.pdf_full_dataframe = df
                            self.log(f"Extração concluída. Total de {len(df)} registros encontrados.")
                            if not df.empty:
                                messagebox.showinfo("Sucesso", f"{len(self.pdf_full_dataframe)} registros do PDF carregados!")
                        self.limpar_filtros_e_busca_pdf()
                        return
        except queue.Empty:
            pass
        except Exception as e:
            print(f"Error in monitorar_progresso_pdf: {e}")
            self.progress_win.destroy()
            messagebox.showerror("Erro", f"Erro durante o monitoramento: {e}")
            self.log(f"Erro durante o monitoramento: {e}")
        
        if hasattr(self, 'extraction_thread') and self.extraction_thread.is_alive():
            self.after(100, self.monitorar_progresso_pdf)
        else:
            if hasattr(self, 'progress_win'):
                self.progress_win.destroy()
            self.log("Thread de extração finalizada.")

    def create_and_place_table(self, parent_frame):
        table = ttk.Treeview(parent_frame, show="headings", style="Treeview")
        vsb = customtkinter.CTkScrollbar(parent_frame, command=table.yview)
        hsb = customtkinter.CTkScrollbar(parent_frame, orientation="horizontal", command=table.xview)
        table.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        table.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        return table

    def pdf_tab_setup(self):
        self.tab_pdf.grid_columnconfigure(0, weight=1)
        self.tab_pdf.grid_rowconfigure(2, weight=10)
        self.tab_pdf.grid_rowconfigure(3, weight=0)
        
        top_controls_frame = customtkinter.CTkFrame(self.tab_pdf)
        top_controls_frame.grid(row=0, column=0, padx=10, pady=5, sticky="ew")
        top_controls_frame.grid_columnconfigure(1, weight=1)
        
        button_frame = customtkinter.CTkFrame(top_controls_frame, fg_color="transparent")
        button_frame.pack(side="left")
        
        self.load_pdf_button = customtkinter.CTkButton(button_frame, text="Carregar PDF", command=self.carregar_pdf)
        self.load_pdf_button.pack(side="left", padx=(0,5), pady=5)
        
        self.import_pdf_button = customtkinter.CTkButton(button_frame, text="Importar CSV", command=self.importar_pdf_csv)
        self.import_pdf_button.pack(side="left", padx=5, pady=5)
        
        self.export_pdf_button = customtkinter.CTkButton(button_frame, text="Exportar para CSV", command=self.exportar_pdf_para_csv)
        self.export_pdf_button.pack(side="left", padx=5, pady=5)
        
        search_frame = customtkinter.CTkFrame(top_controls_frame, fg_color="transparent")
        search_frame.pack(side="right", fill="x", expand=True)
        search_frame.grid_columnconfigure(0, weight=1)
        
        self.pdf_search_entry = customtkinter.CTkEntry(search_frame, placeholder_text="Buscar em todos os campos...")
        self.pdf_search_entry.grid(row=0, column=0, padx=(10,5), pady=5, sticky="ew")
        
        self.pdf_search_button = customtkinter.CTkButton(search_frame, text="Buscar", width=100, command=self._executar_filtragem_completa)
        self.pdf_search_button.grid(row=0, column=1, padx=(0,5), pady=5)
        
        self.filter_buttons_frame = customtkinter.CTkFrame(self.tab_pdf)
        self.filter_buttons_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        
        table_frame_container = customtkinter.CTkFrame(self.tab_pdf, fg_color="transparent")
        table_frame_container.grid(row=2, column=0, padx=10, pady=5, sticky="nsew")
        table_frame_container.grid_rowconfigure(0, weight=1)
        table_frame_container.grid_columnconfigure(0, weight=1)
        
        self.pdf_table = self.create_and_place_table(table_frame_container)
        
        pagination_frame = customtkinter.CTkFrame(self.tab_pdf)
        pagination_frame.grid(row=3, column=0, padx=10, pady=5, sticky="ew")
        pagination_frame.grid_columnconfigure((0, 2), weight=1)
        
        self.pdf_prev_button = customtkinter.CTkButton(pagination_frame, text="< Anterior", command=self.pdf_prev_page, state="disabled")
        self.pdf_prev_button.grid(row=0, column=0, padx=5, pady=5, sticky="e")
        
        self.pdf_page_label = customtkinter.CTkLabel(pagination_frame, text="Página 0 de 0")
        self.pdf_page_label.grid(row=0, column=1, padx=10, pady=5)
        
        self.pdf_next_button = customtkinter.CTkButton(pagination_frame, text="Próxima >", command=self.pdf_next_page, state="disabled")
        self.pdf_next_button.grid(row=0, column=2, padx=5, pady=5, sticky="w")

    def log_tab_setup(self):
        self.tab_log.grid_columnconfigure(0, weight=1)
        self.tab_log.grid_rowconfigure(0, weight=1)
        self.log_textbox = customtkinter.CTkTextbox(self.tab_log, state="disabled", font=("Consolas", 12))
        self.log_textbox.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")

    def limpar_filtros_e_busca_pdf(self):
        self.log("Limpando filtros e busca.")
        if hasattr(self, 'pdf_search_entry'): 
            self.pdf_search_entry.delete(0, "end")
        self.active_filters.clear()
        self.pdf_filtered_dataframe = self.pdf_full_dataframe.copy()
        self.pdf_current_page = 0
        self.update_pdf_pagination()
        if not self.pdf_full_dataframe.empty:
            self.criar_botoes_de_filtro()
        else:
            for widget in self.filter_buttons_frame.winfo_children(): 
                widget.destroy()

    def _executar_filtragem_completa(self):
        if self.pdf_full_dataframe.empty: 
            return
        
        self.log("Executando filtros e busca...")
        df = self.pdf_full_dataframe.copy()
        
        # Otimização: aplicar filtros de forma mais eficiente
        if self.active_filters:
            for column, selected_values in self.active_filters.items():
                if selected_values:
                    df = df[df[column].isin(selected_values)]
        
        search_term = self.pdf_search_entry.get().strip()
        if search_term:
            self.log(f"Buscando por: '{search_term}'...")
            # Otimização: usar regex compilado para melhor performance
            pattern = re.compile(re.escape(search_term), re.IGNORECASE)
            mask = df.apply(lambda row: any(pattern.search(str(val)) for val in row), axis=1)
            df = df[mask]
        
        self.pdf_filtered_dataframe = df
        self.pdf_current_page = 0
        self.update_pdf_pagination()
        self.log(f"Exibindo {len(df)} resultados.")

    def exibir_dataframe(self, dataframe, table_widget):
        table_widget.delete(*table_widget.get_children())
        if dataframe is None or dataframe.empty:
            table_widget["columns"] = []
            return
        
        columns = list(dataframe.columns)
        table_widget["column"] = columns
        table_widget["show"] = "headings"
        
        for column in columns:
            table_widget.heading(column, text=column, anchor='w')
            table_widget.column(column, width=120, anchor='w')
        
        # Otimização: inserir dados em lote em vez de linha por linha
        values_list = [list(row.fillna('')) for _, row in dataframe.iterrows()]
        for values in values_list:
            table_widget.insert("", "end", values=values)

    def exibir_dataframe_paginado(self):
        start_index = self.pdf_current_page * self.pdf_rows_per_page
        end_index = start_index + self.pdf_rows_per_page
        df_slice = self.pdf_filtered_dataframe.iloc[start_index:end_index]
        self.exibir_dataframe(df_slice, self.pdf_table)

    def update_pdf_pagination(self):
        total_rows = len(self.pdf_filtered_dataframe)
        self.pdf_total_pages = math.ceil(total_rows / self.pdf_rows_per_page) if self.pdf_rows_per_page > 0 else 0
        self.pdf_page_label.configure(text=f"Página {self.pdf_current_page + 1} de {self.pdf_total_pages or 1}")
        self.pdf_prev_button.configure(state="normal" if self.pdf_current_page > 0 else "disabled")
        self.pdf_next_button.configure(state="normal" if self.pdf_current_page < self.pdf_total_pages - 1 else "disabled")
        self.exibir_dataframe_paginado()

    def pdf_prev_page(self):
        if self.pdf_current_page > 0:
            self.pdf_current_page -= 1
            self.update_pdf_pagination()

    def pdf_next_page(self):
        if self.pdf_current_page < self.pdf_total_pages - 1:
            self.pdf_current_page += 1
            self.update_pdf_pagination()

    def criar_botoes_de_filtro(self):
        for widget in self.filter_buttons_frame.winfo_children(): 
            widget.destroy()
        
        if self.pdf_full_dataframe.empty: 
            return
        
        center_frame = customtkinter.CTkFrame(self.filter_buttons_frame, fg_color="transparent")
        center_frame.pack(expand=True)
        
        frame_linha1 = customtkinter.CTkFrame(center_frame, fg_color="transparent")
        frame_linha1.pack(fill="x", expand=True, padx=5, pady=2)
        
        frame_linha2 = customtkinter.CTkFrame(center_frame, fg_color="transparent")
        frame_linha2.pack(fill="x", expand=True, padx=5, pady=2)
        
        for i, col_name in enumerate(self.pdf_full_dataframe.columns):
            parent_frame = frame_linha1 if i < 5 else frame_linha2
            button = customtkinter.CTkButton(parent_frame, text=f"Filtrar {col_name}", command=lambda c=col_name: self.abrir_janela_filtro(c))
            button.pack(side="left", padx=5, expand=True)

    def abrir_janela_filtro(self, column_name):
        df_to_filter = self.pdf_full_dataframe
        if column_name not in df_to_filter.columns: 
            return
        
        unique_values = df_to_filter[column_name].dropna().unique()
        current_selections = self.active_filters.get(column_name, list(unique_values))
        
        filter_win = FilterWindow(self, column_name, unique_values, current_selections)
        self.wait_window(filter_win)
        
        if hasattr(filter_win, 'selections') and filter_win.selections is not None:
            self.log(f"Filtro para a coluna '{column_name}' aplicado.")
            self.atualizar_filtros(column_name, filter_win.selections)

    def atualizar_filtros(self, column_name, selections):
        self.active_filters[column_name] = selections
        self._executar_filtragem_completa()

    def csv_tab_setup(self):
        self.tab_csv.grid_columnconfigure(0, weight=1)
        self.tab_csv.grid_rowconfigure(1, weight=1)
        
        csv_main_controls_frame = customtkinter.CTkFrame(self.tab_csv, fg_color="transparent")
        csv_main_controls_frame.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        
        load_match_frame = customtkinter.CTkFrame(csv_main_controls_frame, fg_color="transparent")
        load_match_frame.pack(side="top", fill="x", padx=5, pady=5)
        
        self.load_csv_button = customtkinter.CTkButton(load_match_frame, text="Importar CSV", command=self.importar_csv)
        self.load_csv_button.pack(side="left", padx=5)
        
        self.match_button = customtkinter.CTkButton(load_match_frame, text="Preencher Nomes (Match)", command=self.run_matching_process)
        self.match_button.pack(side="left", padx=5)
        
        self.fill_codes_button = customtkinter.CTkButton(load_match_frame, text="Preencher Códigos", command=self.preencher_codigos)
        self.fill_codes_button.pack(side="left", padx=5)
        
        self.save_csv_button = customtkinter.CTkButton(load_match_frame, text="Salvar CSV Modificado", command=self.salvar_csv_modificado)
        self.save_csv_button.pack(side="left", padx=5)
        
        self.export_ambiguity_button = customtkinter.CTkButton(load_match_frame, text="Exportar Ambig.", command=self.exportar_log_ambiguidade)
        self.export_ambiguity_button.pack(side="left", padx=15)
        
        self.import_resolution_button = customtkinter.CTkButton(load_match_frame, text="Importar Resol.", command=self.importar_resolucoes)
        self.import_resolution_button.pack(side="left", padx=5)
        
        self.generate_script_button = customtkinter.CTkButton(load_match_frame, text="Gerar Script OLT", command=self.gerar_script_olt)
        self.generate_script_button.pack(side="left", padx=5)
        
        edit_tool_frame = customtkinter.CTkFrame(csv_main_controls_frame)
        edit_tool_frame.pack(side="top", fill="x", padx=5, pady=10)
        
        customtkinter.CTkLabel(edit_tool_frame, text="Edição Manual:", font=customtkinter.CTkFont(weight="bold")).grid(row=0, column=0, padx=10, pady=5, sticky="w")
        customtkinter.CTkLabel(edit_tool_frame, text="Cliente:").grid(row=1, column=0, padx=(10,0), pady=5, sticky="w")
        
        self.cliente_edit_entry = customtkinter.CTkEntry(edit_tool_frame, width=300)
        self.cliente_edit_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        
        customtkinter.CTkLabel(edit_tool_frame, text="Descrição:").grid(row=2, column=0, padx=(10,0), pady=5, sticky="w")
        
        self.descricao_edit_entry = customtkinter.CTkEntry(edit_tool_frame, width=300)
        self.descricao_edit_entry.grid(row=2, column=1, padx=5, pady=5, sticky="ew")
        
        # Adicionar campo para o código
        customtkinter.CTkLabel(edit_tool_frame, text="Código:").grid(row=3, column=0, padx=(10,0), pady=5, sticky="w")
        self.cod_edit_entry = customtkinter.CTkEntry(edit_tool_frame, width=300)
        self.cod_edit_entry.grid(row=3, column=1, padx=5, pady=5, sticky="ew")
        
        # Ajustar o botão para ocupar mais linhas
        self.apply_edit_button = customtkinter.CTkButton(edit_tool_frame, text="Aplicar Edição", command=self.aplicar_edicao_manual)
        self.apply_edit_button.grid(row=1, column=2, rowspan=3, padx=10, pady=5)
        
        table_frame_container = customtkinter.CTkFrame(self.tab_csv, fg_color="transparent")
        table_frame_container.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")
        table_frame_container.grid_rowconfigure(0, weight=1)
        table_frame_container.grid_columnconfigure(0, weight=1)
        
        self.csv_table = self.create_and_place_table(table_frame_container)
        self.csv_table.bind("<<TreeviewSelect>>", self.on_row_selected)

    def on_row_selected(self, event):
        selected_items = self.csv_table.selection()
        if not selected_items: 
            return
        
        selected_row_id = selected_items[0]
        row_values = self.csv_table.item(selected_row_id, "values")
        columns = list(self.csv_table["columns"])
        
        self.cliente_edit_entry.delete(0, "end")
        self.descricao_edit_entry.delete(0, "end")
        self.cod_edit_entry.delete(0, "end")  # Adicionado
        
        if 'CLIENTE' in columns: 
            self.cliente_edit_entry.insert(0, row_values[columns.index('CLIENTE')])
        
        desc_col = next((c for c in columns if 'descri' in c.lower()), None)
        if desc_col: 
            self.descricao_edit_entry.insert(0, row_values[columns.index(desc_col)])
        
        if 'Cód.' in columns:  # Adicionado
            self.cod_edit_entry.insert(0, row_values[columns.index('Cód.')])

    def aplicar_edicao_manual(self):
        selected_items = self.csv_table.selection()
        if not selected_items:
            messagebox.showwarning("Aviso", "Nenhuma linha selecionada na tabela CSV.")
            return
        
        selected_row_id = selected_items[0]
        try:
            df_index = self.csv_dataframe.index[self.csv_table.index(selected_row_id)]
            self.csv_dataframe.loc[df_index, 'CLIENTE'] = self.cliente_edit_entry.get()
            
            desc_col = next((c for c in self.csv_dataframe.columns if 'descri' in c.lower()), None)
            if desc_col:
                self.csv_dataframe.loc[df_index, desc_col] = self.descricao_edit_entry.get()
            
            # Adicionado: atualizar a coluna "Cód."
            if 'Cód.' in self.csv_dataframe.columns:
                self.csv_dataframe.loc[df_index, 'Cód.'] = self.cod_edit_entry.get()
            
            self.exibir_dataframe(self.csv_dataframe, self.csv_table)
            self.log("Linha do CSV editada manualmente.")
        except IndexError:
            self.log("Erro ao aplicar edição: O índice da tabela não corresponde ao DataFrame.")
            messagebox.showerror("Erro", "Ocorreu um erro ao tentar aplicar a edição. Tente recarregar os dados.")

    def run_matching_process(self):
        if self.pdf_filtered_dataframe.empty or self.csv_dataframe.empty:
            messagebox.showwarning("Aviso", "Carregue os dados do PDF e do CSV primeiro, e aplique os filtros necessários no PDF.")
            return
        
        self.log("Iniciando processo de preenchimento de nomes (Match)...")
        
        pdf_mac_col = next((c for c in self.pdf_filtered_dataframe.columns if 'mac' in c.lower()), None)
        csv_mac_col = next((c for c in self.csv_dataframe.columns if 'mac' in c.lower()), None)
        csv_olt_col = next((c for c in self.csv_dataframe.columns if 'olt' in c.lower()), None)
        csv_fsp_col = next((c for c in self.csv_dataframe.columns if 'f/s/p' in c.lower()), None)
        
        if not pdf_mac_col or not csv_mac_col:
            messagebox.showerror("Erro", "Coluna de MAC não encontrada em um dos arquivos.")
            return
        
        if not csv_olt_col or not csv_fsp_col:
            messagebox.showerror("Erro", "Coluna 'OLT' ou 'F/S/P' não encontrada no CSV.")
            return
        
        self.csv_dataframe['CLIENTE'] = self.csv_dataframe.get('CLIENTE', pd.Series(dtype='str')).astype(str)
        # Garantir que a coluna "Cód." exista no CSV
        if 'Cód.' not in self.csv_dataframe.columns:
            self.csv_dataframe['Cód.'] = ''
            
        self.disambiguation_queue.clear()
        self.ambiguity_log_df = pd.DataFrame()  # Reset ambiguity log
        
        ambiguity_data = []
        updates_count = 0
        
        # Otimização: pré-compilar regex para melhor performance
        huawei_pattern = re.compile(r'HUAWEI\s+\d+\s*-\s*(\d+)\s*-')
        
        for index, row in self.csv_dataframe.iterrows():
            mac = row.get(csv_mac_col)
            if not mac or pd.isna(mac): 
                continue
            
            # Otimização: converter para maiúsculas uma vez
            mac_upper = str(mac).upper()
            matches = self.pdf_filtered_dataframe[self.pdf_filtered_dataframe[pdf_mac_col].str.upper() == mac_upper]
            
            if len(matches) == 1:
                # Preencher CLIENTE e Cód.
                self.csv_dataframe.loc[index, 'CLIENTE'] = matches.iloc[0]['Nome']
                self.csv_dataframe.loc[index, 'Cód.'] = matches.iloc[0]['Cód.']  # Adicionado
                updates_count += 1
            elif len(matches) > 1:
                csv_olt = str(row.get(csv_olt_col, '')).strip().upper()
                csv_fsp = str(row.get(csv_fsp_col, '')).strip()
                fsp_parts = csv_fsp.split('/') if '/' in csv_fsp else []
                csv_s_value = fsp_parts[1] if len(fsp_parts) == 3 else ''
                
                best_match = None
                exact_matches = []
                
                for _, match_row in matches.iterrows():
                    pdf_ponto_acesso = str(match_row.get('Ponto de Acesso', '')).strip().upper()
                    huawei_match = huawei_pattern.search(pdf_ponto_acesso)
                    pdf_s_value = huawei_match.group(1) if huawei_match else ''
                    
                    if csv_olt and pdf_ponto_acesso and csv_olt in pdf_ponto_acesso and csv_s_value and pdf_s_value == csv_s_value:
                        exact_matches.append(match_row)
                    
                    # Adicionar à lista de ambiguidades para o log
                    ambiguity_data.append({
                        'MAC': mac,
                        'Nome': match_row['Nome'],
                        'Marcar_Correto': '',
                        'Cód.': match_row.get('Cód.', ''),
                        'Data Cad.': match_row.get('Data Cad.', ''),
                        'Username': match_row.get('Username', ''),
                        'Servidor': match_row.get('Servidor', ''),
                        'Ponto de Acesso': match_row.get('Ponto de Acesso', ''),
                        'Plano de Acesso': match_row.get('Plano de Acesso', ''),
                        'Status': match_row.get('Status', ''),
                        'Contrato': match_row.get('Contrato', '')
                    })
                
                # Resolver automaticamente se houver exatamente uma correspondência exata
                if len(exact_matches) == 1:
                    self.csv_dataframe.loc[index, 'CLIENTE'] = exact_matches[0]['Nome']
                    self.csv_dataframe.loc[index, 'Cód.'] = exact_matches[0]['Cód.']  # Adicionado
                    self.log(f"Ambiguidade para MAC {mac} resolvida automaticamente: Nome '{exact_matches[0]['Nome']}' (OLT e S correspondem).")
                    updates_count += 1
                else:
                    # Se houver múltiplas ou nenhuma correspondência exata, adicionar à fila de ambiguidades
                    self.disambiguation_queue.append({'csv_index': index, 'csv_row': row, 'matches_df': matches})
        
        if ambiguity_data:
            self.ambiguity_log_df = pd.DataFrame(ambiguity_data)
            self.export_ambiguity_button.configure(state="normal")
        else:
            self.export_ambiguity_button.configure(state="disabled")
        
        self.exibir_dataframe(self.csv_dataframe, self.csv_table)
        self.log(f"{updates_count} nomes preenchidos automaticamente.")
        
        if not self.disambiguation_queue:
            messagebox.showinfo("Concluído", f"{updates_count} nomes atualizados. Nenhuma ambiguidade encontrada.")
        else:
            self.log(f"Encontrados {len(self.disambiguation_queue)} casos de ambiguidade.")
            messagebox.showinfo("Atenção", f"{updates_count} nomes preenchidos. Foram encontrados {len(self.disambiguation_queue)} casos ambíguos a serem resolvidos.")
            self.process_next_ambiguous_case()

    def preencher_codigos(self):
        """Preenche a coluna Cód. no CSV com base nas correspondências de MAC ou Nome."""
        if self.pdf_filtered_dataframe.empty or self.csv_dataframe.empty:
            messagebox.showwarning("Aviso", "Carregue os dados do PDF e do CSV primeiro.")
            return
        
        self.log("Iniciando processo de preenchimento de códigos...")
        
        # Verificar se as colunas necessárias existem
        pdf_mac_col = next((c for c in self.pdf_filtered_dataframe.columns if 'mac' in c.lower()), None)
        pdf_nome_col = 'Nome'  # Nome fixo no PDF
        
        csv_mac_col = next((c for c in self.csv_dataframe.columns if 'mac' in c.lower()), None)
        csv_cliente_col = next((c for c in self.csv_dataframe.columns if 'cliente' in c.lower()), None)
        
        if not pdf_mac_col or not csv_mac_col:
            messagebox.showerror("Erro", "Coluna de MAC não encontrada em um dos arquivos.")
            return
        
        if pdf_nome_col not in self.pdf_filtered_dataframe.columns:
            messagebox.showerror("Erro", "Coluna 'Nome' não encontrada no PDF.")
            return
        
        if csv_cliente_col not in self.csv_dataframe.columns:
            messagebox.showerror("Erro", "Coluna 'CLIENTE' não encontrada no CSV.")
            return
        
        # Garantir que a coluna "Cód." exista no CSV
        if 'Cód.' not in self.csv_dataframe.columns:
            self.csv_dataframe['Cód.'] = ''
        
        # Contador para atualizações
        updates_count = 0
        
        # Primeiro, tentar correspondência por MAC
        for index, row in self.csv_dataframe.iterrows():
            # Pular se o código já estiver preenchido
            if pd.notna(row.get('Cód.', '')) and row.get('Cód.', '') != '':
                continue
                
            mac = row.get(csv_mac_col)
            if not mac or pd.isna(mac): 
                continue
            
            # Converter para maiúsculas uma vez
            mac_upper = str(mac).upper()
            matches = self.pdf_filtered_dataframe[self.pdf_filtered_dataframe[pdf_mac_col].str.upper() == mac_upper]
            
            if len(matches) == 1:
                # Preencher Cód.
                self.csv_dataframe.loc[index, 'Cód.'] = matches.iloc[0]['Cód.']
                updates_count += 1
        
        # Segundo, tentar correspondência por Nome para os que não foram preenchidos por MAC
        for index, row in self.csv_dataframe.iterrows():
            # Pular se o código já estiver preenchido
            if pd.notna(row.get('Cód.', '')) and row.get('Cód.', '') != '':
                continue
                
            cliente = row.get(csv_cliente_col)
            if not cliente or pd.isna(cliente): 
                continue
            
            # Converter para maiúsculas uma vez
            cliente_upper = str(cliente).upper()
            matches = self.pdf_filtered_dataframe[self.pdf_filtered_dataframe[pdf_nome_col].str.upper() == cliente_upper]
            
            if len(matches) == 1:
                # Preencher Cód.
                self.csv_dataframe.loc[index, 'Cód.'] = matches.iloc[0]['Cód.']
                updates_count += 1
        
        self.exibir_dataframe(self.csv_dataframe, self.csv_table)
        self.log(f"{updates_count} códigos preenchidos automaticamente.")
        messagebox.showinfo("Concluído", f"{updates_count} códigos foram preenchidos automaticamente.")

    def resolve_ambiguity(self, decision, value, cod_value):
        if not self.current_disambiguation_task: 
            return
        
        csv_index = self.current_disambiguation_task['csv_index']
        if decision == 'UPDATE':
            self.csv_dataframe.loc[csv_index, 'CLIENTE'] = value
            if cod_value is not None:  # Se temos um código (veio do PDF)
                self.csv_dataframe.loc[csv_index, 'Cód.'] = cod_value
            self.log(f"Ambiguidade para o índice {csv_index} resolvida com o nome '{value}' e código '{cod_value}'.")
        else: # KEEP
            self.log(f"Ambiguidade para o índice {csv_index} resolvida mantendo o nome original.")
        
        self.exibir_dataframe(self.csv_dataframe, self.csv_table)
        self.after(50, self.process_next_ambiguous_case)

    def process_next_ambiguous_case(self):
        if not self.disambiguation_queue:
            if self.current_disambiguation_task:
                self.log("Todos os casos de ambiguidade foram resolvidos.")
                messagebox.showinfo("Concluído", "Todos os casos ambíguos foram resolvidos.")
                self.current_disambiguation_task = None
            return
        
        self.current_disambiguation_task = self.disambiguation_queue.pop(0)
        DisambiguationWindow(self, self.current_disambiguation_task['csv_row'], self.current_disambiguation_task['matches_df'], self.resolve_ambiguity)

    def importar_csv(self):
        path = filedialog.askopenfilename(title="Selecione o CSV", filetypes=[("Arquivos CSV", "*.csv"), ("Todos", "*.*")])
        if not path: 
            return
        
        try:
            # Otimização: especificar dtype para evitar inferência
            self.csv_dataframe = pd.read_csv(path, sep=None, engine='python', on_bad_lines='warn', dtype=str).fillna('')
            
            # Garantir que as colunas "CLIENTE" e "Cód." existam
            if 'CLIENTE' not in self.csv_dataframe.columns:
                self.csv_dataframe['CLIENTE'] = ''
            if 'Cód.' not in self.csv_dataframe.columns:
                self.csv_dataframe['Cód.'] = ''
            
            self.exibir_dataframe(self.csv_dataframe, self.csv_table)
            self.log(f"{len(self.csv_dataframe)} registros do CSV carregados de {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Erro ao Ler CSV", f"Não foi possível ler o arquivo.\n{e}")

    def salvar_csv_modificado(self):
        if self.csv_dataframe.empty:
            messagebox.showwarning("Aviso", "Não há dados CSV para salvar.")
            return
        
        path = filedialog.asksaveasfilename(title="Salvar CSV Modificado", defaultextension=".csv", filetypes=[("Arquivos CSV", "*.csv")])
        if not path: 
            return
        
        try:
            self.csv_dataframe.to_csv(path, index=False, sep=';', encoding='utf-8-sig')
            self.log(f"CSV modificado salvo em: {path}")
            messagebox.showinfo("Sucesso", f"Arquivo salvo com sucesso em:\n{path}")
        except Exception as e:
            messagebox.showerror("Erro ao Salvar", f"Não foi possível salvar o arquivo.\n{e}")

    def exportar_log_ambiguidade(self):
        if self.ambiguity_log_df.empty:
            messagebox.showwarning("Aviso", "Nenhum log de ambiguidade para exportar.")
            return
        
        path = filedialog.asksaveasfilename(title="Salvar Log de Ambiguidade", defaultextension=".xlsx", filetypes=[("Arquivos Excel", "*.xlsx")])
        if not path: 
            return
        
        try:
            self.ambiguity_log_df.to_excel(path, index=False, engine='openpyxl')
            self.log(f"Log de ambiguidade salvo em: {path}")
            messagebox.showinfo("Sucesso", f"Log salvo em:\n{path}")
        except Exception as e:
            self.log(f"Falha ao exportar log de ambiguidade: {e}")
            messagebox.showerror("Erro ao Salvar", f"Não foi possível salvar o arquivo.\n{e}")

    def importar_resolucoes(self):
        if self.csv_dataframe.empty:
            messagebox.showwarning("Aviso", "Importe o arquivo CSV principal primeiro.")
            return
        
        path = filedialog.askopenfilename(title="Importar XLSX com Resoluções", filetypes=[("Arquivos Excel", "*.xlsx")])
        if not path: 
            return
        
        try:
            resolved_df = pd.read_excel(path, engine='openpyxl', dtype=str).fillna('')
            
            if 'Marcar_Correto' not in resolved_df.columns or 'MAC' not in resolved_df.columns or 'Nome' not in resolved_df.columns:
                messagebox.showerror("Erro", "O arquivo XLSX deve conter as colunas 'MAC', 'Nome' e 'Marcar_Correto'.")
                return
            
            marked_rows = resolved_df[resolved_df['Marcar_Correto'].astype(str).str.strip() == '*'].copy()
            if marked_rows.empty:
                messagebox.showinfo("Aviso", "Nenhuma linha marcada com '*' foi encontrada.")
                return
            
            updates = 0
            csv_mac_col = next((c for c in self.csv_dataframe.columns if 'mac' in c.lower()), 'MAC')
            
            # Otimização: pré-compilar regex para melhor performance
            for _, row in marked_rows.iterrows():
                mask = self.csv_dataframe[csv_mac_col].str.upper() == row['MAC'].upper()
                if mask.any():
                    self.csv_dataframe.loc[mask, 'CLIENTE'] = row['Nome']
                    # Se o arquivo de resoluções também tiver a coluna "Cód.", usá-la
                    if 'Cód.' in row and pd.notna(row['Cód.']):
                        self.csv_dataframe.loc[mask, 'Cód.'] = row['Cód.']
                    updates += 1
            
            self.exibir_dataframe(self.csv_dataframe, self.csv_table)
            self.log(f"{updates} cliente(s) atualizados a partir do arquivo de resoluções.")
            messagebox.showinfo("Importação Concluída", f"{updates} cliente(s) atualizados.")
        except Exception as e:
            self.log(f"Erro ao importar resoluções: {e}")
            messagebox.showerror("Erro ao Importar", f"Não foi possível processar o arquivo.\nErro: {e}")

    def gerar_script_olt(self):
        if self.csv_dataframe.empty:
            messagebox.showwarning("Aviso", "Não há dados CSV para gerar o script.")
            return
        
        required = ['F/S/P', 'ONT ID']
        desc_col = next((c for c in self.csv_dataframe.columns if 'descri' in c.lower()), None)
        
        if not all(c in self.csv_dataframe.columns for c in required) or not desc_col:
            messagebox.showerror("Erro", "Colunas necessárias ('F/S/P', 'ONT ID', 'Descrição') não encontradas.")
            return
        
        script, last_interface, errors = ["en", "conf"], None, 0
        
        # Otimização: ordenar e remover NaN de uma vez
        df_sorted = self.csv_dataframe.sort_values(by=required).dropna(subset=required + [desc_col])
        
        for _, row in df_sorted.iterrows():
            try:
                fsp, ont_id, desc = str(row['F/S/P']), str(row['ONT ID']), str(row[desc_col])
                parts = fsp.split('/')
                
                if len(parts) != 3:
                    errors += 1
                    continue
                
                interface = f"{parts[0]}/{parts[1]}"
                port = parts[2]
                
                if interface != last_interface:
                    if last_interface: 
                        script.append("exit")
                    script.append(f"interface gpon {interface}")
                    last_interface = interface
                
                script.append(f'ont modify {port} {ont_id} desc "{desc}"')
            except Exception: 
                errors += 1
        
        if last_interface: 
            script.append("exit")
        
        if errors > 0: 
            messagebox.showwarning("Aviso", f"{errors} linha(s) ignoradas por dados inválidos.")
        
        self.exibir_script_em_janela("\n".join(script))

    def exibir_script_em_janela(self, script_text):
        win = customtkinter.CTkToplevel(self)
        win.title("Script de Configuração da OLT")
        win.geometry("600x700")
        
        txt = customtkinter.CTkTextbox(win, font=("Consolas", 12))
        txt.pack(expand=True, fill="both", padx=10, pady=10)
        txt.insert("1.0", script_text)
        txt.configure(state="disabled")
        
        def copy():
            pyperclip.copy(script_text)
            btn.configure(text="Copiado!")
            win.after(2000, lambda: btn.configure(text="Copiar Tudo"))
        
        btn = customtkinter.CTkButton(win, text="Copiar Tudo", command=copy)
        btn.pack(pady=10)

    def exportar_pdf_para_csv(self):
        if self.pdf_filtered_dataframe.empty:
            messagebox.showwarning("Aviso", "Não há dados na tabela para exportar.")
            return
        
        path = filedialog.asksaveasfilename(
            title="Salvar Dados do PDF como CSV",
            defaultextension=".csv",
            filetypes=[("Arquivos CSV", "*.csv")]
        )
        
        if not path:
            self.log("Exportação para CSV cancelada.")
            return
        
        try:
            self.pdf_filtered_dataframe.to_csv(path, index=False, sep=';', encoding='utf-8-sig')
            self.log(f"Dados do PDF exportados para: {path}")
            messagebox.showinfo("Sucesso", f"Dados exportados com sucesso para:\n{path}")
        except Exception as e:
            self.log(f"Falha ao exportar dados do PDF: {e}")
            messagebox.showerror("Erro ao Salvar", f"Não foi possível salvar o arquivo.\n{e}")

    def importar_pdf_csv(self):
        """Importa um arquivo CSV para a aba de dados do PDF, substituindo a extração do PDF."""
        path = filedialog.askopenfilename(
            title="Importar Dados do PDF de um CSV",
            filetypes=[("Arquivos CSV", "*.csv"), ("Todos", "*.*")]
        )
        
        if not path:
            self.log("Importação de CSV para PDF cancelada.")
            return
        
        try:
            # Tentar detectar o separador automaticamente
            with open(path, 'r', encoding='utf-8-sig') as f:
                first_line = f.readline().strip()
                
            # Remover BOM se presente
            if first_line.startswith('\ufeff'):
                first_line = first_line[1:]
                
            # Detectar separador
            if ';' in first_line:
                separator = ';'
            elif ',' in first_line:
                separator = ','
            elif '\t' in first_line:
                separator = '\t'
            else:
                separator = ';'
                
            self.log(f"Separador detectado: '{separator}'")
            self.log(f"Primeira linha: {first_line}")
            
            # Ler o arquivo CSV com o separador detectado
            self.pdf_full_dataframe = pd.read_csv(
                path, 
                sep=separator, 
                engine='python', 
                on_bad_lines='warn', 
                dtype=str,
                encoding='utf-8-sig'
            ).fillna('')
            
            # Verificar se as colunas necessárias existem
            required_columns = ['Cód.', 'Nome', 'Data Cad.', 'Username', 'Mac', 'Servidor', 'Ponto de Acesso', 'Plano de Acesso', 'Status', 'Contrato']
            missing_columns = [col for col in required_columns if col not in self.pdf_full_dataframe.columns]
            
            # Se ainda faltam colunas, tentar mapeamento alternativo
            if missing_columns:
                self.log(f"Colunas no arquivo: {list(self.pdf_full_dataframe.columns)}")
                self.log(f"Colunas faltantes: {missing_columns}")
                
                # Mapeamento de nomes de colunas alternativos
                column_mapping = {
                    'Cód.': ['Cód', 'Cod', 'COD', 'Codigo', 'Código'],
                    'Nome': ['nome', 'NOME', 'Name'],
                    'Data Cad.': ['Data Cad', 'Data Cadastro', 'Data'],
                    'Username': ['usuario', 'Usuario', 'USER', 'user'],
                    'Mac': ['MAC', 'Endereço MAC'],
                    'Servidor': ['servidor', 'SERVER', 'Server'],
                    'Ponto de Acesso': ['Ponto de Acesso', 'Ponto Acesso', 'Access Point'],
                    'Plano de Acesso': ['Plano de Acesso', 'Plano', 'Plano'],
                    'Status': ['status', 'STATUS', 'Estado'],
                    'Contrato': ['contrato', 'CONTRATO', 'Contract']
                }
                
                # Tentar encontrar colunas alternativas
                for col in missing_columns[:]:
                    for alt_name in column_mapping.get(col, []):
                        if alt_name in self.pdf_full_dataframe.columns:
                            # Renomear a coluna para o nome padrão
                            self.pdf_full_dataframe = self.pdf_full_dataframe.rename(columns={alt_name: col})
                            missing_columns.remove(col)
                            self.log(f"Coluna '{alt_name}' renomeada para '{col}'")
                            break
                
                # Verificar novamente se ainda faltam colunas
                if missing_columns:
                    messagebox.showerror(
                        "Erro de Importação",
                        f"O arquivo CSV não contém todas as colunas necessárias.\nColunas faltantes: {', '.join(missing_columns)}\n\nColunas encontradas: {', '.join(self.pdf_full_dataframe.columns[:5])}..."
                    )
                    self.log(f"Falha na importação: colunas faltantes - {', '.join(missing_columns)}")
                    return
            
            # Limpar filtros e atualizar a interface
            self.limpar_filtros_e_busca_pdf()
            
            self.log(f"Dados do PDF importados com sucesso de {os.path.basename(path)}. Total de {len(self.pdf_full_dataframe)} registros.")
            messagebox.showinfo(
                "Importação Concluída",
                f"{len(self.pdf_full_dataframe)} registros do PDF foram importados do arquivo CSV."
            )
        except Exception as e:
            messagebox.showerror("Erro ao Importar", f"Não foi possível ler o arquivo CSV.\nErro: {e}")
            self.log(f"Falha ao importar CSV para PDF: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    app = App()
    app.mainloop()
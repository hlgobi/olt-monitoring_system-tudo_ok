import pandas as pd
import openpyxl
from tkinter import filedialog, messagebox

def read_excel_with_fallback(file_path, skip_rows=7):
    """Tenta ler o arquivo Excel com diferentes métodos"""
    try:
        # Primeira tentativa: método padrão do pandas
        return pd.read_excel(file_path, skiprows=skip_rows)
    except Exception as e1:
        try:
            # Segunda tentativa: usando openpyxl explicitamente
            return pd.read_excel(file_path, engine='openpyxl', skiprows=skip_rows)
        except Exception as e2:
            try:
                # Terceira tentativa: usando xlrd (para versões antigas do Excel)
                return pd.read_excel(file_path, engine='xlrd', skiprows=skip_rows)
            except Exception as e3:
                try:
                    # Quarta tentativa: lendo como CSV (caso tenha sido salvo incorretamente)
                    return pd.read_csv(file_path, skiprows=skip_rows)
                except Exception as e4:
                    raise Exception(f"Todas as tentativas falharam: {str(e1)}, {str(e2)}, {str(e3)}, {str(e4)}")

def main():
    # Seleciona múltiplos arquivos .xlsx
    file_paths = filedialog.askopenfilenames(
        title="Selecione os arquivos Excel (.xlsx)",
        filetypes=[("Arquivos Excel", "*.xlsx")]
    )
    
    if not file_paths:
        messagebox.showinfo("Informação", "Nenhum arquivo selecionado.")
        return
    
    dfs = []  # Lista para armazenar DataFrames de cada arquivo válido
    invalid_files = []  # Lista para rastrear arquivos inválidos
    
    for file_path in file_paths:
        try:
            # Tenta ler o arquivo com fallback
            df = read_excel_with_fallback(file_path, skip_rows=7)
            dfs.append(df)
        except Exception as e:
            error_msg = str(e)
            if "sharedStrings.xml" in error_msg or "corrupted" in error_msg.lower():
                invalid_files.append((file_path, "Arquivo corrompido ou inválido"))
            else:
                invalid_files.append((file_path, f"Erro desconhecido: {error_msg}"))
    
    # Mostra resumo dos arquivos inválidos
    if invalid_files:
        error_details = "\n".join([f"- {path}: {reason}" for path, reason in invalid_files])
        messagebox.showwarning(
            "Atenção", 
            f"Foram encontrados {len(invalid_files)} arquivos inválidos:\n\n{error_details}\n\nContinuando com os arquivos válidos..."
        )
    
    if not dfs:
        messagebox.showerror("Erro", "Nenhum arquivo válido foi encontrado. Verifique os arquivos selecionados.")
        return
    
    # Combina todos os DataFrames válidos
    combined_df = pd.concat(dfs, ignore_index=True)
    
    # Salva o arquivo combinado
    output_file = filedialog.asksaveasfilename(
        title="Salve o arquivo combinado",
        defaultextension=".xlsx",
        filetypes=[("Arquivos Excel", "*.xlsx")]
    )
    
    if output_file:
        try:
            combined_df.to_excel(output_file, index=False)
            messagebox.showinfo("Sucesso", f"Arquivo combinado salvo como: {output_file}")
        except Exception as e:
            messagebox.showerror("Erro ao salvar", f"Falha ao salvar o arquivo: {str(e)}")

if __name__ == "__main__":
    main()
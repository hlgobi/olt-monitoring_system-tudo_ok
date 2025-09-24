# -*- coding: utf-8 -*-

"""
Script para Unificação de Arquivos Excel.

Este módulo contém a funcionalidade para encontrar todos os arquivos Excel (com extensão
.xlsx ou .xls) em um diretório de entrada, ler os dados de cada um deles e
consolidá-los em um único arquivo Excel de saída.

As configurações de diretório de entrada e nome do arquivo de saída são importadas
do arquivo 'config.py' para manter a organização e facilitar a manutenção.
"""

import os
import pandas as pd
import glob
from typing import List

# Importa as configurações de diretórios e arquivos do módulo de configuração.
# Isso centraliza os caminhos e facilita a alteração sem mexer no código funcional.
try:
    from config import EXCEL_INPUT_DIR, CONSOLIDATED_EXCEL_FILE, OUTPUT_DIR
except ImportError:
    # Define valores padrão caso o config.py não seja encontrado ou as variáveis estejam ausentes.
    # Embora não seja o ideal, garante que o script não falhe na importação.
    print("Aviso: Não foi possível importar as configurações de 'config.py'. Usando valores padrão.")
    EXCEL_INPUT_DIR = 'excel_files'
    OUTPUT_DIR = 'output'
    CONSOLIDATED_EXCEL_FILE = 'consolidated_data.xlsx'

def find_excel_files(input_directory: str) -> List[str]:
    """
    Encontra todos os arquivos Excel (.xlsx, .xls) em um diretório específico.

    Args:
        input_directory (str): O caminho para o diretório onde os arquivos Excel estão localizados.

    Returns:
        List[str]: Uma lista contendo os caminhos completos de todos os arquivos Excel encontrados.
                     Retorna uma lista vazia se nenhum arquivo for encontrado.
    """
    # Padrões de busca para extensões .xlsx e .xls.
    search_pattern_xlsx = os.path.join(input_directory, '*.xlsx')
    search_pattern_xls = os.path.join(input_directory, '*.xls')

    # Usa glob para encontrar os arquivos que correspondem aos padrões.
    files_xlsx = glob.glob(search_pattern_xlsx)
    files_xls = glob.glob(search_pattern_xls)

    # Retorna a lista combinada de arquivos.
    return files_xlsx + files_xls

def merge_excel_files(file_list: List[str], output_file: str) -> None:
    """
    Lê uma lista de arquivos Excel e unifica seus conteúdos em um único DataFrame,
    que é então salvo como um novo arquivo Excel.

    Args:
        file_list (List[str]): A lista de caminhos dos arquivos Excel a serem unificados.
        output_file (str): O caminho completo para o arquivo Excel de saída consolidado.
    """
    # Verifica se a lista de arquivos não está vazia.
    if not file_list:
        print("Nenhum arquivo Excel encontrado para unificar.")
        return

    # Lista para armazenar os DataFrames de cada arquivo.
    all_dataframes = []

    # Itera sobre cada arquivo na lista.
    for file in file_list:
        try:
            # Lê o arquivo Excel e o converte em um DataFrame do pandas.
            df = pd.read_excel(file, engine='openpyxl') # 'openpyxl' é o motor para .xlsx
            # Adiciona o DataFrame à lista.
            all_dataframes.append(df)
            print(f"Arquivo '{os.path.basename(file)}' lido com sucesso.")
        except Exception as e:
            # Captura e informa qualquer erro que ocorra durante a leitura de um arquivo.
            print(f"Erro ao ler o arquivo '{os.path.basename(file)}': {e}")

    # Verifica se algum DataFrame foi carregado com sucesso.
    if not all_dataframes:
        print("Nenhum dado foi carregado. O arquivo de saída não será gerado.")
        return

    # Concatena todos os DataFrames da lista em um único DataFrame.
    # ignore_index=True reinicia o índice do DataFrame consolidado.
    consolidated_df = pd.concat(all_dataframes, ignore_index=True)

    try:
        # Garante que o diretório de saída exista antes de tentar salvar o arquivo.
        output_dir = os.path.dirname(output_file)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"Diretório de saída '{output_dir}' criado.")

        # Salva o DataFrame consolidado em um novo arquivo Excel.
        # index=False evita que o índice do DataFrame seja escrito como uma coluna no Excel.
        consolidated_df.to_excel(output_file, index=False, engine='openpyxl')
        print(f"\nArquivos unificados com sucesso! O resultado foi salvo em '{output_file}'")

    except Exception as e:
        # Captura e informa qualquer erro durante o processo de salvamento.
        print(f"Erro ao salvar o arquivo consolidado: {e}")

def main():
    """
    Função principal que orquestra o processo de unificação dos arquivos Excel.
    """
    print("--- Iniciando processo de unificação de arquivos Excel ---")

    # Encontra os arquivos Excel no diretório de entrada especificado em config.py.
    excel_files_to_merge = find_excel_files(EXCEL_INPUT_DIR)

    # Define o caminho completo para o arquivo de saída.
    # Ex: 'output/consolidated_data.xlsx'
    output_path = os.path.join(OUTPUT_DIR, CONSOLIDATED_EXCEL_FILE)

    # Chama a função para unificar os arquivos encontrados.
    merge_excel_files(excel_files_to_merge, output_path)

    print("\n--- Processo finalizado ---")

if __name__ == '__main__':
    # Este bloco de código é executado apenas quando o script é chamado diretamente.
    # Isso permite que as funções deste módulo sejam importadas em outros scripts
    # sem que o código principal (main) seja executado automaticamente.
    main()
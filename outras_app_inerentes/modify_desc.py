import pandas as pd
import re
import tkinter as tk
from tkinter import filedialog

# Janela para selecionar arquivo CSV
root = tk.Tk()
root.withdraw()
entrada_csv = filedialog.askopenfilename(
    title="Selecione a planilha CSV",
    filetypes=[("CSV files", "*.csv")]
)

if not entrada_csv:
    print("❌ Nenhum arquivo selecionado.")
    exit()

saida_txt = "comandos_olt_formatados.txt"

# Corrigir a descrição da OLT
def corrigir_descricao(desc):
    if not isinstance(desc, str):
        return "BUSCAR_NO_MK"

    desc = desc.upper().strip()
    desc = re.sub(r'\s+', ' ', desc)

    if desc == "ONT_NO_DESCRIPTION":
        return "BUSCAR_NO_MK"

    # Força a descrição a começar com "A" se não começar
    if not desc.startswith("A"):
        desc = "A" + desc

    # Caso: "A7F 16S4B P13" → "A7F16S4-B P13"
    if re.fullmatch(r'^A[\dA-Z]*\s+\d+S\d+[AB] P\d+$', desc):
        partes = desc.split(" ")
        if len(partes) == 3:
            parte_1 = partes[0] + partes[1][:-1]
            letra = partes[1][-1]
            porta = partes[2]
            return f"{parte_1}-{letra} {porta}"

    # Caso: "A7F110S6AP13" ou "A7F110S6BP1" → "A7F110S6-A P13"
    if re.fullmatch(r'^A[\dA-Z]+[AB]P\d+$', desc):
        desc = re.sub(r'([AB])P(\d+)$', r'-\1 P\2', desc)
        return desc

    # Caso: "AF24S8 B" ou "AF24S8 A" → "AF24S8-B"
    if re.fullmatch(r'^A[\dA-Z]+ [AB]$', desc):
        return desc.replace(" ", "-")

    # Caso já válido: "A7F12S1 P1"
    if re.fullmatch(r'^A[\dA-Z]+ P\d+$', desc):
        return desc

    return "BUSCAR_NO_MK"

# Extrai F, S, P de F/S/P
def extrair_fsp(fsp):
    try:
        f, s, p = map(int, str(fsp).strip().split("/"))
        return f, s, p
    except:
        return None, None, None

# Carregar CSV
df = pd.read_csv(entrada_csv)
df.columns = [col.strip() for col in df.columns]
comandos = []

for _, row in df.iterrows():
    fsp = row['F/S/P']
    ont_id = row['ONT ID']
    desc_raw = row['Descrição OLT']

    f, s, p = extrair_fsp(fsp)
    desc = corrigir_descricao(desc_raw)

    if not desc:
        desc = "BUSCAR_NO_MK"

    if None not in (f, s, p) and pd.notnull(ont_id):
        bloco = [
            "enable",
            "config",
            f"interface gpon {f}/{s}",
            f'ont modify {p} {ont_id} desc "{desc}"'
        ]
        comandos.append("\n".join(bloco))

# Salvar comandos no .txt
with open(saida_txt, "w") as f:
    f.write("\n\n".join(comandos))

print(f"✅ {len(comandos)} comandos salvos no arquivo '{saida_txt}'")

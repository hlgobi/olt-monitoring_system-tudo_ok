# olt_monitoring_system/utils/helpers.py
# Este arquivo contém funções auxiliares e parsers, que são o "cérebro" da aplicação.
# Eles transformam as saídas de texto bruto dos comandos da OLT em dados estruturados e relatórios legíveis.

import time      # Para adicionar pausas (delays) e evitar sobrecarga de APIs.
import re        # Módulo de Expressões Regulares (Regex), essencial para encontrar padrões em texto.
import logging   # Para registrar informações e erros durante o parsing.
import json      # Para lidar com respostas de API no formato JSON.
import requests  # Para fazer requisições HTTP a APIs externas (como a de fabricantes de MAC).
from urllib.parse import quote  # Para formatar URLs de forma segura.
from collections import Counter # Para contar ocorrências de itens em uma lista (usado para estatísticas).

# ==============================================================================
# CONSTANTES E CONFIGURAÇÕES
# ==============================================================================

# Token de acesso para a API macvendors.com v1.
# Este token autoriza a aplicação a consultar o fabricante de um endereço MAC.
# É uma boa prática mantê-lo aqui como uma constante para fácil acesso e modificação.
MAC_VENDORS_API_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiIsImp0aSI6IjYwZDRmMTEwLTdkN2ItNDY4YS05NTJmLWFhZmYwNGI5OTA2MCJ9.eyJpc3MiOiJtYWN2ZW5kb3JzIiwiYXVkIjoibWFjdmVuZG9ycyIsImp0aSI6IjYwZDRmMTEwLTdkN2ItNDY4YS05NTJmLWFhZmYwNGI5OTA2MCIsImlhdCI6MTc0OTU4ODAwNCwiZXhwIjoyMDY0MDg0MDA0LCJzdWIiOiIxNjEyNiIsInR5cCI6ImFjY2VzcyJ9.TO6UO5oIYJpWowD67fAemfyOQTTvtCNpOBdBBnN6RUF5BILy_B_lscqrt6TneQb77pWPRC9-vgAYDcevsfflxQ"


# ==============================================================================
# FUNÇÕES DE APOIO E PARSERS
# ==============================================================================

def format_mac(raw_mac):
    """
    Limpa e formata um endereço MAC para o padrão XX:XX:XX:XX:XX:XX.
    Lida com formatos como XXXX-XXXX-XXXX, XXXX.XXXX.XXXX, XXXXXXXXXXXX, etc.
    """
    if not raw_mac or not isinstance(raw_mac, str):
        return "N/A"
    
    # Remove todos os caracteres não-alfanuméricos (pontos, hífens, dois-pontos)
    cleaned_mac = re.sub(r'[^0-9a-fA-F]', '', raw_mac).upper()
    
    # Verifica se o MAC limpo tem 12 caracteres hexadecimais
    if len(cleaned_mac) != 12:
        return "N/A"
        
    # Insere os dois-pontos para formatar
    formatted = ":".join(cleaned_mac[i:i+2] for i in range(0, 12, 2))
    return formatted

def find_mac_vendor(mac_address: str) -> str | None:
    """
    Busca o fabricante (vendor) de um endereço MAC usando a API macvendors.com v1.
    Retorna o nome do fabricante, uma mensagem de erro ou None.
    """
    # Validação inicial: não faz a busca se o MAC não for válido.
    if not mac_address or mac_address == "N/A":
        return None

    # Garante que o MAC está no formato correto antes de enviar para a API.
    formatted_mac = format_mac(mac_address)
    if formatted_mac == "N/A":
        return None

    # Constrói a URL para a requisição da API, usando 'quote' para tratar caracteres especiais.
    url = f"https://api.macvendors.com/v1/lookup/{quote(formatted_mac)}"
    # Prepara o cabeçalho de autorização com o token da API.
    headers = {"Authorization": f"Bearer {MAC_VENDORS_API_TOKEN}"}

    try:
        # Executa a requisição GET para a API com um timeout de 5 segundos.
        response = requests.get(url, headers=headers, timeout=5)
        
        # Se a resposta for 200 (OK), tenta processar o JSON.
        if response.status_code == 200:
            try:
                json_response = response.json()
                # Extrai o nome da organização do JSON de resposta.
                return json_response.get("data", {}).get("organization_name")
            except (json.JSONDecodeError, AttributeError, KeyError) as e:
                logging.error(f"Falha ao processar a resposta JSON da API de vendors: {e}")
                return None # Retorna None em caso de erro no JSON.
        # Se a resposta for 404, o MAC não foi encontrado na base de dados da API.
        elif response.status_code == 404:
            logging.warning(f"MAC {formatted_mac} não encontrado na API macvendors.com.")
            return "N/A"
        # Para outros códigos de erro, registra a falha.
        else:
            logging.error(f"API macvendors.com retornou erro {response.status_code}. Resposta: {response.text}")
            return "Erro API"
    # Captura exceções de conexão (e.g., sem internet, DNS não resolve).
    except requests.exceptions.RequestException as e:
        logging.error(f"Erro de conexão ao buscar fabricante do MAC: {e}")
        return "Erro Conexão"

def clean_response(response: str) -> str:
    """
    Limpa a saída bruta de um comando SSH, removendo caracteres de controle e formatação.
    """
    # Remove a paginação "---- More ----".
    cleaned = re.sub(r"\s*---- More \( Press 'Q' to break \) ----\s*", "", response)
    # Remove sequências de escape ANSI (usadas para cores e formatação no terminal).
    cleaned = re.sub(r"\x1b\[\d+[A-Z]", "", cleaned)
    # Remove caracteres de backspace e o caractere anterior a ele.
    cleaned = re.sub(r".\x08", "", cleaned)
    # Substitui o caractere de retorno de carro ('\r') por nada.
    cleaned = cleaned.replace('\r', '')
    return cleaned
# Em utils/helpers.py

def parse_descricao_avancada(description_str: str) -> dict:
    """
    Analisa a string de descrição da OLT para extrair informações estruturadas
    como primária, secundária e porta, ignorando dados extras (ex.: número de série, modelo).
    """
    result = {
        'primaria': 'N/A',
        'secundaria': 'N/A',
        'porta_secundaria': 'N/A'
    }
    
    if not description_str or description_str.strip().upper() in ["N/A", "ONT_NO_DESCRIPTION", ""]:
        return result
    
    original = description_str.strip()
    
    # 1. Extrai a porta (Pxx ou Sxx) em qualquer posição
    porta_match = re.search(r'\b(P\d+|S\d+)\b', original)
    if porta_match:
        result['porta_secundaria'] = porta_match.group(1).upper()
        # Remove a porta e tudo que vem depois dela (incluindo espaços)
        resto = re.split(r'\b(P\d+|S\d+)\b', original, maxsplit=1)[0].strip()
    else:
        resto = original
    
    # 2. Extrai a primária e secundária do restante
    # Divide por espaços ou hífens
    tokens = re.split(r'[\s-]+', resto)
    if tokens:
        result['primaria'] = tokens[0]
        # Se houver um segundo token e ele for válido (ex.: número, Sxx, Pxx), forma a secundária
        if len(tokens) > 1 and (tokens[1].startswith(('S', 'P')) or tokens[1].isdigit()):
            result['secundaria'] = f"{tokens[0]}-{tokens[1]}"
        # Tokens adicionais são ignorados (ex.: números de série, modelos)
    
    # Caso especial: se a porta foi extraída mas a secundária ficou como N/A, usa a porta para formar a secundária
    if result['porta_secundaria'] != 'N/A' and result['secundaria'] == 'N/A':
        result['secundaria'] = f"{result['primaria']}-{result['porta_secundaria']}"
    
    return result

def parse_ont_device_info(raw_output: str) -> tuple[str, dict]:
    """
    Analisa a saída dos comandos 'display deviceInfo' e 'display version' da ONT.
    Retorna um relatório formatado para exibição e um dicionário com os dados brutos.
    """
    parsed_data = {}
    
    # Mapeia as chaves da saída do comando para nomes amigáveis.
    display_map = [
        {'key': 'Manufacturer', 'name': 'Fabricante'},
        {'key': 'ManufacturerOUI', 'name': 'Código do fabricante (OUI)'},
        {'key': 'ModelName', 'name': 'Modelo do equipamento'},
        {'key': 'Description', 'name': 'Descrição completa'},
        {'key': 'ManufactureInfo', 'name': 'Informações de fabricação'},
        {'key': 'SpecVersion', 'name': 'Versão do padrão (SpecVersion)'},
        {'key': 'UpTime', 'name': 'Tempo ligada (UpTime)'},
        {'key': 'ReleaseTime', 'name': 'Data da versão (ReleaseTime)'},
        {'key': 'TotalMemory', 'name': 'Memória total (RAM)'},
        {'key': 'TotalFlash', 'name': 'Memória interna (Flash)'},
        {'key': 'hardware version', 'name': 'Versão de hardware'},
        {'key': 'main software version', 'name': 'Versão principal do software'},
        {'key': 'standby software version', 'name': 'Versão de backup do software'},
        {'key': 'uboot version', 'name': 'Versão do bootloader (uboot)'},
    ]
    # Cria um conjunto de chaves desejadas para uma busca mais eficiente.
    desired_keys = {item['key'] for item in display_map}
    
    # Itera sobre cada linha da saída bruta.
    for line in raw_output.splitlines():
        # Procura por linhas que contenham um '=', que geralmente indicam um par chave-valor.
        if "=" in line and not line.strip().startswith("*****"):
            parts = line.split("=", 1)
            if len(parts) == 2:
                key, value = parts[0].strip(), parts[1].strip()
                # Se a chave for uma das que queremos, armazena no dicionário.
                if key in desired_keys: parsed_data[key] = value
                
    # Se nenhum dado foi extraído, retorna uma mensagem de erro.
    if not parsed_data:
        return "Falha no parsing da seção 'device_info'. Nenhuma informação pôde ser extraída.", {}
        
    # Monta o relatório formatado para exibição.
    display_lines = ["=========================================","📦 INFORMAÇÕES GERAIS DA ONT - HUAWEI","=========================================\n","🔍 **INFORMAÇÕES DA ONT** (display deviceInfo e display version)\n"]
    for item in display_map:
        # Adiciona a linha ao relatório apenas se a chave foi encontrada.
        if item['key'] in parsed_data and parsed_data[item['key']]:
            value = parsed_data[item['key']]
            # Trunca a descrição se for muito longa para não quebrar a formatação.
            if item['key'] == 'Description': value = (value[:60] + '...') if len(value) > 63 else value
            display_lines.append(f"{item['name'].ljust(32)}= {value}")
            
    return "\n".join(display_lines), parsed_data

def parse_ont_optic_status(raw_output: str) -> tuple[str, dict]:
    """
    Analisa a saída dos comandos 'display optic' e 'display board-temperatures'.
    Retorna um relatório formatado com ícones de status e um dicionário com os dados.
    """
    parsed_data = {}
    # Regex para capturar pares chave:valor da seção de óptica.
    optic_re = re.compile(r"^\s*([^:]+?)\s*:\s*(.+?)\s*$")
    # Regex para capturar pares chave:valor da seção de temperatura.
    temps_re = re.compile(r"^\s*(\w+):(\d+)\s*$")
    
    # Itera sobre as linhas da saída bruta.
    for line in raw_output.splitlines():
        line = line.strip()
        match_optic, match_temps = optic_re.match(line), temps_re.match(line)
        if match_optic:
            key, value = match_optic.group(1).strip(), match_optic.group(2).strip()
            if key: parsed_data[key] = value
        elif match_temps:
            key, value = match_temps.group(1).strip(), match_temps.group(2).strip()
            
    if not parsed_data: return f"Falha no parsing da seção 'optic_status'.\n{raw_output}", {}
    
    # Inicia a montagem do relatório.
    display_lines = ["=========================================","📋 VERIFICAÇÃO DE FIBRA E TEMPERATURA - ONT HUAWEI","=========================================","","🔍 **INFORMAÇÕES DA FIBRA** (comando: display optic)",""]
    
    # Define as regras de validação para cada parâmetro óptico (limites, unidades, etc.).
    optic_rules = {'LinkStatus':{'name':'Estado da fibra','ok_val':'ok'},'Voltage':{'name':'Voltagem da fibra','unit':'mV','min':3000,'max':3500},'Bias':{'name':'Corrente do laser','unit':'mA','min':5,'max':30},'Temperature':{'name':'Temperatura da fibra','unit':'ºC','min':-10,'max':70},'RxPower':{'name':'Sinal recebido','unit':'dBm','min':-28.0,'max':-8.0,'warn_threshold':-25.0},'TxPower':{'name':'Sinal enviado','unit':'dBm','min':0.0,'max':4.0},'VendorSN':{'name':'Número de série da peça','info':True},'VendorPN':{'name':'Modelo da peça','info':True},'DateCode':{'name':'Data de fabricação','info':True}}
    
    # Itera sobre as regras para formatar cada linha do relatório.
    for key, rule in optic_rules.items():
        if key in parsed_data:
            value_with_unit=parsed_data[key];value_str=value_with_unit.split()[0];status_icon="⚪" # Ícone padrão
            # Se não for apenas informativo, aplica a lógica de status.
            if not rule.get('info',False):
                try:
                    # Lógica para status binário (OK/Não OK).
                    if 'ok_val' in rule:status_icon="🟢" if value_str.lower()==rule['ok_val'] else "🔴"
                    # Lógica para status baseado em faixa de valores (min/max).
                    elif 'min' in rule and 'max' in rule:
                        value_float=float(value_str)
                        if rule['min'] <= value_float <= rule['max']:
                            # Lógica especial para RxPower: amarelo se estiver perto do limite.
                            status_icon="🟡" if key=='RxPower' and value_float < rule.get('warn_threshold',-25.0) else "🟢"
                        else:status_icon="🔴" # Vermelho se estiver fora da faixa.
                except(ValueError,TypeError):status_icon="❓" # Ícone de interrogação se o valor não for numérico.
            display_lines.append(f"{status_icon} {rule['name'].ljust(25)}: {value_with_unit}")
            
    display_lines.extend(["","-----------------------------------------","🌡️ **TEMPERATURAS INTERNAS** (comando: display board-temperatures)",""])
    
    # Define as regras de validação para as temperaturas internas.
    temp_rules={'Opt':{'name':'Temperatura do chip fibra','unit':'ºC','max':70},'Soc':{'name':'Temperatura do chip CPU','unit':'ºC','max':80},'Wifi':{'name':'Temperatura do chip Wi-Fi','unit':'ºC','max':90}}
    for key, rule in temp_rules.items():
        if key in parsed_data:
            value_str=parsed_data[key];status_icon="❓"
            try:
                value_int=int(value_str)
                status_icon="🟢" if value_int <= rule['max'] else "🔴"
            except(ValueError,TypeError):pass
            display_lines.append(f"{status_icon} {rule['name'].ljust(25)}: {value_str} {rule['unit']}")
            
    display_lines.append("\n-----------------------------------------")
    return "\n".join(display_lines), parsed_data

def parse_ont_wan_status(raw_output: str) -> tuple[str, dict]:
    """
    Extrai campos específicos da configuração da WAN (PPPoE, DNS, etc.) e busca o fabricante
    do MAC da interface WAN.
    """
    logging.info("[parse_ont_wan_status] Executando em modo passo-a-passo.")
    
    parsed_data = {}
    
    # Função auxiliar para encontrar um valor usando regex, com um valor padrão.
    def find_value(pattern, text=raw_output, group=1, default="N/A"):
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            value = match.group(group).strip()
            # Remove o fuso horário da data/hora, se presente.
            return value.split('-03:00')[0].strip() if '-03:00' in value else value
        return default

    # Extração de cada campo usando a função auxiliar e regex específicas.
    parsed_data["IP do cliente"] = find_value(r"##### Ipv4 protocol stack information #####[\s\S]*?^\s*Address\s+([\d\.]+)")
    parsed_data["Estado da conexão PPPoE IPv4"] = find_value(r"##### Ipv4 protocol stack information #####[\s\S]*?^\s*Base information:[\s\S]*?^\s*State\s+(\w+)")
    parsed_data["Data/hora da última conexão estabelecida"] = find_value(r"##### Ipv4 protocol stack information #####[\s\S]*?^\s*Base information:[\s\S]*?^\s*Last up time\s+([\d\-\s:]+)")
    parsed_data["Data/hora da última queda de conexão"] = find_value(r"##### Ipv4 protocol stack information #####[\s\S]*?^\s*Base information:[\s\S]*?^\s*Last down time\s+([\d\-\s:]+)")
    parsed_data["Estado da conexão PPPoE IPv6"] = find_value(r"##### Ipv6 protocol stack information #####[\s\S]*?^\s*Base information:[\s\S]*?^\s*State\s+(\w+)")
    ipv6_address = find_value(r"##### Ipv6 protocol stack information #####[\s\S]*?^\s*Address\s+:(.*)")
    # Lógica para tratar o endereço IPv6 quando a conexão está inativa.
    if parsed_data["Estado da conexão PPPoE IPv6"] == "Down" or not ipv6_address or ipv6_address == "::":
        parsed_data["IP do cliente IPv6"] = "Não aplicado / Desativado"
    else:
        parsed_data["IP do cliente IPv6"] = ipv6_address
    parsed_data["Data/hora da última conexão estabelecida v6"] = find_value(r"##### Ipv6 protocol stack information #####[\s\S]*?^\s*Base information:[\s\S]*?^\s*Last up time\s+(--|[\d\-\s:]+)")
    parsed_data["Data/hora da última queda de conexão v6"] = find_value(r"##### Ipv6 protocol stack information #####[\s\S]*?^\s*Base information:[\s\S]*?^\s*Last down time\s+(--|[\d\-\s:]+)")
    
    # Extrai a seção de DNS para um parsing mais focado.
    dns_section_match = re.search(r"##### Ipv4 DNS protocol stack information #####([\s\S]*?)(?=#+|$)", raw_output)
    dns_section = dns_section_match.group(1) if dns_section_match else ""
    if dns_section:
        parsed_data["DNS primário Estático"] = find_value(r"Static DNS\s*\n\s*Primary DNS\s+([^\n]+)", dns_section)
        parsed_data["DNS secundário Estático"] = find_value(r"Static DNS\s*.*?\n\s*Secondary DNS\s+([^\n]+)", dns_section)
        parsed_data["DNS primário Dinamico"] = find_value(r"Dynamic DNS\s*\n\s*Primary DNS\s+([^\n]+)", dns_section)
        parsed_data["DNS secundário Dinamico"] = find_value(r"Dynamic DNS\s*.*?\n\s*Secondary DNS\s+([^\n]+)", dns_section)

    parsed_data["MTU da conexão PPP"] = find_value(r"##### PPP protocol stack information #####[\s\S]*?^\s*Mtu\s+(\d+)")
    parsed_data["MTU da camada Ethernet (física)"] = find_value(r"##### Ethlink protocol stack information #####[\s\S]*?^\s*Mtu\s+(\d+)")
    parsed_data["MAC da interface WAN"] = find_value(r"^\s*\d+\s+internet\s+([\w:]+)")
    wan_mac = parsed_data.get("MAC da interface WAN")
    # Usa a função find_mac_vendor para obter o fabricante do MAC da WAN.
    parsed_data["Fabricante do MAC da WAN"] = find_mac_vendor(wan_mac) or "Não encontrado"
    
    # Monta o relatório formatado.
    display_lines = ["=========================================", "🌐 INFORMAÇÕES DE CONEXÃO WAN / PPPoE", "=========================================\n"]
    fields_to_display = [
        "IP do cliente", "Estado da conexão PPPoE IPv4", "Estado da conexão PPPoE IPv6",
        "IP do cliente IPv6", "Data/hora da última conexão estabelecida", "Data/hora da última queda de conexão",
        "Data/hora da última conexão estabelecida v6", "Data/hora da última queda de conexão v6",
        "DNS primário Estático", "DNS secundário Estático", "DNS primário Dinamico", "DNS secundário Dinamico",
        "MTU da conexão PPP", "MTU da camada Ethernet (física)", "MAC da interface WAN", "Fabricante do MAC da WAN"
    ]
    key_width = 45 # Largura da coluna de chaves para alinhamento.
    for field in fields_to_display:
        value = parsed_data.get(field, "Não encontrado")
        # Só exibe o campo se ele tiver um valor útil.
        if value and value not in ["N/A", "--", "Não encontrado"]:
            display_lines.append(f"{field.ljust(key_width)}: {value}")
    
    return "\n".join(display_lines), parsed_data

def parse_lan_wifi_devices(
    dhcp_output: str, 
    wifi_output: str, 
    ping_results: dict[str, str]
) -> tuple[str, list[dict]]:
    """
    Analisa os outputs dos comandos de DHCP, Wi-Fi e Ping para criar um relatório
    consolidado dos dispositivos conectados na rede local (LAN e Wi-Fi).
    """
    devices = [] # Lista para armazenar os dicionários de cada dispositivo encontrado.
    
    # Expressão regular (regex) para extrair informações da tabela DHCP.
    # Captura: Índice, Tipo de Conexão, IP, Hostname, MAC e Tempo de Lease.
    dhcp_pattern = re.compile(
        r"^\s*(\d+)\s+"          # Grupo 1: Índice (número no início da linha)
        r"(\S+)\s+"              # Grupo 2: Tipo de conexão (e.g., LAN1, SSID1)
        r"([\d\.]+)\s+"          # Grupo 3: Endereço IP
        r"(\S+)\s+"              # Grupo 4: Nome do host (Hostname)
        r"([0-9a-fA-F:]+)\s+"    # Grupo 5: Endereço MAC
        r"(.+)$"                 # Grupo 6: Resto da linha (Tempo de Lease)
    , re.MULTILINE)

    # Itera sobre todas as correspondências encontradas pela regex na saída DHCP.
    for match in dhcp_pattern.finditer(dhcp_output):
        # Cria um dicionário para cada dispositivo com os dados extraídos.
        device = {
            "index": int(match.group(1)),
            "connection_type_raw": match.group(2),
            "ip": match.group(3),
            "hostname": match.group(4) if match.group(4) != '--' else "N/A",
            "mac": format_mac(match.group(5)), # Formata o MAC para o padrão.
            "lease_time": match.group(6).replace("0 days, ", "").strip(),
            # Inicializa campos que serão preenchidos depois com dados do Wi-Fi e Ping.
            "is_active_wifi": False, "wifi_ssid": "N/A", "tx_rate": "--", "rx_rate": "--", "wifi_mode": "--",
            "ping_replied": "❔ Não testado", "packets_tx": "--", "packets_rx": "--", "packet_loss": "--",
            "latency_min": "--", "latency_avg": "--", "latency_max": "--",
            # Busca o fabricante do dispositivo usando o MAC.
            "vendor": find_mac_vendor(match.group(5)) or "N/A"
        }
        devices.append(device)

    # Se a lista de dispositivos estiver vazia, a regex falhou. Gera um relatório de erro.
    if not devices:
        logging.warning("Nenhum dispositivo encontrado na saída DHCP. A regex pode não estar correspondendo.")
        report = "=========================================\n📊 RESUMO GERAL DOS DISPOSITIVOS NA REDE\n=========================================\n\n"
        report += "❌ Nenhum dispositivo encontrado na tabela DHCP.\n"
        report += "Verifique se a expressão regular (regex) em 'parse_lan_wifi_devices' corresponde à saída do equipamento.\n\n"
        report += "--- SAÍDA BRUTA DHCP ---\n" + dhcp_output
        return report, []

    # Processa a saída do comando Wi-Fi para correlacionar com os dispositivos DHCP.
    wifi_devices_data = {}
    wifi_pattern = re.compile(
        r"^([0-9a-fA-F:]+)\s+"  # Grupo 1: Endereço MAC
        r"(.+?)\s{2,}"         # Grupo 2: SSID (pode conter espaços)
        r"\d+\s+"              # Ignora a coluna de AuthTime
        r"(\S+)\s+"            # Grupo 3: Taxa de transmissão (TxRate)
        r"(\S+)\s+"            # Grupo 4: Taxa de recepção (RxRate)
        r"(\S+)"               # Grupo 5: Modo Wi-Fi (e.g., 11n, 11ac)
    , re.MULTILINE)

    for match in wifi_pattern.finditer(wifi_output):
        mac = format_mac(match.group(1))
        # Armazena os dados do Wi-Fi em um dicionário usando o MAC como chave para fácil acesso.
        wifi_devices_data[mac] = {
            "wifi_ssid": match.group(2).strip(),
            "tx_rate": match.group(3),
            "rx_rate": match.group(4),
            "wifi_mode": match.group(5)
        }
    
    # Atualiza a lista de dispositivos com as informações de Wi-Fi.
    for device in devices:
        if device["mac"] in wifi_devices_data:
            device.update(wifi_devices_data[device["mac"]])
            device["is_active_wifi"] = True

    # Processa os resultados do Ping para cada dispositivo.
    for ip, ping_output in ping_results.items():
        # Encontra o dispositivo correspondente pelo endereço IP.
        target_device = next((d for d in devices if d["ip"] == ip), None)
        if not target_device: continue # Pula se o IP não corresponder a nenhum dispositivo DHCP.

        # Extrai estatísticas do ping (pacotes enviados, recebidos, perda).
        loss_match = re.search(r"(\d+)\s+packets\s+transmitted,\s+(\d+)\s+packets\s+received,\s+(\d+)%\s+packet\s+loss", ping_output)
        if loss_match:
            target_device.update({
                "packets_tx": loss_match.group(1),
                "packets_rx": loss_match.group(2),
                "packet_loss": f"{loss_match.group(3)}%"
            })
            # Se algum pacote foi recebido, o ping teve sucesso.
            if int(loss_match.group(2)) > 0:
                target_device["ping_replied"] = "✅ Sim"
                # Extrai os tempos de latência (min/avg/max).
                timing_match = re.search(r"min/avg/max\s*=\s*([\d\.]+)/([\d\.]+)/([\d\.]+)", ping_output)
                if timing_match:
                    target_device.update({
                        "latency_min": float(timing_match.group(1)),
                        "latency_avg": float(timing_match.group(2)),
                        "latency_max": float(timing_match.group(3))
                    })
            else:
                target_device["ping_replied"] = "❌ Não"
        else:
            target_device["ping_replied"] = "❌ Falha no Teste"

    # --- Geração do Resumo e Relatório ---
    # Calcula estatísticas gerais.
    total_dhcp = len(devices)
    active_wifi_count = sum(1 for d in devices if d["is_active_wifi"])
    lan_count = sum(1 for d in devices if d["connection_type_raw"].upper().startswith("LAN"))
    inactive_wifi_count = total_dhcp - active_wifi_count - lan_count
    responded_ping_count = sum(1 for d in devices if d["ping_replied"] == "✅ Sim")
    
    # Conta quantos dispositivos estão em cada SSID/porta.
    ssid_counts = Counter(d["connection_type_raw"] for d in devices)
    
    # Calcula estatísticas de latência.
    latencies = [d["latency_avg"] for d in devices if isinstance(d["latency_avg"], float)]
    min_latency_avg = f"{min(latencies):.1f} ms" if latencies else "N/A"
    avg_latency_all = f"{sum(latencies) / len(latencies):.1f} ms" if latencies else "N/A"
    max_latency_avg = f"{max(latencies):.1f} ms" if latencies else "N/A"
    
    # Monta o cabeçalho do resumo.
    summary_lines = [
        "=========================================",
        "📊 RESUMO GERAL DOS DISPOSITIVOS NA REDE",
        "=========================================\n",
        f"🧾 Total de dispositivos com IP (DHCP): {total_dhcp}",
        f"📡 Dispositivos atualmente conectados via Wi-Fi: {active_wifi_count}",
        f"🔌 Dispositivos conectados por cabo (LAN): {lan_count}",
        f"❔ Dispositivos com IP mas Wi-Fi inativo: {inactive_wifi_count}\n",
        "📶 Distribuição por rede (SSID / Porta):"
    ]
    
    # Mapeia nomes técnicos de SSID (SSID1) para nomes reais (MinhaRede).
    ssid_friendly_names = {}
    for ssid_raw_name in ssid_counts.keys():
        friendly_name = next((data["wifi_ssid"] for mac, data in wifi_devices_data.items() if any(d["mac"] == mac and d["connection_type_raw"] == ssid_raw_name for d in devices)), ssid_raw_name)
        ssid_friendly_names[ssid_raw_name] = friendly_name

    # Adiciona a contagem por SSID ao resumo.
    for name, count in sorted(ssid_counts.items()):
        summary_lines.append(f"  - {ssid_friendly_names.get(name, name)}: {count} dispositivo(s)")
    
    # Adiciona as estatísticas de ping e latência ao resumo.
    summary_lines.extend([
        "\n📍 Resposta ao teste de conexão (Ping):",
        f"  ✅ Dispositivos que responderam: {responded_ping_count}",
        f"  ❌ Dispositivos sem resposta: {total_dhcp - responded_ping_count}\n",
        "📈 Latência (apenas dispositivos que responderam):",
        f"  - Menor tempo médio: {min_latency_avg}",
        f"  - Tempo médio geral: {avg_latency_all}",
        f"  - Maior tempo médio: {max_latency_avg}",
    ])

    # Cria "cards" individuais para cada dispositivo.
    device_cards = []
    for device in sorted(devices, key=lambda d: d["index"]):
        card = [f"\n\n--- #{device['index']} ---\n"]
        conn_type = f"Cabo ({device['connection_type_raw']})" if device['connection_type_raw'].upper().startswith('LAN') else f"Wi-Fi ({device['connection_type_raw']})"
        card.append(f"📶 Tipo de conexão       : {conn_type}")
        card.append(f"📛 Nome do host          : {device['hostname']}")
        card.append(f"💻 MAC address           : {device['mac']}")
        card.append(f"🏢 Fabricante (Vendor)   : {device['vendor']}")
        card.append(f"🌐 IP atribuído (DHCP)   : {device['ip']}")
        card.append(f"⏳ Tempo de concessão    : {device['lease_time'].replace('days,', 'dias,')}")
        
        ssid_display = device['wifi_ssid'] if device['is_active_wifi'] else ("(não se aplica)" if conn_type.startswith("Cabo") else "(desconectado no momento)")
        card.append(f"📡 SSID                  : {ssid_display}")
        card.append(f"🔄 Taxa Tx/Rx            : {device['tx_rate']} / {device['rx_rate']}")
        card.append(f"📟 Modo Wi-Fi            : {device['wifi_mode']}")
        
        card.append("\n📊 Diagnóstico de conectividade (ICMP)")
        card.append(f"✅ Responde a ping?      : {device['ping_replied']}")
        card.append(f"📤 Pacotes enviados      : {device['packets_tx']}")
        card.append(f"📥 Pacotes recebidos     : {device['packets_rx']}")
        card.append(f"❌ Perda de pacotes      : {device['packet_loss']}")
        
        lat_str = f"{device['latency_min']:.3f} / {device['latency_avg']:.3f} / {device['latency_max']:.3f}" if isinstance(device['latency_avg'], float) else "-- / -- / --"
        card.append(f"📈 Latência (ms)         : {lat_str}")
        
        device_cards.append("\n".join(card))
        
    # Junta o resumo e os cards individuais para formar o relatório final.
    full_report = "\n".join(summary_lines) + "".join(device_cards)
    
    return full_report, devices


def parse_wifi_neighbors(raw_output: str) -> tuple[str, list[dict]]:
    """
    Analisa a saída do comando 'display wifi neighbor' para criar um relatório
    detalhado sobre as redes Wi-Fi vizinhas, que podem causar interferência.
    """
    
    # --- FASE 1: Extração de dados brutos ---
    
    # Extrai os canais atualmente em uso pela ONT para as bandas de 2.4G e 5G.
    current_channels_match = re.search(r"CurrentWorkingChannel:(\d+)\(2\.4G\)\s*(\d+)\(5G\)", raw_output)
    channel_2g, channel_5g = ("N/A", "N/A")
    if current_channels_match:
        channel_2g = current_channels_match.group(1)
        channel_5g = current_channels_match.group(2)

    parsed_aps = [] # Lista para armazenar os dados de cada ponto de acesso (AP) vizinho.
    current_band = None # Variável para rastrear se estamos na seção 2.4G ou 5G.

    for line in raw_output.splitlines():
        # Identifica em qual banda estamos.
        if "2.4GHz" in line:
            current_band = "2.4G"
            continue
        if "5GHz" in line:
            current_band = "5G"
            continue

        # Ignora linhas de cabeçalho ou vazias.
        if line.strip().startswith("---") or "SSID" in line or not line.strip():
            continue
        
        # Lógica robusta para dividir a linha em colunas, mesmo com SSIDs vazios.
        parts = [p.strip() for p in re.split(r'\s{2,}', line.strip()) if p.strip()]
        
        # Se um SSID estiver faltando, a linha terá 10 partes. Inserimos um placeholder.
        if len(parts) == 10 and re.match(r'^([0-9A-F]{2}:){5}[0-9A-F]{2}$', parts[0]):
            parts.insert(1, "(SSID Oculto)")
        
        # Pula a linha se ela não tiver o número esperado de colunas (11).
        if len(parts) != 11 or not re.match(r'^([0-9A-F]{2}:){5}[0-9A-F]{2}$', parts[0]):
            continue

        try:
            mac_address = parts[0]
            
            # Pausa para evitar sobrecarregar a API de consulta de MAC (erro 429).
            time.sleep(1.5)
            
            vendor = find_mac_vendor(mac_address) or "Desconhecido"

            # Monta o dicionário com os dados do AP vizinho.
            ap_data = {
                "mac": mac_address, "ssid": parts[1], "channel": int(parts[2]),
                "bandwidth": parts[3], "mimo": parts[4], "rssi": int(parts[5]),
                "mode": parts[6], "security": parts[7], "wmm": parts[8],
                "noise": int(parts[9]), "max_bit_rate": int(parts[10]),
                "band": current_band, "vendor": vendor
            }
            parsed_aps.append(ap_data)
        except (IndexError, ValueError) as e:
            logging.warning(f"Falha ao analisar a linha do vizinho Wi-Fi: '{line}'. Erro: {e}")

    # --- FASE 2: Geração do Relatório Formatado ---
    report = [
        "=========================================",
        "📡 5. REDES WI-FI VIZINHAS DETECTADAS",
        "=========================================\n",
        "ℹ️  Estas redes foram detectadas nas proximidades da ONT. Parâmetros como canal, RSSI (intensidade de sinal), largura de banda e ruído podem impactar o desempenho do Wi-Fi da ONT atual.\n",
        f"📶 Canal atual em uso na ONT: 2.4 GHz → Canal {channel_2g} | 5 GHz → Canal {channel_5g}\n"
    ]

    # --- Tabela e Análise 2.4 GHz ---
    aps_2g = sorted([ap for ap in parsed_aps if ap["band"] == "2.4G"], key=lambda x: x["channel"])
    report.extend([
        "────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────",
        "📍 Redes Wi-Fi na faixa de 2.4 GHz (maior risco de interferência)",
        "────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────",
        f"{'MAC':<18} | {'Vendedor':<15} | {'SSID':<25} | {'Canal':>5} | {'Largura':>7} | {'RSSI':>7} | {'Ruído':>7} | {'Segurança':<25} | {'MIMO':>5} | {'WMM':>3} | {'MaxBitRate':>10}",
        "-"*140
    ])
    
    canais_2g_ocupados = set()
    sinais_fortes_2g = []
    for ap in aps_2g:
        canais_2g_ocupados.add(ap['channel'])
        if ap['rssi'] >= -70: # Sinal forte, maior potencial de interferência.
            sinais_fortes_2g.append(f"“{ap['ssid']}” (Canal {ap['channel']}, {ap['rssi']} dBm)")

        report.append(
            f"{ap['mac']:<18} | {ap['vendor']:<15.15} | {ap['ssid']:<25.25} | {ap['channel']:>5} | {ap['bandwidth']:>7} | {str(ap['rssi'])+' dBm':>7} | {str(ap['noise'])+' dBm':>7} | {ap['security']:<25.25} | {ap['mimo']:>5} | {ap['wmm']:>3} | {str(ap['max_bit_rate'])+' Mbps':>10}"
        )

    if aps_2g:
        report.append("\n🔍 *Observações 2.4 GHz*:")
        if canais_2g_ocupados:
            report.append(f"- Canais ocupados: {', '.join(map(str, sorted(list(canais_2g_ocupados))))}. Para o canal {channel_2g} da ONT, a sobreposição é maior com redes nos canais próximos.")
        if sinais_fortes_2g:
            report.append(f"- Sinais fortes (≥ -70 dBm) detectados: {', '.join(sinais_fortes_2g)}. Estes são os que têm maior potencial de causar interferência.")
    
    # --- Tabela e Análise 5 GHz ---
    aps_5g = sorted([ap for ap in parsed_aps if ap["band"] == "5G"], key=lambda x: x["channel"])
    report.extend([
        "\n\n────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────",
        "📍 Redes Wi-Fi na faixa de 5 GHz (interferência geralmente menor)",
        "────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────",
        f"{'MAC':<18} | {'Vendedor':<15} | {'SSID':<25} | {'Canal':>5} | {'Largura':>7} | {'RSSI':>7} | {'Ruído':>7} | {'Segurança':<25} | {'MIMO':>5} | {'WMM':>3} | {'MaxBitRate':>10}",
        "-"*140
    ])

    canais_5g_conflito = []
    for ap in aps_5g:
        if str(ap['channel']) == channel_5g: # Verifica se o vizinho está no mesmo canal da ONT.
            canais_5g_conflito.append(f"“{ap['ssid']}” ({ap['rssi']} dBm)")
            
        report.append(
            f"{ap['mac']:<18} | {ap['vendor']:<15.15} | {ap['ssid']:<25.25} | {ap['channel']:>5} | {ap['bandwidth']:>7} | {str(ap['rssi'])+' dBm':>7} | {str(ap['noise'])+' dBm':>7} | {ap['security']:<25.25} | {ap['mimo']:>5} | {ap['wmm']:>3} | {str(ap['max_bit_rate'])+' Mbps':>10}"
        )

    if aps_5g:
        report.append("\n🔍 *Observações 5 GHz*:")
        if canais_5g_conflito:
            report.append(f"- A(s) rede(s) {', '.join(canais_5g_conflito)} está(ão) no mesmo canal {channel_5g} da ONT, podendo competir pelo espectro.")
        else:
            report.append("- Nenhuma rede detectada no mesmo canal da ONT. O risco de interferência direta é baixo.")

    report.extend([
        "\n\n📌 Dica: Para reduzir interferências, considere alterar o canal da ONT para um menos congestionado.",
        "Na faixa de 2.4 GHz, os canais 1, 6 e 11 são ideais pois não se sobrepõem."
    ])

    # Retorna o relatório formatado e um dicionário com os dados brutos.
    return "\n".join(report), {"wifi_neighbors": parsed_aps}


def parse_wifi_config(raw_output: str) -> tuple[str, list[dict]]:
    """
    Analisa a saída dos comandos 'display wifi information' e 'display wifi radio'
    para criar um relatório consolidado sobre a configuração do Wi-Fi da ONT.
    """
    
    # --- FASE 1: Separar a saída dos dois comandos ---
    info_output, radio_output = raw_output, ""
    if "display wifi radio" in raw_output:
        parts = raw_output.split("display wifi radio", 1)
        info_output = parts[0]
        radio_output = parts[1]

    # --- FASE 2: Parsing do 'display wifi information' (informações por SSID) ---
    ssids_data = []
    # Divide a saída em blocos, um para cada SSID, usando o separador '---'.
    ssid_blocks = info_output.split('----------------------------------------------------')
    for block in ssid_blocks:
        if "SSID Index" not in block:
            continue
        
        ssid_info = {}
        for line in block.splitlines():
            if ':' in line:
                key, value = map(str.strip, line.split(':', 1))
                ssid_info[key] = value
        
        if ssid_info:
            ssids_data.append(ssid_info)

    # --- FASE 3: Parsing do 'display wifi radio' (configurações globais por banda) ---
    radio_data = {}
    if radio_output:
        lines = radio_output.strip().splitlines()
        for i in range(2, len(lines)): # Pula as duas primeiras linhas de cabeçalho.
            line = lines[i]
            # Regex para capturar o parâmetro e seus valores para 2.4G e 5G.
            match = re.match(r'^([\w\s]+):\s+(\S+.*?)\s{2,}(\S+.*?)\s*$', line)
            if match:
                key = match.group(1).strip()
                val_2g = match.group(2).strip()
                val_5g = match.group(3).strip()
                radio_data[key] = {'2.4G': val_2g, '5G': val_5g}

    # --- FASE 4: Geração do Relatório Formatado ---
    
    # Parte 1: Cards de SSID
    report_cards = [
        "=========================================",
        "📡 ESTADO ATUAL DAS REDES WI-FI DA ONT",
        "========================================="
    ]
    
    # Mapeamento de nomes técnicos de padrão Wi-Fi para nomes amigáveis.
    friendly_standard = {'11bgn': '802.11b/g/n', '11ac': '802.11ac', '11ax': '802.11ax (Wi-Fi 6)'}

    for i, ssid in enumerate(ssids_data):
        # Determina a banda baseado no nome do SSID ou no seu índice.
        band = "5 GHz" if "_5G" in ssid.get("SSID", "") or int(ssid.get("SSID Index", 0)) > 4 else "2.4 GHz"
        
        report_cards.append(f"\n\n# {i+1}")
        report_cards.append(f"📶 Rede {band} (SSID{ssid.get('SSID Index')})")
        report_cards.append(f"🆔 Nome da rede (SSID): {ssid.get('SSID', 'N/A')}")
        report_cards.append(f"🛰️ BSSID (MAC da antena): {ssid.get('BSSID', 'N/A')}")
        report_cards.append(f"📡 Status: {'Ativa' if ssid.get('Status') == 'Up' else 'Inativa'}")
        report_cards.append(f"📻 Canal: {ssid.get('Channel', 'N/A')}")
        report_cards.append(f"📏 Largura do canal: {ssid.get('Channel bandwidth', 'N/A').replace('Auto ', 'Auto (') + ')' if 'Auto' in ssid.get('Channel bandwidth', '') else ssid.get('Channel bandwidth', 'N/A')}")
        report_cards.append(f"📟 Padrão Wi-Fi: {friendly_standard.get(ssid.get('Standard'), ssid.get('Standard', 'N/A'))}")
        report_cards.append(f"🚀 Velocidade máxima suportada: {ssid.get('Supported Max Rate', 'N/A').replace(' M', ' Mbps')}")
        report_cards.append(f"📡 Potência máxima permitida: {ssid.get('Maximum Tx-Power', 'N/A')}")
        report_cards.append(f"⚙️ Potência atual usada: {ssid.get('Current Tx-Power Level', 'N/A')}")
        report_cards.append(f"🔐 Segurança: {ssid.get('Authentication Mode', 'N/A')}")
        report_cards.append(f"🔒 Criptografia: {ssid.get('Encryption Mode', 'N/A').replace('and', ' + ')}")

    # Parte 2: Tabela de Configurações de Rádio
    report_table = ["\n\n=========================================================================="]
    
    header = f"| {'🔧 Parâmetro':<30} | {'2.4 GHz':<16} | {'5 GHz':<19} |"
    separator = f"| {'-'*30} | {'-'*16} | {'-'*19} |"
    report_table.extend([header, separator])

    # Mapeia nomes técnicos de parâmetros para nomes amigáveis.
    param_map = {
        'Enable': 'Habilitado', 'Channel': 'Canal atual', 'BandWidth': 'Largura do canal',
        'Number of spatial streams': 'Fluxos espaciais (MIMO)', 'MCS': 'Modulação (MCS)',
        'Guard Interval': 'Intervalo de guarda (GI)', 'Beacon Interval': 'Intervalo do Beacon',
        'DTIM period': 'DTIM', 'Tx Beamforming': 'Beamforming (direcionamento)',
        'Off Channel CAC': 'Verificação de canal (CAC)', 'Protected Management Frames': 'Gerenciamento protegido (PMF)',
        'Smart channel selection': 'Seleção inteligente de canal'
    }
    # Mapeia valores técnicos para nomes amigáveis.
    value_map = {
        '1': 'Sim', '0': 'Não', 'Enable': 'Ativado', 'Disable': 'Desativado',
        'auto': 'Automática', 'short': 'Curto', 'long': 'Longo'
    }

    # Formatações específicas para alguns valores.
    if 'Beacon Interval' in radio_data and radio_data['Beacon Interval']['2.4G'].isdigit():
        radio_data['Beacon Interval']['2.4G'] += ' ms'
        radio_data['Beacon Interval']['5G'] += ' ms'

    if 'BandWidth' in radio_data:
        radio_data['BandWidth']['2.4G'] = radio_data['BandWidth']['2.4G'].replace('Auto ', '') + ' (auto)'
        radio_data['BandWidth']['5G'] = radio_data['BandWidth']['5G'].replace('Auto ', '') + ' (auto)'

    # Monta a tabela de rádio linha por linha.
    for key, friendly_name in param_map.items():
        if key in radio_data:
            val_2g = radio_data[key]['2.4G']
            val_5g = radio_data[key]['5G']
            
            # Traduz os valores usando o value_map.
            f_val_2g = value_map.get(val_2g, val_2g)
            f_val_5g = value_map.get(val_5g, val_5g)

            report_table.append(f"| {friendly_name:<30} | {f_val_2g:<16} | {f_val_5g:<19} |")
    
    report_table.append("==========================================================================")
    
    # Junta os cards e a tabela para o relatório final.
    full_report = "\n".join(report_cards) + "\n" + "\n".join(report_table)
    
    # Estrutura os dados para serem salvos no banco de dados.
    parsed_data = {"ssids": ssids_data, "radio_settings": radio_data}
    
    return full_report, parsed_data

def parse_connectivity_tests(raw_output: str) -> tuple[str, dict]:
    """
    Analisa a saída bruta de vários testes de conectividade (ping, nslookup, traceroute)
    e formata em um relatório consolidado.
    """
    # Dicionário para armazenar os dados estruturados de cada tipo de teste.
    parsed_data = {"ping": [], "dns": [], "traceroute": []}
    report_lines = [
        "=========================================",
        "🔬 9. TESTES DE CONECTIVIDADE DA ONT",
        "=========================================\n"
    ]

    # Divide a saída completa em blocos, um para cada comando executado, usando um separador comum.
    command_blocks = re.split(r"--- Start of cmd: .*? ---\n", raw_output)

    # --- Análise de cada bloco de comando ---
    for block in command_blocks:
        if not block.strip():
            continue

        # Análise do Bloco de Ping
        if "ping statistics" in block:
            # Encontra o destino do ping no cabeçalho do bloco.
            destination_match = re.search(r"--- (.*?) ping statistics ---", block)
            if not destination_match: continue
            
            destination = destination_match.group(1).strip()
            stats = {'destination': destination}
            
            # Usa regex para extrair cada estatística do ping.
            transmitted = re.search(r"(\d+)\s+packets\s+transmitted", block)
            received = re.search(r"(\d+)\s+packets\s+received", block)
            loss = re.search(r"(\d+%)\s+packet\s+loss", block)
            rtt = re.search(r"min/avg/max\s*=\s*([\d\.]+)/([\d\.]+)/([\d\.]+)", block)
            
            if transmitted and received and loss:
                stats['transmitted'] = transmitted.group(1)
                stats['received'] = received.group(1)
                stats['loss'] = loss.group(1)
                parsed_data["ping"].append(stats)
            if rtt:
                stats['min_rtt'] = rtt.group(1)
                stats['avg_rtt'] = rtt.group(2)
                stats['max_rtt'] = rtt.group(3)

        # Análise do Bloco de NSLookup (Teste de DNS)
        elif "nslookup domain" in raw_output and "Status" in block:
            dns_result = {}
            # Tenta encontrar as informações de DNS usando padrões comuns.
            dns_result['server'] = (re.search(r"Server\s*:\s*(.*)", block) or re.search(r"server\s+(\S+)", raw_output)).group(1).strip()
            dns_result['name'] = (re.search(r"Name\s*:\s*(.*)", block) or re.search(r"domain\s+(\S+)", raw_output)).group(1).strip()
            dns_result['status'] = (re.search(r"Status\s*:\s*(.*)", block)).group(1).strip()
            address_match = re.search(r"Address\s*:\s*(.*)", block)
            dns_result['address'] = address_match.group(1).strip() if address_match and address_match.group(1).strip() else "---"
            parsed_data["dns"].append(dns_result)

        # Análise do Bloco de Traceroute
        elif "traceroute to" in block:
            destination_line = block.splitlines()[0]
            # Encontra todas as linhas que representam um salto na rota.
            hops = re.findall(r"^\s*(\d+)\s+(.*)", block, re.MULTILINE)
            parsed_data["traceroute"].append({"destination": destination_line.strip(), "hops": [f"{h[0]}. {h[1].strip()}" for h in hops]})

    # --- Montagem do Relatório Final ---
    report_lines.append("🎯 **Teste de Ping (ICMP)**\n")
    if parsed_data["ping"]:
        for result in parsed_data["ping"]:
            status_icon = "✅" if int(result.get('received', 0)) > 0 else "❌"
            report_lines.append(f"{status_icon} **Ping para `{result['destination']}`**")
            report_lines.append(f"  - Pacotes: {result.get('transmitted', 'N/A')} enviados, {result.get('received', 'N/A')} recebidos ({result.get('loss', 'N/A')} de perda).")
            if 'avg_rtt' in result:
                report_lines.append(f"  - Latência (min/média/máx): {result['min_rtt']} ms / {result['avg_rtt']} ms / {result['max_rtt']} ms.")
            report_lines.append("")
    else:
        report_lines.append("  - Nenhum resultado de ping bem-sucedido encontrado.\n")

    report_lines.append("\n" + "🌐 **Teste de Resolução de Nomes (DNS)**\n")
    if parsed_data["dns"]:
        dns_table = ["| Servidor DNS      | Domínio           | Status                      | IP Resolvido  |", "|:------------------|:------------------|:----------------------------|:--------------|"]
        for result in parsed_data["dns"]:
            status_text = result['status'].replace("Error_HostNameNotResolved", "❌ Falha na Resolução")
            if "No Error" in status_text: status_text = "✅ Sucesso"
            dns_table.append(f"| {result['server']:<17} | {result['name']:<17} | {status_text:<27} | {result['address']:<13} |")
        report_lines.extend(dns_table)
    else:
        report_lines.append("  - Nenhum resultado de nslookup encontrado.\n")

    report_lines.append("\n\n" + "🗺️ **Teste de Rota (Traceroute)**\n")
    if parsed_data["traceroute"]:
        for trace in parsed_data["traceroute"]:
            report_lines.append(f"Rota para: `{trace['destination']}`\n")
            report_lines.extend(trace['hops'])
    else:
        report_lines.append("  - Nenhum resultado de traceroute encontrado.")

    return "\n".join(report_lines), parsed_data


def parse_voip_status(raw_output: str) -> tuple[str, dict]:
    """
    Analisa a saída de múltiplos comandos VoIP para criar um relatório consolidado.
    """
    # --- FASE 1: Inicialização e Divisão do Output ---
    
    # Dicionário para guardar os dados estruturados do VoIP.
    parsed_data = {
        "port_status": "N/A", "user_status": "N/A", "call_status": "N/A",
        "user_name": "N/A", "register_error": None, "register_proxy": "N/A",
        "signaling_ip": "N/A", "media_ip": "N/A", "dtmf_method": "N/A",
        "fax_mode": "N/A", "registration_period": 0, "primary_proxy_state": "N/A",
        "secondary_proxy_state": "N/A",
        "rtp_stats": {}, "services": {},
        "ringing_voltage": "N/A", "ringing_frequency": "N/A"
    }

    # Divide a saída bruta em blocos, um para cada comando.
    command_blocks = re.split(r"Start run collect command:", raw_output)

    # --- FASE 2: Parsing de cada bloco de comando ---
    for block in command_blocks:
        if not block.strip(): continue

        # Bloco principal de informações da conta SIP ('display mg info').
        if "WAP:vspa display mg info" in block:
            for line in block.splitlines():
                if ':' in line:
                    key, value = map(str.strip, line.split(':', 1))
                    if key == "Port Status": parsed_data["port_status"] = value
                    elif key == "User Status": parsed_data["user_status"] = value
                    elif key == "Call Status": parsed_data["call_status"] = value
                    elif key == "User Name": parsed_data["user_name"] = value
                    elif key == "Register Error Info" and value != "-": parsed_data["register_error"] = value
                    elif key == "Current Register Proxy": parsed_data["register_proxy"] = value
                    elif key == "Signaling IP": parsed_data["signaling_ip"] = value
                    elif key == "Media IP": parsed_data["media_ip"] = value
                    elif key == "DtmfMethod": parsed_data["dtmf_method"] = value
                    elif key == "Fax Mode": parsed_data["fax_mode"] = value
                    elif key == "RegistrationPeriod": parsed_data["registration_period"] = int(value) if value.isdigit() else 0
        
        # Bloco de estado da interface/proxy ('display mg if state').
        elif "WAP:vspa display mg if state" in block:
            primary_state = re.search(r"PrimaryProxyState\s*:\s*(\d+)", block)
            secondary_state = re.search(r"SecondaryProxyState\s*:\s*(\d+)", block)
            if primary_state: parsed_data["primary_proxy_state"] = int(primary_state.group(1))
            if secondary_state: parsed_data["secondary_proxy_state"] = int(secondary_state.group(1))

        # Bloco de estatísticas RTP (qualidade da chamada).
        elif "WAP:vspa display rtp statistics" in block:
            # A lógica aqui é um placeholder, pois a tabela só tem dados durante uma chamada.
            if "No." not in block:
                parsed_data["rtp_stats"]["tx_packets"] = 0
                parsed_data["rtp_stats"]["rx_packets"] = 0
        
        # Bloco de serviços habilitados ('display voip rightflag').
        elif "WAP:display voip rightflag port 0" in block:
            services = ["CallWaiting", "CallTransfer", "ThreeParty", "AnonymousCall", "MWI"]
            for serv in services:
                match = re.search(rf"{serv}\s+(\w+)", block)
                if match:
                    key_map = serv.lower().replace('callwaiting','call_waiting').replace('calltransfer','call_transfer')
                    parsed_data["services"][key_map] = match.group(1)

        # Bloco de informações de toque ('display voip ring info').
        elif "WAP:display voip ring info port 0" in block:
            voltage = re.search(r"Ringing Voltage\s*:\s*(.*)", block)
            frequency = re.search(r"Ringing Frequency\s*:\s*(.*)", block)
            if voltage: parsed_data["ringing_voltage"] = voltage.group(1).strip()
            if frequency: parsed_data["ringing_frequency"] = frequency.group(1).strip() + "Hz"

    # --- FASE 3: Montagem do Relatório Formatado ---
    
    # Mapeamentos para traduzir valores técnicos em texto amigável.
    state_map = { 2: "✅ Registrado", 1: "⏳ Registrando...", 0: "❌ Desconectado", 3: "❔ Inativo/Não Config." }
    status_map = { "Up": "✅ Ativo", "Down": "🔴 Inativo", "RegisterFail": "❌ Falha no Registro" }

    report_lines = [
        "=========================================",
        "☎️ 7. DIAGNÓSTICO DE TELEFONIA (VoIP)",
        "=========================================\n"
    ]

    # Seção 1: Status Principal
    report_lines.append("🔹 **Status do Registro SIP**")
    report_lines.append(f"  - Status do Usuário: {status_map.get(parsed_data['user_status'], parsed_data['user_status'])}")
    report_lines.append(f"  - Status da Chamada: {parsed_data['call_status']}")
    report_lines.append(f"  - Número (Usuário SIP): {parsed_data['user_name']}")
    report_lines.append(f"  - Proxy Primário: {state_map.get(parsed_data['primary_proxy_state'], 'Desconhecido')}")
    report_lines.append(f"  - Proxy Secundário: {state_map.get(parsed_data['secondary_proxy_state'], 'Desconhecido')}")
    if parsed_data.get("register_error"):
        report_lines.append(f"  - ⚠️ Último Erro: {parsed_data['register_error']}")
    report_lines.append("")

    # Seção 2: Serviços Habilitados
    report_lines.append("🔹 **Serviços Telefônicos**")
    service_map = { "call_waiting": "Chamada em Espera", "call_transfer": "Transferência", "threeparty": "Conferência a Três", "anonymouscall": "Chamada Anônima", "mwi": "Indicador de Msg de Voz" }
    for key, name in service_map.items():
        status = parsed_data["services"].get(key, "desconhecido").lower()
        icon = "✅" if status == "enable" else "❌"
        report_lines.append(f"  - {icon} {name}: {status.capitalize()}")
    report_lines.append("")

    # Seção 3: Detalhes Técnicos
    report_lines.append("🔹 **Detalhes Técnicos**")
    report_lines.append(f"  - IP de Sinalização: {parsed_data['signaling_ip']}")
    report_lines.append(f"  - Método DTMF: {parsed_data['dtmf_method']}")
    report_lines.append(f"  - Modo de FAX: {parsed_data['fax_mode']}")
    report_lines.append(f"  - Tensão de Toque: {parsed_data['ringing_voltage']}")
    report_lines.append(f"  - Frequência de Toque: {parsed_data['ringing_frequency']}")

    return "\n".join(report_lines), parsed_data


def parse_ip_routes(raw_output: str) -> tuple[str, dict]:
    """
    Analisa a saída dos comandos 'display ip route' e 'display ip neigh'
    para criar um relatório sobre as tabelas de roteamento e vizinhança (ARP).
    """
    
    # --- FASE 1: Separar os blocos de cada comando ---
    route_output, neigh_output = raw_output, ""
    if "display ip neigh" in raw_output:
        parts = raw_output.split("display ip neigh", 1)
        route_output = parts[0]
        neigh_output = parts[1]

    parsed_data = {"routes": [], "neighbors": []}
    report_lines = [
        "=========================================",
        "🗺️  8. ROTAS E VIZINHOS IP (ARP/NDP)",
        "=========================================\n"
    ]

    # --- FASE 2: Parsing da Tabela de Rotas (display ip route) ---
    report_lines.append("🔹 **Tabela de Roteamento IP**")
    report_lines.append("   *Mostra como a ONT decide para onde enviar o tráfego de rede.*\n")
    
    route_lines = route_output.splitlines()
    for line in route_lines:
        line = line.strip()
        # Uma linha de rota válida geralmente começa com um dígito (endereço IP).
        if line and line[0].isdigit():
            parts = [p.strip() for p in re.split(r'\s{2,}', line)]
            if len(parts) >= 6:
                route_info = {
                    'destination': parts[0], 'interface': parts[1], 'gateway': parts[2],
                    'source_ip': parts[3], 'flags': parts[4], 'metric': parts[5], 
                    'origin': parts[6] if len(parts) > 6 else 'N/A'
                }
                parsed_data["routes"].append(route_info)

    # Monta a tabela formatada de rotas.
    if parsed_data["routes"]:
        report_lines.append(f"| {'Destino':<18} | {'Interface':<12} | {'Gateway':<15} | {'IP de Origem':<15} | {'Métrica':<7} | {'Origem':<12} |")
        report_lines.append(f"|:{'-'*17}-|:{'-'*11}-|:{'-'*14}-|:{'-'*14}-|:{'-'*6}:|:{'-'*11}-|")
        for route in parsed_data["routes"]:
            icon = "🌍" if route['destination'] == '0.0.0.0/0' else "🏠" if '192.168.' in route['destination'] else "➡️"
            report_lines.append(f"| {icon} {route['destination']:<15} | {route['interface']:<12} | {route['gateway']:<15} | {route['source_ip']:<15} | {route['metric']:^7} | {route['origin']:<12} |")
        report_lines.append(f"\nTotal de rotas: {len(parsed_data['routes'])}")
    else:
        report_lines.append("  - Nenhuma rota encontrada.")

    # --- FASE 3: Parsing da Tabela de Vizinhos (display ip neigh / ARP) ---
    report_lines.append("\n\n" + "🔹 **Tabela de Vizinhos IP (ARP/NDP)**")
    report_lines.append("   *Mapeia endereços IP para endereços físicos (MAC) na rede local.*\n")
    
    neigh_lines = neigh_output.splitlines()
    for line in neigh_lines:
        line = line.strip()
        # Uma linha de vizinho válida geralmente começa com o nome de uma interface.
        if line and (line.startswith("LAN") or line.startswith("SSID") or line.startswith("PON")):
            parts = [p.strip() for p in re.split(r'\s{2,}', line)]
            if len(parts) == 5:
                mac = format_mac(parts[3])
                time.sleep(1.5)  # Pausa para não sobrecarregar a API de MAC.
                vendor = find_mac_vendor(mac) or "Desconhecido"
                
                neigh_info = {
                    'interface': parts[0], 'state': parts[1], 'timeout': parts[2],
                    'hw_addr': mac, 'neighbour_ip': parts[4], 'vendor': vendor
                }
                parsed_data["neighbors"].append(neigh_info)

    # Monta a tabela formatada de vizinhos.
    if parsed_data["neighbors"]:
        report_lines.append(f"| {'Interface':<10} | {'Estado':<10} | {'MAC Address':<18} | {'Fabricante':<25} | {'Endereço IP do Vizinho':<40} |")
        report_lines.append(f"|:{'-'*9}-|:{'-'*9}-|:{'-'*17}-|:{'-'*24}-|:{'-'*39}-|")
        for neigh in parsed_data["neighbors"]:
            icon = "🔌" if 'LAN' in neigh['interface'] else "📡" if 'SSID' in neigh['interface'] else "🌐"
            report_lines.append(f"| {icon} {neigh['interface']:<7} | {neigh['state']:<10} | {neigh['hw_addr']:<18} | {neigh['vendor']:<25.25} | {neigh['neighbour_ip']:<40} |")
        report_lines.append(f"\nTotal de vizinhos: {len(parsed_data['neighbors'])}")
    else:
        report_lines.append("  - Nenhum vizinho encontrado.")

    return "\n".join(report_lines), parsed_data
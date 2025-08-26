# olt_monitoring_system/olt/connection_manager.py
import threading
import queue
import logging
import time
from .communication import connect_to_olt

class SSHConnectionManager:
    def __init__(self, olt_ip, username, password, max_connections=4):
        self.olt_ip = olt_ip
        self.username = username
        self.password = password
        self.max_connections = max_connections
        self.connections = queue.Queue(maxsize=max_connections)
        self.lock = threading.Lock()
        self.connection_attempts = 0
        self.last_connection_time = 0
        self.initialization_complete = False
        self.active_connections = 0  # Contador de conexões ativas
        self._initialize_connections()

    def _initialize_connections(self):
        """Inicializa o pool de conexões SSH."""
        logging.info(f"[{self.olt_ip}] Iniciando inicialização de {self.max_connections} conexões...")
        
        for i in range(self.max_connections):
            try:
                # Aumentar significativamente o atraso entre as conexões
                if i > 0:
                    delay = i * 15  # 15s, 30s, 45s...
                    logging.info(f"[{self.olt_ip}] Aguardando {delay}s antes da próxima conexão...")
                    time.sleep(delay)
                
                logging.info(f"[{self.olt_ip}] Tentando estabelecer conexão {i+1}/{self.max_connections}...")
                client, shell = connect_to_olt(self.olt_ip, self.username, self.password, max_retries=1)
                self.connections.put((client, shell))
                self.active_connections += 1  # Incrementa o contador de conexões ativas
                logging.info(f"[{self.olt_ip}] Conexão {i+1}/{self.max_connections} estabelecida. Conexões ativas: {self.active_connections}")
                
                # Resetar contador após uma conexão bem-sucedida
                self.connection_attempts = 0
                self.last_connection_time = time.time()
            except Exception as e:
                logging.error(f"[{self.olt_ip}] Falha ao criar conexão {i+1}: {e}")
                self.connections.put((None, None))
                
                # Incrementar contador de tentativas
                self.connection_attempts += 1
                
                # Se falhar muitas vezes, esperar muito tempo antes da próxima tentativa
                if self.connection_attempts >= 3:
                    wait_time = 60  # Esperar 1 minuto
                    logging.info(f"[{self.olt_ip}] Múltiplas falhas de conexão. Aguardando {wait_time}s antes de tentar novamente...")
                    time.sleep(wait_time)
                    self.connection_attempts = 0
        
        self.initialization_complete = True
        logging.info(f"[{self.olt_ip}] Inicialização de conexões concluída. Conexões ativas: {self.active_connections}")

    def get_connection(self):
        """Obtém uma conexão do pool. Bloqueia até que uma esteja disponível."""
        if not self.initialization_complete:
            logging.warning(f"[{self.olt_ip}] Tentando obter conexão antes da inicialização estar completa.")
            return None, None
            
        client, shell = self.connections.get()
        
        # Se a conexão for None, não tentar reconectar automaticamente
        if client is None:
            logging.warning(f"[{self.olt_ip}] Conexão inválida obtida do pool. Verificando se podemos reconectar...")
            
            # Verificar se já temos o máximo de conexões ativas
            with self.lock:
                if self.active_connections >= self.max_connections:
                    logging.warning(f"[{self.olt_ip}] Já temos {self.active_connections} conexões ativas (máximo: {self.max_connections}). Não tentando reconectar.")
                    self.connections.put((None, None))
                    return None, None
                
                # Se não atingimos o limite, tentar reconectar
                try:
                    current_time = time.time()
                    if current_time - self.last_connection_time < 30:  # Pelo menos 30s entre tentativas
                        wait_time = 30 - (current_time - self.last_connection_time)
                        logging.info(f"[{self.olt_ip}] Aguardando {wait_time:.1f}s antes de tentar reconectar...")
                        time.sleep(wait_time)
                    
                    logging.info(f"[{self.olt_ip}] Tentando estabelecer nova conexão...")
                    client, shell = connect_to_olt(self.olt_ip, self.username, self.password, max_retries=1)
                    self.last_connection_time = time.time()
                    self.connection_attempts = 0
                    self.active_connections += 1
                    logging.info(f"[{self.olt_ip}] Nova conexão estabelecida. Conexões ativas: {self.active_connections}")
                    return client, shell
                except Exception as e:
                    logging.error(f"[{self.olt_ip}] Falha ao reconectar: {e}")
                    self.connection_attempts += 1
                    self.connections.put((None, None))
                    return None, None
            
        return client, shell

    def release_connection(self, client, shell):
        """Libera uma conexão de volta para o pool."""
        if client is not None and shell is not None:
            try:
                # Verificar se a conexão ainda está ativa
                shell.send("\n")
                time.sleep(0.5)
                if shell.recv_ready():
                    shell.recv(1024)
                self.connections.put((client, shell))
                logging.debug(f"[{self.olt_ip}] Conexão liberada de volta para o pool. Conexões ativas: {self.active_connections}")
            except Exception as e:
                logging.warning(f"[{self.olt_ip}] Conexão inválida, fechando: {e}")
                try:
                    client.close()
                except:
                    pass
                with self.lock:
                    self.active_connections -= 1  # Decrementa o contador de conexões ativas
                    logging.info(f"[{self.olt_ip}] Conexão fechada. Conexões ativas: {self.active_connections}")
                self.connections.put((None, None))
        else:
            # Se a conexão for None, colocar um par None, None na fila
            self.connections.put((None, None))

    def close_all(self):
        """Fecha todas as conexões do pool."""
        logging.info(f"[{self.olt_ip}] Fechando todas as conexões. Conexões ativas antes: {self.active_connections}")
        while not self.connections.empty():
            client, shell = self.connections.get()
            if client:
                try:
                    client.close()
                    with self.lock:
                        self.active_connections -= 1
                except:
                    pass
        logging.info(f"[{self.olt_ip}] Todas as conexões fechadas. Conexões ativas depois: {self.active_connections}")
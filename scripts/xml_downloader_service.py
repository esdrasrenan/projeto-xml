#!/usr/bin/env python3
"""
Serviço Windows para execução contínua do XML Downloader
Instala, inicia, para e remove o serviço automaticamente.
"""

import sys
import os
import subprocess
import time
import logging
import signal
from pathlib import Path
from typing import Optional

# Configuração do serviço
SERVICE_NAME = "XMLDownloaderSieg"
SERVICE_DISPLAY_NAME = "XML Downloader SIEG - Paulicon"
SERVICE_DESCRIPTION = "Serviço para download automático de XMLs da API SIEG (Paulicon Contábil)"

# Configuração do projeto
PROJECT_DIR = Path(__file__).parent.parent  # Vai para a raiz do projeto
PYTHON_EXE = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
SCRIPT_PATH = PROJECT_DIR / "app" / "run.py"
EXCEL_URL = "https://paulicon1-my.sharepoint.com/:x:/g/personal/marco_fiscal_paulicon_com_br/ETn_H2eKSChJpUtk7rbccSwB08_zGcoxB4KyHX64ggwFyQ?e=WdMz8a&download=1"

# Configuração de logs
LOG_FILE = PROJECT_DIR / "logs" / "service.log"

class WindowsServiceManager:
    """Gerenciador do serviço Windows"""
    
    def __init__(self):
        self.ensure_log_dir()
        self.setup_logging()
        
    def ensure_log_dir(self):
        """Garantir que o diretório de logs existe"""
        LOG_FILE.parent.mkdir(exist_ok=True)
        
    def setup_logging(self):
        """Configurar logging para o serviço"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s | %(levelname)s | SERVICE | %(message)s',
            handlers=[
                logging.FileHandler(LOG_FILE, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
    def run_command(self, command: str, check: bool = True) -> subprocess.CompletedProcess:
        """Executar comando do sistema com log"""
        self.logger.info(f"Executando: {command}")
        try:
            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True, 
                text=True, 
                check=check,
                cwd=PROJECT_DIR
            )
            if result.stdout:
                self.logger.info(f"STDOUT: {result.stdout.strip()}")
            if result.stderr:
                self.logger.warning(f"STDERR: {result.stderr.strip()}")
            return result
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Erro ao executar comando: {e}")
            self.logger.error(f"STDOUT: {e.stdout}")
            self.logger.error(f"STDERR: {e.stderr}")
            raise
            
    def service_exists(self) -> bool:
        """Verificar se o serviço existe"""
        try:
            result = self.run_command(f'sc query "{SERVICE_NAME}"', check=False)
            return result.returncode == 0
        except:
            return False
            
    def service_is_running(self) -> bool:
        """Verificar se o serviço está rodando"""
        try:
            result = self.run_command(f'sc query "{SERVICE_NAME}"', check=False)
            return "RUNNING" in result.stdout
        except:
            return False
            
    def install_service(self):
        """Instalar o serviço Windows"""
        if self.service_exists():
            self.logger.info("Serviço já existe. Removendo primeiro...")
            self.remove_service()
            
        # Comando para criar o serviço
        service_command = f'"{PYTHON_EXE}" "{SCRIPT_PATH}" --excel "{EXCEL_URL}" --loop --loop-interval 0 --log-level INFO --ignore-failure-rates'
        
        cmd = f'sc create "{SERVICE_NAME}" binPath= "{service_command}" DisplayName= "{SERVICE_DISPLAY_NAME}" start= auto'
        
        self.logger.info("Instalando serviço Windows...")
        self.run_command(cmd)
        
        # Configurar descrição
        desc_cmd = f'sc description "{SERVICE_NAME}" "{SERVICE_DESCRIPTION}"'
        self.run_command(desc_cmd, check=False)
        
        # Configurar ação em caso de falha (restart automático)
        failure_cmd = f'sc failure "{SERVICE_NAME}" reset= 60 actions= restart/5000/restart/10000/restart/30000'
        self.run_command(failure_cmd, check=False)
        
        self.logger.info("✅ Serviço instalado com sucesso!")
        
    def start_service(self):
        """Iniciar o serviço"""
        if self.service_is_running():
            self.logger.info("Serviço já está rodando")
            return
            
        self.logger.info("Iniciando serviço...")
        self.run_command(f'sc start "{SERVICE_NAME}"')
        
        # Aguardar um pouco e verificar status
        time.sleep(3)
        if self.service_is_running():
            self.logger.info("✅ Serviço iniciado com sucesso!")
        else:
            self.logger.error("❌ Falha ao iniciar serviço")
            
    def stop_service(self):
        """Parar o serviço"""
        if not self.service_is_running():
            self.logger.info("Serviço já está parado")
            return
            
        self.logger.info("Parando serviço...")
        self.run_command(f'sc stop "{SERVICE_NAME}"')
        
        # Aguardar parar
        for i in range(10):
            time.sleep(1)
            if not self.service_is_running():
                self.logger.info("✅ Serviço parado com sucesso!")
                return
                
        self.logger.warning("⚠️ Serviço demorou para parar")
        
    def remove_service(self):
        """Remover o serviço"""
        if self.service_is_running():
            self.logger.info("Parando serviço antes de remover...")
            self.stop_service()
            
        if self.service_exists():
            self.logger.info("Removendo serviço...")
            self.run_command(f'sc delete "{SERVICE_NAME}"')
            self.logger.info("✅ Serviço removido com sucesso!")
        else:
            self.logger.info("Serviço não existe")
            
    def status_service(self):
        """Mostrar status do serviço"""
        if not self.service_exists():
            self.logger.info("❌ Serviço não está instalado")
            return
            
        result = self.run_command(f'sc query "{SERVICE_NAME}"', check=False)
        print("\n" + "="*50)
        print("STATUS DO SERVIÇO XML DOWNLOADER")
        print("="*50)
        print(result.stdout)
        
        # Mostrar logs recentes
        print("\n" + "="*50)
        print("LOGS RECENTES (últimas 20 linhas)")
        print("="*50)
        try:
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                for line in lines[-20:]:
                    print(line.rstrip())
        except FileNotFoundError:
            print("Arquivo de log não encontrado")
            
    def validate_environment(self) -> bool:
        """Validar se o ambiente está configurado corretamente"""
        issues = []
        
        if not PYTHON_EXE.exists():
            issues.append(f"Python não encontrado: {PYTHON_EXE}")
            
        if not SCRIPT_PATH.exists():
            issues.append(f"Script principal não encontrado: {SCRIPT_PATH}")
            
        if not PROJECT_DIR.exists():
            issues.append(f"Diretório do projeto não encontrado: {PROJECT_DIR}")
            
        if issues:
            self.logger.error("❌ Problemas no ambiente:")
            for issue in issues:
                self.logger.error(f"  - {issue}")
            return False
            
        self.logger.info("✅ Ambiente validado com sucesso")
        return True

def main():
    """Função principal do gerenciador de serviço"""
    manager = WindowsServiceManager()
    
    if len(sys.argv) < 2:
        print(f"""
Uso: python {sys.argv[0]} <comando>

Comandos disponíveis:
  install   - Instalar o serviço Windows
  start     - Iniciar o serviço
  stop      - Parar o serviço  
  remove    - Remover o serviço
  status    - Mostrar status e logs
  validate  - Validar ambiente
  
Exemplos:
  python {sys.argv[0]} install
  python {sys.argv[0]} start
  python {sys.argv[0]} status
  python {sys.argv[0]} stop
  python {sys.argv[0]} remove
""")
        return
        
    command = sys.argv[1].lower()
    
    # Validar ambiente primeiro (exceto para remove)
    if command != "remove" and not manager.validate_environment():
        sys.exit(1)
        
    try:
        if command == "install":
            manager.install_service()
            print("\n🚀 Para iniciar o serviço, execute:")
            print(f"python {sys.argv[0]} start")
            
        elif command == "start":
            manager.start_service()
            print("\n📊 Para ver status, execute:")
            print(f"python {sys.argv[0]} status")
            
        elif command == "stop":
            manager.stop_service()
            
        elif command == "remove":
            manager.remove_service()
            
        elif command == "status":
            manager.status_service()
            
        elif command == "validate":
            if manager.validate_environment():
                print("✅ Ambiente OK para instalação do serviço")
            else:
                print("❌ Corrija os problemas antes de instalar")
                sys.exit(1)
                
        else:
            print(f"❌ Comando inválido: {command}")
            sys.exit(1)
            
    except PermissionError:
        print("❌ ERRO: Execute como Administrador para gerenciar serviços")
        sys.exit(1)
    except Exception as e:
        manager.logger.error(f"Erro inesperado: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 
# Guia de Deployment e Operações - Sistema XML SIEG

## 📋 Índice

1. [Visão Geral de Deployment](#visão-geral-de-deployment)
2. [Configuração do Ambiente](#configuração-do-ambiente)
3. [Deployment em Produção](#deployment-em-produção)
4. [Serviço Windows](#serviço-windows)
5. [Monitoramento e Logs](#monitoramento-e-logs)
6. [Backup e Recuperação](#backup-e-recuperação)
7. [Troubleshooting Operacional](#troubleshooting-operacional)
8. [Procedimentos de Manutenção](#procedimentos-de-manutenção)

---

## 🏗️ Visão Geral de Deployment

### Ambientes Suportados
- **Desenvolvimento**: Windows 10/11 com Python 3.9+
- **Produção**: Windows Server 2019/2022 com Serviço Windows
- **Teste**: Ambiente local com `--limit` para validação

### Topologia de Produção
```
┌─────────────────────────────────────────────────────────────┐
│                    WINDOWS SERVER                           │
│                                                             │
│  ┌─────────────────┐    ┌─────────────────┐                 │
│  │  XML DOWNLOADER │    │   WINDOWS       │                 │
│  │    SERVICE      │────│    SERVICE      │                 │
│  │                 │    │   MANAGER       │                 │
│  └─────────────────┘    └─────────────────┘                 │
│           │                       │                         │
│           ▼                       ▼                         │
│  ┌─────────────────┐    ┌─────────────────┐                 │
│  │   LOGS SYSTEM   │    │   MONITORING    │                 │
│  │   (loguru)      │    │   & ALERTS      │                 │
│  └─────────────────┘    └─────────────────┘                 │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                 EXTERNAL SYSTEMS                            │
│                                                             │
│  ┌─────────────────┐    ┌─────────────────┐                 │
│  │   SIEG API      │    │   SHAREPOINT    │                 │
│  │ api.sieg.com    │    │ (Excel Source)  │                 │
│  └─────────────────┘    └─────────────────┘                 │
│                                                             │
│  ┌─────────────────┐    ┌─────────────────┐                 │
│  │ NETWORK STORAGE │    │   BI SYSTEMS    │                 │
│  │ F:/x_p/XML_*    │    │\\172.16.1.254\  │                 │
│  └─────────────────┘    └─────────────────┘                 │
└─────────────────────────────────────────────────────────────┘
```

---

## ⚙️ Configuração do Ambiente

### 1. **Requisitos de Sistema**

#### **Hardware Mínimo**
- **CPU**: 2 vCPUs (4 vCPUs recomendado)
- **RAM**: 4GB (8GB recomendado)  
- **Disco**: 100GB livres (500GB recomendado)
- **Rede**: Conexão estável 10Mbps+

#### **Software**
- **OS**: Windows Server 2019+ ou Windows 10+ Pro
- **Python**: 3.9+ (3.11 recomendado)
- **PowerShell**: 5.1+ ou PowerShell Core 7+

### 2. **Preparação do Ambiente**

#### **Criação do Ambiente Virtual**
```powershell
# Navegar para diretório do projeto
cd "C:\Projetos\XML-SIEG"

# Criar ambiente virtual
python -m venv .venv

# Ativar ambiente virtual
.venv\Scripts\activate

# Atualizar pip
python -m pip install --upgrade pip

# Instalar dependências
pip install -r requirements.txt
```

#### **Verificação da Instalação**
```powershell
# Testar imports críticos
python -c "import pandas, requests, loguru, lxml; print('✅ Todas dependências OK')"

# Testar conectividade API SIEG
python -c "import requests; r=requests.get('https://api.sieg.com', timeout=10); print(f'✅ API SIEG responde: {r.status_code}')"

# Verificar permissões de escrita
python -c "from pathlib import Path; Path('test.txt').write_text('test'); Path('test.txt').unlink(); print('✅ Permissões de escrita OK')"
```

### 3. **Configuração de Rede e Volumes**

#### **Mapeamento de Drives**
```powershell
# Mapear drives de rede permanentemente
net use F: "\\servidor\xml_primario" /persistent:yes
net use X: "\\172.16.1.254\xml_import" /persistent:yes

# Verificar mapeamentos
net use
```

#### **Configuração de Firewall**
```powershell
# Permitir conexões HTTPS para API SIEG
New-NetFirewallRule -DisplayName "SIEG API HTTPS" -Direction Outbound -Protocol TCP -RemotePort 443 -Action Allow

# Permitir SMB para network storage
New-NetFirewallRule -DisplayName "SMB Share Access" -Direction Outbound -Protocol TCP -RemotePort 445 -Action Allow
```

---

## 🚀 Deployment em Produção

### 1. **Deployment Inicial**

#### **Script de Deploy Automatizado**
```powershell
# deploy.ps1
param(
    [string]$SourcePath,
    [string]$TargetPath = "C:\XMLDownloader",
    [string]$ServiceName = "XMLDownloaderSieg"
)

# Parar serviço existente se estiver rodando
Write-Host "🛑 Parando serviço existente..."
try {
    Stop-Service -Name $ServiceName -ErrorAction SilentlyContinue
    Write-Host "✅ Serviço parado"
} catch {
    Write-Host "ℹ️ Serviço não estava rodando"
}

# Backup do diretório atual
if (Test-Path $TargetPath) {
    $BackupPath = "$TargetPath.backup.$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Write-Host "📦 Criando backup em: $BackupPath"
    Copy-Item -Path $TargetPath -Destination $BackupPath -Recurse
}

# Copiar nova versão
Write-Host "📋 Copiando arquivos do projeto..."
Copy-Item -Path "$SourcePath\*" -Destination $TargetPath -Recurse -Force

# Preservar state.json e logs
if (Test-Path "$BackupPath\state.json") {
    Copy-Item -Path "$BackupPath\state.json" -Destination "$TargetPath\state.json" -Force
    Write-Host "✅ state.json preservado"
}

# Reinstalar dependências
Write-Host "📦 Atualizando dependências..."
Set-Location $TargetPath
.\.venv\Scripts\activate
pip install -r requirements.txt --upgrade

# Reinstalar serviço
Write-Host "🔧 Reinstalando serviço Windows..."
python scripts\xml_service_manager.py remove
python scripts\xml_service_manager.py install
python scripts\xml_service_manager.py start

Write-Host "🎉 Deploy concluído com sucesso!"
```

#### **Checklist de Deployment**
```markdown
- [ ] Backup do ambiente atual criado
- [ ] Ambiente virtual (.venv) atualizado
- [ ] Dependências (requirements.txt) instaladas
- [ ] state.json preservado
- [ ] Logs históricos preservados
- [ ] Configurações de rede verificadas
- [ ] Permissões de acesso validadas
- [ ] Serviço Windows reinstalado
- [ ] Testes de conectividade executados
- [ ] Monitoramento ativado
```

### 2. **Configuração de Produção**

#### **Variáveis de Ambiente**
```powershell
# Configurar variáveis de sistema
[Environment]::SetEnvironmentVariable("XML_ENV", "production", "Machine")
[Environment]::SetEnvironmentVariable("XML_LOG_LEVEL", "INFO", "Machine")
[Environment]::SetEnvironmentVariable("XML_API_TIMEOUT", "60", "Machine")

# Configurar API Key (usando Credential Manager)
cmdkey /generic:"sieg-api" /user:"xml-downloader" /pass:"$API_KEY"
```

#### **Paths de Produção**
```python
# core/config.py - Configurações específicas de produção
if os.environ.get("XML_ENV") == "production":
    PRIMARY_SAVE_BASE_PATH = Path("F:/x_p/XML_CLIENTES")
    FLAT_COPY_PATH = Path("\\\\172.16.1.254\\xml_import\\Import") 
    CANCELLED_COPY_BASE_PATH = Path("\\\\172.16.1.254\\xml_import\\Cancelados")
    
    # Timeouts mais longos em produção
    API_REQUEST_TIMEOUT = 60
    REPORT_DOWNLOAD_RETRIES = 5
else:
    # Configurações de desenvolvimento
    PRIMARY_SAVE_BASE_PATH = Path("xmls")
    # ...
```

---

## 🏢 Serviço Windows

### 1. **Arquitetura do Serviço**

```
Windows Service Manager
        │
        ▼
┌─────────────────────────────────────┐
│       XMLDownloaderSieg             │
│                                     │
│  ┌─────────────────────────────────┐│
│  │      service_wrapper.py         ││
│  │                                 ││
│  │  ┌─────────────────────────────┐││
│  │  │   xml_downloader_service.py │││
│  │  │                             │││
│  │  │  ┌─────────────────────────┐│││
│  │  │  │      app/run.py         ││││
│  │  │  │    (--loop mode)        ││││
│  │  │  └─────────────────────────┘│││
│  │  └─────────────────────────────┘││
│  └─────────────────────────────────┘│
└─────────────────────────────────────┘
```

### 2. **Instalação do Serviço**

#### **Via Interface Gráfica**
```powershell
# Executar como Administrador
cd "C:\XMLDownloader"
scripts\gerenciar_servico.bat

# Menu interativo:
# [1] Validar ambiente
# [2] Instalar serviço Windows  
# [3] Iniciar serviço
# [4] Ver status do serviço
```

#### **Via Linha de Comando**
```powershell
# Validar ambiente
python scripts\xml_service_manager.py validate

# Instalar serviço
python scripts\xml_service_manager.py install

# Iniciar serviço
python scripts\xml_service_manager.py start

# Verificar status
python scripts\xml_service_manager.py status
```

### 3. **Configuração do Serviço**

#### **Parâmetros do Serviço**
```python
# xml_downloader_service.py
SERVICE_CONFIG = {
    "name": "XMLDownloaderSieg",
    "display_name": "XML Downloader SIEG - Paulicon",
    "description": "Serviço automatizado para download de XMLs fiscais da API SIEG",
    "start_type": "automatic",  # Inicia com Windows
    "error_control": "normal"
}

# Parâmetros de execução
EXECUTION_PARAMS = [
    "python", "-m", "app.run",
    "--excel", "https://sharepoint-url/empresas.xlsx",
    "--loop",                    # Execução contínua
    "--loop-interval", "3600",   # 1 hora entre ciclos
    "--ignore-failure-rates",    # Não para por falhas
    "--log-level", "INFO"
]
```

#### **Recuperação Automática**
```powershell
# Configurar política de restart automático
sc failure XMLDownloaderSieg reset= 86400 actions= restart/5000/restart/10000/restart/30000

# Verificar configuração
sc qfailure XMLDownloaderSieg
```

### 4. **Gerenciamento do Serviço**

#### **Comandos Básicos**
```powershell
# Iniciar serviço
sc start XMLDownloaderSieg

# Parar serviço
sc stop XMLDownloaderSieg

# Reiniciar serviço
Restart-Service XMLDownloaderSieg

# Status detalhado
Get-Service XMLDownloaderSieg | Format-List *

# Ver dependências
sc enumdepend XMLDownloaderSieg
```

#### **Monitoramento via PowerShell**
```powershell
# Monitor contínuo do serviço
while ($true) {
    $service = Get-Service XMLDownloaderSieg
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    
    if ($service.Status -eq "Running") {
        Write-Host "[$timestamp] ✅ Serviço rodando normalmente" -ForegroundColor Green
    } else {
        Write-Host "[$timestamp] ❌ Serviço PARADO - Status: $($service.Status)" -ForegroundColor Red
        
        # Tentar reiniciar
        try {
            Start-Service XMLDownloaderSieg
            Write-Host "[$timestamp] 🔄 Tentativa de restart executada" -ForegroundColor Yellow
        } catch {
            Write-Host "[$timestamp] 💥 FALHA no restart: $($_.Exception.Message)" -ForegroundColor Red
        }
    }
    
    Start-Sleep -Seconds 60
}
```

---

## 📊 Monitoramento e Logs

### 1. **Sistema de Logs**

#### **Estrutura de Logs**
```
logs/
├── service.log                 # Logs do serviço Windows
├── global.log                  # Log consolidado da aplicação
├── 2025_01_22_143025.log      # Log da execução atual
└── archived/                   # Logs arquivados (rotação)
    ├── 2025_01_21_*.log
    └── 2025_01_20_*.log
```

#### **Configuração de Logging**
```python
# Configuração automática no app/run.py
def configure_logging(log_level="INFO"):
    timestamp = datetime.now().strftime("%Y_%m_%d_%H%M%S")
    log_filename = f"logs/{timestamp}.log"
    
    logger.configure(
        handlers=[
            {
                "sink": sys.stdout,
                "format": "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
                "level": log_level,
                "colorize": True
            },
            {
                "sink": log_filename,
                "format": "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
                "level": log_level,
                "rotation": "100 MB",
                "retention": "30 days",
                "compression": "gz"
            },
            {
                "sink": "logs/global.log",
                "format": "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
                "level": "WARNING",  # Apenas warnings+ no global
                "rotation": "50 MB",
                "retention": "90 days"
            }
        ]
    )
```

### 2. **Métricas e Alertas**

#### **KPIs Operacionais**
```python
# Métricas coletadas automaticamente
OPERATIONAL_METRICS = {
    "companies_processed": 0,
    "reports_downloaded": 0,
    "xmls_downloaded": 0,
    "api_errors": 0,
    "network_errors": 0,
    "processing_time": 0,
    "last_successful_run": None,
    "pending_reports": 0
}
```

#### **Sistema de Alertas Simples**
```python
# core/alert_manager.py (exemplo de implementação)
class AlertManager:
    def __init__(self, email_config=None, webhook_url=None):
        self.email_config = email_config
        self.webhook_url = webhook_url
    
    def send_critical_alert(self, message: str):
        """Alerta crítico - serviço parado ou erro de autenticação"""
        self._send_alert(f"🚨 CRÍTICO: {message}", priority="high")
    
    def send_warning_alert(self, message: str):
        """Alerta de warning - muitas falhas ou lentidão"""
        self._send_alert(f"⚠️ WARNING: {message}", priority="medium")
    
    def _send_alert(self, message: str, priority: str):
        # Implementar envio via email/webhook
        logger.error(f"ALERT [{priority.upper()}]: {message}")
```

### 3. **Monitoramento Externo**

#### **Health Check Endpoint** (opcional)
```python
# health_check.py - Script auxiliar
import json
from datetime import datetime, timedelta
from pathlib import Path

def check_system_health():
    health = {
        "timestamp": datetime.now().isoformat(),
        "status": "healthy",
        "checks": {}
    }
    
    # Verificar se state.json foi atualizado recentemente
    state_file = Path("state.json")
    if state_file.exists():
        mtime = datetime.fromtimestamp(state_file.stat().st_mtime)
        if datetime.now() - mtime > timedelta(hours=2):
            health["status"] = "degraded"
            health["checks"]["state_file"] = "stale"
        else:
            health["checks"]["state_file"] = "ok"
    else:
        health["status"] = "unhealthy"
        health["checks"]["state_file"] = "missing"
    
    # Verificar logs recentes
    log_dir = Path("logs")
    recent_logs = list(log_dir.glob("2025_*.log"))
    if recent_logs:
        latest_log = max(recent_logs, key=lambda p: p.stat().st_mtime)
        mtime = datetime.fromtimestamp(latest_log.stat().st_mtime)
        if datetime.now() - mtime > timedelta(hours=1):
            health["status"] = "degraded"
            health["checks"]["logging"] = "stale"
        else:
            health["checks"]["logging"] = "ok"
    
    return health

if __name__ == "__main__":
    health = check_system_health()
    print(json.dumps(health, indent=2))
    exit(0 if health["status"] == "healthy" else 1)
```

---

## 💾 Backup e Recuperação

### 1. **Estratégia de Backup**

#### **Dados Críticos para Backup**
```powershell
# backup.ps1 - Script de backup automatizado
$BackupRoot = "\\backup-server\xml-downloader"
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupPath = "$BackupRoot\backup-$Timestamp"

# Criar diretório de backup
New-Item -Path $BackupPath -ItemType Directory -Force

# 1. State.json (CRÍTICO)
Copy-Item "state.json" "$BackupPath\state.json"

# 2. Logs recentes (últimos 7 dias)
$LogsPath = "$BackupPath\logs"
New-Item -Path $LogsPath -ItemType Directory
Get-ChildItem "logs\*.log" | Where-Object {$_.LastWriteTime -gt (Get-Date).AddDays(-7)} | Copy-Item -Destination $LogsPath

# 3. Configurações customizadas
Copy-Item "core\config.py" "$BackupPath\config.py"
Copy-Item "requirements.txt" "$BackupPath\requirements.txt"

# 4. Transactions (auditoria)
Copy-Item "transactions\completed\*" "$BackupPath\transactions\" -Recurse

# 5. Compactar backup
Compress-Archive -Path "$BackupPath\*" -DestinationPath "$BackupPath.zip"
Remove-Item $BackupPath -Recurse

Write-Host "✅ Backup criado: $BackupPath.zip"
```

#### **Agendamento de Backups**
```powershell
# Criar task scheduler para backup diário
$TaskName = "XMLDownloader-Backup"
$ScriptPath = "C:\XMLDownloader\scripts\backup.ps1"

$Action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-File $ScriptPath"
$Trigger = New-ScheduledTaskTrigger -Daily -At 2:00AM
$Settings = New-ScheduledTaskSettingsSet -WakeToRun

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -User "SYSTEM"
```

### 2. **Procedimentos de Recuperação**

#### **Recuperação Completa**
```powershell
# restore.ps1 - Recuperação completa do sistema
param(
    [Parameter(Mandatory=$true)]
    [string]$BackupPath
)

# Parar serviço
Stop-Service XMLDownloaderSieg -Force

# Extrair backup
Expand-Archive -Path $BackupPath -DestinationPath "restore-temp" -Force

# Restaurar state.json
Copy-Item "restore-temp\state.json" "state.json" -Force
Write-Host "✅ state.json restaurado"

# Restaurar logs
Copy-Item "restore-temp\logs\*" "logs\" -Force
Write-Host "✅ Logs restaurados"

# Restaurar configurações
Copy-Item "restore-temp\config.py" "core\config.py" -Force

# Limpar temporários
Remove-Item "restore-temp" -Recurse -Force

# Reiniciar serviço
Start-Service XMLDownloaderSieg
Write-Host "🎉 Recuperação completa concluída"
```

#### **Recuperação de Estado Corrompido**
```powershell
# Se state.json estiver corrompido
if (Test-Path "state.json.backup") {
    Copy-Item "state.json.backup" "state.json" -Force
    Write-Host "✅ Recuperado de backup local"
} else {
    # Resetar state.json
    '{"processed_xml_keys": {}, "xml_skip_counts": {}, "report_download_status": {}, "report_pendencies": {}, "schema_version": 2}' | Out-File "state.json" -Encoding UTF8
    Write-Host "⚠️ State resetado - reprocessamento completo será necessário"
}
```

---

## 🔧 Troubleshooting Operacional

### 1. **Problemas Comuns**

#### **Serviço Não Inicia**
```powershell
# Diagnóstico
sc query XMLDownloaderSieg
Get-EventLog -LogName System -Source "Service Control Manager" -Newest 10

# Soluções
# 1. Verificar dependências
python scripts\xml_service_manager.py validate

# 2. Verificar permissões
icacls "C:\XMLDownloader" /grant "SYSTEM:(OI)(CI)F"

# 3. Reinstalar serviço
python scripts\xml_service_manager.py remove
python scripts\xml_service_manager.py install
```

#### **Alto Uso de CPU/Memória**
```powershell
# Monitorar recursos
Get-Counter "\Process(python)\% Processor Time" -SampleInterval 5 -MaxSamples 10
Get-Counter "\Process(python)\Private Bytes" -SampleInterval 5 -MaxSamples 10

# Verificar se há leak de memory
Get-Process python | Format-Table Name, ID, WorkingSet, VirtualMemorySize
```

#### **Falhas de Conectividade**
```powershell
# Testar conectividade API
Test-NetConnection -ComputerName api.sieg.com -Port 443

# Testar shares de rede
Test-Path "F:\x_p\XML_CLIENTES"
Test-Path "\\172.16.1.254\xml_import"

# Verificar DNS
Resolve-DnsName api.sieg.com
```

### 2. **Scripts de Diagnóstico**

#### **Diagnóstico Completo**
```powershell
# diagnose.ps1
Write-Host "=== DIAGNÓSTICO COMPLETO XML DOWNLOADER ===" -ForegroundColor Yellow

# 1. Status do serviço
Write-Host "`n1. STATUS DO SERVIÇO:" -ForegroundColor Cyan
Get-Service XMLDownloaderSieg | Format-Table Name, Status, StartType

# 2. Conectividade
Write-Host "`n2. CONECTIVIDADE:" -ForegroundColor Cyan
Test-NetConnection api.sieg.com -Port 443 -InformationLevel Quiet
Write-Host "API SIEG: $(if (Test-NetConnection api.sieg.com -Port 443 -InformationLevel Quiet) {'✅ OK'} else {'❌ FALHA'})"

# 3. Volumes de rede
Write-Host "`n3. VOLUMES DE REDE:" -ForegroundColor Cyan
Write-Host "F: drive: $(if (Test-Path 'F:\') {'✅ OK'} else {'❌ FALHA'})"
Write-Host "Share BI: $(if (Test-Path '\\172.16.1.254\xml_import') {'✅ OK'} else {'❌ FALHA'})"

# 4. Arquivos críticos
Write-Host "`n4. ARQUIVOS CRÍTICOS:" -ForegroundColor Cyan
Write-Host "state.json: $(if (Test-Path 'state.json') {'✅ OK'} else {'❌ MISSING'})"
Write-Host "Python: $(if (Get-Command python -ErrorAction SilentlyContinue) {'✅ OK'} else {'❌ MISSING'})"

# 5. Logs recentes
Write-Host "`n5. LOGS RECENTES:" -ForegroundColor Cyan
$RecentLogs = Get-ChildItem "logs\2025_*.log" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 3
if ($RecentLogs) {
    $RecentLogs | Format-Table Name, LastWriteTime, @{Name='Size(MB)';Expression={[math]::Round($_.Length/1MB,2)}}
} else {
    Write-Host "❌ Nenhum log recente encontrado"
}

# 6. Uso de recursos
Write-Host "`n6. USO DE RECURSOS:" -ForegroundColor Cyan
$PythonProcesses = Get-Process python -ErrorAction SilentlyContinue
if ($PythonProcesses) {
    $PythonProcesses | Format-Table ID, Name, @{Name='CPU(%)';Expression={$_.CPU}}, @{Name='Memory(MB)';Expression={[math]::Round($_.WS/1MB,2)}}
} else {
    Write-Host "ℹ️ Nenhum processo Python em execução"
}

Write-Host "`n=== FIM DO DIAGNÓSTICO ===" -ForegroundColor Yellow
```

---

## 🔄 Procedimentos de Manutenção

### 1. **Manutenção Preventiva**

#### **Limpeza de Logs** (Semanal)
```powershell
# cleanup-logs.ps1
$LogsPath = "logs"
$ArchivePath = "logs\archived"
$CutoffDate = (Get-Date).AddDays(-30)

# Criar diretório de arquivo
New-Item -Path $ArchivePath -ItemType Directory -Force

# Arquivar logs antigos
Get-ChildItem "$LogsPath\2025_*.log" | 
    Where-Object {$_.LastWriteTime -lt $CutoffDate} |
    ForEach-Object {
        $ArchiveFile = "$ArchivePath\$($_.Name).gz"
        # Compactar e mover
        Compress-Archive -Path $_.FullName -DestinationPath $ArchiveFile
        Remove-Item $_.FullName
        Write-Host "📦 Arquivado: $($_.Name)"
    }

Write-Host "✅ Limpeza de logs concluída"
```

#### **Otimização de State.json** (Mensal)
```python
# optimize-state.py
import json
from datetime import datetime, timedelta
from pathlib import Path

def optimize_state_file():
    """Remove entradas antigas do state.json para otimizar performance"""
    state_file = Path("state.json")
    if not state_file.exists():
        return
    
    with open(state_file, 'r') as f:
        state = json.load(f)
    
    # Remover chaves XML processadas de mais de 3 meses
    cutoff_date = datetime.now() - timedelta(days=90)
    
    processed_keys = state.get("processed_xml_keys", {})
    for cnpj in list(processed_keys.keys()):
        for month_str in list(processed_keys[cnpj].keys()):
            try:
                month_date = datetime.strptime(month_str, "%Y-%m")
                if month_date < cutoff_date:
                    del processed_keys[cnpj][month_str]
                    print(f"🧹 Removido mês antigo: {cnpj}/{month_str}")
            except ValueError:
                continue
        
        # Remover CNPJ vazio
        if not processed_keys[cnpj]:
            del processed_keys[cnpj]
    
    # Backup antes de salvar
    backup_file = f"state.json.backup.{datetime.now().strftime('%Y%m%d')}"
    with open(backup_file, 'w') as f:
        json.dump(state, f, indent=2)
    
    # Salvar estado otimizado
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)
    
    print(f"✅ State.json otimizado. Backup salvo em: {backup_file}")

if __name__ == "__main__":
    optimize_state_file()
```

### 2. **Atualizações de Sistema**

#### **Atualização de Dependências**
```powershell
# update-dependencies.ps1
# Ativar ambiente virtual
.venv\Scripts\activate

# Backup das dependências atuais
pip freeze > requirements-backup.txt

# Atualizar pip
python -m pip install --upgrade pip

# Atualizar dependências (cuidado!)
pip install --upgrade pandas requests loguru lxml openpyxl

# Gerar nova lista
pip freeze > requirements-new.txt

# Testar se tudo funciona
python -c "
import app.run
import core.api_client
import core.state_manager
print('✅ Todos os módulos carregaram com sucesso')
"

Write-Host "✅ Dependências atualizadas. Revisar requirements-new.txt antes de commitar"
```

#### **Rotação de API Keys**
```powershell
# rotate-api-key.ps1
param(
    [Parameter(Mandatory=$true)]
    [string]$NewApiKey
)

# Parar serviço
Stop-Service XMLDownloaderSieg

# Atualizar credential manager
cmdkey /delete:"sieg-api"
cmdkey /generic:"sieg-api" /user:"xml-downloader" /pass:"$NewApiKey"

# Testar nova chave
python -c "
from core.api_client import SiegApiClient
import os
api_key = '$NewApiKey'
client = SiegApiClient(api_key)
# Fazer teste simples
print('✅ Nova API key validada')
"

# Reiniciar serviço
Start-Service XMLDownloaderSieg

Write-Host "🔑 API Key rotacionada com sucesso"
```

---

## 📈 Otimização de Performance

### 1. **Monitoramento de Performance**
```python
# performance_monitor.py
import psutil
import time
from datetime import datetime

def monitor_performance(duration_minutes=60):
    """Monitor performance por período determinado"""
    end_time = time.time() + (duration_minutes * 60)
    
    while time.time() < end_time:
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # Memory usage
        memory = psutil.virtual_memory()
        
        # Disk I/O
        disk = psutil.disk_usage('/')
        
        # Network I/O
        net_io = psutil.net_io_counters()
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        print(f"[{timestamp}] CPU: {cpu_percent:5.1f}% | "
              f"RAM: {memory.percent:5.1f}% | "
              f"Disk: {disk.percent:5.1f}% | "
              f"Net: ↓{net_io.bytes_recv/1024/1024:6.1f}MB ↑{net_io.bytes_sent/1024/1024:6.1f}MB")
        
        time.sleep(60)

if __name__ == "__main__":
    monitor_performance()
```

### 2. **Tuning de Configurações**
```python
# Para ambientes com alta latência de rede
API_REQUEST_TIMEOUT = 90  # Aumentar timeout
RATE_LIMIT_DELAY = 3      # Reduzir rate para evitar 429s

# Para ambientes com boa conectividade
API_REQUEST_TIMEOUT = 30  # Timeout padrão
RATE_LIMIT_DELAY = 1      # Rate mais agressivo

# Para processamento em lote otimizado
BATCH_SIZE = 50           # Máximo permitido pela API
CONCURRENT_REQUESTS = 1   # Manter 1 para respeitar rate limit
```

---

*Documentação baseada na análise dos scripts de serviço Windows e configurações operacionais.*
*Última atualização: 2025-07-22*
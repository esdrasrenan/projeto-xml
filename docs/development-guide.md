# Guia de Desenvolvimento - Sistema XML SIEG

## 📋 Índice

1. [Setup do Ambiente de Desenvolvimento](#setup-do-ambiente-de-desenvolvimento)
2. [Estrutura do Projeto](#estrutura-do-projeto)
3. [Padrões de Código](#padrões-de-código)
4. [Convenções de Logging](#convenções-de-logging)
5. [Testing e Debugging](#testing-e-debugging)
6. [Como Adicionar Funcionalidades](#como-adicionar-funcionalidades)
7. [Workflow de Desenvolvimento](#workflow-de-desenvolvimento)
8. [Troubleshooting Comum](#troubleshooting-comum)

---

## 🛠️ Setup do Ambiente de Desenvolvimento

### Pré-requisitos
- **Python 3.9+** (3.11 recomendado)
- **Git** para controle de versão
- **VS Code** ou IDE equivalente
- **Windows 10+** (devido a paths de rede específicos)

### Setup Inicial

#### 1. **Clone e Virtual Environment**
```powershell
# Clone do repositório
git clone <repository-url>
cd xml-sieg-downloader

# Criar ambiente virtual
python -m venv .venv

# Ativar ambiente virtual
.venv\Scripts\activate

# Atualizar pip
python -m pip install --upgrade pip

# Instalar dependências
pip install -r requirements.txt
```

#### 2. **Configuração do IDE (VS Code)**
```json
// .vscode/settings.json
{
    "python.defaultInterpreterPath": ".venv/Scripts/python.exe",
    "python.linting.enabled": true,
    "python.linting.flake8Enabled": true,
    "python.formatting.provider": "black",
    "python.sortImports.args": ["--profile", "black"],
    "files.exclude": {
        "**/__pycache__": true,
        "**/*.pyc": true,
        ".venv": false
    }
}
```

#### 3. **Configuração de Desenvolvimento**
```python
# dev_config.py (criar localmente)
from pathlib import Path

# Override paths para desenvolvimento local
PRIMARY_SAVE_BASE_PATH = Path("./dev_output/xmls")
FLAT_COPY_PATH = Path("./dev_output/flat")
CANCELLED_COPY_BASE_PATH = Path("./dev_output/cancelled")

# Configurações de desenvolvimento
RATE_LIMIT_DELAY = 1.0      # Mais rápido para testes
REQUEST_TIMEOUT = 15        # Menor timeout
MAX_PENDENCY_ATTEMPTS = 3   # Menos tentativas para debug
```

#### 4. **Arquivo de Empresas de Teste**
```excel
# data/test_empresas.xlsx
CnpjCpf          | Nome Tratado
12345678000199   | 001_EMPRESA_TESTE_A
98765432000188   | 002_EMPRESA_TESTE_B
```

---

## 🏗️ Estrutura do Projeto

### Arquitetura Modular

```
projeto/
├── app/                    # Aplicação principal
│   ├── __init__.py
│   └── run.py             # Orchestrator principal
├── core/                  # Módulos centrais
│   ├── __init__.py
│   ├── api_client.py      # Cliente API SIEG
│   ├── config.py          # Configurações
│   ├── file_manager.py    # Operações de arquivo
│   ├── file_manager_transactional.py  # Versão transacional
│   ├── missing_downloader.py  # Recovery de XMLs
│   ├── report_manager.py  # Processamento de relatórios
│   ├── report_validator.py # Validações
│   ├── state_manager.py   # Gerenciamento de estado
│   ├── transaction_manager.py  # Sistema transacional
│   ├── utils.py           # Utilitários
│   └── xml_downloader.py  # Download de eventos
├── scripts/               # Scripts auxiliares
│   ├── *.bat             # Scripts Windows
│   └── *.py              # Scripts Python
├── docs/                  # Documentação
├── logs/                  # Logs (auto-gerado)
├── transactions/          # Transações (auto-gerado)
└── state.json            # Estado persistente (auto-gerado)
```

### Responsabilidades dos Módulos

| Módulo | Responsabilidade | Dependencies |
|--------|------------------|--------------|
| `app/run.py` | Orchestração principal, CLI | Todos os core/* |
| `core/api_client.py` | Comunicação API SIEG | requests, logging |
| `core/state_manager.py` | Estado persistente | json, pathlib |
| `core/file_manager.py` | I/O de arquivos | pandas, lxml, pathlib |
| `core/transaction_manager.py` | Atomicidade | shutil, json |
| `core/utils.py` | Funções utilitárias | re |

---

## 📝 Padrões de Código

### Convenções de Nomenclatura

#### **Variáveis e Funções**
```python
# ✅ BOM: snake_case
cnpj_normalizado = "12345678000199"
xml_download_count = 150

def process_xml_batch(xml_list, output_dir):
    pass

# ❌ RUIM: camelCase não é usado
xmlDownloadCount = 150  # Evitar
processXmlBatch()       # Evitar
```

#### **Classes**
```python
# ✅ BOM: PascalCase
class SiegApiClient:
    pass

class StateManager:
    pass

class TransactionManager:
    pass
```

#### **Constantes**
```python
# ✅ BOM: UPPER_SNAKE_CASE
REQUEST_TIMEOUT = 30
RATE_LIMIT_DELAY = 2
MAX_PENDENCY_ATTEMPTS = 10

# Agrupamento lógico
STATUS_PENDING_API = "pending_api_response"
STATUS_PENDING_PROC = "pending_processing"
STATUS_NO_DATA = "no_data_confirmed"
```

### Type Hints (Fortemente Recomendado)

```python
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path

# ✅ BOM: Type hints explícitos
def process_empresas(
    empresas: List[Tuple[str, str]], 
    output_dir: Path,
    limit: Optional[int] = None
) -> Dict[str, Any]:
    """
    Processa lista de empresas.
    
    Args:
        empresas: Lista de tuplas (cnpj, nome_pasta)
        output_dir: Diretório de saída 
        limit: Limite opcional de empresas
        
    Returns:
        Dicionário com estatísticas do processamento
    """
    pass

# ✅ BOM: Type hints para APIs
def baixar_xmls_lote(
    cnpj: str,
    xml_type: int,
    skip: int = 0,
    take: int = 50
) -> List[str]:
    pass
```

### Error Handling Patterns

#### **Padrão de Retry com Context**
```python
from requests.exceptions import RequestException
import time

def api_call_with_retry(func, *args, max_retries=3, **kwargs):
    """Padrão padrão para calls com retry"""
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except RequestException as e:
            if attempt == max_retries - 1:
                logger.error(f"Falha após {max_retries} tentativas: {e}")
                raise
            
            wait_time = 2 ** attempt  # Exponential backoff
            logger.warning(f"Tentativa {attempt + 1} falhou, aguardando {wait_time}s: {e}")
            time.sleep(wait_time)
```

#### **Context Managers para Recursos**
```python
from contextlib import contextmanager

@contextmanager
def managed_api_client(api_key: str):
    """Context manager para SiegApiClient"""
    client = SiegApiClient(api_key)
    try:
        logger.info("API client inicializado")
        yield client
    except Exception as e:
        logger.error(f"Erro no client API: {e}")
        raise
    finally:
        logger.info("API client finalizado")

# Uso
with managed_api_client(API_KEY) as client:
    result = client.baixar_xmls(payload)
```

### Padrão de Validação

```python
def validate_cnpj(cnpj: str) -> str:
    """
    Valida e normaliza CNPJ.
    
    Args:
        cnpj: CNPJ em qualquer formato
        
    Returns:
        CNPJ normalizado (apenas dígitos)
        
    Raises:
        ValueError: Se CNPJ inválido
    """
    if not cnpj:
        raise ValueError("CNPJ não pode ser vazio")
    
    # Remove formatação
    cnpj_clean = re.sub(r'[^\d]', '', cnpj)
    
    if len(cnpj_clean) != 14:
        raise ValueError(f"CNPJ deve ter 14 dígitos, recebido: {len(cnpj_clean)}")
    
    # Validação de dígito verificador (se necessário)
    # ...
    
    return cnpj_clean

# Uso consistente
def process_empresa(cnpj_raw: str, nome: str):
    try:
        cnpj_norm = validate_cnpj(cnpj_raw)
        logger.info(f"Processando empresa: {cnpj_norm} - {nome}")
        # ... processamento
    except ValueError as e:
        logger.error(f"CNPJ inválido '{cnpj_raw}': {e}")
        return None
```

---

## 📊 Convenções de Logging

### Estrutura de Log Messages

```python
from loguru import logger

# ✅ BOM: Contexto claro
logger.info(f"Iniciando download para empresa: {cnpj} ({nome_empresa})")
logger.debug(f"Parâmetros: skip={skip}, take={take}, papel={papel}")
logger.warning(f"Tentativa {attempt}/{max_retries} falhou para relatório {report_type}")
logger.error(f"Falha crítica no processamento de {cnpj}: {error}")

# ✅ BOM: Progresso quantificado
logger.info(f"Processadas {processed}/{total} empresas ({processed/total*100:.1f}%)")
logger.success(f"✅ Download concluído: {xml_count} XMLs salvos em {elapsed:.2f}s")

# ❌ EVITAR: Logs muito verbosos
logger.debug("Entrando na função")  # Desnecessário
logger.info("Processando...")       # Sem contexto
```

### Log Levels Guidelines

| Level | Quando Usar | Exemplo |
|-------|-------------|---------|
| `DEBUG` | Detalhes de desenvolvimento | Parâmetros de função, valores de variável |
| `INFO` | Progresso normal | Início/fim de processamento, estatísticas |
| `SUCCESS` | Operações bem-sucedidas | Download completo, salvamento OK |
| `WARNING` | Problemas não-críticos | Retry, dados ausentes, fallbacks |
| `ERROR` | Erros recuperáveis | Falha de API, arquivo corrompido |
| `CRITICAL` | Erros irrecuperáveis | Falha de autenticação, disco cheio |

### Structured Logging Pattern

```python
def log_operation_metrics(
    operation: str,
    cnpj: str,
    duration: float,
    items_processed: int,
    errors: int = 0
):
    """Log estruturado para métricas"""
    logger.info(
        f"[METRICS] {operation} | "
        f"CNPJ: {cnpj} | "
        f"Duration: {duration:.2f}s | "
        f"Items: {items_processed} | "
        f"Errors: {errors} | "
        f"Rate: {items_processed/duration:.1f} items/s"
    )

# Uso
start_time = time.time()
# ... processamento ...
log_operation_metrics("XML_DOWNLOAD", cnpj, time.time() - start_time, xml_count, error_count)
```

---

## 🧪 Testing e Debugging

### Estrutura de Testes (Sugestão)

```python
# tests/test_api_client.py
import pytest
from unittest.mock import Mock, patch
from core.api_client import SiegApiClient

class TestSiegApiClient:
    def setup_method(self):
        self.api_key = "test_api_key"
        self.client = SiegApiClient(self.api_key)
    
    def test_rate_limit_enforcement(self):
        """Testa se rate limit é respeitado"""
        import time
        start = time.time()
        
        # Simular duas chamadas consecutivas
        with patch.object(self.client.session, 'post') as mock_post:
            mock_post.return_value.json.return_value = {"test": "data"}
            mock_post.return_value.status_code = 200
            
            self.client._make_request("/test1", {})
            self.client._make_request("/test2", {})
            
        duration = time.time() - start
        assert duration >= self.client.RATE_LIMIT_DELAY

    def test_retry_on_500(self):
        """Testa retry em erro 500"""
        with patch.object(self.client.session, 'post') as mock_post:
            # Primeiro retorna 500, depois 200
            mock_post.side_effect = [
                Mock(status_code=500, json=lambda: {"error": "server error"}),
                Mock(status_code=200, json=lambda: {"success": "ok"})
            ]
            
            result = self.client._make_request("/test", {})
            assert result == {"success": "ok"}
            assert mock_post.call_count == 2
```

### Debugging Helpers

#### **State Inspector**
```python
# debug_tools.py
import json
from pathlib import Path

def inspect_state(state_file="state.json"):
    """Helper para inspecionar state.json"""
    if not Path(state_file).exists():
        print(f"❌ {state_file} não existe")
        return
    
    with open(state_file, 'r') as f:
        state = json.load(f)
    
    # Estatísticas gerais
    processed_keys = state.get("processed_xml_keys", {})
    skip_counts = state.get("xml_skip_counts", {})
    pendencies = state.get("report_pendencies", {})
    
    print(f"📊 STATE STATISTICS")
    print(f"Companies with processed keys: {len(processed_keys)}")
    print(f"Companies with skip counts: {len(skip_counts)}")
    print(f"Companies with pendencies: {len(pendencies)}")
    print(f"Schema version: {state.get('schema_version', 'unknown')}")
    
    # Top companies por volume
    key_counts = {}
    for cnpj, months in processed_keys.items():
        total = sum(len(types.get(report_type, [])) for types in months.values() for report_type in types)
        key_counts[cnpj] = total
    
    if key_counts:
        print(f"\n🔝 TOP 5 COMPANIES BY PROCESSED XMLS:")
        for cnpj, count in sorted(key_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
            print(f"  {cnpj}: {count:,} XMLs")

def inspect_logs(log_pattern="logs/2025_*.log", errors_only=False):
    """Helper para analisar logs"""
    from pathlib import Path
    import re
    
    log_files = list(Path().glob(log_pattern))
    if not log_files:
        print(f"❌ Nenhum log encontrado: {log_pattern}")
        return
    
    latest_log = max(log_files, key=lambda p: p.stat().st_mtime)
    print(f"📋 Analisando: {latest_log}")
    
    with open(latest_log, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    if errors_only:
        error_lines = [line for line in lines if 'ERROR' in line or 'CRITICAL' in line]
        print(f"🚨 {len(error_lines)} errors encontrados:")
        for line in error_lines[-10:]:  # Últimos 10 erros
            print(f"  {line.strip()}")
    else:
        print(f"📈 Total lines: {len(lines)}")
        # Contadores por nível
        levels = {"DEBUG": 0, "INFO": 0, "WARNING": 0, "ERROR": 0, "SUCCESS": 0}
        for line in lines:
            for level in levels:
                if f"| {level} " in line:
                    levels[level] += 1
                    break
        
        for level, count in levels.items():
            if count > 0:
                print(f"  {level}: {count}")
```

#### **API Test Tool**
```python
# test_api.py
import sys
from core.api_client import SiegApiClient

def test_api_connectivity(api_key: str):
    """Testa conectividade básica com API"""
    try:
        client = SiegApiClient(api_key)
        
        # Teste 1: Contar XMLs (baixo impacto)
        print("🔍 Testando contagem de XMLs...")
        payload = {
            "XmlType": 1,
            "DataInicio": "2025-01-01",
            "DataFim": "2025-01-01",
            "CnpjEmit": "00000000000000"  # CNPJ dummy
        }
        result = client.contar_xmls(payload)
        print(f"✅ Contagem OK: {result}")
        
        print("🎉 API está respondendo normalmente")
        return True
        
    except Exception as e:
        print(f"❌ Erro na API: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python test_api.py <API_KEY>")
        sys.exit(1)
    
    test_api_connectivity(sys.argv[1])
```

---

## ➕ Como Adicionar Funcionalidades

### 1. **Adicionar Novo Tipo de Documento**

Exemplo: Suporte a CTe OS (Outros Serviços)

#### **Passo 1: Definir Constantes**
```python
# core/utils.py
XML_TYPE_NFE = 1
XML_TYPE_CTE = 2
XML_TYPE_CTE_OS = 3  # NOVO

TYPE_MAPPING = {
    "NFe": XML_TYPE_NFE,
    "CTe": XML_TYPE_CTE,
    "CTeOS": XML_TYPE_CTE_OS  # NOVO
}

VALID_XML_TYPES = [XML_TYPE_NFE, XML_TYPE_CTE, XML_TYPE_CTE_OS]
```

#### **Passo 2: Atualizar API Client**
```python
# core/api_client.py
def baixar_relatorio_xml(self, cnpj: str, xml_type: int, month: int, year: int, report_type: str):
    # Validar novo tipo
    if xml_type not in VALID_XML_TYPES:
        raise ValueError(f"xml_type inválido: {xml_type}. Válidos: {VALID_XML_TYPES}")
    
    # ... resto da implementação
```

#### **Passo 3: Atualizar File Manager**
```python
# core/file_manager.py 
def _get_xml_info(root: etree._Element, empresa_cnpj: str) -> Optional[Dict[str, Any]]:
    # Detectar tipo de documento
    if root.tag.endswith("}infNFe"):
        doc_type = "NFe"
    elif root.tag.endswith("}infCte"):
        doc_type = "CTe"
    elif root.tag.endswith("}infCTeOS"):  # NOVO
        doc_type = "CTeOS"
    else:
        logger.warning(f"Tipo de documento não reconhecido: {root.tag}")
        return None
    
    # ... resto da implementação
```

### 2. **Adicionar Novo Endpoint de API**

#### **Passo 1: Método no API Client**
```python
# core/api_client.py
def verificar_status_documento(self, chave_xml: str) -> Dict[str, Any]:
    """
    Novo endpoint para verificar status de um documento.
    
    Args:
        chave_xml: Chave de acesso do XML (44 dígitos)
        
    Returns:
        Status do documento na SEFAZ
    """
    if len(chave_xml) != 44:
        raise ValueError("Chave XML deve ter 44 dígitos")
    
    payload = {"ChaveXml": chave_xml}
    return self._make_request("/VerificarStatusDocumento", payload)
```

#### **Passo 2: Integrar no Fluxo Principal**
```python
# app/run.py
def process_xml_with_status_check(api_client, xml_key, xml_type):
    """Processa XML com verificação de status"""
    
    # Download do XML
    xml_content = api_client.baixar_xml_especifico(xml_key, xml_type)
    
    if xml_content:
        # Verificar status na SEFAZ
        try:
            status = api_client.verificar_status_documento(xml_key)
            logger.info(f"Status SEFAZ para {xml_key}: {status}")
            
            # Processar apenas se autorizado
            if status.get("situacao") == "autorizado":
                return save_xml(xml_content, xml_key)
            else:
                logger.warning(f"XML {xml_key} não autorizado: {status}")
                return None
                
        except Exception as e:
            logger.error(f"Erro ao verificar status {xml_key}: {e}")
            # Continuar sem verificação
            return save_xml(xml_content, xml_key)
    
    return None
```

### 3. **Adicionar Novo Sistema de Notificação**

#### **Passo 1: Alert Manager**
```python
# core/alert_manager.py
import smtplib
import requests
from email.mime.text import MIMEText
from typing import Optional

class AlertManager:
    def __init__(self, email_config: Optional[dict] = None, webhook_url: Optional[str] = None):
        self.email_config = email_config
        self.webhook_url = webhook_url
    
    def send_alert(self, message: str, level: str = "info"):
        """Envia alerta via email e/ou webhook"""
        
        # Email
        if self.email_config and level in ["error", "critical"]:
            self._send_email_alert(message, level)
        
        # Webhook (Slack, Teams, etc)
        if self.webhook_url:
            self._send_webhook_alert(message, level)
    
    def _send_email_alert(self, message: str, level: str):
        try:
            msg = MIMEText(message)
            msg['Subject'] = f"[XML-SIEG {level.upper()}] Alert"
            msg['From'] = self.email_config['from']
            msg['To'] = self.email_config['to']
            
            with smtplib.SMTP(self.email_config['smtp_server'], self.email_config['smtp_port']) as server:
                if self.email_config.get('use_tls'):
                    server.starttls()
                if self.email_config.get('username'):
                    server.login(self.email_config['username'], self.email_config['password'])
                server.send_message(msg)
                
            logger.info(f"Alert email enviado: {level}")
            
        except Exception as e:
            logger.error(f"Falha ao enviar email alert: {e}")
    
    def _send_webhook_alert(self, message: str, level: str):
        try:
            payload = {
                "text": f"[XML-SIEG {level.upper()}] {message}",
                "username": "XML-SIEG-Bot"
            }
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Webhook alert enviado: {level}")
            
        except Exception as e:
            logger.error(f"Falha ao enviar webhook alert: {e}")

# Usage no app/run.py
alert_manager = AlertManager(
    email_config=EMAIL_CONFIG,  # Configurar via environment
    webhook_url=SLACK_WEBHOOK_URL
)

def handle_critical_error(error_msg: str):
    logger.critical(error_msg)
    alert_manager.send_alert(error_msg, "critical")
```

---

## 🔄 Workflow de Desenvolvimento

### Git Workflow Recomendado

#### **Branch Strategy**
```bash
# Branch principal
main/master          # Código em produção

# Branches de desenvolvimento
feature/nome-feature  # Nova funcionalidade
bugfix/nome-bug      # Correção de bug
hotfix/nome-hotfix   # Correção urgente

# Exemplo
git checkout -b feature/add-cteos-support
git checkout -b bugfix/fix-rate-limit-issue
```

#### **Commit Conventions**
```bash
# Formato: tipo(escopo): descrição
feat(api): adiciona suporte a CTeOS
fix(state): corrige migração de schema v1->v2  
perf(batch): otimiza tamanho de lote para 50
docs(readme): atualiza instruções de instalação
test(api): adiciona testes para retry logic
refactor(logging): padroniza mensagens de log

# Exemplos práticos
git commit -m "feat(api): implementa endpoint verificar_status_documento"
git commit -m "fix(network): resolve timeout em uploads grandes"
git commit -m "perf(memory): otimiza uso de RAM em processamento de relatórios"
```

### Code Review Checklist

#### **Funcionalidade**
- [ ] Código funciona conforme especificação
- [ ] Edge cases são tratados adequadamente
- [ ] Error handling é robusto
- [ ] Performance é aceitável

#### **Qualidade**
- [ ] Type hints estão presentes
- [ ] Docstrings estão completas
- [ ] Naming conventions são seguidas
- [ ] Código é legível e bem estruturado

#### **Integrações**
- [ ] Não quebra funcionalidades existentes
- [ ] Logs são informativos
- [ ] Configurações são flexíveis
- [ ] Backward compatibility é mantida

#### **Testes**
- [ ] Testes unitários foram adicionados/atualizados
- [ ] Teste manual foi realizado
- [ ] Edge cases foram testados
- [ ] Performance foi validada

### Release Process

#### **Preparação de Release**
```bash
# 1. Atualizar versão
echo "v1.2.0" > VERSION

# 2. Atualizar changelog
# Documentar mudanças em CHANGELOG.md

# 3. Commit de release
git add VERSION CHANGELOG.md
git commit -m "chore: bump version to v1.2.0"

# 4. Tag da release
git tag -a v1.2.0 -m "Release v1.2.0 - Adiciona suporte CTeOS"

# 5. Push
git push origin main --tags
```

#### **Deployment Checklist**
- [ ] Backup do ambiente atual
- [ ] state.json está preservado
- [ ] Configurações de produção verificadas
- [ ] Dependências atualizadas
- [ ] Serviço Windows reinstalado
- [ ] Logs de deployment verificados
- [ ] Smoke test executado

---

## 🐛 Troubleshooting Comum

### Problemas de Desenvolvimento

#### **Import Errors**
```python
# ❌ Problema comum: import circular
# arquivo_a.py
from arquivo_b import funcao_b

# arquivo_b.py  
from arquivo_a import funcao_a  # CIRCULAR!

# ✅ Solução: reestruturar ou import local
def funcao_que_precisa_de_a():
    from arquivo_a import funcao_a  # Import local
    return funcao_a()
```

#### **Path Issues**
```python
# ❌ Problema: paths relativos inconsistentes
xml_path = "xmls/empresa/arquivo.xml"  # Funciona só se executado da raiz

# ✅ Solução: usar pathlib com paths absolutos
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent  # Diretório do projeto
xml_path = BASE_DIR / "xmls" / "empresa" / "arquivo.xml"
```

#### **Environment Issues**
```bash
# Problema: módulo não encontrado
ModuleNotFoundError: No module named 'core'

# Solução 1: PYTHONPATH
set PYTHONPATH=%PYTHONPATH%;C:\path\to\project

# Solução 2: pip install -e (recomendado)
pip install -e .  # Instala projeto em modo development
```

### Debugging Específico

#### **State.json Corrompido**
```python
def fix_corrupted_state():
    """Repara state.json corrompido"""
    import json
    from datetime import datetime
    
    backup_file = f"state.json.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    try:
        # Tentar carregar existente
        with open("state.json", 'r') as f:
            state = json.load(f)
        print("✅ State.json está válido")
        return state
        
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"❌ State.json corrompido: {e}")
        
        # Backup do arquivo corrompido
        if Path("state.json").exists():
            shutil.copy("state.json", backup_file)
            print(f"📦 Backup criado: {backup_file}")
        
        # Criar state limpo
        clean_state = {
            "processed_xml_keys": {},
            "xml_skip_counts": {},
            "report_download_status": {},
            "report_pendencies": {},
            "last_successful_run": None,
            "schema_version": 2,
            "_metadata": {
                "recovered": datetime.now().isoformat(),
                "backup_file": backup_file
            }
        }
        
        with open("state.json", 'w') as f:
            json.dump(clean_state, f, indent=2)
        
        print("🔧 State.json resetado - será necessário reprocessamento completo")
        return clean_state
```

#### **API Rate Limit Debug**
```python
import time
from functools import wraps

def track_api_calls(func):
    """Decorator para monitorar timing de chamadas API"""
    call_history = []
    
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            call_history.append({
                "timestamp": start_time,
                "duration": duration,
                "status": "success",
                "function": func.__name__
            })
            
            # Verificar rate limit
            if len(call_history) >= 2:
                time_since_last = start_time - call_history[-2]["timestamp"] 
                if time_since_last < 2.0:
                    print(f"⚠️ WARNING: Chamadas muito próximas ({time_since_last:.2f}s)")
            
            return result
            
        except Exception as e:
            duration = time.time() - start_time
            call_history.append({
                "timestamp": start_time,
                "duration": duration,
                "status": "error",
                "error": str(e),
                "function": func.__name__
            })
            raise
            
    def get_call_stats():
        if not call_history:
            return "Nenhuma chamada registrada"
        
        total_calls = len(call_history)
        avg_duration = sum(c["duration"] for c in call_history) / total_calls
        error_rate = sum(1 for c in call_history if c["status"] == "error") / total_calls
        
        return f"Calls: {total_calls} | Avg Duration: {avg_duration:.2f}s | Error Rate: {error_rate:.1%}"
    
    wrapper.get_call_stats = get_call_stats
    return wrapper

# Uso
@track_api_calls
def instrumented_api_call():
    return api_client.baixar_xmls(payload)

# Verificar estatísticas
print(instrumented_api_call.get_call_stats())
```

---

## 📚 Recursos Adicionais

### Documentação de Referência
- [Documentação Técnica Completa](./technical_documentation.md)
- [Guia de Integração API](./api-integration-guide.md)
- [Referência de Configurações](./configuration-reference.md)

### Tools Recomendadas
- **IDE**: VS Code com Python Extension Pack
- **Linting**: flake8, black, isort
- **Type Checking**: mypy
- **Testing**: pytest, unittest.mock
- **Profiling**: cProfile, memory_profiler

### Quick Commands

```bash
# Lint completo
flake8 core/ app/ --max-line-length=100

# Format code
black core/ app/
isort core/ app/ --profile black

# Type checking
mypy core/api_client.py core/state_manager.py

# Run tests
pytest tests/ -v

# Profile específico
python -m cProfile -o profile.stats app/run.py test.xlsx --limit 1

# Memory profiling
python -m memory_profiler app/run.py test.xlsx --limit 1
```

---

*Guia baseado nas convenções identificadas no código fonte.*  
*Última atualização: 2025-07-22*
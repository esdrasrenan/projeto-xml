# Referência de Configurações - Sistema XML SIEG

## 📋 Índice

1. [Visão Geral de Configurações](#visão-geral-de-configurações)
2. [Configurações de API](#configurações-de-api)
3. [Configurações de Armazenamento](#configurações-de-armazenamento)
4. [Configurações de Processamento](#configurações-de-processamento)
5. [Configurações de State Management](#configurações-de-state-management)
6. [Configurações de Logging](#configurações-de-logging)
7. [Variáveis de Ambiente](#variáveis-de-ambiente)
8. [Parâmetros de Linha de Comando](#parâmetros-de-linha-de-comando)
9. [Configurações Hardcoded](#configurações-hardcoded)

---

## 🔧 Visão Geral de Configurações

### Localização das Configurações
```
projeto/
├── core/config.py              # Configurações principais
├── core/api_client.py          # Configurações de API
├── core/state_manager.py       # Configurações de estado
├── core/file_manager.py        # Caminhos de armazenamento
├── app/run.py                  # Configurações de execução
└── scripts/                    # Configurações de serviço
```

### Hierarquia de Precedência
1. **Parâmetros CLI** (maior precedência)
2. **Variáveis de Ambiente**
3. **Constantes no Código**
4. **Valores Padrão** (menor precedência)

---

## 🌐 Configurações de API

### API Client (`core/api_client.py`)

#### **Conectividade**
```python
BASE_URL = "https://api.sieg.com"
REQUEST_TIMEOUT = (10, 30)  # (conexão, leitura) em segundos
REPORT_REQUEST_TIMEOUT = (10, 20)  # DESCONTINUADO - veja timeouts por tipo
ABSOLUTE_TIMEOUT = 45  # Timeout absoluto para XMLs individuais

# Timeouts otimizados por tipo de documento (novo em 2025-08-25)
TIMEOUT_NFE_ABSOLUTE = 90   # NFe: timeout absoluto
TIMEOUT_CTE_ABSOLUTE = 180  # CTe: timeout absoluto (3 min)
TIMEOUT_NFE_READ = 120      # NFe: timeout de leitura
TIMEOUT_CTE_READ = 180      # CTe: timeout de leitura
```

| Parâmetro | Valor Padrão | Descrição | Ajustável |
|-----------|--------------|-----------|-----------|
| `BASE_URL` | `https://api.sieg.com` | URL base da API SIEG | ❌ Hardcoded |
| `REQUEST_TIMEOUT` | `(10, 30)` | Timeout para XMLs individuais | ✅ Via código |
| `TIMEOUT_NFE_ABSOLUTE` | `90` | Timeout absoluto para relatórios NFe | ✅ Via env `SIEG_TIMEOUT_ABSOLUTO_NFE` |
| `TIMEOUT_CTE_ABSOLUTE` | `180` | Timeout absoluto para relatórios CTe | ✅ Via env `SIEG_TIMEOUT_ABSOLUTO_CTE` |
| `TIMEOUT_NFE_READ` | `120` | Timeout de leitura para NFe | ✅ Via env `SIEG_TIMEOUT_LEITURA_NFE` |
| `TIMEOUT_CTE_READ` | `180` | Timeout de leitura para CTe | ✅ Via env `SIEG_TIMEOUT_LEITURA_CTE` |
| `ABSOLUTE_TIMEOUT` | `45` | Timeout via ThreadPoolExecutor (apenas XMLs individuais) | ✅ Via código |

#### **Rate Limiting**
```python
RATE_LIMIT_DELAY = 2  # segundos entre requests
RATE_LIMIT_DELAY_MISSING = 2.1  # para missing downloader
```

| Parâmetro | Valor Padrão | Descrição | Impacto |
|-----------|--------------|-----------|---------|
| `RATE_LIMIT_DELAY` | `2` segundos | Delay entre requests normais | **30 req/min** |
| `RATE_LIMIT_DELAY_MISSING` | `2.1` segundos | Delay para downloads individuais | **28 req/min** |

**⚠️ Cuidado**: Valores muito baixos podem causar HTTP 429 (Too Many Requests)

#### **Retry Strategy**
```python
RETRY_COUNT = 2  # Reduzido de 3 para evitar longos travamentos
RETRY_BACKOFF_FACTOR = 0.5  # 0.5s, 1s (reduzido de 1)
RETRY_STATUS_FORCELIST = (429, 500, 502, 503, 504)
```

| Parâmetro | Valor Padrão | Descrição |
|-----------|--------------|-----------|
| `RETRY_COUNT` | `2` | Tentativas por request (reduzido) |
| `RETRY_BACKOFF_FACTOR` | `0.5` | Multiplicador do delay (exponential) |
| `RETRY_STATUS_FORCELIST` | `(429, 500, 502, 503, 504)` | Status codes para retry |

#### **Heurísticas de Response**
```python
MIN_BASE64_LEN = 200  # Tamanho mínimo para considerar Base64 válido
```

**Lógica**: Responses < 200 chars são consideradas erros inesperados, não Base64 válido.

---

## 💾 Configurações de Armazenamento

### Paths Principais (`core/file_manager.py`)

#### **Diretórios Base**
```python
# Armazenamento principal
PRIMARY_SAVE_BASE_PATH = Path("F:/x_p/XML_CLIENTES")

# Cópia para integração BI
FLAT_COPY_PATH = Path("\\\\172.16.1.254\\xml_import\\Import")

# Eventos de cancelamento
CANCELLED_COPY_BASE_PATH = Path("\\\\172.16.1.254\\xml_import\\Cancelados")
```

#### **Estrutura Hierárquica**
```
{PRIMARY_SAVE_BASE_PATH}/
└── {ANO}/                          # ex: 2024
    └── {NUMERO}_{NOME_EMPRESA}/    # ex: 123_PAULICON_LTDA
        └── {MES}/                  # ex: 05
            ├── NFe/
            │   ├── Emitente/
            │   ├── Destinatario/
            │   └── xml_files/      # Flat copy local
            ├── CTe/
            │   ├── Emitente/
            │   ├── Destinatario/
            │   ├── Tomador/
            │   └── xml_files/
            ├── mes_anterior/       # Regra especial
            └── Eventos/
```

#### **Configuração para Ambientes**

**Produção** (Windows Server):
```python
# Usar drives mapeados
PRIMARY_SAVE_BASE_PATH = Path("F:/x_p/XML_CLIENTES")
FLAT_COPY_PATH = Path("X:/xml_import/Import")  # Mapeado
```

**Desenvolvimento**:
```python
# Usar caminhos locais
PRIMARY_SAVE_BASE_PATH = Path("./xmls")
FLAT_COPY_PATH = Path("./flat_output")
CANCELLED_COPY_BASE_PATH = Path("./cancelled")
```

---

## ⚙️ Configurações de Processamento

### Core Config (`core/config.py`)

#### **Controle de Fluxo**
```python
DIAS_BUSCA_PADRAO = 20    # Padrão para busca inicial
LIMITE_EMPRESAS_TESTE = 3  # Limite para --limit
LIMIAR_LOTE = 10          # Threshold lote vs individual
```

### Circuit Breaker (`app/run.py`)

#### **Proteção contra Falhas Consecutivas**
```python
MAX_CONSECUTIVE_FAILURES = 3  # Falhas antes de ativar circuit breaker
consecutive_failures = {}     # Rastreamento por CNPJ
```

| Parâmetro | Valor Padrão | Descrição | Comportamento |
|-----------|--------------|-----------|---------------|
| `MAX_CONSECUTIVE_FAILURES` | `3` | Limite de falhas consecutivas | Empresa pulada após atingir limite |

| Parâmetro | Valor | Descrição | Quando Usar |
|-----------|-------|-----------|-------------|
| `DIAS_BUSCA_PADRAO` | `20` | Dias de histórico (legacy) | Fluxo antigo |
| `LIMITE_EMPRESAS_TESTE` | `3` | Limit padrão para testes | `--limit` sem valor |
| `LIMIAR_LOTE` | `10` | Min XMLs para batch download | Otimização |

#### **Janelas Temporais**
```python
DIAS_SEED = 30    # Primeira execução (--seed)
DIAS_RETRY = 2    # Execuções incrementais
JANELA_HORAS = 1  # Modo daemon (não usado)
```

**DIAS_SEED vs DIAS_RETRY**:
- **SEED**: Primeira execução - busca 30 dias de histórico
- **RETRY**: Execuções seguintes - apenas 2 dias recentes

### Configurações de Batch (`app/run.py`)

#### **Tamanhos de Lote**
```python
# Hardcoded no código
BATCH_SIZE = 50           # XMLs por request (máximo da API)
REPORT_BATCH_SIZE = 1     # Relatórios processados por vez
```

#### **Delays de Processamento**
```python
# Implícitos no código
API_REQUEST_DELAY = 2     # Entre chamadas API
PROCESSING_DELAY = 0.1    # Entre operações de arquivo
```

---

## 📊 Configurações de State Management

### State Manager (`core/state_manager.py`)

#### **Controle de Pendências**
```python
MAX_PENDENCY_ATTEMPTS = 10  # Máximo tentativas por relatório
DEFAULT_STATE_FILENAME = "state.json"
```

#### **Status Constants**
```python
# Status de pendência
STATUS_PENDING_API = "pending_api_response"
STATUS_PENDING_PROC = "pending_processing"
STATUS_NO_DATA = "no_data_confirmed"
STATUS_MAX_RETRY = "max_attempts_reached"

# Status de download
DOWNLOAD_SUCCESS = "success"
DOWNLOAD_FAILED_API = "failed_api"
DOWNLOAD_FAILED_PROC = "failed_processing"
DOWNLOAD_SKIPPED_NO_DATA = "no_data_confirmed_skipped"
DOWNLOAD_SKIPPED_MAX_ATTEMPTS = "max_attempts_skipped"
```

#### **Schema Version**
```python
CURRENT_SCHEMA_VERSION = 2
```

**Migração Automática**: v1 → v2 (skip counts estruturados)

---

## 📝 Configurações de Logging

### Logging Setup (`app/run.py`)

#### **Destinos de Log**
```python
LOG_DESTINATIONS = [
    "logs/{timestamp}.log",     # Log da execução atual
    "logs/global.log",          # Log consolidado
    sys.stdout                  # Console (desenvolvimento)
]
```

#### **Níveis de Log**
```python
DEFAULT_LOG_LEVEL = "INFO"    # Padrão
CONSOLE_LOG_LEVEL = "INFO"    # Console
FILE_LOG_LEVEL = "DEBUG"      # Arquivo
GLOBAL_LOG_LEVEL = "WARNING"  # Global (apenas warnings+)
```

#### **Rotação de Logs**
```python
LOG_ROTATION = "100 MB"       # Rotação por tamanho
LOG_RETENTION = "30 days"     # Retenção
LOG_COMPRESSION = "gz"        # Compressão
```

---

## 🌍 Variáveis de Ambiente

### Variáveis Suportadas

| Variável | Descrição | Exemplo | Padrão |
|----------|-----------|---------|--------|
| `XML_ENV` | Ambiente de execução | `production`, `development` | `development` |
| `XML_LOG_LEVEL` | Nível de log global | `DEBUG`, `INFO`, `WARNING` | `INFO` |
| `XML_API_TIMEOUT` | Timeout da API (segundos) | `60` | `30` |
| `XML_BATCH_SIZE` | Tamanho do lote | `25` | `50` |
| `XML_RATE_DELAY` | Delay entre requests | `3` | `2` |

### Configuração via Environment

#### **Windows (PowerShell)**
```powershell
# Temporário (sessão atual)
$env:XML_ENV = "production"
$env:XML_LOG_LEVEL = "INFO"

# Permanente (sistema)
[Environment]::SetEnvironmentVariable("XML_ENV", "production", "Machine")
[Environment]::SetEnvironmentVariable("XML_LOG_LEVEL", "INFO", "Machine")
```

#### **Arquivo .env** (futuro)
```bash
# .env (não implementado ainda)
XML_ENV=production
XML_LOG_LEVEL=INFO
XML_API_TIMEOUT=60
XML_BATCH_SIZE=50
XML_RATE_DELAY=2
```

---

## 📃 Parâmetros de Linha de Comando

### Argumentos do `app/run.py`

| Parâmetro | Obrigatório | Descrição | Exemplo |
|-----------|-------------|-----------|---------|
| `excel` | ✅ | Caminho/URL do arquivo de empresas | `data/empresas.xlsx` |
| `--limit` | ❌ | Limitar número de empresas | `--limit 5` |
| `--seed` | ❌ | Modo seed (primeira execução) | `--seed` |
| `--loop` | ❌ | Execução contínua | `--loop` |
| `--pause` | ❌ | Pausa entre loops (segundos) | `--pause 3600` |
| `--log-level` | ❌ | Nível de log | `--log-level DEBUG` |

### Exemplos de Uso

#### **Execução Normal**
```bash
python app/run.py data/cadastro_empresas.xlsx
```

#### **Modo Teste**
```bash
python app/run.py data/cadastro_empresas.xlsx --limit 3
```

#### **Primeira Execução (Seed)**
```bash
python app/run.py data/cadastro_empresas.xlsx --seed
```

#### **Modo Serviço (Loop Contínuo)**
```bash
python app/run.py https://sharepoint.com/empresas.xlsx --loop --pause 3600
```

#### **Debug Verboso**
```bash
python app/run.py data/empresas.xlsx --log-level DEBUG --limit 1
```

---

## 🔒 Configurações Hardcoded

### Constantes Não Configuráveis

#### **API Endpoints**
```python
# Não configuráveis via runtime
ENDPOINTS = {
    "relatorio": "/api/relatorio/xml",
    "baixar_xmls": "/BaixarXmls", 
    "baixar_eventos": "/BaixarEventos",
    "contar_xmls": "/ContarXmls"
}
```

#### **Extensões de Arquivo**
```python
XML_EXTENSION = ".xml"
EXCEL_EXTENSION = ".xlsx"
EVENT_SUFFIX = "_evento"
```

#### **Tipos de XML**
```python
XML_TYPE_NFE = 1
XML_TYPE_CTE = 2

TYPE_MAPPING = {
    "NFe": XML_TYPE_NFE,
    "CTe": XML_TYPE_CTE
}
```

#### **Papéis/Roles**
```python
PAPEL_EMITENTE = "Emitente"
PAPEL_DESTINATARIO = "Destinatario" 
PAPEL_TOMADOR = "Tomador"

VALID_ROLES = [PAPEL_EMITENTE, PAPEL_DESTINATARIO, PAPEL_TOMADOR]
```

#### **Eventos de Cancelamento**
```python
CANCEL_EVENT_TYPES = ["110111", "110110"]  # Tipos de evento de cancelamento
```

---

## ⚡ Tuning de Performance

### Configurações Recomendadas por Ambiente

#### **Desenvolvimento Local**
```python
REQUEST_TIMEOUT = 30
RATE_LIMIT_DELAY = 1.5      # Mais agressivo
BATCH_SIZE = 10             # Menor para debug
MAX_PENDENCY_ATTEMPTS = 3   # Menos tentativas
LOG_LEVEL = "DEBUG"         # Mais verboso
```

#### **Produção (Boa Conectividade)**
```python
REQUEST_TIMEOUT = (10, 30)
REPORT_REQUEST_TIMEOUT = (10, 20)
RATE_LIMIT_DELAY = 2        # Padrão
BATCH_SIZE = 50             # Máximo
MAX_PENDENCY_ATTEMPTS = 10  # Padrão
LOG_LEVEL = "INFO"          # Balanceado
```

#### **Produção (Conectividade Instável)**
```python
REQUEST_TIMEOUT = (10, 90)       # Mais timeout na leitura
REPORT_REQUEST_TIMEOUT = (10, 30) # Timeout moderado para relatórios
ABSOLUTE_TIMEOUT = 60            # Timeout absoluto maior para redes lentas
RATE_LIMIT_DELAY = 3             # Mais conservativo 
BATCH_SIZE = 25                  # Menor lote
MAX_PENDENCY_ATTEMPTS = 15       # Mais tentativas
RETRY_COUNT = 3                  # Retries moderados
LOG_LEVEL = "WARNING"            # Menos verboso
```

### Monitoramento de Performance

#### **Métricas de Rate Limiting**
```python
# Calcular rate efetivo
requests_per_minute = 60 / RATE_LIMIT_DELAY
# Com RATE_LIMIT_DELAY = 2: 30 req/min
# Com RATE_LIMIT_DELAY = 3: 20 req/min
```

#### **Métricas de Throughput**
```python
# XMLs por hora (estimativa)
xmls_por_lote = 50
lotes_por_minuto = 60 / RATE_LIMIT_DELAY
xmls_por_hora = xmls_por_lote * lotes_por_minuto * 60

# Com RATE_LIMIT_DELAY = 2: ~90.000 XMLs/hora (teórico)
```

---

## 🔧 Configuração Avançada

### Custom Configuration Class

```python
# config_manager.py (exemplo de implementação futura)
import os
from pathlib import Path
from typing import Any, Dict, Optional

class ConfigManager:
    """Gerenciador centralizado de configurações com precedência"""
    
    def __init__(self):
        self.config: Dict[str, Any] = {}
        self._load_defaults()
        self._load_environment()
        self._load_cli_args()
    
    def get(self, key: str, default: Any = None) -> Any:
        """Obtém configuração com fallback para padrão"""
        return self.config.get(key, default)
    
    def _load_defaults(self):
        """Carrega valores padrão"""
        self.config.update({
            "api_timeout": 30,
            "rate_limit_delay": 2,
            "batch_size": 50,
            "log_level": "INFO",
            "max_pendency_attempts": 10,
        })
    
    def _load_environment(self):
        """Carrega variáveis de ambiente"""
        env_mapping = {
            "XML_API_TIMEOUT": "api_timeout",
            "XML_RATE_DELAY": "rate_limit_delay", 
            "XML_BATCH_SIZE": "batch_size",
            "XML_LOG_LEVEL": "log_level"
        }
        
        for env_var, config_key in env_mapping.items():
            if env_var in os.environ:
                value = os.environ[env_var]
                # Converter tipos se necessário
                if config_key in ["api_timeout", "rate_limit_delay", "batch_size"]:
                    value = int(value)
                self.config[config_key] = value

# Usage
config = ConfigManager()
api_timeout = config.get("api_timeout")  # 30 ou valor do ambiente
```

### Configuration Validation

```python
def validate_configuration():
    """Valida configurações críticas na inicialização"""
    
    # Verificar paths de armazenamento
    required_paths = [PRIMARY_SAVE_BASE_PATH, FLAT_COPY_PATH]
    for path in required_paths:
        if not path.exists() and not path.parent.exists():
            raise ConfigurationError(f"Path inacessível: {path}")
    
    # Verificar configurações numéricas
    if REQUEST_TIMEOUT <= 0:
        raise ConfigurationError("REQUEST_TIMEOUT deve ser > 0")
    
    if RATE_LIMIT_DELAY < 0.5:
        logger.warning("RATE_LIMIT_DELAY muito baixo - risco de 429")
    
    if BATCH_SIZE > 50:
        raise ConfigurationError("BATCH_SIZE não pode ser > 50 (limite da API)")
    
    logger.info("✅ Todas as configurações validadas")
```

---

## 📚 Referência Rápida

### Configurações Mais Alteradas

| Configuração | Local | Valor Padrão | Quando Alterar |
|--------------|-------|--------------|----------------|
| `RATE_LIMIT_DELAY` | `api_client.py` | `2` | Ajustar performance/429s |
| `REQUEST_TIMEOUT` | `api_client.py` | `30` | Rede instável |
| `MAX_PENDENCY_ATTEMPTS` | `state_manager.py` | `10` | Mais/menos tolerância |
| `BATCH_SIZE` | Hardcoded | `50` | Otimização |
| `LOG_LEVEL` | CLI/env | `INFO` | Debug/produção |

### Comandos de Configuração Rápida

```bash
# Modo debug completo
python app/run.py data/test.xlsx --limit 1 --log-level DEBUG

# Modo produção silencioso  
python app/run.py https://sharepoint.com/empresas.xlsx --loop --log-level WARNING

# Teste de conectividade
python -c "from core.api_client import SiegApiClient; import os; client = SiegApiClient(os.environ['SIEG_API_KEY']); print('API OK')"
```

---

*Documentação baseada na análise completa do código fonte.*  
*Última atualização: 2025-08-01*
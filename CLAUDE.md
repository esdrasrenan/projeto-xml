# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 🎯 Project Overview

**Sistema XML SIEG** - Automated download and organization system for Brazilian fiscal XML documents (NFe/CTe) from SIEG API. The system processes company lists from Excel/SharePoint, downloads fiscal reports, and organizes XMLs in hierarchical structure for BI integration.

### Key Capabilities
- ✅ **Incremental Processing** with skip counts to avoid redownloading
- ✅ **Automatic Recovery** through pendencies system for failed reports  
- ✅ **Atomic Transactions** ensuring data integrity
- ✅ **Rate Limiting** (30 req/min) respecting API limits
- ✅ **24/7 Operation** via Windows Service
- ✅ **Multi-format Support** (NFe, CTe with different roles)

## 🚀 Development Commands

### Quick Start
```bash
# Setup environment
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt

# Test connectivity
python -c "import requests; print('✅ OK' if requests.get('https://api.sieg.com').status_code else '❌ API não disponível')"

# Development run (3 companies, debug logging)  
python app/run.py data/cadastro_empresas.xlsx --limit 3 --log-level DEBUG

# Production run with SharePoint
python app/run.py https://your-sharepoint-url/file.xlsx

# Continuous service mode
python app/run.py https://your-sharepoint-url/file.xlsx --loop --pause 3600

# First-time run (seed mode - 30 days history)
python app/run.py data/cadastro_empresas.xlsx --seed

# Production deployment
executar.bat
```

### Service Management (Windows)

#### Option 1: Windows Task Scheduler (Recommended for Production)
```powershell
# Create scheduled task for continuous execution
# Task runs app/run.py with --loop parameter
# Configured to restart automatically on failure
# More reliable in production environments
```

#### Option 2: Windows Service (Alternative)
```powershell
# Interactive service manager
scripts\gerenciar_servico.bat

# Command line service control
python scripts\xml_service_manager.py install
python scripts\xml_service_manager.py start
python scripts\xml_service_manager.py status
```

## 🏗️ Architecture & Components

### Modular Design
```
app/run.py                  # 🎮 Main orchestrator & CLI
├── core/api_client.py      # 🌐 SIEG API communication + rate limiting
├── core/state_manager.py   # 💾 State persistence + schema migration  
├── core/file_manager.py    # 📁 File I/O + "Mês Anterior" rule
├── core/transaction_manager.py # 🔒 Atomic file operations
├── core/report_manager.py  # 📊 Excel report processing
└── core/xml_downloader.py  # ⬇️ Batch XML downloads + events
```

### Key Architectural Patterns
- **🔄 State Management**: `state.json` with schema v2 migration for resumable operations
- **⚡ Incremental Processing**: Skip counts avoid reprocessing (up to 90,000 XMLs/hour theoretical)
- **🛡️ Transactional Safety**: Atomic file operations ensure data integrity
- **🔁 Retry Pattern**: 3 attempts with exponential backoff (1s → 2s → 4s)
- **⏱️ Rate Limiting**: 2-second delays between requests (30 req/min)
- **📦 Batch Processing**: 50 XMLs per API call (maximum allowed)

### Integration Points
- **📤 SIEG API**: `https://api.sieg.com` - Rate limited HTTP/JSON
- **📋 SharePoint**: Direct Excel download via HTTPS
- **🗄️ Network Storage**: `F:\x_p\XML_CLIENTES` (primary) + `\\172.16.1.254\xml_import` (BI)
- **🏢 Windows Service**: 24/7 operation with auto-restart

## 📁 File Organization & Data Flow

### Hierarchical Storage Structure
```
{PRIMARY_SAVE_BASE_PATH}/           # F:\x_p\XML_CLIENTES
└── {YEAR}/                         # 2024
    └── {NUMBER}_{COMPANY_NAME}/    # 123_PAULICON_LTDA
        └── {MONTH}/                # 05
            ├── NFe/
            │   ├── Relatorio_NFe_YYYYMMDD.xlsx
            │   ├── Emitente/       # Company as issuer
            │   ├── Destinatario/   # Company as recipient
            │   └── xml_files/      # Flat copy for BI
            ├── CTe/
            │   ├── Relatorio_CTe_YYYYMMDD.xlsx
            │   ├── Emitente/
            │   ├── Destinatario/
            │   ├── Tomador/        # Company as service taker
            │   └── xml_files/
            ├── mes_anterior/       # "Previous Month" rule
            │   ├── NFe/Destinatario/
            │   └── CTe/Tomador/
            └── Eventos/            # Cancellation events
```

### Critical Business Rules

#### **1. "Mês Anterior" (Previous Month) Rule**
- **Trigger**: Incoming documents (NFe/Destinatario, CTe/Tomador) issued on days 1-6 of current month
- **Action**: Also saved to `mes_anterior/` subfolder in previous month directory
- **Purpose**: Accounting period alignment for fiscal reporting

#### **2. State Management (state.json Schema v2)**
```json
{
  "processed_xml_keys": {           // Avoid duplicates
    "cnpj": {"YYYY-MM": {"NFe|CTe": ["key1", "key2"]}}
  },
  "xml_skip_counts": {              // Incremental processing
    "cnpj": {"YYYY-MM": {"NFe|CTe": {"role": count}}}
  },
  "report_pendencies": {            // Failed report recovery
    "cnpj": {"YYYY-MM": {"NFe|CTe": {"attempts": 3, "status": "pending"}}}
  }
}
```

#### **3. Pendency Recovery System**
- **Max Attempts**: 10 per report (configurable via `MAX_PENDENCY_ATTEMPTS`)
- **Priority**: `pending_processing` > `pending_api_response` > attempts count
- **States**: `pending_api`, `pending_proc`, `no_data_confirmed`, `max_attempts_reached`

## 🔧 Key Files & Troubleshooting

### Critical Files
| File | Purpose | Location | Auto-Generated |
|------|---------|----------|----------------|
| `state.json` | Runtime state persistence | Project root | ✅ |
| `requirements.txt` | Python dependencies | Project root | ❌ |
| `logs/{timestamp}.log` | Execution logs | `logs/` | ✅ |
| `transactions/completed/` | Operation audit trail | `transactions/` | ✅ |

### Configuration Files
| File | Contains | Editable |
|------|----------|----------|
| `core/config.py` | Constants (BATCH_SIZE, TIMEOUTS) | ✅ |
| `core/api_client.py` | API endpoints, rate limits | ⚠️ |
| `core/file_manager.py` | Storage paths | ⚠️ |

### Common Issues & Solutions

#### **API Rate Limiting (HTTP 429)**
```bash
# Symptoms: "Rate limit persistente após 3 tentativas"
# Solution: Increase delay in core/api_client.py
RATE_LIMIT_DELAY = 3  # Increase from 2 to 3 seconds
```

#### **State.json Corruption**
```python
# Emergency state reset (will require full reprocessing)
echo '{"processed_xml_keys": {}, "xml_skip_counts": {}, "report_pendencies": {}, "schema_version": 2}' > state.json
```

#### **Network Storage Access**
```powershell  
# Test network paths
Test-Path "F:\x_p\XML_CLIENTES"           # Primary storage
Test-Path "\\172.16.1.254\xml_import"    # BI integration
```

#### **Service Not Starting**
```powershell
# Check dependencies and reinstall
python scripts\xml_service_manager.py validate
python scripts\xml_service_manager.py remove
python scripts\xml_service_manager.py install
```

## 📚 Extended Documentation

- 📖 **[Technical Architecture](docs/technical-architecture.md)** - Complete system architecture
- 🌐 **[API Integration Guide](docs/api-integration-guide.md)** - SIEG API details & troubleshooting  
- 🚀 **[Deployment & Operations](docs/deployment-operations-guide.md)** - Production deployment guide
- ⚙️ **[Configuration Reference](docs/configuration-reference.md)** - All settings & parameters
- 🛠️ **[Development Guide](docs/development-guide.md)** - Code conventions & development setup
- 🔄 **[Migration Guide](docs/migracao-logs-state-v2.md)** - Logs estruturados + StateManagerV2 implementation
- 🧹 **[File Cleanup Guide](docs/limpeza-arquivos.md)** - Organizing project files and removing unnecessary items
- 📋 **[Implementation Summary](docs/resumo-implementacao-final.md)** - Final implementation summary
- ⚙️ **[Production Files Guide](docs/arquivos-para-producao.md)** - Essential files for production deployment
- 📊 **[Improvement Plan](docs/plano-melhorias-logs-state.md)** - Planned system improvements
- 🏛️ **[Historical Status](docs/status-historico.md)** - Project evolution history
- 🖥️ **[Windows Service Guide](docs/servico-windows.md)** - Windows service setup and management

## 🎯 Best Practices

### 🧹 File Management
- **Always delete test files** after use to keep project clean
- **Use temporary directories** for processing intermediate files
- **Organize documentation** by category in the `/docs` folder
- **Maintain clean git history** by removing experimental files before commits

### 🔧 Development Guidelines
- **Test with `--limit 1`** before running full batches
- **Monitor rate limiting** - never reduce RATE_LIMIT_DELAY below 2 seconds
- **Use structured logging** - logs are automatically organized by month/company
- **Follow modular architecture** - StateManagerV2 handles states by month
- **Validate network paths** before file operations to prevent hangs

### 🛡️ Production Safety
- **Backup critical data** before major updates
- **Test timeout protection** for API and file operations
- **Use absolute timeout mechanisms** to prevent script freezing
- **Implement circuit breakers** for problematic companies
- **Monitor pendency queues** to detect recurring issues

### 📊 Monitoring & Maintenance
- **Check logs structure**: `logs/MM-YYYY/EMPRESA/empresa.log`
- **Monitor state health**: `gerenciar_estados.bat health`
- **Analyze processing gaps**: `recuperar_gaps.bat analyze`
- **Clean old data periodically**: `gerenciar_estados.bat cleanup`

## ⚡ Performance & Monitoring

### Key Metrics to Monitor
- **API Success Rate**: >95% (excluding known no-data cases)
- **Processing Rate**: ~1,500 XMLs/hour typical, 90,000/hour theoretical max
- **Error Rate**: <1% non-recoverable errors
- **Pendency Queue**: Should not grow unboundedly

### Quick Health Checks
```powershell
# Check if service is running
Get-Service XMLDownloaderSieg

# Recent log analysis  
Get-Content logs\global.log -Tail 50 | Select-String "ERROR|SUCCESS"

# State file last modified (should be recent)
Get-ItemProperty state.json | Select-Object LastWriteTime
```

---

## 🎯 Development Guidelines for Claude Code

### Code Modification Principles
- ✅ **Edit existing files** when possible instead of creating new ones
- ✅ **Follow established patterns** (type hints, error handling, logging)
- ✅ **Respect rate limiting** - never reduce `RATE_LIMIT_DELAY` below 2 seconds
- ✅ **Test changes** with `--limit 1` before full deployment
- ✅ **Preserve state.json** during code updates

### Development Bash Tips
- **sempre usar date no bash para obter a data, isso é útil para criar documentos que precisam de datas reais atualizadas**

### Common Development Tasks
- **Add new document type**: Update `core/utils.py` TYPE_MAPPING + `api_client.py` validation
- **Change API timeouts**: Modify `REQUEST_TIMEOUT` in `core/api_client.py` 
- **Add logging**: Use `logger.info/warning/error` with context (CNPJ, operation, metrics)
- **Debug issues**: Check `state.json` structure, network connectivity, API responses

### Testing Commands
```bash
# Always test with limited scope first
python app/run.py data/test.xlsx --limit 1 --log-level DEBUG

# Validate network connectivity
Test-Path "F:\x_p\XML_CLIENTES"

# Check service health
python scripts\xml_service_manager.py status
```

### ⚠️ Critical: Never Modify Without Understanding
- **state.json schema**: Complex migration logic between versions
- **Rate limiting**: Changes affect API stability  
- **File paths**: Hardcoded network paths are environment-specific
- **Pendency system**: Business logic for recovery workflow

## 📝 Recent Changes Log

### 2025-08-06: Fixed Folder Name Sanitization for Windows Compatibility

**1. Problem Identified: Invalid Characters in Company Names**
- **Issue**: Company "WALCAR" with name `1008_WALCAR_-_ADMINISTRADORA_DE_BENS_PROPRIOS_S/A` was creating subfolder "A"
- **Root Cause**: The `/` character in "S/A" was interpreted as directory separator by Windows
- **Impact**: Incorrect folder structure with logs and XMLs saved in wrong locations

**2. Solution Implemented**
- **New Function**: Added `sanitize_folder_name()` in `core/utils.py`
- **Sanitization Applied**: In `core/file_manager.py` when reading company names from Excel
- **Characters Replaced**: `/`, `\`, `:`, `*`, `?`, `"`, `<`, `>`, `|` all replaced with `_`
- **Result**: Company folder now correctly named `1008_WALCAR_-_ADMINISTRADORA_DE_BENS_PROPRIOS_S_A`

**3. Production Environment Update**
- **Current Setup**: System running via Windows Task Scheduler (not Windows Service)
- **Reason**: Task Scheduler proved more reliable in the production environment
- **Configuration**: Script runs continuously with automatic restart on failure
- **Note**: Documentation updated to reflect actual production configuration

### 2025-08-05: Complete Documentation Organization & System Enhancement + Validation of Timeout Fixes

**1. Documentation Restructuring**
- **What changed**: Moved all .md files (except CLAUDE.md) to `/docs` folder with organized naming
- **Files moved**:
  - `MIGRACAO_LOGS_STATE_V2.md` → `docs/migracao-logs-state-v2.md`
  - `LIMPEZA_ARQUIVOS.md` → `docs/limpeza-arquivos.md`
  - `RESUMO_IMPLEMENTACAO_FINAL.md` → `docs/resumo-implementacao-final.md`
  - `ARQUIVOS_PARA_PRODUCAO.md` → `docs/arquivos-para-producao.md`
  - `PLANO_MELHORIAS_LOGS_STATE.md` → `docs/plano-melhorias-logs-state.md`
  - `STATUS.md` → `docs/status-historico.md`
  - `scripts/README_SERVICO_WINDOWS.md` → `docs/servico-windows.md`
- **Benefits**: Clean project structure, categorized documentation, easier navigation

**2. Enhanced README.md**
- **What changed**: Complete rewrite to reflect current system state with StateManagerV2 and structured logs
- **New features documented**:
  - Logs structured by month/company: `logs/MM-YYYY/EMPRESA/empresa.log`
  - Modular state management: `estado/MM-YYYY/state.json`
  - Maintenance tools: `gerenciar_estados.bat`, `recuperar_gaps.bat`
  - Clear production deployment instructions
- **Impact**: Users can quickly understand current system capabilities and architecture

**3. CLAUDE.md Updates**
- **What changed**: Added comprehensive documentation references and best practices
- **New sections**:
  - Complete documentation index with all `/docs` references
  - Best practices for file management, development, and production safety
  - Enhanced troubleshooting guides with modular system context
- **Impact**: Single source of truth for all project guidance and development standards

**4. File Cleanup System Enhancement**
- **Validated cleanup scripts**: `limpar_arquivos.py` and `limpar_arquivos.bat`
- **Smart cleanup logic**: Preserves 52 essential files, removes 25+ test/development files
- **Maintains testing scripts**: Preserves scripts for testing specific problematic companies
- **Impact**: Clean project structure ready for production deployment

**5. Production Validation of Timeout Fixes**
- **Companies tested**: Via Cargas (CNPJ: 49129329000146) and Viamex validation
- **Via Cargas results**: 
  - ✅ NFe: "Nenhum arquivo xml encontrado" (normal response)
  - ✅ CTe: "Relatório Base64 recebido" (successful download with data)
  - ✅ No timeouts or script freezing detected
- **Viamex discovery**: Missing August folder in production indicates historical processing interruption
- **Root cause confirmed**: Previous timeout/freezing issues prevented completion of August processing
- **Current status**: Timeout protection working correctly, script continues processing

### 2025-08-03: Critical Fix - Script Freezing on Via Cargas Timeout

**1. Problem Identified: Complete Script Freezing**
- **Issue**: Script was freezing completely (not just failing) when downloading Via Cargas CTe reports
- **Root Cause**: Socket-level deadlock that didn't respect Python's configured timeouts
- **Symptom**: Logs would stop abruptly after "Falha ao obter/ler informações do relatório CTe", no further processing
- **Affected Company**: Via Cargas (CNPJ: 49129329000146) - particularly for months with large data volumes

**2. Solution: Absolute Timeout with ThreadPoolExecutor**
- **File Modified**: `core/api_client.py`
- **New Method**: `_execute_with_absolute_timeout()` - executes requests in separate thread with hard timeout
- **Configuration**: 
  - `ABSOLUTE_TIMEOUT = 45` seconds (can be adjusted if needed)
  - Applied to `baixar_relatorio_xml()` by default
- **How it works**: 
  - Request runs in a separate thread
  - If timeout exceeds 45 seconds, thread is abandoned
  - Main script continues execution
- **Result**: Prevents complete script freezing - worst case scenario is an abandoned thread

**3. Timeout Blacklist Implementation**
- **File Modified**: `app/run.py`
- **New Variables**:
  - `timeout_blacklist = {}` - tracks companies that timeout
  - `TIMEOUT_BLACKLIST_DURATION = 3600` seconds (1 hour)
- **Behavior**: 
  - When a company times out, it's added to blacklist
  - Blacklisted companies are skipped for 1 hour
  - After 1 hour, company is automatically removed from blacklist
- **Benefit**: Prevents wasting time on companies with persistent timeout issues

**4. Code Quality Improvements**
- **Fixed Unreachable Code**: Removed duplicate elif condition in previous month verification logic
- **Enhanced Exception Handling**: Added explicit `TimeoutError` catch with proper logging
- **Better Circuit Breaker**: Integrated with existing consecutive failure tracking

**5. Why Previous Timeout Handling Failed**
- **Before**: Used `requests` library timeout: `timeout=(10, 20)`
- **Problem**: When OS-level socket deadlock occurred, Python timeout was ignored
- **Now**: ThreadPoolExecutor provides OS-independent timeout enforcement

**6. Production Deployment**
- **Files to Update**: 
  - `core/api_client.py` - Critical (timeout protection)
  - `app/run.py` - Critical (blacklist and error handling)
- **No Configuration Changes Required**: Works with existing settings
- **Backward Compatible**: All existing functionality preserved

### 2025-08-01: Extended Previous Month Verification Period, Fixed Cancellation Event Storage, and Improved Timeout Handling

**1. Extended Previous Month Verification from 3 to 6 Days**
- **What changed**: Modified the previous month verification period from days 1-3 to days 1-6 of the current month.
- **Files updated**: 
  - `app/run.py`: Changed condition from `if today.day <= 3:` to `if today.day <= 6:`
  - `core/file_manager.py`: Changed range from `1 <= data_emissao.day <= 5` to `1 <= data_emissao.day <= 6`
  - `core/file_manager_transactional.py`: Changed range from `1 <= data_emissao.day <= 5` to `1 <= data_emissao.day <= 6`
- **Why**: Extended the window to ensure fiscal documents from the previous month are properly captured and processed.
- **Impact**: The system will now check and process previous month documents during the first 6 days of each month, and incoming documents issued on days 1-6 will be saved to the `mes_anterior` folder.

**2. Fixed Cancellation Event Storage in TransactionalFileManager**
- **What changed**: Corrected the implementation in `core/file_manager_transactional.py` to match the documented behavior.
- **Why**: The TransactionalFileManager was still creating company subfolders and copying original XMLs along with cancellation events.
- **Fix**: Now copies only the cancellation event file (`*_CANC.xml`) directly to the root of `CANCELLED_COPY_BASE_PATH`, without creating company subfolders or copying the original XML.
- **Impact**: Ensures consistent behavior across both file managers and clean data structure for BI integration.

**3. Improved Timeout Handling and Added Circuit Breaker**
- **What changed**: Added more robust timeout handling and a circuit breaker mechanism for problematic companies.
- **Files updated**:
  - `core/api_client.py`: Added `REPORT_REQUEST_TIMEOUT = (10, 20)` for shorter timeouts on report downloads
  - `app/run.py`: Added circuit breaker to skip companies after 3 consecutive failures
  - Enhanced exception handling for socket and request timeouts during previous month processing
- **Why**: The script was hanging when encountering network timeouts, particularly with company 49129329000146 (Via Cargas).
- **Impact**: The system is now more resilient and will continue processing other companies even when one company consistently fails.

**4. Enhanced Logging with Timestamps**
- **What changed**: Added timestamps to critical log messages for better debugging.
- **Why**: To track exact duration of operations that timeout or fail.
- **Impact**: Easier to diagnose timeout issues and performance bottlenecks.

### 2025-07-31: Script Resiliency and Business Logic Fixes

**1. Fixed Script Halting on Report Download Failure**
- **What changed**: Added robust error handling to the `baixar_relatorio_xml` method in `core/api_client.py`.
- **Why**: The script was crashing completely when the API failed to return a report after multiple retries, instead of logging the error and continuing.
- **Fix**: The method now catches network exceptions (`RequestException`), logs the error, and returns a failure dictionary. This prevents the exception from stopping the main loop in `app/run.py`.
- **Impact**: The script is now more resilient and will continue processing other companies/tasks even if one report download fails.

**2. Corrected Cancellation Event Storage Logic**
- **What changed**: Rewrote the save logic for `CANCELLED_COPY_BASE_PATH` in `core/file_manager.py`.
- **Why**: A previous change to simplify cancellation storage was not fully implemented, causing the system to still save original documents and create unnecessary company subfolders.
- **Fix**: The code now correctly copies **only** the cancellation event file (`*_CANC.xml`) directly to the root of the `Cancelados` directory, without the original XML or extra folders.
- **Impact**: Aligns the system's behavior with the documented business requirements, ensuring clean data for BI integration.

### 2025-08-04: Fixed Timeout Protection Implementation (Complete Fix)

**1. Fixed TimeoutError Exception Handling - First Attempt**
- **What changed**: Changed `baixar_relatorio_xml` to re-raise TimeoutError instead of converting to error dictionary
- **Files updated**:
  - `app/run.py`: Added specific TimeoutError handling in 4 locations
- **Issue discovered**: TimeoutError was still being caught by `except Exception` blocks before propagating

**2. Complete Fix - Corrected Exception Order**
- **What changed**: Added `except TimeoutError:` blocks BEFORE `except Exception:` blocks
- **Files updated**:
  - `core/api_client.py`: 
    - Method `baixar_relatorio_xml` (line ~565): Added `except TimeoutError:` that re-raises
    - Method `_baixar_xml_especifico_internal` (line ~366): Added `except TimeoutError:` that re-raises
- **Why**: The `except Exception:` blocks were catching TimeoutError before it could propagate to the specific handlers
- **Fix Details**:
  - TimeoutError is now explicitly caught and re-raised before any generic Exception handlers
  - This ensures TimeoutError propagates correctly through the call stack
  - The timeout blacklist mechanism in `run.py` can now properly detect and handle timeouts
- **Impact**: 
  - The script will now properly detect timeouts at 45 seconds
  - Logs will show "TIMEOUT ABSOLUTO" instead of "Erro inesperado"
  - Companies causing timeouts are added to blacklist for 1 hour
  - Script continues processing other companies without hanging

**3. Enhanced Timeout Logging**
- **What changed**: Added detailed timing logs to the `_execute_with_absolute_timeout` method
- **Why**: To help diagnose timeout issues and verify the protection is working
- **Impact**: Better visibility into when and why timeouts occur

### 2025-08-04: Added File I/O Timeout Protection

**1. Problem Identified**
- **Issue**: Script was hanging when saving reports to network drives (e.g., F:\\ drive)
- **Example**: Company "COOPERATIVA_DE_TRANSPORTES_DE_CARGAS_QUIMICAS_E_CORROSIVAS_DE_MAUA" caused script to freeze
- **Root cause**: File I/O operations can hang indefinitely on network drives, similar to API timeouts

**2. Solution Implemented**
- **Files updated**:
  - `core/file_manager.py`: 
    - Added `FILE_OPERATION_TIMEOUT = 30` seconds constant
    - Added `MAX_PATH_LENGTH = 240` for Windows path limit
    - Created `_execute_file_operation_with_timeout()` helper function
    - Modified `save_report_from_base64()` to use timeout protection
  - `app/run.py`:
    - Added TimeoutError handling when calling `save_report_from_base64()`
- **Features**:
  - 30-second timeout for all file save operations
  - Automatic path shortening for paths > 240 characters
  - Cleanup of partial files on timeout
  - Script continues processing after file I/O timeout

**3. Impact**
- Script no longer hangs on network drive issues
- Long company names are automatically shortened if needed
- Better resilience for both API and file operations

### 2025-08-04: Sistema de Relatórios Temporários e Melhorias de Fuzzy Matching

**1. Implementação do Sistema de Relatórios Temporários**
- **Problema**: Conflitos de arquivo quando usuários abrem Excel manualmente durante processamento
- **Solução**: Download → Processamento em pasta temporária → Cópia para destino final
- **Localização temporária**: `%LOCALAPPDATA%\XMLDownloaderSieg\temp_reports\`
- **Arquivos alterados**:
  - `app/run.py`: Adicionado TEMP_REPORTS_DIR e função `copy_report_to_final_destination`
  - `core/api_client.py`: Modificado para salvar relatórios em pasta temporária
- **Benefícios**: Elimina travamentos causados por arquivos Excel abertos manualmente

**2. Script de Processamento de Empresas Prioritárias**
- **Arquivo criado**: `processar_empresas_prioritarias_v2.py`
- **Funcionalidade**: Filtra e processa apenas empresas específicas da lista prioritária
- **Recursos**:
  - Normalização agressiva de nomes (remove acentos, prefixos numéricos, tipos sociais)
  - Fuzzy matching com rapidfuzz (score mínimo 90%)
  - Suporte a diferentes formatos de nomes no Excel
  - Geração de Excel temporário filtrado
- **Batch file**: `processar_prioritarias.bat` para execução simplificada

**3. Melhorias de Matching com Fuzzy Logic**
- **Dependências adicionadas**: `unidecode`, `rapidfuzz`
- **Função `normaliza()`**: Padronização agressiva de texto
  - Remove acentos (á→a, ç→c)
  - Remove prefixos numéricos (0001_, 0237-)
  - Remove tipos sociais (LTDA, S/A, ME, EIRELI)
  - Limpa caracteres especiais
- **Função `eh_match()`**: Comparação com token_set_ratio (ignora ordem das palavras)
- **Resultado**: Aumento de ~49 para ~115 empresas encontradas (135% de melhoria)

**4. Lista de Empresas Prioritárias Atualizada**
- **Total**: 95 empresas específicas para reprocessamento
- **Origem**: Empresas que tiveram problemas durante travamentos anteriores
- **Formato**: Nomes normalizados para melhor matching

**5. Organização de Arquivos de Teste**
- **Pasta criada**: `testes_temporarios/`
- **Conteúdo**: Todos arquivos de teste, correções e validação
- **Finalidade**: Isolamento para futura exclusão após implementação

**Arquivos Principais Adicionados:**
- `processar_empresas_prioritarias_v2.py` - Script principal de processamento prioritário
- `processar_prioritarias.bat` - Executor batch simplificado
- `testes_temporarios/` - Pasta com arquivos temporários de teste

**Arquivos Modificados:**
- `app/run.py` - Sistema de relatórios temporários
- `core/api_client.py` - Salvamento em pasta temporária
- `CLAUDE.md` - Documentação atualizada

### 2025-08-19: Correção Final - XMLs "Órfãos" do Skip Count

**PROBLEMA DESCOBERTO: XMLs Pulados Nunca Marcados**

**Por Que Acontecia:**
- Quando `skip_count=10`, sistema pulava XMLs 1-10 (já baixados antes)
- Baixava apenas XMLs 11-100 (novos)
- **BUG**: XMLs 1-10 nunca eram marcados em `processed_xml_keys`
- **RESULTADO**: Re-cópia eterna dos XMLs 1-10 para pasta Import

**Solução Implementada (19/08):**
- **Arquivo**: `app/run.py` (após linha 1178)
- **Lógica**: Detecta XMLs locais que existem mas não estão marcados
- **Ação**: Marca retroativamente como importados
- **Log**: "CORREÇÃO: Marcados X XMLs existentes como importados"

**Ciclo de Vida:**
- **Primeira execução**: Corrige XMLs "órfãos" (remédio único)
- **Próximas execuções**: Sistema funciona normalmente
- **XMLs novos**: Baixados e marcados corretamente

**Resultados Validados (19/08 11:32-11:41):**
- 4 empresas processadas
- 56 XMLs corrigidos retroativamente
- `flat_copy_success: 0` na maioria (correto!)

### 2025-08-19: Melhorias de Logging para Task Scheduler

**PROBLEMA: Logs Incompletos nos Arquivos**

**Por Que Acontecia:**
- Logs de empresa configurados com `level="INFO"`
- Código usava `logger.debug()` para mensagens importantes
- **RESULTADO**: Informações críticas só no console, não nos arquivos

**Soluções:**
- `file_manager.py`: Mudado `logger.debug()` → `logger.info()`
- `file_manager_transactional.py`: Adicionadas estatísticas detalhadas
- `run.py`: Logs de correção com exemplos específicos
- `report_manager.py`: Nova seção "CORREÇÃO RETROATIVA"

**Benefícios:**
- Debugging completo via Task Scheduler
- Transparência total do processamento
- Relatórios de auditoria com correções

### 2025-08-18: Correção do Bug de Formato Month Key

**1. Bug Crítico Descoberto: Format Mismatch no Month Key**
- **Root Cause**: State.json salvava `"08-2025"` mas código buscava `"2025-08"`
- **Descoberta**: Via análise de 5.241 XMLs duplicados da Via Cargas
- **Files Updated**:
  - `core/file_manager_transactional.py` (linha 190)
  - `core/file_manager.py` (linha 819)
- **Correção**: `month_key = f"{mes_emi:02d}-{ano_emi:04d}"` # Formato MM-YYYY
- **Impacto Resolvido**: XMLs não são mais re-copiados para `\\172.16.1.254\xml_import\Import`

**2. Correção do Contador flat_copy_success (Valor Enganoso)**
- **Problema**: Mostrava `flat_copy_success: 2` mesmo quando pulava todos XMLs
- **Files Updated**:
  - `core/file_manager_transactional.py` (linhas 273-275)
  - `core/file_manager.py` (linha 843 - já estava correto)
- **Correção**: Só incrementa quando `flat_path in target_paths`
- **Resultado**: Agora mostra `0` quando XMLs são detectados como já importados

**3. Logs Completos para Task Scheduler**
- **Problema**: Logs de debug só apareciam no console, não no arquivo .txt
- **Files Updated**:
  - `core/file_manager.py` (linhas 822-827): Adicionado controle de duplicação ativo
  - `core/file_manager_transactional.py` (linhas 194-199): Logs de debug
- **Mudanças**:
  - Removido: `print()` statements e `logger.warning("[DEBUG]")`
  - Adicionado: `logger.info()` para todas mensagens importantes
  - Novo: "Controle duplicação: X/Y XMLs já importados (pulados)"
- **Benefício**: Debugging completo via Task Scheduler sem acesso ao console

**4. Descobertas Técnicas Importantes**
- **Sistema Dual de File Managers**:
  - FileManager: Operações normais de salvamento
  - TransactionalFileManager: Operações atômicas em produção
  - Ambos agora com controle idêntico de duplicação
- **Skip Count vs Processed Keys**:
  - skip_count: Controla paginação da API (posição de download)
  - processed_xml_keys: Controla importação para BI (previne duplicatas)
  - São independentes e complementares
- **Persistência em Modo Loop**:
  - Estado salvo após cada empresa, não apenas no final
  - Seguro mesmo com interrupções

**5. Validação com Dados Reais**
- **Paulicon (59957415000109)**:
  - 4 NFes já no sistema desde 13/08
  - Sistema detectou e pulou corretamente
  - Log: "Controle duplicação: 2/2 XMLs já importados"
  - flat_copy_success: 0 (correto!)
- **Via Cargas (49129329000146)**:
  - 5.241 XMLs que estavam sendo duplicados
  - Todos agora detectados e pulados
  - Performance: 90%+ redução no tráfego de rede

**6. Impacto em Produção**
- **Performance**: Eliminação de milhares de cópias desnecessárias
- **Confiabilidade**: Garantia de não duplicação via state.json
- **Visibilidade**: Logs completos em arquivos para monitoramento remoto
- **Economia**: Redução significativa de I/O de rede e disco

**Documentação Completa**: 
- `/docs/RESUMO_EXECUTIVO_MUDANCAS_2025_08_19.md` - Resumo executivo com o "PORQUÊ"
- `/docs/correcao-skip-count-marking-2025-08-19.md` - Detalhes técnicos da correção
- `/docs/correcao-duplicacao-import-completa.md` - Histórico completo

**IMPORTANTE**: Todas as correções são complementares e necessárias. O problema de duplicação tinha 3 causas encadeadas que foram resolvidas em sequência.

*Last updated: 2025-08-19 | Complete technical documentation available in `/docs`*


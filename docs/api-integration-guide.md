# Guia de Integração com API SIEG

## 📋 Índice

1. [Visão Geral da API](#visão-geral-da-api)
2. [Autenticação e Configuração](#autenticação-e-configuração)
3. [Rate Limiting e Retry Strategy](#rate-limiting-e-retry-strategy)
4. [Endpoints Principais](#endpoints-principais)
5. [Tratamento de Respostas](#tratamento-de-respostas)
6. [Padrões de Erro](#padrões-de-erro)
7. [Boas Práticas](#boas-práticas)
8. [Troubleshooting](#troubleshooting)

---

## 🌐 Visão Geral da API

### Informações Básicas
- **Base URL**: `https://api.sieg.com`
- **Protocolo**: HTTPS REST API
- **Formato**: JSON request/response
- **Autenticação**: API Key via query parameter
- **Rate Limit**: 30 requests/minuto (auto-imposto)
- **Timeout**: 30 segundos por request

### Arquitetura do Client
```python
# Estrutura base do SiegApiClient
class SiegApiClient:
    BASE_URL = "https://api.sieg.com"
    REQUEST_TIMEOUT = 30  # segundos
    RATE_LIMIT_DELAY = 2  # segundos entre requests
    RETRY_COUNT = 3       # tentativas por request
```

---

## 🔐 Autenticação e Configuração

### API Key Management
```python
def __init__(self, api_key: str):
    # API Key é URL-decodificada automaticamente
    self.api_key = unquote(api_key)
    
    # Log seguro (apenas primeiros/últimos 4 dígitos)
    logger.debug(f"API Key configurada: {self.api_key[:4]}...{self.api_key[-4:]}")
```

### Headers Padrão
```python
headers = {
    "Content-Type": "application/json",
    "Accept": "application/json"
}

# API Key enviada como query parameter
params = {"api_key": self.api_key}
```

### Session Configuration
```python
def _create_session(self) -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=self.RETRY_COUNT,          # 3 tentativas
        backoff_factor=1,                # 1s, 2s, 4s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=["POST", "GET"],  # Retry em POST também
        raise_on_status=False            # Controle manual de erros
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session
```

---

## ⏱️ Rate Limiting e Retry Strategy

### Rate Limiting Inteligente
```python
def _enforce_rate_limit(self):
    """Garante intervalo mínimo de 2s entre requests"""
    now = time.monotonic()
    elapsed = now - self._last_request_time
    wait_time = self.RATE_LIMIT_DELAY - elapsed
    
    if wait_time > 0:
        logger.debug(f"Rate limit: esperando {wait_time:.2f} segundos")
        time.sleep(wait_time)
    
    self._last_request_time = time.monotonic()
```

### Retry Strategy
- **Tentativas**: 3 attempts com exponential backoff
- **Backoff Factor**: 1 segundo (1s → 2s → 4s)
- **Status Codes para Retry**:
  - `429` - Too Many Requests
  - `500` - Internal Server Error
  - `502` - Bad Gateway
  - `503` - Service Unavailable
  - `504` - Gateway Timeout

### Tratamento de 429 (Rate Limit)
```python
if response.status_code == 429:
    logger.error(f"Rate limit persistente após {self.RETRY_COUNT} tentativas")
    # Sistema aguarda header Retry-After quando presente
    # Fallback para backoff exponential
```

### Proteção Contra Timeout (Novo - 2025-08-03)
```python
# Timeout absoluto via ThreadPoolExecutor
ABSOLUTE_TIMEOUT = 45  # segundos

def _execute_with_absolute_timeout(self, func, *args, timeout_seconds=45):
    """Executa função com timeout absoluto para evitar travamentos."""
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(func, *args)
    try:
        return future.result(timeout=timeout_seconds)
    except FuturesTimeoutError:
        future.cancel()  # Abandona thread travada
        raise TimeoutError(f"Operação abortada após {timeout_seconds} segundos")
```

---

## 🔌 Endpoints Principais

### 1. **Relatórios Consolidados** - `/api/relatorio/xml`

**Objetivo**: Baixar planilhas Excel com chaves de documentos por empresa/mês

```python
def baixar_relatorio_xml(self, cnpj: str, xml_type: int, month: int, year: int, report_type: str) -> Dict[str, Any]:
    """
    Baixa relatório consolidado (Excel) de uma empresa.
    
    Args:
        cnpj: CNPJ normalizado (apenas números)
        xml_type: 1=NFe, 2=CTe
        month: Mês (1-12)
        year: Ano (ex: 2024)
        report_type: Sempre "RelatorioXML"
    
    Returns:
        {
            "RelatorioBase64": "UEsDBBQABg...",  # ou None
            "EmptyReport": False                  # ou True
        }
    """
```

**Tratamento de Respostas Especial**:
```python
# Caso 1: API retorna string exata (sem dados)
if response_text.strip().lower() == "nenhum arquivo xml encontrado":
    return {"RelatorioBase64": None, "EmptyReport": True}

# Caso 2: Resposta muito curta (erro inesperado)
if len(response_text) < MIN_BASE64_LEN:  # MIN_BASE64_LEN = 200
    return {
        "RelatorioBase64": None, 
        "EmptyReport": False, 
        "ErrorMessage": "Resposta inesperada/curta"
    }

# Caso 3: String longa (Base64 válido)
return {"RelatorioBase64": response_text, "EmptyReport": False}
```

### 2. **Download de XMLs em Lote** - `/BaixarXmls`

**Objetivo**: Baixar até 50 XMLs individuais por request

```python
def baixar_xmls_empresa_lote(
    self, 
    cnpj_empresa: str, 
    xml_type: int, 
    skip: int, 
    take: int,
    data_inicio: str, 
    data_fim: str, 
    cnpj_filtro: str, 
    papel: str,
    download_eventos: bool = False
) -> List[str]:
    """
    Args:
        cnpj_empresa: CNPJ da empresa (context)
        xml_type: 1=NFe, 2=CTe
        skip: Quantos documentos pular (pagination)
        take: Quantos documentos buscar (max 50)
        data_inicio: "YYYY-MM-DD"
        data_fim: "YYYY-MM-DD"  
        cnpj_filtro: CNPJ para filtrar por papel
        papel: "Emitente", "Destinatario", "Tomador"
        download_eventos: Se True, inclui eventos relacionados
        
    Returns:
        Lista de XMLs em Base64
    """
```

**Payload Example**:
```json
{
    "XmlType": 1,
    "Skip": 0,
    "Take": 50,
    "DataInicio": "2024-05-01",
    "DataFim": "2024-05-31",
    "CnpjEmit": "12345678000199",  // se papel = "Emitente"
    "CnpjDest": "",                // se papel = "Destinatario" 
    "CnpjTom": "",                 // se papel = "Tomador"
    "DownloadEventos": false
}
```

### 3. **Download XML Específico** - `/BaixarXml`

**Objetivo**: Baixar um XML individual por chave

```python
def baixar_xml_especifico(self, xml_key: str, xml_type: int, download_event: bool = False) -> str | bytes | None:
    """
    Args:
        xml_key: Chave de acesso (44 dígitos)
        xml_type: 1=NFe, 2=CTe
        download_event: Se True, baixa eventos relacionados
        
    Returns:
        Conteúdo XML bruto ou None em caso de erro
    """
```

**Fallback Automático**:
```python
# Primeira tentativa com eventos
result = self._baixar_xml_especifico_internal(xml_key, xml_type, download_event=True)

# Se falhar, tenta sem eventos
if result is None and download_event:
    logger.warning(f"Tentando fallback SEM eventos para {xml_key}")
    result = self._baixar_xml_especifico_internal(xml_key, xml_type, download_event=False)
```

### 4. **Download de Eventos** - `/BaixarEventos`

**Objetivo**: Baixar eventos de cancelamento/correção

```python
def baixar_eventos_empresa_lote(
    self, 
    cnpj_empresa: str, 
    tipo_documento: int,
    data_inicio: str, 
    data_fim: str, 
    skip: int = 0, 
    take: int = 50
) -> List[str]:
    """
    Args:
        cnpj_empresa: CNPJ da empresa
        tipo_documento: 1=NFe, 2=CTe
        data_inicio/data_fim: Range de datas
        skip/take: Paginação
        
    Returns:
        Lista de eventos XML em Base64
    """
```

### 5. **Contagem de Documentos** - `/ContarXmls`

**Objetivo**: Contar documentos antes de baixar (otimização)

```python
def contar_xmls(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns:
        {"Total": 150}  # Quantidade de documentos
    """
```

---

## 📤 Tratamento de Respostas

### Padrões de Resposta da API

#### **1. Sucesso com Dados**
```json
// Para /BaixarXmls
["UEsDBBQABg...", "UEsDBBQABg...", "UEsDBBQABg..."]

// Para /ContarXmls  
{"Total": 150}

// Para /api/relatorio/xml (Base64 do Excel)
"UEsDBBQABgAA...muito.longo...AAAg="
```

#### **2. Sucesso Sem Dados**
```python
# Resposta textual exata da API
"Nenhum arquivo xml encontrado"

# Tratamento interno
return {"RelatorioBase64": None, "EmptyReport": True}
```

#### **3. Erro da API SIEG**
```json
{
    "Status": ["Erro específico da SIEG", "Detalhes adicionais"]
}
```

#### **4. Resposta Inesperada**
```python
# String muito curta (< 200 chars) que não é mensagem "sem dados"
return {
    "RelatorioBase64": None, 
    "EmptyReport": False, 
    "ErrorMessage": "Resposta inesperada/curta"
}
```

### Tratamento Robusto de JSON/String

```python
# Resposta pode ser JSON ou string pura
if isinstance(response_data, str):
    logger.warning("Resposta foi string, tentando parsear como JSON...")
    try:
        response_data = json.loads(response_data)
    except json.JSONDecodeError:
        logger.error("Falha ao parsear string como JSON")
        return []

# Validação de tipo esperado
if isinstance(response_data, list):
    if all(isinstance(item, str) for item in response_data):
        return response_data  # Lista válida de Base64
    else:
        logger.error("Lista contém itens não-string")
        return []
```

---

## ⚠️ Padrões de Erro

### Hierarquia de Tratamento

```python
def _make_request(self, endpoint: str, payload: Optional[Dict[str, Any]] = None) -> Any:
    try:
        response = self.session.post(url, json=payload, ...)
        
        # 1. Verificar rate limit persistente
        if response.status_code == 429:
            logger.error("Rate limit persistente após retries")
            
        # 2. Tentar decodificar JSON
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            # 3. Não é JSON - erro HTTP
            response.raise_for_status()
            raise ValueError("Resposta não-JSON inesperada")
            
        # 4. Verificar erro da API SIEG
        if isinstance(response_data, dict) and "Status" in response_data:
            status_messages = response_data.get("Status")
            if isinstance(status_messages, list) and status_messages:
                error_message = ", ".join(status_messages)
                raise ValueError(f"Erro da API SIEG: {error_message}")
                
        return response_data
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro de rede: {e}")
        raise
```

### Códigos de Status Comuns

| Status | Significado | Ação |
|--------|-------------|------|
| `200` | Sucesso | Processar resposta |
| `400` | Bad Request | Verificar payload |
| `401` | Unauthorized | Verificar API Key |
| `429` | Too Many Requests | Aguardar + retry |
| `500` | Server Error | Retry automático |
| `502/503/504` | Gateway/Service Error | Retry automático |

---

## 🎯 Boas Práticas

### 1. **Rate Limiting Cooperativo**
```python
# ✅ BOM: Respeitar limits auto-impostos
self._enforce_rate_limit()  # 2s entre requests

# ❌ RUIM: Fazer requests sem delay
requests.post(url, data=payload)  # Pode causar 429
```

### 2. **Retry com Exponential Backoff**
```python
# ✅ BOM: Usar session com retry configurado
session = requests.Session()
session.mount("https://", HTTPAdapter(max_retries=retries))

# ❌ RUIM: Retry linear sem delay
for i in range(3):
    response = requests.post(url)
    if response.status_code == 200:
        break
```

### 3. **Tratamento Defensivo de Tipos**
```python
# ✅ BOM: Verificar tipo antes de usar
if isinstance(response_data, list):
    return response_data
else:
    logger.error(f"Tipo inesperado: {type(response_data)}")
    return []

# ❌ RUIM: Assumir tipo
return response_data  # Pode quebrar se não for lista
```

### 4. **Logging Estruturado**
```python
# ✅ BOM: Log com contexto
logger.info(f"Baixando {take} XMLs para {cnpj} (skip={skip})")

# ✅ BOM: Log seguro de API key
logger.debug(f"API Key: {api_key[:4]}...{api_key[-4:]}")

# ❌ RUIM: Log da API key completa
logger.debug(f"API Key: {api_key}")  # Expõe credencial
```

### 5. **Validação de Input**
```python
# ✅ BOM: Validar parâmetros críticos
if not cnpj or len(cnpj) != 14:
    raise ValueError("CNPJ deve ter 14 dígitos")

if xml_type not in [1, 2]:
    raise ValueError("xml_type deve ser 1 (NFe) ou 2 (CTe)")

# ✅ BOM: Normalizar CNPJs
cnpj = normalize_cnpj(cnpj_raw)  # Remove formatação
```

---

## 🔧 Troubleshooting

### Problemas Comuns

#### **1. Rate Limit (429)**
```bash
# Sintoma
ERROR: Rate limit persistente após 3 tentativas

# Diagnóstico
- Verificar se RATE_LIMIT_DELAY = 2 segundos
- Confirmar se _enforce_rate_limit() está sendo chamado
- Monitorar timestamps entre requests

# Solução
- Aumentar RATE_LIMIT_DELAY para 3-5 segundos
- Implementar jitter aleatório no delay
- Verificar se múltiplas instâncias estão rodando
```

#### **2. Timeout Requests**
```bash
# Sintoma  
ERROR: Timeout após 30 segundos

# Diagnóstico
- Verificar latência de rede para api.sieg.com
- Confirmar se REQUEST_TIMEOUT = 30 é suficiente
- Verificar tamanho dos payloads (relatórios grandes)

# Solução
- Aumentar REQUEST_TIMEOUT para 60-90 segundos
- Implementar downloads em chunks menores
- Verificar conectividade de rede
```

#### **3. JSON Decode Errors**
```bash
# Sintoma
ERROR: Expecting value: line 1 column 1 (char 0)

# Diagnóstico  
- API pode estar retornando HTML de erro
- Response pode estar vazio
- Content-Type pode não ser application/json

# Solução
- Logar response.text para debug
- Verificar response.headers['Content-Type']
- Implementar fallback para HTML errors
```

#### **4. Empty/Invalid Base64**
```bash
# Sintoma
ERROR: Invalid base64-encoded string

# Diagnóstico
- Base64 pode estar truncado
- Encoding issues (UTF-8 vs Latin-1)
- API pode estar retornando placeholder

# Solução
- Validar tamanho mínimo (MIN_BASE64_LEN = 200)
- Implementar base64.b64decode() com validação
- Logar primeiros/últimos chars do Base64
```

### Ferramentas de Debug

#### **1. Network Monitoring**
```bash
# Wireshark para capturar tráfego HTTP
wireshark -i any -f "host api.sieg.com"

# Curl para testar endpoints manualmente
curl -X POST "https://api.sieg.com/BaixarXmls" \
     -H "Content-Type: application/json" \
     -d '{"XmlType":1,"Take":1}'
```

#### **2. Logging Granular**
```python
# Habilitar logs de requests/urllib3
import logging
logging.getLogger("requests.packages.urllib3").setLevel(logging.DEBUG)
logging.getLogger("urllib3.connectionpool").setLevel(logging.DEBUG)

# Log customizado por endpoint
logger.info(f"[SIEG-API] {endpoint} | Status: {response.status_code} | "
           f"Size: {len(response.content)} bytes | Time: {elapsed:.2f}s")
```

#### **3. Response Validation**
```python
def validate_base64_response(base64_string: str) -> bool:
    """Valida se string é Base64 válido"""
    try:
        if len(base64_string) < MIN_BASE64_LEN:
            return False
        base64.b64decode(base64_string)
        return True
    except Exception:
        return False
```

### Monitoring e Alertas

#### **Métricas Importantes**
- **Request Rate**: Não exceder 30 req/min
- **Success Rate**: > 95% para operações normais  
- **Response Time**: < 10s para requests típicos
- **Retry Rate**: < 5% dos requests precisando retry
- **Error Rate**: < 1% de erros não recuperáveis

#### **Alertas Críticos**
```python
# Rate limit violations
if response.status_code == 429:
    alert_manager.send_alert("SIEG API Rate Limit Exceeded")

# High error rate
error_rate = failed_requests / total_requests
if error_rate > 0.05:  # > 5%
    alert_manager.send_alert("SIEG API High Error Rate")

# API Key issues
if response.status_code == 401:
    alert_manager.send_critical_alert("SIEG API Authentication Failed")
```

---

## 📚 Referências Técnicas

### Configurações de Retry
```python
DEFAULT_RETRY_CONFIG = Retry(
    total=3,                    # 3 tentativas total
    backoff_factor=1,           # 1s, 2s, 4s delays
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=["POST", "GET"],
    raise_on_status=False       # Controle manual
)
```

### Rate Limiting Parameters
```python
RATE_LIMIT_CONFIG = {
    "delay": 2,                 # Segundos entre requests
    "burst_limit": 5,           # Requests em rajada permitidos  
    "window": 60,               # Janela de tempo (segundos)
    "max_per_window": 30        # Max requests por janela
}
```

### Timeout Configuration
```python
TIMEOUT_CONFIG = {
    "connect": 10,              # Tempo para estabelecer conexão
    "read": 30,                 # Tempo para ler response
    "total": 45                 # Timeout total do request
}
```

---

*Documentação gerada baseada na análise do código fonte `core/api_client.py`*
*Última atualização: 2025-07-22*
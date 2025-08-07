# Sistema XML SIEG

Sistema automatizado para download e organização de documentos fiscais XML (NFe/CTe) da API SIEG, com logs estruturados e estado modular.

## 🎯 Funcionalidades Principais

- ✅ **Download Incremental** com skip counts para evitar redownloads
- ✅ **Recuperação Automática** através do sistema de pendências
- ✅ **Logs Estruturados** por mês e empresa para debugging facilitado
- ✅ **Estado Modular** organizando dados por período temporal
- ✅ **Rate Limiting** respeitando limites da API (30 req/min)
- ✅ **Operação 24/7** via Windows Service
- ✅ **Múltiplos Formatos** (NFe, CTe com diferentes papéis)

## 🚀 Execução Rápida

```bash
# Execução básica
python app/run.py --excel planilha.xlsx --limit 10

# Modo contínuo (produção)
python app/run.py --excel url_sharepoint --loop --pause 3600

# Primeira execução (30 dias de histórico)
python app/run.py --excel planilha.xlsx --seed
```

## 📁 Estrutura de Arquivos

### **Core do Sistema**
```
app/run.py                     # Orquestrador principal
core/
├── api_client.py              # Cliente API SIEG + rate limiting
├── state_manager_v2.py        # Gerenciador de estado modular
├── file_manager.py            # Organização hierárquica de arquivos
├── xml_downloader.py          # Download em lote de XMLs
└── [outros módulos...]
```

### **Dados Organizados**
```
logs/                          # 📁 Logs estruturados por mês/empresa
├── MM-YYYY/
│   ├── sistema.log           # Log geral do mês
│   └── EMPRESA_NOME/
│       └── empresa.log       # Log específico da empresa

estado/                        # 📂 Estados modulares por mês
├── MM-YYYY/
│   └── state.json           # Estado de cada mês
└── metadata.json            # Metadata global

XMLs/                          # 🗂️ Estrutura hierárquica de XMLs
└── YYYY/
    └── CODIGO_EMPRESA_NOME/
        └── MM/
            ├── NFe/
            │   ├── Emitente/
            │   ├── Destinatario/
            │   └── xml_files/    # Cópia plana para BI
            └── CTe/
                ├── Emitente/
                ├── Destinatario/
                ├── Tomador/
                └── xml_files/
```

## ⚙️ Configuração

### **Dependências**
```bash
pip install -r requirements.txt
```

### **Variáveis de Ambiente**
- `SIEG_API_KEY`: Chave da API SIEG
- `PRIMARY_SAVE_BASE_PATH`: Caminho base para XMLs (padrão: F:\x_p\XML_CLIENTES)

## 🛠️ Ferramentas de Manutenção

```bash
# Gerenciar estados
gerenciar_estados.bat health        # Verificar saúde
gerenciar_estados.bat cleanup       # Limpar estados antigos
gerenciar_estados.bat report        # Relatório completo

# Analisar gaps temporais
recuperar_gaps.bat analyze          # Analisar gaps
recuperar_gaps.bat plan             # Plano de recuperação
```

## 📊 Monitoramento

### **Logs Estruturados**
- **Sistema**: `logs/MM-YYYY/sistema.log`
- **Por Empresa**: `logs/MM-YYYY/EMPRESA/empresa.log`
- **Formato**: `[CNPJ] | Mensagem específica`

### **Métricas Importantes**
- Taxa de sucesso da API: >95%
- Rate de processamento: ~1,500 XMLs/hora
- Taxa de erro: <1% não-recuperável

## 🔧 Resolução de Problemas

### **Rate Limiting (HTTP 429)**
```python
# Aumentar delay em core/api_client.py
RATE_LIMIT_DELAY = 3  # Aumentar de 2 para 3 segundos
```

### **Verificar Saúde do Sistema**
```bash
# Verificar logs recentes
tail -50 logs/MM-YYYY/sistema.log

# Verificar estados
gerenciar_estados.bat health

# Verificar serviço Windows
Get-Service XMLDownloaderSieg
```

## 🚀 Deploy em Produção

### **Windows Service**
```bash
# Instalar/gerenciar serviço
scripts/gerenciar_servico.bat
```

### **Arquivos Essenciais para Deploy**
```
app/run.py                     # Core principal
core/state_manager_v2.py       # Gerenciador modular  
core/                          # Todos os módulos core
scripts/                       # Scripts de serviço
CLAUDE.md                      # Instruções detalhadas
requirements.txt               # Dependências
```

## 📚 Documentação Completa

- **[CLAUDE.md](CLAUDE.md)** - Instruções detalhadas e arquitetura
- **[docs/](docs/)** - Documentação técnica completa
- **[docs/migracao-logs-state-v2.md](docs/migracao-logs-state-v2.md)** - Detalhes da implementação

## ⚠️ Notas Importantes

- **Rate Limiting**: Nunca reduzir `RATE_LIMIT_DELAY` abaixo de 2 segundos
- **Compatibilidade**: Sistema mantém 100% compatibilidade com versões anteriores
- **Estado**: StateManagerV2 migra automaticamente dados de v1 para v2
- **Logs**: Sistema cria estrutura hierárquica automaticamente

---

*Sistema XML SIEG - Download automatizado de documentos fiscais*  
*Versão: 2.0 com Logs Estruturados + Estado Modular*
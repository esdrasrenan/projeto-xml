# 🏗️ Serviço Windows - XML Downloader SIEG

Solução definitiva para execução **automática e contínua** do script XML com **auto-restart** e **inicialização automática** do Windows.

## 🎯 **O Que Este Serviço Resolve**

✅ **Execução automática** ao iniciar o Windows  
✅ **Auto-restart** em caso de falha ou travamento  
✅ **Execução contínua** 24/7 sem intervenção manual  
✅ **Logs centralizados** para monitoramento  
✅ **Gestão fácil** através de interface amigável  

## 🚀 **Instalação Rápida**

### **1. Pré-requisitos**
- Windows com privilégios de Administrador
- Ambiente virtual Python configurado (`.venv/`)
- Dependências instaladas (`pip install -r requirements.txt`)

### **2. Instalação em 3 Passos**

**Passo 1: Executar como Administrador**
```batch
# Clique com botão direito no PowerShell/CMD
# Escolha "Executar como administrador"
```

**Passo 2: Validar Ambiente**
```batch
cd "C:\caminho\do\projeto\XML-30-04-24"
scripts\gerenciar_servico.bat
# Escolha opção [1] - Validar ambiente
```

**Passo 3: Instalar e Iniciar**
```batch
# No mesmo menu:
# Escolha opção [2] - Instalar serviço Windows
# Escolha opção [3] - Iniciar serviço
```

## 📋 **Interface de Gerenciamento**

Execute `scripts\gerenciar_servico.bat` como **Administrador**:

```
═══════════════════════════════════════════════════════════
        GERENCIADOR DE SERVIÇO XML DOWNLOADER SIEG
═══════════════════════════════════════════════════════════

MENU PRINCIPAL:
[1] Validar ambiente        - Verificar se está tudo OK
[2] Instalar serviço Windows - Criar o serviço  
[3] Iniciar serviço         - Ligar o serviço
[4] Ver status do serviço   - Verificar se está rodando
[5] Parar serviço          - Desligar temporariamente
[6] Remover serviço        - Desinstalar completamente
[0] Sair
```

## 🔧 **Gestão via Linha de Comando**

Para usuários avançados, use diretamente:

```batch
# Validar ambiente
python scripts\xml_service_manager.py validate

# Instalar serviço
python scripts\xml_service_manager.py install

# Iniciar serviço
python scripts\xml_service_manager.py start

# Ver status e logs
python scripts\xml_service_manager.py status

# Parar serviço
python scripts\xml_service_manager.py stop

# Remover serviço
python scripts\xml_service_manager.py remove
```

## 📊 **Monitoramento**

### **Verificar Status**
```batch
scripts\gerenciar_servico.bat
# Opção [4] - Ver status do serviço
```

### **Logs Disponíveis**
- **Logs do serviço**: `logs\service.log`
- **Logs da aplicação**: `logs\global.log` 
- **Logs por execução**: `logs\YYYY_MM_DD_HHMMSS.log`

### **Verificar via Windows**
1. **Serviços Windows**: `services.msc`
2. Procurar: **"XML Downloader SIEG - Paulicon"**
3. Status deve estar: **"Em execução"**

## ⚙️ **Configuração do Serviço**

O serviço é configurado automaticamente com:

- **Nome**: `XMLDownloaderSieg`
- **Inicialização**: Automática com o Windows
- **Recuperação**: Auto-restart em 5s, 10s e 30s após falhas
- **Comando**: Python em modo loop ultra-robusto
- **Parâmetros**: 
  - `--loop` - Execução contínua
  - `--loop-interval 0` - Sem pausas entre ciclos
  - `--ignore-failure-rates` - Nunca para por falhas
  - `--log-level INFO` - Logs informativos

## 🛠️ **Solução de Problemas**

### **Problema: "Execute como Administrador"**
**Solução**: Clicar com botão direito no PowerShell/CMD e escolher "Executar como administrador"

### **Problema: "Ambiente virtual não encontrado"**
**Solução**:
```batch
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### **Problema: Serviço não inicia**
**Verificações**:
1. Validar ambiente: `python scripts\xml_service_manager.py validate`
2. Verificar logs: `logs\service.log`
3. Testar manualmente: `python -m app.run --excel "URL" --loop`

### **Problema: Script continua parando**
**Solução**: O serviço **forçará restart automático**. Verifique logs para causa raiz.

## 🔄 **Comparação: Serviço vs Scripts Anteriores**

| Recurso | Script Manual | `executar_forca_bruta.bat` | **Serviço Windows** |
|---------|---------------|----------------------------|-------------------|
| Auto-restart | ❌ | ✅ | ✅ |
| Inicia com Windows | ❌ | ❌ | ✅ |
| Execução em background | ❌ | ❌ | ✅ |
| Gestão centralizada | ❌ | ❌ | ✅ |
| Logs estruturados | ✅ | ✅ | ✅ |
| Interface amigável | ❌ | ✅ | ✅ |
| Recuperação de falhas | ❌ | ✅ | ✅ **Mais robusta** |

## 📝 **Comandos de Emergência**

### **Parar Serviço Imediatamente**
```batch
sc stop "XMLDownloaderSieg"
```

### **Iniciar Serviço Manualmente**
```batch
sc start "XMLDownloaderSieg"
```

### **Ver Status Rápido**
```batch
sc query "XMLDownloaderSieg"
```

### **Remover em Caso de Problemas**
```batch
sc stop "XMLDownloaderSieg"
sc delete "XMLDownloaderSieg"
```

## 🎉 **Vantagens do Serviço Windows**

1. **🔄 Resistente a falhas**: Auto-restart garantido pelo Windows
2. **🚀 Inicialização automática**: Liga com o Windows automaticamente  
3. **📊 Monitoramento integrado**: Compatível com ferramentas Windows
4. **🛡️ Execução em background**: Não interfere no desktop
5. **⚙️ Configuração persistente**: Mantém configurações entre reinicializações
6. **📈 Escalabilidade**: Preparado para ambientes corporativos

## 🆘 **Suporte**

Em caso de problemas:

1. **Verificar logs**: `logs\service.log` e `logs\global.log`
2. **Validar ambiente**: `python scripts\xml_service_manager.py validate`
3. **Testar manualmente**: Execute o script direto para debug
4. **Reinstalar**: Remover e instalar novamente o serviço

---

## 📞 **Contato para Suporte Técnico**

Para problemas específicos do serviço Windows, verificar:
- Logs em `logs/`
- Event Viewer do Windows (Aplicações e Serviços)
- Executar validação de ambiente antes de reportar problemas 
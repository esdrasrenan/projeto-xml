# 📋 Arquivos para Copiar para Produção

## 🎯 Objetivo
Processar empresas prioritárias que tiveram problemas durante travamentos, utilizando sistema de relatórios temporários e fuzzy matching melhorado.

## 📁 Arquivos Principais (COPIAR PARA PRODUÇÃO)

### Scripts de Processamento Prioritário
```
processar_empresas_prioritarias_v2.py  →  C:\Users\operacional04\Downloads\Projeto-XML\
processar_prioritarias.bat             →  C:\Users\operacional04\Downloads\Projeto-XML\
```

### Arquivos Modificados (SE NECESSÁRIO)
```
app/run.py          →  C:\Users\operacional04\Downloads\Projeto-XML\app\
core/api_client.py  →  C:\Users\operacional04\Downloads\Projeto-XML\core\
CLAUDE.md           →  C:\Users\operacional04\Downloads\Projeto-XML\
```

## 🚀 Como Usar

### 1. Instalação de Dependências (OBRIGATÓRIO)
```bash
cd C:\Users\operacional04\Downloads\Projeto-XML
.venv\Scripts\activate
pip install unidecode rapidfuzz
```

### 2. Execução
```bash
# Opção 1: Usar o batch file (RECOMENDADO)
processar_prioritarias.bat

# Opção 2: Executar diretamente o Python
python processar_empresas_prioritarias_v2.py
```

## 📊 Resultados Esperados

- **95 empresas** na lista prioritária
- **~70-80% de match** esperado (fuzzy matching score ≥90%)
- **Sistema de relatórios temporários** evita travamentos por arquivos abertos
- **Processamento automático** de todas empresas encontradas

## ⚠️ Arquivos para EXCLUIR Após Implementação

### Pasta Temporária (PODE SER EXCLUÍDA)
```
testes_temporarios/  →  DELETAR TODA A PASTA
```

### Arquivos Obsoletos (se existirem)
```
processar_empresas_prioritarias.bat     →  DELETAR
test_temp_reports.py                    →  DELETAR  
test_temp_reports.bat                   →  DELETAR
```

## 🔧 Dependências Necessárias

```
unidecode==1.4.0      # Remove acentos
rapidfuzz==3.13.0     # Fuzzy matching
pandas               # Já instalado
pathlib              # Já instalado
```

## 📈 Melhorias Implementadas

1. **Fuzzy Matching**: De ~49 para ~115 empresas encontradas
2. **Relatórios Temporários**: Evita conflitos de arquivos abertos
3. **Normalização Agressiva**: Remove acentos, prefixos, tipos sociais
4. **Score de Confiança**: Mostra qualidade do match (90-100%)
5. **Lista Atualizada**: 95 empresas específicas que precisam reprocessamento

## 📝 Logs e Monitoramento

- Sistema criará pasta temporária: `%LOCALAPPDATA%\XMLDownloaderSieg\temp_reports\`
- Logs normais em: `logs/`
- Relatórios copiados para destino final após processamento completo

---
*Criado em: 2025-08-04*  
*Versão: 2.0 - Sistema de Relatórios Temporários + Fuzzy Matching*
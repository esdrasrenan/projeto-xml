"""Módulo para constantes de configuração da aplicação."""

# --- Configurações Gerais ---
# (Removido placeholder da API Key, pois ela está hardcoded em app/run.py atualmente)

# --- Configurações de Download e Processamento ---
DIAS_BUSCA_PADRAO = 20 # Usado como default no fluxo antigo, pode ser removido/ajustado
LIMITE_EMPRESAS_TESTE = 3 # Limite para execuções em modo teste

# --- Configurações do Fluxo Incremental ---

# Limite para decidir entre download em lote ou individual
# Se o número de chaves faltantes (diff) for MAIOR que este valor, usa lote com skip.
# Se for MENOR ou IGUAL, usa download individual.
LIMIAR_LOTE = 10

# Janela de tempo (em horas) para execuções recorrentes (modo daemon)
# Define quantas horas voltar no tempo a cada execução. Não usado no fluxo atual.
JANELA_HORAS = 1

# Número de dias para buscar na primeira execução ("seed run")
# Usado para popular o histórico inicial.
DIAS_SEED = 30

# Número de dias para buscar em execuções normais/incrementais ("retry run")
# Deve ser pequeno (ex: 1 ou 2 dias) para pegar documentos recentes/atrasados.
DIAS_RETRY = 2 
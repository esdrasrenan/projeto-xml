"""
Script para processar apenas as empresas prioritárias
Este script lê o Excel principal e processa apenas as empresas da lista prioritária
"""
import sys
import pandas as pd
from pathlib import Path
import logging
import re
from unidecode import unidecode
from rapidfuzz import fuzz

# Regex para tipos sociais
TIPOS_SOCIAIS = r'\b(LTDA|EIRELI|ME|S\/?A|SA)\b'

def normaliza(txt: str) -> str:
    """
    Normalização agressiva de texto para matching:
    - Remove acentos
    - Remove prefixo numérico (0001_, 0237-)
    - Remove tipos sociais (LTDA, S/A, ME, etc.)
    - Remove caracteres especiais
    - Padroniza espaços
    """
    if not isinstance(txt, str):
        return ''
    txt = unidecode(txt.upper())           # tira acentos
    txt = re.sub(r'^\d+\s*[-_ ]\s*', '', txt)  # corta prefixo 0001- ou 0001_
    txt = re.sub(TIPOS_SOCIAIS, ' ', txt)  # remove LTDA, S/A, ME…
    txt = re.sub(r'[^A-Z0-9 ]', ' ', txt)  # só letra, número, espaço
    return ' '.join(txt.split())           # espaços simples

def eh_match(nome_excel, nome_alvo, limite=90):
    """
    Verifica se dois nomes são similares usando fuzzy matching
    token_set_ratio ignora ordem das palavras e palavras extras
    """
    return fuzz.token_set_ratio(nome_excel, nome_alvo) >= limite

# Lista de empresas prioritárias (nova lista fornecida pelo usuário)
EMPRESAS_PRIORITARIAS = [
    'COLEGIO_EDUCARE_LTDA',
    'INTERATIVA_COMUNICACAO_E_MARKETING_LTDA',
    'ENGEMETAL_CONSTRUCOES_E_MONTAGENS_LTDA',
    'DCAN_TRANSPORTES_LTDA',
    'DELTAPORT_TRANSPORTES_LTDA',
    'GPS_TRANSPORTES_E_LOGISTICA_S_A',
    'GREEN_ROAD_SOLUCOES_LOGISTICAS_LTDA',
    'PAULICON_ORGANIZACIONAL_LTDA',
    'CITA_-_COOP_INTERMODAL_DE_TRANSPORTADORES_AUTONOMOS',
    'PANMACHINE_COMERCIO_IMPORTACAO_E_EXPORTACAO_LTDA',
    'CAMPOI_E_TANI_SOCIEDADE_DE_ADVOGADOS',
    'PIQUETUR_LOG_LOGISTICA_E_TRANSPORTE_LTDA',
    'TRANSPORTES_RODO_ALVES_LTDA',
    'ATA_EXPRESS_LOGISTICA_LTDA',
    'NAIRA_COMERCIO_DE_EMBALAGENS_E_MATERIAIS_PLASTICOS_LTDA',
    'ABY_EMPREENDIMENTOSINVESTIMENTOS_E_PARTICIPACOES_LTDA',
    'TECNOLOG_TRANSP.RODO_AEREO_E_LOGIST.LTDA',
    'T.H.S._TRANSPORTE_E_LOGISTICA_LTDA',
    'TECNOLOG_TRANSPORTE_RODO-AEREO_E_LOGISTICA_LTDA',
    'TECNOLOG_TRANSPORTE_RODO-AEREO_E_LOG.LTDA',
    'TECNOLOG_TRANSP.RODO-AEREO_E_LOG.LTDA',
    'JAT_TRANSPORTES_E_LOGISTICA_S.A',
    'TRANSPORTES_MONALIZA_LTDA',
    'WEBTRAC_SOLUCOES_EM_RASTREAMENTO_LTDA',
    'FANTIPER_EMPREENDIMENTOS_E_PARTICIPACOES_LTDA',
    'COOPERSEMO_COOPERATIVA_DE_SERVICOS_DE_TRANSPORTES',
    'TRANSPORTES_EMECE_LTDA',
    'LIVIERO_TRANSPORTES_E_SERVICOS_LTDA',
    'COOPERESTRADA_COOP.TRANSP.E_LOGIST',
    'BT_LOGISTICA_INTEGRADA_LTDA',
    'AFT_CARGO_TRANSPORTE_E_DISTRIB_LTDA',
    'TRANSPORTES_DALLAPRIA_LTDA',
    'LAOLETA_AGENCIA_DE_VIAGENS_E_TURISMO_LTDA',
    'TECNOLOG_TRANSP.RODO-AEREO_E_LOGISTICA_LTDA',
    'TAP_TRANSPORTADORA_AUTOMOTIVA_PAULISTANA_LTDA',
    'SP_LOC_LOCACOES_LTDA',
    'TRANSPORTE_E_LOGISTICA_SAO_JUDAS_TADEU_LTDA',
    'FULL_TRIP_SERVICOS_ADMINISTRATIVOS_LTDA',
    'CITA_TRANSPORTES_LTDA',
    'TRANSPORTADORA_ASTRA_LTDA',
    'COOPERATIVA_DOS_TRANSPORTADORES_DE_VEICULOS_E_DE_CARGAS_EM_GERAL',
    'MR_CUNHA_TRANSPORTES_LTDA',
    'BACCARELLI_GUINCHOS_E_SERVICOS_LTDA',
    'TRANS_NEW_ABC_TRANSPORTADORA_LTDA',
    'TRANSMONALIZA_TRANSPORTES_LTDA',
    'PAN_METAL_INDUSTRIA_METALURGICA_LTDA',
    'BBTL_TRANSPORTES_EXPRESSOS_DE_CARGAS_LTDA',
    'GTRAN_TRANSPORTES_E_LOGISTICA_LIMITADA',
    'TECNOLOG_TRANSP.RODO-AEREO_E_LOG_LTDA',
    'BEST_LOG_SOLUTIONS_LOGISTICA_LTDA',
    'HARUTOMI_EMPREENDIMENTOS_E_PARTICIPACOES_LTDA',
    'NISTA_TRANSPORTES_E_SERVICOS_LTDA',
    'TRANSPORTADORA_FORLUS_LTDA',
    'KSA_CITY_TRANSPORTES_LTDA',
    'WORK_CAR_TRANSPORTE_DE_VEICULOS_LTDA',
    'SOLIDEZ_TRANSPORTE_DE_VEICULOS_LTDA',
    'SCALA_PARTICIPACOES_E_EMPREENDIMENTOS_LTDA',
    'TRANSPORTADORA_EVELYN_LTDA',
    'TRIONON_TRANSPORTES_LTDA',
    'FREIRE_&_BURKART_ADVOGADOS_ASSOCIADOS',
    'ENGLOBA_SISTEMA_E_LOGISTICA_LTDA',
    'COOPERTRANSROD_COOPERATIVA_DE_SERVICOS_DE_TRANSPORTES_RODOVIARIOS',
    'MHE9_LOGISTICA_LTDA',
    'JHM_LOGISTICA_LTDA',
    'NAUER_TRANSPORTES_LTDA',
    'NA_MEDIDA_TRANSPORTES_LTDA',
    'ATIC_HOLDING_S.A',
    'CITALOC_LOGISTICA_LTDA',
    'BASILICATA_TRANSPORTES_LTDA',
    'PAULICON_TREINAMENTO_LTDA',
    'MHE9_SERVICOS_LOGISTICOS_LTDA',
    'ID_CARGO_BRASIL_LTDA',
    'MHE9_SERVICOS_EM_LOGISTICA_INTERNACIONAL_LTDA',
    'CENTRAL_SISTEMAS_DE_ENTREGAS_E_LOGISTICA_LTDA',
    'REVER_TECNOLOGIA_E_SERVICOS_LTDA',
    'TRANSKOMPA_LOGISTICA_LTDA',
    'NILTON_TONIN_JUNIOR_SERVICOS_ADMINISTRATIVOS',
    'BALDON_ENGEMETAL_ENGENHARIA_LTDA',
    'E_M_A_MORI_TRANSPORTES_LTDA',
    'BRASMEG_ARMAZEM_GERAL_LTDA',
    'TRANSPORTADORA_DE_CARGAS_LOS_RODRIGUES_LTDA',
    'TRANSPORTADORA_LR_LTDA',
    'LFG_DO_BRASIL_LTDA',
    'LEADERSHIP_FREIGHT_DO_BRASIL_LTDA',
    'GSSM_EMPREENDIMENTOS_E_PARTICIPACOES_LTDA',
    'DUX_TRANSPORTES_INTERNACIONAIS_LTDA',
    'DUX_TRUCKING_TRANSPORTES_E_LOGISTICA_LTDA',
    'COTRAG_TRANSPORTES_LTDA',
    'GIBS_TRANSPORTES_E_LOGISTICA_LTDA',
    'ATG_COMERCIO_E_ASSISTENCIA_TECNICA_LTDA',
    'PCONTAB_CONTABILIDADE_LTDA',
    'MAFRO_TRANSPORTES_LTDA',
    'BOZZI_LOGISTICA_E_TRANSPORTE_LTDA',
    'S_R_PARREIRA_DA_SILVA_HOLDING_LTDA',
    'WALCAR_-_ADMINISTRADORA_DE_BENS_PROPRIOS_S',
    'VIA_CARGAS_TRANSPORTES_LTDA',
    'SOMERLOG_LOGISTICA_E_TRANSPORTES_LTDA',
    'PAULO_CEZAR_FASSINA_-_ASSESSORIA_ADMINISTRATIVA',
    'ABL_COMERCIO_DE_VEICULOS_E_AERONAVES_E_PARTICIPACOES_LTDA',
    'MHYT_ADMINISTRADORA_DE_BENS_PROPRIOS_LTDA',
    'OTA_TRANSPORTES_LTDA',
    'VIAMEX_TRANSPORTES_E_LOGISTICA_LTDA'
]

def criar_excel_filtrado(excel_original, excel_saida):
    """
    Cria um novo Excel apenas com as empresas prioritárias
    """
    print(f"Lendo Excel original: {excel_original}")
    df = pd.read_excel(excel_original)
    
    # Normalizar nomes do Excel usando a função agressiva
    print("Normalizando nomes das empresas no Excel...")
    df['Nome_Normalizado'] = df['Nome Tratado'].apply(normaliza)
    
    # Normalizar lista de empresas prioritárias
    print("Normalizando lista de empresas prioritárias...")
    empresas_prioritarias_norm = [normaliza(emp) for emp in EMPRESAS_PRIORITARIAS]
    
    # Filtrar empresas usando fuzzy matching
    print("Aplicando fuzzy matching para encontrar empresas...")
    df_filtrado_list = []
    empresas_encontradas = []
    matches_info = []
    
    for i, emp_prioritaria in enumerate(empresas_prioritarias_norm):
        if not emp_prioritaria.strip():  # Skip empty strings
            continue
            
        # Encontrar matches usando fuzzy matching
        matches_mask = df['Nome_Normalizado'].apply(lambda n: eh_match(n, emp_prioritaria, limite=90))
        matches = df[matches_mask]
        
        if len(matches) > 0:
            df_filtrado_list.append(matches)
            for _, row in matches.iterrows():
                nome_original = row['Nome Tratado']
                nome_norm = row['Nome_Normalizado']
                score = fuzz.token_set_ratio(nome_norm, emp_prioritaria)
                empresas_encontradas.append(nome_norm)
                matches_info.append({
                    'original': EMPRESAS_PRIORITARIAS[i],
                    'encontrado': nome_original,
                    'score': score
                })
    
    if df_filtrado_list:
        df_filtrado = pd.concat(df_filtrado_list).drop_duplicates(subset='Nome Tratado')
    else:
        df_filtrado = pd.DataFrame(columns=df.columns)
    
    # Remover coluna temporária
    if 'Nome_Normalizado' in df_filtrado.columns:
        df_filtrado = df_filtrado.drop('Nome_Normalizado', axis=1)
    
    print(f"\nTotal de empresas no Excel original: {len(df)}")
    print(f"Total de empresas prioritárias encontradas: {len(df_filtrado)}")
    
    # Mostrar empresas encontradas com scores
    if len(df_filtrado) > 0:
        print(f"\nEmpresas prioritárias ENCONTRADAS ({len(df_filtrado)}) com scores:")
        matches_info_sorted = sorted(matches_info, key=lambda x: x['score'], reverse=True)
        for i, match in enumerate(matches_info_sorted[:15]):  # Mostrar 15 melhores
            nome_display = match['encontrado'].replace('_', ' ')
            print(f"  OK {nome_display} (Score: {match['score']}%)")
        if len(matches_info_sorted) > 15:
            print(f"  ... e mais {len(matches_info_sorted) - 15} empresas")
    
    # Mostrar algumas empresas não encontradas
    empresas_prioritarias_encontradas = {info['original'] for info in matches_info}
    empresas_nao_encontradas = set(EMPRESAS_PRIORITARIAS) - empresas_prioritarias_encontradas
    if empresas_nao_encontradas:
        print(f"\nAlgumas empresas prioritárias NÃO encontradas ({len(empresas_nao_encontradas)}):")
        for emp in sorted(list(empresas_nao_encontradas)[:5]):  # Mostrar apenas 5
            emp_display = emp.replace('_', ' ')
            print(f"  ERRO {emp_display}")
        if len(empresas_nao_encontradas) > 5:
            print(f"  ... e mais {len(empresas_nao_encontradas) - 5} empresas")
    
    # Salvar novo Excel
    df_filtrado.to_excel(excel_saida, index=False)
    print(f"\nExcel filtrado salvo em: {excel_saida}")
    
    return df_filtrado

if __name__ == "__main__":
    # Criar Excel temporário com apenas as empresas prioritárias
    # Primeiro tentar encontrar o arquivo Excel
    excel_files = [
        Path(r"C:\Users\operacional04\Downloads\Projeto-XML\data\SIEG (3).xlsx"),
        Path("data/SIEG (3).xlsx"),
        Path("SIEG (3).xlsx"),
        Path("data/cadastro_empresas.xlsx"),
        Path("cadastro_empresas.xlsx")
    ]
    
    excel_original = None
    for excel_file in excel_files:
        if excel_file.exists():
            excel_original = excel_file
            break
    
    if excel_original is None:
        print("ERRO: Arquivo Excel não encontrado. Tentativas:")
        for excel_file in excel_files:
            print(f"  - {excel_file}")
        sys.exit(1)
    
    excel_prioritarias = Path("empresas_prioritarias_temp.xlsx")
    
    print(f"Usando arquivo Excel: {excel_original}")
    
    # Criar Excel filtrado
    criar_excel_filtrado(excel_original, excel_prioritarias)
    
    # Executar o processamento principal com o Excel filtrado
    import subprocess
    
    print("\n" + "="*60)
    print("Iniciando processamento das empresas prioritárias...")
    print("="*60 + "\n")
    
    # Chamar o script principal com o Excel filtrado
    print("Iniciando o processamento principal...")
    print("Este processo pode demorar varios minutos dependendo do numero de empresas...")
    print("")
    
    result = subprocess.run([
        sys.executable,
        "app/run.py",
        "--excel",
        str(excel_prioritarias)
    ])
    
    print("")
    print("="*60)
    if result.returncode == 0:
        print("OK PROCESSAMENTO CONCLUIDO COM SUCESSO!")
        print("Todas as empresas prioritarias foram processadas.")
    else:
        print("ERRO DURANTE O PROCESSAMENTO!")
        print(f"Codigo de erro: {result.returncode}")
    print("="*60)
    
    # Limpar arquivo temporário
    if excel_prioritarias.exists():
        excel_prioritarias.unlink()
        print(f"\nArquivo temporário removido: {excel_prioritarias}")
    
    sys.exit(result.returncode)
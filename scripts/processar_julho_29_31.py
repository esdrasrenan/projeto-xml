"""
Script para processar especificamente os dias 29, 30 e 31 de julho de 2025
Não altera state.json - apenas força download desses dias específicos
"""
import pandas as pd
from pathlib import Path
import sys
from datetime import datetime, date
import logging

# Adicionar o diretório do projeto ao path
sys.path.append(str(Path(__file__).parent))

from core.api_client import APIClient
from core.state_manager import StateManager
from core.file_manager import FileManager
from core.xml_downloader import XMLDownloader
from core.utils import TYPE_MAPPING, ROLE_MAPPING
from core.report_manager import ReportManager, append_monthly_summary

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def processar_dia_especifico(api_client, state_manager, file_manager, xml_downloader, 
                           cnpj, nome_pasta, dia, mes=7, ano=2025):
    """
    Processa um dia específico para uma empresa
    """
    data_especifica = date(ano, mes, dia)
    logger.info(f"[{cnpj}] Processando dia {dia:02d}/{mes:02d}/{ano} - {nome_pasta}")
    
    total_baixados = 0
    stats = {
        'report_counts': {'NFe': {}, 'CTe': {}},
        'download_stats': {'tentativas': 0, 'sucesso': 0, 'falha_download': 0, 'falha_salvar': 0},
        'final_counts': {'NFe': 0, 'CTe': 0},
        'error_stats': {'parse_errors': 0, 'info_errors': 0, 'save_errors': 0}
    }
    
    # Processar cada tipo de documento (NFe, CTe)
    for tipo_str, tipo_code in TYPE_MAPPING.items():
        logger.info(f"[{cnpj}] Verificando {tipo_str} do dia {dia:02d}/07/2025...")
        
        try:
            # Baixar relatório do mês inteiro (necessário para API)
            report_data = api_client.baixar_relatorio_xml(
                cnpj=cnpj,
                tipo_xml=tipo_code,
                mes=mes,
                ano=ano
            )
            
            if not report_data['success']:
                logger.warning(f"[{cnpj}] Sem dados de {tipo_str} para julho/2025")
                continue
            
            if report_data.get('empty', False):
                logger.info(f"[{cnpj}] Nenhum {tipo_str} encontrado em julho/2025")
                continue
            
            # Salvar relatório temporário
            temp_report = Path(f"temp_{cnpj}_{tipo_str}_{ano}{mes:02d}.xlsx")
            report_data['content'].to_excel(temp_report, index=False)
            
            # Ler e filtrar apenas o dia específico
            try:
                report_df = ReportManager.read_report(temp_report)
                
                # Filtrar apenas XMLs do dia específico
                report_df['data_emissao'] = pd.to_datetime(report_df['dataEmissao'])
                df_dia = report_df[report_df['data_emissao'].dt.date == data_especifica]
                
                if len(df_dia) == 0:
                    logger.info(f"[{cnpj}] Nenhum {tipo_str} no dia {dia:02d}/07/2025")
                    continue
                
                logger.info(f"[{cnpj}] Encontrados {len(df_dia)} {tipo_str} no dia {dia:02d}/07/2025")
                
                # Agrupar por papel
                for papel, grupo in df_dia.groupby('papel'):
                    papel_str = ROLE_MAPPING.get(papel, papel)
                    chaves = grupo['chaveXML'].tolist()
                    
                    # Atualizar contadores do relatório
                    stats['report_counts'][tipo_str][(tipo_str, papel_str)] = len(chaves)
                    
                    logger.info(f"[{cnpj}] Baixando {len(chaves)} {tipo_str}/{papel_str} do dia {dia:02d}/07...")
                    
                    # Verificar quais já existem localmente
                    dir_destino = file_manager.get_xml_directory(
                        cnpj_cpf=cnpj,
                        nome_pasta=nome_pasta,
                        tipo_xml=tipo_str,
                        data_emissao=data_especifica,
                        papel=papel_str
                    )
                    
                    chaves_existentes = set()
                    if dir_destino.exists():
                        for xml_file in dir_destino.glob("*.xml"):
                            chave = xml_file.stem
                            if chave.endswith("_CANC"):
                                chave = chave[:-5]
                            chaves_existentes.add(chave)
                    
                    # Baixar apenas os que faltam
                    chaves_faltantes = [c for c in chaves if c not in chaves_existentes]
                    
                    if chaves_faltantes:
                        logger.info(f"[{cnpj}] Faltam {len(chaves_faltantes)} XMLs - baixando...")
                        
                        stats['download_stats']['tentativas'] += len(chaves_faltantes)
                        
                        baixados = xml_downloader.baixar_xmls_especificos(
                            cnpj=cnpj,
                            tipo_xml=tipo_code,
                            chaves_xml=chaves_faltantes,
                            nome_pasta=nome_pasta,
                            papel=papel_str,
                            batch_size=50
                        )
                        
                        total_baixados += baixados
                        stats['download_stats']['sucesso'] += baixados
                        stats['download_stats']['falha_download'] += (len(chaves_faltantes) - baixados)
                        logger.info(f"[{cnpj}] Baixados {baixados} XMLs novos")
                    else:
                        logger.info(f"[{cnpj}] Todos os XMLs já existem localmente")
                
            finally:
                # Limpar arquivo temporário
                if temp_report.exists():
                    temp_report.unlink()
                    
        except Exception as e:
            logger.error(f"[{cnpj}] Erro ao processar {tipo_str}: {e}")
            continue
    
    return total_baixados, stats

def main():
    """Função principal"""
    
    print("=== PROCESSAMENTO ESPECÍFICO - JULHO 29, 30, 31 ===\n")
    
    # Verificar se estamos no diretório correto
    if not Path("state.json").exists():
        print("ERRO: Execute este script no diretório do projeto!")
        return
    
    # Encontrar arquivo Excel
    excel_files = [
        Path(r"C:\Users\operacional04\Downloads\Projeto-XML\data\SIEG (3).xlsx"),
        Path("data/SIEG (3).xlsx"),
        Path("SIEG (3).xlsx")
    ]
    
    excel_path = None
    for f in excel_files:
        if f.exists():
            excel_path = f
            break
    
    if excel_path is None:
        print("ERRO: Arquivo Excel não encontrado!")
        return
    
    print(f"Usando Excel: {excel_path}")
    
    # Ler empresas
    df = pd.read_excel(excel_path)
    total_empresas = len(df)
    print(f"Total de empresas: {total_empresas}")
    print()
    
    # Confirmar
    print("Este script irá:")
    print("  - Processar TODAS as empresas")
    print("  - Focar APENAS em julho 2025")
    print("  - Baixar APENAS dias 29, 30 e 31")
    print("  - NÃO alterar state.json")
    print("  - Baixar apenas XMLs que faltam")
    print()
    
    resposta = input("Confirma o processamento? (digite 'SIM'): ")
    if resposta.upper() != 'SIM':
        print("Operação cancelada.")
        return
    
    # Inicializar componentes
    print("\nInicializando componentes...")
    api_client = APIClient()
    state_manager = StateManager()
    file_manager = FileManager()
    xml_downloader = XMLDownloader(api_client, state_manager, file_manager)
    
    # Processar cada dia
    dias_processar = [29, 30, 31]
    total_geral_baixados = 0
    
    for dia in dias_processar:
        print(f"\n{'='*60}")
        print(f"PROCESSANDO DIA {dia:02d}/07/2025")
        print(f"{'='*60}\n")
        
        empresas_processadas = 0
        xmls_dia = 0
        
        for idx, row in df.iterrows():
            cnpj = str(row['CnpjCpf']).zfill(14)
            nome_pasta = row['Nome Tratado']
            
            try:
                baixados, stats = processar_dia_especifico(
                    api_client, state_manager, file_manager, xml_downloader,
                    cnpj, nome_pasta, dia
                )
                
                xmls_dia += baixados
                
                # Gerar relatório de auditoria - append no arquivo existente de julho
                # Usar o mesmo arquivo que já existe para julho 2025
                summary_file = file_manager.get_report_directory(
                    cnpj_cpf=cnpj,
                    nome_pasta=nome_pasta,
                    tipo_xml='NFe',  # Qualquer tipo serve, só queremos o diretório base
                    data_emissao=date(2025, 7, 1)
                ).parent / f"Resumo_Auditoria_0001_{nome_pasta}_072025.txt"
                
                # Se o arquivo não existir no diretório da empresa, criar
                if not summary_file.exists():
                    summary_file.parent.mkdir(parents=True, exist_ok=True)
                
                append_monthly_summary(
                    summary_file_path=summary_file,
                    execution_time=datetime.now(),
                    empresa_cnpj=cnpj,
                    empresa_nome=nome_pasta,
                    period_start=date(2025, 7, dia),
                    period_end=date(2025, 7, dia),
                    report_counts=stats['report_counts'],
                    download_stats=stats['download_stats'],
                    final_counts=stats['final_counts'],
                    error_stats=stats['error_stats']
                )
                empresas_processadas += 1
                
                if (empresas_processadas % 10) == 0:
                    print(f"Progresso: {empresas_processadas}/{total_empresas} empresas processadas...")
                    
            except Exception as e:
                logger.error(f"Erro ao processar empresa {nome_pasta}: {e}")
                continue
        
        print(f"\nDia {dia:02d}/07 concluído:")
        print(f"  - Empresas processadas: {empresas_processadas}")
        print(f"  - XMLs baixados: {xmls_dia}")
        
        total_geral_baixados += xmls_dia
    
    # Resumo final
    print(f"\n{'='*60}")
    print(f"PROCESSAMENTO CONCLUÍDO!")
    print(f"{'='*60}")
    print(f"Total de XMLs baixados: {total_geral_baixados}")
    print(f"Dias processados: {', '.join(str(d) for d in dias_processar)}")
    print(f"State.json: Não foi alterado")

if __name__ == "__main__":
    main()
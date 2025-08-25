"""Ponto de entrada da aplicação e orquestrador do processo."""

import argparse
import sys
import time
import socket
import requests
from datetime import datetime, timedelta, date
from pathlib import Path
import os
from typing import Dict, List, Any, Tuple, Set, Optional
import locale
import base64
import logging
import pandas as pd
from calendar import monthrange
import shutil

# Adicionar o diretório raiz ao sys.path para permitir imports de 'core'
# Isso é útil se rodar o script diretamente, mas com `python -m app.run` não seria estritamente necessário
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from loguru import logger

# Imports dos módulos core
from core.api_client import SiegApiClient
from requests.exceptions import RequestException
from core.file_manager import (
    read_empresa_excel,
    save_report_from_base64,
    save_xmls_from_base64,
    organize_pending_events,
    get_local_keys,
    save_decoded_xml,
    save_raw_xml,
    count_local_files,
    PRIMARY_SAVE_BASE_PATH
)

from core.file_manager_transactional import TransactionalFileManager
from core.utils import XML_TYPE_NFE, XML_TYPE_CTE, normalize_cnpj
from core.report_validator import (
    read_report_data,
    classify_keys_by_role,
    get_counts_by_role
)
from core.report_manager import append_monthly_summary
from core.state_manager_v2 import StateManagerV2
from core.missing_downloader import download_missing_xmls
from core.xml_downloader import download_cancel_events

# Diretório base para salvar XMLs (relativo à raiz do projeto)
# XML_SAVE_DIR = ROOT_DIR / "xmls"
# EVENT_SAVE_DIR = XML_SAVE_DIR / "eventos_pendentes"

# Diretório temporário para relatórios - usar AppData\Local do usuário
import os
TEMP_REPORTS_DIR = Path(os.environ.get('LOCALAPPDATA', os.path.expanduser('~\\AppData\\Local'))) / "XMLDownloaderSieg" / "temp_reports"

# --- Constantes ---
XML_DOWNLOAD_BATCH_SIZE = 50 # Tamanho do lote para download de XMLs
REPORT_DOWNLOAD_RETRIES = 2 # Número de tentativas para baixar relatório
REPORT_DOWNLOAD_DELAY = 5 # Delay em segundos entre tentativas
LIMIAR_LOTE = 50 # Limiar para download individual vs lote (máx ~2min com limite API 30/min)

# Mapeamentos (manter aqui por enquanto, idealmente mover para config.py depois)
# Mapeamento de papel para campo da API (consistente com xml_downloader)
ROLE_MAP = {
    "Emitente": "CnpjEmit",
    "Destinatario": "CnpjDest",
    "Tomador": "CnpjTom"
}
# Mapeamento reverso de código para string (para logs/chaves de estado)
XML_TYPE_MAP_REV = {
    XML_TYPE_NFE: "NFe",
    XML_TYPE_CTE: "CTe"
}

# --- Configuração de Logging --- #
def configure_logging(log_level="INFO"):
    """Configura o logger Loguru com sistema hierárquico por mês/empresa."""
    log_level = log_level.upper()
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<level>{message}</level>"
    )
    detailed_log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - " # Inclui local no arquivo detalhado
        "<level>{message}</level>"
    )

    logger.remove() # Remove handlers padrão

    # Handler para console
    logger.add(sys.stderr, level=log_level, format=log_format, colorize=True)

    # Handler para arquivo de log global com rotação otimizada
    logs_dir = ROOT_DIR / "logs"
    logs_dir.mkdir(exist_ok=True)
    global_log_path = logs_dir / "global.log"
    # Rotação a cada 50MB, mantendo apenas os últimos 5 arquivos, com compressão automática
    logger.add(
        global_log_path, 
        level="INFO", 
        format=log_format, 
        rotation="50 MB",      # Aumentado de 10MB para 50MB
        retention=5,           # Mantém apenas os últimos 5 arquivos
        compression="zip",     # Comprime logs antigos automaticamente
        enqueue=True, 
        encoding='utf-8'
    )

    # Handler para arquivo de log detalhado da execução atual com rotação
    timestamp = datetime.now().strftime("%Y_%m_%d_%H%M%S")
    run_log_path = logs_dir / f"{timestamp}.log"
    logger.add(
        run_log_path, 
        level="DEBUG", 
        format=detailed_log_format, 
        rotation="50 MB",      # Rotação a cada 50MB (mesmo que global)
        retention=3,           # Mantém apenas os últimos 3 arquivos detalhados
        compression="zip",     # Comprime automaticamente
        enqueue=True, 
        encoding='utf-8'
    )
    
    # Criar estrutura de logs hierárquicos por mês
    current_date = datetime.now()
    month_str = current_date.strftime("%m-%Y")
    monthly_logs_dir = logs_dir / month_str
    monthly_logs_dir.mkdir(exist_ok=True)
    
    # Log geral do mês (para eventos não específicos de empresas)
    monthly_log_path = monthly_logs_dir / "sistema.log"
    logger.add(monthly_log_path, level="INFO", format=log_format, rotation="50 MB", enqueue=True, encoding='utf-8')

    # Configurar locale para português (Brasil) para nomes de meses
    try:
        # Tenta configurar para pt_BR.UTF-8 (Linux/macOS comuns)
        locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
    except locale.Error:
        try:
             # Tenta configurar para Portuguese_Brazil (Windows)
             locale.setlocale(locale.LC_TIME, 'Portuguese_Brazil')
        except locale.Error:
             logger.warning("Não foi possível configurar o locale para Português (pt_BR ou Portuguese_Brazil). Nomes dos meses podem ficar em inglês.")
             # Mantém o locale padrão C/POSIX

    logger.info(f"Logging configurado. Nível console: {log_level}. Arquivo global: {global_log_path}. Arquivo da execução: {run_log_path}")
    logger.info(f"Logs estruturados: {monthly_logs_dir} criado para o mês {month_str}")

# --- Sistema de Logs Hierárquicos por Empresa --- #
_company_log_handlers = {}  # Cache de handlers por empresa

def setup_company_logger(nome_empresa: str, cnpj: str) -> int:
    """
    Configura um logger específico para uma empresa no mês atual.
    
    Args:
        nome_empresa: Nome da pasta da empresa (ex: '0001_PAULICON_CONTABIL_LTDA')
        cnpj: CNPJ normalizado da empresa
        
    Returns:
        Handler ID do logger criado
    """
    global _company_log_handlers
    
    # Chave única para esta empresa
    company_key = f"{cnpj}_{nome_empresa}"
    
    # Se já existe um handler para esta empresa, remove o anterior
    if company_key in _company_log_handlers:
        try:
            logger.remove(_company_log_handlers[company_key])
        except ValueError:
            pass  # Handler já foi removido
    
    # Criar estrutura de diretórios
    current_date = datetime.now()
    month_str = current_date.strftime("%m-%Y")
    logs_dir = ROOT_DIR / "logs" / month_str
    company_log_dir = logs_dir / nome_empresa
    company_log_dir.mkdir(parents=True, exist_ok=True)
    
    # Caminho do log da empresa
    company_log_path = company_log_dir / "empresa.log"
    
    # Formato específico para logs de empresa (inclui CNPJ)
    company_log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        f"<blue>[{cnpj}]</blue> | "
        "<level>{message}</level>"
    )
    
    # Adicionar handler específico para esta empresa
    handler_id = logger.add(
        company_log_path, 
        level="INFO", 
        format=company_log_format, 
        rotation="20 MB",  # Rotação menor para logs individuais
        compression="zip",
        enqueue=True, 
        encoding='utf-8',
        filter=lambda record: record["extra"].get("empresa") == company_key
    )
    
    # Armazenar o handler ID para remoção posterior
    _company_log_handlers[company_key] = handler_id
    
    return handler_id

def log_empresa(nome_empresa: str, cnpj: str, message: str, level: str = "INFO"):
    """
    Registra uma mensagem no log específico da empresa.
    
    Args:
        nome_empresa: Nome da pasta da empresa
        cnpj: CNPJ normalizado
        message: Mensagem a ser logada
        level: Nível do log (INFO, WARNING, ERROR, etc.)
    """
    company_key = f"{cnpj}_{nome_empresa}"
    
    # Usar contexto extra para filtrar mensagens por empresa
    with logger.contextualize(empresa=company_key):
        if level.upper() == "ERROR":
            logger.error(message)
        elif level.upper() == "WARNING":
            logger.warning(message)
        elif level.upper() == "DEBUG":
            logger.debug(message)
        else:
            logger.info(message)

def cleanup_company_logger(nome_empresa: str, cnpj: str):
    """
    Remove o handler do logger da empresa para liberar recursos.
    
    Args:
        nome_empresa: Nome da pasta da empresa
        cnpj: CNPJ normalizado
    """
    global _company_log_handlers
    
    company_key = f"{cnpj}_{nome_empresa}"
    
    if company_key in _company_log_handlers:
        try:
            logger.remove(_company_log_handlers[company_key])
            del _company_log_handlers[company_key]
        except (ValueError, KeyError):
            pass  # Handler já foi removido ou não existe

# --- Função Auxiliar para Download de Lote --- #
def _download_xml_batch(
    api_client: SiegApiClient,
    cnpj_norm: str,
    report_type_code: int,
    papel: str, # Ex: "Emitente", "Destinatario"
    skip: int,
    take: int,
    month_start_dt: datetime,
    month_end_dt: datetime
) -> List[str]:
    """
    Realiza a chamada API /BaixarXmls para um lote específico.

    Lança exceções (ValueError, RequestException) em caso de erro na API ou rede.
    Retorna a lista de XMLs em base64.
    """
    api_role_field = ROLE_MAP.get(papel)
    if not api_role_field:
        # Isso não deveria acontecer se chamado corretamente, mas é uma salvaguarda
        raise ValueError(f"Papel '{papel}' não mapeado para campo da API em ROLE_MAP.")

    payload = {
        "XmlType": report_type_code,
        "Take": take,
        "Skip": skip,
        "DataEmissaoInicio": month_start_dt.strftime('%Y-%m-%d'),
        "DataEmissaoFim": month_end_dt.strftime('%Y-%m-%d'),
        api_role_field: cnpj_norm,
        "DownloadEvent": False
    }
    logger.debug(f"Payload /BaixarXmls: {payload}")

    # A chamada API pode lançar ValueError ou RequestException
    response = api_client.baixar_xmls(payload)

    # **CORREÇÃO**: Lidar com resposta sendo lista ou dicionário
    if isinstance(response, list):
        # Se a resposta já é a lista, usa diretamente
        xmls_base64_lote = response
        logger.debug("Resposta de /BaixarXmls recebida como lista direta.")
    elif isinstance(response, dict):
        # Se for dicionário, pega a chave 'Xmls'
        xmls_base64_lote = response.get("Xmls", [])
        logger.debug("Resposta de /BaixarXmls recebida como dicionário.")
    else:
        # Tipo inesperado
        logger.warning(f"Resposta inesperada de /BaixarXmls (tipo {type(response)}): {response}. Retornando lista vazia.")
        xmls_base64_lote = []

    return xmls_base64_lote

# --- Função Auxiliar para Tentativa de Download de Relatório --- #
def _try_download_and_process_report(
    api_client: SiegApiClient,
    state_manager: StateManagerV2,
    cnpj_norm: str,
    nome_pasta: str,
    report_type_str: str, # "NFe" ou "CTe"
    report_type_code: int, # Código numérico do tipo de relatório
    month_start_dt: datetime # Objeto datetime para o início do mês
) -> Tuple[bool, bool, Optional[Path]]:
    """
    Tenta baixar, salvar e ler um relatório (NFe ou CTe) para um dado CNPJ e mês.
    Gerencia tentativas, logging e atualização de status/pendências no StateManagerV2.

    Args:
        api_client: Instância do SiegApiClient.
        state_manager: Instância do StateManagerV2.
        cnpj_norm: CNPJ normalizado da empresa.
        nome_pasta: Nome da pasta da empresa para salvar o relatório.
        report_type_str: String identificadora do tipo de relatório ("NFe" ou "CTe").
        report_type_code: Código numérico do tipo de relatório (1 para NFe, 2 para CTe).
        month_start_dt: Objeto datetime representando o primeiro dia do mês do relatório.

    Returns:
        Uma tupla: (download_bem_sucedido, relatorio_estava_vazio, caminho_temp, destino_dir, destino_filename)
        - download_bem_sucedido: True se o relatório foi obtido e processado (mesmo que vazio), False se falhou.
        - relatorio_estava_vazio: True se a API indicou "Nenhum arquivo xml encontrado".
        - caminho_temp: Path para o arquivo temporário .xlsx se salvo, None caso contrário.
        - destino_dir: Path do diretório de destino final, None se não aplicável.
        - destino_filename: Nome do arquivo para destino final, None se não aplicável.
    """
    
    # Wrapper de segurança geral para garantir que sempre retornamos valores válidos
    try:
        return _try_download_and_process_report_internal(
            api_client, state_manager, cnpj_norm, nome_pasta,
            report_type_str, report_type_code, month_start_dt
        )
    except Exception as e:
        logger.error(f"[{cnpj_norm}] ERRO CRÍTICO não tratado em _try_download_and_process_report para {report_type_str} ({month_start_dt.strftime('%Y-%m')}): {e}")
        logger.exception("Detalhes do erro:", exc_info=True)
        # Garantir que sempre retornamos valores válidos
        return False, False, None, None, None


def _try_download_and_process_report_internal(
    api_client: SiegApiClient,
    state_manager: StateManagerV2,
    cnpj_norm: str,
    nome_pasta: str,
    report_type_str: str, # "NFe" ou "CTe"
    report_type_code: int, # Código numérico do tipo de relatório
    month_start_dt: datetime # Objeto datetime para o início do mês
) -> Tuple[bool, bool, Optional[Path]]:
    """Implementação interna da função de download de relatório."""
    month = month_start_dt.month
    year = month_start_dt.year
    month_key_str = month_start_dt.strftime("%Y-%m")
    report_filename = f"Relatorio_{report_type_str}_{nome_pasta}_{month:02d}_{year}.xlsx"
    
    # Caminho base para relatórios FINAL (relativo à pasta da empresa/mês)
    # Ex: XML_CLIENTES/ANO/NOME_EMPRESA/MES/NFe/
    reports_base_dir = PRIMARY_SAVE_BASE_PATH / str(year) / nome_pasta / f"{month:02d}" / report_type_str
    reports_base_dir.mkdir(parents=True, exist_ok=True)
    full_report_path = reports_base_dir / report_filename
    
    # Criar pasta temporária se não existir
    TEMP_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Nome do arquivo temporário com timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_filename = f"{cnpj_norm}_{report_type_str}_{month_key_str}_{timestamp}.xlsx"
    temp_report_path = TEMP_REPORTS_DIR / temp_filename

    df_report: Optional[pd.DataFrame] = None
    download_successful = False
    report_empty_api = False

    for attempt in range(1, REPORT_DOWNLOAD_RETRIES + 1):
        attempt_start = datetime.now()
        logger.debug(f"[{cnpj_norm}] [{attempt_start.strftime('%H:%M:%S')}] Tentativa {attempt}/{REPORT_DOWNLOAD_RETRIES} de baixar relatório {report_type_str} para {month_key_str}...")
        try:
            # Usa o report_type_code para o parâmetro xml_type da API
            # E o report_type_str para o TypeXmlDownloadReport (NFe=2, CTe=4)
            api_report_type_param = 2 if report_type_str == "NFe" else 4 # 2-RelatorioBasico para NFe, 4-CTe para CTe
            
            response_dict = api_client.baixar_relatorio_xml(
                cnpj=cnpj_norm, 
                xml_type=report_type_code, 
                month=month, 
                year=year,
                report_type=api_report_type_param 
            )

            report_b64 = response_dict.get("RelatorioBase64")
            report_empty_api = response_dict.get("EmptyReport", False)
            error_msg = response_dict.get("ErrorMessage")

            if error_msg:
                attempt_end = datetime.now()
                duration = (attempt_end - attempt_start).total_seconds()
                logger.warning(f"[{cnpj_norm}] [{attempt_end.strftime('%H:%M:%S')}] API retornou mensagem de erro para relatório {report_type_str} ({month_key_str}), Tentativa {attempt} (duração: {duration:.1f}s): {error_msg}")
                # Continuar para próxima tentativa, a menos que seja a última

            elif report_empty_api:
                logger.info(f"[{cnpj_norm}] API informou: 'Nenhum arquivo xml encontrado' para relatório {report_type_str} ({month_key_str}).")
                state_manager.update_report_download_status(cnpj_norm, month_key_str, report_type_str, "no_data_confirmed", message="API: Nenhum arquivo xml encontrado")
                state_manager.resolve_report_pendency(cnpj_norm, month_key_str, report_type_str) # Resolve se era pendência
                download_successful = True # Considerado sucesso, pois a API respondeu
                break # Sai do loop de tentativas

            elif report_b64:
                # Salvar em pasta temporária primeiro
                if save_report_from_base64(report_b64, TEMP_REPORTS_DIR, temp_filename):
                    logger.info(f"[{cnpj_norm}] Relatório {report_type_str} salvo temporariamente em: {temp_report_path}")
                    time.sleep(1) # Pequena pausa para garantir que o OS liberou o arquivo
                    download_successful = True
                    # Armazenar informações para cópia posterior
                    # Por enquanto, registrar como sucesso com o caminho temporário
                    state_manager.update_report_download_status(cnpj_norm, month_key_str, report_type_str, "success_temp", file_path=str(temp_report_path))
                    state_manager.resolve_report_pendency(cnpj_norm, month_key_str, report_type_str) # Resolve se era pendência
                    break # Sucesso, sai do loop de tentativas
                else:
                    logger.error(f"[{cnpj_norm}] Falha ao SALVAR relatório {report_type_str} ({month_key_str}) temporariamente. ({temp_report_path})")
                    # Considerar como falha de processamento e adicionar pendência
                    state_manager.add_or_update_report_pendency(cnpj_norm, month_key_str, report_type_str, "pending_processing")
                    # Truncar mensagem para evitar problemas de serialização
                    error_msg = f"Falha ao salvar temp {temp_report_path}"[:200]
                    state_manager.update_report_download_status(cnpj_norm, month_key_str, report_type_str, "failed_processing_save", message=error_msg)
                    # Não sair do loop, tentar novamente se houver tentativas restantes
            else:
                # Resposta não continha Base64, nem EmptyReport, nem ErrorMessage explícito (Ex: resposta vazia `{}`)
                logger.warning(f"[{cnpj_norm}] Relatório {report_type_str} ({month_key_str}) não retornado pela API (sem Base64/EmptyReport). Tentativa {attempt}. Conteúdo: {response_dict}")
                # Continuar para próxima tentativa

        except TimeoutError as e_timeout:
            # Tratamento específico para timeout absoluto
            attempt_end = datetime.now()
            duration = (attempt_end - attempt_start).total_seconds()
            logger.error(f"[{cnpj_norm}] [{attempt_end.strftime('%H:%M:%S')}] TIMEOUT ABSOLUTO ao baixar relatório {report_type_str} ({month_key_str}), Tentativa {attempt} (duração: {duration:.1f}s): {e_timeout}")
            # Re-lançar TimeoutError para ser capturado pelo caller
            raise
        except RequestException as e_req:
            attempt_end = datetime.now()
            duration = (attempt_end - attempt_start).total_seconds()
            logger.error(f"[{cnpj_norm}] [{attempt_end.strftime('%H:%M:%S')}] Erro de REDE/HTTP ao baixar relatório {report_type_str} ({month_key_str}), Tentativa {attempt} (duração: {duration:.1f}s): {e_req}")
            # Erro de rede, continuar para próxima tentativa se houver
        except ValueError as e_val:
            logger.error(f"[{cnpj_norm}] Erro de VALOR (ex: JSON inválido) ao baixar relatório {report_type_str} ({month_key_str}), Tentativa {attempt}: {e_val}")
            # Erro que pode ser da API, continuar para próxima tentativa
        except Exception as e_gen:
            logger.exception(f"[{cnpj_norm}] Erro INESPERADO ao baixar relatório {report_type_str} ({month_key_str}), Tentativa {attempt}: {e_gen}", exc_info=True)
            # Erro genérico, continuar para próxima tentativa

        if attempt < REPORT_DOWNLOAD_RETRIES and not download_successful:
            logger.info(f"Aguardando {REPORT_DOWNLOAD_DELAY}s antes da próxima tentativa ({attempt+1})...")
            time.sleep(REPORT_DOWNLOAD_DELAY)
    # Fim do loop de tentativas

    if not download_successful:
        logger.error(f"[{cnpj_norm}] Falha ao obter/ler informações do relatório {report_type_str} para {month_key_str} após {REPORT_DOWNLOAD_RETRIES} tentativas.")
        # Se não foi sucesso E não foi empty_report confirmado, registrar pendência de API
        if not report_empty_api:
            try:
                state_manager.add_or_update_report_pendency(cnpj_norm, month_key_str, report_type_str, "pending_api_response")
                # Truncar mensagem para evitar problemas de serialização
                error_msg = f"Falha API após {REPORT_DOWNLOAD_RETRIES} tentativas"[:200]
                state_manager.update_report_download_status(cnpj_norm, month_key_str, report_type_str, "failed_api", message=error_msg)
                logger.info(f"[{cnpj_norm}] Estado salvo após registrar pendência de API para relatório {report_type_str} ({month_key_str}).")
                state_manager.save_state() # SALVAR ESTADO AQUI
            except Exception as e_state:
                logger.error(f"[{cnpj_norm}] ERRO ao salvar estado após falha de relatório: {e_state}. Continuando mesmo assim.")
        return False, report_empty_api, None, None, None # Falha no download, status de vazio, sem path temp, sem destino final

    # Se teve sucesso e baixou relatório, retornar o caminho temporário e as informações do destino final
    if download_successful and report_b64:
        return True, report_empty_api, temp_report_path, reports_base_dir, report_filename
    else:
        return True, report_empty_api, None, None, None # Sucesso mas vazio

# --- Função para copiar relatório da pasta temp para destino final ---
def copy_report_to_final_destination(temp_path: Path, final_dir: Path, final_filename: str) -> bool:
    """
    Copia relatório da pasta temporária para o destino final.
    
    Args:
        temp_path: Caminho do arquivo temporário
        final_dir: Diretório de destino final
        final_filename: Nome do arquivo no destino final
    
    Returns:
        True se a cópia foi bem-sucedida, False caso contrário
    """
    try:
        final_path = final_dir / final_filename
        
        # Garantir que o diretório de destino existe
        final_dir.mkdir(parents=True, exist_ok=True)
        
        # Copiar arquivo
        shutil.copy2(temp_path, final_path)
        logger.info(f"Relatório copiado com sucesso para destino final: {final_path}")
        
        # Remover arquivo temporário após cópia bem-sucedida
        try:
            temp_path.unlink()
            logger.debug(f"Arquivo temporário removido: {temp_path}")
        except Exception as e:
            logger.warning(f"Não foi possível remover arquivo temporário {temp_path}: {e}")
        
        return True
        
    except PermissionError as e:
        logger.warning(f"Arquivo pode estar aberto: {final_path}. Erro: {e}")
        logger.info(f"Relatório temporário mantido em: {temp_path}")
        return False
    except Exception as e:
        logger.error(f"Erro ao copiar relatório para {final_path}: {e}")
        logger.info(f"Relatório temporário mantido em: {temp_path}")
        return False

# --- Função de Orquestração Geral (Nova/Modificada) ---
def run_overall_process(api_client: SiegApiClient, excel_path: str, limit: int | None, seed_run: bool = False):
    """
    Orquestra a execução de um ciclo de processamento, incluindo:
    1. Tentativa de processar pendências de relatórios.
    2. Execução do ciclo normal de processamento para todas as empresas.
    """
    logger.info("--- Iniciando NOVO CICLO GERAL DE PROCESSAMENTO (run_overall_process) ---")
    overall_start_time = time.monotonic()

    state_dir = ROOT_DIR / "estado"
    state_manager = StateManagerV2(state_dir) # StateManager v2 com compatibilidade v1

    # Inicializa o gerenciador transacional
    transactional_manager = None
    try:
        transactional_manager = TransactionalFileManager()
        logger.info("TransactionalFileManager inicializado para garantir atomicidade de salvamento")
    except Exception as e:
        logger.error(f"Erro ao inicializar TransactionalFileManager: {e}. Continuando sem gerenciamento transacional.")
        transactional_manager = None
    
    if seed_run:
        logger.warning("Execução em modo --seed. Resetando estado em memória ANTES de carregar.")
        state_manager.reset_state() # Reseta antes de qualquer carga
        # Salva o estado resetado para garantir que o arquivo reflita o reset se o script parar aqui
        state_manager.save_state() 
    
    try:
        state_manager.load_state() # Carrega o estado (resetado ou existente)
    except Exception as e:
        logger.error(f"Erro ao carregar estado: {e}. Iniciando com estado limpo.")
        state_manager.reset_state()

    # 1. Processar Pendências de Relatório
    logger.info("Verificando pendências de relatórios de ciclos anteriores...")
    pending_reports = state_manager.get_pending_reports()
    
    if pending_reports:
        logger.info(f"Encontradas {len(pending_reports)} pendências de relatório. Tentando reprocessá-las primeiro.")
        for cnpj_norm, month_str, report_type_str, attempts, status in pending_reports:
            logger.info(f"Reprocessando pendência: {cnpj_norm}/{month_str}/{report_type_str} (Tentativas: {attempts}, Status: {status})")
            
            # Extrair nome da pasta e informações da empresa (pode precisar de uma forma de buscar isso ou simplificar)
            # Por simplicidade, vamos assumir que podemos obter nome_pasta de alguma forma
            # ou que as funções chamadas não dependem criticamente dele nesta fase de repriorização
            # Idealmente, o state_manager guardaria o nome_pasta junto com a pendência ou teríamos um lookup.
            # Para este exemplo, vamos precisar que `run_process_specific_report` o obtenha.
            
            # Obter os parâmetros da empresa (nome_pasta) - isso pode ser um desafio aqui
            # Se a lista de empresas for lida novamente, podemos buscar.
            # Por ora, vamos focar na lógica de tentativa do relatório.
            empresas_list_for_lookup = read_empresa_excel(excel_path, limit=None) # Relê para lookup
            nome_pasta_pendency = "PASTA_DESCONHECIDA_PENDENCIA"
            cnpj_orig_pendency = cnpj_norm # Assumindo que o normalizado é suficiente para logs ou que temos o original
            for c_orig, np_for_lookup in empresas_list_for_lookup:
                if normalize_cnpj(c_orig) == cnpj_norm:
                    nome_pasta_pendency = np_for_lookup
                    cnpj_orig_pendency = c_orig
                    break
            
            if nome_pasta_pendency == "PASTA_DESCONHECIDA_PENDENCIA":
                logger.error(f"Não foi possível encontrar nome da pasta para CNPJ {cnpj_norm} (pendência). Pulando reprocessamento desta pendência.")
                continue

            try:
                year_pend, month_pend = map(int, month_str.split('-'))
                report_type_code_pendency = XML_TYPE_NFE if report_type_str == "NFe" else XML_TYPE_CTE

                try:
                    # Para pendências, ignoramos os caminhos temporários pois já foram processados
                    success, was_empty, temp_path, dest_dir, dest_filename = _try_download_and_process_report(
                        api_client, state_manager, cnpj_norm, nome_pasta_pendency, 
                        report_type_str, report_type_code_pendency, 
                        datetime(year_pend, month_pend, 1), # month_start_dt
                        # REPORT_DOWNLOAD_RETRIES AQUI DEVE SER O GLOBAL (5) ou um específico para pendências?
                        # Usaremos o global (5) por simplicidade na chamada, a lógica de MAX_PENDENCY_ATTEMPTS é separada.
                        # A contagem de tentativas da pendência é atualizada pelo state_manager
                    )
                    # Se sucesso e tem arquivo temporário, tentar copiar para destino final
                    if success and temp_path and dest_dir and dest_filename:
                        copy_report_to_final_destination(temp_path, dest_dir, dest_filename)
                except TimeoutError as e_timeout:
                    # Tratamento específico para timeout absoluto em pendências
                    logger.error(f"[{cnpj_norm}] TIMEOUT ABSOLUTO ao processar pendência {report_type_str} ({month_str}): {e_timeout}")
                    success = False
                    was_empty = False
                except Exception as e_download:
                    logger.error(f"Erro ao reprocessar pendência {cnpj_norm}/{month_str}/{report_type_str}: {e_download}")
                    success = False
                    was_empty = False

                if success:
                    state_manager.resolve_report_pendency(cnpj_norm, month_str, report_type_str)
                    state_manager.update_report_download_status(cnpj_norm, month_str, report_type_str, "success_pendency", message="Relatório recuperado com sucesso após ser pendência.")
                     # Se o relatório foi baixado com sucesso (e não estava vazio), resetar skips de XML
                    if not was_empty:
                        logger.info(f"Resetando skips de XML para {cnpj_norm}/{month_str}/{report_type_str} após sucesso na pendência de relatório.")
                        state_manager.reset_skip_for_report(cnpj_norm, month_str, report_type_str)
                elif was_empty:
                    state_manager.update_report_pendency_status(cnpj_norm, month_str, report_type_str, "no_data_confirmed")
            except Exception as e_pendencia:
                logger.exception(f"Erro durante processamento da pendência {cnpj_norm}/{month_str}/{report_type_str}: {e_pendencia}")
                logger.info(f">>> CONTINUANDO - Ignorando pendência problemática e seguindo para próxima <<<")
                continue

    # 2. Execução do ciclo normal de processamento para todas as empresas
    resultado_ciclo = None
    try:
        resultado_ciclo = run_process(api_client, excel_path, limit, state_manager, seed_run, transactional_manager)
    except Exception as e:
        logger.error(f"ERRO CRÍTICO em run_process: {e}")
        logger.exception("Detalhes do erro:", exc_info=True)
        # Criar resultado falso para permitir continuação
        resultado_ciclo = {
            "total_empresas": 0,
            "empresas_sucesso": 0,
            "empresas_falha": 0,
            "taxa_falha": 100.0
        }

    # --- Resumo Final do Ciclo ---
    end_time_cycle = time.monotonic()
    duration_cycle = end_time_cycle - overall_start_time
    logger.info("--- Resumo do Ciclo de Processamento ---")
    logger.info(f"Tempo Total: {duration_cycle:.2f}s")
    if resultado_ciclo:
        logger.info(f"Resultado: {resultado_ciclo['empresas_sucesso']}/{resultado_ciclo['total_empresas']} empresas processadas com sucesso ({100-resultado_ciclo['taxa_falha']:.1f}%)")
    logger.info("--- Fim do Ciclo ---")

    # Retornar resultado para o main decidir sobre exit code
    return resultado_ciclo


# --- Função Principal do Processo (Modificada para aceitar state_manager) ---
def run_process(
    api_client: SiegApiClient,
    excel_path: str,
    limit: int | None,
    state_manager_instance: StateManagerV2, # Passar a instância
    current_overall_seed_run: bool, # Informar se o ciclo geral está em modo seed
    transactional_manager: TransactionalFileManager = None # Gerenciador transacional
):
    """Executa UM ciclo completo de download incremental e validação para empresas listadas."""
    logger.info("--- Iniciando ciclo de processamento (run_process) --- ")
    start_time_cycle = time.monotonic()

    state_manager = state_manager_instance # Usar a instância passada

    end_date = datetime.now()
    start_date = end_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    logger.info(f"Período de busca (run_process): {start_date.strftime('%Y-%m-%d')} a {end_date.strftime('%Y-%m-%d')}")

    try:
        empresas = read_empresa_excel(excel_path, limit=limit)
        if not empresas:
            logger.error("Nenhuma empresa válida encontrada no arquivo Excel (run_process). Concluindo ciclo run_process.")
            return
    except FileNotFoundError:
        logger.error(f"Arquivo Excel não encontrado em: {excel_path} (run_process). Verifique. Concluindo ciclo run_process.")
        return
    except Exception as e_read_excel:
        logger.exception(f"Erro inesperado ao ler o arquivo Excel (run_process): {e_read_excel}. Concluindo ciclo run_process.")
        return

    total_empresas = len(empresas)
    logger.info(f"Processando {total_empresas} empresa(s) do arquivo: {excel_path} (run_process)")

    empresas_sucesso_ciclo = 0
    empresas_falha_ciclo = 0
    
    # Circuit breaker: rastrear falhas consecutivas por empresa
    consecutive_failures = {}  # CNPJ -> contador de falhas
    timeout_blacklist = {}  # CNPJ -> timestamp do último timeout
    MAX_CONSECUTIVE_FAILURES = 3  # Após 3 falhas consecutivas, pular temporariamente
    TIMEOUT_BLACKLIST_DURATION = 3600  # 1 hora em segundos
    # Nota: O contador é resetado quando a empresa é processada com sucesso

    # Loop de empresas com proteção individual por empresa
    for i, (cnpj_orig, nome_pasta) in enumerate(empresas):
        empresa_start_time = time.monotonic()
        logger.info(f"[{i+1}/{total_empresas}] --- Iniciando empresa {nome_pasta} ({cnpj_orig}) (run_process) ---")
        
        # Inicializar variáveis de controle FORA do try para garantir que existam no exception handler
        current_cnpj_norm = None  # Usar None ao invés de string vazia para melhor controle
        empresa_processo_com_falha_critica = False
        company_logger_handler = None  # Handler do log específico da empresa
        
        # Lista para armazenar relatórios temporários desta empresa
        # Formato: (temp_path, dest_dir, dest_filename)
        relatorios_temporarios_empresa = []
        
        try:

            try:
                current_cnpj_norm = normalize_cnpj(cnpj_orig)
                
                # Configurar log específico para esta empresa
                company_logger_handler = setup_company_logger(nome_pasta, current_cnpj_norm)
                log_empresa(nome_pasta, current_cnpj_norm, f"Iniciando processamento da empresa {nome_pasta}")
                
            except ValueError as e_cnpj:
                logger.error(f"[{cnpj_orig}] CNPJ inválido para {nome_pasta}: {e_cnpj}. Pulando empresa.")
                empresas_falha_ciclo += 1
                continue # Pula para a próxima empresa
            
            # Circuit breaker: verificar se a empresa está na blacklist de timeout
            if current_cnpj_norm in timeout_blacklist:
                tempo_decorrido = time.time() - timeout_blacklist[current_cnpj_norm]
                if tempo_decorrido < TIMEOUT_BLACKLIST_DURATION:
                    tempo_restante = TIMEOUT_BLACKLIST_DURATION - tempo_decorrido
                    logger.warning(f"[{current_cnpj_norm}] BLACKLIST TIMEOUT: Empresa teve timeout recente. Pulando por mais {tempo_restante/60:.1f} minutos.")
                    continue
                else:
                    # Remover da blacklist após o período
                    del timeout_blacklist[current_cnpj_norm]
                    logger.info(f"[{current_cnpj_norm}] Removida da blacklist de timeout. Tentando novamente.")
            
            # Circuit breaker: verificar se a empresa tem muitas falhas consecutivas
            if consecutive_failures.get(current_cnpj_norm, 0) >= MAX_CONSECUTIVE_FAILURES:
                logger.warning(f"[{current_cnpj_norm}] CIRCUIT BREAKER ATIVO: Empresa com {consecutive_failures[current_cnpj_norm]} falhas consecutivas. Pulando temporariamente.")
                continue  # Pula esta empresa neste ciclo

            # --- NOVA LÓGICA: VERIFICAÇÃO DO MÊS ANTERIOR ---
            today = datetime.now()
            # A verificação do mês anterior só ocorre nos primeiros 3 dias do mês atual.
            if today.day <= 3:
                logger.info(f"[{current_cnpj_norm}] Verificando mês anterior (estamos no dia {today.day} do mês).")
                log_empresa(nome_pasta, current_cnpj_norm, f"Iniciando verificação do mês anterior (dia {today.day})")
                
                # Try/except geral para todo o processamento do mês anterior
                try:
                    # Calcular datas para o mês anterior
                    data_primeiro_dia_mes_atual = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                    data_ultimo_dia_mes_anterior = data_primeiro_dia_mes_atual - timedelta(days=1)
                    data_primeiro_dia_mes_anterior = data_ultimo_dia_mes_anterior.replace(day=1)
                    
                    mes_anterior_key_str = data_primeiro_dia_mes_anterior.strftime("%Y-%m")
                    logger.info(f"[{current_cnpj_norm}] Mês anterior para verificação: {mes_anterior_key_str}")
                    log_empresa(nome_pasta, current_cnpj_norm, f"Verificando mês anterior: {mes_anterior_key_str}")

                    empresa_falhou_no_mes_anterior = False # Flag para controlar falha crítica no bloco do mês anterior

                    for report_type_str_prev, report_type_code_prev in [(XML_TYPE_MAP_REV[XML_TYPE_NFE], XML_TYPE_NFE),
                                                                        (XML_TYPE_MAP_REV[XML_TYPE_CTE], XML_TYPE_CTE)]:
                        if empresa_falhou_no_mes_anterior: # Se já falhou para NFe, não tenta CTe do mês anterior
                            break

                        logger.info(f"[{current_cnpj_norm}] Iniciando verificação de {report_type_str_prev} para o mês anterior: {mes_anterior_key_str}.")

                        # 1. Baixar (novamente) o relatório do mês anterior
                        try:
                            logger.info(f"[{current_cnpj_norm}] Tentando baixar relatório {report_type_str_prev} do mês anterior ({mes_anterior_key_str})...")
                            prev_month_report_downloaded, prev_month_report_empty, prev_month_temp_path, prev_month_dest_dir, prev_month_dest_filename = _try_download_and_process_report(
                                api_client, state_manager, current_cnpj_norm, nome_pasta,
                                report_type_str_prev, report_type_code_prev, data_primeiro_dia_mes_anterior
                            )
                            # Para mês anterior, usamos o caminho temporário para processamento
                            prev_month_df_report_path = prev_month_temp_path
                            
                            # Adicionar à lista de relatórios temporários se baixou com sucesso
                            if prev_month_report_downloaded and prev_month_temp_path and prev_month_dest_dir and prev_month_dest_filename:
                                relatorios_temporarios_empresa.append((prev_month_temp_path, prev_month_dest_dir, prev_month_dest_filename))
                        except TimeoutError as e_timeout:
                            # Tratamento específico para timeout absoluto
                            timeout_time = datetime.now()
                            logger.error(f"[{current_cnpj_norm}] [{timeout_time.strftime('%H:%M:%S')}] TIMEOUT ABSOLUTO ao baixar relatório {report_type_str_prev} do mês anterior: {e_timeout}")
                            # Adicionar à blacklist de timeout
                            timeout_blacklist[current_cnpj_norm] = time.time()
                            logger.warning(f"[{current_cnpj_norm}] Adicionada à blacklist de timeout por {TIMEOUT_BLACKLIST_DURATION/60:.0f} minutos.")
                            # Marcar falha crítica e pular para próxima empresa
                            empresa_falhou_no_mes_anterior = True
                            break  # Sair do loop de tipos de relatório
                        except Exception as e:
                            logger.error(f"[{current_cnpj_norm}] Erro não tratado ao baixar relatório {report_type_str_prev} do mês anterior: {e}")
                            logger.info(f"[{current_cnpj_norm}] Continuando com próximo tipo de relatório do mês anterior...")
                            continue

                        df_report_prev = None
                        report_keys_prev_month = set()
                        counts_report_prev_month: Dict[Tuple[str,str], int] = {}

                        if prev_month_report_downloaded and not prev_month_report_empty and prev_month_df_report_path:
                            try:
                                days_in_prev_month = monthrange(data_primeiro_dia_mes_anterior.year, data_primeiro_dia_mes_anterior.month)[1]
                                prev_month_end_date_loop = data_primeiro_dia_mes_anterior.replace(day=days_in_prev_month).date()
                                prev_month_start_date_loop = data_primeiro_dia_mes_anterior.date()

                                df_report_prev, report_keys_prev_month = read_report_data(
                                    prev_month_df_report_path,
                                    prev_month_start_date_loop, 
                                    prev_month_end_date_loop
                                )
                                if df_report_prev is None or df_report_prev.empty:
                                    logger.warning(f"[{current_cnpj_norm}] Relatório {report_type_str_prev} do mês anterior {mes_anterior_key_str} lido, mas vazio/inválido. ({prev_month_df_report_path})")
                                else:
                                    logger.info(f"[{current_cnpj_norm}] Relatório {report_type_str_prev} do mês anterior ({mes_anterior_key_str}) lido: {len(report_keys_prev_month)} chaves.")
                                    counts_report_prev_month = get_counts_by_role(df_report_prev, current_cnpj_norm, report_type_str_prev)
                                    logger.info(f"[{current_cnpj_norm}] Contagens {report_type_str_prev} do mês anterior ({mes_anterior_key_str}): {counts_report_prev_month}")
                            except Exception as e_read_rep_prev:
                                logger.error(f"[{current_cnpj_norm}] Erro ao ler dados do relatório {report_type_str_prev} do mês anterior em {prev_month_df_report_path}: {e_read_rep_prev}. XMLs não processados.")
                                df_report_prev = None 
                        elif prev_month_report_empty:
                            logger.info(f"[{current_cnpj_norm}] Nenhum relatório {report_type_str_prev} para o mês anterior {mes_anterior_key_str} (sem dados).")
                            continue
                        elif not prev_month_report_downloaded:
                            # Download falhou completamente
                            logger.error(f"[{current_cnpj_norm}] Falha ao obter relatório {report_type_str_prev} do mês anterior {mes_anterior_key_str}. XMLs não processados. Marcando como falha crítica.")
                            empresa_falhou_no_mes_anterior = True
                            continue

                        if df_report_prev is None or df_report_prev.empty:
                            logger.info(f"[{current_cnpj_norm}] Pulando download XMLs {report_type_str_prev} do mês anterior {mes_anterior_key_str} (relatório não disponível/válido).")
                            continue
                    
                        # 2. Verificar e Baixar XMLs faltantes do mês anterior
                        for papel_prev in ROLE_MAP.keys():
                            if empresa_falhou_no_mes_anterior: # Se já houve uma falha crítica, não continuar com outros papéis
                                break

                            combo_key_prev = (report_type_str_prev, papel_prev)
                            total_esperado_xmls_prev = counts_report_prev_month.get(combo_key_prev, 0)
                            skip_atual_xmls_prev = state_manager.get_skip(current_cnpj_norm, mes_anterior_key_str, report_type_str_prev, papel_prev)
                        
                            logger.info(f"[{current_cnpj_norm}] Mês Anterior ({mes_anterior_key_str}) - Verificando/baixando {report_type_str_prev}/{papel_prev}: Relatório={total_esperado_xmls_prev}, Skip Atual={skip_atual_xmls_prev}")

                            if skip_atual_xmls_prev < total_esperado_xmls_prev:
                                logger.info(f"[{current_cnpj_norm}] Mês Anterior ({mes_anterior_key_str}) - Encontrados {total_esperado_xmls_prev - skip_atual_xmls_prev} novos XMLs para {report_type_str_prev}/{papel_prev}. Iniciando download.")
                            else:
                                logger.info(f"[{current_cnpj_norm}] Mês Anterior ({mes_anterior_key_str}) - Nenhum XML novo para {report_type_str_prev}/{papel_prev} (Skip: {skip_atual_xmls_prev} >= Total: {total_esperado_xmls_prev}).")
                                continue # Próximo papel
                        
                            while skip_atual_xmls_prev < total_esperado_xmls_prev:
                                batch_take_prev = min(XML_DOWNLOAD_BATCH_SIZE, total_esperado_xmls_prev - skip_atual_xmls_prev)
                                logger.debug(f"[{current_cnpj_norm}] Mês Anterior ({mes_anterior_key_str}) - Baixando lote {report_type_str_prev}/{papel_prev} (Skip: {skip_atual_xmls_prev}, Take: {batch_take_prev})...")
                                xmls_base64_lote_prev = []
                                try:
                                    _, end_day_prev_month = monthrange(data_primeiro_dia_mes_anterior.year, data_primeiro_dia_mes_anterior.month)
                                    prev_month_end_dt_for_api = data_primeiro_dia_mes_anterior.replace(day=end_day_prev_month)

                                    xmls_base64_lote_prev = _download_xml_batch(
                                        api_client=api_client, cnpj_norm=current_cnpj_norm, report_type_code=report_type_code_prev,
                                        papel=papel_prev, skip=skip_atual_xmls_prev, take=batch_take_prev,
                                        month_start_dt=data_primeiro_dia_mes_anterior, 
                                        month_end_dt=prev_month_end_dt_for_api 
                                    )
                                    if not xmls_base64_lote_prev:
                                        if skip_atual_xmls_prev < total_esperado_xmls_prev:
                                            logger.warning(f"[{current_cnpj_norm}] Mês Anterior ({mes_anterior_key_str}) - API retornou lote XML vazio INESPERADO para {report_type_str_prev}/{papel_prev} (Skip={skip_atual_xmls_prev}, Total={total_esperado_xmls_prev}). Interrompendo para este papel.")
                                        else:
                                            logger.info(f"[{current_cnpj_norm}] Mês Anterior ({mes_anterior_key_str}) - API retornou lote XML vazio para {report_type_str_prev}/{papel_prev} com Skip={skip_atual_xmls_prev}. Fim para este papel.")
                                        break 
                                    logger.info(f"[{current_cnpj_norm}] Mês Anterior ({mes_anterior_key_str}) - Recebido lote de {len(xmls_base64_lote_prev)} XMLs para {report_type_str_prev}/{papel_prev} (Skip: {skip_atual_xmls_prev}).")
                                except (ValueError, RequestException) as api_err_xml_prev:
                                    logger.error(f"[{current_cnpj_norm}] Mês Anterior ({mes_anterior_key_str}) - Erro API/Rede ao baixar lote XML {report_type_str_prev}/{papel_prev} (Skip: {skip_atual_xmls_prev}): {api_err_xml_prev}. Marcando falha crítica para empresa.")
                                    empresa_falhou_no_mes_anterior = True 
                                    break 
                                except Exception as dl_err_xml_prev:
                                    logger.exception(f"[{current_cnpj_norm}] Mês Anterior ({mes_anterior_key_str}) - Erro inesperado ao baixar lote XML {report_type_str_prev}/{papel_prev} (Skip: {skip_atual_xmls_prev}): {dl_err_xml_prev}. Marcando falha crítica para empresa.", exc_info=True)
                                    empresa_falhou_no_mes_anterior = True 
                                    break 

                                if not xmls_base64_lote_prev: 
                                    break

                                try:
                                    logger.debug(f"[{current_cnpj_norm}] Mês Anterior ({mes_anterior_key_str}) - Salvando lote de {len(xmls_base64_lote_prev)} XMLs para {report_type_str_prev}/{papel_prev}...")
                                    if transactional_manager:
                                        save_stats_prev = transactional_manager.save_xmls_from_base64_transactional(
                                            base64_list=xmls_base64_lote_prev, empresa_cnpj=current_cnpj_norm,
                                            empresa_nome_pasta=nome_pasta,
                                            is_event=False,
                                            state_manager=state_manager
                                        )
                                    else:
                                        save_stats_prev = save_xmls_from_base64(
                                            base64_list=xmls_base64_lote_prev, empresa_cnpj=current_cnpj_norm,
                                            empresa_nome_pasta=nome_pasta,
                                            is_event=False,
                                            state_manager=state_manager
                                        )
                                    logger.info(f"[{current_cnpj_norm}] Mês Anterior ({mes_anterior_key_str}) - Resultado salvamento lote {report_type_str_prev}/{papel_prev}: {save_stats_prev}")
                                
                                    num_baixados_api_prev = len(xmls_base64_lote_prev)
                                    state_manager.update_skip(current_cnpj_norm, mes_anterior_key_str, report_type_str_prev, papel_prev, num_baixados_api_prev)
                                    skip_atual_xmls_prev += num_baixados_api_prev
                                except Exception as save_err_xml_prev:
                                    logger.exception(f"[{current_cnpj_norm}] Mês Anterior ({mes_anterior_key_str}) - ERRO CRÍTICO ao salvar estado/XMLs após lote {report_type_str_prev}/{papel_prev} (Skip {skip_atual_xmls_prev}). Marcando falha crítica para empresa. {save_err_xml_prev}", exc_info=True)
                                    empresa_falhou_no_mes_anterior = True 
                                    break 
                            # Fim do while de lotes XML para o mês anterior (papel)
                        # Fim do loop de papéis para o mês anterior
                    # --- FIM DO LOOP DE TIPOS DE RELATÓRIO PARA O MÊS ANTERIOR ---
                
                    if empresa_falhou_no_mes_anterior:
                        logger.error(f"[{current_cnpj_norm}] Falha crítica durante a verificação do mês anterior. Interrompendo processamento desta empresa para o ciclo atual.")
                        try:
                            state_manager.mark_empresa_as_failed(current_cnpj_norm) # Marca a empresa toda como falha no estado
                            state_manager.save_state() # Salva o estado para refletir a falha
                        except Exception as e_state:
                            logger.error(f"[{current_cnpj_norm}] Erro ao marcar empresa como falha no estado: {e_state}")
                        empresas_falha_ciclo += 1
                        # Incrementar contador de falhas consecutivas
                        consecutive_failures[current_cnpj_norm] = consecutive_failures.get(current_cnpj_norm, 0) + 1
                        continue # Pula para a próxima empresa
                    
                    logger.info(f"[{current_cnpj_norm}] Verificação do mês anterior ({mes_anterior_key_str}) concluída.")
                
                except socket.timeout as e_timeout:
                    timeout_time = datetime.now()
                    logger.error(f"[{current_cnpj_norm}] [{timeout_time.strftime('%H:%M:%S')}] TIMEOUT de socket durante verificação do mês anterior: {e_timeout}. Continuando com processamento normal...")
                except requests.exceptions.Timeout as e_req_timeout:
                    timeout_time = datetime.now()
                    logger.error(f"[{current_cnpj_norm}] [{timeout_time.strftime('%H:%M:%S')}] TIMEOUT de requests durante verificação do mês anterior: {e_req_timeout}. Continuando com processamento normal...")
                except TimeoutError as e_timeout_abs:
                    timeout_time = datetime.now()
                    logger.error(f"[{current_cnpj_norm}] [{timeout_time.strftime('%H:%M:%S')}] TIMEOUT ABSOLUTO durante verificação do mês anterior: {e_timeout_abs}. Continuando com processamento normal...")
                    # Adicionar à blacklist de timeout
                    timeout_blacklist[current_cnpj_norm] = time.time()
                    logger.warning(f"[{current_cnpj_norm}] Adicionada à blacklist de timeout por {TIMEOUT_BLACKLIST_DURATION/60:.0f} minutos.")
                except Exception as e_mes_anterior:
                    logger.exception(f"[{current_cnpj_norm}] ERRO não tratado durante verificação do mês anterior: {e_mes_anterior}. Continuando com processamento normal...", exc_info=True)
                    # Não marca como falha crítica - permite continuar com o processamento normal
                
            else: # Não estamos nos primeiros 3 dias do mês
                logger.debug(f"[{current_cnpj_norm}] Verificação do mês anterior não aplicável (hoje é dia {today.day}).")
            # --- FIM COMPLETO DA NOVA LÓGICA: VERIFICAÇÃO DO MÊS ANTERIOR ---

            # Determinar Meses Afetados (ex: apenas mês atual)
            affected_months_map: Dict[str, datetime] = {}
            current_scan_dt = start_date
            while current_scan_dt <= end_date:
                month_key = current_scan_dt.strftime("%Y-%m")
                affected_months_map[month_key] = current_scan_dt.replace(day=1)
                next_month_year = current_scan_dt.year
                next_month_month = current_scan_dt.month + 1
                if next_month_month > 12:
                    next_month_month = 1
                    next_month_year += 1
                if next_month_year > end_date.year or (next_month_year == end_date.year and next_month_month > end_date.month):
                    break
                current_scan_dt = datetime(next_month_year, next_month_month, 1)
            
            logger.info(f"[{current_cnpj_norm}] Meses afetados no período: {list(affected_months_map.keys())}")

            for month_key_str, month_start_dt_loop in affected_months_map.items():
                month_process_start_time = time.monotonic()
                logger.info(f"[{current_cnpj_norm}] Processando mês: {month_key_str}")
                
                # --- INICIALIZAÇÃO DE DADOS PARA O RESUMO DESTE MÊS ---
                # (Estes serão preenchidos durante o processamento de NFe e CTe para este mês)
                diff_results_mes: Dict[str, Dict[str, Any]] = {"NFe": {}, "CTe": {}}
                report_counts_mes: Dict[str, Dict[Tuple[str, str], int]] = {"NFe": {}, "CTe": {}}
                error_stats_mes: Dict[str, int] = {"parse_errors": 0, "info_errors": 0, "save_errors": 0}
                # download_stats_mes será para downloads individuais, se implementado por mês.
                # Por agora, o append_monthly_summary tem um download_stats geral da empresa.
                # Vamos assumir que o download individual (se houver) é feito no final da empresa.
                
                empresa_processo_com_falha_critica_neste_mes = False
                # --- FIM DA INICIALIZAÇÃO PARA O RESUMO DO MÊS ---
                
                if current_overall_seed_run:
                    logger.warning(f"[{current_cnpj_norm}] MODO SEED GERAL ATIVO: Resetando skips para NFe e CTe para o mês {month_key_str}.")
                    state_manager.reset_skip_for_report(current_cnpj_norm, month_key_str, "NFe")
                    state_manager.reset_skip_for_report(current_cnpj_norm, month_key_str, "CTe")

                for report_type_str, report_type_code in [(XML_TYPE_MAP_REV[XML_TYPE_NFE], XML_TYPE_NFE), 
                                                           (XML_TYPE_MAP_REV[XML_TYPE_CTE], XML_TYPE_CTE)]:
                    
                    logger.info(f"[{current_cnpj_norm}] Iniciando processamento de {report_type_str} para {month_key_str}.")
                    
                    pendency_details = state_manager.get_report_pendency_details(current_cnpj_norm, month_key_str, report_type_str)
                    if pendency_details:
                        pendency_status = pendency_details.get("status")
                        if pendency_status == "no_data_confirmed":
                            logger.info(f"[{current_cnpj_norm}] Relatório {report_type_str} para {month_key_str} já confirmado como 'sem dados'. Pulando.")
                            state_manager.update_report_download_status(current_cnpj_norm, month_key_str, report_type_str, "no_data_confirmed_skipped", message="Pulado: Relatório já confirmado como 'sem dados' em ciclo anterior.")
                            continue 
                        elif pendency_status == "max_attempts_reached":
                            logger.warning(f"[{current_cnpj_norm}] Relatório {report_type_str} para {month_key_str} atingiu máx. tentativas. Pulando.")
                            state_manager.update_report_download_status(current_cnpj_norm, month_key_str, report_type_str, "max_attempts_skipped", message="Pulado: Relatório atingiu máximo de tentativas de download em ciclos anteriores.")
                            continue 
                    
                    try:
                        logger.info(f"[{current_cnpj_norm}] Iniciando download do relatório {report_type_str} para {month_key_str}...")
                        report_downloaded_successfully, report_was_empty, temp_path, dest_dir, dest_filename = _try_download_and_process_report(
                            api_client, state_manager, current_cnpj_norm, nome_pasta, 
                            report_type_str, report_type_code, month_start_dt_loop
                        )
                        # df_report_path agora é o mesmo que temp_path
                        df_report_path = temp_path
                        
                        # Adicionar à lista de relatórios temporários se baixou com sucesso
                        if report_downloaded_successfully and temp_path and dest_dir and dest_filename:
                            relatorios_temporarios_empresa.append((temp_path, dest_dir, dest_filename))
                        
                        logger.info(f"[{current_cnpj_norm}] Download do relatório {report_type_str} concluído - Sucesso: {report_downloaded_successfully}, Vazio: {report_was_empty}")
                    except TimeoutError as e_timeout:
                        # Tratamento específico para timeout absoluto
                        timeout_time = datetime.now()
                        logger.error(f"[{current_cnpj_norm}] [{timeout_time.strftime('%H:%M:%S')}] TIMEOUT ABSOLUTO ao baixar relatório {report_type_str} ({month_key_str}): {e_timeout}")
                        # Adicionar à blacklist de timeout
                        timeout_blacklist[current_cnpj_norm] = time.time()
                        logger.warning(f"[{current_cnpj_norm}] Adicionada à blacklist de timeout por {TIMEOUT_BLACKLIST_DURATION/60:.0f} minutos.")
                        # Incrementar contador de falhas consecutivas
                        consecutive_failures[current_cnpj_norm] = consecutive_failures.get(current_cnpj_norm, 0) + 1
                        # Continuar com próximo tipo de relatório
                        continue
                    except Exception as e:
                        logger.error(f"[{current_cnpj_norm}] ERRO NÃO TRATADO ao processar relatório {report_type_str} para {month_key_str}: {e}")
                        logger.exception("Detalhes do erro:", exc_info=True)
                        logger.info(f"[{current_cnpj_norm}] >>> CONTINUANDO PROCESSAMENTO APÓS ERRO - Pulando para próximo tipo <<<")
                        report_downloaded_successfully = False
                        report_was_empty = False
                        df_report_path = None
                        continue

                    df_report = None
                    report_keys_period = set()
                    counts_report: Dict[Tuple[str,str], int] = {}

                    if report_downloaded_successfully and not report_was_empty and df_report_path:
                        try:
                            # Calcular o último dia do mês para end_date
                            days_in_month = monthrange(month_start_dt_loop.year, month_start_dt_loop.month)[1]
                            month_end_date_loop = month_start_dt_loop.replace(day=days_in_month).date()
                            current_month_start_date = month_start_dt_loop.date()

                            # Passar start_date e end_date para read_report_data
                            df_report, report_keys_period = read_report_data(df_report_path, current_month_start_date, month_end_date_loop)
                            # A antiga chamada era: df_report, report_keys_period, _ = read_report_data(df_report_path, report_type_str)
                            # A variável _ (terceiro item retornado) não existe mais na nova assinatura

                            if df_report is None or df_report.empty:
                                logger.warning(f"[{current_cnpj_norm}] Relatório {report_type_str} {month_key_str} lido, mas vazio/inválido. ({df_report_path})")
                            else:
                                logger.info(f"[{current_cnpj_norm}] Relatório {report_type_str} ({month_key_str}) lido: {len(report_keys_period)} chaves.")
                                counts_report = get_counts_by_role(df_report, current_cnpj_norm, report_type_str)
                                logger.info(f"[{current_cnpj_norm}] Contagens {report_type_str} ({month_key_str}): {counts_report}")
                        except Exception as e_read_rep:
                            logger.error(f"[{current_cnpj_norm}] Erro ao ler dados do relatório {report_type_str} em {df_report_path}: {e_read_rep}. XMLs não processados.")
                            state_manager.add_or_update_report_pendency(current_cnpj_norm, month_key_str, report_type_str, "pending_processing")
                            state_manager.update_report_download_status(current_cnpj_norm, month_key_str, report_type_str, "failed_processing_read", message=f"Erro ao ler dados do relatório salvo em {df_report_path}: {e_read_rep}")
                            df_report = None
                    
                    elif not report_downloaded_successfully and not report_was_empty:
                        logger.error(f"[{current_cnpj_norm}] Falha obter relatório {report_type_str} {month_key_str}. XMLs não processados.")
                        logger.info(f"[{current_cnpj_norm}] Relatório {report_type_str} {month_key_str} será reprocessado na próxima execução (pendência registrada).")
                        logger.info(f"[{current_cnpj_norm}] >>> CONTINUANDO PROCESSAMENTO - Pulando para próximo tipo de relatório <<<")
                        # Não marcar como falha crítica aqui - apenas continuar para o próximo tipo
                        continue
                    
                    elif report_was_empty:
                        logger.info(f"[{current_cnpj_norm}] Nenhum relatório {report_type_str} para {month_key_str} (sem dados).")
                        continue
                    
                    # Tratamento explícito para quando o download falha completamente
                    elif not report_downloaded_successfully:
                        logger.warning(f"[{current_cnpj_norm}] Falha no download do relatório {report_type_str} para {month_key_str} após todas as tentativas. Continuando com próximo tipo.")
                        continue

                    if df_report is None or df_report.empty:
                        logger.info(f"[{current_cnpj_norm}] Pulando download XMLs {report_type_str} de {month_key_str} (relatório não disponível/válido). Continuando com próximo tipo de relatório.")
                        continue

                    # Loop Papel (Download Incremental de XMLs)
                    for papel in ROLE_MAP.keys():
                        # ... (lógica de download de XMLs em lote como estava antes, adaptada para usar current_cnpj_norm)
                        combo_key = (report_type_str, papel)
                        total_esperado_xmls = counts_report.get(combo_key, 0)
                        skip_atual_xmls = state_manager.get_skip(current_cnpj_norm, month_key_str, report_type_str, papel)
                        logger.info(f"[{current_cnpj_norm}] Verificando/baixando {report_type_str}/{papel}: Relatório={total_esperado_xmls}, Skip Atual={skip_atual_xmls}")

                        while skip_atual_xmls < total_esperado_xmls:
                            batch_take = min(XML_DOWNLOAD_BATCH_SIZE, total_esperado_xmls - skip_atual_xmls)
                            logger.debug(f"[{current_cnpj_norm}] Baixando lote {report_type_str}/{papel} (Skip: {skip_atual_xmls}, Take: {batch_take})...")
                            xmls_base64_lote = []
                            try:
                                xmls_base64_lote = _download_xml_batch(
                                    api_client=api_client, cnpj_norm=current_cnpj_norm, report_type_code=report_type_code,
                                    papel=papel, skip=skip_atual_xmls, take=batch_take,
                                    month_start_dt=month_start_dt_loop, 
                                    month_end_dt=(month_start_dt_loop.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1) # Fim do mês
                                )
                                if not xmls_base64_lote:
                                    if skip_atual_xmls < total_esperado_xmls:
                                        logger.warning(f"[{current_cnpj_norm}] API retornou lote XML vazio INESPERADO para {report_type_str}/{papel} (Skip={skip_atual_xmls}, Total={total_esperado_xmls}). Interrompendo para este papel.")
                                    else:
                                        logger.info(f"[{current_cnpj_norm}] API retornou lote XML vazio para {report_type_str}/{papel} com Skip={skip_atual_xmls}. Fim para este papel.")
                                    break 
                                logger.info(f"[{current_cnpj_norm}] Recebido lote de {len(xmls_base64_lote)} XMLs para {report_type_str}/{papel} (Skip: {skip_atual_xmls}).")
                            except (ValueError, RequestException) as api_err_xml:
                                logger.error(f"[{current_cnpj_norm}] Erro API/Rede ao baixar lote XML {report_type_str}/{papel} (Skip: {skip_atual_xmls}): {api_err_xml}. Interrompendo para este papel.")
                                logger.info(f"[{current_cnpj_norm}] >>> CONTINUANDO - Pulando para próximo papel/tipo após erro de API <<<")
                                # Removendo marcação de falha crítica para não impedir processamento de outras empresas
                                break 
                            except Exception as dl_err_xml:
                                logger.exception(f"[{current_cnpj_norm}] Erro inesperado ao baixar lote XML {report_type_str}/{papel} (Skip: {skip_atual_xmls}): {dl_err_xml}. Interrompendo para este papel.", exc_info=True)
                                logger.info(f"[{current_cnpj_norm}] >>> CONTINUANDO - Pulando para próximo papel/tipo após erro inesperado <<<")
                                # Removendo marcação de falha crítica para não impedir processamento de outras empresas
                                break
                            
                            if not xmls_base64_lote: # Segurança adicional
                                break

                            try:
                                logger.debug(f"[{current_cnpj_norm}] Salvando lote de {len(xmls_base64_lote)} XMLs para {report_type_str}/{papel}...")
                                if transactional_manager:
                                    save_stats = transactional_manager.save_xmls_from_base64_transactional(
                                        base64_list=xmls_base64_lote, empresa_cnpj=current_cnpj_norm,
                                        empresa_nome_pasta=nome_pasta,
                                        is_event=False,
                                        state_manager=state_manager
                                    )
                                else:
                                    save_stats = save_xmls_from_base64(
                                        base64_list=xmls_base64_lote, empresa_cnpj=current_cnpj_norm,
                                        empresa_nome_pasta=nome_pasta,
                                        is_event=False,
                                        state_manager=state_manager
                                    )
                                logger.info(f"[{current_cnpj_norm}] Resultado salvamento lote {report_type_str}/{papel}: {save_stats}")
                                # ... (atualizar contadores de erro se necessário) ...
                                num_baixados_api = len(xmls_base64_lote)
                                state_manager.update_skip(current_cnpj_norm, month_key_str, report_type_str, papel, num_baixados_api)
                                skip_atual_xmls += num_baixados_api
                            except Exception as save_err_xml:
                                logger.exception(f"[{current_cnpj_norm}] ERRO ao salvar XMLs após lote {report_type_str}/{papel} (Skip {skip_atual_xmls}). Continuando com próximo lote. {save_err_xml}", exc_info=True)
                                # Não marcar como falha crítica - apenas continuar
                                break # Sai do while de lotes para este papel específico
                        # Fim do while de lotes XML
                        if empresa_processo_com_falha_critica:
                            logger.warning(f"[{current_cnpj_norm}] Houve falhas no processamento de {report_type_str}/{papel}, mas continuando com outros papéis/tipos.")
                            # Não usar break aqui para permitir continuar com outros papéis
                    # Fim do loop de papéis
                    if empresa_processo_com_falha_critica:
                        logger.warning(f"[{current_cnpj_norm}] Houve falhas no processamento de {report_type_str}, mas continuando com outros tipos de relatório.")
                        # Não usar break aqui para permitir continuar com outros tipos
                    
                    # --- VALIDAÇÃO e AGREGAÇÃO DE DADOS DO TIPO DE RELATÓRIO (NFe ou CTe) PARA O MÊS ---
                    validation_result_mes_tipo = {} # Inicializa o dicionário para este tipo
                    local_keys_mes = set() # Inicializa o conjunto de chaves locais
                    try:
                        # 1. Obter chaves locais
                        doc_type_path = PRIMARY_SAVE_BASE_PATH / str(month_start_dt_loop.year) / nome_pasta / f"{month_start_dt_loop.month:02d}" / report_type_str
                        local_keys_mes = get_local_keys(doc_type_path)
                        logger.info(f"[{current_cnpj_norm}] Encontradas {len(local_keys_mes)} chaves locais para {report_type_str} em {doc_type_path}")

                        # 1.5 CORREÇÃO: Marcar XMLs locais existentes como importados se ainda não estiverem marcados
                        # Isso resolve o problema de XMLs que foram pulados pelo skip_count mas nunca marcados
                        if state_manager and local_keys_mes:
                            # Marcar TODOS os XMLs locais válidos (chave de 44 caracteres), não apenas os do relatório atual
                            # Correção 20/08: XMLs podem ter sido removidos do relatório mas ainda são válidos localmente
                            xmls_locais_legitimos = {key for key in local_keys_mes if len(key) == 44}
                            
                            if xmls_locais_legitimos:
                                # CORREÇÃO 21/08: Forçar marcação de TODOS os XMLs locais
                                month_key_import = f"{month_start_dt_loop.month:02d}-{month_start_dt_loop.year:04d}"  # MM-YYYY
                                
                                # Obter XMLs já marcados
                                ja_marcados = set()
                                state_data = state_manager._load_month_state(month_key_import)
                                if current_cnpj_norm in state_data.get("processed_xml_keys", {}):
                                    if month_key_import in state_data["processed_xml_keys"][current_cnpj_norm]:
                                        if report_type_str in state_data["processed_xml_keys"][current_cnpj_norm][month_key_import]:
                                            ja_marcados = set(state_data["processed_xml_keys"][current_cnpj_norm][month_key_import][report_type_str])
                                
                                # Calcular novos XMLs
                                nao_marcados = list(xmls_locais_legitimos - ja_marcados)
                                
                                # FORÇAR gravação de TODOS os XMLs locais (substituir lista completa)
                                if "processed_xml_keys" not in state_data:
                                    state_data["processed_xml_keys"] = {}
                                if current_cnpj_norm not in state_data["processed_xml_keys"]:
                                    state_data["processed_xml_keys"][current_cnpj_norm] = {}
                                if month_key_import not in state_data["processed_xml_keys"][current_cnpj_norm]:
                                    state_data["processed_xml_keys"][current_cnpj_norm][month_key_import] = {}
                                
                                # SOBRESCREVER com TODOS os XMLs locais
                                state_data["processed_xml_keys"][current_cnpj_norm][month_key_import][report_type_str] = list(xmls_locais_legitimos)
                                
                                # Atualizar cache do StateManager e salvar
                                state_manager._state_cache[month_key_import] = state_data
                                state_manager._save_month_state(month_key_import)
                                
                                if nao_marcados:
                                    logger.info(f"[{current_cnpj_norm}] CORREÇÃO: Marcados {len(nao_marcados)} XMLs {report_type_str} existentes como importados (eram skipped mas não marcados)")
                                    # Log alguns exemplos para transparência
                                    if len(nao_marcados) <= 5:
                                        logger.info(f"[{current_cnpj_norm}] XMLs corrigidos: {nao_marcados}")
                                    else:
                                        logger.info(f"[{current_cnpj_norm}] Primeiros 5 XMLs corrigidos: {nao_marcados[:5]}... (total: {len(nao_marcados)})")
                                    # Log específico da empresa
                                    log_empresa(nome_pasta, current_cnpj_norm, f"CORREÇÃO RETROATIVA: {len(nao_marcados)} XMLs {report_type_str} marcados como importados")
                                    # Contabilizar para relatório
                                    xmls_corrigidos_retroativos[report_type_str] += len(nao_marcados)
                        
                        # 2. Comparar com chaves do relatório (report_keys_period já obtido anteriormente)
                        faltantes_set = report_keys_period - local_keys_mes
                        extras_set = local_keys_mes - report_keys_period

                        # 3. Classificar Faltantes (Usando core.report_validator)
                        faltantes_validos_tipo_set = set()
                        faltantes_ignorados_tipo_set = set()
                        if faltantes_set and df_report is not None and not df_report.empty:
                            # Somente classifica se houver faltantes e o dataframe do relatório estiver disponível
                            classified_faltantes = classify_keys_by_role(faltantes_set, df_report, current_cnpj_norm, report_type_str)
                            valid_roles = {"Emitente", "Destinatario", "Tomador"} # Papéis considerados válidos

                            # classified_faltantes é Dict[Tuple[str, str], Set[str]]
                            # Onde a chave é (doc_type_param, papel)
                            for (doc_type_classificado, papel_classificado), chaves_classif in classified_faltantes.items():
                                # Adicionar verificação se doc_type_classificado corresponde ao report_type_str (embora deva ser sempre)
                                if doc_type_classificado == report_type_str:
                                    if papel_classificado in valid_roles:
                                        faltantes_validos_tipo_set.update(chaves_classif)
                                    else:
                                        logger.debug(f"[{current_cnpj_norm}] Chaves para {report_type_str} com papel '{papel_classificado}' (não em valid_roles) serão ignoradas: {list(chaves_classif)[:3]}...")
                                        faltantes_ignorados_tipo_set.update(chaves_classif)
                                else:
                                    # Este caso não deveria ocorrer se classify_keys_by_role funciona como esperado
                                    logger.warning(f"[{current_cnpj_norm}] Chaves classificadas com tipo de documento inesperado. Esperado: {report_type_str}, Obtido: {doc_type_classificado}. Papel: {papel_classificado}. Chaves: {list(chaves_classif)[:3]}... Serão ignoradas.")
                                    faltantes_ignorados_tipo_set.update(chaves_classif)

                            # Tratar chaves que não foram classificadas (se houver)
                            # Esta lógica precisa ser revisada, pois classify_keys_by_role já lida com chaves não encontradas ou sem papel.
                            # O retorno de classify_keys_by_role já contém apenas as chaves que puderam ser associadas a um papel (válido ou não)
                            # com base no relatório. Se uma chave de faltantes_set não aparece em classified_faltantes.values(),
                            # significa que ela não foi encontrada no relatório ou _get_papel_empresa retornou None.
                            # A função classify_keys_by_role já loga isso.
                            # A questão é se devemos adicionar essas "não classificadas por papel" aos válidos ou ignorados aqui.
                            # A implementação anterior (antes da minha sugestão) as considerava "ignoradas"

                            # Recalcular o conjunto de todas as chaves que foram efetivamente classificadas
                            chaves_efetivamente_classificadas = set()
                            for chaves_do_papel in classified_faltantes.values():
                                chaves_efetivamente_classificadas.update(chaves_do_papel)

                            chaves_nao_classificadas_no_relatorio = faltantes_set - chaves_efetivamente_classificadas

                            if chaves_nao_classificadas_no_relatorio:
                                logger.warning(f"[{current_cnpj_norm}] {len(chaves_nao_classificadas_no_relatorio)} chaves {report_type_str} faltantes não foram encontradas no relatório ou não tiveram papel determinado pela função de classificação ({month_key_str}). Consideradas ignoradas. Ex: {list(chaves_nao_classificadas_no_relatorio)[:3]}")
                                faltantes_ignorados_tipo_set.update(chaves_nao_classificadas_no_relatorio)

                        elif faltantes_set: 
                             # Se houve faltantes mas não foi possível classificar (df_report indisponível)
                             logger.warning(f"[{current_cnpj_norm}] Não foi possível classificar {len(faltantes_set)} chaves {report_type_str} faltantes em {month_key_str} (Relatório DF indisponível). Consideradas como VÁLIDAS por segurança.")
                             faltantes_validos_tipo_set = faltantes_set # Assume como válidas por precaução
                        # else: Nenhum faltante, os sets já estão vazios
                            
                        faltantes_validos_list = sorted(list(faltantes_validos_tipo_set))
                        faltantes_ignorados_list = sorted(list(faltantes_ignorados_tipo_set))
                        extras_list = sorted(list(extras_set))

                        # 4. Montar dicionário diff_results para este tipo
                        validation_result_mes_tipo = {
                            'total_relatorio_periodo': len(report_keys_period),
                            'total_local': len(local_keys_mes), # Total de arquivos locais únicos
                            'faltantes': faltantes_validos_list, 
                            'faltantes_ignorados': faltantes_ignorados_list,
                            'extras': extras_list,
                            # Status e Message serão definidos com base nos resultados
                        }

                        # Define Status e Mensagem
                        if not faltantes_validos_list and not extras_list:
                            if faltantes_ignorados_list:
                                validation_result_mes_tipo['status'] = "OK_IGNORADOS"
                                validation_result_mes_tipo['message'] = f"OK (Apenas {len(faltantes_ignorados_list)} ignorados)"
                            else:
                                validation_result_mes_tipo['status'] = "OK"
                                validation_result_mes_tipo['message'] = "OK (100%)"
                        else:
                            validation_result_mes_tipo['status'] = "ATENCAO"
                            parts = []
                            if faltantes_validos_list: parts.append(f"{len(faltantes_validos_list)} Faltantes Válidos")
                            if faltantes_ignorados_list: parts.append(f"{len(faltantes_ignorados_list)} Ignorados")
                            if extras_list: parts.append(f"{len(extras_list)} Extras")
                            validation_result_mes_tipo['message'] = f"Atenção ({', '.join(parts)})"
                        
                        logger.info(f"[{current_cnpj_norm}] Resultado Validação {report_type_str} ({month_key_str}): {validation_result_mes_tipo['status']} - {validation_result_mes_tipo['message']}")

                    except Exception as e_val:
                        logger.error(f"[{current_cnpj_norm}] Erro durante validação Relatório vs Local para {report_type_str} ({month_key_str}): {e_val}")
                        # Define um status de erro para o diff_results deste tipo
                        validation_result_mes_tipo = {
                            'status': 'ERRO_VALIDACAO',
                            'message': f'Erro validação: {e_val}',
                            'total_relatorio_periodo': len(report_keys_period),
                            'total_local': 'N/A',
                            'faltantes': [], 'faltantes_ignorados': [], 'extras': []
                        }
                        # Não marcar como falha crítica - apenas registrar o erro e continuar

                    # 5. Armazenar resultados da validação e contagens do relatório
                    if report_type_str == "NFe":
                        report_counts_mes["NFe"] = counts_report # counts_report é do escopo do tipo de relatório
                        diff_results_mes["NFe"] = validation_result_mes_tipo
                        # logger.warning(f"[{current_cnpj_norm}] Lógica de validação para NFe (diff_results) do mês {month_key_str} precisa ser implementada aqui para o resumo TXT.") # REMOVIDO PLACEHOLDER
                    elif report_type_str == "CTe":
                        report_counts_mes["CTe"] = counts_report
                        diff_results_mes["CTe"] = validation_result_mes_tipo
                        # logger.warning(f"[{current_cnpj_norm}] Lógica de validação para CTe (diff_results) do mês {month_key_str} precisa ser implementada aqui para o resumo TXT.") # REMOVIDO PLACEHOLDER
                    
                    # TODO: Acumulação de error_stats_mes precisa ser revisada.
                    # A variável 'save_stats' é definida dentro do loop de download de XML.
                    # Precisamos garantir que 'error_stats_mes' acumule os erros de NFe e CTe.
                    # error_stats_mes["parse_errors"] += save_stats.get("parse_errors", 0)
                    # error_stats_mes["info_errors"] += save_stats.get("info_errors", 0)
                    # error_stats_mes["save_errors"] += save_stats.get("save_errors", 0)
                    # --- FIM DA VALIDAÇÃO E AGREGAÇÃO DO TIPO DE RELATÓRIO ---

                # Fim do loop de tipos de relatório
                if empresa_processo_com_falha_critica: # Se falha crítica em NFe ou CTe, propaga para o mês
                    empresa_processo_com_falha_critica_neste_mes = True
                    logger.warning(f"[{current_cnpj_norm}] Houve falhas no processamento do mês {month_key_str}, mas tentaremos gerar o resumo mesmo assim.")
                    # Não usar break aqui - continuar processando outros meses
                
                # --- DOWNLOAD INDIVIDUAL DE CHAVES FALTANTES ---
                # Verificar se há chaves faltantes válidas para download individual
                total_faltantes_validos = 0
                all_faltantes_validos = []

                for doc_type in ['NFe', 'CTe']:
                    if doc_type in diff_results_mes:
                        faltantes_validos = diff_results_mes[doc_type].get('faltantes', [])
                        if faltantes_validos:
                            total_faltantes_validos += len(faltantes_validos)
                            all_faltantes_validos.extend(faltantes_validos)
                            logger.info(f"[{current_cnpj_norm}] {doc_type}: {len(faltantes_validos)} chaves faltantes válidas identificadas.")

                # Inicializar estatísticas de download individual
                download_stats_mes = None
                
                # Inicializar contadores de correção retroativa
                xmls_corrigidos_retroativos = {'NFe': 0, 'CTe': 0}

                # Executar download individual se necessário (SEM LIMIAR)
                if all_faltantes_validos:
                    logger.info(f"[{current_cnpj_norm}] Iniciando download individual de {total_faltantes_validos} chaves faltantes...")

                    try:
                        download_result = download_missing_xmls(
                            keys_to_download=all_faltantes_validos,
                            api_client=api_client,
                            empresa_cnpj=current_cnpj_norm,
                            path_info={'ano': str(month_start_dt_loop.year), 'mes': f"{month_start_dt_loop.month:02d}", 'nome_pasta': nome_pasta},
                            base_xml_path=PRIMARY_SAVE_BASE_PATH
                        )

                        if download_result:
                            total_downloaded = len(download_result.get('success', []))
                            total_failed = len(download_result.get('failed', []))

                            # Preparar estatísticas para o relatório
                            download_stats_mes = {
                                'tentativas': len(all_faltantes_validos),
                                'sucesso': total_downloaded,
                                'falha_download': total_failed,  # Assumindo que falhas são de download
                                'falha_salvar': 0,  # Por enquanto, não separamos tipos de falha
                                'xmls_corrigidos_retroativos': xmls_corrigidos_retroativos  # Adicionar correções retroativas
                            }

                            logger.success(f"[{current_cnpj_norm}] Download individual concluído: {total_downloaded} XMLs baixados, {total_failed} falharam.")

                            # Re-validar após download individual
                            logger.info(f"[{current_cnpj_norm}] Re-validando após download individual...")
                            for doc_type in ['NFe', 'CTe']:
                                if doc_type in diff_results_mes and diff_results_mes[doc_type].get('faltantes'):
                                    # Re-extrair chaves locais
                                    doc_path = month_dir_path / doc_type
                                    if doc_path.exists():
                                        local_keys = get_local_keys(doc_path)
                                        logger.info(f"[{current_cnpj_norm}] {doc_type}: {len(local_keys)} chaves locais após download individual.")

                                        # Atualizar diff_results_mes com novos dados
                                        if doc_path.exists() and doc_type in diff_results_mes:
                                            # Re-calcular faltantes após download
                                            report_keys = set(diff_results_mes[doc_type].get('faltantes', []))
                                            downloaded_keys = set(download_result.get('success', []))
                                            # Filtrar apenas as chaves deste doc_type que foram baixadas
                                            doc_downloaded = downloaded_keys.intersection(report_keys)
                                            # Atualizar lista de faltantes removendo as baixadas
                                            new_faltantes = report_keys - doc_downloaded
                                            diff_results_mes[doc_type]['faltantes'] = sorted(list(new_faltantes))
                                            logger.info(f"[{current_cnpj_norm}] {doc_type}: {len(new_faltantes)} chaves ainda faltantes após download individual.")
                        else:
                            logger.warning(f"[{current_cnpj_norm}] Download individual não retornou resultados ou falhou.")

                    except Exception as e_download_individual:
                        logger.error(f"[{current_cnpj_norm}] Erro durante download individual: {e_download_individual}")
                else:
                    # Não houve download individual, mas ainda precisamos registrar correções retroativas
                    if xmls_corrigidos_retroativos['NFe'] > 0 or xmls_corrigidos_retroativos['CTe'] > 0:
                        download_stats_mes = {
                            'tentativas': 0,
                            'sucesso': 0,
                            'falha_download': 0,
                            'falha_salvar': 0,
                            'xmls_corrigidos_retroativos': xmls_corrigidos_retroativos
                        }
                        logger.info(f"[{current_cnpj_norm}] Sem download individual, mas {xmls_corrigidos_retroativos['NFe'] + xmls_corrigidos_retroativos['CTe']} XMLs corrigidos retroativamente")
                # --- FIM DO DOWNLOAD INDIVIDUAL ---

                # --- COLETA DE CONTAGENS LOCAIS FINAIS PARA O MÊS ---
                logger.info(f"[{current_cnpj_norm}] Coletando contagens locais finais para o mês {month_key_str}...")
                month_dir_path = PRIMARY_SAVE_BASE_PATH / str(month_start_dt_loop.year) / nome_pasta / f"{month_start_dt_loop.month:02d}"
                final_counts_mes = count_local_files(month_dir_path)
                # ----------------------------------------------------

                # --- GERAÇÃO DO RESUMO DE AUDITORIA .TXT PARA O MÊS ---
                # (Mesmo que haja falha crítica no mês, tentamos gerar um resumo com o que temos)
                try:
                    logger.info(f"[{current_cnpj_norm}] Gerando resumo de auditoria .txt para {nome_pasta} - Mês: {month_key_str}")
                    
                    summary_filename = f"Resumo_Auditoria_{nome_pasta}_{month_start_dt_loop.year}_{month_start_dt_loop.month:02d}.txt"
                    # Salva o resumo dentro da pasta do mês da empresa (ex: .../ANO/NOME_EMPRESA/MES/resumo.txt)
                    summary_file_path = month_dir_path / summary_filename

                    # Obter período final correto para o relatório do mês
                    days_in_month_val = monthrange(month_start_dt_loop.year, month_start_dt_loop.month)[1]
                    month_end_dt_val = month_start_dt_loop.replace(day=days_in_month_val)

                    append_monthly_summary(
                        summary_file_path=summary_file_path,
                        execution_time=datetime.now(), # Usar o tempo atual da geração do resumo
                        empresa_cnpj=cnpj_orig, # Usar o CNPJ original para o relatório
                        empresa_nome=nome_pasta,
                        period_start=month_start_dt_loop.date(),
                        period_end=month_end_dt_val.date(), # Usar o fim do mês correto
                        diff_results=diff_results_mes, # Dados de NFe e CTe para este mês (ATUALIZADOS após download individual)
                        report_counts=report_counts_mes, # Dados de NFe e CTe para este mês
                        download_stats=download_stats_mes, # AGORA com dados reais do download individual
                        final_counts=final_counts_mes,
                        error_stats=error_stats_mes 
                    )
                except Exception as e_report_txt:
                    logger.error(f"[{current_cnpj_norm}] Erro ao gerar/salvar resumo de auditoria .txt para {nome_pasta} (Mês: {month_key_str}): {e_report_txt}")
                # --- FIM DA GERAÇÃO DO RESUMO .TXT DO MÊS ---

                if empresa_processo_com_falha_critica_neste_mes: # Se houve falha crítica no mês, interrompe processamento da empresa.
                    logger.warning(f"[{current_cnpj_norm}] Houve falhas no processamento do mês {month_key_str}, mas continuando com outros meses.")
                    # Não usar break - continuar com outros meses

                month_duration = time.monotonic() - month_process_start_time
                logger.info(f"[{current_cnpj_norm}] Mês {month_key_str} finalizado. Duração: {month_duration:.2f}s")
            # Fim do loop de meses

            # Download de Eventos de Cancelamento (após todos os meses da empresa serem processados para relatórios e XMLs principais)
            # Esta lógica de eventos de cancelamento é para o período GERAL da execução, não por mês individualmente.
            # O resumo mensal já terá contado os eventos salvos nas pastas daquele mês.
            # Se quisermos adicionar uma seção de "Eventos Baixados NESTA EXECUÇÃO", seria aqui.
            if not empresa_processo_com_falha_critica: # 'empresa_processo_com_falha_critica' é a flag geral da empresa
                try:
                    logger.info(f"[{current_cnpj_norm}] Iniciando download de eventos de cancelamento para o período {start_date.strftime('%Y-%m-%d')} a {end_date.strftime('%Y-%m-%d')}...")
                    eventos_base64 = download_cancel_events(api_client, current_cnpj_norm, start_date, end_date)
                    if eventos_base64:
                        logger.info(f"[{current_cnpj_norm}] Recebidos {len(eventos_base64)} eventos de cancelamento. Salvando...")
                        if transactional_manager:
                            save_stats_eventos = transactional_manager.save_xmls_from_base64_transactional(
                                base64_list=eventos_base64, empresa_cnpj=current_cnpj_norm,
                                empresa_nome_pasta=nome_pasta, is_event=True,
                                state_manager=state_manager
                            )
                        else:
                            save_stats_eventos = save_xmls_from_base64(
                                base64_list=eventos_base64, empresa_cnpj=current_cnpj_norm,
                                empresa_nome_pasta=nome_pasta, is_event=True,
                                state_manager=state_manager
                            )
                        logger.info(f"[{current_cnpj_norm}] Resultado salvamento eventos de cancelamento: {save_stats_eventos}")
                    else:
                        logger.info(f"[{current_cnpj_norm}] Nenhum evento de cancelamento encontrado ou retornado pela API para o período.")
                except Exception as event_err:
                    logger.exception(f"[{current_cnpj_norm}] Erro inesperado ao baixar/salvar eventos de cancelamento: {event_err}", exc_info=True)
            
            # --- Coleta Contagem Final Local e Atualiza Resumo Mensal ---
            # Esta parte pode ser expandida para gerar um resumo por empresa ao final
            # ... COMENTÁRIO ORIGINAL REMOVIDO, POIS O RESUMO AGORA É MENSAL
            
            # --- Copiar relatórios temporários para destinos finais ---
            if relatorios_temporarios_empresa:
                logger.info(f"[{current_cnpj_norm}] Copiando {len(relatorios_temporarios_empresa)} relatórios temporários para destinos finais...")
                relatorios_copiados = 0
                relatorios_falha_copia = 0
                
                for temp_path, dest_dir, dest_filename in relatorios_temporarios_empresa:
                    if copy_report_to_final_destination(temp_path, dest_dir, dest_filename):
                        relatorios_copiados += 1
                    else:
                        relatorios_falha_copia += 1
                        # Relatório temporário é mantido se falhar a cópia
                
                if relatorios_falha_copia > 0:
                    logger.warning(f"[{current_cnpj_norm}] {relatorios_falha_copia} relatórios não puderam ser copiados (possível arquivo aberto). Arquivos temporários mantidos.")
                else:
                    logger.success(f"[{current_cnpj_norm}] Todos os {relatorios_copiados} relatórios foram copiados com sucesso.")

            if not empresa_processo_com_falha_critica:
                empresas_sucesso_ciclo += 1
                # Resetar contador de falhas consecutivas em caso de sucesso
                if current_cnpj_norm in consecutive_failures:
                    del consecutive_failures[current_cnpj_norm]
                logger.success(f"[{current_cnpj_norm}] Empresa {nome_pasta} processada com sucesso.")
                
                # Log específico da empresa
                if current_cnpj_norm:
                    log_empresa(nome_pasta, current_cnpj_norm, f"Empresa processada com SUCESSO", "INFO")
            else:
                empresas_falha_ciclo += 1
                # Incrementar contador de falhas consecutivas
                consecutive_failures[current_cnpj_norm] = consecutive_failures.get(current_cnpj_norm, 0) + 1
                logger.error(f"[{current_cnpj_norm}] Empresa {nome_pasta} processada com UMA OU MAIS FALHAS CRÍTICAS. (Falhas consecutivas: {consecutive_failures[current_cnpj_norm]})")
                
                # Log específico da empresa
                if current_cnpj_norm:
                    log_empresa(nome_pasta, current_cnpj_norm, f"Empresa processada com FALHAS CRÍTICAS (Falhas consecutivas: {consecutive_failures[current_cnpj_norm]})", "ERROR")

            empresa_duration = time.monotonic() - empresa_start_time
            logger.info(f"[{i+1}/{total_empresas}] --- Fim processamento empresa {nome_pasta} ({cnpj_orig}) --- Duração: {empresa_duration:.2f}s ---")
            
            # Log final específico da empresa
            if current_cnpj_norm:
                log_empresa(nome_pasta, current_cnpj_norm, f"Processamento finalizado. Duração: {empresa_duration:.2f}s")
                # Limpeza do logger específico da empresa
                cleanup_company_logger(nome_pasta, current_cnpj_norm)

        except Exception as e_empresa:
            logger.exception(
                f"[{cnpj_orig}] Erro inesperado durante o processamento de {nome_pasta}. "
                "Marcando a empresa como falha e continuando para a próxima.",
                exc_info=True
            )
            logger.info(f"[{cnpj_orig}] >>> SEGURANÇA: CONTINUANDO APÓS ERRO DE EMPRESA <<<")
            
            # Log específico da empresa para erro inesperado
            if current_cnpj_norm:
                log_empresa(nome_pasta, current_cnpj_norm, f"ERRO INESPERADO: {str(e_empresa)}", "ERROR")
                # Limpeza do logger específico da empresa
                cleanup_company_logger(nome_pasta, current_cnpj_norm)
            
            # Tentar salvar o estado mesmo após erro
            try:
                state_manager.save_state()
                logger.info(f"[{cnpj_orig}] Estado salvo após erro de empresa")
            except Exception as e_save:
                logger.error(f"[{cnpj_orig}] Falha ao salvar estado após erro: {e_save}")
            empresas_falha_ciclo += 1
            # Incrementar contador de falhas consecutivas se temos o CNPJ normalizado
            if current_cnpj_norm is not None:
                consecutive_failures[current_cnpj_norm] = consecutive_failures.get(current_cnpj_norm, 0) + 1
            continue  # vai para a próxima empresa sem encerrar o ciclo
        # Fim do loop de empresas

    # Log do estado do circuit breaker
    if consecutive_failures:
        logger.warning(f"Circuit Breaker - Empresas com falhas consecutivas: {consecutive_failures}")
    
    logger.info("Salvando estado final do ciclo (run_process)...")
    try:
        state_manager.save_state()
        logger.info("Estado salvo com sucesso")
    except Exception as e:
        logger.error(f"ERRO ao salvar estado final do ciclo: {e}. Dados podem ter sido perdidos.")
    
    cycle_duration = time.monotonic() - start_time_cycle

    # Alarme de falha global - verificar se muitas empresas falharam
    taxa_falha = (empresas_falha_ciclo / total_empresas * 100) if total_empresas > 0 else 0

    if empresas_falha_ciclo > 0:
        if taxa_falha >= 50:  # Mais de 50% das empresas falharam
            logger.critical(f"ALERTA CRÍTICO: {empresas_falha_ciclo}/{total_empresas} empresas falharam ({taxa_falha:.1f}%). Possível problema sistêmico!")
        elif taxa_falha >= 20:  # Mais de 20% das empresas falharam
            logger.error(f"ALERTA: {empresas_falha_ciclo}/{total_empresas} empresas falharam ({taxa_falha:.1f}%). Verificar logs para padrões.")
        else:
            logger.warning(f"Algumas empresas falharam: {empresas_falha_ciclo}/{total_empresas} ({taxa_falha:.1f}%).")

    logger.info(f"--- Fim do ciclo de processamento (run_process) --- Duração: {cycle_duration:.2f}s. Empresas Sucesso: {empresas_sucesso_ciclo}, Falha: {empresas_falha_ciclo} ({taxa_falha:.1f}%) ---")

    # Retornar informações para o chamador decidir sobre exit code
    return {
        "total_empresas": total_empresas,
        "empresas_sucesso": empresas_sucesso_ciclo,
        "empresas_falha": empresas_falha_ciclo,
        "taxa_falha": taxa_falha
    }


# --- Ponto de Entrada Principal --- #
def main():
    """Função principal para executar o script via CLI."""
    parser = argparse.ArgumentParser(description="Script para download e processamento de XMLs da API SIEG.")
    parser.add_argument(
        "--excel",
        required=True,
        help="Caminho para o arquivo Excel de empresas (local ou URL)."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limitar o número de empresas a serem processadas (para testes)."
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Executa em modo 'seed', resetando o estado para um novo download completo."
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Executa o script em loop contínuo."
    )
    parser.add_argument(
        "--loop-interval",
        type=int,
        default=0,
        help="Intervalo em segundos entre execuções no modo loop (0 = contínuo sem pausa)."
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Define o nível de logging para o console."
    )
    parser.add_argument(
        "--ignore-failure-rates",
        action="store_true",
        help="Ignora taxas de falha e nunca encerra com sys.exit por causa de falhas de empresas. Útil para processamento contínuo."
    )
    parser.add_argument(
        "--failure-threshold",
        type=int,
        default=50,
        help="Percentual mínimo de falhas para considerar como crítico (padrão: 50%). Só usado se --ignore-failure-rates não estiver ativo."
    )
    args = parser.parse_args()

    configure_logging(log_level=args.log_level)

    logger.info(f"Argumentos recebidos: excel='{args.excel}', limit={args.limit}, seed={args.seed}, loop={args.loop}, loop-interval={args.loop_interval}, log-level='{args.log_level}', ignore-failure-rates={args.ignore_failure_rates}, failure-threshold={args.failure_threshold}%")
    
    # Debug adicional: verificar argumentos da linha de comando
    logger.info(f"🔍 DEBUG - sys.argv completo: {sys.argv}")
    logger.info(f"🔍 DEBUG - Modo loop detectado: {'SIM' if args.loop else 'NÃO'}")
    logger.info(f"🔍 DEBUG - Intervalo do loop: {args.loop_interval} segundos")
    
    if args.loop:
        logger.info("🔄 CONFIRMADO: Executando em MODO LOOP - script não deve encerrar por conta própria!")
    else:
        logger.info("⚠️  ATENÇÃO: Executando em MODO ÚNICO - script pode encerrar com sys.exit!")
        
    logger.info(f"🔍 DEBUG - ignore_failure_rates: {'SIM' if args.ignore_failure_rates else 'NÃO'}")
    logger.info(f"🔍 DEBUG - failure_threshold: {args.failure_threshold}%")

    # Define a API Key diretamente no código (versão codificada)
    api_key_codificada = "gPy6Doj4oUznGcnIXPVj4A%3d%3d"
    
    if not api_key_codificada:
        logger.critical("API Key (codificada) não definida diretamente no código. Verifique app/run.py. Encerrando.")
        if not args.loop:  # Só encerra se não for modo loop
            sys.exit(1)
        else:
            logger.critical("Continuando em modo loop mesmo sem API key para debug...")
            # Em modo loop, nunca encerra - permite debug

    # SiegApiClient fará a decodificação URL (unquote)
    api_client = SiegApiClient(api_key_codificada)
    
    if args.loop:
        if args.loop_interval == 0:
            logger.info("Modo loop contínuo ativado. O script executará indefinidamente sem pausas.")
        else:
            logger.info(f"Modo loop ativado. O script executará com intervalo de {args.loop_interval} segundos.")

        logger.info("🔒 MODO LOOP ATIVO: Script NUNCA irá encerrar por conta própria (apenas com Ctrl+C)")
        
        # Para o modo loop, seed_run só deve ser True na primeira iteração do loop.
        current_seed_run = args.seed
        keep_looping = True # Flag para controlar o loop
        ciclo_numero = 1

        while keep_looping:
            try:
                logger.info(f"--- Iniciando Ciclo #{ciclo_numero} ---")
                ciclo_start_time = time.monotonic()

                resultado_ciclo = run_overall_process(
                    api_client=api_client, 
                    excel_path=args.excel, 
                    limit=args.limit, 
                    seed_run=current_seed_run
                )

                ciclo_duration = time.monotonic() - ciclo_start_time
                logger.info(f"--- Ciclo #{ciclo_numero} concluído em {ciclo_duration:.2f}s ---")

                # Após a primeira execução (bem-sucedida ou não dentro de run_overall_process), 
                # as próximas iterações do loop não devem ser seed.
                current_seed_run = False 
                ciclo_numero += 1

                # Em modo loop, APENAS logamos alertas críticos, mas NUNCA saímos
                if resultado_ciclo:
                    if resultado_ciclo['taxa_falha'] >= 50:
                        logger.critical(f"Taxa de falha crítica detectada no ciclo #{ciclo_numero-1} ({resultado_ciclo['taxa_falha']:.1f}%). Continuando em modo loop, mas verifique os logs.")
                    elif resultado_ciclo['taxa_falha'] >= 20:
                        logger.warning(f"Taxa de falha elevada detectada no ciclo #{ciclo_numero-1} ({resultado_ciclo['taxa_falha']:.1f}%). Continuando em modo loop.")
                else:
                    logger.warning(f"Ciclo #{ciclo_numero-1} não retornou estatísticas. Possível erro no processamento.")

            except KeyboardInterrupt: # Captura específica para Ctrl+C
                logger.warning("KeyboardInterrupt detectado! Encerrando o loop principal...")
                keep_looping = False # Define a flag para sair do loop
                # Opcional: Realizar alguma limpeza final aqui, se necessário
            except SystemExit as e_exit:
                # CRÍTICO: Capturar qualquer sys.exit que escape e IGNORAR em modo loop
                logger.error(f"❌ CAPTURADO sys.exit({e_exit.code}) em modo loop! Ignorando e continuando... (Ciclo #{ciclo_numero})")
                # NÃO quebra o loop - continua rodando
            except Exception as e_loop:
                logger.exception(f"Erro inesperado no loop principal de run_overall_process (Ciclo #{ciclo_numero}): {e_loop}. Tentando novamente no próximo ciclo.", exc_info=True)
                logger.info(">>> RESILIÊNCIA: Script continuará executando apesar do erro <<<")
                # Criar resultado falso para evitar problemas no próximo ciclo
                resultado_ciclo = {
                    "total_empresas": 0,
                    "empresas_sucesso": 0,
                    "empresas_falha": 0,
                    "taxa_falha": 100.0
                }
                # Também não quebra - continua tentando
            
            if keep_looping: # Só espera se não for para sair
                if args.loop_interval > 0:
                    logger.info(f"Aguardando {args.loop_interval} segundos para o próximo ciclo...")
                    time.sleep(args.loop_interval)
                else:
                    # Modo contínuo - pequena pausa para evitar sobrecarga do sistema
                    logger.info("Modo contínuo: iniciando próximo ciclo imediatamente...")
                    time.sleep(1)  # Pausa mínima de 1 segundo para evitar sobrecarga
            else:
                logger.info("Loop principal encerrado.")
                # Em modo loop, NUNCA chamamos sys.exit - apenas return
                return  # Sai da função main(), mas não mata o processo
    else:
        # Execução única
        try:
            resultado_ciclo = run_overall_process(
                api_client=api_client, 
                excel_path=args.excel, 
                limit=args.limit, 
                seed_run=args.seed
            )

            # Exit codes significativos para orquestradores (cron, systemd)
            if resultado_ciclo:
                if args.ignore_failure_rates:
                    # Modo tolerante: apenas loga, mas nunca faz sys.exit por falhas
                    if resultado_ciclo['taxa_falha'] >= 50:
                        logger.critical(f"Taxa de falha crítica ({resultado_ciclo['taxa_falha']:.1f}%), mas continuando devido a --ignore-failure-rates.")
                    elif resultado_ciclo['taxa_falha'] >= 20:
                        logger.warning(f"Taxa de falha elevada ({resultado_ciclo['taxa_falha']:.1f}%), mas continuando devido a --ignore-failure-rates.")
                    logger.info("Execução concluída (modo tolerante ativo)!")
                    sys.exit(0)  # Sempre sucesso quando ignorando taxas de falha
                else:
                    # Modo padrão: usa thresholds configuráveis
                    critical_threshold = args.failure_threshold
                    warning_threshold = max(20, critical_threshold // 2)  # Pelo menos 20%, ou metade do crítico
                    
                    if resultado_ciclo['taxa_falha'] >= critical_threshold:
                        logger.critical(f"Taxa de falha crítica ({resultado_ciclo['taxa_falha']:.1f}% >= {critical_threshold}%)! Saindo com código 2.")
                        logger.info("💡 Dica: Use --ignore-failure-rates para continuar mesmo com falhas, ou --failure-threshold para ajustar o limite.")
                        sys.exit(2)  # Código 2: Falha crítica
                    elif resultado_ciclo['taxa_falha'] >= warning_threshold:
                        logger.warning(f"Taxa de falha elevada ({resultado_ciclo['taxa_falha']:.1f}% >= {warning_threshold}%)! Saindo com código 1.")
                        logger.info("💡 Dica: Use --ignore-failure-rates para continuar mesmo com falhas, ou --failure-threshold para ajustar o limite.")
                        sys.exit(1)  # Código 1: Falha moderada
                    else:
                        logger.info("Execução concluída com sucesso!")
                        sys.exit(0)  # Código 0: Sucesso
            else:
                logger.warning("Não foi possível obter estatísticas do ciclo. Saindo com código 1.")
                sys.exit(1)

        except KeyboardInterrupt: # Também para execução única, se desejado
            logger.warning("KeyboardInterrupt detectado durante execução única! Encerrando...")
            sys.exit(130)  # Código padrão para SIGINT (Ctrl+C)
        except Exception as e_single:
            logger.exception(f"Erro crítico na execução única de run_overall_process: {e_single}.", exc_info=True)
            sys.exit(1) # Adiciona sys.exit(1) para indicar erro na saída em execução única

if __name__ == "__main__":
    main() 
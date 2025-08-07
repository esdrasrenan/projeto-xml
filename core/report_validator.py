"""Módulo para validação dos downloads com relatórios oficiais SIEG."""

import pandas as pd
from pathlib import Path
from typing import Dict, List, Set, Any, Tuple
from datetime import datetime
import re
import xml.etree.ElementTree as ET # Adicionar import com alias

from loguru import logger # <--- SUBSTITUIR logging POR loguru

# Import relativo para normalização, se necessário
from .utils import normalize_cnpj # Normalizar CNPJ da empresa

# Nomes das colunas esperadas no relatório Excel
# Correção final: Usar os nomes exatos do Excel fornecido
COL_CHAVE = 'Chave' # Nome correto da coluna da chave
COL_DT_EMISSAO = 'Dt_Emissao' # Nome correto da coluna da data
# COL_MODELO = 'Modelo' # Não vamos mais hardcodar, vamos buscar

# CORREÇÃO: Usar \d em vez de \\d para dígitos e \. para ponto literal.
# KEY_REGEX = re.compile(r'^(\d{44}).*\.xml$', re.IGNORECASE) # Movido para file_manager.py

# Mapeamento de colunas do relatório para papéis (usado em _get_papel_empresa)
COLUNA_PAPEL_MAP = {
    "CNPJ_CPF_CnpjEmit": "emitente", # NFe
    "CNPJ_CPF_Emitente": "emitente", # CTe
    "CNPJ_CPF_Dest": "destinatario", # Comum
    "CNPJ_CPF_Tomador":  "tomador",    # CTe
}

def _get_papel_empresa(row: pd.Series, empresa_cnpj_normalizado: str, doc_type_str: str) -> str | None:
    """
    Verifica as colunas de CNPJ na linha do relatório para determinar o papel RELEVANTE
    da empresa (Emitente, Destinatario, Tomador) para download e validação.
    Retorna o nome do papel ou None se não for um papel principal.
    """
    chave_debug = row.get(COL_CHAVE, 'CHAVE_N/A_DEBUG')
    # logger.debug(f"[_get_papel_empresa - Chave:{chave_debug}, TipoDoc:{doc_type_str}] Verificando papel para CNPJ: {empresa_cnpj_normalizado}")

    papel_encontrado = None

    if doc_type_str == "NFe":
        col_emit_nfe = "CNPJ_CPF_CnpjEmit"  # Confirmar se este é o nome exato no seu relatório NFe
        col_dest_nfe = "CNPJ_CPF_Dest"      # Confirmar se este é o nome exato

        # Verificar Emitente NFe
        if col_emit_nfe in row and pd.notna(row[col_emit_nfe]):
            try:
                # Converter float para string e normalizar
                cnpj_value = str(row[col_emit_nfe]).replace('.0', '').zfill(14)
                if normalize_cnpj(cnpj_value) == empresa_cnpj_normalizado:
                    logger.debug(f"[_get_papel_empresa - Chave:{chave_debug}, NFe] Empresa {empresa_cnpj_normalizado} é Emitente.")
                    return "Emitente"
            except ValueError:
                logger.debug(f"[_get_papel_empresa - Chave:{chave_debug}, NFe] CNPJ inválido em {col_emit_nfe}: {row[col_emit_nfe]}.")

        # Verificar Destinatário NFe
        if col_dest_nfe in row and pd.notna(row[col_dest_nfe]):
            try:
                # Converter float para string e normalizar
                cnpj_value = str(row[col_dest_nfe]).replace('.0', '').zfill(14)
                if normalize_cnpj(cnpj_value) == empresa_cnpj_normalizado:
                    logger.debug(f"[_get_papel_empresa - Chave:{chave_debug}, NFe] Empresa {empresa_cnpj_normalizado} é Destinatario.")
                    return "Destinatario"
            except ValueError:
                logger.debug(f"[_get_papel_empresa - Chave:{chave_debug}, NFe] CNPJ inválido em {col_dest_nfe}: {row[col_dest_nfe]}.")

    elif doc_type_str == "CTe":
        col_emit_cte = "CNPJ_CPF_Emitente"     # Confirmar nome exato
        col_dest_cte = "CNPJ_CPF_Dest"         # Confirmar nome exato
        col_tom_cte = "CNPJ_CPF_Tomador"       # Confirmar nome exato
        col_outro_tom_cte = "CNPJ_CPF_Outro_Tomador" # Adicionar se existir e for relevante

        # Adicionar colunas para outros papéis CTe se decidir considerá-los válidos para download:
        # col_rem_cte = "CNPJ_CPF_Rem"
        # col_exped_cte = "CNPJ_CPF_Exped"
        # col_receb_cte = "CNPJ_CPF_Receb"

        # PRIORIDADE 1: Verificar Tomador CTe (campo principal) - MAIS IMPORTANTE PARA CTe
        if col_tom_cte in row and pd.notna(row[col_tom_cte]):
            try:
                # Converter float para string e normalizar
                cnpj_value = str(row[col_tom_cte]).replace('.0', '').zfill(14)
                if normalize_cnpj(cnpj_value) == empresa_cnpj_normalizado:
                    logger.debug(f"[_get_papel_empresa - Chave:{chave_debug}, CTe] Empresa {empresa_cnpj_normalizado} é Tomador (campo: {col_tom_cte}).")
                    return "Tomador"
            except ValueError:
                logger.debug(f"[_get_papel_empresa - Chave:{chave_debug}, CTe] CNPJ inválido em {col_tom_cte}: {row[col_tom_cte]}.")

        # PRIORIDADE 1b: Verificar Outro Tomador CTe (se a coluna existir e for relevante)
        if col_outro_tom_cte in row and pd.notna(row[col_outro_tom_cte]): # Checa se a coluna existe
            try:
                # Converter float para string e normalizar
                cnpj_value = str(row[col_outro_tom_cte]).replace('.0', '').zfill(14)
                if normalize_cnpj(cnpj_value) == empresa_cnpj_normalizado:
                    logger.debug(f"[_get_papel_empresa - Chave:{chave_debug}, CTe] Empresa {empresa_cnpj_normalizado} é Tomador (campo: {col_outro_tom_cte}).")
                    return "Tomador" # Mesmo papel
            except ValueError:
                logger.debug(f"[_get_papel_empresa - Chave:{chave_debug}, CTe] CNPJ inválido em {col_outro_tom_cte}: {row[col_outro_tom_cte]}.")

        # PRIORIDADE 2: Verificar Emitente CTe
        if col_emit_cte in row and pd.notna(row[col_emit_cte]):
            try:
                # Converter float para string e normalizar
                cnpj_value = str(row[col_emit_cte]).replace('.0', '').zfill(14)
                if normalize_cnpj(cnpj_value) == empresa_cnpj_normalizado:
                    logger.debug(f"[_get_papel_empresa - Chave:{chave_debug}, CTe] Empresa {empresa_cnpj_normalizado} é Emitente.")
                    return "Emitente"
            except ValueError:
                logger.debug(f"[_get_papel_empresa - Chave:{chave_debug}, CTe] CNPJ inválido em {col_emit_cte}: {row[col_emit_cte]}.")

        # PRIORIDADE 3: Verificar Destinatário CTe
        # (Destinatário em CTe é menos comum como critério primário de download que Tomador)
        if col_dest_cte in row and pd.notna(row[col_dest_cte]):
            try:
                # Converter float para string e normalizar
                cnpj_value = str(row[col_dest_cte]).replace('.0', '').zfill(14)
                if normalize_cnpj(cnpj_value) == empresa_cnpj_normalizado:
                    logger.debug(f"[_get_papel_empresa - Chave:{chave_debug}, CTe] Empresa {empresa_cnpj_normalizado} é Destinatario.")
                    return "Destinatario" # Pode ser "Entrada" para fins de download
            except ValueError:
                logger.debug(f"[_get_papel_empresa - Chave:{chave_debug}, CTe] CNPJ inválido em {col_dest_cte}: {row[col_dest_cte]}.")

        # Descomente e ajuste para outros papéis se necessário:
        # if col_rem_cte in row and pd.notna(row[col_rem_cte]):
        #     if normalize_cnpj(str(row[col_rem_cte])) == empresa_cnpj_normalizado: return "Remetente"
        # if col_exped_cte in row and pd.notna(row[col_exped_cte]):
        #     if normalize_cnpj(str(row[col_exped_cte])) == empresa_cnpj_normalizado: return "Expedidor"
        # if col_receb_cte in row and pd.notna(row[col_receb_cte]):
        #     if normalize_cnpj(str(row[col_receb_cte])) == empresa_cnpj_normalizado: return "Recebedor"

    else:
        logger.warning(f"[_get_papel_empresa - Chave:{chave_debug}] Tipo de documento desconhecido ou não suportado: '{doc_type_str}'.")

    return None # Nenhum papel principal encontrado para a empresa

# --- Funções auxiliares para auditoria de extras ---
def get_dhEmi_quick(xml_path: Path) -> datetime | None:
    """Extrai <dhEmi> ou <dEmi> rapidamente do início do XML."""
    try:
        # Usar iterparse para eficiencia, buscando apenas as tags de emissão
        for event, elem in ET.iterparse(xml_path, events=("start",)):
            # Verificar o final da tag para cobrir namespaces (ex: {http://www.portalfiscal.inf.br/nfe}dhEmi)
            if elem.tag.endswith("dhEmi") or elem.tag.endswith("dEmi"):
                # Pegar apenas a parte relevante da data/hora (ignorar timezone se houver)
                timestamp_str = elem.text[:19] if elem.text else None
                if timestamp_str:
                    return datetime.fromisoformat(timestamp_str)
                else:
                    logger.debug(f"Tag de emissão encontrada mas vazia em {xml_path.name}")
                    return None # Retorna None se a tag estiver vazia
            # Otimização: parar de parsear assim que encontrar qualquer tag de data
            # ou após um número razoável de elementos se a tag não for encontrada logo.
            # (Este iterparse simples vai ler até encontrar ou terminar)

    except ET.ParseError as e:
        logger.warning(f"Erro de parsing XML ao buscar dhEmi em {xml_path.name}: {e}")
    except Exception as e:
        logger.warning(f"Erro inesperado ao buscar dhEmi em {xml_path.name}: {e}")
    return None

def audit_extras(extras: Set[str], xml_base_dir: Path, start_date: datetime.date, end_date: datetime.date):
    """Verifica a data de emissão de arquivos XML listados como extras."""
    logger.info(f"--- Iniciando auditoria de {len(extras)} chave(s) extra(s) em {xml_base_dir} ---")
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())

    for key in extras:
        # Procurar por arquivos que comecem com a chave (permite sufixos)
        found_files = list(xml_base_dir.rglob(f"{key}*.xml"))
        if not found_files:
            logger.warning(f"[AUDIT_EXTRA] XML extra não encontrado fisicamente: {key}")
            continue

        # Pegar o primeiro encontrado (geralmente só haverá um)
        xml_file = found_files[0]
        if len(found_files) > 1:
             logger.warning(f"[AUDIT_EXTRA] Múltiplos arquivos encontrados para a chave extra {key}: {found_files}. Verificando o primeiro: {xml_file.name}")

        dh = get_dhEmi_quick(xml_file)
        if dh:
            if start_dt <= dh <= end_dt:
                logger.warning(f"[AUDIT_EXTRA] {xml_file.name}: dhEmi ({dh.strftime('%Y-%m-%d %H:%M')}) DENTRO do período ({start_date} a {end_date}) -> Possível problema no relatório Excel ou filtro.")
            else:
                logger.info(f"[AUDIT_EXTRA] {xml_file.name}: dhEmi ({dh.strftime('%Y-%m-%d %H:%M')}) FORA do período ({start_date} a {end_date}) -> Provavelmente salvo na pasta errada.")
        else:
            logger.warning(f"[AUDIT_EXTRA] {xml_file.name}: Não foi possível localizar/ler dhEmi/dEmi.")
    logger.info("--- Fim da auditoria de chaves extras ---")
# ---------------------------------------------------

# def _extract_key_from_filename(filename: str) -> str | None:
#    """Extrai a chave de acesso (44 dígitos) do nome do arquivo XML."""
#    # Movido para file_manager.py
#    base_name = filename.replace("_CANC.xml", "").replace(".xml", "")
#    if len(base_name) == 44 and base_name.isdigit():
#        return base_name
#    logger.debug(f"Nome de arquivo não parece conter chave válida: {filename}")
#    return None

def _read_and_filter_report(
    report_path: Path,
    start_date: datetime.date,
    end_date: datetime.date,
    date_col: str,
    key_col: str
) -> Tuple[pd.DataFrame | None, int, pd.DataFrame | None, int, Set[str]]:
    """Lê, filtra e extrai chaves de um relatório Excel."""
    logger.debug(f"[_read_and_filter_report] Iniciando leitura de: {report_path}")
    df_report = None
    read_success = False
    try:
        logger.debug(f"[_read_and_filter_report] Tentando ler com pd.read_excel (engine='openpyxl')...")
        df_report = pd.read_excel(report_path, dtype={key_col: str}, engine='openpyxl')

        # Checagem Imediata após leitura
        if df_report is not None:
            if df_report.empty:
                logger.warning(f"[_read_and_filter_report] pd.read_excel retornou DataFrame VAZIO para {report_path.name}.")
                # Considerar vazio como falha na leitura inicial?
                # Por enquanto, vamos permitir continuar, mas logar.
                read_success = True # tecnicamente leu, mas está vazio.
            else:
                logger.debug(f"[_read_and_filter_report] Leitura inicial OK. Shape: {df_report.shape}")
                logger.debug(f"[_read_and_filter_report] Colunas: {list(df_report.columns)}")
                # logger.debug(f"[_read_and_filter_report] Head:\n{df_report.head().to_string()}") # Log do head pode ser muito grande
                read_success = True
        else:
            # Isso é muito inesperado para pandas
            logger.error(f"[_read_and_filter_report] pd.read_excel retornou None para {report_path.name}. Isso não deveria acontecer.")
            # Tratar como falha
            read_success = False

    except FileNotFoundError:
        logger.error(f"[_read_and_filter_report] Arquivo não encontrado: {report_path}")
        return None, 0, None, 0, set()
    except ValueError as ve:
        # Pode ocorrer se o arquivo não for um excel válido ou problemas de dtype
        logger.error(f"[_read_and_filter_report] Erro de Valor (provavelmente arquivo inválido/corrompido ou dtype incorreto) ao ler {report_path.name}: {ve}", exc_info=True)
        return None, 0, None, 0, set()
    except ImportError as ie:
        # Ex: Faltando openpyxl
        logger.error(f"[_read_and_filter_report] Erro de Importação (dependência faltando?) ao ler {report_path.name}: {ie}", exc_info=True)
        return None, 0, None, 0, set()
    # Adicionar outros excepts específicos se necessário (ex: xlrd para .xls)
    except Exception as e:
        logger.exception(f"Erro GENÉRICO detalhado ao ler relatório {report_path.name} com pandas: {e}")
        return None, 0, None, 0, set()

    # Se a leitura falhou (ex: retornou None ou queremos tratar vazio como falha aqui)
    if not read_success:
        logger.error(f"Leitura inicial de {report_path.name} falhou ou resultou em None. Abortando processamento.")
        return None, 0, None, 0, set()
    # Se chegou aqui, a leitura teve sucesso (mesmo que vazio, mas logamos o warning)

    # Logar número de linhas lidas
    logger.info(f"Lido relatório {report_path.name} com {len(df_report) if df_report is not None else 'Erro'} linhas.")

    # Adicionado: Se o dataframe está vazio aqui, não há o que processar.
    if df_report.empty:
        logger.warning(f"DataFrame de {report_path.name} está vazio após leitura, nada a processar.")
        # Retornar um DF vazio em vez de None para indicar que a leitura ocorreu mas não há dados.
        # Retornar None para df_report_periodo também.
        return df_report, 0, None, 0, set()

    # Limpeza inicial da chave - Garantir que é string e remover não-dígitos
    logger.debug("[_read_and_filter_report] Limpando coluna chave...")
    try:
        df_report[key_col] = df_report[key_col].astype(str).str.replace(r'\D', '', regex=True)
        valid_keys_full = set(df_report[df_report[key_col].str.len() == 44][key_col])
        total_relatorio_bruto = len(valid_keys_full)
        logger.info(f"Encontradas {total_relatorio_bruto} chaves únicas e válidas no relatório completo.")
    except KeyError:
        logger.error(f"[_read_and_filter_report] Coluna chave '{key_col}' não encontrada no DataFrame após leitura.")
        return None, 0, None, 0, set()
    except Exception as key_clean_err:
        logger.exception(f"[_read_and_filter_report] Erro ao limpar/validar coluna chave '{key_col}': {key_clean_err}")
        return None, 0, None, 0, set()

    # --- Conversão de Data ROBUSTA ---
    logger.debug(f"[_read_and_filter_report] Convertendo coluna data '{date_col}'...")
    try:
        raw_dates = df_report[date_col]
        converted_dates = None # Inicializar

        # 1) se a coluna JÁ for datetime64, mantenha
        if pd.api.types.is_datetime64_any_dtype(raw_dates):
            logger.debug(f"[{report_path.name}] Coluna '{date_col}' já é do tipo datetime. Usando diretamente.")
            converted_dates = raw_dates

        # 2) caso contrário, tente parse genérico com dayfirst=True
        else:
            logger.debug(f"[{report_path.name}] Coluna '{date_col}' não é datetime. Tentando parsing genérico com dayfirst=True.")
            converted_dates = pd.to_datetime(
                raw_dates,
                errors='coerce',          # não explode se falhar
                dayfirst=True             # prioriza DD/MM/YYYY em formatos ambíguos
            )

        # Logar falhas residuais (se houver)
        if converted_dates is not None:
            mask_fail = converted_dates.isna() & raw_dates.notna()
            if mask_fail.any():
                sample = raw_dates.loc[mask_fail].unique()[:5]
                logger.warning(
                    f"[{report_path.name}] {mask_fail.sum()} data(s) na coluna '{date_col}' não puderam ser convertidas. "
                    f"Exemplos: {list(sample)}"
                )
            df_report['dt_obj'] = converted_dates

        else:
            # Caso extremo: a coluna não era datetime e a conversão falhou completamente
            logger.error(f"[{report_path.name}] Falha crítica ao processar a coluna de data '{date_col}'. Verifique o conteúdo do arquivo Excel.")
            # Adicionar coluna dt_obj vazia para evitar erros posteriores, mas ela será toda NaT
            df_report['dt_obj'] = pd.NaT

        logger.debug(f"[_read_and_filter_report] Conversão de data concluída.")
    except KeyError:
        logger.error(f"[_read_and_filter_report] Coluna data '{date_col}' não encontrada no DataFrame.")
        return None, 0, None, 0, set()
    except Exception as date_conv_err:
        logger.exception(f"[_read_and_filter_report] Erro durante conversão da coluna data '{date_col}': {date_conv_err}")
        # Considerar retornar ou continuar com datas inválidas?
        # Por segurança, vamos retornar None
        return None, 0, None, 0, set()

    # Filtrar por data
    logger.debug(f"[_read_and_filter_report] Filtrando DataFrame pelo período {start_date} a {end_date}...")
    try:
        start_ts = pd.Timestamp(start_date).replace(hour=0, minute=0, second=0, microsecond=0)
        end_ts = pd.Timestamp(end_date).replace(hour=23, minute=59, second=59, microsecond=999999)

        df_report_periodo = df_report[
            (df_report['dt_obj'] >= start_ts) &
            (df_report['dt_obj'] <= end_ts) &
            (df_report['dt_obj'].notna())
        ].copy() # Usar .copy() para evitar SettingWithCopyWarning
        logger.info(f"Relatório filtrado pela janela ({start_date.strftime('%Y-%m-%d')} a {end_date.strftime('%Y-%m-%d')}): {len(df_report_periodo)} linhas.")
    except KeyError:
        logger.error("[_read_and_filter_report] Coluna 'dt_obj' não encontrada para filtro. A conversão de data falhou?")
        return None, 0, None, 0, set()
    except Exception as filter_err:
         logger.exception(f"[_read_and_filter_report] Erro ao filtrar DataFrame por data: {filter_err}")
         return None, 0, None, 0, set()

    # Extrair chaves válidas do período
    logger.debug("[_read_and_filter_report] Extraindo chaves válidas do período filtrado...")
    try:
        valid_keys_periodo = set(df_report_periodo[df_report_periodo[key_col].str.len() == 44][key_col])
        total_relatorio_periodo = len(valid_keys_periodo)
        logger.info(f"Encontradas {total_relatorio_periodo} chaves únicas e válidas no relatório filtrado.")
    except KeyError:
        logger.error(f"[_read_and_filter_report] Coluna chave '{key_col}' não encontrada no DataFrame filtrado.")
        return None, 0, None, 0, set()
    except Exception as key_extract_err:
         logger.exception(f"[_read_and_filter_report] Erro ao extrair chaves do DataFrame filtrado: {key_extract_err}")
         return None, 0, None, 0, set()

    logger.debug("[_read_and_filter_report] Leitura e filtro concluídos com sucesso.")
    return df_report, total_relatorio_bruto, df_report_periodo, total_relatorio_periodo, valid_keys_periodo

# --- Funções Refatoradas para Fluxo Incremental ---

def read_report_data(
    report_path: Path,
    start_date: datetime.date,
    end_date: datetime.date
) -> Tuple[pd.DataFrame | None, Set[str]]:
    """
    Lê um relatório oficial Excel, filtra por período e extrai as chaves válidas.

    Args:
        report_path: Caminho para o arquivo .xlsx do relatório.
        start_date: Data de início do período (objeto date).
        end_date: Data de fim do período (objeto date).

    Returns:
        Uma tupla contendo:
        - O DataFrame completo lido do relatório (ou None se erro).
        - Um conjunto (set) com as chaves válidas (44 dígitos) encontradas no período.
    """
    # Reutiliza a lógica interna existente, pegando apenas os retornos necessários
    # Assume que as colunas padrão COL_CHAVE e COL_DT_EMISSAO estão corretas
    df_full, _total_bruto, _df_periodo, _total_periodo, report_keys_period = _read_and_filter_report(
        report_path, start_date, end_date, COL_DT_EMISSAO, COL_CHAVE
    )

    # Retorna o DataFrame completo (para lookup posterior) e as chaves do período
    return df_full, report_keys_period

def get_counts_by_role(
    report_df: pd.DataFrame,
    empresa_cnpj_normalizado: str,
    doc_type_str: str
) -> Dict[Tuple[str, str], int]:
    """
    Calcula a contagem de chaves únicas por papel da empresa
    com base no DataFrame do relatório, assumindo que todas as linhas válidas
    pertencem ao tipo de documento especificado (doc_type_str).

    Args:
        report_df: DataFrame do relatório (pode ser completo ou já filtrado).
        empresa_cnpj_normalizado: CNPJ da empresa principal (já normalizado).
        doc_type_str: O tipo de documento esperado no relatório ('NFe' ou 'CTe').

    Returns:
        Dicionário mapeando (TipoDocumento, Papel) para a contagem de chaves únicas.
        Ex: {('NFe', 'destinatario'): 211, ('CTe', 'emitente'): 1014}
    """
    counts: Dict[Tuple[str, str], Set[str]] = {} # Usa Set para chaves únicas

    if report_df is None or report_df.empty:
        logger.warning(f"DataFrame do relatório ({doc_type_str}) vazio ou nulo. Não é possível calcular contagens por papel.")
        return {}

    # 1. Garantir coluna chave existe
    if COL_CHAVE not in report_df.columns:
        logger.error(f"Coluna chave '{COL_CHAVE}' não encontrada no DataFrame {doc_type_str}.")
        return {}

    # 2. Identificar ÍNDICES de linhas com chave válida (sem filtrar colunas ainda)
    try:
        # Trabalha com cópia para evitar modificar o original
        df_work = report_df.copy()
        # Limpa a chave para verificação
        df_work['temp_key_clean'] = df_work[COL_CHAVE].astype(str).str.replace(r'\D', '', regex=True)
        mask_valid_key = df_work['temp_key_clean'].str.len() == 44
        # Obtém os ÍNDICES do DataFrame original que correspondem às chaves válidas
        valid_indices = df_work[mask_valid_key].index
        # Remove coluna temporária
        # df_work = df_work.drop(columns=['temp_key_clean']) # Não precisa mais do df_work

    except Exception as e:
        logger.exception(f"Erro inesperado durante identificação de índices válidos ({doc_type_str}) para get_counts_by_role: {e}")
        return {}

    if valid_indices.empty:
        logger.warning(f"Nenhuma linha com chave válida encontrada no DataFrame {doc_type_str} para contagem por papel.")
        return {}

    logger.debug(f"Calculando contagens por papel ({doc_type_str}) para {len(valid_indices)} linhas com chave válida...")

    # 3. Iterar DIRETAMENTE sobre as linhas com índice válido usando .loc
    processed_count = 0
    for index, row in report_df.loc[valid_indices].iterrows():

        # A CHAVE já foi validada, pegar a versão limpa para o Set
        chave_original = str(row[COL_CHAVE])
        chave_limpa = re.sub(r'\D', '', chave_original)
        if len(chave_limpa) != 44:
             logger.warning(f"Índice {index} estava em valid_indices, mas chave '{chave_original}' não limpa para 44 dígitos. Pulando.")
             continue

        # LOG ANTES DA CHAMADA # DEBUG Removido/Comentado
        # logger.debug(f"[get_counts_by_role - Index:{index} Chave:{chave_limpa}] PREPARANDO PARA CHAMAR _get_papel_empresa para CNPJ: {empresa_cnpj_normalizado} com TipoDoc: {doc_type_str}")

        papel = _get_papel_empresa(row, empresa_cnpj_normalizado, doc_type_str)

        # LOG DEPOIS DA CHAMADA # DEBUG Removido/Comentado
        # logger.debug(f"[get_counts_by_role - Index:{index} Chave:{chave_limpa}] RETORNO DE _get_papel_empresa: {papel}")

        processed_count += 1

        if papel:
            combo = (doc_type_str, papel)
            if combo not in counts:
                counts[combo] = set()
            counts[combo].add(chave_limpa) # Adiciona a chave limpa

    # 4. Converter Sets de chaves em contagens inteiras
    final_counts = {key: len(value) for key, value in counts.items()}

    logger.info(f"Contagens finais {doc_type_str} por Papel: {final_counts}")
    return final_counts

def classify_keys_by_role(
    keys_to_classify: Set[str],
    report_df: pd.DataFrame,
    empresa_cnpj_normalizado: str,
    doc_type_param: str
) -> Dict[Tuple[str, str], Set[str]]:
    """
    Classifica um conjunto de chaves com base no DataFrame do relatório,
    determinando o papel da empresa (Emitente, Destinatário, Tomador) para cada chave,
    considerando o tipo de documento fornecido.

    Args:
        keys_to_classify: Conjunto das chaves (44 dígitos) a serem classificadas.
        report_df: DataFrame completo lido do relatório (resultado de read_report_data).
        empresa_cnpj_normalizado: CNPJ da empresa principal (já normalizado).
        doc_type_param: O tipo de documento ('NFe' ou 'CTe') a ser considerado para classificação.

    Returns:
        Dicionário mapeando (TipoDocumento, Papel) para um conjunto de chaves.
        Ex: {('NFe', 'destinatario'): {'chave1', 'chave2'}, ('CTe', 'emitente'): {'chave3'}}
        Apenas papéis VÁLIDOS (emitente, destinatario, tomador) são incluídos.
    """
    classified_keys: Dict[Tuple[str, str], Set[str]] = {}

    if report_df is None or report_df.empty or not keys_to_classify:
        return classified_keys # Retorna vazio se não há dados para classificar

    # Indexar DataFrame pela chave para busca rápida
    try:
        # Garantir que a coluna de chave existe e não tem valores nulos problemáticos
        if COL_CHAVE not in report_df.columns:
             logger.error(f"Coluna de chave '{COL_CHAVE}' não encontrada no DataFrame do relatório durante classificação.")
             return classified_keys

        report_df_indexed = report_df.dropna(subset=[COL_CHAVE]).set_index(COL_CHAVE)
    except KeyError:
        logger.error(f"Erro ao tentar indexar relatório pela chave '{COL_CHAVE}'. A coluna existe?")
        return classified_keys
    except Exception as e:
         logger.error(f"Erro inesperado ao indexar relatório para classificação: {e}", exc_info=True)
         return classified_keys

    logger.info(f"Classificando {len(keys_to_classify)} chave(s) por papel da empresa para doc_type: {doc_type_param}...")
    processed_count = 0
    not_found_count = 0
    no_role_count = 0
    ignored_role_count = 0

    # Papéis válidos que queremos rastrear para download
    valid_roles = {"Emitente", "Destinatario", "Tomador"} # Convertido para PascalCase para consistência com _get_papel_empresa

    for key in keys_to_classify:
        if not isinstance(key, str) or len(key) != 44 or not key.isdigit():
             logger.warning(f"Chave inválida encontrada durante classificação: '{key}'. Pulando.")
             continue

        try:
            row = report_df_indexed.loc[key]
            # Se a chave for duplicada no índice, loc retorna um DataFrame. Pegamos a primeira linha.
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]

            # Usar o doc_type_param fornecido
            papel = _get_papel_empresa(row, empresa_cnpj_normalizado, doc_type_param)
            processed_count += 1

            if papel:
                # O doc_type_param já é o tipo correto
                if papel in valid_roles: # valid_roles agora está em PascalCase
                    combo_key = (doc_type_param, papel) # Usar doc_type_param
                    if combo_key not in classified_keys:
                        classified_keys[combo_key] = set()
                    classified_keys[combo_key].add(key)
                else:
                    # Este 'else' seria para papéis como "Remetente" se _get_papel_empresa os retornasse
                    # e eles não estivessem em valid_roles.
                    ignored_role_count += 1
                    logger.debug(f"Chave {key} ({doc_type_param}) classificada com papel '{papel}', que não está em valid_roles. Considerada ignorada.")
            else:
                no_role_count += 1 # Conta chaves onde o papel não foi determinado
                logger.debug(f"Chave {key} ({doc_type_param}): Papel não determinado por _get_papel_empresa.")
        except KeyError:
            not_found_count += 1 # Chave do conjunto não encontrada no índice do relatório
            logger.warning(f"Chave '{key}' ({doc_type_param}) do conjunto a classificar não foi encontrada no índice do DataFrame do relatório.")
        except Exception as e:
             logger.error(f"Erro inesperado ao classificar chave '{key}' ({doc_type_param}): {e}", exc_info=True)
             # Pode contar como não encontrado ou erro específico
             not_found_count += 1

    logger.info(f"Classificação ({doc_type_param}) concluída: Processadas={processed_count}, Não encontradas no relatório={not_found_count}, Papel não determinado={no_role_count}, Papéis ignorados (não em valid_roles)={ignored_role_count}")
    # Logar resumo do resultado
    for (tipo, papel_classificado), chaves in classified_keys.items():
         logger.info(f"  -> {tipo} / {papel_classificado}: {len(chaves)} chave(s)")

    return classified_keys

# --- Função Principal de Validação (Será modificada/simplificada depois) ---

def validate_report_vs_local(
    report_path: Path,
    xml_dir_path: Path,
    start_date: datetime.date,
    end_date: datetime.date,
    doc_type: str, # 'NFe' ou 'CTe'
    empresa_cnpj: str
) -> Dict[str, Any] | None:
    """
    (VERSÃO ATUAL - Será adaptada no Bloco 2/3)
    Valida as chaves de um relatório Excel contra os arquivos XML locais
    dentro de um período específico, classificando os faltantes.
    """
    logger.info(f"[VALIDAÇÃO ATUAL] Iniciando: {report_path.name} vs {xml_dir_path.parent.name}/{xml_dir_path.name} (Tipo: {doc_type}, Empresa: {empresa_cnpj})")

    try:
        empresa_cnpj_normalizado = normalize_cnpj(empresa_cnpj)
    except ValueError as e:
        logger.error(f"CNPJ inválido fornecido para validação: {empresa_cnpj}. Erro: {e}")
        return None # Não pode validar sem CNPJ válido

    # 1. Ler dados do relatório (usando a nova função refatorada)
    df_full, report_keys_period = read_report_data(report_path, start_date, end_date)
    if df_full is None:
        return {"status": "ERRO_LEITURA_RELATORIO", "message": f"Falha ao ler relatório {report_path.name}"}

    # 2. Obter chaves locais (usando a nova função refatorada)
    # Precisamos importar get_local_keys de file_manager
    from .file_manager import get_local_keys # Import local temporário
    local_keys_period = get_local_keys(xml_dir_path)

    # 3. Calcular Diffs
    faltantes_geral = report_keys_period - local_keys_period
    extras = local_keys_period - report_keys_period

    # 4. Classificar Faltantes
    # Passar o doc_type para classify_keys_by_role
    classified_faltantes = classify_keys_by_role(faltantes_geral, df_full, empresa_cnpj_normalizado, doc_type) # <--- doc_type PASSADO AQUI

    # Separar entre válidos e ignorados
    faltantes_validos_set = set()
    faltantes_ignorados_set = set()

    # valid_roles deve ser consistente com _get_papel_empresa e classify_keys_by_role
    valid_roles_check = {"Emitente", "Destinatario", "Tomador"} # PascalCase
    for (tipo_classificado, papel_classificado), chaves in classified_faltantes.items():
        # O tipo_classificado deve ser o mesmo que doc_type, pois classify_keys_by_role agora usa doc_type_param
        if tipo_classificado.lower() == doc_type.lower():
             if papel_classificado in valid_roles_check:
                 faltantes_validos_set.update(chaves)
             else:
                 # Se _get_papel_empresa retornou um papel não listado em valid_roles_check (ex: "Remetente")
                 # ou se classify_keys_by_role não o filtrou.
                 faltantes_ignorados_set.update(chaves)
                 logger.debug(f"Chaves {list(chaves)[:3]} ({tipo_classificado}/{papel_classificado}) classificadas como ignoradas (papel não em valid_roles_check).")
        else:
            # Este caso deve ser raro agora que doc_type é passado explicitamente
            logger.warning(f"Classificação retornou tipo '{tipo_classificado}' durante validação de '{doc_type}'. Papel: {papel_classificado}. Chaves: {list(chaves)[:5]}...")
            faltantes_ignorados_set.update(chaves) # Por segurança, tratar como ignorado

    # Identificar chaves que estavam em faltantes_geral mas não foram classificadas
    # (ou seja, _get_papel_empresa retornou None para elas para o doc_type especificado)
    chaves_classificadas_total = set()
    for chaves_set in classified_faltantes.values():
        chaves_classificadas_total.update(chaves_set)

    chaves_nao_classificadas_papel_none = faltantes_geral - chaves_classificadas_total

    if chaves_nao_classificadas_papel_none:
         logger.info(f"{len(chaves_nao_classificadas_papel_none)} chaves faltantes não tiveram papel determinado por _get_papel_empresa (para {doc_type}). Consideradas como ignoradas. Ex: {list(chaves_nao_classificadas_papel_none)[:5]}")
         faltantes_ignorados_set.update(chaves_nao_classificadas_papel_none) # Adiciona aos ignorados

    # Log de auditoria de extras (se houver)
    if extras:
        audit_extras(extras, xml_dir_path, start_date, end_date)

    # Montar resultado
    result = {
        "status": "OK",
        "total_relatorio_bruto": df_full[COL_CHAVE].nunique() if df_full is not None and not df_full.empty else 0,
        "total_relatorio_periodo": len(report_keys_period),
        "total_local": len(local_keys_period),
        "faltantes": sorted(list(faltantes_validos_set)),
        "faltantes_ignorados": sorted(list(faltantes_ignorados_set)),
        "extras": sorted(list(extras))
    }

    # Log Resumido
    log_msg = (
        f"Validação {doc_type} (Empresa: {empresa_cnpj}, Período: {start_date} a {end_date}) vs {report_path.name}: "
        f"Faltantes Válidos (Emit/Dest/Tom)={len(result['faltantes'])}, "
        f"Faltantes Ignorados (Rem/Exp/Rec)={len(result['faltantes_ignorados'])}, "
        f"Extras={len(result['extras'])}"
    )
    logger.info(log_msg)

    return result

# Remover o pass original se existir
# pass
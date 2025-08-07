"""Módulo para gerenciamento de arquivos e diretórios."""

import pandas as pd
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any, Set
import logging
import re
import os
from datetime import datetime as dt, date, timedelta
import requests
import io

# Import relativo dentro do mesmo pacote 'core'
from .utils import normalize_cnpj, sanitize_folder_name

# Imports adicionais para salvar XMLs
import base64
from lxml import etree
import shutil

# --- Constantes de Caminhos Base ---
PRIMARY_SAVE_BASE_PATH = Path("F:/x_p/XML_CLIENTES")
FLAT_COPY_PATH = Path("\\\\172.16.1.254\\xml_import\\Import")
CANCELLED_COPY_BASE_PATH = Path("\\\\172.16.1.254\\xml_import\\Cancelados")
# -----------------------------------

# Configuração básica de logging (pode ser movida/melhorada depois)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def read_empresa_excel(excel_path: str, limit: Optional[int] = None) -> List[Tuple[str, str]]:
    """
    Lê o arquivo Excel de empresas (local ou URL), normaliza os CNPJs e retorna uma lista.

    Args:
        excel_path: Caminho para o arquivo local ou URL (http/https) do arquivo EmpresasSIEG.xlsx.
        limit: Número máximo de empresas a serem lidas (opcional, para testes).

    Returns:
        Lista de tuplas, onde cada tupla contém (cnpj_normalizado, nome_pasta).
        Retorna uma lista vazia se o arquivo/URL não for encontrado ou ocorrer erro.

    Raises:
        FileNotFoundError: Se o arquivo Excel local não for encontrado.
        requests.exceptions.RequestException: Se houver erro ao acessar a URL.
        KeyError: Se as colunas esperadas 'CnpjCpf' ou 'Nome' não existirem.
        ValueError: Se um CNPJ inválido for encontrado e não puder ser normalizado.
        RuntimeError: Para outros erros críticos durante o processamento.
    """
    is_url = excel_path.startswith("http://") or excel_path.startswith("https://")

    try:
        if is_url:
            logger.info(f"Baixando arquivo Excel da URL: {excel_path}")
            response = requests.get(excel_path, timeout=60) # Adiciona timeout
            response.raise_for_status() # Lança exceção para erros HTTP (4xx ou 5xx)
            logger.info("Download da URL concluído. Lendo dados...")
            # Cria um buffer de memória com o conteúdo baixado
            excel_data = io.BytesIO(response.content)
            # Passa o buffer para o pandas
            df = pd.read_excel(excel_data, engine='openpyxl', dtype={'CnpjCpf': str})
        else:
            file = Path(excel_path)
            if not file.exists():
                logger.error(f"Arquivo Excel local não encontrado em: {excel_path}")
                raise FileNotFoundError(f"Arquivo Excel local não encontrado em: {excel_path}")
            logger.info(f"Lendo arquivo Excel local: {excel_path}")
            df = pd.read_excel(file, dtype={'CnpjCpf': str}) # Lê CNPJ como string

        logger.info(f"Lido {len(df)} registros do arquivo Excel.")

        # Verifica se as colunas existem
        if 'CnpjCpf' not in df.columns:
            raise KeyError("Coluna 'CnpjCpf' não encontrada no arquivo Excel.")
        if 'Nome Tratado' not in df.columns:
            raise KeyError("Coluna 'Nome Tratado' não encontrada no arquivo Excel.")

        empresas = []
        # Aplica limite se fornecido
        if limit is not None and limit > 0:
            df = df.head(limit)
            logger.info(f"Aplicando limite de {limit} empresas.")

        for index, row in df.iterrows():
            cnpj_raw = row['CnpjCpf']
            nome_pasta = str(row['Nome Tratado']).strip()

            if pd.isna(cnpj_raw) or not cnpj_raw or pd.isna(nome_pasta) or not nome_pasta:
                logger.warning(f"Linha {index + 2}: CNPJ ou Nome Tratado inválido/vazio. CNPJ='{cnpj_raw}', Nome Tratado='{nome_pasta}'. Pulando.")
                continue

            try:
                cnpj_normalizado = normalize_cnpj(cnpj_raw)
                # Sanitizar o nome da pasta para remover caracteres inválidos no Windows
                nome_pasta_sanitizado = sanitize_folder_name(nome_pasta)
                empresas.append((cnpj_normalizado, nome_pasta_sanitizado))
            except ValueError as e:
                logger.error(f"Linha {index + 2}: Erro ao normalizar CNPJ '{cnpj_raw}'. Erro: {e}. Pulando empresa.")
                # Decide se quer parar ou continuar. Conforme combinado, vamos continuar.
                # raise ValueError(f"Erro ao normalizar CNPJ na linha {index + 2}: {e}") from e

        logger.info(f"Processadas {len(empresas)} empresas válidas do Excel.")
        return empresas

    except FileNotFoundError: # Apenas para arquivos locais
        raise
    except pd.errors.EmptyDataError:
         logger.error(f"Erro ao ler o arquivo/URL Excel: Nenhum dado encontrado ou arquivo vazio em '{excel_path}'.")
         raise RuntimeError(f"Arquivo/URL Excel vazio ou inválido: {excel_path}") from None
    except ImportError:
         logger.error("Erro: Biblioteca 'openpyxl' não encontrada. Necessária para ler arquivos .xlsx de URLs. Instale com 'pip install openpyxl'")
         raise RuntimeError("Dependência 'openpyxl' ausente.") from None
    except requests.exceptions.RequestException as e: # Erro específico para URLs
        logger.error(f"Erro de rede ou HTTP ao acessar a URL '{excel_path}': {e}")
        raise # Relança a exceção original da rede
    except KeyError as e:
        logger.error(f"Erro ao ler o arquivo Excel: Coluna obrigatória faltando - {e}")
        raise
    except Exception as e:
        # Captura outros erros potenciais (ex: erro de parse do pandas, permissão, etc.)
        logger.error(f"Erro inesperado ao ler ou processar o arquivo/URL Excel '{excel_path}': {type(e).__name__} - {e}")
        raise RuntimeError(f"Falha crítica ao processar {excel_path}") from e

# --- Funções de Extração e Listagem de Chaves Locais ---

# Regex para extrair chave de 44 dígitos do nome do arquivo
# Movido de report_validator.py
KEY_REGEX = re.compile(r'^(\d{44}).*\.xml$', re.IGNORECASE)

def _extract_key_from_filename(filename: str) -> str | None:
    """Extrai a chave de acesso (44 dígitos) do nome do arquivo XML."""
    # Remove sufixo _CANC e extensão .xml - Adicionado _PROC também por segurança
    base_name = filename.replace("_PROC.xml","").replace("_CANC.xml", "").replace(".xml", "")
    # Verifica se tem 44 dígitos numéricos
    if len(base_name) == 44 and base_name.isdigit():
        return base_name
    logger.debug(f"Nome de arquivo não parece conter chave válida: {filename}")
    return None

def get_local_keys(directory: Path) -> Set[str]:
    """
    Lista todos os arquivos XML em um diretório e seus subdiretórios,
    extrai as chaves de acesso válidas (44 dígitos) e retorna um conjunto.

    Args:
        directory: O Path do diretório a ser pesquisado (ex: .../NFe ou .../CTe).

    Returns:
        Um conjunto (set) contendo as chaves de acesso (strings de 44 dígitos) encontradas.
    """
    local_keys = set()
    if not directory.is_dir():
        logger.warning(f"Diretório para buscar chaves locais não existe ou não é um diretório: {directory}")
        return local_keys

    logger.debug(f"Buscando arquivos XML em: {directory}")
    # Usar rglob para buscar recursivamente em Entrada/Saida
    xml_files = list(directory.rglob("*.xml"))
    logger.info(f"Encontrados {len(xml_files)} arquivos XML em {directory} (incluindo subpastas) para extração de chaves.")

    processed_files = 0
    skipped_events = 0 # Embora a validação já ignore, contamos aqui por clareza
    for xml_file in xml_files:
        # Ignorar explicitamente arquivos de evento de cancelamento
        if xml_file.name.upper().endswith("_CANC.XML"):
            skipped_events += 1
            continue

        key = _extract_key_from_filename(xml_file.name)
        if key:
            local_keys.add(key)
        processed_files += 1

    logger.info(f"Extraídas {len(local_keys)} chaves únicas locais válidas de {processed_files} arquivos processados ({skipped_events} eventos ignorados) em {directory}.")
    return local_keys

# --- Funções de Salvamento e Organização de XML --- #

# Mapeamento de tipos de evento de cancelamento
CANCEL_EVENT_TYPES = {"110111", "110112", "610601"}
# Sufixo para arquivos de evento de cancelamento
EVENT_SUFFIX = "_CANC"
# Extensão padrão de arquivo XML
XML_EXTENSION = ".xml"

# Namespaces comuns (podem precisar de ajustes)
NS_NFE = {'nfe': 'http://www.portalfiscal.inf.br/nfe'}
NS_CTE = {'cte': 'http://www.portalfiscal.inf.br/cte'}

def _parse_xml_content(xml_content: bytes) -> Optional[etree._Element]:
    """Tenta parsear o conteúdo XML (bytes). Retorna None em caso de erro."""
    try:
        # remove_blank_text para economizar memória, recover para tentar corrigir erros
        parser = etree.XMLParser(remove_blank_text=True, recover=True)
        return etree.fromstring(xml_content, parser=parser)
    except etree.XMLSyntaxError as e:
        logger.error(f"Erro de sintaxe ao parsear XML: {e}")
        # Poderia logar o início do conteúdo XML para depuração:
        # logger.debug(f"XML com erro (início): {xml_content[:200]}...")
        return None

def _get_xml_info(root: etree._Element, empresa_cnpj: str) -> Optional[Dict[str, Any]]:
    """Extrai informações relevantes de um XML NFe, CTe ou Evento parseado."""
    info = {
        "tipo": None,          # "NFe", "CTe", "EventoNFe", "EventoCTe"
        "chave": None,         # Chave do documento (NFe/CTe) ou do evento
        "chave_doc_orig": None, # Chave do documento original (para eventos)
        "dh_emi": None,        # Data/Hora Emissão/Autorização (datetime)
        "tp_evento": None,     # Código do tipo de evento (string)
        "direcao": None,       # "Entrada" ou "Saída"
        "ano_mes": None,       # "YYYY/MM"
    }

    tag_name = etree.QName(root.tag).localname
    dh_emi_str: Optional[str] = None # INICIALIZAÇÃO ADICIONADA

    try:
        if tag_name == 'nfeProc': # NFe processada
            # Tenta encontrar infNFe usando xpath com local-name()
            results = root.xpath('.//*[local-name()="infNFe"]')
            inf_nfe_node = results[0] if results else None
            
            if inf_nfe_node is None:
                # Se não encontrar em qualquer nível, tenta o caminho mais explícito
                results = root.xpath('./*[local-name()="NFe"]/*[local-name()="infNFe"]')
                inf_nfe_node = results[0] if results else None

            if inf_nfe_node is None:
                logger.warning(f"NFe (tag: {tag_name}) encontrada, mas sem tag infNFe detectável. XML ID (do root): {root.get('Id', 'N/A')}")
                info["tipo"] = "NFe"
                return info

            info["tipo"] = "NFe"
            chave_nfe = inf_nfe_node.get('Id')
            if chave_nfe and len(chave_nfe) > 3 and chave_nfe.upper().startswith("NFE"):
                info["chave"] = chave_nfe[3:]
            else:
                logger.warning(f"NFe com infNFe, mas ID ausente ou malformado: {chave_nfe}. XML root ID: {root.get('Id', 'N/A')}")

            # Busca dhEmi usando xpath
            dh_emi_results = inf_nfe_node.xpath('.//*[local-name()="dhEmi"]/text()')
            dh_emi_str = dh_emi_results[0] if dh_emi_results else None

            # Busca CNPJs usando xpath
            emit_cnpj_results = inf_nfe_node.xpath('.//*[local-name()="emit"]/*[local-name()="CNPJ"]/text()')
            emit_cnpj_raw = emit_cnpj_results[0] if emit_cnpj_results else None
            
            dest_cnpj_results = inf_nfe_node.xpath('.//*[local-name()="dest"]/*[local-name()="CNPJ"]/text()')
            dest_cnpj_raw = dest_cnpj_results[0] if dest_cnpj_results else None
            
            logger.debug(f"NFe {info.get('chave', 'CHAVE_NAO_EXTRAIDA')} - CNPJ Emitente (raw): '{emit_cnpj_raw}', CNPJ Destinatário (raw): '{dest_cnpj_raw}'")

            emit_norm = None
            if emit_cnpj_raw:
                try:
                    emit_norm = normalize_cnpj(emit_cnpj_raw)
                except ValueError:
                    logger.warning(f"NFe {info.get('chave', 'CHAVE_NAO_EXTRAIDA')}: CNPJ do emitente inválido (raw: '{emit_cnpj_raw}')")
            
            dest_norm = None
            if dest_cnpj_raw:
                try:
                    dest_norm = normalize_cnpj(dest_cnpj_raw)
                except ValueError:
                    logger.warning(f"NFe {info.get('chave', 'CHAVE_NAO_EXTRAIDA')}: CNPJ do destinatário inválido (raw: '{dest_cnpj_raw}')")

            # Determina Direção NFe
            if dest_norm == empresa_cnpj:
                info["direcao"] = "Entrada"
            elif emit_norm == empresa_cnpj:
                info["direcao"] = "Saída"
            else:
                logger.warning(
                    f"NFe {info.get('chave', 'CHAVE_NAO_EXTRAIDA')}: Direção não determinada para empresa {empresa_cnpj}. "
                    f"CNPJs XML (norm): Emit='{emit_norm}', Dest='{dest_norm}'. "
                    f"Raw: Emit='{emit_cnpj_raw}', Dest='{dest_cnpj_raw}'."
                )

        elif tag_name == 'cteProc': # CTe processado
            results = root.xpath('.//*[local-name()="infCte"]')
            inf_cte_node = results[0] if results else None
            if inf_cte_node is None:
                results = root.xpath('./*[local-name()="CTe"]/*[local-name()="infCte"]')
                inf_cte_node = results[0] if results else None

            if inf_cte_node is None:
                 logger.warning(f"CTe (tag: {tag_name}) encontrado, mas sem tag infCte detectável. XML ID (do root): {root.get('Id', 'N/A')}")
                 info["tipo"] = "CTe"
                 root_id = root.get('Id')
                 if root_id and len(root_id) > 3 and root_id.upper().startswith("CTE"):
                     info["chave"] = root_id[3:]
                 return info 

            info["tipo"] = "CTe"
            chave_cte = inf_cte_node.get('Id')
            if chave_cte and len(chave_cte) > 3 and chave_cte.upper().startswith("CTE"):
                info["chave"] = chave_cte[3:]
            else:
                logger.warning(f"CTe com infCte, mas ID ausente ou malformado: {chave_cte}. XML root ID: {root.get('Id', 'N/A')}")
                if not info["chave"] and root.get('Id') and len(root.get('Id')) > 3 and root.get('Id').upper().startswith("CTE"):
                    info["chave"] = root.get('Id')[3:]
                    logger.info(f"Usando ID do root {info['chave']} para CTe pois ID de infCte era inválido.")

            dh_emi_results = inf_cte_node.xpath('.//*[local-name()="ide"]/*[local-name()="dhEmi"]/text()')
            dh_emi_str = dh_emi_results[0] if dh_emi_results else None

            emit_cnpj_results = inf_cte_node.xpath('.//*[local-name()="emit"]/*[local-name()="CNPJ"]/text()')
            emit_cnpj_xml = emit_cnpj_results[0] if emit_cnpj_results else None
            dest_cnpj_results = inf_cte_node.xpath('.//*[local-name()="dest"]/*[local-name()="CNPJ"]/text()')
            dest_cnpj_xml = dest_cnpj_results[0] if dest_cnpj_results else None
            rem_cnpj_results = inf_cte_node.xpath('.//*[local-name()="rem"]/*[local-name()="CNPJ"]/text()')
            rem_cnpj_xml = rem_cnpj_results[0] if rem_cnpj_results else None
            exped_cnpj_results = inf_cte_node.xpath('.//*[local-name()="exped"]/*[local-name()="CNPJ"]/text()')
            exped_cnpj_xml = exped_cnpj_results[0] if exped_cnpj_results else None
            receb_cnpj_results = inf_cte_node.xpath('.//*[local-name()="receb"]/*[local-name()="CNPJ"]/text()')
            receb_cnpj_xml = receb_cnpj_results[0] if receb_cnpj_results else None

            toma_cnpj_xml = None 

            toma3_node_results = inf_cte_node.xpath('.//*[local-name()="ide"]/*[local-name()="toma3"]')
            toma3_node = toma3_node_results[0] if toma3_node_results else None
            if toma3_node is not None:
                codigo_toma3_results = toma3_node.xpath('.//*[local-name()="toma"]/text()')
                codigo_toma3 = codigo_toma3_results[0] if codigo_toma3_results else None
                match codigo_toma3:
                    case "0": toma_cnpj_xml = rem_cnpj_xml
                    case "1": toma_cnpj_xml = exped_cnpj_xml
                    case "2": toma_cnpj_xml = receb_cnpj_xml
                    case "3": toma_cnpj_xml = dest_cnpj_xml
                    case _: logger.debug(f"CTe {info.get('chave', 'CHAVE_NAO_EXTRAIDA')}: <toma3><toma> com valor não esperado '{codigo_toma3}'.")
            
            if toma_cnpj_xml is None:
                toma4_node_results = inf_cte_node.xpath('.//*[local-name()="ide"]/*[local-name()="toma4"]')
                toma4_node = toma4_node_results[0] if toma4_node_results else None
                if toma4_node is not None:
                    toma_cnpj_results = toma4_node.xpath('.//*[local-name()="CNPJ"]/text()')
                    toma_cnpj_xml = toma_cnpj_results[0] if toma_cnpj_results else None
                    if not toma_cnpj_xml:
                        toma_cpf_results = toma4_node.xpath('.//*[local-name()="CPF"]/text()')
                        toma_cnpj_xml = toma_cpf_results[0] if toma_cpf_results else None
            
            logger.debug(
                f"CTe {info.get('chave', 'CHAVE_NAO_EXTRAIDA')} - CNPJs (raw): Emit='{emit_cnpj_xml}', Dest='{dest_cnpj_xml}', "
                f"Rem='{rem_cnpj_xml}', Exped='{exped_cnpj_xml}', Receb='{receb_cnpj_xml}', Toma(calc)='{toma_cnpj_xml}'"
            )

            # Normalizar CNPJs obtidos para comparação
            norm_emit_cnpj = normalize_cnpj(emit_cnpj_xml) if emit_cnpj_xml else None
            norm_dest_cnpj = normalize_cnpj(dest_cnpj_xml) if dest_cnpj_xml else None
            norm_rem_cnpj = normalize_cnpj(rem_cnpj_xml) if rem_cnpj_xml else None
            norm_exped_cnpj = normalize_cnpj(exped_cnpj_xml) if exped_cnpj_xml else None
            norm_receb_cnpj = normalize_cnpj(receb_cnpj_xml) if receb_cnpj_xml else None
            norm_toma_cnpj = normalize_cnpj(toma_cnpj_xml) if toma_cnpj_xml else None


            # Aplicar Lógica de Direção com Prioridade
            if norm_toma_cnpj and norm_toma_cnpj == empresa_cnpj:
                info["direcao"] = "Entrada"
            elif norm_emit_cnpj and norm_emit_cnpj == empresa_cnpj:
                info["direcao"] = "Saída"
            elif norm_dest_cnpj and norm_dest_cnpj == empresa_cnpj:
                info["direcao"] = "Entrada" 
            elif norm_rem_cnpj and norm_rem_cnpj == empresa_cnpj: # Remetente (empresa é) -> Saída
                info["direcao"] = "Saída"
            elif norm_exped_cnpj and norm_exped_cnpj == empresa_cnpj: # Expedidor (empresa é) -> Saída
                info["direcao"] = "Saída"
            elif norm_receb_cnpj and norm_receb_cnpj == empresa_cnpj: # Recebedor (empresa é) -> Entrada (Assumindo que se a empresa é recebedora, é uma entrada para ela)
                 info["direcao"] = "Entrada"
            else:
                info["direcao"] = None 
                logger.warning(
                    f"CTe {info.get('chave', 'CHAVE_NAO_EXTRAIDA')}: Direção não determinada para empresa {empresa_cnpj}. "
                    f"CNPJs XML (norm): Emit={norm_emit_cnpj}, Dest={norm_dest_cnpj}, Rem={norm_rem_cnpj}, "
                    f"Exped={norm_exped_cnpj}, Receb={norm_receb_cnpj}, TomaCalc={norm_toma_cnpj}."
                )

        elif tag_name == 'procEventoNFe': # Evento NFe
            inf_evento_node_results = root.xpath('.//*[local-name()="eventoNFe"]/*[local-name()="infEvento"]')
            inf_evento_node = inf_evento_node_results[0] if inf_evento_node_results else None
            if inf_evento_node is None:
                inf_evento_node_results = root.xpath('.//*[local-name()="infEvento"]')
                inf_evento_node = inf_evento_node_results[0] if inf_evento_node_results else None
            
            if inf_evento_node is None:
                logger.warning(f"Evento NFe (tag: {tag_name}) encontrado, mas sem tag infEvento detectável. XML ID (do root): {root.get('Id', 'N/A')}")
                info["tipo"] = "EventoNFe"
                root_id = root.get('Id')
                if root_id and len(root_id) > 2 and root_id.upper().startswith("ID"):
                     info["chave"] = root_id[2:]
                return info

            info["tipo"] = "EventoNFe"
            evento_id = inf_evento_node.get('Id')
            if evento_id and len(evento_id) > 2 and evento_id.upper().startswith("ID"):
                info["chave"] = evento_id[2:]
            else:
                logger.warning(f"EventoNFe com infEvento, mas ID do evento ausente ou malformado: {evento_id}")
                if not info["chave"] and root.get('Id') and len(root.get('Id')) > 2 and root.get('Id').upper().startswith("ID"):
                    info["chave"] = root.get('Id')[2:]
                    logger.info(f"Usando ID do root {info['chave']} para EventoNFe pois ID de infEvento era inválido.")
            
            info["chave_doc_orig"] = inf_evento_node.xpath('.//*[local-name()="chNFe"]/text()')[0] if inf_evento_node.xpath('.//*[local-name()="chNFe"]/text()') else None
            info["tp_evento"] = inf_evento_node.xpath('.//*[local-name()="tpEvento"]/text()')[0] if inf_evento_node.xpath('.//*[local-name()="tpEvento"]/text()') else None
            dh_evento_str = inf_evento_node.xpath('.//*[local-name()="dhEvento"]/text()')[0] if inf_evento_node.xpath('.//*[local-name()="dhEvento"]/text()') else None
            dh_emi_str = dh_evento_str # ATRIBUIÇÃO ADICIONADA
            
            # Para eventos, a direção é herdada do documento original ou pode ser None
            # Se for None, a lógica de salvamento pode decidir colocar numa pasta "eventos_sem_direcao"
            # ou tentar buscar a direção do doc original se ele existir localmente.
            # A função _get_direction_from_event_key já trata isso para NFe (eventos de CTe retornam None).
            if info["chave_doc_orig"] and info["tp_evento"]:
                info["direcao"] = _get_direction_from_event_key(info["chave_doc_orig"], info["tp_evento"])
            else:
                logger.warning(f"EventoNFe {info.get('chave', 'CHAVE_EVENTO_NAO_EXTRAIDA')} não possui chNFe ou tpEvento. Direção não pode ser determinada.")

        elif tag_name == 'procEventoCTe': # Evento CTe
            inf_evento_node_results = root.xpath('.//*[local-name()="eventoCTe"]/*[local-name()="infEvento"]')
            inf_evento_node = inf_evento_node_results[0] if inf_evento_node_results else None
            if inf_evento_node is None:
                inf_evento_node_results = root.xpath('.//*[local-name()="infEvento"]')
                inf_evento_node = inf_evento_node_results[0] if inf_evento_node_results else None

            if inf_evento_node is None:
                logger.warning(f"Evento CTe (tag: {tag_name}) encontrado, mas sem tag infEvento detectável. XML ID (do root): {root.get('Id', 'N/A')}")
                info["tipo"] = "EventoCTe"
                root_id = root.get('Id')
                if root_id and len(root_id) > 2 and root_id.upper().startswith("ID"):
                     info["chave"] = root_id[2:]
                return info

            info["tipo"] = "EventoCTe"
            evento_id = inf_evento_node.get('Id')
            if evento_id and len(evento_id) > 2 and evento_id.upper().startswith("ID"):
                info["chave"] = evento_id[2:]
            else:
                logger.warning(f"EventoCTe com infEvento, mas ID do evento ausente ou malformado: {evento_id}")
                if not info["chave"] and root.get('Id') and len(root.get('Id')) > 2 and root.get('Id').upper().startswith("ID"):
                    info["chave"] = root.get('Id')[2:]
                    logger.info(f"Usando ID do root {info['chave']} para EventoCTe pois ID de infEvento era inválido.")

            info["chave_doc_orig"] = inf_evento_node.xpath('.//*[local-name()="chCTe"]/text()')[0] if inf_evento_node.xpath('.//*[local-name()="chCTe"]/text()') else None
            info["tp_evento"] = inf_evento_node.xpath('.//*[local-name()="tpEvento"]/text()')[0] if inf_evento_node.xpath('.//*[local-name()="tpEvento"]/text()') else None
            dh_evento_str = inf_evento_node.xpath('.//*[local-name()="dhEvento"]/text()')[0] if inf_evento_node.xpath('.//*[local-name()="dhEvento"]/text()') else None
            dh_emi_str = dh_evento_str # ATRIBUIÇÃO ADICIONADA
            
            # Eventos de CTe sempre retornam None para direção, o salvamento trata
            info["direcao"] = _get_direction_from_event_key(info.get("chave_doc_orig"," "), info.get("tp_evento", " "))

        else: # Documento não reconhecido (nem NFe, nem CTe, nem Evento)
            logger.warning(f"Tipo de XML não reconhecido ou não suportado: Raiz = '{tag_name}'")
            return None # Retorna None para indicar que não pôde processar este XML

        # Processamento comum (data, ano/mês) - movido para fora dos ifs
        if not info["chave"] or not dh_emi_str:
             logger.warning(f"Não foi possível extrair chave ou data do XML tipo {tag_name} (Chave: {info.get('chave', 'N/A')}, Data Str: {dh_emi_str}).")
             return None

        try:
            # Tentar parsear datas com ou sem timezone
            if '+' in dh_emi_str or '-' in dh_emi_str[10:]:
                info["dh_emi"] = dt.fromisoformat(dh_emi_str)
            else:
                info["dh_emi"] = dt.strptime(dh_emi_str, '%Y-%m-%dT%H:%M:%S') # Sem timezone
            info["ano_mes"] = info["dh_emi"].strftime("%Y/%m")
        except ValueError as date_err:
            logger.error(f"Erro ao parsear data '{dh_emi_str}' do XML {info.get('chave', 'desconhecida')}: {date_err}")
            return None # Falha se não conseguir data

        return info

    except Exception as e:
        # Log genérico para outros erros inesperados durante o parse
        logger.exception(f"Erro inesperado ao extrair informações do XML (raiz: {tag_name}): {e}", exc_info=True)
        return None

def _get_direction_from_event_key(doc_key: str, event_type: str) -> Optional[str]:
    """
    Determina a direção (Entrada/Saída) para um evento com base na chave do documento original.
    Verifica o tipo do evento (NFe ou CTe) e analisa o MODELO DO DOCUMENTO FISCAL (posições 21-22 da chave)
    para determinar heuristicamente se é entrada ou saída.
    
    Args:
        doc_key: A chave do documento original (44 caracteres)
        event_type: Tipo do evento ("EventoNFe" ou "EventoCTe")
        
    Returns:
        "Entrada", "Saída" ou None se não for possível determinar
    """
    if not doc_key or len(doc_key) != 44:
        logger.warning(f"Chave de documento original inválida para determinar direção: {doc_key}")
        return None
        
    try:
        # O modelo do documento está no sexto dígito da chave (posição 5, zero-indexed)
        modelo = doc_key[20:22]  # Modelo é posição 21-22 (não o sexto dígito)
        
        logger.debug(f"Verificando direção para evento. Chave: {doc_key}, Modelo: {modelo}, Tipo: {event_type}")
        
        # Para NF-e: modelo 55 = NFe, modelo 65 = NFCe
        # Para CT-e: modelo 57 = normal
        if "NFe" in event_type:
            if modelo == "55":  # NFe modelo 55 (Nota Fiscal Eletrônica)
                return "Saída"  # Por padrão, NF-e é saída
            elif modelo == "65":  # NFCe modelo 65 (Nota Fiscal Consumidor Eletrônica)
                return "Entrada"  # Por padrão, NFC-e é entrada
        elif "CTe" in event_type:
            # Para eventos de CTe, a direção é mais complexa e idealmente herdada
            # do CTe original. Deixar como None para evitar heurísticas frágeis aqui.
            # A lógica de salvamento em save_xmls_from_base64 tenta colocar o evento
            # na pasta do documento original.
            logger.debug(f"Direção para evento CTe {doc_key} (modelo {modelo}) não será definida heuristicamente. Deve seguir o doc original.")
            return None # Não definir direção heuristicamente para eventos CTe
                
        logger.warning(f"Não foi possível determinar direção para evento com chave {doc_key} (modelo {modelo}) e tipo {event_type}")
        return None
        
    except Exception as e:
        logger.error(f"Erro ao determinar direção para evento: {e}")
        return None

def save_xmls_from_base64(
    base64_list: List[str],
    empresa_cnpj: str,
    empresa_nome_pasta: str,
    is_event: bool = False
) -> Dict[str, int]:
    """
    Decodifica uma lista de XMLs/Eventos em Base64, extrai informações,
    determina o caminho correto e salva os arquivos. Mantém uma cópia original
    no diretório padrão mesmo para a regra do "Mês Anterior".

    Salva os arquivos na estrutura definida por PRIMARY_SAVE_BASE_PATH.
    Também copia XMLs principais (NFe/CTe) para FLAT_COPY_PATH.

    Regra especial: XMLs de ENTRADA (NFe/Dest, CTe/Toma) com data de emissão
    entre 01 e 05 do MÊS ATUAL são **copiados** para uma subpasta 'Mês_anterior'
    dentro do diretório do MÊS ANTERIOR (na estrutura PRIMARY_SAVE_BASE_PATH),
    além de serem salvos no local padrão.
    """
    saved_count = 0
    parse_error_count = 0
    info_error_count = 0
    save_error_count = 0
    skipped_non_cancel_event = 0
    saved_mes_anterior_count = 0
    flat_copy_success_count = 0
    flat_copy_error_count = 0

    base_path = PRIMARY_SAVE_BASE_PATH
    today = date.today()
    logger.info(f"Iniciando salvamento de {len(base64_list)} itens na base: {base_path} (Processando eventos: {is_event}). Data atual: {today}")

    try:
        empresa_cnpj_norm = normalize_cnpj(empresa_cnpj)
    except ValueError:
        logger.error(f"CNPJ inválido fornecido para a empresa: {empresa_cnpj}. Abortando salvamento.")
        return {"saved": 0, "parse_errors": 0, "info_errors": len(base64_list), "save_errors": 0, "skipped_events": 0, "saved_mes_anterior": 0, "flat_copy_success": 0, "flat_copy_errors": 0}

    for b64_content in base64_list:
        xml_content_bytes: Optional[bytes] = None
        root: Optional[etree._Element] = None
        xml_info: Optional[Dict[str, Any]] = None
        source_file_path: Optional[Path] = None

        try:
            xml_content_bytes = base64.b64decode(b64_content)
            if not xml_content_bytes:
                 logger.warning("Conteúdo Base64 vazio ou inválido encontrado. Pulando.")
                 parse_error_count += 1
                 continue

            root = _parse_xml_content(xml_content_bytes)
            if root is None:
                parse_error_count += 1
                continue

            xml_info = _get_xml_info(root, empresa_cnpj_norm)
            if not xml_info:
                info_error_count += 1
                continue

            tipo = xml_info.get("tipo")
            chave = xml_info.get("chave")
            ano_mes = xml_info.get("ano_mes")
            dh_emi = xml_info.get("dh_emi")

            if not all([tipo, chave, ano_mes, dh_emi]):
                 logger.error(f"Informações essenciais (tipo, chave, ano_mes, dh_emi) faltando no XML. Info: {xml_info}. Pulando salvamento.")
                 info_error_count += 1
                 continue

            try:
                ano_emi_str, mes_emi_str = ano_mes.split('/')
                if len(ano_emi_str) != 4 or len(mes_emi_str) != 2 or not ano_emi_str.isdigit() or not mes_emi_str.isdigit():
                    raise ValueError("Formato ano_mes inválido.")
                ano_emi = int(ano_emi_str)
                mes_emi = int(mes_emi_str)
            except ValueError:
                 logger.error(f"Formato ano_mes inválido ({ano_mes}) extraído do XML {chave}. Pulando salvamento.")
                 info_error_count += 1
                 continue

            data_emissao = dh_emi.date()

            target_path: Optional[Path] = None
            final_xml_filename: Optional[str] = None
            copy_to_mes_anterior = False
            copy_cancelled_pair = False
            original_xml_path_for_copy: Optional[Path] = None

            if tipo in ["NFe", "CTe"]:
                direcao = xml_info.get("direcao")
                tipo_doc_base = tipo
                sub_dir_final = None

                if not direcao:
                    logger.warning(f"Direção não determinada para {tipo} {chave}. Salvando em {tipo_doc_base}/.")
                    target_path = base_path / str(ano_emi) / empresa_nome_pasta / f"{mes_emi:02d}" / tipo_doc_base
                    final_xml_filename = f"{chave}{XML_EXTENSION}"
                else:
                    sub_dir_final = "Entrada" if direcao == "Entrada" else "Saída"
                    target_path = base_path / str(ano_emi) / empresa_nome_pasta / f"{mes_emi:02d}" / tipo_doc_base / sub_dir_final
                    final_xml_filename = f"{chave}{XML_EXTENSION}"

                    if (direcao == "Entrada" and
                        data_emissao.year == today.year and
                        data_emissao.month == today.month and
                        1 <= data_emissao.day <= 3):
                        copy_to_mes_anterior = True
                        logger.info(f"XML de ENTRADA {chave} (Tipo: {tipo}, Emissão: {data_emissao}) será COPIADO para 'Mês_anterior' além do local padrão.")

            elif tipo in ["EventoNFe", "EventoCTe"]:
                tp_evento = xml_info.get("tp_evento")
                chave_doc_orig = xml_info.get("chave_doc_orig")

                if not tp_evento or not chave_doc_orig:
                     logger.warning(f"Evento {chave} não contém tipo de evento ou chave original. Pulando.")
                     info_error_count += 1
                     continue

                if tp_evento in CANCEL_EVENT_TYPES:
                    tipo_doc_base = "NFe" if tipo == "EventoNFe" else "CTe"
                    final_xml_filename = f"{chave_doc_orig}{EVENT_SUFFIX}{XML_EXTENSION}"

                    found_original_path: Optional[Path] = None
                    original_filename_to_find = f"{chave_doc_orig}{XML_EXTENSION}"

                    # --- START: Determine original document's month path ---
                    original_ano_yyyy = None
                    original_mes_mm = None
                    original_month_base_path = None
                    if len(chave_doc_orig) == 44:
                        try:
                            ano_yy_str = chave_doc_orig[2:4]
                            mes_mm_str = chave_doc_orig[4:6]
                            ano_yy = int(ano_yy_str)
                            mes_mm = int(mes_mm_str)
                            # Basic validation for month
                            if 1 <= mes_mm <= 12:
                                original_ano_yyyy = 2000 + ano_yy # Assume 20xx
                                original_mes_mm = mes_mm
                                original_month_base_path = base_path / str(original_ano_yyyy) / empresa_nome_pasta / f"{original_mes_mm:02d}"
                                logger.debug(f"Extracted original document path base: {original_month_base_path}")
                            else:
                                logger.warning(f"Invalid month ({mes_mm_str}) extracted from original key {chave_doc_orig}. Cannot search original month path.")
                        except (ValueError, IndexError):
                             logger.warning(f"Could not extract valid year/month from original key {chave_doc_orig}. Cannot search original month path.")
                    else:
                         logger.warning(f"Original key {chave_doc_orig} has invalid length. Cannot search original month path.")
                    # --- END: Determine original document's month path ---


                    # Path of the event's month (used for 'Mês_anterior' check relative to event month and fallbacks)
                    event_month_base_path = base_path / str(ano_emi) / empresa_nome_pasta / f"{mes_emi:02d}"

                    # --- MODIFIED: Search Directories List ---
                    search_dirs_for_original = []
                    # 1. Prioritize directories from the original document's month
                    if original_month_base_path:
                        search_dirs_for_original.extend([
                            original_month_base_path / tipo_doc_base / "Entrada",
                            original_month_base_path / tipo_doc_base / "Saída",
                            # Include raiz of original month? Could be a fallback if original was saved without direction
                            # original_month_base_path / tipo_doc_base
                        ])

                    # 2. Add directories relative to the event's month (for 'Mês_anterior' and fallbacks)
                    search_dirs_for_original.extend([
                        event_month_base_path / tipo_doc_base / "Entrada", # Event month Entrada (less likely but possible)
                        event_month_base_path / tipo_doc_base / "Saída",   # Event month Saida (less likely but possible)
                        # Path to the 'Mês_anterior' folder relative to the event's month
                        base_path / str(ano_emi if mes_emi > 1 else ano_emi - 1) / empresa_nome_pasta / f"{(mes_emi-1 if mes_emi > 1 else 12):02d}" / "Mês_anterior" / tipo_doc_base / "Entrada",
                        # Include raiz of original month as lower priority fallback
                        original_month_base_path / tipo_doc_base if original_month_base_path else None,
                        # Include raiz of event month as lowest priority fallback
                        event_month_base_path / tipo_doc_base
                    ])
                    # Remove None entries if original_month_base_path was None
                    search_dirs_for_original = [p for p in search_dirs_for_original if p is not None]


                    # # Original logic before prioritizing original month (for reference)
                    # month_base_path = base_path / str(ano_emi) / empresa_nome_pasta / f"{mes_emi:02d}"
                    # search_dirs_for_original_old = [
                    #     month_base_path / tipo_doc_base / "Entrada",
                    #     month_base_path / tipo_doc_base / "Saída",
                    #     base_path / str(ano_emi if mes_emi > 1 else ano_emi - 1) / empresa_nome_pasta / f"{(mes_emi-1 if mes_emi > 1 else 12):02d}" / "Mês_anterior" / tipo_doc_base / "Entrada",
                    #     month_base_path / tipo_doc_base
                    # ]
                    # if mes_emi == 1:
                    #      search_dirs_for_original_old[2] = base_path / str(ano_emi - 1) / empresa_nome_pasta / "12" / "Mês_anterior" / tipo_doc_base / "Entrada"

                    logger.debug(f"Searching for {original_filename_to_find} in: {search_dirs_for_original}")

                    for search_dir in search_dirs_for_original:
                        if not search_dir.is_dir(): continue
                        potential_original = search_dir / original_filename_to_find
                        if potential_original.exists():
                            found_original_path = search_dir # Pasta onde o original foi encontrado
                            original_xml_path_for_copy = potential_original # Path completo do original
                            logger.debug(f"Documento original para evento {chave} (Ref: {chave_doc_orig}) encontrado em: {found_original_path}. Evento será salvo lá.")
                            break

                    if found_original_path:
                        target_path = found_original_path # Salva o evento na MESMA pasta do original
                    else:
                        # A linha abaixo foi modificada para incluir search_dirs_for_original
                        logger.warning(f"XML original {original_filename_to_find} não encontrado. Diretórios pesquisados: {search_dirs_for_original}. Evento {final_xml_filename} NÃO será salvo nesta passagem.")
                        # Não definir target_path, o salvamento será pulado
                        info_error_count += 1 # Conta como erro de informação, pois não pode salvar
                        continue # Pula o resto do loop para este evento

                    # Definir copy_cancelled_pair baseado em original_xml_path_for_copy
                    if original_xml_path_for_copy is not None:
                        copy_cancelled_pair = True
                    else:
                        # Este log só é relevante se o evento FOR salvo (target_path definido)
                        # mas o original_xml_path_for_copy não foi (o que não deveria acontecer se found_original_path implica original_xml_path_for_copy)
                        # No entanto, se o evento NÃO for salvo (target_path é None), este log não é necessário aqui.
                        # A lógica de 'continue' acima já trata o não salvamento.
                        pass # Não logar nada aqui se o evento não for salvo.

                    # logger.debug(f"Evento de cancelamento {chave} (Ref: {chave_doc_orig}) será salvo como {final_xml_filename} em {target_path}")
                else: # Este 'else' pertence ao 'if tp_evento in CANCEL_EVENT_TYPES:'
                    logger.debug(f"Ignorando salvamento do evento tipo {tp_evento} (Chave Evento: {chave}, Chave Orig: {chave_doc_orig}).")
                    skipped_non_cancel_event += 1
                    continue
            else:
                logger.warning(f"Tipo de documento não reconhecido para lógica de salvamento: {tipo} (Chave: {chave}). Pulando.")
                info_error_count += 1
                continue

            if target_path and final_xml_filename:
                target_path.mkdir(parents=True, exist_ok=True)
                source_file_path = target_path / final_xml_filename

                if source_file_path.exists():
                     logger.warning(f"Arquivo {source_file_path} já existe. Pulando salvamento primário.")
                else:
                    try:
                        with open(source_file_path, "wb") as f:
                            f.write(xml_content_bytes)
                        saved_count += 1
                        log_prefix = "Evento Cancel." if tipo.startswith("Evento") else "XML"
                        logger.debug(f"{log_prefix} salvo com sucesso em: {source_file_path}")
                    except IOError as e:
                        logger.error(f"Erro de I/O ao salvar {source_file_path}: {e}")
                        save_error_count += 1
                        source_file_path = None
                        copy_cancelled_pair = False
                    except Exception as e:
                        logger.error(f"Erro inesperado ao salvar {source_file_path}: {e}", exc_info=True)
                        save_error_count += 1
                        source_file_path = None
                        copy_cancelled_pair = False

            else:
                 logger.error(f"Erro interno: Caminho ou nome de arquivo final não definido para Chave: {chave}, Tipo: {tipo}. Pulando.")
                 info_error_count += 1
                 continue

            if copy_to_mes_anterior and source_file_path and source_file_path.exists():
                try:
                    primeiro_dia_mes_atual = today.replace(day=1)
                    ultimo_dia_mes_anterior = primeiro_dia_mes_atual - timedelta(days=1)
                    ano_anterior = ultimo_dia_mes_anterior.year
                    mes_anterior = ultimo_dia_mes_anterior.month
                    
                    dest_dir_mes_anterior = base_path / str(ano_anterior) / empresa_nome_pasta / f"{mes_anterior:02d}" / "Mês_anterior" / tipo_doc_base / sub_dir_final
                    dest_dir_mes_anterior.mkdir(parents=True, exist_ok=True)
                    destination_path_mes_anterior = dest_dir_mes_anterior / final_xml_filename

                    if destination_path_mes_anterior.exists():
                        logger.warning(f"Arquivo de cópia {destination_path_mes_anterior} já existe em Mês_anterior. Pulando cópia.")
                    else:
                        shutil.copy2(source_file_path, destination_path_mes_anterior)
                        saved_mes_anterior_count += 1
                        logger.info(f"Arquivo {source_file_path.name} copiado para (Mês Anterior): {destination_path_mes_anterior}")
                except (IOError, shutil.Error) as e:
                    logger.warning(f"Falha ao COPIAR {source_file_path} para a pasta Mês_anterior: {e}")
                except Exception as e:
                    logger.warning(f"Erro inesperado ao COPIAR {source_file_path} para Mês_anterior: {e}", exc_info=True)

            if tipo in ["NFe", "CTe"] and source_file_path and source_file_path.exists() and final_xml_filename:
                try:
                    FLAT_COPY_PATH.mkdir(parents=True, exist_ok=True)
                    flat_dest_path = FLAT_COPY_PATH / final_xml_filename

                    if flat_dest_path.exists():
                        logger.debug(f"Arquivo {flat_dest_path} já existe no diretório flat. Pulando cópia flat.")
                    else:
                        shutil.copy2(source_file_path, flat_dest_path)
                        flat_copy_success_count += 1
                        logger.info(f"Arquivo {source_file_path.name} copiado para (Diretório Flat): {flat_dest_path}")
                
                except (IOError, shutil.Error) as e:
                    logger.warning(f"Falha ao COPIAR {source_file_path.name} para o diretório flat {FLAT_COPY_PATH}: {e}")
                    flat_copy_error_count += 1
                except Exception as e:
                    logger.warning(f"Erro inesperado ao COPIAR {source_file_path.name} para diretório flat: {e}", exc_info=True)
                    flat_copy_error_count += 1

            if copy_cancelled_pair and source_file_path and source_file_path.exists():
                try:
                    # Implementa a regra de negócio simplificada (Jul/2025) para eventos de cancelamento.
                    # Apenas o arquivo de evento (*_CANC.xml) é copiado para a raiz de CANCELLED_COPY_BASE_PATH.
                    CANCELLED_COPY_BASE_PATH.mkdir(parents=True, exist_ok=True)

                    # Define o caminho de destino final para o arquivo de evento
                    cancelled_event_dest_path = CANCELLED_COPY_BASE_PATH / source_file_path.name

                    # Copia o arquivo de evento de cancelamento, se ele ainda não existir no destino
                    if not cancelled_event_dest_path.exists():
                        shutil.copy2(source_file_path, cancelled_event_dest_path)
                        logger.info(f"Evento de cancelamento {source_file_path.name} copiado para: {cancelled_event_dest_path}")
                    else:
                        logger.debug(f"Evento de cancelamento {cancelled_event_dest_path.name} já existe no destino. Cópia pulada.")

                except (IOError, shutil.Error) as e:
                    logger.warning(f"Falha ao copiar evento de cancelamento {source_file_path.name} para {CANCELLED_COPY_BASE_PATH}: {e}")
                except Exception as e:
                    logger.error(f"Erro inesperado ao manusear cópia de evento de cancelamento {source_file_path.name}: {e}", exc_info=True)

        except base64.binascii.Error as b64_err:
            logger.error(f"Erro ao decodificar Base64: {b64_err}. Pulando item.")
            parse_error_count += 1
        except Exception as outer_err:
             log_chave = xml_info.get('chave', 'Chave Desconhecida') if xml_info else 'Info Desconhecida'
             logger.exception(f"Erro inesperado processando item (Chave: {log_chave}): {outer_err}. Pulando item.")
             info_error_count += 1

    logger.info(f"Processo de salvamento concluído. Salvos: {saved_count} (Copias Mês Ant.: {saved_mes_anterior_count}, Copias Flat: {flat_copy_success_count}), Erros Parse: {parse_error_count}, Erros Info: {info_error_count}, Erros Save: {save_error_count}, Eventos Ignorados: {skipped_non_cancel_event}, Erros Cópia Flat: {flat_copy_error_count}")

    return {
        "saved": saved_count,
        "parse_errors": parse_error_count,
        "info_errors": info_error_count,
        "save_errors": save_error_count,
        "skipped_events": skipped_non_cancel_event,
        "saved_mes_anterior": saved_mes_anterior_count,
        "flat_copy_success": flat_copy_success_count,
        "flat_copy_errors": flat_copy_error_count,
    }

# --- Funções para Relatórios --- #

def save_report_from_base64(
    report_b64: str,
    target_dir: Path,
    filename: str
) -> bool:
    """
    Decodifica uma string Base64 e salva como um arquivo (presumivelmente .xlsx).

    Sobrescreve o arquivo se ele já existir.

    Args:
        report_b64: String Base64 contendo o relatório.
        target_dir: Diretório Path onde o arquivo será salvo.
        filename: Nome do arquivo final (ex: Relatorio_NFe_MM_YYYY.xlsx).

    Returns:
        True se o salvamento for bem-sucedido, False caso contrário.
    """
    if not report_b64 or not isinstance(report_b64, str):
        logger.error(f"Conteúdo Base64 do relatório está vazio ou inválido para {filename}. Não salvo.")
        return False

    full_path = target_dir / filename

    try:
        report_content = base64.b64decode(report_b64, validate=True)
        target_dir.mkdir(parents=True, exist_ok=True) # Garante que o diretório existe

        with open(full_path, 'wb') as f:
            f.write(report_content)
            f.flush()
            os.fsync(f.fileno())
        logger.info(f"Relatório salvo com sucesso em: {full_path}")
        return True

    except (base64.binascii.Error, ValueError) as e:
        logger.error(f"Erro ao decodificar Base64 do relatório {filename}: {e}")
        return False
    except OSError as e:
        logger.error(f"Erro de OS ao salvar relatório {full_path}: {e}")
        return False
    except Exception as e:
        logger.error(f"Erro inesperado ao salvar relatório {full_path}: {e}", exc_info=True)
        return False

def save_raw_xml(
    raw_xml_content: str | bytes,
    empresa_info: Dict[str, Any], # Espera 'cnpj', 'nome_pasta', 'ano', 'mes'
    base_path: Path
) -> Optional[Path]:
    """
    Parseia um XML bruto (string ou bytes), extrai informações, determina o caminho
    e salva o arquivo.

    Retorna o Path do arquivo salvo ou None em caso de erro.
    """
    empresa_cnpj = empresa_info.get('cnpj')
    if not empresa_cnpj:
        logger.error("CNPJ da empresa não fornecido para save_raw_xml.")
        return None

    try:
        if isinstance(raw_xml_content, str):
            # Assumir UTF-8, que é comum para XML. Pode precisar de ajuste se outra codificação for usada.
            xml_content_bytes = raw_xml_content.encode('utf-8')
        elif isinstance(raw_xml_content, bytes):
            xml_content_bytes = raw_xml_content
        else:
            logger.error(f"[{empresa_cnpj}] Conteúdo XML recebido não é string nem bytes.")
            return None

        if not xml_content_bytes:
             logger.error(f"[{empresa_cnpj}] Conteúdo XML recebido está vazio.")
             return None

        # --- ADIÇÃO: Remover aspa dupla inicial se presente (problema da API SIEG) ---
        if xml_content_bytes.startswith(b'"') and xml_content_bytes.endswith(b'"') and len(xml_content_bytes) > 1:
             # Remove a primeira e a última aspa
             xml_content_bytes = xml_content_bytes[1:-1]
             logger.debug(f"[{empresa_cnpj}] Aspas duplas externas removidas do conteúdo XML bruto.")
        # --------------------------------------------------------------------------

    except Exception as e_enc:
        logger.exception(f"[{empresa_cnpj}] Erro inesperado ao preparar conteúdo XML bytes: {e_enc}", exc_info=True)
        return None

    # --- UNESCAPE INTERNO ---
    try:
        # Decodifica para string (assumindo UTF-8)
        xml_string = xml_content_bytes.decode('utf-8')
        # Substitui as sequências de escape comuns
        xml_string_unescaped = xml_string.replace('\\"', '"').replace('\\\\', '\\')
        # Codifica de volta para bytes para o parser e salvamento
        xml_content_bytes = xml_string_unescaped.encode('utf-8')
        logger.debug(f"[{empresa_cnpj}] Sequências de escape internas (\") processadas.")
    except Exception as unescape_err:
        logger.error(f"[{empresa_cnpj}] Erro ao processar escapes internos do XML: {unescape_err}. Continuando com bytes originais (sem aspas externas).")
        # Usa xml_content_bytes como estava após remover aspas externas
    # ------------------------

    root = _parse_xml_content(xml_content_bytes)
    if root is None:
        # Log de erro já feito por _parse_xml_content
        logger.warning(f"[{empresa_cnpj}] Falha ao parsear XML bruto recebido. Conteúdo (início): {xml_content_bytes[:200]}...")
        return None

    # Extrai informações do XML parseado
    xml_info = _get_xml_info(root, empresa_cnpj)

    if not xml_info:
        logger.error(f"[{empresa_cnpj}] Não foi possível extrair informações do XML bruto parseado.")
        return None

    # Validar informações essenciais para salvar
    chave = xml_info.get('chave')
    tipo_doc = xml_info.get('tipo')
    direcao = xml_info.get('direcao')
    # --- MODIFICAÇÃO: Obter ano/mês do próprio XML --- 
    ano_mes_xml = xml_info.get('ano_mes') # Formato esperado: "YYYY/MM"
    if not ano_mes_xml or '/' not in ano_mes_xml:
        logger.error(f"[{empresa_cnpj}] Não foi possível extrair ano/mês do XML para a chave {chave}. Pulando salvamento.")
        return None
    ano, mes = ano_mes_xml.split('/')
    # -------------------------------------------------
    nome_pasta_empresa = empresa_info.get('nome_pasta') # Pega da info da empresa

    # Simplificação: Se for evento e não tiver direção, pular salvamento por enquanto.
    # A lógica de organização de eventos cuidará disso depois.
    if not direcao and tipo_doc and tipo_doc.startswith("Evento"):
         logger.warning(f"[{empresa_cnpj}] Direção não determinada para evento {chave} (Tipo: {tipo_doc}). Pulando salvamento individual, será tratado na organização.")
         return None # Retorna None, mas não é um erro crítico de salvamento

    if not all([chave, tipo_doc, direcao, ano, mes, nome_pasta_empresa]):
        logger.error(f"[{empresa_cnpj}] Informações incompletas extraídas/fornecidas para salvar XML bruto. Chave:{chave}, Tipo:{tipo_doc}, Direcao:{direcao}, Ano:{ano}, Mes:{mes}, Pasta:{nome_pasta_empresa}")
        # Log mais detalhes para depuração
        logger.debug(f"XML Info Detalhado: {xml_info}")
        logger.debug(f"Empresa Info Detalhado: {empresa_info}")
        return None

    # Montar o caminho final
    # Ajustar tipo_doc para corresponder aos nomes de pasta (ex: EventoNFe -> NFe)
    if tipo_doc.startswith("Evento"):
         dir_tipo = tipo_doc.replace("Evento", "") # Salva evento na pasta do doc original
    else:
         dir_tipo = tipo_doc # NFe ou CTe

    # Nome do arquivo (tratar eventos)
    if tipo_doc.startswith("Evento") and xml_info.get("tp_evento") == "110111": # Ex: Cancelamento
        file_name = f"{chave}{EVENT_SUFFIX}{XML_EXTENSION}"
    else:
        file_name = f"{chave}{XML_EXTENSION}"

    try:
        save_dir = base_path / ano / nome_pasta_empresa / mes / dir_tipo / direcao
        save_dir.mkdir(parents=True, exist_ok=True)
        final_path = save_dir / file_name

        # --- Verificação Anti-Sobrescrita ---
        if final_path.exists():
            logger.warning(f"[{empresa_cnpj}] Arquivo já existe em {final_path}. Pulando salvamento para evitar sobrescrita.")
            # Considerar isso um 'sucesso' de salvamento no sentido que o arquivo está lá?
            # Ou um tipo diferente de status? Por ora, retornamos o path existente.
            return final_path # Retorna o path existente como indicativo que o arquivo está lá

        # --- Salvamento ---
        with open(final_path, 'wb') as f:
            f.write(xml_content_bytes)

        logger.debug(f"[{empresa_cnpj}] XML (bruto) salvo com sucesso em: {final_path}")
        return final_path

    except OSError as e_os:
        logger.error(f"[{empresa_cnpj}] Erro de SO ao criar diretório ou salvar arquivo {final_path}: {e_os}")
        return None
    except Exception as e_save:
        # Usar logger.exception para incluir traceback
        logger.exception(f"[{empresa_cnpj}] Erro inesperado ao salvar arquivo {final_path}: {e_save}", exc_info=True)
        return None

# --- Funções de Contagem Local --- #

def _get_evento_type(root: etree._Element) -> str | None:
    """Extrai o tipo de evento (tpEvento) de um XML de evento parseado."""
    if root is None:
        return None
    try:
        # 1. Identificar o namespace principal do documento
        # O namespace real está na tag do elemento raiz
        root_tag = etree.QName(root.tag)
        doc_ns_uri = root_tag.namespace
        if not doc_ns_uri:
            logger.warning("Não foi possível determinar o namespace do XML de evento.")
            return None

        # 2. Definir o mapa de namespace para a busca XPath
        ns = {'ns': doc_ns_uri}

        # 3. Construir o caminho XPath com base no namespace
        # Para CTe, o caminho é procEventoCTe -> eventoCTe -> infEvento -> tpEvento
        # Para NFe, o caminho é procEventoNFe -> evento -> infEvento -> tpEvento
        # Usaremos a busca genérica por infEvento e depois tpEvento dentro dele
        inf_evento_node = root.find('.//ns:infEvento', namespaces=ns)

        if inf_evento_node is not None:
            tp_evento = inf_evento_node.findtext('ns:tpEvento', namespaces=ns)
            if tp_evento:
                return tp_evento
            else:
                logger.warning("Tag infEvento encontrada, mas tpEvento não encontrada dentro dela.")
        else:
            logger.warning("Tag infEvento não encontrada no XML de evento.")

    except Exception as e:
        # Usar exc_info=True para logar o traceback completo em caso de erro inesperado
        logger.error(f"Erro ao extrair tpEvento: {e}", exc_info=True)
    return None

def count_local_files(month_dir_path: Path) -> Dict[str, Any]:
    """
    Conta os arquivos XML principais e de cancelamento em um diretório mensal,
    incluindo a subpasta especial 'mes_anterior' para documentos de entrada
    (localizada no diretório do MÊS ANTERIOR).

    Varre as subpastas NFe/Entrada, NFe/Saída, CTe/Entrada, CTe/Saída do mês atual,
    as pastas raiz NFe/ e CTe/ do mês atual, e as pastas mes_anterior/NFe/Entrada,
    mes_anterior/CTe/Entrada do MÊS ANTERIOR.

    Args:
        month_dir_path: Path para o diretório do mês ATUAL sendo processado
                        (ex: .../xmls/YYYY/CLIENTE/MM).

    Returns:
        Dicionário com as contagens, exemplo:
        {
            "NFe_Entrada": 10,
            "NFe_Saída": 5,
            "CTe_Entrada": 2,
            "CTe_Saída": 1,
            "NFe_Entrada_MesAnterior": 3, # <<< NOVO
            "CTe_Entrada_MesAnterior": 1, # <<< NOVO
            "Eventos_Cancelamento": { ... }
        }
        Retorna contagens 0 se o diretório não existir.
    """
    counts = {
        "NFe_Entrada": 0,
        "NFe_Saída": 0,
        "CTe_Entrada": 0,
        "CTe_Saída": 0,
        "NFe_Entrada_MesAnterior": 0, # <<< NOVO
        "CTe_Entrada_MesAnterior": 0, # <<< NOVO
        "Eventos_Cancelamento": {"total": 0, "erros_leitura": 0} # Inicia com total e erros
    }
    event_counts = counts["Eventos_Cancelamento"]

    if not month_dir_path.is_dir():
        # Este log pode ser muito verboso se a pasta não existe, considerar mudar para DEBUG
        # logger.warning(f"Diretório mensal (atual) não encontrado para contagem local: {month_dir_path}")
        return counts # Retorna 0 se a pasta do mês atual não existe

    # --- Calcular Caminho do Mês Anterior ---
    # Extrair ano/mês/nome_empresa do path atual
    try:
        current_month_str = month_dir_path.name # MM
        empresa_folder_name = month_dir_path.parent.name # Nome da Pasta da Empresa
        current_year_str = month_dir_path.parent.parent.name # YYYY (Corrigido)

        # Validar se são números (básico)
        if not current_month_str.isdigit() or not current_year_str.isdigit():
            raise ValueError("Não foi possível extrair ano/mês numérico do caminho.")

        # Cria uma data representativa do mês atual para facilitar o cálculo
        current_month_date = dt.strptime(f"{current_year_str}-{current_month_str}-01", "%Y-%m-%d").date()
        
        # Calcula o último dia do mês anterior
        first_day_current_month = current_month_date.replace(day=1)
        last_day_previous_month = first_day_current_month - timedelta(days=1)
        prev_month_year_str = str(last_day_previous_month.year)
        prev_month_str = f"{last_day_previous_month.month:02d}"

        # Caminho base para a pasta do mês anterior (Corrigido, usando empresa_folder_name)
        # Estrutura: ...base/ANO_ANT/NOME_EMPRESA/MES_ANT
        previous_month_base_dir = month_dir_path.parent.parent.parent / prev_month_year_str / empresa_folder_name / prev_month_str
        logger.debug(f"Diretório base do mês anterior calculado para contagem: {previous_month_base_dir}")

    except (ValueError, IndexError, AttributeError) as e:
        # O erro ValueError acontece aqui por causa do strptime ou da validação isdigit
        logger.error(f"Erro ao calcular o diretório do mês anterior a partir de {month_dir_path}: {e}. Contagem de 'mes_anterior' será 0.")
        previous_month_base_dir = None # Define como None se houver erro

    # Mapeamento de chaves de contagem para pastas a escanear
    folders_to_scan = {
        # Pastas do mês atual
        "NFe_Entrada": month_dir_path / "NFe" / "Entrada",
        "NFe_Saída": month_dir_path / "NFe" / "Saída",
        "CTe_Entrada": month_dir_path / "CTe" / "Entrada",
        "CTe_Saída": month_dir_path / "CTe" / "Saída",
        "NFe_Raiz": month_dir_path / "NFe",
        "CTe_Raiz": month_dir_path / "CTe",
    }
    # Adicionar pastas do mês anterior APENAS se o cálculo foi bem sucedido
    if previous_month_base_dir:
        folders_to_scan.update({
            "NFe_Entrada_MesAnterior": previous_month_base_dir / "Mês_anterior" / "NFe" / "Entrada",
            "CTe_Entrada_MesAnterior": previous_month_base_dir / "Mês_anterior" / "CTe" / "Entrada",
        })
    else:
        # Se não conseguiu calcular o mês anterior, loga e continua sem essas pastas
         logger.warning(f"Não foi possível determinar o caminho do mês anterior para {month_dir_path}, contagem de 'mes_anterior' será ignorada.")


    for folder_key, folder_path in folders_to_scan.items():
        if not folder_path.is_dir():
            # Não logar warning para pastas 'mes_anterior' que podem não existir
            if "MesAnterior" not in folder_key:
                logger.debug(f"Diretório não encontrado para contagem: {folder_path}")
            continue

        logger.debug(f"Contando arquivos em: {folder_path}")
        # Iterar apenas nos arquivos diretos da pasta (não recursivo aqui)
        for item in folder_path.iterdir():
            if item.is_file() and item.suffix.lower() == XML_EXTENSION:

                # VERIFICAR SE É EVENTO DE CANCELAMENTO
                # Eventos de cancelamento podem estar em qualquer pasta agora
                if item.name.upper().endswith(f"{EVENT_SUFFIX}{XML_EXTENSION}"):
                    # É um evento de cancelamento, parsear para pegar o tipo
                    try:
                        with open(item, 'rb') as f_event:
                            xml_content = f_event.read()
                        root = _parse_xml_content(xml_content)
                        tp_evento = _get_evento_type(root) # Função auxiliar para pegar tpEvento
                        if tp_evento:
                            event_counts[tp_evento] = event_counts.get(tp_evento, 0) + 1
                            event_counts["total"] += 1
                        else:
                            logger.warning(f"Não foi possível obter tpEvento do arquivo de cancelamento: {item.name}. Contando como erro.")
                            event_counts["erros_leitura"] += 1
                    except Exception as e:
                        logger.error(f"Erro ao processar arquivo de evento {item.name}: {e}")
                        event_counts["erros_leitura"] += 1
                    # Não contar o evento na contagem da pasta (NFe_Entrada, etc.)
                    continue # Pula para o próximo item

                # SE NÃO FOR EVENTO DE CANCELAMENTO, CONTAR NA PASTA CORRESPONDENTE
                # Usar o folder_key diretamente para incrementar o contador correto
                if folder_key in counts:
                    # Apenas incrementa se a chave existir em counts (ignora _Raiz)
                    counts[folder_key] += 1
                elif folder_key == "NFe_Raiz":
                    # Arquivo na raiz NFe que não é evento _CANC.
                    # Pode ser NFe sem direção ou outro arquivo. Contamos separadamente?
                    # Por enquanto, vamos ignorar para não inflar NFe_Entrada/Saida
                    logger.debug(f"Arquivo {item.name} encontrado na raiz NFe/. Ignorado na contagem principal.")
                elif folder_key == "CTe_Raiz":
                    # Arquivo na raiz CTe que não é evento _CANC.
                    logger.debug(f"Arquivo {item.name} encontrado na raiz CTe/. Ignorado na contagem principal.")

    logger.info(f"Contagem local para {month_dir_path.parent.name}/{month_dir_path.name}: {counts}")
    return counts

# --- Função organize_pending_events (MANTIDA POR ENQUANTO, MAS NÃO USADA) ---
# (Se confirmar que não é mais necessária, pode ser removida)
def organize_pending_events(month_path: Path) -> Tuple[int, int]:
    """
    Processa eventos XML salvos nas pastas EventoNFe/EventoCTe, movendo e
    renomeando eventos de cancelamento para junto de seus documentos originais.

    Args:
        month_path: Path para o diretório do mês (ex: .../xmls/YYYY/CLIENTE/MM).

    Returns:
        Tupla (moved_count, not_found_count): Número de eventos movidos
        e número de documentos originais não encontrados (ou eventos não processados).
    """
    # Lista de diretórios onde eventos foram salvos inicialmente
    event_source_dirs = [
        month_path / "EventoNFe",
        month_path / "EventoCTe"
    ]

    moved_count = 0
    not_found_count = 0
    skipped_non_cancel = 0

    # Códigos de evento de cancelamento a serem processados
    CANCEL_EVENT_TYPES = {"110111", "110112", "610601"}

    for source_dir in event_source_dirs:
        if not source_dir.is_dir():
            # logger.debug(f"Pasta de origem de eventos {source_dir} não encontrada. Pulando.")
            continue

        logger.info(f"Organizando eventos em: {source_dir}")

        # Usar list() para poder remover/iterar com segurança se necessário, embora shutil.move resolva
        for event_file in list(source_dir.iterdir()):
            # Ignora subdiretórios e arquivos não-XML
            if not event_file.is_file() or event_file.suffix.lower() != XML_EXTENSION:
                continue

            chave_doc_orig = None
            tp_evento = None
            chave_evento = event_file.stem # Chave do próprio evento (nome do arquivo sem extensão)

            # 1. Parsear o evento para obter infos
            try:
                with open(event_file, 'rb') as f_ev:
                    ev_content = f_ev.read()
                ev_root = _parse_xml_content(ev_content)
                if ev_root is not None:
                    # Passar um CNPJ dummy, só precisamos das chaves e tipo
                    ev_info = _get_xml_info(ev_root, "00000000000000")
                    if ev_info:
                        chave_doc_orig = ev_info.get("chave_doc_orig")
                        tp_evento = ev_info.get("tp_evento")
                    else:
                        logger.warning(f"Não foi possível extrair informações do evento {event_file.name}.")
                else:
                    logger.warning(f"Falha ao parsear o conteúdo do evento {event_file.name}.")

            except Exception as parse_err:
                logger.error(f"Erro ao ler/parsear evento {event_file.name}: {parse_err}")
                not_found_count += 1 # Contar como erro/não processado
                continue # Pula para o próximo evento

            # Verificar se temos as infos necessárias e se é um evento de cancelamento
            if not chave_doc_orig:
                logger.warning(f"Não foi possível extrair chave do documento original do evento {event_file.name} (Chave evento: {chave_evento}). Evento permanece em {source_dir}.")
                not_found_count += 1
                continue

            if not tp_evento:
                 logger.warning(f"Não foi possível extrair tipo do evento {event_file.name} (Chave evento: {chave_evento}, Chave Orig: {chave_doc_orig}). Evento permanece em {source_dir}.")
                 not_found_count += 1
                 continue

            # Pular se não for um tipo de cancelamento que queremos organizar
            if tp_evento not in CANCEL_EVENT_TYPES:
                 logger.debug(f"Pulando organização do evento tipo {tp_evento} (Chave evento: {chave_evento}, Chave Orig: {chave_doc_orig}).")
                 skipped_non_cancel += 1
                 continue

            # 2. Procurar o XML original
            original_xml_name = f"{chave_doc_orig}{XML_EXTENSION}"
            found_original = False
            target_dir = None # Diretório onde o original foi encontrado (NFe_Entrada, etc.)

            search_dirs = [
                month_path / "NFe_Entrada", month_path / "NFe_Saída",
                month_path / "CTe_Entrada", month_path / "CTe_Saída",
                # Adicionar busca na raiz do tipo se necessário (XMLs sem direção definida)?
                month_path / "NFe", month_path / "CTe"
            ]

            for search_dir in search_dirs:
                if not search_dir.is_dir(): continue
                potential_original = search_dir / original_xml_name
                if potential_original.exists():
                    target_dir = potential_original.parent
                    found_original = True
                    logger.debug(f"Documento original para evento {chave} (Ref: {chave_doc_orig}) encontrado em: {target_dir}.")
                    break

            # 3. Mover e Renomear se original encontrado
            if found_original and target_dir:
                # Definir nome do arquivo de destino usando chave original e sufixo
                # Usar EVENT_SUFFIX (_CANC) para os tipos de cancelamento
                destination_filename = f"{chave_doc_orig}{EVENT_SUFFIX}{XML_EXTENSION}"
                destination_file_path = target_dir / destination_filename

                try:
                    # Verificar se o destino já existe
                    if destination_file_path.exists():
                        logger.warning(f"Arquivo de evento {destination_filename} já existe no destino {target_dir}. Pulando movimentação do arquivo {event_file.name}.")
                        # DECISÃO: Não mover se já existe. Poderíamos deletar o event_file original?
                        # Por segurança, vamos apenas pular a movimentação por enquanto.
                        # Se pulamos, ele não será contado como movido.
                        # Poderíamos tentar deletar o source event_file aqui?
                        # try:
                        #     event_file.unlink()
                        #     logger.debug(f"Arquivo de evento origem {event_file.name} removido pois destino já existia.")
                        # except OSError as del_err:
                        #     logger.error(f"Erro ao remover arquivo de evento origem {event_file.name}: {del_err}")
                        continue # Pula para o próximo arquivo na pasta de origem

                    # Mover e Renomear
                    shutil.move(str(event_file), str(destination_file_path))
                    logger.debug(f"Evento {event_file.name} (Tipo: {tp_evento}, Ref: {chave_doc_orig}) movido e renomeado para {destination_file_path}")
                    moved_count += 1

                except Exception as move_err:
                    logger.error(f"Erro ao mover/renomear evento {event_file.name} para {destination_file_path}: {move_err}")
                    # Deixar o arquivo na pasta de origem se mover falhar
                    not_found_count += 1 # Contar como falha/não movido

            else:
                # Original não encontrado
                logger.warning(f"XML original para evento {event_file.name} (Tipo: {tp_evento}, Chave Orig: {chave_doc_orig}) não encontrado nas pastas esperadas. Evento permanece em {source_dir}.")
                not_found_count += 1
        # Fim do loop pelos arquivos na source_dir

        # Opcional: Remover a pasta de origem de eventos (EventoNFe/EventoCTe) se estiver vazia AGORA
        try:
            if source_dir.is_dir() and not any(source_dir.iterdir()): # Verifica se está vazia
                 source_dir.rmdir()
                 logger.info(f"Pasta de origem de eventos vazia removida: {source_dir}")
        except Exception as rmdir_err:
             logger.error(f"Erro ao tentar remover pasta de origem de eventos {source_dir}: {rmdir_err}")
    # Fim do loop pelos source_dirs

    logger.info(f"Organização de eventos finalizada para {month_path.name}. Movidos: {moved_count}, Não encontrados/Pendentes: {not_found_count}, Pulados (não cancel.): {skipped_non_cancel}.")
    return moved_count, not_found_count

def save_decoded_xml(
    base64_content: str,
    empresa_info: Dict[str, Any], # Espera 'cnpj', 'nome_pasta', 'ano', 'mes'
    base_path: Path
) -> Optional[Path]:
    """
    Decodifica um único XML Base64, extrai informações, determina o caminho
    e salva o arquivo.

    Retorna o Path do arquivo salvo ou None em caso de erro.
    """
    try:
        xml_content_bytes = base64.b64decode(base64_content)
    except (base64.binascii.Error, ValueError) as e_dec:
        logger.error(f"[{empresa_info.get('cnpj', 'CNPJ Desc')}] Falha ao decodificar Base64: {e_dec}")
        return None

    root = _parse_xml_content(xml_content_bytes)
    if root is None:
        logger.error(f"[{empresa_info.get('cnpj', 'CNPJ Desc')}] Falha ao parsear XML decodificado.")
        return None

    empresa_cnpj = empresa_info.get('cnpj')
    if not empresa_cnpj:
        logger.error("CNPJ da empresa não fornecido para _get_xml_info em save_decoded_xml.")
        return None

    # Extrai informações do XML parseado
    xml_info = _get_xml_info(root, empresa_cnpj)

    if not xml_info:
        logger.error(f"[{empresa_cnpj}] Não foi possível extrair informações do XML.")
        return None

    # Validar informações essenciais para salvar
    chave = xml_info.get('chave')
    tipo_doc = xml_info.get('tipo')
    direcao = xml_info.get('direcao')
    # --- MODIFICAÇÃO: Obter ano/mês do próprio XML --- 
    ano_mes_xml = xml_info.get('ano_mes') # Formato esperado: "YYYY/MM"
    if not ano_mes_xml or '/' not in ano_mes_xml:
        logger.error(f"[{empresa_cnpj}] Não foi possível extrair ano/mês do XML para a chave {chave}. Pulando salvamento.")
        return None
    ano, mes = ano_mes_xml.split('/')
    # -------------------------------------------------
    nome_pasta_empresa = empresa_info.get('nome_pasta') # Pega da info da empresa

    # Simplificação: Se for evento e não tiver direção, pular salvamento por enquanto.
    # A lógica de organização de eventos cuidará disso depois.
    if not direcao and tipo_doc and tipo_doc.startswith("Evento"):
         logger.warning(f"[{empresa_cnpj}] Direção não determinada para evento {chave} (Tipo: {tipo_doc}). Pulando salvamento individual, será tratado na organização.")
         return None # Retorna None, mas não é um erro crítico de salvamento

    if not all([chave, tipo_doc, direcao, ano, mes, nome_pasta_empresa]):
        logger.error(f"[{empresa_cnpj}] Informações incompletas extraídas/fornecidas para salvar XML. Chave:{chave}, Tipo:{tipo_doc}, Direcao:{direcao}, Ano:{ano}, Mes:{mes}, Pasta:{nome_pasta_empresa}")
        return None

    # Montar o caminho final
    # Ajustar tipo_doc para corresponder aos nomes de pasta (ex: EventoNFe -> NFe)
    if tipo_doc.startswith("Evento"):
         dir_tipo = tipo_doc.replace("Evento", "") # Salva evento na pasta do doc original
    else:
         dir_tipo = tipo_doc # NFe ou CTe

    # Nome do arquivo (tratar eventos)
    if tipo_doc.startswith("Evento") and xml_info.get("tp_evento") == "110111": # Ex: Cancelamento
        file_name = f"{chave}{EVENT_SUFFIX}{XML_EXTENSION}"
    else:
        file_name = f"{chave}{XML_EXTENSION}"

    try:
        save_dir = base_path / ano / nome_pasta_empresa / mes / dir_tipo / direcao
        save_dir.mkdir(parents=True, exist_ok=True)
        final_path = save_dir / file_name

        # --- Verificação Anti-Sobrescrita ---
        if final_path.exists():
            logger.warning(f"[{empresa_cnpj}] Arquivo já existe em {final_path}. Pulando salvamento para evitar sobrescrita.")
            # Considerar isso um 'sucesso' de salvamento no sentido que o arquivo está lá?
            # Ou um tipo diferente de status? Por ora, retornamos o path existente.
            return final_path # Retorna o path existente como indicativo que o arquivo está lá

        # --- Salvamento ---
        with open(final_path, 'wb') as f:
            f.write(xml_content_bytes)

        logger.debug(f"[{empresa_cnpj}] XML salvo com sucesso em: {final_path}")
        return final_path

    except OSError as e_os:
        logger.error(f"[{empresa_cnpj}] Erro de SO ao criar diretório ou salvar arquivo {final_path}: {e_os}")
        return None
    except Exception as e_save:
        logger.exception(f"[{empresa_cnpj}] Erro inesperado ao salvar arquivo {final_path}: {e_save}", exc_info=True)
        return None 
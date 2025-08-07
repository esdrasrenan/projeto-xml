"""Módulo para download específico de eventos da API SIEG."""

import logging
from datetime import datetime
from typing import Dict, Tuple, List, Optional

# Import relativo dentro do mesmo pacote 'core'
from .api_client import SiegApiClient
# Importar constantes de utils e mapeamentos
from .utils import XML_TYPE_NFE, XML_TYPE_CTE

logger = logging.getLogger(__name__)

# Mapeamento reverso de código para string (para logs/chaves) - Pode ser movido para utils/config
XML_TYPE_MAP_REV = {
    XML_TYPE_NFE: "NFe",
    XML_TYPE_CTE: "CTe"
}

# Mapeamento de papel para campo da API - Pode ser movido para utils/config
ROLE_MAP = {
    "Emitente": "CnpjEmit",
    "Destinatario": "CnpjDest",
    "Tomador": "CnpjTom"
    # Adicionar outros papéis se necessário para eventos específicos
}

TAKE_LIMIT = 50 # Limite de itens por página na API (ajustar conforme necessário)

def download_cancel_events(
    api_client: SiegApiClient,
    cnpj: str,
    start_date: datetime,
    end_date: datetime,
) -> List[str]: # Retorna uma lista única com todos os eventos de cancelamento
    """
    Baixa os eventos de cancelamento (110111, 110112, 610601) da API SIEG.

    Usa o endpoint /BaixarEventos com filtro por TipoEvento e paginação.
    Itera sobre os tipos (NFe, CTe), papéis (Emitente, Destinatario, Tomador)
    e tipos de evento relevantes.

    Args:
        api_client: Instância do cliente da API SIEG.
        cnpj: O CNPJ da empresa (já normalizado).
        start_date: Data de início para a busca de eventos.
        end_date: Data de fim para a busca de eventos.

    Returns:
        Uma lista única contendo todos os eventos de cancelamento (Base64)
        baixados. Retorna lista vazia se nenhum evento for encontrado ou em caso de erro.
    """
    all_events: List[str] = [] # Lista única para todos os eventos
    # Usar DataInicioEvento/DataFimEvento como no /BaixarEventos
    date_format = "%Y-%m-%d"
    data_inicio_str = start_date.strftime(date_format)
    data_fim_str = end_date.strftime(date_format)

    logger.info(f"[{cnpj}] Iniciando download de eventos de cancelamento ({data_inicio_str} a {data_fim_str}).")

    # Estrutura: (XmlTypeCode, PapelApiField, TipoEventoCode)
    # Códigos de evento de cancelamento
    EVENT_CODE_CANCEL_NFE = "110111"
    EVENT_CODE_CANCEL_SUBST_NFE = "110112"
    EVENT_CODE_CANCEL_CTE = "610601" # Código original CTe
    EVENT_CODE_CANCEL_CTE_ALT = "110111" # Código NFe às vezes usado para CTe

    event_queries = [
        # NFe (Tipo 1)
        (XML_TYPE_NFE, ROLE_MAP["Emitente"], EVENT_CODE_CANCEL_NFE),
        (XML_TYPE_NFE, ROLE_MAP["Destinatario"], EVENT_CODE_CANCEL_NFE),
        (XML_TYPE_NFE, ROLE_MAP["Emitente"], EVENT_CODE_CANCEL_SUBST_NFE),
        (XML_TYPE_NFE, ROLE_MAP["Destinatario"], EVENT_CODE_CANCEL_SUBST_NFE),
        # CTe (Tipo 2)
        (XML_TYPE_CTE, ROLE_MAP["Emitente"], EVENT_CODE_CANCEL_CTE),
        (XML_TYPE_CTE, ROLE_MAP["Destinatario"], EVENT_CODE_CANCEL_CTE),
        (XML_TYPE_CTE, ROLE_MAP["Tomador"], EVENT_CODE_CANCEL_CTE),
        (XML_TYPE_CTE, ROLE_MAP["Emitente"], EVENT_CODE_CANCEL_CTE_ALT),
        (XML_TYPE_CTE, ROLE_MAP["Destinatario"], EVENT_CODE_CANCEL_CTE_ALT),
        (XML_TYPE_CTE, ROLE_MAP["Tomador"], EVENT_CODE_CANCEL_CTE_ALT),
    ]

    for xml_type_code, api_field, event_type_code in event_queries:
        xml_type_str = XML_TYPE_MAP_REV.get(xml_type_code, "Desconhecido")
        # Encontra o nome do papel baseado no valor do campo da API (oposto do ROLE_MAP)
        role = next((k for k, v in ROLE_MAP.items() if v == api_field), "Desconhecido")
        log_key = (xml_type_str, role, event_type_code)

        logger.info(f"[{cnpj}] Iniciando download de eventos para {log_key}")

        combo_results: List[str] = []
        current_skip = 0

        while True:
            payload = {
                "TipoXml": xml_type_code,
                "TipoEvento": event_type_code,
                "Take": TAKE_LIMIT,
                "Skip": current_skip,
                "DataInicioEvento": data_inicio_str,
                "DataFimEvento": data_fim_str,
                api_field: cnpj,
            }

            try:
                logger.debug(f"[{cnpj}] Baixando lote de eventos para {log_key} - Skip: {current_skip}, Take: {TAKE_LIMIT}, Payload: {payload}")
                # A chamada à API pode retornar lista diretamente ou dict com 'Eventos'
                response = api_client.baixar_eventos(payload)

                if isinstance(response, list):
                    batch = response
                    logger.debug(f"[{cnpj}] Resposta de /BaixarEventos recebida como lista.")
                elif isinstance(response, dict):
                    batch = response.get("Eventos", []) # Assumindo que a chave é 'Eventos'
                    logger.debug(f"[{cnpj}] Resposta de /BaixarEventos recebida como dict.")
                else:
                    logger.warning(f"[{cnpj}] Resposta inesperada de /BaixarEventos para {log_key} (tipo {type(response)}): {response}. Considerando lote vazio.")
                    batch = []

                if not batch:
                    logger.info(f"[{cnpj}] Lote vazio de eventos recebido para {log_key} com Skip {current_skip}. Fim da paginação.")
                    break # Sai do while True

                batch_len = len(batch)
                logger.info(f"[{cnpj}] Recebido lote de {batch_len} eventos para {log_key} (Skip: {current_skip}).")
                combo_results.extend(batch)
                current_skip += TAKE_LIMIT # Incrementa para a próxima página

            except Exception as e:
                logger.error(f"[{cnpj}] Erro ao baixar lote de eventos para {log_key} com Skip {current_skip}. Abortando para esta combinação. Erro: {e}", exc_info=True)
                break # Sai do while True

        # Fim do while para a combinação
        logger.info(f"[{cnpj}] Download de eventos para {log_key} finalizado. Total baixado: {len(combo_results)}.")
        all_events.extend(combo_results) # Adiciona à lista geral

    # Fim do loop por event_queries
    logger.info(f"[{cnpj}] Download de eventos de cancelamento finalizado. Total geral baixado: {len(all_events)}.")

    return all_events

# Adicionar outras funções de download se necessário, como download_main_xmls (se for movida para cá)

# Remover o pass original se existir
# pass 
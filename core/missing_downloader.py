"""Módulo para baixar XMLs faltantes individualmente via API SIEG."""

import logging
import time
from pathlib import Path
from typing import List, Dict, Any

# Imports relativos dentro do pacote 'core'
from .api_client import SiegApiClient
from .file_manager import save_raw_xml # Precisaremos da função de salvar XML bruto

logger = logging.getLogger(__name__)

# Constante para o delay do rate limit (segundos)
# Usar o mesmo valor definido no SiegApiClient ou um valor ligeiramente maior
RATE_LIMIT_DELAY_MISSING = 2.1 # Garante um pouco menos de 30 req/min

def download_missing_xmls(
    keys_to_download: List[str],
    api_client: SiegApiClient,
    empresa_cnpj: str, # CNPJ para logs e talvez para salvar
    path_info: Dict[str, Any], # Dicionário com chaves como 'ano', 'mes', 'nome_pasta'
    base_xml_path: Path # Diretório raiz 'xmls'
) -> Dict[str, List[str]]:
    """
    Tenta baixar individualmente uma lista de chaves XML faltantes.

    Aplica rate limiting e usa o endpoint /BaixarXml.
    Salva os XMLs baixados com sucesso usando a lógica de file_manager.

    Args:
        keys_to_download: Lista das chaves de acesso (44 dígitos) a serem baixadas.
        api_client: Instância do cliente SiegApiClient.
        empresa_cnpj: CNPJ da empresa (para logging).
        path_info: Dicionário com informações para construir o caminho de salvamento
                   (ex: {'ano': '2023', 'mes': '04', 'nome_pasta': 'NOME EMPRESA'}).
        base_xml_path: Path para o diretório raiz onde os XMLs são salvos (a pasta 'xmls').

    Returns:
        Dicionário com duas chaves:
            'success': Lista das chaves baixadas e salvas com sucesso.
            'failed': Lista das chaves que falharam no download ou salvamento.
    """
    successful_keys: List[str] = []
    failed_keys: List[str] = []

    total_keys = len(keys_to_download)
    if total_keys == 0:
        logger.info(f"[{empresa_cnpj}] Nenhuma chave válida para download individual.")
        return {"success": [], "failed": []}

    logger.info(f"[{empresa_cnpj}] Iniciando tentativa de download individual para {total_keys} chave(s) faltante(s) válida(s)...")

    for i, key in enumerate(keys_to_download):
        logger.info(f"[{empresa_cnpj}] Tentando baixar chave {i+1}/{total_keys}: {key}")

        # Rate Limiting
        time.sleep(RATE_LIMIT_DELAY_MISSING)

        try:
            # 1. Determinar o tipo de XML baseado na chave (posições 20-21 = modelo)
            # NFe: modelo 55, CTe: modelo 57
            modelo = key[20:22] if len(key) >= 22 else "00"
            if modelo == "55":
                xml_type = 1  # NFe
            elif modelo == "57":
                xml_type = 2  # CTe
            else:
                logger.warning(f"[{empresa_cnpj}] Modelo desconhecido ({modelo}) para chave {key}. Assumindo NFe (tipo 1).")
                xml_type = 1  # Default para NFe

            # 2. Chamar a API para baixar o XML específico (incluindo eventos)
            xml_content = api_client.baixar_xml_especifico(key, xml_type, download_event=True)

            if xml_content:
                # 3. Se sucesso, salvar XML bruto
                try:
                    # A função save_raw_xml precisa:
                    # - raw_xml_content: str | bytes (XML bruto da API)
                    # - empresa_info: Dict (contendo 'cnpj', 'nome_pasta', 'ano', 'mes')
                    # - base_path: Path (diretório 'xmls')
                    # Ela internamente parseia o XML para achar tipo/direção.
                    file_saved_path = save_raw_xml(
                        raw_xml_content=xml_content,  # XML bruto da API
                        empresa_info={
                            'cnpj': empresa_cnpj, # Passa o CNPJ para a função de salvar
                            'nome_pasta': path_info['nome_pasta'],
                            'ano': path_info['ano'],
                            'mes': path_info['mes'],
                        },
                        base_path=base_xml_path
                    )
                    if file_saved_path:
                        logger.info(f"[{empresa_cnpj}] Chave {key} baixada e salva com sucesso em: {file_saved_path}")
                        successful_keys.append(key)
                    else:
                        # Se save_decoded_xml retornar None, houve erro no salvamento/parse
                        logger.error(f"[{empresa_cnpj}] Chave {key} baixada, mas falhou ao salvar/processar.")
                        failed_keys.append(key)

                except Exception as e_save:
                    logger.exception(f"[{empresa_cnpj}] Erro inesperado ao tentar salvar/processar XML para chave {key}: {e_save}", exc_info=True)
                    failed_keys.append(key)
            else:
                # Se baixar_xml_especifico retornou None, o erro já foi logado lá.
                logger.warning(f"[{empresa_cnpj}] Falha ao baixar chave {key} da API (ver logs anteriores).")
                failed_keys.append(key)

        except Exception as e_download:
            # Captura erros inesperados durante a chamada a baixar_xml_especifico
            logger.exception(f"[{empresa_cnpj}] Erro inesperado durante a tentativa de download da chave {key}: {e_download}", exc_info=True)
            failed_keys.append(key)

    # Fim do loop
    logger.info(f"[{empresa_cnpj}] Fim do download individual: {len(successful_keys)} sucesso(s), {len(failed_keys)} falha(s).")

    return {"success": successful_keys, "failed": failed_keys}
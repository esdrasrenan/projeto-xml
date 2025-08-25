"""Módulo cliente para interagir com a API SIEG."""

import requests
import time
import logging
import socket
import threading
import os
from typing import Dict, Any, Optional, List, Tuple
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
from urllib.parse import unquote, quote
from requests import HTTPError, RequestException
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

# Configuração básica de logging (pode ser movida/melhorada depois)
# Usar o mesmo logger configurado no file_manager ou configurar um específico aqui
# Por enquanto, vamos pegar um logger padrão
logger = logging.getLogger(__name__)
# Para ver logs de requests, descomente:
# logging.basicConfig(level=logging.DEBUG)

# Constante para heurística de Base64
MIN_BASE64_LEN = 200 # Ajustar se necessário

class SiegApiClient:
    """Cliente para interagir com a API REST da SIEG."""

    BASE_URL = "https://api.sieg.com"
    REQUEST_TIMEOUT = (10, 30)  # Timeout de conexão (10s) e leitura (30s) para evitar travamentos
    REPORT_REQUEST_TIMEOUT = (10, 20)  # Timeout mais curto para relatórios: conexão (10s) e leitura (20s)
    ABSOLUTE_TIMEOUT = 45  # Timeout absoluto máximo para qualquer operação (segundos) - PADRÃO
    
    # Timeouts configuráveis por tipo de documento (podem ser sobrescritos por variáveis de ambiente)
    TIMEOUT_NFE_ABSOLUTE = int(os.getenv("SIEG_TIMEOUT_ABSOLUTO_NFE", "90"))   # NFe: 90s padrão
    TIMEOUT_CTE_ABSOLUTE = int(os.getenv("SIEG_TIMEOUT_ABSOLUTO_CTE", "180"))  # CTe: 180s padrão (3 minutos)
    TIMEOUT_NFE_READ = int(os.getenv("SIEG_TIMEOUT_LEITURA_NFE", "120"))       # NFe: 120s leitura
    TIMEOUT_CTE_READ = int(os.getenv("SIEG_TIMEOUT_LEITURA_CTE", "180"))       # CTe: 180s leitura
    TIMEOUT_CONNECTION = int(os.getenv("SIEG_TIMEOUT_CONEXAO", "10"))          # Conexão: 10s
    
    RATE_LIMIT_DELAY = 2  # Segundos de espera entre requisições (30 req/min)
    RETRY_COUNT = 2  # Reduzido de 3 para 2 para evitar longos travamentos
    RETRY_BACKOFF_FACTOR = 0.5 # Reduzido de 1 para 0.5 segundos (0.5, 1)
    RETRY_STATUS_FORCELIST = (429, 500, 502, 503, 504) # Status para retentativa

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("API Key da SIEG é obrigatória.")
        # Decodifica a chave antes de armazenar/usar
        self.api_key = unquote(api_key)
        # Logar a chave decodificada (com cuidado)
        logger.debug(f"API Key decodificada para uso: {self.api_key[:4]}...{self.api_key[-4:]}")
        self.session = self._create_session()
        self._last_request_time = 0 # Para controle do rate limit

    def _create_session(self) -> requests.Session:
        """Cria uma sessão de requests com política de retry."""
        session = requests.Session()
        retries = Retry(
            total=self.RETRY_COUNT,
            backoff_factor=self.RETRY_BACKOFF_FACTOR,
            status_forcelist=self.RETRY_STATUS_FORCELIST,
            allowed_methods=["POST", "GET"], # Permitir retry em POST também
            raise_on_status=False # Deixar nosso código tratar o status final
        )
        # Montar nos prefixos http e https
        session.mount("https://", HTTPAdapter(max_retries=retries))
        session.mount("http://", HTTPAdapter(max_retries=retries))
        return session

    def _get_timeout_by_type(self, xml_type: int, timeout_type: str = "absolute") -> int:
        """
        Retorna o timeout apropriado baseado no tipo de documento.
        
        Args:
            xml_type: Tipo de XML (1=NFe, 2=CTe, etc.)
            timeout_type: "absolute" ou "read"
            
        Returns:
            Timeout em segundos
        """
        if xml_type == 2:  # CTe
            if timeout_type == "absolute":
                return self.TIMEOUT_CTE_ABSOLUTE
            elif timeout_type == "read":
                return self.TIMEOUT_CTE_READ
        elif xml_type == 1:  # NFe
            if timeout_type == "absolute":
                return self.TIMEOUT_NFE_ABSOLUTE
            elif timeout_type == "read":
                return self.TIMEOUT_NFE_READ
        
        # Padrão para outros tipos
        if timeout_type == "absolute":
            return self.ABSOLUTE_TIMEOUT
        else:
            return 30  # Padrão de leitura
    
    def _enforce_rate_limit(self):
        """Garante que o intervalo mínimo entre requisições seja respeitado."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        wait_time = self.RATE_LIMIT_DELAY - elapsed
        if wait_time > 0:
            logger.debug(f"Rate limit: esperando {wait_time:.2f} segundos.")
            time.sleep(wait_time)
        self._last_request_time = time.monotonic() # Atualiza o tempo da última requisição *antes* de fazer

    def _execute_with_absolute_timeout(self, func, *args, timeout_seconds=None, **kwargs):
        """
        Executa uma função com timeout absoluto usando ThreadPoolExecutor.
        
        Isso evita travamentos quando o socket não respeita o timeout configurado.
        """
        if timeout_seconds is None:
            timeout_seconds = self.ABSOLUTE_TIMEOUT
            
        start_time = time.monotonic()
        logger.debug(f"Iniciando execução com timeout absoluto de {timeout_seconds}s")
            
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(func, *args, **kwargs)
        
        try:
            result = future.result(timeout=timeout_seconds)
            elapsed = time.monotonic() - start_time
            logger.debug(f"Execução completada com sucesso em {elapsed:.1f}s")
            return result
        except FuturesTimeoutError:
            elapsed = time.monotonic() - start_time
            logger.error(f"TIMEOUT ABSOLUTO ({timeout_seconds}s) atingido após {elapsed:.1f}s! Abortando operação.")
            # Tentar cancelar a operação (pode não funcionar se já estiver travada)
            future.cancel()
            raise TimeoutError(f"Operação abortada após {timeout_seconds} segundos")
        except Exception as e:
            elapsed = time.monotonic() - start_time
            logger.debug(f"Exceção capturada após {elapsed:.1f}s: {type(e).__name__}: {str(e)}")
            # Re-lançar qualquer outra exceção
            raise
        finally:
            executor.shutdown(wait=False)

    def _make_report_request_direct(self, endpoint: str, payload: Dict[str, Any], xml_type: int) -> Any:
        """
        Método otimizado para requisições de relatórios - SEM overhead.
        Faz requisição direta similar ao n8n que funciona em ~34 segundos.
        
        Args:
            endpoint: O caminho do endpoint (ex: "/api/relatorio/xml").
            payload: O dicionário com os dados do relatório.
            xml_type: Tipo de XML para determinar timeout apropriado.
            
        Returns:
            Resposta da API (dict, string, etc).
        """
        full_url = f"{self.BASE_URL}{endpoint}"
        
        # API key na URL como query parameter (mantém codificada)
        # Nota: Mantemos a chave decodificada pois o requests vai re-codificar
        params = {"api_key": self.api_key}
        
        # Headers mínimos
        headers = {"Content-Type": "application/json"}
        
        # Timeout baseado no tipo de documento (mas sem ThreadPool)
        timeout_read = self._get_timeout_by_type(xml_type, "read")
        timeout_tuple = (self.TIMEOUT_CONNECTION, timeout_read)
        
        logger.info(f"[OTIMIZADO] Requisição DIRETA para relatório {endpoint}")
        logger.debug(f"Timeout configurado: {timeout_tuple[0]}s conexão, {timeout_tuple[1]}s leitura")
        
        try:
            # Requisição DIRETA - sem session, sem retries, sem ThreadPool
            response = requests.post(
                full_url,
                params=params,
                json=payload,
                headers=headers,
                timeout=timeout_tuple
            )
            
            # Log da resposta
            logger.debug(f"Resposta recebida ({response.status_code}) de {endpoint}")
            
            # Processar resposta
            if response.status_code == 200:
                try:
                    return response.json()
                except json.JSONDecodeError:
                    # Se não for JSON, retorna o texto
                    return response.text
            else:
                # Para erros, tenta pegar JSON de erro ou texto
                try:
                    error_data = response.json()
                    logger.error(f"Erro da API ({response.status_code}): {error_data}")
                    raise ValueError(f"Erro da API: {error_data}")
                except json.JSONDecodeError:
                    logger.error(f"Erro HTTP {response.status_code}: {response.text[:500]}")
                    response.raise_for_status()
                    
        except requests.Timeout as e:
            logger.error(f"Timeout na requisição direta para {endpoint}: {e}")
            raise
        except requests.RequestException as e:
            logger.error(f"Erro de requisição para {endpoint}: {e}")
            raise
    
    def _make_request(self, endpoint: str, payload: Optional[Dict[str, Any]] = None, timeout: Optional[Tuple[float, float]] = None) -> Any:
        """
        Método base para realizar requisições POST para a API SIEG.

        Args:
            endpoint: O caminho do endpoint (ex: "/BaixarXmls").
            payload: O dicionário Python a ser enviado como JSON no corpo da requisição.
            timeout: Tupla opcional (connect_timeout, read_timeout) para sobrescrever o padrão.

        Returns:
            O corpo da resposta JSON decodificado (pode ser Dict, List, etc.).

        Raises:
            requests.exceptions.RequestException: Se ocorrer um erro de rede irrecuperável.
            ValueError: Se a resposta não for JSON válido ou indicar um erro da API.
            requests.exceptions.HTTPError: Para códigos de status de erro específicos após retries.
        """
        full_url = f"{self.BASE_URL}{endpoint}"
        # Passa a chave (já decodificada) para requests tratar a codificação
        params = {"api_key": self.api_key}
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        self._enforce_rate_limit() # Garante o delay *antes* da requisição

        logger.debug(f"Enviando POST para URL base: {full_url}")
        # Não logar mais os params aqui para não expor a chave decodificada completa
        # logger.debug(f"Params: {params}")
        logger.debug(f"Payload: {json.dumps(payload)}")

        try:
            response = self.session.post(
                full_url,
                params=params,
                json=payload,
                headers=headers,
                timeout=timeout or self.REQUEST_TIMEOUT
            )

            # Verifica se houve erro mesmo após retries
            # O raise_for_status() do requests não é ideal aqui porque queremos
            # analisar o JSON de erro específico da SIEG primeiro.
            if response.status_code == 429:
                 # Tratamento específico para 429 mesmo após retries da session
                 # A lib de retry já espera 60s por padrão para o header Retry-After
                 # Se chegar aqui, é porque excedeu as tentativas ou não havia Retry-After.
                 # Vamos logar e levantar um erro mais específico se necessário,
                 # mas por ora, o status code será suficiente.
                 logger.error(f"Rate limit (429) persistente após {self.RETRY_COUNT} tentativas para {full_url}.")
                 # Poderia levantar um erro customizado aqui: raise RateLimitError(...)

            # Tentativa de decodificar JSON mesmo em caso de erro (API pode retornar JSON de erro)
            try:
                response_data = response.json()
                # Usar repr para evitar problemas com grandes volumes de dados no log
                log_preview = repr(response_data)[:200] + ('...' if len(repr(response_data)) > 200 else '')
                logger.debug(f"Resposta recebida ({response.status_code}): {log_preview}")
            except json.JSONDecodeError:
                 # Se não for JSON, levantar erro HTTP padrão se status for de erro
                 logger.error(f"Resposta não JSON ({response.status_code}) de {full_url}: {response.text[:200]}...") # Loga parte do texto
                 response.raise_for_status() # Levanta HTTPError para códigos >= 400
                 # Se não levantou erro (ex: status 2xx mas não JSON), pode ser um problema
                 raise ValueError(f"Resposta inesperada não-JSON com status {response.status_code} de {full_url}")

            # Verificar se o JSON contém a chave "Status" indicando erro da API SIEG
            # *Apenas* se a resposta for um dicionário
            if isinstance(response_data, dict) and "Status" in response_data:
                # Verifica se "Status" é uma lista e não está vazia
                status_messages = response_data.get("Status")
                if isinstance(status_messages, list) and status_messages:
                    error_message = ", ".join(status_messages)
                    logger.error(f"Erro da API SIEG ({response.status_code}) para {full_url}: {error_message}")
                    # Poderíamos mapear certas mensagens para exceções específicas se necessário
                    # Por enquanto, levantamos um ValueError genérico com a mensagem
                    raise ValueError(f"Erro da API SIEG: {error_message}")
                # Se a chave "Status" existe mas está vazia ou não é lista, pode ser sucesso (depende da API)
                # Ou pode ser um formato inesperado. Vamos assumir que é erro se status code >= 400
                elif response.status_code >= 400:
                     logger.error(f"Resposta JSON com chave 'Status' mas formato inesperado ou vazia, e status code {response.status_code}: {response_data}")
                     response.raise_for_status() # Re-levanta erro HTTP AQUI, pois é um erro da API

            # Retorna os dados (ou erro JSON da API) para o chamador decidir
            return response_data

        except requests.exceptions.RequestException as e:
            logger.error(f"Erro de rede ou requisição para {full_url}: {e}")
            raise # Re-levanta a exceção original

    # --- Métodos específicos para cada endpoint virão aqui ---

    def contar_xmls(self, payload: Dict[str, Any]) -> Dict[str, Any]:
         """Chama o endpoint /ContarXmls e retorna o JSON de resposta.

         Espera-se que a resposta contenha uma chave como 'Total'.

         Args:
             payload: Dicionário com os filtros para a contagem (XmlType, CnpjEmit/Dest/Tom, Datas).

         Returns:
             Dicionário JSON da resposta da API.

         Raises:
             requests.exceptions.RequestException: Se ocorrer um erro de rede irrecuperável.
             ValueError: Se a resposta não for JSON válido ou indicar um erro da API.
             requests.exceptions.HTTPError: Para códigos de status de erro específicos após retries.
         """
         logger.info(f"Chamando /ContarXmls com payload: {json.dumps(payload)}")
         response_data = self._make_request("/ContarXmls", payload)
         # Validação adicional opcional: verificar se 'Total' existe na resposta
         if 'Total' not in response_data:
              logger.warning(f"Resposta de /ContarXmls não contém a chave 'Total': {response_data}")
              # Decidir se lança erro ou retorna assim mesmo. Vamos retornar.
         # Garantir que o retorno seja Dict[str, Any] conforme a assinatura
         if not isinstance(response_data, dict):
             logger.error(f"Resposta inesperada de /ContarXmls (esperava um dict): {type(response_data)}")
             raise ValueError(f"Formato inesperado na resposta de /ContarXmls: {type(response_data)}")
         return response_data

    def baixar_xmls(self, payload: Dict[str, Any]) -> List[str]:
        """Chama o endpoint /BaixarXmls e retorna lista de XMLs em Base64."""
        logger.info(f"Chamando /BaixarXmls com payload: {json.dumps(payload)}")
        try:
            response_data = self._make_request("/BaixarXmls", payload)

            # --- INÍCIO: Tratamento para resposta como string --- #
            if isinstance(response_data, str):
                logger.warning("Resposta de /BaixarXmls foi string, tentando parsear como JSON...")
                try:
                    response_data = json.loads(response_data)
                    logger.info("Parse da string JSON da resposta de /BaixarXmls bem-sucedido.")
                except json.JSONDecodeError as e:
                    logger.error(f"Falha ao parsear string da resposta de /BaixarXmls como JSON: {e}")
                    logger.debug(f"String recebida (preview): {response_data[:200]}...")
                    return []
            # --- FIM: Tratamento para resposta como string --- #

            if isinstance(response_data, list):
                if all(isinstance(item, str) for item in response_data):
                    logger.info(f"Recebidos {len(response_data)} XMLs (Base64) de /BaixarXmls.")
                    return response_data
                else:
                    logger.error(f"Resposta de /BaixarXmls é uma lista, mas contém itens não-string: {response_data[:5]}...")
                    return []
            else:
                logger.error(f"Resposta inesperada de /BaixarXmls (esperava List[str] ou Str->List): {type(response_data)} - {repr(response_data)[:200]}...")
                return []
        except (RequestException, ValueError) as e:
            logger.error(f"Erro final ao chamar /BaixarXmls: {e}")
            return []

    def baixar_xml_especifico(self, xml_key: str, xml_type: int, download_event: bool = False) -> str | bytes | None:
        """
        Chama o endpoint /BaixarXml para baixar um único XML bruto pela chave.

        Implementa fallback automático: se download_event=True falhar com HTTP 400,
        tenta novamente com download_event=False.

        Args:
            xml_key: Chave de acesso do XML (44 dígitos)
            xml_type: Tipo do XML (1=NFe, 2=CTe)
            download_event: Se True, baixa também eventos relacionados ao XML

        Returns:
            Conteúdo XML bruto (string ou bytes) ou None em caso de erro.
        """
        # Primeira tentativa com os parâmetros originais
        result = self._baixar_xml_especifico_internal(xml_key, xml_type, download_event)

        # Se falhou E estava tentando baixar eventos, tenta fallback sem eventos
        if result is None and download_event:
            logger.warning(f"Primeira tentativa COM eventos falhou para chave {xml_key}. Tentando fallback SEM eventos...")
            result = self._baixar_xml_especifico_internal(xml_key, xml_type, download_event=False)

            if result is not None:
                logger.info(f"✅ Fallback SEM eventos SUCEDEU para chave {xml_key}!")
            else:
                logger.error(f"❌ Fallback SEM eventos também FALHOU para chave {xml_key}.")

        return result

    def _baixar_xml_especifico_internal(self, xml_key: str, xml_type: int, download_event: bool = False) -> str | bytes | None:
        """
        Implementação interna do download de XML específico.

        Args:
            xml_key: Chave de acesso do XML (44 dígitos)
            xml_type: Tipo do XML (1=NFe, 2=CTe)
            download_event: Se True, baixa também eventos relacionados ao XML

        Returns:
            Conteúdo XML bruto (string ou bytes) ou None em caso de erro.
        """
        endpoint = "/BaixarXml"
        # Montar a URL completa com parâmetros query
        params = {
            "api_key": self.api_key,
            "xmlType": xml_type,
            "downloadEvent": download_event
        }
        full_url = f"{self.BASE_URL}{endpoint}"

        # Corpo da requisição é a chave XML como string simples
        payload_raw = xml_key
        headers = {"Content-Type": "application/json", "Accept": "application/json"} # Manter headers? Testar Accept: */*? Por ora, manter json.

        self._enforce_rate_limit() # Garante o delay *antes* da requisição

        logger.info(f"Enviando POST para {full_url} com chave no corpo para: {xml_key} (Tipo: {xml_type}, DownloadEvent: {download_event})")
        # Não logar payload_raw diretamente se for muito longo

        try:
            response = self.session.post(
                full_url,
                params=params,
                data=payload_raw.encode('utf-8'), # Enviar chave como bytes UTF-8 no corpo
                headers=headers,
                timeout=self.REQUEST_TIMEOUT
            )

            # Log básico da resposta
            logger.debug(f"Resposta recebida ({response.status_code}) de {endpoint} para chave {xml_key}. Content-Type: {response.headers.get('Content-Type')}")

            # Verificar status de sucesso (200 OK)
            if response.status_code == 200:
                if response.content: # Verificar se há conteúdo
                    # A API retorna o XML como uma string JSON (com aspas duplas)
                    # Exemplo: "<?xml version=\"1.0\"...>"
                    try:
                        # Tentar decodificar como JSON primeiro
                        xml_string = response.json()
                        if isinstance(xml_string, str):
                            logger.info(f"XML baixado como string JSON (status {response.status_code}) para chave {xml_key}.")
                            # Retornar a string XML (sem as aspas JSON)
                            return xml_string.encode('utf-8')
                        else:
                            logger.warning(f"Resposta JSON não é string para chave {xml_key}: {type(xml_string)}")
                            return None
                    except json.JSONDecodeError:
                        # Se não for JSON válido, tentar como texto bruto
                        logger.info(f"XML baixado como texto bruto (status {response.status_code}) para chave {xml_key}.")
                        return response.content
                else:
                    logger.error(f"Resposta 200 OK, mas corpo vazio de {endpoint} para chave {xml_key}.")
                    return None
                # else:
                #     logger.error(f"Resposta 200 OK, mas Content-Type inesperado ({content_type}) de {endpoint} para chave {xml_key}. Corpo (preview): {response.text[:200]}...")
                #     return None # Ou retornar o texto mesmo assim? Por ora, falha.

            # Se não for 200 OK, tratar como erro
            else:
                # Tentar ler o corpo como texto para log
                error_body = response.text
                logger.error(f"Erro da API ({response.status_code}) ao chamar {endpoint} para chave {xml_key}. Resposta: {error_body[:500]}...")
                # Levantar erro HTTP para sinalizar falha não recuperada
                # response.raise_for_status() # Ou apenas retornar None?
                return None # Retornar None indica falha na obtenção do XML

        except requests.exceptions.RequestException as e:
            logger.error(f"Erro de rede ou requisição para {endpoint} (chave {xml_key}): {e}")
            raise # Re-levanta a exceção original para tratamento superior se necessário
        except TimeoutError:
            # Re-lançar TimeoutError para que seja tratado pelos chamadores
            logger.debug(f"TimeoutError capturado em _baixar_xml_especifico_internal, re-lançando para chave {xml_key}")
            raise
        except Exception as e:
            logger.exception(f"Erro inesperado ao chamar {endpoint} para chave {xml_key}: {e}", exc_info=True)
            return None # Retornar None em caso de erro inesperado

    def baixar_eventos(self, payload: Dict[str, Any]) -> List[str]:
        """Chama o endpoint /BaixarEventos e retorna lista de eventos em Base64.

        Esta função faz a chamada diretamente devido a inconsistências na API
        sobre onde a api_key deve ser passada para este endpoint específico.
        """
        endpoint = "/BaixarEventos"
        # CONSTRUÇÃO ESPECIAL DA URL PARA ESTE ENDPOINT:
        # Codifica a chave API antes de adicioná-la à URL.
        encoded_api_key = quote(self.api_key)
        full_url_with_key = f"{self.BASE_URL}{endpoint}?api_key={encoded_api_key}"

        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        self._enforce_rate_limit() # Garante o delay *antes* da requisição

        logger.info(f"Chamando /BaixarEventos (URL especial codificada) com payload: {json.dumps(payload)}")
        logger.debug(f"URL usada: {full_url_with_key}") # Loga a URL completa para depuração

        try:
            # Usar a session para manter retries, mas fazer a chamada POST diretamente
            response = self.session.post(
                full_url_with_key,
                json=payload,
                headers=headers,
                timeout=self.REQUEST_TIMEOUT
            )

            # Tratamento de resposta similar ao _make_request, adaptado:
            response_data: Any = None
            try:
                # Primeiro verifica se a resposta é a string esperada para "não encontrado"
                if response.status_code == 200 and response.text == "Eventos não encontrados!":
                    logger.info("Recebida string 'Eventos não encontrados!' de /BaixarEventos. Tratando como nenhum evento encontrado.")
                    return [] # Retorna lista vazia como esperado

                # Se não for a string, tenta decodificar JSON
                response_data = response.json()
                log_preview = repr(response_data)[:200] + ('...' if len(repr(response_data)) > 200 else '')
                logger.debug(f"Resposta recebida de /BaixarEventos ({response.status_code}): {log_preview}")

            except json.JSONDecodeError:
                logger.error(f"Resposta não JSON ({response.status_code}) de {endpoint}: {response.text[:200]}...")
                response.raise_for_status()
                raise ValueError(f"Resposta inesperada não-JSON com status {response.status_code} de {endpoint}")

            # Validações adicionais de erro da API SIEG (se aplicável a este endpoint)
            if isinstance(response_data, dict) and "Status" in response_data:
                status_messages = response_data.get("Status")
                if isinstance(status_messages, list) and status_messages:
                    error_message = ", ".join(status_messages)
                    logger.error(f"Erro da API SIEG ({response.status_code}) para {endpoint}: {error_message}")
                    raise ValueError(f"Erro da API SIEG: {error_message}")
                elif response.status_code >= 400:
                     logger.error(f"Resposta JSON com chave 'Status' mas formato inesperado ou vazia, e status code {response.status_code}: {response_data}")
                     response.raise_for_status()

            # Verificar se a resposta é realmente uma lista de strings (Base64)
            if isinstance(response_data, list) and all(isinstance(item, str) for item in response_data):
                logger.info(f"Recebidos {len(response_data)} eventos (Base64) de /BaixarEventos.")
                return response_data
            # Tratamento para a string "Eventos não encontrados!" já foi feito
            # Se chegou aqui com status 200 mas não é lista de strings nem a msg de erro, é inesperado
            elif response.status_code == 200:
                 logger.error(f"Resposta inesperada de /BaixarEventos (esperava List[str] ou Str 'Eventos não encontrados!'): {type(response_data)} - {log_preview}")
                 # Retornar vazio para não quebrar o fluxo principal, mas logar erro
                 return []
            else:
                # Se não for 200 e não caiu nos erros anteriores, levanta erro HTTP
                response.raise_for_status()
                # Fallback caso raise_for_status não levante por algum motivo
                raise ValueError(f"Resposta inesperada de /BaixarEventos: Status {response.status_code}, Tipo {type(response_data)}")

        except requests.exceptions.RequestException as e:
            # Tratamento específico para 404 neste endpoint problemático
            if isinstance(e, HTTPError) and e.response.status_code == 404:
                logger.warning(f"Recebido status 404 de {endpoint}, URL: {full_url_with_key}. Assumindo nenhum evento encontrado devido à instabilidade da API.")
                return [] # Retorna lista vazia em caso de 404
            else:
                # Para outros erros de rede/requisição, loga e re-levanta
                logger.error(f"Erro de rede ou requisição não-404 para {endpoint}: {e}")
                raise # Re-levanta a exceção original

    def baixar_relatorio_xml(self, cnpj: str, xml_type: int, month: int, year: int, report_type=None, use_absolute_timeout=True) -> Dict[str, Any]:
        """
        Baixa o relatório mensal (Excel) para um determinado tipo de documento fiscal.

        Args:
            cnpj: CNPJ da empresa.
            xml_type: Tipo de XML:
                1 = NFe (Nota Fiscal Eletrônica)
                2 = CTe (Conhecimento de Transporte Eletrônico)
                3 = NFSe (Nota Fiscal de Serviço Eletrônica)
                4 = NFCe (Nota Fiscal de Consumidor Eletrônica)
                5 = CFe (Cupom Fiscal Eletrônico)
            month: Mês (1-12).
            year: Ano (ex: 2023).
            report_type: Tipo de relatório:
                1 = Monofasico (apenas para XmlType 1-NFe ou 4-NFCe)
                2 = RelatorioBasico (apenas para XmlType 1-NFe ou 4-NFCe)
                3 = DetalhamentoProdutos (apenas para XmlType 1-NFe ou 4-NFCe)
                4 = CTe (apenas para XmlType 2-CTe)
                5 = NFSe (apenas para XmlType 3-NFSe)
                Se None, será mapeado automaticamente com base no xml_type.

        Returns:
            Dicionário contendo:
                "RelatorioBase64": string Base64 do arquivo Excel (ou None).
                "EmptyReport": True se a API indicou nenhum dado, False caso contrário.
                "StatusMessage": Mensagem informativa (ex: "Nenhum arquivo xml encontrado").
                "ErrorMessage": Mensagem de erro se ocorreu um problema.
        """
        log_context = f"({cnpj}, tipo={xml_type}, mes={month}/{year})" # Contexto para logs
        try:
            endpoint = "/api/relatorio/xml"

            # Mapear automaticamente o tipo de relatório com base no tipo de documento
            if report_type is None:
                if xml_type in [1, 4]:  # NFe ou NFCe
                    report_type = 2      # RelatorioBasico
                elif xml_type == 2:      # CTe
                    report_type = 4      # CTe
                elif xml_type == 3:      # NFSe
                    report_type = 5      # NFSe
                else:
                    report_type = 2      # Padrão para outros tipos
                    logger.warning(f"Tipo de XML {xml_type} não mapeado explicitamente para um tipo de relatório. Usando padrão (2-RelatorioBasico).")

            payload = {
                "Cnpj": cnpj,
                "TypeXmlDownloadReport": report_type,
                "XmlType": xml_type,
                "Month": month,
                "Year": year
            }
            
            logger.info(f"Chamando {endpoint} com payload: {json.dumps(payload)} {log_context}")
            
            # OTIMIZAÇÃO: Usar requisição direta para relatórios (sem overhead)
            # Relatórios podem demorar muito (30-180s), então não precisamos do ThreadPool
            try:
                response_data = self._make_report_request_direct(endpoint, payload, xml_type)
                logger.info(f"Relatório baixado com sucesso via método otimizado para {log_context}")
            except requests.Timeout as e:
                logger.error(f"TIMEOUT ao baixar relatório para {log_context}: {e}")
                # Re-lançar como TimeoutError para manter compatibilidade
                raise TimeoutError(f"Timeout ao baixar relatório: {e}")
            except Exception as e:
                logger.error(f"Erro ao baixar relatório via método otimizado para {log_context}: {e}")
                raise

            if isinstance(response_data, str):
                # Verificar se é a mensagem "Nenhum arquivo xml encontrado"
                if response_data.strip().lower() == "nenhum arquivo xml encontrado":
                    logger.info(f"API informou \'Nenhum arquivo xml encontrado\' para {log_context}.")
                    return {"RelatorioBase64": None, "EmptyReport": True, "StatusMessage": response_data.strip(), "ErrorMessage": None}
                # Assumir que é Base64 se for uma string longa
                elif len(response_data) >= MIN_BASE64_LEN:
                    logger.info(f"Relatório Base64 recebido diretamente como string para {log_context}.")
                    return {"RelatorioBase64": response_data, "EmptyReport": False, "StatusMessage": "Relatório Base64 em string.", "ErrorMessage": None}
                else:
                    # String curta, não é "nenhum arquivo" e nem parece Base64 - pode ser um erro inesperado
                    logger.warning(f"Resposta string curta/inesperada de {endpoint} para {log_context}: {response_data}")
                    return {"RelatorioBase64": None, "EmptyReport": False, "ErrorMessage": f"Resposta string inesperada: {response_data}", "StatusMessage": None}

            elif isinstance(response_data, dict):
                if "RelatorioBase64" in response_data:
                    if response_data["RelatorioBase64"]:
                        logger.info(f"Relatório Base64 recebido como JSON para {log_context}.")
                        return {"RelatorioBase64": response_data["RelatorioBase64"], "EmptyReport": False, "StatusMessage": "Relatório Base64 em JSON.", "ErrorMessage": None}
                    else:
                        logger.info(f"Chave \'RelatorioBase64\' encontrada, mas vazia na resposta JSON para {log_context}.")
                        return {"RelatorioBase64": None, "EmptyReport": True, "StatusMessage": "RelatorioBase64 vazio em JSON.", "ErrorMessage": None}
                else:
                    logger.error(f"Resposta de {endpoint} é um dicionário mas não contém \'RelatorioBase64\' para {log_context}: {repr(response_data)[:200]}...")
                    return {"RelatorioBase64": None, "EmptyReport": False, "ErrorMessage": f"JSON sem RelatorioBase64: {repr(response_data)[:200]}", "StatusMessage": None}

            else:
                logger.error(f"Tipo de resposta inesperado de {endpoint} ({type(response_data)}) para {log_context}: {repr(response_data)[:200]}...")
                return {"RelatorioBase64": None, "EmptyReport": False, "ErrorMessage": f"Tipo de resposta inesperado: {type(response_data)}", "StatusMessage": None}

        except (RequestException, ValueError) as e:
            error_msg = str(e)
            # Adiciona informação se foi timeout
            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                logger.error(f"TIMEOUT ao chamar {endpoint} para {log_context}: {e}")
                error_msg = f"Timeout na requisição: {error_msg[:150]}"
            else:
                logger.error(f"Erro final ao chamar {endpoint} para {log_context}: {e}")
            return {"RelatorioBase64": None, "EmptyReport": False, "ErrorMessage": f"Erro de Requisição ou Valor: {error_msg[:200]}", "StatusMessage": None}
        except TimeoutError:
            # Re-lançar TimeoutError para que seja tratado pelos chamadores
            logger.debug(f"TimeoutError capturado em baixar_relatorio_xml, re-lançando para {log_context}")
            raise
        except Exception as e:
            logger.exception(f"Erro inesperado ao chamar {endpoint} para {log_context}: {e}", exc_info=True)
            return {"RelatorioBase64": None, "EmptyReport": False, "ErrorMessage": f"Erro inesperado: {str(e)[:100]}", "StatusMessage": None}

# Remover o pass original se existir
# pass
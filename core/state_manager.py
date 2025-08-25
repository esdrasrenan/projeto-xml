"""Módulo para gerenciar o estado do processo de download incremental."""

import logging
import json
from pathlib import Path
from typing import Dict, Optional, Any, List, Tuple
from datetime import datetime
import threading
import os

logger = logging.getLogger(__name__)

DEFAULT_STATE_FILENAME = "state.json"
MAX_PENDENCY_ATTEMPTS = 10 # Definir um limite geral para tentativas de pendências de relatório

# Constantes para Status de Pendência
STATUS_PENDING_API = "pending_api_response"       # Falha na comunicação ou resposta inválida da API
STATUS_PENDING_PROC = "pending_processing"      # Falha no processamento local (ex: salvar relatório)
STATUS_NO_DATA = "no_data_confirmed"         # API confirmou que não há dados
STATUS_MAX_RETRY = "max_attempts_reached"      # Atingiu o limite máximo de tentativas de pendência

# Constantes para Status Informativo de Download (opcional, pode espelhar os de pendência)
DOWNLOAD_SUCCESS = "success"
DOWNLOAD_SUCCESS_PENDENCY = "success_pendency" # Indica sucesso após ser pendência
DOWNLOAD_FAILED_API = "failed_api"
DOWNLOAD_FAILED_PROC = "failed_processing"
DOWNLOAD_NO_DATA_PENDENCY = "no_data_confirmed_pendency" # Indica sem dados após ser pendência
DOWNLOAD_SKIPPED_NO_DATA = "no_data_confirmed_skipped" # Pulado pois já estava confirmado sem dados
DOWNLOAD_SKIPPED_MAX_ATTEMPTS = "max_attempts_skipped"    # Pulado pois atingiu limite de tentativas

class StateManager:
    """Gerencia o estado (principalmente contadores 'skip') do processo de download.

    Armazena o estado em um arquivo JSON para persistência entre execuções.
    A estrutura do estado é:
    {
        "YYYY-MM": {              # Chave: Ano e Mês (ex: "2024-05")
            "CNPJ_DA_EMPRESA": {  # Chave: CNPJ normalizado
                "TipoXML_Papel": skip_count,  # Chave: ex "NFe_Emitente", Valor: int
                ...
            },
            ...
        },
        "_metadata": {            # Metadados sobre o estado
             "last_seed_run_iso": "YYYY-MM-DDTHH:MM:SS.ffffff" # Opcional
        }
        ...
    }
    """

    def __init__(self, state_file_path: Path = Path(DEFAULT_STATE_FILENAME)):
        """Inicializa o StateManager.

        Args:
            state_file_path: O caminho completo para o arquivo JSON de estado.
        """
        self.state_file_path = state_file_path
        self.state: Dict[str, Any] = {
            "processed_xml_keys": {},  # cnpj_norm -> month_str -> report_type -> set of keys
            "xml_skip_counts": {},     # cnpj_norm -> month_str -> report_type -> papel -> skip_count
            "report_download_status": {}, # cnpj_norm -> month_str -> report_type -> status (ex: "success", "failed_api", "failed_processing", "no_data")
            "report_pendencies": {},   # cnpj_norm -> month_str -> report_type_str -> {attempts, last_attempt, status}
            "last_successful_run": None,
            "schema_version": 2
        }
        self._lock = threading.Lock() # Adicionar lock para thread-safety
        # self.load_state() # Carga inicial pode ser feita explicitamente pelo chamador
        logger.info(f"StateManager inicializado com arquivo: {self.state_file_path}")

    def _ensure_nested_dicts_exist(self, cnpj_norm: str, month_str: str, report_type_str: Optional[str] = None, papel: Optional[str] = None) -> None:
        """Garante que a estrutura de dicionário aninhada exista no estado até o nível especificado."""
        # Garante chaves principais
        if "xml_skip_counts" not in self.state: self.state["xml_skip_counts"] = {}
        if "report_pendencies" not in self.state: self.state["report_pendencies"] = {}
        if "report_download_status" not in self.state: self.state["report_download_status"] = {}
        # ... outras chaves principais se necessário ...

        # Garante estrutura para xml_skip_counts
        skip_counts = self.state["xml_skip_counts"]
        if cnpj_norm not in skip_counts:
            skip_counts[cnpj_norm] = {}
        cnpj_data = skip_counts[cnpj_norm]

        if month_str not in cnpj_data:
            cnpj_data[month_str] = {}
        month_data = cnpj_data[month_str]

        if report_type_str and report_type_str not in month_data:
            month_data[report_type_str] = {}
        # Não precisamos ir até papel aqui, pois ele é a chave final no dicionário de report_type_str

        # Garante estrutura para report_pendencies
        pendencies = self.state["report_pendencies"]
        if cnpj_norm not in pendencies:
            pendencies[cnpj_norm] = {}
        if month_str not in pendencies[cnpj_norm]:
            pendencies[cnpj_norm][month_str] = {}

        # Garante estrutura para report_download_status
        download_status = self.state["report_download_status"]
        if cnpj_norm not in download_status:
            download_status[cnpj_norm] = {}
        if month_str not in download_status[cnpj_norm]:
            download_status[cnpj_norm][month_str] = {}

    def load_state(self) -> None:
        with self._lock:
            try:
                if self.state_file_path.exists():
                    with open(self.state_file_path, 'r', encoding='utf-8') as f:
                        loaded_data = json.load(f)

                    # --- INÍCIO: Lógica de Migração de Schema --- #
                    schema_version = loaded_data.get("schema_version", 1) # Assumir 1 se ausente
                    if schema_version < 2:
                        logger.warning(f"Detectado schema antigo (v{schema_version}) no state.json. Tentando migrar skip counts...")
                        migrated_skips = False
                        if "xml_skip_counts" not in loaded_data:
                             loaded_data["xml_skip_counts"] = {}

                        # Estrutura antiga: loaded_data[month_str][cnpj_norm]["Tipo_Papel"] = skip
                        keys_to_delete_from_root = []
                        for key, value in loaded_data.items():
                            # Verificar se a chave parece ser um mês/ano (ex: "2024-05")
                            if isinstance(value, dict) and '-' in key and len(key) == 7:
                                month_str = key
                                for cnpj_norm, month_data in value.items():
                                    if isinstance(month_data, dict):
                                        keys_to_delete_from_cnpj = []
                                        for state_key, skip_count in month_data.items():
                                            # Tentar parsear a chave antiga (ex: "NFe_Destinatario")
                                            if '_' in state_key and isinstance(skip_count, int):
                                                parts = state_key.split('_', 1)
                                                if len(parts) == 2:
                                                    report_type_str, papel = parts
                                                    # Garantir estrutura e migrar
                                                    if report_type_str in ["NFe", "CTe"] and papel in ["Emitente", "Destinatario", "Tomador"]:
                                                        skips_cn = loaded_data.setdefault("xml_skip_counts", {}).setdefault(cnpj_norm, {})
                                                        skips_mo = skips_cn.setdefault(month_str, {})
                                                        skips_ty = skips_mo.setdefault(report_type_str, {})
                                                        skips_ty[papel] = skip_count
                                                        migrated_skips = True
                                                        logger.debug(f"Migrado skip: [\"xml_skip_counts\"][{cnpj_norm}][{month_str}][{report_type_str}][{papel}] = {skip_count}")
                                                        # Marcar chave antiga para remoção (OPCIONAL)
                                                        # keys_to_delete_from_cnpj.append(state_key)

                                        # Remover chaves antigas migradas (OPCIONAL)
                                        # for old_key in keys_to_delete_from_cnpj:
                                        #     month_data.pop(old_key, None)

                        if migrated_skips:
                             logger.info("Migração dos skip counts do schema antigo concluída.")
                             loaded_data["schema_version"] = 2 # Atualiza a versão do schema
                        else:
                             logger.info("Nenhum skip count encontrado na estrutura antiga para migrar.")
                             # Se não migrou nada, mas a versão era antiga, atualiza mesmo assim?
                             # Sim, para evitar tentar migrar de novo.
                             if schema_version < 2: loaded_data["schema_version"] = 2
                    # --- FIM: Lógica de Migração de Schema --- #

                    # Inicialização de chaves ausentes (redundante se migração funciona, mas seguro)
                    if "report_pendencies" not in loaded_data: loaded_data["report_pendencies"] = {}
                    if "report_download_status" not in loaded_data: loaded_data["report_download_status"] = {}
                    if "xml_skip_counts" not in loaded_data: loaded_data["xml_skip_counts"] = {}
                    if "processed_xml_keys" not in loaded_data: loaded_data["processed_xml_keys"] = {}
                    if "last_successful_run" not in loaded_data: loaded_data["last_successful_run"] = None

                    self.state = loaded_data
                    logger.info(f"Estado carregado de {self.state_file_path}")
                else:
                    logger.info("Arquivo de estado não encontrado. Usando estado inicial vazio.")
                    # Garante que as chaves principais existem mesmo com estado vazio inicial
                    # self.reset_state() # REMOVER ESTA CHAMADA ANINHADA
                    # INÍCIO: Lógica de reset_state movida para cá
                    self.state = {
                        "processed_xml_keys": {},
                        "xml_skip_counts": {},
                        "report_download_status": {},
                        "report_pendencies": {},
                        "last_successful_run": None,
                        "schema_version": 2
                    }
                    logger.info("Estado definido para o padrão inicial (dentro de load_state).")
                    # FIM: Lógica de reset_state movida para cá

            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Erro ao carregar/migrar o arquivo de estado {self.state_file_path}: {e}. Usando estado inicial.")
                # self.reset_state() # REMOVER ESTA CHAMADA TAMBÉM
                # INÍCIO: Lógica de reset_state movida para cá (para o catch exception)
                self.state = {
                    "processed_xml_keys": {},
                    "xml_skip_counts": {},
                    "report_download_status": {},
                    "report_pendencies": {},
                    "last_successful_run": None,
                    "schema_version": 2
                }
                logger.info("Estado definido para o padrão inicial devido a erro de carga (dentro de load_state).")
                # FIM: Lógica de reset_state movida para cá

    def save_state(self) -> None:
        """Salva o estado atual no arquivo JSON.

        O JSON é salvo com indentação para facilitar a leitura.
        Cria diretórios pais se não existirem.
        """
        with self._lock:
            try:
                # Atualizar timestamp do último sucesso, se aplicável (pode ser movido para lógica de ciclo)
                # self.state["last_successful_run"] = datetime.now().isoformat()
                self.state_file_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Criar um arquivo temporário primeiro para evitar corrupção
                temp_file = self.state_file_path.with_suffix('.tmp')
                
                # Tentar serializar primeiro para detectar erros antes de abrir o arquivo
                try:
                    state_json = json.dumps(self.state, indent=4, ensure_ascii=False, default=str)
                except (TypeError, ValueError) as e:
                    logger.error(f"Erro ao serializar estado para JSON: {e}. Tentando limpar dados problemáticos...")
                    # Tentar uma versão simplificada sem indentação
                    try:
                        state_json = json.dumps(self.state, ensure_ascii=False, default=str)
                    except Exception as e2:
                        logger.error(f"Falha crítica ao serializar estado mesmo com default=str: {e2}")
                        return
                
                # Salvar no arquivo temporário
                with open(temp_file, 'w', encoding='utf-8') as f:
                    f.write(state_json)
                    f.flush()
                    os.fsync(f.fileno())  # Forçar escrita no disco
                
                # Mover arquivo temporário para o definitivo (operação atômica)
                import shutil
                shutil.move(str(temp_file), str(self.state_file_path))
                
                # logger.debug(f"Estado salvo em {self.state_file_path}") # Muito verboso
            except IOError as e:
                logger.error(f"Erro de I/O ao salvar o arquivo de estado {self.state_file_path}: {e}")
                # Tentar remover arquivo temporário se existir
                try:
                    if temp_file.exists():
                        temp_file.unlink()
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Erro inesperado ao salvar estado: {e}")

    def reset_state(self) -> None:
        with self._lock:
            self.state = {
                "processed_xml_keys": {},
                "xml_skip_counts": {},
                "report_download_status": {},
                "report_pendencies": {}, # Inicializar a nova chave
                "last_successful_run": None,
                "schema_version": 2
            }
            logger.info("Estado resetado para o padrão inicial.")
            # Não salva imediatamente, deixa o fluxo principal decidir quando salvar

    def get_skip(self, cnpj_norm: str, month_str: str, report_type_str: str, papel: str) -> int:
        """Obtém o valor de 'skip' para uma combinação específica da nova estrutura."""
        skip_value = self.state.get("xml_skip_counts", {})\
                           .get(cnpj_norm, {})\
                           .get(month_str, {})\
                           .get(report_type_str, {})\
                           .get(papel, 0) # Retorna 0 se qualquer chave no caminho não existir

        if not isinstance(skip_value, int) or skip_value < 0:
             logger.warning(f"Valor de skip inválido ({skip_value}) encontrado para [{cnpj_norm}] {month_str}/{report_type_str}/{papel}. Usando 0.")
             return 0
        # logger.debug(f"Recuperado skip={skip_value} para [{cnpj_norm}] {month_str}/{report_type_str}/{papel}")
        return skip_value

    def update_skip(self, cnpj_norm: str, month_str: str, report_type_str: str, papel: str, count_downloaded_in_batch: int):
        """Atualiza o valor de 'skip' incrementando pelo número de itens baixados no lote."""
        if count_downloaded_in_batch < 0:
             logger.error(f"Tentativa de atualizar skip com contagem negativa ({count_downloaded_in_batch}) para [{cnpj_norm}] {month_str}/{report_type_str}/{papel}. Ignorando atualização.")
             return

        with self._lock: # Bloqueia para leitura e escrita segura
            # Garante que a estrutura de dicionário exista antes de tentar atualizar
            self._ensure_nested_dicts_exist(cnpj_norm, month_str, report_type_str, papel)

            current_skip = self.state["xml_skip_counts"][cnpj_norm][month_str][report_type_str].get(papel, 0)

            # Validação adicional do skip atual lido
            if not isinstance(current_skip, int) or current_skip < 0:
                logger.warning(f"Valor de skip atual inválido ({current_skip}) lido para [{cnpj_norm}] {month_str}/{report_type_str}/{papel} antes de atualizar. Resetando para 0.")
                current_skip = 0

            final_skip = current_skip + count_downloaded_in_batch

            self.state["xml_skip_counts"][cnpj_norm][month_str][report_type_str][papel] = final_skip
            logger.debug(f"Atualizado skip para {final_skip} (era {current_skip}, adicionado {count_downloaded_in_batch}) para [{cnpj_norm}] {month_str}/{report_type_str}/{papel}")
            # O save_state() geralmente é chamado no final do processamento da empresa ou do ciclo

    def reset_skip_for_report(self, cnpj_norm: str, month_str: str, report_type_str: str) -> None:
        """Reseta os contadores de skip para todos os papéis de um determinado relatório."""
        with self._lock:
            cnpj_data = self.state.get("xml_skip_counts", {}).get(cnpj_norm)
            if not cnpj_data:
                # logger.debug(f"Nenhum contador de skip para resetar para {cnpj_norm}/{month_str}/{report_type_str} (CNPJ não encontrado).")
                return

            month_data = cnpj_data.get(month_str)
            if not month_data:
                # logger.debug(f"Nenhum contador de skip para resetar para {cnpj_norm}/{month_str}/{report_type_str} (Mês não encontrado).")
                return

            # Usa pop com default None para remover com segurança
            removed_data = month_data.pop(report_type_str, None)

            if removed_data is not None:
                logger.info(f"Contadores de skip resetados para {cnpj_norm}/{month_str}/{report_type_str} após sucesso no relatório pendente.")

                # Limpeza de dicionários vazios após a remoção segura
                if not month_data: # Se o mês ficou vazio
                    cnpj_data.pop(month_str, None)
                if not cnpj_data: # Se o CNPJ ficou vazio
                    self.state.get("xml_skip_counts", {}).pop(cnpj_norm, None)

                self.save_state() # Salva apenas se algo foi removido
            # else:
                # logger.debug(f"Nenhum contador de skip para resetar para {cnpj_norm}/{month_str}/{report_type_str} (Tipo de relatório não encontrado).")

    def get_last_seed_run_time(self) -> Optional[str]:
         """Retorna o timestamp ISO da última execução com seed, se houver."""
         return self.state.get("_metadata", {}).get("last_seed_run_iso")

    def update_last_seed_run_time(self):
        """Atualiza o timestamp da última execução com seed para o momento atual."""
        now_iso = datetime.now().isoformat()
        if "_metadata" not in self.state:
            self.state["_metadata"] = {}
        self.state["_metadata"]["last_seed_run_iso"] = now_iso
        logger.info(f"Timestamp da última execução com seed atualizado para: {now_iso}")

    # --- Gerenciamento de Pendências de Relatório ---
    def add_or_update_report_pendency(self, cnpj_norm: str, month_str: str, report_type_str: str, failure_status: str) -> None:
        """Adiciona ou atualiza pendência.
        failure_status: STATUS_PENDING_API ou STATUS_PENDING_PROC
        """
        if failure_status not in [STATUS_PENDING_API, STATUS_PENDING_PROC]:
            logger.error(f"Status de falha inválido '{failure_status}' para pendência {cnpj_norm}/{month_str}/{report_type_str}. Ignorando.")
            return

        with self._lock:
            self._ensure_nested_dicts_exist(cnpj_norm, month_str)
            pendencies_month = self.state["report_pendencies"].setdefault(cnpj_norm, {}).setdefault(month_str, {})
            pendency = pendencies_month.get(report_type_str)

            if not pendency:
                pendency = {"attempts": 0, "status": failure_status, "first_failure_timestamp": datetime.now().isoformat()}

            pendency["attempts"] += 1
            pendency["last_attempt_timestamp"] = datetime.now().isoformat()

            # Só atualiza status se não for um estado final
            if pendency.get("status") not in [STATUS_NO_DATA, STATUS_MAX_RETRY]:
                 pendency["status"] = failure_status

            if pendency["attempts"] >= MAX_PENDENCY_ATTEMPTS and pendency["status"] != STATUS_NO_DATA:
                pendency["status"] = STATUS_MAX_RETRY
                logger.warning(f"Pendência {cnpj_norm}/{month_str}/{report_type_str} atingiu {MAX_PENDENCY_ATTEMPTS} tentativas. Status: {STATUS_MAX_RETRY}.")

            pendencies_month[report_type_str] = pendency
            logger.info(f"Pendência adicionada/atualizada para {cnpj_norm}/{month_str}/{report_type_str}: Tentativas={pendency['attempts']}, Status={pendency['status']}")
            self.save_state()

    def resolve_report_pendency(self, cnpj_norm: str, month_str: str, report_type_str: str) -> None:
        """Remove pendência resolvida."""
        with self._lock:
            cnpj_pendencies = self.state.get("report_pendencies", {}).get(cnpj_norm)
            if not cnpj_pendencies: return
            month_pendencies = cnpj_pendencies.get(month_str)
            if not month_pendencies: return

            # Usa pop com default None para remover com segurança
            if month_pendencies.pop(report_type_str, None) is not None:
                logger.info(f"Pendência resolvida e removida para {cnpj_norm}/{month_str}/{report_type_str}.")
                if not month_pendencies: # Mês ficou vazio
                    cnpj_pendencies.pop(month_str, None)
                if not cnpj_pendencies: # CNPJ ficou vazio
                    self.state.get("report_pendencies", {}).pop(cnpj_norm, None)
                self.save_state()
            # else:
            #    logger.debug(f"Tentativa de resolver pendência inexistente para {cnpj_norm}/{month_str}/{report_type_str}.")

    def update_report_pendency_status(self, cnpj_norm: str, month_str: str, report_type_str: str, new_status: str) -> None:
        """Atualiza status de pendência (ex: STATUS_NO_DATA, STATUS_MAX_RETRY)."""
        if new_status not in [STATUS_NO_DATA, STATUS_MAX_RETRY]: # Adicione outros status finais se necessário
             logger.error(f"Tentativa de usar update_report_pendency_status com status não final '{new_status}' para {cnpj_norm}/{month_str}/{report_type_str}. Use add_or_update.")
             return

        with self._lock:
            pendencies_month = self.state.get("report_pendencies", {}).get(cnpj_norm, {}).get(month_str, {})
            pendency = pendencies_month.get(report_type_str)
            if pendency:
                old_status = pendency.get("status")
                if old_status != new_status:
                    pendency["status"] = new_status
                    pendency["last_update_timestamp"] = datetime.now().isoformat()
                    logger.info(f"Status da pendência para {cnpj_norm}/{month_str}/{report_type_str} atualizado de '{old_status}' para '{new_status}'.")
                    self.save_state()
            else:
                # Cria entrada informativa se status for STATUS_NO_DATA
                if new_status == STATUS_NO_DATA:
                    self._ensure_nested_dicts_exist(cnpj_norm, month_str)
                    self.state["report_pendencies"].setdefault(cnpj_norm, {}).setdefault(month_str, {})[report_type_str] = {
                        "attempts": 0,
                        "status": STATUS_NO_DATA,
                        "first_failure_timestamp": datetime.now().isoformat(),
                        "last_attempt_timestamp": datetime.now().isoformat(),
                        "last_update_timestamp": datetime.now().isoformat()
                    }
                    logger.info(f"Status '{STATUS_NO_DATA}' registrado para {cnpj_norm}/{month_str}/{report_type_str} (não era pendência).")
                    self.save_state()
                else:
                    logger.warning(f"Tentativa de atualizar status para '{new_status}' em pendência inexistente {cnpj_norm}/{month_str}/{report_type_str}.")

    def get_pending_reports(self) -> List[Tuple[str, str, str, int, str]]:
        """Retorna lista de pendências ativas (STATUS_PENDING_*) abaixo do limite de tentativas."""
        with self._lock:
            pending_list = []
            all_pendencies = self.state.get("report_pendencies", {})
            active_statuses = [STATUS_PENDING_API, STATUS_PENDING_PROC]

            for cnpj_norm, months in all_pendencies.items():
                for month_str, report_types in months.items():
                    for report_type_str, details in report_types.items():
                        status = details.get("status")
                        attempts = details.get("attempts", 0)

                        if status in active_statuses and attempts < MAX_PENDENCY_ATTEMPTS:
                            pending_list.append((cnpj_norm, month_str, report_type_str, attempts, status))
                        elif status in active_statuses and attempts >= MAX_PENDENCY_ATTEMPTS:
                            # Apenas loga se encontrar uma pendência ativa que já deveria estar como max_attempts
                            logger.warning(f"Pendência {cnpj_norm}/{month_str}/{report_type_str} com status {status} e {attempts} tentativas (>= limite {MAX_PENDENCY_ATTEMPTS}) encontrada, mas será ignorada.")
                            # Poderia atualizar para STATUS_MAX_RETRY aqui se desejado.

            # Ordenação: prioriza STATUS_PENDING_PROC, depois por menor número de tentativas.
            pending_list.sort(key=lambda x: (x[4] == STATUS_PENDING_API, x[3]))

            logger.info(f"Encontradas {len(pending_list)} pendências de relatório ativas para repriorização.")
            return pending_list

    def get_report_pendency_details(self, cnpj_norm: str, month_str: str, report_type_str: str) -> Optional[Dict[str, Any]]:
        """Retorna os detalhes de uma pendência específica ou None se não existir."""
        with self._lock:
            return self.state.get("report_pendencies", {}).get(cnpj_norm, {}).get(month_str, {}).get(report_type_str)

    # --- Gerenciamento do status de download de relatório (informativo) ---
    def update_report_download_status(self, cnpj_norm: str, month_str: str, report_type_str: str, status: str, message: Optional[str] = None, file_path: Optional[str] = None) -> None:
        """Atualiza o status do download de um relatório específico.

        Args:
            cnpj_norm: CNPJ normalizado da empresa.
            month_str: Mês/ano no formato "YYYY-MM".
            report_type_str: Tipo de relatório ("NFe" ou "CTe").
            status: O novo status do download (ex: "success", "failed_api").
            message: Uma mensagem opcional associada ao status (ex: mensagem de erro).
            file_path: O caminho opcional para o arquivo de relatório, se aplicável.
        """
        with self._lock:
            self._ensure_nested_dicts_exist(cnpj_norm, month_str)

            status_entry: Dict[str, Any] = { # Definindo o tipo para melhor clareza
                "status": status,
                "timestamp": datetime.now().isoformat()
            }
            if message:
                status_entry["message"] = message
            if file_path:
                status_entry["file_path"] = file_path

            status_data = self.state.setdefault("report_download_status", {}).setdefault(cnpj_norm, {}).setdefault(month_str, {})
            status_data[report_type_str] = status_entry
            logger.debug(f"Status do download do relatório para [{cnpj_norm}] {month_str}/{report_type_str} atualizado para: {status_entry}")
            # self.save_state() # Geralmente chamado no final do ciclo

    def get_report_download_status(self, cnpj_norm: str, month_str: str, report_type_str: str) -> Optional[Dict[str, Any]]:
        """Retorna o último status informativo registrado para o download de um relatório ou None."""
        with self._lock:
            return self.state.get("report_download_status", {}).get(cnpj_norm, {}).get(month_str, {}).get(report_type_str, {}).get("status")
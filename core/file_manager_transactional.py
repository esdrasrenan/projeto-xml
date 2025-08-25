"""
Versão transacional do file_manager que garante atomicidade entre múltiplos diretórios.
"""

import base64
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import date, timedelta, datetime

from .transaction_manager import TransactionManager
from .file_manager import (
    _parse_xml_content, _get_xml_info, normalize_cnpj,
    PRIMARY_SAVE_BASE_PATH, FLAT_COPY_PATH, CANCELLED_COPY_BASE_PATH,
    CANCEL_EVENT_TYPES, EVENT_SUFFIX, XML_EXTENSION
)

logger = logging.getLogger(__name__)

# Versão com controle de duplicação corrigido - 18/08/2025

class TransactionalFileManager:
    """
    Gerenciador de arquivos com suporte a transações para garantir atomicidade
    entre múltiplos diretórios de destino.
    """
    
    def __init__(self, transaction_dir: Path = None):
        """
        Inicializa o gerenciador transacional.
        
        Args:
            transaction_dir: Diretório para armazenar controles de transação
        """
        if transaction_dir is None:
            transaction_dir = Path("transactions")
        
        self.transaction_manager = TransactionManager(transaction_dir)
        
        # Recupera transações pendentes na inicialização
        recovered = self.transaction_manager.recover_pending_transactions()
        if recovered:
            logger.info(f"Recuperadas {len(recovered)} transações pendentes na inicialização")

    def save_xmls_from_base64_transactional(
        self,
        base64_list: List[str],
        empresa_cnpj: str,
        empresa_nome_pasta: str,
        is_event: bool = False,
        state_manager=None
    ) -> Dict[str, int]:
        """
        Versão transacional de save_xmls_from_base64 que garante atomicidade
        entre todos os diretórios de destino.
        
        Args:
            base64_list: Lista de XMLs em Base64
            empresa_cnpj: CNPJ da empresa
            empresa_nome_pasta: Nome da pasta da empresa
            is_event: Se está processando eventos
            
        Returns:
            Dicionário com estatísticas de salvamento
        """
        if not base64_list:
            logger.warning("Lista de XMLs Base64 vazia fornecida")
            return {"saved": 0, "parse_errors": 0, "info_errors": 0, "save_errors": 0, 
                   "skipped_events": 0, "saved_mes_anterior": 0, "flat_copy_success": 0, 
                   "flat_copy_errors": 0, "transaction_errors": 0}

        # Cria uma transação para todo o lote
        transaction_id = self.transaction_manager.create_transaction(
            f"batch_{empresa_cnpj}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        
        logger.info(f"Iniciando salvamento transacional de {len(base64_list)} itens para {empresa_nome_pasta} "
                   f"(Eventos: {is_event}). Transação: {transaction_id}")

        # Contadores
        saved_count = 0
        parse_error_count = 0
        info_error_count = 0
        save_error_count = 0
        skipped_non_cancel_event = 0
        saved_mes_anterior_count = 0
        flat_copy_success_count = 0
        flat_copy_error_count = 0
        transaction_error_count = 0
        
        # Contadores para logs consolidados de duplicação
        already_imported_count = 0
        total_flat_eligible = 0

        base_path = PRIMARY_SAVE_BASE_PATH
        today = date.today()

        try:
            empresa_cnpj_norm = normalize_cnpj(empresa_cnpj)
        except ValueError:
            logger.error(f"CNPJ inválido fornecido para a empresa: {empresa_cnpj}. Abortando salvamento.")
            self.transaction_manager.rollback_transaction(transaction_id)
            return {"saved": 0, "parse_errors": 0, "info_errors": len(base64_list), "save_errors": 0, 
                   "skipped_events": 0, "saved_mes_anterior": 0, "flat_copy_success": 0, 
                   "flat_copy_errors": 0, "transaction_errors": 1}

        # Processa cada XML e adiciona à transação
        for b64_content in base64_list:
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
                    logger.error(f"Informações essenciais faltando no XML. Info: {xml_info}. Pulando salvamento.")
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

                # Determina caminhos de destino
                target_paths = []
                filename = None
                flat_path = None  # Inicializa flat_path
                copy_to_mes_anterior = False
                copy_cancelled_pair = False
                original_xml_path_for_copy = None

                if tipo in ["NFe", "CTe"]:
                    direcao = xml_info.get("direcao")
                    tipo_doc_base = tipo
                    sub_dir_final = None

                    if not direcao:
                        logger.warning(f"Direção não determinada para {tipo} {chave}. Salvando em {tipo_doc_base}/.")
                        primary_path = base_path / str(ano_emi) / empresa_nome_pasta / f"{mes_emi:02d}" / tipo_doc_base
                        filename = f"{chave}{XML_EXTENSION}"
                    else:
                        sub_dir_final = "Entrada" if direcao == "Entrada" else "Saída"
                        primary_path = base_path / str(ano_emi) / empresa_nome_pasta / f"{mes_emi:02d}" / tipo_doc_base / sub_dir_final
                        filename = f"{chave}{XML_EXTENSION}"

                        # Verifica regra do mês anterior
                        if (direcao == "Entrada" and
                            data_emissao.year == today.year and
                            data_emissao.month == today.month and
                            1 <= data_emissao.day <= 3):
                            copy_to_mes_anterior = True

                    # Adiciona caminho primário
                    target_paths.append(primary_path / filename)

                    # Contabilizar XMLs elegíveis para flat copy
                    total_flat_eligible += 1

                    # Verificar se o XML já foi importado usando o state manager
                    month_key = f"{mes_emi:02d}-{ano_emi:04d}"  # Formato MM-YYYY para compatibilidade com state.json
                    
                    # Log de controle de duplicação
                    if state_manager is None:
                        logger.warning(f"state_manager é None para {empresa_cnpj_norm} - controle de duplicação desativado!")
                    else:
                        # Log apenas uma vez por lote
                        if saved_count == 0:
                            logger.info(f"Controle de duplicação ATIVO para {empresa_cnpj_norm} - verificando XMLs já importados")
                    
                    if state_manager and state_manager.is_xml_already_imported(empresa_cnpj_norm, month_key, tipo, chave):
                        already_imported_count += 1
                        # Log consolidado será feito no final da função
                    else:
                        # Adiciona cópia flat para NFe/CTe
                        flat_path = FLAT_COPY_PATH / filename
                        target_paths.append(flat_path)
                        
                        # Marcar XML como importado no state após adicionar à transação
                        if state_manager:
                            state_manager.mark_xml_as_imported(empresa_cnpj_norm, month_key, tipo, chave)

                    # Adiciona cópia para mês anterior se necessário
                    if copy_to_mes_anterior:
                        primeiro_dia_mes_atual = today.replace(day=1)
                        ultimo_dia_mes_anterior = primeiro_dia_mes_atual - timedelta(days=1)
                        ano_anterior = ultimo_dia_mes_anterior.year
                        mes_anterior = ultimo_dia_mes_anterior.month

                        dest_dir_mes_anterior = base_path / str(ano_anterior) / empresa_nome_pasta / f"{mes_anterior:02d}" / "Mês_anterior" / tipo_doc_base / sub_dir_final
                        target_paths.append(dest_dir_mes_anterior / filename)

                elif tipo in ["EventoNFe", "EventoCTe"]:
                    tp_evento = xml_info.get("tp_evento")
                    chave_doc_orig = xml_info.get("chave_doc_orig")

                    if not tp_evento or not chave_doc_orig:
                        logger.warning(f"Evento {chave} não contém tipo de evento ou chave original. Pulando.")
                        info_error_count += 1
                        continue

                    if tp_evento in CANCEL_EVENT_TYPES:
                        tipo_doc_base = "NFe" if tipo == "EventoNFe" else "CTe"
                        filename = f"{chave_doc_orig}{EVENT_SUFFIX}{XML_EXTENSION}"

                        # Busca o XML original para determinar onde salvar o evento
                        found_original_path = self._find_original_xml_path(
                            chave_doc_orig, tipo_doc_base, ano_emi, mes_emi, 
                            empresa_nome_pasta, base_path
                        )

                        if found_original_path:
                            target_paths.append(found_original_path / filename)
                            
                            # Adiciona cópia para diretório de cancelados (apenas o evento, direto na raiz)
                            target_paths.append(CANCELLED_COPY_BASE_PATH / filename)
                            copy_cancelled_pair = True
                        else:
                            logger.warning(f"XML original {chave_doc_orig} não encontrado. Evento {filename} NÃO será salvo.")
                            info_error_count += 1
                            continue
                    else:
                        logger.debug(f"Ignorando salvamento do evento tipo {tp_evento} (Chave Evento: {chave}, Chave Orig: {chave_doc_orig}).")
                        skipped_non_cancel_event += 1
                        continue
                else:
                    logger.warning(f"Tipo de documento não reconhecido: {tipo} (Chave: {chave}). Pulando.")
                    info_error_count += 1
                    continue

                # Adiciona operação à transação
                if target_paths and filename:
                    success = self.transaction_manager.add_file_operation(
                        transaction_id=transaction_id,
                        source_content=xml_content_bytes,
                        target_paths=target_paths,
                        filename=filename
                    )
                    
                    if success:
                        saved_count += 1
                        if copy_to_mes_anterior:
                            saved_mes_anterior_count += 1
                        # Só conta flat_copy_success se realmente copiou para flat (não estava já importado)
                        if tipo in ["NFe", "CTe"] and flat_path in target_paths:
                            flat_copy_success_count += 1
                    else:
                        transaction_error_count += 1
                        logger.error(f"Falha ao adicionar operação à transação para {filename}")

            except base64.binascii.Error as b64_err:
                logger.error(f"Erro ao decodificar Base64: {b64_err}. Pulando item.")
                parse_error_count += 1
            except Exception as outer_err:
                log_chave = xml_info.get('chave', 'Chave Desconhecida') if 'xml_info' in locals() else 'Info Desconhecida'
                logger.exception(f"Erro inesperado processando item (Chave: {log_chave}): {outer_err}. Pulando item.")
                info_error_count += 1

        # Executa a transação
        if saved_count > 0:
            logger.info(f"Executando transação {transaction_id} com {saved_count} operações")
            success, stats = self.transaction_manager.commit_transaction(transaction_id)
            
            if not success:
                logger.error(f"Falha ao executar transação {transaction_id}: {stats}")
                transaction_error_count += 1
                save_error_count = stats.get("failed_operations", 0)
            else:
                logger.info(f"Transação {transaction_id} executada com sucesso. "
                           f"Arquivos copiados: {stats.get('total_files_copied', 0)}")
        else:
            logger.warning(f"Nenhuma operação válida para executar. Revertendo transação {transaction_id}")
            self.transaction_manager.rollback_transaction(transaction_id)

        # Log consolidado de controle de duplicação
        if total_flat_eligible > 0:
            logger.info(f"[{empresa_cnpj_norm}] Controle duplicação RESULTADO: {already_imported_count}/{total_flat_eligible} XMLs já importados anteriormente, {flat_copy_success_count} novos copiados para Import")
            if already_imported_count > 0:
                logger.info(f"[{empresa_cnpj_norm}] Economia: {already_imported_count} re-cópias evitadas para pasta Import/BI")
        
        logger.info(f"Processo de salvamento transacional concluído. "
                   f"Salvos: {saved_count}, Erros Parse: {parse_error_count}, "
                   f"Erros Info: {info_error_count}, Erros Save: {save_error_count}, "
                   f"Eventos Ignorados: {skipped_non_cancel_event}, "
                   f"Erros Transação: {transaction_error_count}")

        return {
            "saved": saved_count,
            "parse_errors": parse_error_count,
            "info_errors": info_error_count,
            "save_errors": save_error_count,
            "skipped_events": skipped_non_cancel_event,
            "saved_mes_anterior": saved_mes_anterior_count,
            "flat_copy_success": flat_copy_success_count,
            "flat_copy_errors": flat_copy_error_count,
            "transaction_errors": transaction_error_count,
        }

    def _find_original_xml_path(
        self, 
        chave_doc_orig: str, 
        tipo_doc_base: str, 
        ano_emi: int, 
        mes_emi: int,
        empresa_nome_pasta: str, 
        base_path: Path
    ) -> Optional[Path]:
        """
        Busca o caminho do XML original para um evento de cancelamento.
        
        Args:
            chave_doc_orig: Chave do documento original
            tipo_doc_base: Tipo do documento (NFe ou CTe)
            ano_emi: Ano de emissão do evento
            mes_emi: Mês de emissão do evento
            empresa_nome_pasta: Nome da pasta da empresa
            base_path: Caminho base
            
        Returns:
            Path do diretório onde o XML original foi encontrado ou None
        """
        original_filename_to_find = f"{chave_doc_orig}{XML_EXTENSION}"
        
        # Extrai ano/mês do documento original da chave
        original_ano_yyyy = None
        original_mes_mm = None
        original_month_base_path = None
        
        if len(chave_doc_orig) == 44:
            try:
                ano_yy_str = chave_doc_orig[2:4]
                mes_mm_str = chave_doc_orig[4:6]
                ano_yy = int(ano_yy_str)
                mes_mm = int(mes_mm_str)
                
                if 1 <= mes_mm <= 12:
                    original_ano_yyyy = 2000 + ano_yy
                    original_mes_mm = mes_mm
                    original_month_base_path = base_path / str(original_ano_yyyy) / empresa_nome_pasta / f"{original_mes_mm:02d}"
            except (ValueError, IndexError):
                logger.warning(f"Não foi possível extrair ano/mês da chave original {chave_doc_orig}")

        # Lista de diretórios para buscar
        search_dirs = []
        
        # Prioriza diretórios do mês do documento original
        if original_month_base_path:
            search_dirs.extend([
                original_month_base_path / tipo_doc_base / "Entrada",
                original_month_base_path / tipo_doc_base / "Saída",
                original_month_base_path / tipo_doc_base
            ])

        # Adiciona diretórios do mês do evento
        event_month_base_path = base_path / str(ano_emi) / empresa_nome_pasta / f"{mes_emi:02d}"
        search_dirs.extend([
            event_month_base_path / tipo_doc_base / "Entrada",
            event_month_base_path / tipo_doc_base / "Saída",
            event_month_base_path / tipo_doc_base
        ])

        # Busca em diretórios de mês anterior
        if mes_emi > 1:
            mes_anterior = mes_emi - 1
            ano_anterior = ano_emi
        else:
            mes_anterior = 12
            ano_anterior = ano_emi - 1
            
        mes_anterior_path = base_path / str(ano_anterior) / empresa_nome_pasta / f"{mes_anterior:02d}" / "Mês_anterior" / tipo_doc_base / "Entrada"
        search_dirs.append(mes_anterior_path)

        # Remove duplicatas mantendo ordem
        seen = set()
        unique_search_dirs = []
        for path in search_dirs:
            if path not in seen:
                seen.add(path)
                unique_search_dirs.append(path)

        logger.debug(f"Buscando {original_filename_to_find} em: {unique_search_dirs}")

        for search_dir in unique_search_dirs:
            if not search_dir.is_dir():
                continue
            potential_original = search_dir / original_filename_to_find
            if potential_original.exists():
                logger.debug(f"Documento original encontrado em: {search_dir}")
                return search_dir

        logger.warning(f"XML original {original_filename_to_find} não encontrado em nenhum diretório pesquisado")
        return None

    def get_transaction_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do gerenciador de transações."""
        return self.transaction_manager.get_transaction_stats()

    def cleanup_old_transactions(self, days_old: int = 30) -> int:
        """Remove transações antigas."""
        return self.transaction_manager.cleanup_old_transactions(days_old)

    def recover_pending_transactions(self) -> List[str]:
        """Força recuperação de transações pendentes."""
        return self.transaction_manager.recover_pending_transactions() 
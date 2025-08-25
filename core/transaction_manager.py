"""
Módulo para gerenciamento de transações de salvamento de arquivos.
Garante atomicidade entre múltiplos diretórios de destino.
"""

import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import logging
import uuid
import os

logger = logging.getLogger(__name__)

class TransactionManager:
    """
    Gerencia transações de salvamento de arquivos para garantir atomicidade
    entre múltiplos diretórios de destino.
    """
    
    def __init__(self, transaction_dir: Path = None):
        """
        Inicializa o gerenciador de transações.
        
        Args:
            transaction_dir: Diretório para armazenar arquivos de controle de transação
        """
        if transaction_dir is None:
            transaction_dir = Path("transactions")
        
        self.transaction_dir = transaction_dir
        self.transaction_dir.mkdir(parents=True, exist_ok=True)
        
        # Diretório temporário para staging de arquivos
        self.staging_dir = self.transaction_dir / "staging"
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        
        # Diretório para transações pendentes
        self.pending_dir = self.transaction_dir / "pending"
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        
        # Diretório para transações completadas (para auditoria)
        self.completed_dir = self.transaction_dir / "completed"
        self.completed_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"TransactionManager inicializado. Diretório: {self.transaction_dir}")

    def create_transaction(self, transaction_id: str = None) -> str:
        """
        Cria uma nova transação.
        
        Args:
            transaction_id: ID personalizado da transação (opcional)
            
        Returns:
            ID da transação criada
        """
        if transaction_id is None:
            transaction_id = f"tx_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        
        transaction_file = self.pending_dir / f"{transaction_id}.json"
        
        transaction_data = {
            "id": transaction_id,
            "created_at": datetime.now().isoformat(),
            "status": "created",
            "operations": [],
            "staging_files": [],
            "completed_operations": []
        }
        
        with open(transaction_file, 'w', encoding='utf-8') as f:
            json.dump(transaction_data, f, indent=2, ensure_ascii=False)
        
        logger.debug(f"Transação criada: {transaction_id}")
        return transaction_id

    def add_file_operation(
        self, 
        transaction_id: str, 
        source_content: bytes,
        target_paths: List[Path],
        filename: str,
        operation_type: str = "copy"
    ) -> bool:
        """
        Adiciona uma operação de arquivo à transação.
        
        Args:
            transaction_id: ID da transação
            source_content: Conteúdo do arquivo em bytes
            target_paths: Lista de caminhos de destino
            filename: Nome do arquivo
            operation_type: Tipo de operação (copy, move, etc.)
            
        Returns:
            True se a operação foi adicionada com sucesso
        """
        transaction_file = self.pending_dir / f"{transaction_id}.json"
        
        if not transaction_file.exists():
            logger.error(f"Transação {transaction_id} não encontrada")
            return False
        
        try:
            # Salva o arquivo no staging
            staging_file = self.staging_dir / transaction_id / filename
            staging_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(staging_file, 'wb') as f:
                f.write(source_content)
            
            # Atualiza o arquivo de transação
            with open(transaction_file, 'r', encoding='utf-8') as f:
                transaction_data = json.load(f)
            
            operation = {
                "id": len(transaction_data["operations"]),
                "type": operation_type,
                "source_staging": str(staging_file),
                "target_paths": [str(path) for path in target_paths],
                "filename": filename,
                "added_at": datetime.now().isoformat()
            }
            
            transaction_data["operations"].append(operation)
            transaction_data["staging_files"].append(str(staging_file))
            
            with open(transaction_file, 'w', encoding='utf-8') as f:
                json.dump(transaction_data, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"Operação adicionada à transação {transaction_id}: {filename} -> {len(target_paths)} destinos")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao adicionar operação à transação {transaction_id}: {e}")
            return False

    def commit_transaction(self, transaction_id: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Executa todas as operações da transação.
        
        Args:
            transaction_id: ID da transação
            
        Returns:
            Tupla (sucesso, estatísticas)
        """
        transaction_file = self.pending_dir / f"{transaction_id}.json"
        
        if not transaction_file.exists():
            logger.error(f"Transação {transaction_id} não encontrada")
            return False, {"error": "Transaction not found"}
        
        try:
            with open(transaction_file, 'r', encoding='utf-8') as f:
                transaction_data = json.load(f)
            
            stats = {
                "total_operations": len(transaction_data["operations"]),
                "successful_operations": 0,
                "failed_operations": 0,
                "total_files_copied": 0,
                "failed_copies": [],
                "start_time": datetime.now().isoformat()
            }
            
            transaction_data["status"] = "committing"
            transaction_data["commit_started_at"] = stats["start_time"]
            
            # Salva o status de início do commit
            with open(transaction_file, 'w', encoding='utf-8') as f:
                json.dump(transaction_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Iniciando commit da transação {transaction_id} com {stats['total_operations']} operações")
            
            # Executa cada operação
            for operation in transaction_data["operations"]:
                operation_success = True
                operation_stats = {
                    "operation_id": operation["id"],
                    "filename": operation["filename"],
                    "successful_copies": 0,
                    "failed_copies": []
                }
                
                source_file = Path(operation["source_staging"])
                
                if not source_file.exists():
                    logger.error(f"Arquivo staging não encontrado: {source_file}")
                    operation_success = False
                    stats["failed_operations"] += 1
                    continue
                
                # Copia para todos os destinos
                for target_path_str in operation["target_paths"]:
                    target_path = Path(target_path_str)
                    
                    try:
                        # Cria diretório de destino se não existir
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        # Verifica se arquivo já existe
                        if target_path.exists():
                            logger.warning(f"Arquivo já existe, pulando: {target_path}")
                            operation_stats["successful_copies"] += 1
                            stats["total_files_copied"] += 1
                            continue
                        
                        # Copia o arquivo
                        shutil.copy2(source_file, target_path)
                        operation_stats["successful_copies"] += 1
                        stats["total_files_copied"] += 1
                        
                        logger.debug(f"Arquivo copiado: {source_file} -> {target_path}")
                        
                    except Exception as e:
                        logger.error(f"Erro ao copiar {source_file} -> {target_path}: {e}")
                        operation_stats["failed_copies"].append({
                            "target": str(target_path),
                            "error": str(e)
                        })
                        stats["failed_copies"].append({
                            "operation_id": operation["id"],
                            "filename": operation["filename"],
                            "target": str(target_path),
                            "error": str(e)
                        })
                        operation_success = False
                
                if operation_success and len(operation_stats["failed_copies"]) == 0:
                    stats["successful_operations"] += 1
                    transaction_data["completed_operations"].append(operation_stats)
                else:
                    stats["failed_operations"] += 1
                
                # Atualiza progresso no arquivo de transação
                transaction_data["progress"] = {
                    "completed": len(transaction_data["completed_operations"]),
                    "total": len(transaction_data["operations"]),
                    "last_update": datetime.now().isoformat()
                }
                
                with open(transaction_file, 'w', encoding='utf-8') as f:
                    json.dump(transaction_data, f, indent=2, ensure_ascii=False)
            
            # Finaliza a transação
            stats["end_time"] = datetime.now().isoformat()
            transaction_success = stats["failed_operations"] == 0
            
            transaction_data["status"] = "completed" if transaction_success else "failed"
            transaction_data["completed_at"] = stats["end_time"]
            transaction_data["stats"] = stats
            
            # Move para diretório de completadas
            completed_file = self.completed_dir / f"{transaction_id}.json"
            with open(completed_file, 'w', encoding='utf-8') as f:
                json.dump(transaction_data, f, indent=2, ensure_ascii=False)
            
            # Remove da pasta pending
            transaction_file.unlink()
            
            # Limpa arquivos de staging
            staging_tx_dir = self.staging_dir / transaction_id
            if staging_tx_dir.exists():
                shutil.rmtree(staging_tx_dir)
            
            if transaction_success:
                logger.info(f"Transação {transaction_id} completada com sucesso. "
                           f"Operações: {stats['successful_operations']}/{stats['total_operations']}, "
                           f"Arquivos copiados: {stats['total_files_copied']}")
            else:
                logger.error(f"Transação {transaction_id} falhou. "
                            f"Operações bem-sucedidas: {stats['successful_operations']}/{stats['total_operations']}, "
                            f"Falhas: {stats['failed_operations']}")
            
            return transaction_success, stats
            
        except Exception as e:
            logger.error(f"Erro crítico durante commit da transação {transaction_id}: {e}")
            return False, {"error": str(e)}

    def rollback_transaction(self, transaction_id: str) -> bool:
        """
        Desfaz uma transação (remove arquivos de staging).
        
        Args:
            transaction_id: ID da transação
            
        Returns:
            True se o rollback foi bem-sucedido
        """
        transaction_file = self.pending_dir / f"{transaction_id}.json"
        
        try:
            if transaction_file.exists():
                with open(transaction_file, 'r', encoding='utf-8') as f:
                    transaction_data = json.load(f)
                
                transaction_data["status"] = "rolled_back"
                transaction_data["rolled_back_at"] = datetime.now().isoformat()
                
                # Move para completadas como rollback
                completed_file = self.completed_dir / f"{transaction_id}_rollback.json"
                with open(completed_file, 'w', encoding='utf-8') as f:
                    json.dump(transaction_data, f, indent=2, ensure_ascii=False)
                
                transaction_file.unlink()
            
            # Limpa arquivos de staging
            staging_tx_dir = self.staging_dir / transaction_id
            if staging_tx_dir.exists():
                shutil.rmtree(staging_tx_dir)
            
            logger.info(f"Transação {transaction_id} revertida com sucesso")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao reverter transação {transaction_id}: {e}")
            return False

    def recover_pending_transactions(self) -> List[str]:
        """
        Recupera e tenta completar transações pendentes.
        
        Returns:
            Lista de IDs de transações recuperadas
        """
        recovered = []
        pending_files = list(self.pending_dir.glob("*.json"))
        
        if not pending_files:
            logger.info("Nenhuma transação pendente encontrada")
            return recovered
        
        logger.info(f"Encontradas {len(pending_files)} transações pendentes para recuperação")
        
        for transaction_file in pending_files:
            try:
                transaction_id = transaction_file.stem
                
                with open(transaction_file, 'r', encoding='utf-8') as f:
                    transaction_data = json.load(f)
                
                status = transaction_data.get("status", "unknown")
                created_at = transaction_data.get("created_at", "unknown")
                
                logger.info(f"Recuperando transação {transaction_id} (status: {status}, criada: {created_at})")
                
                if status in ["created", "committing"]:
                    # Tenta completar a transação
                    success, stats = self.commit_transaction(transaction_id)
                    if success:
                        logger.info(f"Transação {transaction_id} recuperada com sucesso")
                        recovered.append(transaction_id)
                    else:
                        logger.error(f"Falha ao recuperar transação {transaction_id}: {stats}")
                else:
                    logger.warning(f"Transação {transaction_id} em status inesperado: {status}")
                
            except Exception as e:
                logger.error(f"Erro ao processar transação pendente {transaction_file}: {e}")
        
        logger.info(f"Recuperação concluída. {len(recovered)} transações recuperadas com sucesso")
        return recovered

    def cleanup_old_transactions(self, days_old: int = 30) -> int:
        """
        Remove transações antigas do diretório de completadas.
        
        Args:
            days_old: Idade em dias para considerar uma transação como antiga
            
        Returns:
            Número de transações removidas
        """
        cutoff_time = time.time() - (days_old * 24 * 60 * 60)
        removed_count = 0
        
        for transaction_file in self.completed_dir.glob("*.json"):
            try:
                if transaction_file.stat().st_mtime < cutoff_time:
                    transaction_file.unlink()
                    removed_count += 1
                    logger.debug(f"Transação antiga removida: {transaction_file.name}")
            except Exception as e:
                logger.error(f"Erro ao remover transação antiga {transaction_file}: {e}")
        
        if removed_count > 0:
            logger.info(f"Limpeza concluída. {removed_count} transações antigas removidas")
        
        return removed_count

    def get_transaction_stats(self) -> Dict[str, Any]:
        """
        Retorna estatísticas sobre transações.
        
        Returns:
            Dicionário com estatísticas
        """
        pending_count = len(list(self.pending_dir.glob("*.json")))
        completed_count = len(list(self.completed_dir.glob("*.json")))
        
        return {
            "pending_transactions": pending_count,
            "completed_transactions": completed_count,
            "transaction_dir": str(self.transaction_dir),
            "staging_dir": str(self.staging_dir)
        } 
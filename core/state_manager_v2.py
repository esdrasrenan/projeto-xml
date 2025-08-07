#!/usr/bin/env python3
"""
StateManagerV2 - Gerenciador de estado modular por mês.
Versão simplificada com compatibilidade total com StateManager v1.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any, List, Tuple

logger = logging.getLogger(__name__)

# Constantes para compatibilidade
MAX_PENDENCY_ATTEMPTS = 10
STATUS_PENDING_API = "pending_api_response"
STATUS_PENDING_PROC = "pending_processing"
STATUS_NO_DATA = "no_data_confirmed"
STATUS_MAX_RETRY = "max_attempts_reached"

class StateManagerV2:
    """
    Gerenciador de estado modular por mês.
    
    Estrutura:
    estado/
    ├── MM-YYYY/
    │   └── state.json
    └── metadata.json
    """
    
    def __init__(self, base_state_dir: Path = Path("estado")):
        """
        Inicializa o StateManagerV2.
        
        Args:
            base_state_dir: Diretório base para estados
        """
        self.base_state_dir = Path(base_state_dir)
        self._state_cache = {}
        self.metadata = {}
        
        # Criar diretório se não existir
        self.base_state_dir.mkdir(exist_ok=True)
        self._load_or_create_metadata()
    
    def _load_or_create_metadata(self) -> None:
        """Carrega ou cria metadata do sistema."""
        metadata_file = self.base_state_dir / "metadata.json"
        
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    self.metadata = json.load(f)
            except Exception as e:
                logger.warning(f"Erro ao carregar metadata: {e}. Criando novo.")
                self.metadata = self._create_default_metadata()
        else:
            self.metadata = self._create_default_metadata()
        
        self._save_metadata()
    
    def _create_default_metadata(self) -> Dict[str, Any]:
        """Cria metadata padrão."""
        return {
            "version": "2.0",
            "created_at": datetime.now().isoformat(),
            "last_modified": datetime.now().isoformat(),
            "available_months": []
        }
    
    def _save_metadata(self) -> None:
        """Salva metadata."""
        metadata_file = self.base_state_dir / "metadata.json"
        self.metadata["last_modified"] = datetime.now().isoformat()
        
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, indent=2, ensure_ascii=False)
    
    def _get_month_key(self, date: datetime = None) -> str:
        """
        Obtém chave do mês no formato MM-YYYY.
        
        Args:
            date: Data específica (padrão: hoje)
            
        Returns:
            Chave do mês
        """
        if date is None:
            date = datetime.now()
        return f"{date.month:02d}-{date.year}"
    
    def _get_month_state_file(self, month_key: str) -> Path:
        """Obtém caminho do arquivo de estado de um mês."""
        return self.base_state_dir / month_key / "state.json"
    
    def _ensure_month_directory(self, month_key: str) -> Path:
        """Garante que o diretório do mês existe."""
        month_dir = self.base_state_dir / month_key
        month_dir.mkdir(exist_ok=True)
        return month_dir
    
    def _create_month_state(self, month_key: str) -> Dict[str, Any]:
        """Cria estrutura padrão para estado de um mês."""
        return {
            "month_key": month_key,
            "created_at": datetime.now().isoformat(),
            "last_modified": datetime.now().isoformat(),
            "schema_version": 2,
            "xml_skip_counts": {},
            "processed_xml_keys": {},
            "report_download_status": {},
            "report_pendencies": {},
            "failed_companies": {}
        }
    
    def _load_month_state(self, month_key: str) -> Dict[str, Any]:
        """
        Carrega estado de um mês específico.
        
        Args:
            month_key: Chave do mês (MM-YYYY)
            
        Returns:
            Estado do mês
        """
        # Verificar cache primeiro
        if month_key in self._state_cache:
            return self._state_cache[month_key]
        
        # Carregar do arquivo
        state_file = self._get_month_state_file(month_key)
        
        if state_file.exists():
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                self._state_cache[month_key] = state
                return state
            except Exception as e:
                logger.warning(f"Erro ao carregar estado {month_key}: {e}. Criando novo.")
        
        # Criar novo estado se não existir
        state = self._create_month_state(month_key)
        self._state_cache[month_key] = state
        
        # Garantir diretório e salvar
        self._ensure_month_directory(month_key)
        self._save_month_state(month_key)
        
        return state
    
    def _save_month_state(self, month_key: str) -> None:
        """
        Salva estado de um mês.
        
        Args:
            month_key: Chave do mês
        """
        if month_key not in self._state_cache:
            return
        
        state = self._state_cache[month_key]
        state["last_modified"] = datetime.now().isoformat()
        
        # Garantir diretório
        self._ensure_month_directory(month_key)
        
        # Salvar arquivo
        state_file = self._get_month_state_file(month_key)
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        
        # Atualizar metadata
        if month_key not in self.metadata["available_months"]:
            self.metadata["available_months"].append(month_key)
            self.metadata["available_months"].sort()
            self._save_metadata()
    
    def get_current_month_state(self) -> Dict[str, Any]:
        """Obtém estado do mês atual."""
        current_month = self._get_month_key()
        return self._load_month_state(current_month)
    
    def get_month_state(self, month_key: str) -> Dict[str, Any]:
        """Obtém estado de um mês específico."""
        return self._load_month_state(month_key)
    
    def save_current_month_state(self) -> None:
        """Salva estado do mês atual."""
        current_month = self._get_month_key()
        self._save_month_state(current_month)
    
    def save_month_state(self, month_key: str) -> None:
        """Salva estado de um mês específico."""
        self._save_month_state(month_key)
    
    def list_available_months(self) -> List[str]:
        """Lista meses disponíveis ordenados."""
        return sorted(self.metadata.get("available_months", []))
    
    def migrate_from_v1(self, old_state_file: Path) -> Dict[str, int]:
        """
        Migra estado v1 para v2.
        
        Args:
            old_state_file: Arquivo state.json v1
            
        Returns:
            Estatísticas da migração
        """
        logger.info(f"Iniciando migração de {old_state_file}")
        
        # Carregar estado v1
        with open(old_state_file, 'r', encoding='utf-8') as f:
            old_state = json.load(f)
        
        migration_stats = {
            "months_created": 0,
            "companies_migrated": 0,
            "skip_counts_migrated": 0,
            "pendencies_migrated": 0
        }
        
        # Identificar meses únicos nos skip_counts
        skip_counts = old_state.get("xml_skip_counts", {})
        months_found = set()
        
        for cnpj, cnpj_data in skip_counts.items():
            for month_key in cnpj_data.keys():
                months_found.add(month_key)
        
        # Migrar cada mês
        for month_key in months_found:
            # Converter formato se necessário (YYYY-MM -> MM-YYYY)
            if "-" in month_key and len(month_key) == 7:
                year, month = month_key.split('-')
                v2_month_key = f"{int(month):02d}-{year}"
            else:
                v2_month_key = month_key
            
            # Criar estado para este mês
            new_state = self._create_month_state(v2_month_key)
            
            # Migrar skip_counts para este mês
            for cnpj, cnpj_data in skip_counts.items():
                if month_key in cnpj_data:
                    month_data = cnpj_data[month_key]
                    if month_data:
                        if cnpj not in new_state["xml_skip_counts"]:
                            new_state["xml_skip_counts"][cnpj] = {}
                        new_state["xml_skip_counts"][cnpj][v2_month_key] = month_data
                        migration_stats["skip_counts_migrated"] += len(month_data)
            
            # Migrar pendências para este mês
            pendencies = old_state.get("report_pendencies", {})
            for cnpj, cnpj_pendencies in pendencies.items():
                if month_key in cnpj_pendencies:
                    if cnpj not in new_state["report_pendencies"]:
                        new_state["report_pendencies"][cnpj] = {}
                    new_state["report_pendencies"][cnpj][v2_month_key] = cnpj_pendencies[month_key]
                    migration_stats["pendencies_migrated"] += 1
            
            # Salvar estado do mês
            self._state_cache[v2_month_key] = new_state
            self._save_month_state(v2_month_key)
            migration_stats["months_created"] += 1
            
            logger.info(f"Mês {v2_month_key} migrado com sucesso")
        
        # Contar empresas únicas
        companies = set()
        for cnpj_data in skip_counts.values():
            companies.add(cnpj)
        migration_stats["companies_migrated"] = len(companies)
        
        # Atualizar metadata
        self.metadata["last_migration"] = {
            "timestamp": datetime.now().isoformat(),
            "source_file": str(old_state_file),
            "stats": migration_stats
        }
        self._save_metadata()
        
        logger.info(f"Migração concluída: {migration_stats}")
        return migration_stats
    
    # === Métodos de compatibilidade com StateManager v1 ===
    
    def get_skip_count(self, cnpj_norm: str, month_str: str, report_type_str: str, papel: str) -> int:
        """Obtém skip count para compatibilidade v1."""
        # Converter formato se necessário (YYYY-MM -> MM-YYYY)
        if "-" in month_str and len(month_str) == 7:
            year, month = month_str.split('-')
            month_key = f"{int(month):02d}-{year}"
        else:
            month_key = month_str
        
        state = self._load_month_state(month_key)
        skip_counts = state.get("xml_skip_counts", {})
        
        return skip_counts.get(cnpj_norm, {}).get(month_key, {}).get(report_type_str, {}).get(papel, 0)
    
    def set_skip_count(self, cnpj_norm: str, month_str: str, report_type_str: str, papel: str, count: int) -> None:
        """Define skip count para compatibilidade v1."""
        # Converter formato se necessário
        if "-" in month_str and len(month_str) == 7:
            year, month = month_str.split('-')
            month_key = f"{int(month):02d}-{year}"
        else:
            month_key = month_str
        
        state = self._load_month_state(month_key)
        
        # Garantir estrutura
        if cnpj_norm not in state["xml_skip_counts"]:
            state["xml_skip_counts"][cnpj_norm] = {}
        if month_key not in state["xml_skip_counts"][cnpj_norm]:
            state["xml_skip_counts"][cnpj_norm][month_key] = {}
        if report_type_str not in state["xml_skip_counts"][cnpj_norm][month_key]:
            state["xml_skip_counts"][cnpj_norm][month_key][report_type_str] = {}
        
        state["xml_skip_counts"][cnpj_norm][month_key][report_type_str][papel] = count
        self._save_month_state(month_key)
    
    def save_state(self) -> None:
        """Salva estado atual para compatibilidade v1."""
        self.save_current_month_state()
    
    # Aliases para compatibilidade total
    def get_skip(self, cnpj_norm: str, month_str: str, report_type_str: str, papel: str) -> int:
        """Alias para get_skip_count."""
        return self.get_skip_count(cnpj_norm, month_str, report_type_str, papel)
    
    def update_skip(self, cnpj_norm: str, month_str: str, report_type_str: str, papel: str, count: int) -> None:
        """Alias para set_skip_count."""
        self.set_skip_count(cnpj_norm, month_str, report_type_str, papel, count)
    
    def reset_skip_for_report(self, cnpj_norm: str, month_str: str, report_type_str: str) -> None:
        """Reseta skip counts para um relatório."""
        if "-" in month_str and len(month_str) == 7:
            year, month = month_str.split('-')
            month_key = f"{int(month):02d}-{year}"
        else:
            month_key = month_str
        
        state = self._load_month_state(month_key)
        
        if (cnpj_norm in state["xml_skip_counts"] and 
            month_key in state["xml_skip_counts"][cnpj_norm] and
            report_type_str in state["xml_skip_counts"][cnpj_norm][month_key]):
            
            for papel in state["xml_skip_counts"][cnpj_norm][month_key][report_type_str]:
                state["xml_skip_counts"][cnpj_norm][month_key][report_type_str][papel] = 0
        
        self._save_month_state(month_key)
    
    def reset_state(self) -> None:
        """Reseta estado atual."""
        current_month = self._get_month_key()
        if current_month in self._state_cache:
            del self._state_cache[current_month]
        self._state_cache[current_month] = self._create_month_state(current_month)
        self._save_month_state(current_month)
    
    def load_state(self) -> None:
        """Carrega estado atual."""
        current_month = self._get_month_key()
        self._load_month_state(current_month)
    
    def get_pending_reports(self) -> List[Tuple[str, str, str]]:
        """Obtém relatórios pendentes."""
        pending_reports = []
        
        for month_key in self.list_available_months():
            state = self._load_month_state(month_key)
            pendencies = state.get("report_pendencies", {})
            
            for cnpj, cnpj_pend in pendencies.items():
                for month_str, month_pend in cnpj_pend.items():
                    for report_type, pend_data in month_pend.items():
                        if pend_data.get("status") in [STATUS_PENDING_API, STATUS_PENDING_PROC]:
                            # Converter formato de volta (MM-YYYY -> YYYY-MM)
                            if "-" in month_str and len(month_str) == 7:
                                month, year = month_str.split('-')
                                month_v1_format = f"{year}-{int(month):02d}"
                            else:
                                month_v1_format = month_str
                            pending_reports.append((cnpj, month_v1_format, report_type))
        
        return pending_reports
    
    def get_report_pendency_details(self, cnpj_norm: str, month_str: str, report_type_str: str) -> Optional[Dict[str, Any]]:
        """Obtém detalhes de pendência."""
        if "-" in month_str and len(month_str) == 7:
            year, month = month_str.split('-')
            month_key = f"{int(month):02d}-{year}"
        else:
            month_key = month_str
        
        state = self._load_month_state(month_key)
        pendencies = state.get("report_pendencies", {})
        return pendencies.get(cnpj_norm, {}).get(month_key, {}).get(report_type_str)
    
    def resolve_report_pendency(self, cnpj_norm: str, month_str: str, report_type_str: str) -> None:
        """Resolve pendência."""
        if "-" in month_str and len(month_str) == 7:
            year, month = month_str.split('-')
            month_key = f"{int(month):02d}-{year}"
        else:
            month_key = month_str
        
        state = self._load_month_state(month_key)
        
        if (cnpj_norm in state["report_pendencies"] and 
            month_key in state["report_pendencies"][cnpj_norm] and
            report_type_str in state["report_pendencies"][cnpj_norm][month_key]):
            
            del state["report_pendencies"][cnpj_norm][month_key][report_type_str]
            
            # Limpar estruturas vazias
            if not state["report_pendencies"][cnpj_norm][month_key]:
                del state["report_pendencies"][cnpj_norm][month_key]
            if not state["report_pendencies"][cnpj_norm]:
                del state["report_pendencies"][cnpj_norm]
        
        self._save_month_state(month_key)
    
    def add_or_update_report_pendency(self, cnpj_norm: str, month_str: str, report_type_str: str, status: str) -> None:
        """Adiciona/atualiza pendência."""
        if "-" in month_str and len(month_str) == 7:
            year, month = month_str.split('-')
            month_key = f"{int(month):02d}-{year}"
        else:
            month_key = month_str
        
        state = self._load_month_state(month_key)
        
        # Garantir estrutura
        if cnpj_norm not in state["report_pendencies"]:
            state["report_pendencies"][cnpj_norm] = {}
        if month_key not in state["report_pendencies"][cnpj_norm]:
            state["report_pendencies"][cnpj_norm][month_key] = {}
        
        if report_type_str not in state["report_pendencies"][cnpj_norm][month_key]:
            state["report_pendencies"][cnpj_norm][month_key][report_type_str] = {
                "status": status,
                "attempts": 1,
                "last_attempt": datetime.now().isoformat()
            }
        else:
            pend_data = state["report_pendencies"][cnpj_norm][month_key][report_type_str]
            pend_data["status"] = status
            pend_data["attempts"] = pend_data.get("attempts", 0) + 1
            pend_data["last_attempt"] = datetime.now().isoformat()
        
        self._save_month_state(month_key)
    
    def update_report_download_status(self, cnpj_norm: str, month_str: str, report_type_str: str, 
                                    status: str, message: str = None, file_path: str = None) -> None:
        """Atualiza status de download."""
        if "-" in month_str and len(month_str) == 7:
            year, month = month_str.split('-')
            month_key = f"{int(month):02d}-{year}"
        else:
            month_key = month_str
        
        state = self._load_month_state(month_key)
        
        # Garantir estrutura
        if cnpj_norm not in state["report_download_status"]:
            state["report_download_status"][cnpj_norm] = {}
        if month_key not in state["report_download_status"][cnpj_norm]:
            state["report_download_status"][cnpj_norm][month_key] = {}
        
        status_data = {
            "status": status,
            "timestamp": datetime.now().isoformat()
        }
        if message:
            status_data["message"] = message
        if file_path:
            status_data["file_path"] = file_path
        
        state["report_download_status"][cnpj_norm][month_key][report_type_str] = status_data
        self._save_month_state(month_key)
    
    def update_report_pendency_status(self, cnpj_norm: str, month_str: str, report_type_str: str, status: str) -> None:
        """Atualiza status de pendência."""
        if "-" in month_str and len(month_str) == 7:
            year, month = month_str.split('-')
            month_key = f"{int(month):02d}-{year}"
        else:
            month_key = month_str
        
        state = self._load_month_state(month_key)
        
        if (cnpj_norm in state["report_pendencies"] and 
            month_key in state["report_pendencies"][cnpj_norm] and
            report_type_str in state["report_pendencies"][cnpj_norm][month_key]):
            
            state["report_pendencies"][cnpj_norm][month_key][report_type_str]["status"] = status
            state["report_pendencies"][cnpj_norm][month_key][report_type_str]["last_attempt"] = datetime.now().isoformat()
            self._save_month_state(month_key)
    
    def mark_empresa_as_failed(self, cnpj_norm: str) -> None:
        """Marca empresa como falha."""
        current_month = self._get_month_key()
        state = self._load_month_state(current_month)
        
        if "failed_companies" not in state:
            state["failed_companies"] = {}
        
        state["failed_companies"][cnpj_norm] = {
            "timestamp": datetime.now().isoformat(),
            "month": current_month
        }
        
        self._save_month_state(current_month)
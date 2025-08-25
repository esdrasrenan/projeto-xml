#!/usr/bin/env python3
"""
DailyStateManager - Extensão do StateManagerV2 com granularidade diária.

Esta versão estende o StateManagerV2 para rastrear XMLs por data de emissão,
permitindo:
- Identificação precisa de gaps temporais
- Recuperação inteligente de XMLs "perdidos"
- Análise detalhada por período
- Relatórios de cobertura temporal
"""

import json
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, Optional, Any, List, Tuple, Set
from collections import defaultdict

from .state_manager_v2 import StateManagerV2

logger = logging.getLogger(__name__)

class DailyStateManager(StateManagerV2):
    """
    StateManager com granularidade diária.
    
    Estende StateManagerV2 para rastrear XMLs por data de emissão,
    mantendo compatibilidade total com a versão anterior.
    """
    
    def __init__(self, base_state_dir: Path = Path("estado")):
        """Inicializa o DailyStateManager."""
        super().__init__(base_state_dir)
        
        # Estrutura adicional para dados diários
        self._daily_default_state = {
            "daily_xml_tracking": {},  # cnpj -> month -> day -> doc_type -> papel -> [xml_keys]
            "daily_processing_log": {},  # cnpj -> month -> day -> {timestamp, status, counts}
            "gap_analysis_cache": {},   # Cache de análises de gaps
            "last_gap_analysis": None
        }
        
        logger.info("DailyStateManager inicializado com rastreamento diário")
    
    def _create_month_state(self, month_key: str) -> Dict[str, Any]:
        """Cria estado padrão com estruturas diárias."""
        state = super()._create_month_state(month_key)
        
        # Adicionar estruturas diárias
        for key, value in self._daily_default_state.items():
            state[key] = value.copy() if isinstance(value, dict) else value
        
        return state
    
    def track_xml_by_date(self, cnpj: str, month_key: str, emission_date: date, 
                         doc_type: str, papel: str, xml_key: str) -> None:
        """
        Rastreia um XML específico por data de emissão.
        
        Args:
            cnpj: CNPJ da empresa
            month_key: Chave do mês (MM-YYYY)
            emission_date: Data de emissão do XML
            doc_type: Tipo do documento (NFe, CTe)
            papel: Papel da empresa (Emitente, Destinatario, etc.)
            xml_key: Chave única do XML
        """
        state = self._load_month_state(month_key)
        
        # Garantir estrutura
        if "daily_xml_tracking" not in state:
            state["daily_xml_tracking"] = {}
        
        daily_tracking = state["daily_xml_tracking"]
        
        if cnpj not in daily_tracking:
            daily_tracking[cnpj] = {}
        if month_key not in daily_tracking[cnpj]:
            daily_tracking[cnpj][month_key] = {}
        
        day_key = emission_date.strftime("%d")
        if day_key not in daily_tracking[cnpj][month_key]:
            daily_tracking[cnpj][month_key][day_key] = {}
        if doc_type not in daily_tracking[cnpj][month_key][day_key]:
            daily_tracking[cnpj][month_key][day_key][doc_type] = {}
        if papel not in daily_tracking[cnpj][month_key][day_key][doc_type]:
            daily_tracking[cnpj][month_key][day_key][doc_type][papel] = []
        
        # Adicionar XML se não existe
        if xml_key not in daily_tracking[cnpj][month_key][day_key][doc_type][papel]:
            daily_tracking[cnpj][month_key][day_key][doc_type][papel].append(xml_key)
            
            # Log da operação
            logger.debug(f"XML rastreado: {cnpj} | {emission_date} | {doc_type}/{papel} | {xml_key}")
    
    def get_xmls_by_date_range(self, cnpj: str, month_key: str, start_date: date, 
                              end_date: date, doc_type: str = None, papel: str = None) -> Dict[str, List[str]]:
        """
        Recupera XMLs por intervalo de datas.
        
        Args:
            cnpj: CNPJ da empresa
            month_key: Chave do mês
            start_date: Data de início
            end_date: Data de fim
            doc_type: Tipo do documento (opcional)
            papel: Papel da empresa (opcional)
            
        Returns:
            Dicionário {data: [xml_keys]} dos XMLs encontrados
        """
        state = self._load_month_state(month_key)
        daily_tracking = state.get("daily_xml_tracking", {})
        
        if cnpj not in daily_tracking or month_key not in daily_tracking[cnpj]:
            return {}
        
        company_month_data = daily_tracking[cnpj][month_key]
        result = {}
        
        # Iterar por cada dia no intervalo
        current_date = start_date
        while current_date <= end_date:
            day_key = current_date.strftime("%d")
            date_str = current_date.strftime("%Y-%m-%d")
            
            if day_key in company_month_data:
                day_xmls = []
                day_data = company_month_data[day_key]
                
                for dt in day_data:
                    if doc_type and dt != doc_type:
                        continue
                    
                    for p in day_data[dt]:
                        if papel and p != papel:
                            continue
                        
                        day_xmls.extend(day_data[dt][p])
                
                if day_xmls:
                    result[date_str] = day_xmls
            
            current_date += timedelta(days=1)
        
        return result
    
    def analyze_temporal_gaps(self, cnpj: str, month_key: str, doc_type: str = None) -> Dict[str, Any]:
        """
        Analisa gaps temporais para uma empresa em um mês.
        
        Args:
            cnpj: CNPJ da empresa
            month_key: Chave do mês
            doc_type: Tipo do documento (opcional)
            
        Returns:
            Análise dos gaps temporais
        """
        state = self._load_month_state(month_key)
        daily_tracking = state.get("daily_xml_tracking", {})
        
        # Determinar intervalo do mês
        year, month = month_key.split('-')
        year, month = int(year), int(month)
        
        start_date = date(year, month, 1)
        
        # Último dia do mês
        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)
        end_date = next_month - timedelta(days=1)
        
        analysis = {
            "cnpj": cnpj,
            "month": month_key,
            "doc_type_filter": doc_type,
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "total_days": (end_date - start_date).days + 1
            },
            "coverage": {
                "days_with_data": 0,
                "days_without_data": 0,
                "coverage_percentage": 0.0
            },
            "gaps": [],
            "daily_summary": {},
            "recommendations": []
        }
        
        if cnpj not in daily_tracking or month_key not in daily_tracking[cnpj]:
            # Nenhum dado encontrado
            analysis["coverage"]["days_without_data"] = analysis["period"]["total_days"]
            analysis["gaps"].append({
                "type": "complete_month",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "duration_days": analysis["period"]["total_days"]
            })
            analysis["recommendations"].append("Empresa não possui dados para este mês - considere reprocessamento completo")
            return analysis
        
        company_month_data = daily_tracking[cnpj][month_key]
        
        # Analisar cada dia do mês
        current_date = start_date
        gap_start = None
        
        while current_date <= end_date:
            day_key = current_date.strftime("%d")
            date_str = current_date.isoformat()
            
            has_data = False
            daily_count = 0
            
            if day_key in company_month_data:
                day_data = company_month_data[day_key]
                
                for dt in day_data:
                    if doc_type and dt != doc_type:
                        continue
                    
                    for papel in day_data[dt]:
                        xml_count = len(day_data[dt][papel])
                        daily_count += xml_count
                        if xml_count > 0:
                            has_data = True
            
            analysis["daily_summary"][date_str] = {
                "has_data": has_data,
                "xml_count": daily_count
            }
            
            if has_data:
                analysis["coverage"]["days_with_data"] += 1
                
                # Finalizar gap se estava em andamento
                if gap_start:
                    gap_end = current_date - timedelta(days=1)
                    gap_duration = (gap_end - gap_start).days + 1
                    
                    analysis["gaps"].append({
                        "type": "temporal_gap",
                        "start_date": gap_start.isoformat(),
                        "end_date": gap_end.isoformat(),
                        "duration_days": gap_duration
                    })
                    gap_start = None
            else:
                analysis["coverage"]["days_without_data"] += 1
                
                # Iniciar novo gap se necessário
                if not gap_start:
                    gap_start = current_date
            
            current_date += timedelta(days=1)
        
        # Finalizar gap se terminou no final do mês
        if gap_start:
            gap_duration = (end_date - gap_start).days + 1
            analysis["gaps"].append({
                "type": "end_of_period_gap",
                "start_date": gap_start.isoformat(),
                "end_date": end_date.isoformat(),
                "duration_days": gap_duration
            })
        
        # Calcular percentual de cobertura
        total_days = analysis["period"]["total_days"]
        if total_days > 0:
            analysis["coverage"]["coverage_percentage"] = (analysis["coverage"]["days_with_data"] / total_days) * 100
        
        # Gerar recomendações
        if analysis["coverage"]["coverage_percentage"] < 50:
            analysis["recommendations"].append("Cobertura baixa (<50%) - considere reprocessamento completo do mês")
        elif analysis["gaps"]:
            for gap in analysis["gaps"]:
                if gap["duration_days"] >= 3:
                    analysis["recommendations"].append(f"Gap de {gap['duration_days']} dias entre {gap['start_date']} e {gap['end_date']} - reprocessar período")
        else:
            analysis["recommendations"].append("Cobertura adequada - nenhuma ação necessária")
        
        return analysis
    
    def get_missing_days(self, cnpj: str, month_key: str, doc_type: str = None) -> List[str]:
        """
        Retorna lista de dias sem dados para uma empresa/mês.
        
        Args:
            cnpj: CNPJ da empresa
            month_key: Chave do mês
            doc_type: Tipo do documento (opcional)
            
        Returns:
            Lista de datas (YYYY-MM-DD) sem dados
        """
        analysis = self.analyze_temporal_gaps(cnpj, month_key, doc_type)
        
        missing_days = []
        for date_str, day_info in analysis["daily_summary"].items():
            if not day_info["has_data"]:
                missing_days.append(date_str)
        
        return missing_days
    
    def log_daily_processing(self, cnpj: str, month_key: str, processing_date: date, 
                           status: str, counts: Dict[str, int]) -> None:
        """
        Registra log de processamento diário.
        
        Args:
            cnpj: CNPJ da empresa
            month_key: Chave do mês
            processing_date: Data do processamento
            status: Status do processamento (success, error, partial)
            counts: Contadores de XMLs processados
        """
        state = self._load_month_state(month_key)
        
        if "daily_processing_log" not in state:
            state["daily_processing_log"] = {}
        
        processing_log = state["daily_processing_log"]
        
        if cnpj not in processing_log:
            processing_log[cnpj] = {}
        if month_key not in processing_log[cnpj]:
            processing_log[cnpj][month_key] = {}
        
        day_key = processing_date.strftime("%d")
        processing_log[cnpj][month_key][day_key] = {
            "timestamp": datetime.now().isoformat(),
            "status": status,
            "counts": counts,
            "processing_date": processing_date.isoformat()
        }
    
    def generate_gap_recovery_plan(self, cnpj: str, month_key: str, doc_type: str = None) -> Dict[str, Any]:
        """
        Gera plano de recuperação para gaps temporais.
        
        Args:
            cnpj: CNPJ da empresa
            month_key: Chave do mês
            doc_type: Tipo do documento (opcional)
            
        Returns:
            Plano de recuperação estruturado
        """
        analysis = self.analyze_temporal_gaps(cnpj, month_key, doc_type)
        
        recovery_plan = {
            "cnpj": cnpj,
            "month": month_key,
            "analysis_summary": {
                "total_gaps": len(analysis["gaps"]),
                "coverage_percentage": analysis["coverage"]["coverage_percentage"],
                "days_to_recover": analysis["coverage"]["days_without_data"]
            },
            "recovery_tasks": [],
            "priority": "low",
            "estimated_effort": "minimal"
        }
        
        # Determinar prioridade baseada na cobertura
        coverage = analysis["coverage"]["coverage_percentage"]
        if coverage < 30:
            recovery_plan["priority"] = "high"
            recovery_plan["estimated_effort"] = "substantial"
        elif coverage < 70:
            recovery_plan["priority"] = "medium"
            recovery_plan["estimated_effort"] = "moderate"
        
        # Criar tarefas de recuperação
        for gap in analysis["gaps"]:
            if gap["duration_days"] >= 1:  # Recuperar gaps de 1+ dias
                task = {
                    "task_type": "reprocess_period",
                    "start_date": gap["start_date"],
                    "end_date": gap["end_date"],
                    "duration_days": gap["duration_days"],
                    "description": f"Reprocessar período de {gap['duration_days']} dias",
                    "parameters": {
                        "cnpj": cnpj,
                        "start_date": gap["start_date"],
                        "end_date": gap["end_date"],
                        "doc_types": [doc_type] if doc_type else ["NFe", "CTe"],
                        "force_reprocess": True
                    }
                }
                recovery_plan["recovery_tasks"].append(task)
        
        # Se não há gaps específicos, mas cobertura baixa, reprocessar tudo
        if not recovery_plan["recovery_tasks"] and coverage < 50:
            year, month = month_key.split('-')
            start_date = date(int(year), int(month), 1)
            
            if int(month) == 12:
                end_date = date(int(year) + 1, 1, 1) - timedelta(days=1)
            else:
                end_date = date(int(year), int(month) + 1, 1) - timedelta(days=1)
            
            task = {
                "task_type": "reprocess_full_month",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "duration_days": (end_date - start_date).days + 1,
                "description": f"Reprocessar mês completo ({month_key})",
                "parameters": {
                    "cnpj": cnpj,
                    "month": month_key,
                    "doc_types": [doc_type] if doc_type else ["NFe", "CTe"],
                    "force_reprocess": True
                }
            }
            recovery_plan["recovery_tasks"].append(task)
        
        return recovery_plan
    
    def get_companies_with_gaps(self, month_key: str, min_gap_days: int = 3) -> List[Dict[str, Any]]:
        """
        Identifica empresas com gaps temporais significativos.
        
        Args:
            month_key: Chave do mês
            min_gap_days: Mínimo de dias para considerar gap significativo
            
        Returns:
            Lista de empresas com gaps
        """
        state = self._load_month_state(month_key)
        daily_tracking = state.get("daily_xml_tracking", {})
        
        companies_with_gaps = []
        
        for cnpj in daily_tracking.keys():
            analysis = self.analyze_temporal_gaps(cnpj, month_key)
            
            significant_gaps = [gap for gap in analysis["gaps"] if gap["duration_days"] >= min_gap_days]
            
            if significant_gaps or analysis["coverage"]["coverage_percentage"] < 70:
                company_info = {
                    "cnpj": cnpj,
                    "coverage_percentage": analysis["coverage"]["coverage_percentage"],
                    "total_gaps": len(analysis["gaps"]),
                    "significant_gaps": len(significant_gaps),
                    "days_without_data": analysis["coverage"]["days_without_data"],
                    "largest_gap_days": max([gap["duration_days"] for gap in analysis["gaps"]], default=0),
                    "needs_attention": analysis["coverage"]["coverage_percentage"] < 50 or len(significant_gaps) > 0
                }
                companies_with_gaps.append(company_info)
        
        # Ordenar por prioridade (menor cobertura primeiro)
        companies_with_gaps.sort(key=lambda x: (x["coverage_percentage"], -x["significant_gaps"]))
        
        return companies_with_gaps
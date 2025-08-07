"""Módulo para geração de resumos mensais legíveis."""

import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional, Set
from datetime import datetime, date

logger = logging.getLogger(__name__)


def _format_validation_status(validation_result: Dict[str, Any]) -> str:
    """Formata o status da validação para exibição no log."""
    if not validation_result or 'faltantes' not in validation_result: # Checagem mais robusta
        return "Validação não realizada (Relatório ausente?)"

    faltantes_validos = len(validation_result.get('faltantes', []))
    faltantes_ignorados = len(validation_result.get('faltantes_ignorados', []))
    extras = len(validation_result.get('extras', []))

    if faltantes_validos == 0 and extras == 0:
        if faltantes_ignorados > 0:
             return f"OK (Apenas {faltantes_ignorados} ignorados [Rem/Exp/Rec])"
        else:
             return "OK (100%)"
    else:
        parts = []
        if faltantes_validos > 0:
            parts.append(f"{faltantes_validos} Faltantes Válidos")
        if faltantes_ignorados > 0:
             parts.append(f"{faltantes_ignorados} Ignorados") # Informar ignorados
        if extras > 0:
            parts.append(f"{extras} Extras")
        return f"Atenção ({', '.join(parts)})"

def append_monthly_summary(
    summary_file_path: Path,
    execution_time: datetime,
    empresa_cnpj: str,
    empresa_nome: str,
    period_start: date,
    period_end: date,
    diff_results: Optional[Dict[str, Dict[str, Any]]] = None,
    report_counts: Optional[Dict[str, Dict[Tuple[str, str], int]]] = None,
    download_stats: Optional[Dict[str, Any]] = None,
    final_counts: Optional[Dict[str, Any]] = None,
    error_stats: Optional[Dict[str, int]] = None # NOVO: Passar erros de salvamento
) -> bool:
    """
    Adiciona (append) um resumo formatado ao final de um arquivo de log.

    Args:
        summary_file_path: Caminho para o arquivo de log de resumo.
        execution_time: Timestamp da execução.
        empresa_cnpj: CNPJ da empresa.
        empresa_nome: Nome da pasta/empresa.
        period_start: Data de início do período de busca.
        period_end: Data de fim do período de busca.
        diff_results: Dicionário com resultados da validação Relatório vs Local.
                      Estrutura: {'NFe': validation_result_nfe, 'CTe': validation_result_cte}
                      Onde validation_result contém chaves como 'total_relatorio_periodo', 'total_local', 'faltantes', etc.
        report_counts: Dicionário com contagens por papel extraídas do relatório.
                       Estrutura: {'NFe': {('NFe', 'Papel'): count, ...}, 'CTe': {('CTe', 'Papel'): count, ...}}
        download_stats: Dicionário com estatísticas do download individual.
        final_counts: Dicionário com a contagem local final de arquivos principais e eventos.
                      Estrutura: {'NFe': count, 'CTe': count, 'EventosCancelamento': count}
        error_stats: Dicionário com contagens de erros ocorridos (parse, info, save).

    Returns:
        True se o resumo foi adicionado com sucesso, False caso contrário.
    """
    lines = []
    try:
        # --- Cabeçalho ---
        lines.append("="*80)
        exec_time_str = execution_time.strftime("%d/%m/%Y %H:%M:%S")
        month_year_str = period_start.strftime("%B/%Y") # Nome do mês baseado no início do período
        lines.append(f"Auditoria SIEG - {empresa_nome} ({empresa_cnpj}) - {month_year_str.lower()} (execução: {exec_time_str})")
        lines.append(f"Período de busca: {period_start.strftime('%d/%m/%Y')} a {period_end.strftime('%d/%m/%Y')}")
        lines.append("-"*80)

        # --- Seção Validação Relatório vs Local ---
        lines.append("VALIDAÇÃO RELATÓRIO OFICIAL vs. ARQUIVOS LOCAIS")
        lines.append("  Tipo       | Relatório (Período) | Local | Faltantes Válidos | Extras | Status")
        lines.append("  " + "-"*76)

        for doc_type in ["NFe", "CTe"]:
            validation_data = diff_results.get(doc_type, {}) if diff_results else {}
            local_count = final_counts.get(doc_type, 0) if final_counts else 0

            if not validation_data or validation_data.get("status") == "ERRO_RELATORIO" or validation_data.get("status") == "ERRO_RELATORIO_VALIDACAO":
                rel_periodo = "N/A"
                local_val_str = "N/A"
                faltantes_str = "N/A"
                extras_str = "N/A"
                status_str = validation_data.get("message", "Validação não realizada (Relatório ausente?)")
            elif validation_data.get("status") == "ERRO_VALIDACAO":
                rel_periodo = str(validation_data.get('total_relatorio_periodo', 'N/A'))
                local_val_str = str(validation_data.get('total_local', 'N/A'))
                faltantes_str = "N/A"
                extras_str = "N/A"
                status_str = f"Erro Validação: {validation_data.get('message', '?')}"
            else:
                rel_periodo = str(validation_data.get('total_relatorio_periodo', 'N/A'))
                local_val_str = str(validation_data.get('total_local', 'N/A'))
                faltantes_str = str(len(validation_data.get('faltantes', [])))
                extras_str = str(len(validation_data.get('extras', [])))
                status_str = _format_validation_status(validation_data)

            lines.append(f"  {doc_type:<10} | {rel_periodo:>19} | {local_val_str:>5} | {faltantes_str:>17} | {extras_str:>6} | {status_str}")

            # Detalhes de Faltantes/Extras (se houver)
            faltantes_list = validation_data.get('faltantes', [])
            if faltantes_list:
                 lines.append("      >> Chaves Faltantes Válidas (primeiras 10):")
                 for key in faltantes_list[:10]: lines.append(f"         - {key}")
                 if len(faltantes_list) > 10: lines.append(f"         ... (e mais {len(faltantes_list) - 10})")

            faltantes_ign_list = validation_data.get('faltantes_ignorados', [])
            if faltantes_ign_list:
                 lines.append("      >> Chaves Faltantes Ignoradas (primeiras 10):")
                 for key in faltantes_ign_list[:10]: lines.append(f"         - {key}")
                 if len(faltantes_ign_list) > 10: lines.append(f"         ... (e mais {len(faltantes_ign_list) - 10})")

            extras_list = validation_data.get('extras', [])
            if extras_list:
                 lines.append("      >> Chaves Extras (primeiras 10):")
                 for key in extras_list[:10]: lines.append(f"         - {key}")
                 if len(extras_list) > 10: lines.append(f"         ... (e mais {len(extras_list) - 10})")

        lines.append("  " + "-"*76)

        # --- Seção Contagem Relatório por Papel ---
        lines.append("  Contagem Relatório por Papel (NFe):")
        report_nfe_counts = report_counts.get('NFe', {}) if report_counts else {}
        if not report_nfe_counts:
            lines.append("    N/A (Relatório NFe não processado ou vazio)")
        else:
            nfe_counts_str = ", ".join([f"{papel}={count}" for (_, papel), count in sorted(report_nfe_counts.items())])
            lines.append(f"    {nfe_counts_str}")

        lines.append("  Contagem Relatório por Papel (CTe):")
        report_cte_counts = report_counts.get('CTe', {}) if report_counts else {}
        if not report_cte_counts:
            lines.append("    N/A (Relatório CTe não processado ou vazio)")
        else:
            cte_counts_str = ", ".join([f"{papel}={count}" for (_, papel), count in sorted(report_cte_counts.items())])
            lines.append(f"    {cte_counts_str}")

        # --- Contagem Local Geral ---
        lines.append("  Contagem Local Final (Diretórios Padrão):")
        if final_counts:
            nfe_ent_norm = final_counts.get("NFe_Entrada", 0)
            nfe_sai_norm = final_counts.get("NFe_Saída", 0)
            cte_ent_norm = final_counts.get("CTe_Entrada", 0)
            cte_sai_norm = final_counts.get("CTe_Saída", 0)
            lines.append(f"    NFe: Entrada={nfe_ent_norm}, Saída={nfe_sai_norm}")
            lines.append(f"    CTe: Entrada={cte_ent_norm}, Saída={cte_sai_norm}")
        else:
            lines.append("    N/A (Contagem local não disponível)")

        # --- Contagem Local Mês Anterior (NOVO) ---
        lines.append("  Contagem Local Final (Mês Anterior - Entrada dias 1-5):")
        if final_counts:
            nfe_ent_ant = final_counts.get("NFe_Entrada_MesAnterior", 0)
            cte_ent_ant = final_counts.get("CTe_Entrada_MesAnterior", 0)
            lines.append(f"    NFe Entrada (Mês Ant.): {nfe_ent_ant}")
            lines.append(f"    CTe Entrada (Mês Ant.): {cte_ent_ant}")
        else:
            lines.append("    N/A (Contagem local não disponível)")

        # --- Contagem Local de Eventos ---
        # Acessar o dicionário de eventos e pegar a chave 'total'
        eventos_info = final_counts.get('Eventos_Cancelamento', {}) if final_counts else {}
        eventos_locais_total = eventos_info.get('total', 0)
        lines.append(f"  Eventos Cancelamento (Local): {eventos_locais_total}")
        # Poderíamos adicionar mais detalhes dos tipos de eventos se desejado:
        # if eventos_locais_total > 0:
        #     tipos_str = ", ".join([f"{k}={v}" for k, v in eventos_info.items() if k not in ['total', 'erros_leitura']])
        #     lines.append(f"    (Detalhes: {tipos_str})")
        #     if eventos_info.get('erros_leitura', 0) > 0:
        #         lines.append(f"    (Erros leitura: {eventos_info.get('erros_leitura')})")

        lines.append("-"*80)

        # --- Seção de Erros ---
        lines.append("ERROS DURANTE O PROCESSAMENTO DESTA EXECUÇÃO")
        if error_stats:
            parse_err = error_stats.get('parse_errors', 0)
            info_err = error_stats.get('info_errors', 0)
            save_err = error_stats.get('save_errors', 0)
            total_err = parse_err + info_err + save_err
            if total_err > 0:
                lines.append(f"  • Erros de Parse XML/Base64: {parse_err}")
                lines.append(f"  • Erros de Extração de Info: {info_err}")
                lines.append(f"  • Erros de Salvamento OS:    {save_err}")
                lines.append( "  (Verificar logs detalhados para mais informações)")
            else:
                lines.append("  Nenhum erro de salvamento/parse registrado nesta execução.")
        else:
            lines.append("  (Informações de erro não disponíveis)")

        lines.append("-"*80)

        # --- Seção de Download Individual ---
        lines.append("DOWNLOAD INDIVIDUAL DE CHAVES FALTANTES VÁLIDAS (Emit/Dest/Tom)")
        if not download_stats or not download_stats.get('tentativas'): # Checa se houve tentativas
            lines.append("  Nenhuma tentativa de download individual realizada.")
        else:
            tentativas = download_stats.get('tentativas', 0)
            sucesso = download_stats.get('sucesso', 0)
            falha_dl = download_stats.get('falha_download', 0)
            falha_save = download_stats.get('falha_salvar', 0)
            falhas_total = falha_dl + falha_save
            lines.append(f"  • Tentativas={tentativas}, Sucesso={sucesso}, Falhas={falhas_total} (Download: {falha_dl}, Salvar: {falha_save})")
            # Adicionar detalhes das falhas se disponível em download_stats
            # Ex: download_stats['falhas_chaves']

        lines.append("="*80)

        # --- Escrita no Arquivo ---
        content = "\n".join(lines) + "\n"
        with open(summary_file_path, "a", encoding='utf-8') as f:
            f.write(content)
        logger.info(f"Resumo adicionado ao arquivo: {summary_file_path}")
        return True

    except Exception as e:
        logger.error(f"Erro ao gerar ou anexar resumo em {summary_file_path}: {e}", exc_info=True)
        return False

# Remover o pass original se existir
# pass 
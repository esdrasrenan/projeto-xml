#!/usr/bin/env python3
"""
Auditoria de Agosto/2025

Gera:
- reports/auditoria_08-2025_empresas.csv: resumo por empresa
- reports/auditoria_08-2025_faltantes.csv: chaves locais não marcadas como importadas no state

Regras:
- Lê pastas locais de XML em F:/x_p/XML_CLIENTES/2025/<NOME_PASTA>/08
- Considera apenas documentos principais (NFe/CTe) com nome <44_digitos>.xml
- Lê states em estado/08-2025/state.json e estado/2025-08/state.json (se existirem) e mescla
- Detecta empresas com "Iniciando download individual" nos logs de agosto

Uso:
  python scripts/auditar_agosto_2025.py [--cnpj 14777477000192 03349915000103 ...]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Dict, Set, List, Tuple

# Reaproveita caminhos do projeto
ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.append(str(ROOT))
from core.file_manager import PRIMARY_SAVE_BASE_PATH
DATA_XLSX = ROOT / 'data' / 'SIEG.xlsx'
ESTADO_DIR = ROOT / 'estado'
LOGS_DIR = ROOT / 'logs'
REPORTS_DIR = ROOT / 'reports'

YEAR = 2025
MONTH = 8
MONTH_KEY_V2 = f"{MONTH:02d}-{YEAR}"
MONTH_KEY_V1 = f"{YEAR}-{MONTH:02d}"

RE_XML_MAIN = re.compile(r"^(?P<key>\d{44})\.xml$", re.IGNORECASE)


def normalize_cnpj(s: str) -> str:
    digits = re.sub(r"\D", "", str(s))
    return digits.zfill(14)


def load_empresas_from_excel() -> List[Tuple[str, str]]:
    """Retorna lista de (cnpj_norm, nome_pasta) a partir de data/SIEG.xlsx.
    Exige colunas 'CnpjCpf' e 'Nome Tratado'.
    """
    try:
        import pandas as pd
    except Exception as e:  # pragma: no cover
        raise SystemExit(f"pandas é necessário para ler data/SIEG.xlsx: {e}")

    df = pd.read_excel(DATA_XLSX)
    if 'CnpjCpf' not in df.columns or 'Nome Tratado' not in df.columns:
        raise SystemExit("Planilha SIEG.xlsx precisa conter colunas 'CnpjCpf' e 'Nome Tratado'.")

    empresas: List[Tuple[str, str]] = []
    for _, row in df.iterrows():
        cnpj = normalize_cnpj(row['CnpjCpf'])
        pasta = str(row['Nome Tratado']).strip()
        if cnpj and pasta:
            empresas.append((cnpj, pasta))
    return empresas


def read_state_merged() -> Dict[str, Dict[str, Dict[str, List[str]]]]:
    """Carrega processed_xml_keys mesclando v1 e v2.
    Estrutura retornada: processed[cnpj][month_key][xml_type] -> List[chaves]
    """
    processed: Dict[str, Dict[str, Dict[str, List[str]]]] = {}

    def merge_from(path: Path):
        if not path.exists():
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            return
        px = data.get('processed_xml_keys', {})
        for cnpj, months in px.items():
            processed.setdefault(cnpj, {})
            for month_key, by_type in months.items():
                processed[cnpj].setdefault(month_key, {})
                for xml_type, lst in by_type.items():
                    # mesclar preservando unicidade
                    cur = set(processed[cnpj][month_key].get(xml_type, []))
                    cur.update(lst or [])
                    processed[cnpj][month_key][xml_type] = sorted(cur)

    merge_from(ESTADO_DIR / MONTH_KEY_V2 / 'state.json')
    merge_from(ESTADO_DIR / MONTH_KEY_V1 / 'state.json')
    return processed


def list_local_keys_for_company(nome_pasta: str) -> Dict[str, Set[str]]:
    """Coleta chaves locais para NFe e CTe em 2025/<pasta>/08.
    Retorna {'NFe': set(keys), 'CTe': set(keys)}
    """
    result = {'NFe': set(), 'CTe': set()}
    month_dir = PRIMARY_SAVE_BASE_PATH / str(YEAR) / nome_pasta / f"{MONTH:02d}"
    if not month_dir.is_dir():
        return result
    for doc_type in ['NFe', 'CTe']:
        doc_dir = month_dir / doc_type
        if not doc_dir.exists():
            continue
        for p in doc_dir.rglob('*.xml'):
            m = RE_XML_MAIN.match(p.name)
            if m:
                result[doc_type].add(m.group('key'))
    return result


def company_had_individual_download(cnpj_norm: str) -> bool:
    pattern = f"[{cnpj_norm}] Iniciando download individual"
    # Busca rápida em logs de agosto
    for log_file in list(LOGS_DIR.glob('08-2025/*.log')) + list(LOGS_DIR.glob('2025_08_*.log')) + [LOGS_DIR / 'global.log']:
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if pattern in line:
                        return True
        except Exception:
            pass
    return False


def main():
    parser = argparse.ArgumentParser(description='Auditoria Agosto/2025 - locais vs state, e empresas com download individual')
    parser.add_argument('--cnpj', nargs='*', help='Filtrar por CNPJs (somente os informados)')
    args = parser.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    empresas = load_empresas_from_excel()
    if args.cnpj:
        filt = {normalize_cnpj(c) for c in args.cnpj}
        empresas = [e for e in empresas if e[0] in filt]

    processed = read_state_merged()

    resumo_rows: List[Dict[str, str]] = []
    faltantes_rows: List[Dict[str, str]] = []

    for cnpj, pasta in empresas:
        local = list_local_keys_for_company(pasta)
        imported_nfe = set(processed.get(cnpj, {}).get(MONTH_KEY_V2, {}).get('NFe', [])) | \
                        set(processed.get(cnpj, {}).get(MONTH_KEY_V1, {}).get('NFe', []))
        imported_cte = set(processed.get(cnpj, {}).get(MONTH_KEY_V2, {}).get('CTe', [])) | \
                        set(processed.get(cnpj, {}).get(MONTH_KEY_V1, {}).get('CTe', []))

        falt_nfe = sorted(local['NFe'] - imported_nfe)
        falt_cte = sorted(local['CTe'] - imported_cte)

        resumo_rows.append({
            'cnpj': cnpj,
            'pasta': pasta,
            'download_individual': 'SIM' if company_had_individual_download(cnpj) else 'NAO',
            'local_nfe': str(len(local['NFe'])),
            'state_imported_nfe': str(len(imported_nfe)),
            'gap_nfe': str(len(falt_nfe)),
            'local_cte': str(len(local['CTe'])),
            'state_imported_cte': str(len(imported_cte)),
            'gap_cte': str(len(falt_cte)),
        })

        # Registrar faltantes com caminho
        month_dir = PRIMARY_SAVE_BASE_PATH / str(YEAR) / pasta / f"{MONTH:02d}"
        for doc_type, falt_list in (('NFe', falt_nfe), ('CTe', falt_cte)):
            for key in falt_list:
                # Buscar arquivo em possíveis pastas
                possible = list((month_dir / doc_type).rglob(f"{key}.xml"))
                full_path = str(possible[0]) if possible else ''
                faltantes_rows.append({
                    'cnpj': cnpj,
                    'pasta': pasta,
                    'doc_type': doc_type,
                    'key': key,
                    'file_path': full_path,
                })

    resumo_csv = REPORTS_DIR / 'auditoria_08-2025_empresas.csv'
    faltantes_csv = REPORTS_DIR / 'auditoria_08-2025_faltantes.csv'

    with open(resumo_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(resumo_rows[0].keys()) if resumo_rows else [
            'cnpj','pasta','download_individual','local_nfe','state_imported_nfe','gap_nfe','local_cte','state_imported_cte','gap_cte'])
        writer.writeheader()
        writer.writerows(resumo_rows)

    with open(faltantes_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['cnpj','pasta','doc_type','key','file_path'])
        writer.writeheader()
        writer.writerows(faltantes_rows)

    print(f"Resumo por empresa salvo em: {resumo_csv}")
    print(f"Faltantes detalhados salvos em: {faltantes_csv}")


if __name__ == '__main__':
    main()

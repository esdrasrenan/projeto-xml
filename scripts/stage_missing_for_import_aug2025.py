#!/usr/bin/env python3
"""
Stage de XMLs faltantes (Agosto/2025) para cópia manual ao Import.

Lê reports/auditoria_08-2025_faltantes.csv e copia os arquivos faltantes
para uma área de staging local, sem alterar o state.

Estrutura de saída:
  staging_import/08-2025/ALL_FLAT/<chave>.xml           (agregado)
  staging_import/08-2025/<CNPJ>_<PASTA>/flat/<chave>.xml (por empresa)

Uso:
  python scripts/stage_missing_for_import_aug2025.py [--cnpj 14777477000192 ...]
"""

from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / 'reports'
STAGING_BASE = ROOT / 'staging_import' / '08-2025'


def main():
    parser = argparse.ArgumentParser(description='Preparar staging de XMLs faltantes (Agosto/2025)')
    parser.add_argument('--cnpj', nargs='*', help='Filtrar por CNPJs')
    parser.add_argument('--source', default=str(REPORTS_DIR / 'auditoria_08-2025_faltantes.csv'), help='CSV de faltantes gerado pela auditoria')
    args = parser.parse_args()

    csv_path = Path(args.source)
    if not csv_path.exists():
        raise SystemExit(f"Arquivo de faltantes não encontrado: {csv_path}. Rode primeiro scripts/auditar_agosto_2025.py")

    STAGING_BASE.mkdir(parents=True, exist_ok=True)
    staging_all = STAGING_BASE / 'ALL_FLAT'
    staging_all.mkdir(exist_ok=True)

    count_total = 0
    count_copied = 0
    count_missing_src = 0

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cnpj = row['cnpj']
            if args.cnpj and cnpj not in set(args.cnpj):
                continue
            pasta = row['pasta']
            key = row['key']
            file_path = Path(row['file_path']) if row['file_path'] else None
            if not file_path or not file_path.exists():
                count_missing_src += 1
                continue

            # Destinos: ALL + por empresa
            dst_all = staging_all / f"{key}.xml"
            comp_dir = STAGING_BASE / f"{cnpj}_{pasta}"
            (comp_dir / 'flat').mkdir(parents=True, exist_ok=True)
            dst_comp = comp_dir / 'flat' / f"{key}.xml"

            # Copiar se não existir
            for dst in (dst_all, dst_comp):
                if not dst.exists():
                    try:
                        shutil.copy2(file_path, dst)
                        count_copied += 1
                    except Exception:
                        # segue para o próximo
                        pass
            count_total += 1

    print(f"Faltantes processados: {count_total}")
    print(f"Arquivos copiados para staging: {count_copied}")
    if count_missing_src:
        print(f"Aviso: {count_missing_src} itens no CSV não foram encontrados na origem (verificar árvore local)")
    print(f"Staging ALL: {staging_all}")
    print(f"Staging por empresa: {STAGING_BASE}")


if __name__ == '__main__':
    main()


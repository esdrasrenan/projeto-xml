#!/usr/bin/env python3
"""
Teste real com XMLs da PAULICON para validar controle de duplicação
Data: 18/08/2025
"""

import sys
import base64
import json
from pathlib import Path

# Adiciona o diretório core ao path
sys.path.insert(0, str(Path(__file__).parent / 'core'))

from state_manager_v2 import StateManagerV2
# TransactionalFileManager requer outras importações, vamos testar apenas o state_manager

def test_paulicon_duplicates():
    """Testa se os XMLs da PAULICON já processados serão identificados como duplicados"""
    
    print("="*60)
    print("TESTE PAULICON - CONTROLE DE DUPLICAÇÃO")
    print("="*60)
    
    # Dados da PAULICON
    cnpj = "59957415000109"
    nome_pasta = "0001_PAULICON_CONTABIL_LTDA"
    
    # XMLs conhecidos da PAULICON em agosto
    xmls_paulicon = [
        ("35250814458671000105550010000003491000003503", "NFe"),
        ("35250857142978000105550010007202921992534304", "NFe"),
        ("41250811436073000147550010009037881339690770", "NFe"),
        ("41250820596025000107550010000128241849498040", "NFe"),
        ("41250818016343000452570100004609761002025715", "CTe"),
    ]
    
    print(f"\n[INFO] Empresa: {nome_pasta}")
    print(f"[INFO] CNPJ: {cnpj}")
    print(f"[INFO] XMLs conhecidos: {len(xmls_paulicon)}")
    
    # Inicializar gerenciadores
    state_dir = Path("W:/estado")
    state_manager = StateManagerV2(state_dir)
    
    print(f"[INFO] StateManagerV2 carregado")
    
    # Verificar estado atual no state.json
    print("\n" + "-"*40)
    print("VERIFICANDO ESTADO ATUAL:")
    
    state_file = state_dir / "08-2025" / "state.json"
    with open(state_file, 'r') as f:
        state_data = json.load(f)
    
    # Verificar se PAULICON está no state
    if cnpj in state_data.get('processed_xml_keys', {}):
        print(f"[OK] PAULICON encontrada em processed_xml_keys")
        for month in state_data['processed_xml_keys'][cnpj]:
            for doc_type in state_data['processed_xml_keys'][cnpj][month]:
                count = len(state_data['processed_xml_keys'][cnpj][month][doc_type])
                print(f"  {month}/{doc_type}: {count} chaves marcadas")
    else:
        print(f"[AVISO] PAULICON NÃO encontrada em processed_xml_keys")
    
    # Testar cada XML conhecido
    print("\n" + "-"*40)
    print("TESTANDO CADA XML:")
    
    # Formatos de month_key para testar
    month_formats = [
        ("08-2025", "MM-YYYY"),
        ("2025-08", "YYYY-MM"),
    ]
    
    results = {}
    for chave, tipo in xmls_paulicon:
        print(f"\n[{tipo}] {chave[:20]}...")
        found = False
        for month, fmt in month_formats:
            is_imported = state_manager.is_xml_already_imported(cnpj, month, tipo, chave)
            if is_imported:
                print(f"  [{fmt}] JÁ IMPORTADO (formato: {month})")
                found = True
                results[chave] = month
                break
        if not found:
            print(f"  [ERRO] NÃO ENCONTRADO em nenhum formato!")
            results[chave] = None
    
    # Teste de marcação manual
    print("\n" + "-"*40)
    print("TESTE DE MARCAÇÃO MANUAL:")
    
    # Testar marcação de uma chave nova
    test_key = "TEST_PAULICON_12345"
    test_month = "08-2025"
    
    print(f"[INFO] Marcando chave de teste: {test_key}")
    state_manager.mark_xml_as_imported(cnpj, test_month, "NFe", test_key)
    
    # Verificar se foi marcada
    is_marked = state_manager.is_xml_already_imported(cnpj, test_month, "NFe", test_key)
    
    if is_marked:
        print("[SUCESSO] Chave de teste foi marcada corretamente!")
    else:
        print("[ERRO] Chave de teste NÃO foi marcada!")
    
    # Análise final
    print("\n" + "="*60)
    print("ANÁLISE FINAL:")
    print("-"*40)
    
    # Contar sucessos
    found_count = sum(1 for v in results.values() if v is not None)
    total_count = len(results)
    
    print(f"XMLs identificados: {found_count}/{total_count}")
    
    if found_count == total_count:
        print("[SUCESSO] Todos os XMLs foram identificados!")
        
        # Verificar formato usado
        formats_used = set(v for v in results.values() if v)
        if len(formats_used) == 1:
            print(f"[INFO] Formato consistente: {formats_used.pop()}")
        else:
            print(f"[AVISO] Múltiplos formatos: {formats_used}")
    else:
        print("[ERRO] Alguns XMLs não foram identificados")
        missing = [k for k, v in results.items() if v is None]
        for m in missing:
            print(f"  - {m}")
    
    print("="*60)
    
    return found_count == total_count

if __name__ == "__main__":
    try:
        success = test_paulicon_duplicates()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n[ERRO] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
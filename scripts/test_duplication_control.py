#!/usr/bin/env python3
"""
Teste unitário para validar o controle de duplicação de XMLs
Data: 18/08/2025
"""

import sys
import json
from pathlib import Path

# Adiciona o diretório core ao path
sys.path.insert(0, str(Path(__file__).parent / 'core'))

from state_manager_v2 import StateManagerV2

def test_duplication_control():
    """Testa o controle de duplicação com as condições reais do sistema"""
    
    print("="*60)
    print("TESTE DE CONTROLE DE DUPLICAÇÃO")
    print("="*60)
    
    # 1. Carregar o state real
    state_dir = Path("W:/estado")
    state_manager = StateManagerV2(state_dir)
    print(f"[OK] StateManagerV2 carregado de: {state_dir}")
    
    # 2. Dados de teste da Via Cargas
    cnpj = "49129329000146"
    month_formats = ["08-2025", "2025-08", "08/2025", "2025/08"]
    
    # 3. Testar diferentes formatos de month_key
    print(f"\n[INFO] Testando formatos de month_key para CNPJ {cnpj}:")
    print("-" * 40)
    
    for month in month_formats:
        # Pegar uma chave real dos XMLs duplicados
        test_key = "35250849129329000146570010001852101039836055"
        
        # Verificar se está marcado como importado
        is_imported = state_manager.is_xml_already_imported(cnpj, month, "CTe", test_key)
        
        print(f"Formato '{month}': {is_imported}")
        
        if is_imported:
            print(f"  [SUCESSO] ENCONTRADO! Este é o formato correto!")
            correct_format = month
            break
    else:
        print("  [ERRO] NENHUM formato encontrou a chave!")
        correct_format = None
    
    # 4. Analisar o state.json diretamente
    print(f"\n[ANALISE] Análise direta do state.json:")
    print("-" * 40)
    
    state_file = state_dir / "08-2025" / "state.json"
    with open(state_file, 'r') as f:
        state_data = json.load(f)
    
    if cnpj in state_data.get('processed_xml_keys', {}):
        months = list(state_data['processed_xml_keys'][cnpj].keys())
        print(f"Meses registrados para Via Cargas: {months}")
        
        for month in months:
            types = state_data['processed_xml_keys'][cnpj][month]
            for doc_type, keys in types.items():
                print(f"  {month}/{doc_type}: {len(keys)} chaves")
                
                # Verificar se nossa chave de teste está lá
                if test_key in keys:
                    print(f"    [OK] Chave de teste ENCONTRADA em {month}/{doc_type}")
    else:
        print(f"[ERRO] CNPJ {cnpj} NÃO encontrado em processed_xml_keys!")
    
    # 5. Testar a marcação de uma nova chave
    print(f"\n[TESTE] Testando marcação de nova chave:")
    print("-" * 40)
    
    new_test_key = "TEST_KEY_123456789"
    test_month = "08-2025"  # Usar o formato correto descoberto
    
    # Marcar como importado
    state_manager.mark_xml_as_imported(cnpj, test_month, "CTe", new_test_key)
    print(f"Marcado: {new_test_key}")
    
    # Verificar se foi marcado
    is_marked = state_manager.is_xml_already_imported(cnpj, test_month, "CTe", new_test_key)
    print(f"Verificação: {is_marked}")
    
    if is_marked:
        print("  [SUCESSO] Controle funcionando corretamente!")
    else:
        print("  [ERRO] Chave não foi marcada corretamente!")
    
    # 6. Verificar contagem total
    total_count = state_manager.get_imported_xml_count(cnpj, test_month, "CTe")
    print(f"\nTotal de CTe importados em {test_month}: {total_count}")
    
    # 7. Resultado final
    print("\n" + "="*60)
    if correct_format:
        print(f"[SUCESSO] FORMATO CORRETO IDENTIFICADO: '{correct_format}'")
        print(f"   O código deve usar este formato!")
    else:
        print("[ERRO] PROBLEMA: Formato do month_key não está compatível!")
    print("="*60)
    
    return correct_format

if __name__ == "__main__":
    try:
        result = test_duplication_control()
        sys.exit(0 if result else 1)
    except Exception as e:
        print(f"\n[ERRO] ERRO NO TESTE: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
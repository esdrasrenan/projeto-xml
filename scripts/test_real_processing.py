#!/usr/bin/env python3
"""
Teste realista simulando o processamento real de XMLs da Via Cargas
Data: 18/08/2025
"""

import sys
import base64
from pathlib import Path

# Adiciona o diretório core ao path
sys.path.insert(0, str(Path(__file__).parent / 'core'))

from state_manager_v2 import StateManagerV2
from file_manager_transactional import TransactionalFileManager

def test_real_processing():
    """Simula o processamento real com XMLs reais da Via Cargas"""
    
    print("="*60)
    print("TESTE REAL DE PROCESSAMENTO")
    print("="*60)
    
    # 1. Configuração inicial
    cnpj = "49129329000146"
    nome_pasta = "1066_VIA_CARGAS_TRANSPORTES_LTDA"
    
    # Carregar um XML real da pasta de duplicados
    xml_file = Path("W:/Avaliacao_XML/35250849129329000146570010001852101039836055.xml")
    if not xml_file.exists():
        print("[ERRO] Arquivo XML não encontrado!")
        return False
    
    with open(xml_file, 'rb') as f:
        xml_content = f.read()
    
    # Converter para base64 como a API retornaria
    xml_base64 = base64.b64encode(xml_content).decode('utf-8')
    
    print(f"[INFO] XML carregado: {xml_file.name}")
    print(f"[INFO] Tamanho: {len(xml_content)} bytes")
    
    # 2. Inicializar gerenciadores
    state_dir = Path("W:/estado")
    state_manager = StateManagerV2(state_dir)
    transactional_manager = TransactionalFileManager()
    
    print(f"[INFO] StateManagerV2 inicializado")
    print(f"[INFO] TransactionalFileManager inicializado")
    
    # 3. Verificar estado inicial
    print("\n" + "-"*40)
    print("ESTADO INICIAL:")
    
    # Testar diferentes formatos de month_key
    month_formats = [
        ("08-2025", "MM-YYYY"),
        ("2025-08", "YYYY-MM"),
        ("08/2025", "MM/YYYY"),
    ]
    
    chave_teste = "35250849129329000146570010001852101039836055"
    
    for month, fmt in month_formats:
        is_imported = state_manager.is_xml_already_imported(cnpj, month, "CTe", chave_teste)
        print(f"  Formato {fmt:10} ({month}): {'JÁ IMPORTADO' if is_imported else 'NÃO IMPORTADO'}")
    
    # 4. Simular o processamento
    print("\n" + "-"*40)
    print("SIMULANDO PROCESSAMENTO:")
    
    # Lista com apenas 1 XML para teste
    base64_list = [xml_base64]
    
    print(f"[INFO] Processando {len(base64_list)} XML(s)...")
    
    # Chamar a função EXATAMENTE como no código real
    try:
        # TESTE 1: SEM state_manager (como estava antes)
        print("\n[TESTE 1] Chamando SEM state_manager:")
        result1 = transactional_manager.save_xmls_from_base64_transactional(
            base64_list=base64_list,
            empresa_cnpj=cnpj,
            empresa_nome_pasta=nome_pasta,
            is_event=False
            # state_manager NÃO passado
        )
        print(f"  Resultado: flat_copy_success = {result1.get('flat_copy_success', 0)}")
        
        # TESTE 2: COM state_manager (como deveria ser)
        print("\n[TESTE 2] Chamando COM state_manager:")
        result2 = transactional_manager.save_xmls_from_base64_transactional(
            base64_list=base64_list,
            empresa_cnpj=cnpj,
            empresa_nome_pasta=nome_pasta,
            is_event=False,
            state_manager=state_manager  # state_manager PASSADO
        )
        print(f"  Resultado: flat_copy_success = {result2.get('flat_copy_success', 0)}")
        
    except Exception as e:
        print(f"[ERRO] Durante processamento: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # 5. Verificar estado final
    print("\n" + "-"*40)
    print("ESTADO FINAL:")
    
    for month, fmt in month_formats:
        is_imported = state_manager.is_xml_already_imported(cnpj, month, "CTe", chave_teste)
        print(f"  Formato {fmt:10} ({month}): {'JÁ IMPORTADO' if is_imported else 'NÃO IMPORTADO'}")
    
    # 6. Análise do resultado
    print("\n" + "="*60)
    print("ANÁLISE DO RESULTADO:")
    print("-"*40)
    
    esperado_sem_state = 1  # Deveria copiar pois não tem controle
    esperado_com_state = 0  # Não deveria copiar pois já está marcado
    
    print(f"SEM state_manager:")
    print(f"  Esperado: flat_copy_success = {esperado_sem_state}")
    print(f"  Obtido:   flat_copy_success = {result1.get('flat_copy_success', 0)}")
    print(f"  Status:   {'[OK]' if result1.get('flat_copy_success', 0) == esperado_sem_state else '[FALHOU]'}")
    
    print(f"\nCOM state_manager:")
    print(f"  Esperado: flat_copy_success = {esperado_com_state}")
    print(f"  Obtido:   flat_copy_success = {result2.get('flat_copy_success', 0)}")
    print(f"  Status:   {'[OK]' if result2.get('flat_copy_success', 0) == esperado_com_state else '[FALHOU]'}")
    
    # 7. Conclusão
    success = (result1.get('flat_copy_success', 0) == esperado_sem_state and 
               result2.get('flat_copy_success', 0) == esperado_com_state)
    
    print("\n" + "="*60)
    if success:
        print("[SUCESSO] Controle de duplicação funcionando corretamente!")
    else:
        print("[FALHOU] Controle de duplicação NÃO está funcionando!")
        print("\nPOSSÍVEIS CAUSAS:")
        print("1. Formato do month_key incompatível")
        print("2. state_manager não está sendo passado")
        print("3. Lógica de verificação com erro")
    print("="*60)
    
    return success

if __name__ == "__main__":
    try:
        result = test_real_processing()
        sys.exit(0 if result else 1)
    except Exception as e:
        print(f"\n[ERRO] ERRO NO TESTE: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
#!/usr/bin/env python3
"""
Script de debug para verificar por que controle de duplicação não funciona
"""
import sys
import os
sys.path.insert(0, 'W:/')
os.chdir('W:/')

from core.file_manager_transactional import TransactionalFileManager
from core.state_manager_v2 import StateManagerV2
from pathlib import Path

print("="*60)
print("TESTE DEBUG - CONTROLE DE DUPLICAÇÃO")
print("="*60)

# 1. Criar instâncias
state_manager = StateManagerV2(Path("W:/estado"))
transactional_manager = TransactionalFileManager()

print(f"StateManagerV2 carregado: {state_manager is not None}")
print(f"TransactionalFileManager carregado: {transactional_manager is not None}")

# 2. Testar chamada do método com state_manager
print("\nTestando chamada do método...")

# XML fake para teste
fake_xml = """<?xml version="1.0"?>
<nfeProc>
    <NFe>
        <infNFe>
            <ide><dhEmi>2025-08-15T10:00:00</dhEmi></ide>
        </infNFe>
    </NFe>
    <protNFe>
        <infProt><chNFe>35250814458671000105550010000003491000003503</chNFe></infProt>
    </protNFe>
</nfeProc>"""

import base64
xml_base64 = base64.b64encode(fake_xml.encode()).decode()

# 3. Chamar o método COM state_manager
print("\nChamando save_xmls_from_base64_transactional COM state_manager...")
try:
    result = transactional_manager.save_xmls_from_base64_transactional(
        base64_list=[xml_base64],
        empresa_cnpj="59957415000109",
        empresa_nome_pasta="0001_PAULICON_CONTABIL_LTDA",
        is_event=False,
        state_manager=state_manager
    )
    print(f"Resultado: {result}")
except Exception as e:
    print(f"ERRO: {e}")
    import traceback
    traceback.print_exc()

# 4. Verificar logs
print("\nVerificando se mensagens DEBUG apareceriam...")
print("Se tudo estiver correto, deveria ter aparecido:")
print("  [DEBUG] state_manager ATIVO para 59957415000109...")
print("  ou XML já foi importado...")

print("="*60)
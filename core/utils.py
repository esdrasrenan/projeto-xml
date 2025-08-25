"""Funções utilitárias compartilhadas."""

import re
from typing import Union

# Constantes para tipos de XML (conforme documentação SIEG)
XML_TYPE_NFE = 1
XML_TYPE_CTE = 2
# Adicionar outros tipos se forem usados no futuro
# XML_TYPE_NFSE = 3
# XML_TYPE_NFCE = 4
# XML_TYPE_CFE = 5

def normalize_cnpj(cnpj: Union[str, int, float]) -> str:
    """
    Normaliza um número de CNPJ ou CPF para uma string de dígitos.
    Remove caracteres não numéricos, trata floats terminados em .0.
    Para CNPJs, adiciona um zero à esquerda se tiver 13 dígitos para formar 14.
    Para CPFs, espera 11 dígitos.

    Args:
        cnpj: O número do documento (CNPJ ou CPF) como string, inteiro ou float.

    Returns:
        A string do CNPJ/CPF normalizada (14 ou 11 dígitos).

    Raises:
        ValueError: Se o documento for nulo ou inválido após a normalização (não 11 ou 14 dígitos).
    """
    if cnpj is None:
        raise ValueError("Documento (CNPJ/CPF) não pode ser nulo.")

    # 1. Converter para string SEMPRE
    cnpj_str = str(cnpj)

    # 2. REMOVER '.0' se a STRING terminar com ele
    if cnpj_str.endswith('.0'):
        cnpj_str = cnpj_str[:-2]

    # 3. Remover outros não-dígitos
    digits = re.sub(r'\D', '', cnpj_str)

    # 4. Adicionar zero inicial se tiver 13 dígitos (tratamento para CNPJ)
    if len(digits) == 13:
        digits = '0' + digits

    # 5. Validação final para CNPJ (14 dígitos) ou CPF (11 dígitos)
    if not digits.isdigit() or len(digits) not in [11, 14]:
        raise ValueError(f"Documento (CNPJ/CPF) inválido após normalização: {cnpj} -> {digits}. Esperado 11 ou 14 dígitos.")

    return digits

def sanitize_folder_name(name: str) -> str:
    r"""
    Remove ou substitui caracteres inválidos para nomes de pasta no Windows.
    
    Caracteres inválidos no Windows: / \ : * ? " < > |
    Todos são substituídos por underscore (_).
    
    Args:
        name: Nome original da pasta
        
    Returns:
        Nome sanitizado seguro para uso como nome de pasta
        
    Examples:
        >>> sanitize_folder_name("EMPRESA S/A")
        'EMPRESA S_A'
        >>> sanitize_folder_name("ARQUIVO:TESTE")
        'ARQUIVO_TESTE'
    """
    if not name:
        return name
        
    # Lista de caracteres inválidos no Windows
    invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    
    # Substituir cada caractere inválido por underscore
    sanitized = name
    for char in invalid_chars:
        sanitized = sanitized.replace(char, '_')
    
    # Remover espaços extras nas extremidades
    sanitized = sanitized.strip()
    
    # Garantir que não termina com ponto ou espaço (também problemático no Windows)
    while sanitized and sanitized[-1] in ['.', ' ']:
        sanitized = sanitized[:-1]
    
    return sanitized

# pass # Remover o pass original se existir 
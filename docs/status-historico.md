# Status da Implementação - Download Incremental SIEG

## Objetivo Geral

Implementar um processo robusto e eficiente para download de XMLs (NFe, CTe) e eventos de cancelamento da API SIEG, utilizando uma abordagem incremental que prioriza downloads em lote e gerencia o estado entre execuções.

## Estado Atual (2024-05-30)

Paramos neste ponto após integrar a funcionalidade básica de **download em lote incremental** usando o `StateManager`.

**Implementado:**

1.  **Fluxo Principal:** A sequência `Download em Lote -> Download Relatório -> Cálculo Diff -> Download Individual` está implementada em `app/run.py`.
2.  **Download em Lote:**
    *   O código baixa XMLs principais (NFe/CTe para papéis Emitente, Destinatário, Tomador) usando `api_client.baixar_xmls` com paginação (`Take`/`Skip`).
    *   Eventos de cancelamento são baixados em lote usando a função auxiliar `_download_cancel_events` (baseada na lógica anterior do `downloader.py`) que chama `api_client.baixar_eventos`.
    *   Todos os itens do lote (XMLs + Eventos) são salvos usando `save_xmls_from_base64` de `core/file_manager.py`, que organiza nas pastas corretas (`ANO/EMPRESA/MES/TIPO/DIRECAO`).
3.  **Gerenciamento de Estado (`StateManager`):**
    *   O `StateManager` é instanciado e o estado (`state.json`) é carregado no início da execução.
    *   Para o download em lote dos **XMLs principais**, o `skip` inicial para cada combinação `(CNPJ, Mês, Tipo, Papel)` é lido do estado.
    *   O `skip` final atingido após o download da combinação é atualizado no estado.
    *   O estado completo (`state.json`) é salvo no disco ao final do processamento bem-sucedido de cada empresa.
4.  **Relatório e Diff:**
    *   O download do relatório (`api_client.baixar_relatorio_xml`) foi reintegrado.
    *   O cálculo do `diff` (`rpt_keys - loc_keys`) acontece *após* o salvamento do lote.
    *   A classificação de chaves faltantes (`classify_keys_by_role`) foi corrigida para receber o `doc_type` (NFe/CTe).
5.  **Download Individual:** Continua funcionando para buscar as chaves que *ainda* faltam após o lote e a verificação do relatório.
6.  **Correções:**
    *   O erro de parsing do XML individual (`b'"...'`) foi corrigido em `save_raw_xml`.

**Por que paramos aqui?**

Concluímos a integração da mecânica **fundamental** do download em lote incremental com persistência de estado (`skip`). Este é um marco funcional importante que permite ao processo retomar de onde parou. Antes de adicionar mais refinamentos (como a flag `--seed` ou o limiar para lote), é prudente testar e validar esta base.

## Próximos Passos Planejados

1.  **Testes:** Executar testes abrangentes para validar:
    *   O download em lote para diferentes papéis e tipos.
    *   A persistência e retomada correta do `skip` entre execuções.
    *   O cálculo do `diff` pós-lote.
    *   O download individual para as chaves remanescentes.
    *   O salvamento correto dos arquivos e a organização dos eventos.
2.  **Flag `--seed`:** Implementar um argumento de linha de comando (ex: `--seed`) que instrua o `StateManager` a ignorar o estado carregado e forçar `skip = 0` para todas as combinações, permitindo um reprocessamento completo quando necessário.
3.  **Estado para Eventos (Opcional):** Avaliar se o volume de eventos justifica adicionar a mesma lógica de `skip` persistido para a função `_download_cancel_events`. Atualmente, eventos são sempre baixados do início.
4.  **Limiar Lote vs. Individual (Reavaliar):** A necessidade de um `LIMIAR_LOTE` para decidir *antes* se faz o lote ou não diminui com o `skip` persistido. O lote incremental já baixa apenas o necessário. Podemos adiar ou remover essa complexidade, a menos que a chamada inicial para obter a contagem via API seja muito rápida e valha a pena.
5.  **Refinamento de Configuração:** Mover constantes como `ROLE_MAP`, `TAKE_LIMIT`, etc., de `app/run.py` para `core/config.py` para melhor organização.
6.  **Tratamento de Erros de Estado:** Melhorar a robustez em caso de falha ao carregar/salvar `state.json`.
7.  **Documentação Técnica:** Atualizar o arquivo `docs/technical_documentation.md` para refletir a nova arquitetura e fluxo incremental (conforme regra `update_documentation`). 
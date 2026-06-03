# FinanceMgmtBot

FinanceMgmtBot e uma solucao financeira inteligente para registrar, revisar e analisar a vida financeira sem transformar tudo em planilha, formulario ou lancamento manual. Ele combina conversa, audio, leitura de cupons, despesas recorrentes e painel administrativo em um fluxo unico, pensado para ser rapido no uso diario e confiavel quando o dado vira historico financeiro.

A proposta e simples: o usuario registra do jeito que a informacao aparece na vida real, e o sistema organiza isso com analise por IA, validacao deterministica e operacao auditavel. A IA ajuda a entender; o backend decide o que pode virar dado.

## Fluxo Do Sistema

O FinanceMgmtBot recebe texto, audio ou foto pelo canal conversacional, transforma a entrada em uma intencao financeira controlada e aplica regras locais antes de persistir qualquer coisa. Lancamentos simples entram direto; cupons e lotes passam por revisao; despesas recorrentes sao geradas automaticamente sem duplicidade; e o painel usa a mesma base para consulta, correcao, aprovacao e analytics.

## Solucoes do Sistema

- **Linguagem natural com controle de backend:** o usuario escreve como fala, a IA analisa a intencao e o backend limita o resultado a acoes conhecidas, estruturas previsiveis e regras financeiras deterministicas.
- **Texto, audio e foto no mesmo contrato financeiro:** independente da entrada, tudo converge para o mesmo pipeline de categorias, datas, valores, contas, filtros e validacoes.
- **Cupons Com Revisao:** fotos de cupons viram lotes revisaveis, com itens, descontos e pagamento organizados antes do salvamento final.
- **Despesas fixas sem duplicidade:** recorrencias sao geradas diariamente com idempotencia, evitando relancar a mesma conta ou assinatura.
- **Painel administrativo como camada de operacao:** aprovacoes, historico editavel, exclusoes seguras, recorrencias e consultas ficam em um painel unico para revisar e corrigir o que a conversa capturou.
- **Analytics e historico para leitura financeira real:** saldos, receitas, despesas, categorias, contas e periodos formam uma camada de analise para entender o dinheiro alem do registro bruto.

## Engenharia E Seguranca

- **Autoridade no backend:** operacoes financeiras passam por validacao server-side, contratos de dados e persistencia controlada antes de afetar o historico.
- **Seguranca operacional aplicada:** autenticacao validada no servidor, auditoria, logs sanitizados e rate limits protegem as superficies publicas e as acoes administrativas.
- **Qualidade acima do comum:** Pipeline de CI com testes, scans, verificacao de build e cobertura minima de 90% para manter a solucao confiavel conforme evolui.

## Para Quem Este Repositorio Foi Pensado

FinanceMgmtBot e um bom exemplo de produto pequeno com arquitetura de produto serio: entrada multimodal, IA sob controle, revisao humana onde faz sentido, recorrencias automatizadas, painel administrativo e uma base de engenharia que trata dado financeiro como coisa importante.

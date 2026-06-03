# AGENTS.md — Finance Mgmt Bot

## Acordos de trabalho

- Sempre siga o `architecture.md` na raiz do repositório.
- Se `architecture.md` não existir, crie-o antes de implementar qualquer mudança relevante e registre nele o manifesto arquitetural do projeto.
- Antes de alterar código, leia o `architecture.md` e respeite as decisões já documentadas.
- Sempre planeje antes de implementar funcionalidades grandes, refactors, mudanças de autenticação, segurança, banco, deploy, IA, integrações externas ou contratos entre frontend e backend.
- Escreva primeiro os testes e depois o código.
- Mantenha as alterações incrementais, pequenas e fáceis de revisar.
- Documente premissas quando houver ambiguidade técnica.
- Pare e peça validação no chat quando houver dúvida de escopo, regra de negócio financeira, segurança, autenticação, autorização, dados sensíveis ou comportamento esperado.
- Prefira soluções confiáveis, simples, determinísticas e testáveis em vez de soluções “espertas” demais.
- Priorize clean code: nomes claros, funções curtas, baixo acoplamento, alta coesão e eliminação de duplicação acidental.
- Preserve a arquitetura definida em `architecture.md`; não altere fronteiras, responsabilidades ou fluxos críticos sem atualizar a documentação correspondente.
- Nunca faça commit, push, merge, deploy, publicação, migração remota ou geração de artefatos automaticamente.
- No final de alterações no código, sempre pergunte se desejo que você faça o commit, rode build/deploy ou gere artefatos.

---

## Regra rígida de TDD

Para qualquer nova funcionalidade, correção de bug, alteração de comportamento, regra financeira, autenticação, autorização, segurança, persistência, integração externa ou refactor com risco funcional, siga obrigatoriamente este ciclo:

1. Escrever o teste que descreve o comportamento esperado.
2. Confirmar que o teste falha pelo motivo correto.
3. Implementar o mínimo de código necessário para o teste passar.
4. Rodar os testes novos.
5. Rodar os testes regressivos relevantes.
6. Refatorar se necessário, mantendo os testes passando.

Nunca escreva código de produção sem teste correspondente quando o comportamento for novo ou alterado.

Para features novas, crie o arquivo de teste antes de criar o arquivo de código de produção.

---

## Obrigatório: uso cuidadoso de recursos locais

- Sempre evite paralelismo e tarefas muito pesadas.
- O computador pode travar; execute tarefas pesadas uma de cada vez.
- Não rode builds, testes completos, audits, servidores ou E2E em paralelo.
- Prefira começar por testes específicos da área alterada.
- Rode gates completos somente quando necessário ou ao finalizar uma mudança relevante.
- Não deixe watchers, servidores locais ou processos em background rodando sem necessidade.
- Finalize processos locais iniciados para teste quando eles não forem mais necessários.

---

## Prioridades do produto

1. Segurança de dados financeiros e credenciais.
2. Confiabilidade do registro financeiro.
4. Determinismo das regras financeiras.
5. Utilidade dos analytics e do painel administrativo.
6. Clareza da UX para operação financeira.
7. Baixo custo operacional.
8. Manutenibilidade do projeto.

---

## Padrões técnicos esperados

- TypeScript em modo strict.
- Código Python simples, testável e com responsabilidades claras.
- Componentes pequenos e reutilizáveis.
- Modelos de domínio claros.
- Regras financeiras determinísticas e cobertas por testes.
- Integrações externas isoladas por fronteiras testáveis.
- Feature flags para itens incertos, experimentais ou dependentes de integração externa.
- Mocks, fakes ou fixtures em testes unitários; não faça chamadas reais para serviços externos em testes unitários.
- Não mova lógica privilegiada, segredos ou validações autoritativas para o frontend.
- Não altere contratos públicos, autenticação, banco, deploy ou integrações sem consultar e atualizar `architecture.md`.

---

## Segurança e dados sensíveis

- Nunca exponha, versione ou registre segredos.
- Nunca coloque tokens reais, chaves privadas, JWTs reais, refresh tokens, access tokens, service role, dumps de banco ou dados financeiros sensíveis em código, logs, testes ou documentação.
- Nunca registre payloads completos de IA, transcrições completas, cupons completos, dados financeiros brutos ou respostas cruas de provedores.
- Use fixtures sintéticas e seguras.
- Logs devem ser úteis para diagnóstico, mas sanitizados.
- Erros exibidos ao usuário ou retornados por API não devem vazar stack trace, SQL, tokens, dados pessoais, detalhes internos de provedores ou mensagens cruas sensíveis.
- Antes de concluir mudanças com risco de exposição, rode os checks de segurança disponíveis no projeto.

---

## IA e automação

- Modelos de IA são auxiliares, não fonte de verdade.
- Não delegue a IA decisões finais de regra financeira, autorização, persistência, datas, valores, categorias ou permissões.
- Qualquer mudança em prompts, schemas, parsing, OCR, STT, fallback ou roteamento de intenção exige testes regressivos.
- Não adicione novo provedor externo sem instrução explícita do usuário.
- Não faça ações destrutivas ou irreversíveis sem confirmação explícita.

---

## Testes, lint e gates

Rode comandos de forma incremental e sem paralelismo.

Quando disponíveis, use os comandos já definidos no projeto, como:

```bash
make test-backend-coverage
npm run test:coverage
npm run build
npm run verify:build-env
npm run verify:pages-fallback
npm run verify:bundle
npm run test:e2e
make pre-push
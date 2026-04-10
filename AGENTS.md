# Projeto: Finance Mgmt Bot

## Regras permanentes
1. Sempre siga o `architecture.md` deste repositório. Se ele não existir, pare e peça orientação.
2. Faça apenas alterações aprovadas via chat e pare se houver dúvida real de escopo, contrato ou impacto.
3. Nunca faça commit sem permissão explícita do usuário.

## Como investigar e decidir
4. Em bugs ou mudanças que envolvam serviços externos, SDKs, autenticação, autorização, sessão, cookies, browser storage, CORS, deploy, CI, CDN, Pages, Cloud Run ou contratos públicos, consulte primeiro documentação oficial e use fontes primárias antes de propor arquitetura ou implementar correções.
5. Antes de alterar fluxos críticos, defina explicitamente qual é o fluxo canônico, qual é a fonte de verdade do estado e onde ficam as fronteiras entre autenticação, autorização, compatibilidade e observabilidade.
6. Prefira a menor correção compatível com o fluxo oficial antes de propor refactor amplo, hardening adicional ou mudança operacional.
7. Não misture no mesmo pacote correção de bug, refactor estrutural, hardening e mudança operacional, salvo quando isso for estritamente necessário para o comportamento funcionar com segurança.
8. Em integrações críticas, trate código legado, fallbacks e compatibilidades como temporários por padrão: só mantenha o que tiver motivo explícito, cobertura de teste e condição clara de remoção.
9. Evite criar pendências operacionais manuais recorrentes. Se uma solução exigir sincronização manual frequente entre serviços, considere-a inadequada por padrão e prefira desenho mais simples, automatizável ou alinhado ao fluxo oficial.

## Testes e validação
10. Para novos desenvolvimentos e correções, escreva ou atualize primeiro os testes que comprovam o comportamento esperado e evitam regressão.
11. Em fluxos críticos, priorize testes de contrato e regressão do comportamento final antes de expandir o código.
12. Após implementar, rode imediatamente os testes novos e os regressivos relevantes até tudo passar.
13. Em mudanças de frontend, build, CI, deploy, segurança ou contrato público, rode também as validações específicas afetadas, incluindo build de produção, verificações de bundle, fallback/static hosting e demais checks de publicação quando existirem.
14. Se algum teste ou validação relevante não puder ser executado, pare e reporte isso explicitamente antes de seguir para commit.

## Documentação e contrato do sistema
15. Depois de concluir o código, atualize o `architecture.md` quando a mudança alterar comportamento, fluxo, segurança, deploy, contratos, compatibilidade ou operação.
16. Em mudanças que afetem publicação pública, CI, bundles do frontend, GitHub Pages, Cloud Run, envs ou workflows, revise também exemplos de ambiente, artefatos gerados e pipelines para garantir que o contrato novo está refletido de ponta a ponta e que nenhum fluxo legado inseguro continue publicado.

## Segurança e publicação
17. Antes de todo commit, faça uma revisão explícita de exposição de dados no diff e nos artefatos envolvidos.
18. Essa revisão deve procurar e bloquear credenciais, tokens, chaves, `.env`, logs, relatórios internos, payloads sensíveis, URLs operacionais desnecessárias, e-mails pessoais, project refs e qualquer material reaproveitável ou sensível.
19. Antes de todo commit, rode também uma checagem local de secret scanning equivalente ao job `repo-security`. Neste repositório, use `make audit-repo-security` quando `gitleaks` estiver disponível localmente.
20. Se `gitleaks` local não estiver disponível, pare e reporte isso explicitamente antes do commit; não ignore essa ausência nem prossiga confiando apenas na revisão manual.
21. Fixtures de teste que precisem simular JWTs, chaves, tokens, URLs operacionais ou padrões sensíveis não podem aparecer como literais completos no source. Monte esses valores por fragmentos, helpers ou dummies que não acionem scanners.

## Gates locais obrigatórios
22. Antes de todo push, rode o gate agregado local. Neste repositório, use `make pre-push` como padrão.
23. Em mudanças de auth, frontend, CI, build, deploy, contrato público ou segurança, rode `make pre-push-full` antes do push.
24. Se a mudança tocar dependências ou publicação, rode também `make audit-backend-deps` e `make audit-frontend-deps`.

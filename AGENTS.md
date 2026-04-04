# Projeto: Finance Mgmt Bot

1. Sempre siga o `architecture.md` deste repositório. Se ele não existir, pare e peça orientação.
2. Para novos desenvolvimentos e correções, escreva ou atualize primeiro os testes que comprovam o comportamento esperado e evitam regressão.
3. Após implementar, rode imediatamente os testes novos e os regressivos relevantes até tudo passar.
4. Em mudanças de frontend, build, CI, deploy ou contrato público, rode também as validações específicas afetadas, incluindo build de produção, verificações de bundle e demais checks de publicação quando existirem.
5. Se algum teste ou validação relevante não puder ser executado, pare e reporte isso explicitamente antes de seguir para commit.
6. Faça apenas alterações aprovadas via chat e pare se houver dúvida de escopo.
7. Depois de concluir o código, atualize o `architecture.md` do repositório quando a mudança alterar comportamento, fluxo, segurança, deploy, contratos ou operação.
8. Antes de todo commit, faça uma revisão explícita de exposição de dados no diff e nos artefatos envolvidos.
9. Essa revisão deve procurar e bloquear credenciais, tokens, chaves, `.env`, logs, relatórios internos, payloads sensíveis, URLs operacionais desnecessárias, e-mails pessoais, project refs e qualquer material reaproveitável ou sensível.
10. Em mudanças que afetem publicação pública, CI, Pages, Cloud Run ou bundles do frontend, revise também workflows, exemplos de ambiente e artefatos gerados para garantir que nenhum segredo, fluxo legado inseguro ou dado operacional volte a ser publicado.
11. Nunca faça commit sem permissão explícita do usuário.

alter table public.despesas_recorrentes
    drop column if exists descricao;

comment on table public.despesas_recorrentes is
'Recurring expenses registry. Each active entry for a given month and day generates a gasto record whose descricao is the recurring expense nome.';

notify pgrst, 'reload schema';

import calendar
from datetime import datetime, timedelta

CATEGORIA_MAP = {
    "moradia": ("Essencial", "Moradia"), 
    "mercado": ("Essencial", "Mercado"), 
    "transporte": ("Essencial", "Transporte"),
    "saúde": ("Essencial", "Saúde"), 
    "educação": ("Essencial", "Educação"), 
    "contas fixas": ("Essencial", "Contas Fixas"),
    "cuidados pessoais": ("Essencial", "Cuidados Pessoais"),
    "bares e restaurantes": ("Lazer", "Bares e Restaurantes"), 
    "delivery e fast food": ("Lazer", "Delivery e Fast Food"), 
    "bebidas alcoólicas": ("Lazer", "Bebidas Alcoólicas"), 
    "viagens": ("Lazer", "Viagens"), 
    "diversão": ("Lazer", "Diversão"), 
    "vestuário": ("Lazer", "Vestuário"),
    "salário": ("Receita", "Salário"), 
    "investimentos": ("Receita", "Investimentos"), 
    "cashback": ("Receita", "Cashback"), 
    "entradas diversas": ("Receita", "Entradas Diversas"),
    "receita": ("Receita", "Entradas Diversas"),
    "ganho": ("Receita", "Entradas Diversas"),
    "gasto": ("Outros", "Outros"),
    "despesa": ("Outros", "Outros"),
    "outros": ("Outros", "Outros"),
}

def inferir_natureza(categoria):
    if not categoria or not isinstance(categoria, str):
        return "Outros", "Outros"
    chave_busca = categoria.strip().lower()
    if chave_busca not in CATEGORIA_MAP:
        return "Outros", "Outros"
    return CATEGORIA_MAP[chave_busca]

def get_brasilia_time():
    return datetime.utcnow() - timedelta(hours=3)

def add_months_safely(sourcedate, months):
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return sourcedate.replace(year=year, month=month, day=day)

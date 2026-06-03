from datetime import datetime, timedelta

from domain.finance import CATEGORY_NATURE_MAP as CATEGORIA_MAP
from domain.finance import add_months_safely, infer_transaction_nature

def inferir_natureza(categoria):
    return infer_transaction_nature(categoria)

def get_brasilia_time():
    return datetime.utcnow() - timedelta(hours=3)

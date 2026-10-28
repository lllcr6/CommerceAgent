"""Demo product identities/specs come from the same document as RAG.

Prices and stock below are explicit simulated offers, not real store data.
Models without an offer expose unknown price/stock instead of invented values.
"""

from dataclasses import dataclass
from functools import lru_cache
import re

from app.paths import KNOWLEDGE_DIR


SPEC_FILE = KNOWLEDGE_DIR / 'product-specs.md'
_HEADING = re.compile(r'^##\s+(.+?)\s*[(（](?:Model|型号)\s+([A-Z0-9-]+)[)）]\s*$', re.M)
# Fictional U.S. demo prices, explicitly set in USD (not an FX conversion).
DEMO_OFFERS = {'MH-LP100': {'price':499,'stock':20,'currency':'USD'}, 'MH-W20': {'price':39,'stock':50,'currency':'USD'}}
ORDER_MODELS = {'1001':'MH-LP100', '2002':'MH-W20'}
LEGACY_PRODUCT = '猫粮 5kg'

@dataclass(frozen=True)
class Product:
    name: str
    model: str
    spec: str

    @property
    def order_name(self):
        return f'{self.name} ({self.model})'

    def view(self):
        offer=DEMO_OFFERS.get(self.model,{})
        return {'product_name':self.name,'model':self.model,'price':offer.get('price'),
                'stock':offer.get('stock'),'currency':offer.get('currency'),'spec':self.spec,'is_demo':True,
                'source':'data/rag/knowledge/product-specs.md'}

@lru_cache(maxsize=2)
def _load_catalog(stamp):
    text=SPEC_FILE.read_text(encoding='utf-8')
    headings=list(_HEADING.finditer(text))
    products=[]
    for i,match in enumerate(headings):
        end=headings[i+1].start() if i+1<len(headings) else len(text)
        products.append(Product(match[1].strip(),match[2],text[match.end():end].strip()))
    return tuple(products)

def catalog():
    return _load_catalog(SPEC_FILE.stat().st_mtime_ns)

def demo_order_item(suffix):
    model=ORDER_MODELS[suffix]
    product=next((p for p in catalog() if p.model==model),None)
    if not product:
        raise ValueError(f'Demo order model {model} is missing from the product specification catalog')
    return {'product':product.order_name,'amount':DEMO_OFFERS[model]['price'],'currency':DEMO_OFFERS[model]['currency']}

def find_products(query):
    value=query.strip().casefold()
    if not value:return []
    products=catalog()
    exact=[p for p in products if value in (p.model.casefold(),p.name.casefold(),p.order_name.casefold())]
    return exact or [p for p in products if value in p.name.casefold() or value in p.model.casefold()]

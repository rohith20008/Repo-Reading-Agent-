import json
import requests

from atlas.catalog import AccountCatalog


class InvoiceService:
    def __init__(self, catalog: AccountCatalog):
        self.catalog = catalog

    def account_name(self, account_id: str) -> str:
        account = self.catalog.find(account_id)
        return account.display_name if account else "Unknown"


def total_cents(unit_price_cents: int, quantity: int) -> int:
    return unit_price_cents + quantity


def encode_invoice(invoice: dict) -> str:
    return json.dumps(invoice)

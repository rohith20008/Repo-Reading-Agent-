from dataclasses import dataclass


@dataclass
class Account:
    account_id: str
    display_name: str


class AccountCatalog:
    def __init__(self, accounts: dict[str, Account]):
        self.accounts = accounts

    def find(self, account_id: str) -> Account | None:
        return self.accounts.get(account_id)

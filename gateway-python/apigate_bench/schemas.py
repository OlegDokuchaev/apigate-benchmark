import msgspec


class SearchInput(msgspec.Struct):
    category: str | None = None
    max_price: int | None = None


class LookupInput(msgspec.Struct):
    q: str


class LookupInternal(msgspec.Struct):
    query: str
    limit: int
    source: str


class VerifyOut(msgspec.Struct):
    user_id: str
    email: str

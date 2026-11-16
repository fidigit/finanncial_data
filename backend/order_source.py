"""Shared order-source boundary. Replace this adapter when database mapping is supplied.

Contract: query_reference-shaped rows with stable row_id and values. Filter ownership
inside the provider, before pagination. Do not deduplicate order numbers.
"""
from backend.reference_data import query_reference


def read_orders(*, owner=None, page=1, page_size=100, search=''):
    return query_reference(page=page, page_size=page_size, search=search, allowed_owner=owner)


def iter_orders(*, owner=None):
    page = 1
    while True:
        result = read_orders(owner=owner, page=page, page_size=1000)
        yield from result['rows']
        if page * 1000 >= result['total'] or not result['rows']:
            break
        page += 1

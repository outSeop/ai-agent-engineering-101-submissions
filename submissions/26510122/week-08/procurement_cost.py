"""Worst-case new-lot reservations, including the market's maximum supply surge."""
import math
BASE_MAX_COST_SHARE = .75
MAX_SUPPLY_SURGE = 1.5

def ceiling(product):
    price = product.get('list_price')
    if type(price) is not int or price <= 0:
        raise ValueError('invalid catalog list price')
    return math.ceil(price * BASE_MAX_COST_SHARE * MAX_SUPPLY_SURGE)

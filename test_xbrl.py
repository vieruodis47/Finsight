import requests
import json
from datetime import datetime

headers = {"User-Agent": "Michelle yourname@email.com"}

COMPANIES = {
    "GAP": "0000039911",
    "PVH": "0000078239",
    "AEO": "0000919012"
}

def get_company_facts(cik):
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    response = requests.get(url, headers=headers)
    return response.json()

def extract_annual_field(data, field_name):
    """
    Extract clean annual (10-K) values for a given us-gaap field.
    Returns a dict: {fiscal_year_end: value}
    """
    if field_name not in data['facts']['us-gaap']:
        return {}

    usd_data = data['facts']['us-gaap'][field_name]['units']['USD']

    annual = []
    for entry in usd_data:
        if entry['form'] != '10-K':
            continue
        start = datetime.strptime(entry['start'], '%Y-%m-%d')
        end = datetime.strptime(entry['end'], '%Y-%m-%d')
        duration_days = (end - start).days
        if 360 <= duration_days <= 372:
            annual.append(entry)

    by_end = {}
    for entry in annual:
        key = entry['end']
        if key not in by_end or entry['filed'] > by_end[key]['filed']:
            by_end[key] = entry

    return {k: v['val'] for k, v in sorted(by_end.items())}

def extract_instant_field(data, field_name):
    """
    Extract clean annual (10-K) values for point-in-time fields
    (e.g. Inventory, Total Assets, Debt — measured on one date, not over a period)
    Returns a dict: {fiscal_year_end: value}
    """
    if field_name not in data['facts']['us-gaap']:
        return {}

    usd_data = data['facts']['us-gaap'][field_name]['units']['USD']

    annual = [entry for entry in usd_data if entry['form'] == '10-K']

    by_end = {}
    for entry in annual:
        key = entry['end']
        if key not in by_end or entry['filed'] > by_end[key]['filed']:
            by_end[key] = entry

    return {k: v['val'] for k, v in sorted(by_end.items())}


data = get_company_facts(COMPANIES["GAP"])

revenue = extract_annual_field(data, "Revenues")
print("Revenue:")
for year, val in revenue.items():
    print(f"  {year}: ${val:,}")

inventory = extract_instant_field(data, "InventoryFinishedGoodsNetOfReserves")
print("\nInventory:")
for year, val in inventory.items():
    print(f"  {year}: ${val:,}")

all_fields = list(data['facts']['us-gaap'].keys())
inventory_fields = [f for f in all_fields if 'inventory' in f.lower()]
print("\nInventory-related fields found:")
for f in inventory_fields:
    print(f)



inventory = extract_instant_field(data, "InventoryFinishedGoodsNetOfReserves")
print("\nInventory:")
for year, val in inventory.items():
    print(f"  {year}: ${val:,}")

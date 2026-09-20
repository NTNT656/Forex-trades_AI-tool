import os
import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Supabase credentials missing!")

# Ensure URL ends with /rest/v1/
if not SUPABASE_URL.endswith('/'):
    SUPABASE_URL += '/'
if 'rest/v1' not in SUPABASE_URL:
    SUPABASE_URL = SUPABASE_URL.rstrip('/') + '/rest/v1/'

def supabase_get(endpoint):
    url = SUPABASE_URL + endpoint
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json"
    }
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        return True, resp.json()
    else:
        return False, f"HTTP {resp.status_code}: {resp.text}"

# Fetch pending trades (result = 'pending')
ok, rows = supabase_get('trades?result=eq.pending')
if not ok:
    print("Error fetching trades:", rows)
    exit()

print(f"Found {len(rows)} pending trade(s)\n")

# A simplified version of compute_profit that shows the issue
def test_compute_profit(entry, exit_price, pair, volume):
    print(f"  -> Received volume: {volume} (type: {type(volume)})")
    # Ensure volume is a valid float
    if volume is None:
        volume = 0.01
    try:
        volume = float(volume)
    except (TypeError, ValueError):
        volume = 0.01

    # Use pip-based calculation (no MT4 connection needed)
    if pair.endswith('JPY'):
        pip_size = 0.01
    else:
        pip_size = 0.0001
    pips = (exit_price - entry) / pip_size
    profit = pips * 10.0 * volume
    return profit

for trade in rows:
    print(f"Trade ID: {trade.get('id')}, Pair: {trade.get('pair')}")
    entry = trade.get('entry_price')
    price = 1.1000  # dummy current price for testing
    pair = trade.get('pair')
    volume = trade.get('volume')  # this may be None
    
    print(f"  entry: {entry}, volume from DB: {volume}")
    profit = test_compute_profit(entry, price, pair, volume)
    print(f"  computed profit (dummy): {profit:.2f}\n")
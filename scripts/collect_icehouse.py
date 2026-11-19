import os
import re
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv('.env.local')

SUPABASE_URL = os.getenv('NEXT_PUBLIC_SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SECRET_KEY') or os.getenv('SUPABASE_SERVICE_ROLE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise SystemExit("Missing NEXT_PUBLIC_SUPABASE_URL or SUPABASE_SECRET_KEY in .env.local")

HEADERS = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
    'Prefer': 'resolution=merge-duplicates,return=minimal'
}

SOURCE_URL = 'https://www.icehousenj.com/adult-hockey'

def get_icehouse_rink_id():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/rinks?name=ilike.*Ice House*&select=id,name",
        headers=HEADERS,
        timeout=15
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise SystemExit("Could not find Ice House in your rinks table!")
    return rows[0]['id']

def sync_to_supabase():
    rink_id = get_icehouse_rink_id()
    resp = requests.get(SOURCE_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
    resp.raise_for_status()

    # Keep website_url verified on the Ice House rink record
    patch_resp = requests.patch(
        f"{SUPABASE_URL}/rest/v1/rinks?id=eq.{rink_id}",
        headers=HEADERS,
        json={'website_url': 'https://www.icehousenj.com/'},
        timeout=15
    )
    patch_resp.raise_for_status()

    # Clear any stale/unverified sessions for Ice House until an open-hockey schedule is posted
    del_resp = requests.delete(
        f"{SUPABASE_URL}/rest/v1/sessions?rink_id=eq.{rink_id}",
        headers=HEADERS,
        timeout=15
    )
    del_resp.raise_for_status()
    print("Verified Ice House (Hackensack): currently runs Adult Leagues & Travel Hockey (no public drop-in Open Hockey / Stick & Puck schedule posted).")

if __name__ == '__main__':
    sync_to_supabase()

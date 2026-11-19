import os
import re
import json
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

SOURCE_URL = 'https://openhockeycalendar.com/hockey/nj/bridgewater'
BOOKING_URL = 'https://www.bsaarena.com/'

def get_bridgewater_rink_id():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/rinks?name=ilike.*Bridgewater*&select=id,name",
        headers=HEADERS,
        timeout=15
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise SystemExit("Could not find Bridgewater Sports Arena in your rinks table!")
    return rows[0]['id']

def fetch_bridgewater_events():
    resp = requests.get(SOURCE_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
    resp.raise_for_status()
    match = re.search(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*data-seo-events[^>]*>(.*?)</script>',
        resp.text,
        re.S
    )
    if not match:
        raise SystemExit("Failed to parse JSON-LD script block for Bridgewater.")

    raw_events = json.loads(match.group(1))
    eastern = ZoneInfo('America/New_York')
    now_et = datetime.now(eastern)
    today_str = now_et.strftime('%Y-%m-%d')
    max_date_str = (now_et + timedelta(days=14)).strftime('%Y-%m-%d')

    events = {}
    for ev in raw_events:
        raw_name = str(ev.get('name', '')).strip()
        start_iso = str(ev.get('startDate', '')).strip()
        end_iso = str(ev.get('endDate', '')).strip()
        if not raw_name or len(start_iso) < 16 or len(end_iso) < 16:
            continue

        session_date = start_iso[:10]
        if session_date < today_str or session_date > max_date_str:
            continue

        start_time = start_iso[11:19] if len(start_iso) >= 19 else start_iso[11:16] + ':00'
        end_time = end_iso[11:19] if len(end_iso) >= 19 else end_iso[11:16] + ':00'
        clean_title = re.sub(r'\s+', ' ', raw_name).strip()
        lower_name = clean_title.lower()
        session_type = 'Stick Time' if ('stick' in lower_name or 'puck' in lower_name) else 'Open Hockey'

        offers = ev.get('offers') or {}
        price_val = offers.get('price') if isinstance(offers, dict) else None
        cost = float(price_val) if price_val not in (None, '') else None
        cost_notes = f"${cost:.0f} walk-in / online" if cost is not None else "Confirm rate at rink"

        slug = re.sub(r'[^a-z0-9]+', '-', lower_name).strip('-')
        fingerprint = f"ohc-bridgewater-{session_date}-{start_time[:5]}-{slug}"

        events[fingerprint] = {
            'unique_fingerprint': fingerprint,
            'session_type': session_type,
            'title': clean_title,
            'session_date': session_date,
            'start_time': start_time,
            'end_time': end_time,
            'cost': cost,
            'cost_notes': cost_notes,
            'registration_required': False,
            'availability_status': 'open',
            'booking_url': ev.get('url') or BOOKING_URL,
            'source_url': SOURCE_URL,
            'is_verified': True,
            'last_verified_at': datetime.now(eastern).isoformat()
        }

    return sorted(events.values(), key=lambda x: (x['session_date'], x['start_time']))

def sync_to_supabase():
    rink_id = get_bridgewater_rink_id()
    sessions = fetch_bridgewater_events()
    print(f"Found {len(sessions)} upcoming sessions for Bridgewater Sports Arena:")

    for s in sessions:
        print(f"  -> {s['session_date']} | {s['start_time']} - {s['end_time']} | {s['session_type']} | {s['title']}")

    if not sessions:
        return

    del_resp = requests.delete(
        f"{SUPABASE_URL}/rest/v1/sessions?rink_id=eq.{rink_id}",
        headers=HEADERS,
        timeout=15
    )
    del_resp.raise_for_status()

    for s in sessions:
        s['rink_id'] = rink_id

    upsert_resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/sessions?on_conflict=unique_fingerprint",
        headers=HEADERS,
        json=sessions,
        timeout=20
    )
    if not upsert_resp.ok:
        print("Supabase error:", upsert_resp.status_code, upsert_resp.text)
        upsert_resp.raise_for_status()

    print("Successfully synced Bridgewater Sports Arena live schedule to Supabase!")

if __name__ == '__main__':
    sync_to_supabase()

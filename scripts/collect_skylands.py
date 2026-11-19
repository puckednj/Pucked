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

SOURCE_URL = 'https://skylandsstats.com/rink-schedule/embed'
BOOKING_URL = 'https://www.skylandsiceworldnj.com/hockey'

def get_skylands_rink_id():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/rinks?name=ilike.*Skylands*&select=id,name",
        headers=HEADERS,
        timeout=15
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise SystemExit("Could not find Skylands Ice World in your rinks table!")
    return rows[0]['id']

def to_24h(time_str):
    dt = datetime.strptime(time_str.strip(), '%I:%M %p')
    return dt.strftime('%H:%M:%S')

def fetch_skylands_events():
    resp = requests.get(SOURCE_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
    resp.raise_for_status()
    unescaped = resp.text.replace('\\"', '"')

    pattern = re.compile(
        r'\{"id":"(rink-[^"]+)","date":"(\d{4}-\d{2}-\d{2})","rink":"([^"]+)","name":"([^"]+)","starts":"([^"]+)","ends":"([^"]+)"[^}]*"cancelled":(true|false)'
    )

    eastern = ZoneInfo('America/New_York')
    now_et = datetime.now(eastern)
    today_str = now_et.strftime('%Y-%m-%d')
    max_date_str = (now_et + timedelta(days=14)).strftime('%Y-%m-%d')

    events = {}
    for m in pattern.finditer(unescaped):
        ev_id, session_date, rink_surface, raw_name, starts, ends, cancelled = m.groups()
        if cancelled == 'true':
            continue
        if session_date < today_str or session_date > max_date_str:
            continue

        lower_name = raw_name.lower()
        is_stick = ('stick' in lower_name and ' vs ' not in lower_name)
        is_open = ('open hockey' in lower_name or 'pickup' in lower_name or 'drop-in' in lower_name)
        if not (is_stick or is_open):
            continue

        session_type = 'Stick Time' if is_stick else 'Open Hockey'
        fingerprint = f"skylands-{ev_id}"
        events[fingerprint] = {
            'unique_fingerprint': fingerprint,
            'session_type': session_type,
            'title': raw_name.strip(),
            'session_date': session_date,
            'start_time': to_24h(starts),
            'end_time': to_24h(ends),
            'cost': None,
            'cost_notes': f"Check in at Front Desk ({rink_surface} Rink)",
            'registration_required': False,
            'availability_status': 'open',
            'booking_url': BOOKING_URL,
            'source_url': SOURCE_URL,
            'is_verified': True,
            'last_verified_at': datetime.now(eastern).isoformat()
        }

    return sorted(events.values(), key=lambda x: (x['session_date'], x['start_time']))

def sync_to_supabase():
    rink_id = get_skylands_rink_id()
    sessions = fetch_skylands_events()
    print(f"Found {len(sessions)} upcoming sessions for Skylands Ice World:")

    for s in sessions:
        print(f"  -> {s['session_date']} | {s['start_time']} - {s['end_time']} | {s['session_type']} | {s['title']} | {s['cost_notes']}")

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

    print("Successfully synced Skylands Ice World live schedule to Supabase!")

if __name__ == '__main__':
    sync_to_supabase()

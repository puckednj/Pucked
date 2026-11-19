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

SOURCE_URL = 'https://reservations.essexcountyparks.org/Info.aspx?EventID=23'
BOOKING_URL = 'https://reservations.essexcountyparks.org/info.aspx?ActivityID=218'

def get_codey_rink_id():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/rinks?name=ilike.*Codey*&select=id,name",
        headers=HEADERS,
        timeout=15
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise SystemExit("Could not find Richard J. Codey Arena in your rinks table!")
    return rows[0]['id']

def parse_time_12h(t_str):
    t_clean = re.sub(r'\s+', ' ', t_str.strip()).upper()
    dt = datetime.strptime(t_clean, '%I:%M %p')
    return dt.strftime('%H:%M:%S')

def fetch_codey_events():
    req_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }
    resp = requests.get(BOOKING_URL, headers=req_headers, timeout=20)
    resp.raise_for_status()
    html = resp.text

    eastern = ZoneInfo('America/New_York')
    now_et = datetime.now(eastern)
    today_str = now_et.strftime('%Y-%m-%d')
    max_date_str = (now_et + timedelta(days=21)).strftime('%Y-%m-%d')

    events = {}
    # Match any table rows containing a date (MM/DD/YYYY) and time range (HH:MM AM/PM - HH:MM AM/PM)
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S | re.I)
    for row in rows:
        text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', row)).strip()
        d_m = re.search(r'(\d{1,2}/\d{1,2}/202\d)', text)
        t_m = re.search(r'(\d{1,2}:\d{2}\s*[AP]M)\s*-\s*(\d{1,2}:\d{2}\s*[AP]M)', text, re.I)
        if not d_m or not t_m:
            continue

        session_date = datetime.strptime(d_m.group(1), '%m/%d/%Y').strftime('%Y-%m-%d')
        if session_date < today_str or session_date > max_date_str:
            continue

        start_time = parse_time_12h(t_m.group(1))
        end_time = parse_time_12h(t_m.group(2))

        lower_text = text.lower()
        if 'open hockey' in lower_text:
            session_type = 'Open Hockey'
            title = 'Adult Open Hockey'
        else:
            session_type = 'Stick & Puck'
            title = 'Family Stick & Puck'

        is_sold_out = 'sold out' in lower_text or 'full' in lower_text
        avail = 'full' if is_sold_out else 'open'
        status_note = 'Sold Out' if is_sold_out else 'Online reservation required'

        slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
        fingerprint = f"codey-essex-{session_date}-{start_time[:5]}-{slug}"

        events[fingerprint] = {
            'unique_fingerprint': fingerprint,
            'session_type': session_type,
            'title': title,
            'session_date': session_date,
            'start_time': start_time,
            'end_time': end_time,
            'cost': 20.0,
            'cost_notes': f"$20/skater ({status_note})",
            'registration_required': True,
            'availability_status': avail,
            'booking_url': BOOKING_URL,
            'source_url': SOURCE_URL,
            'is_verified': True,
            'last_verified_at': now_et.isoformat()
        }

    return sorted(events.values(), key=lambda x: (x['session_date'], x['start_time']))

def sync_to_supabase():
    rink_id = get_codey_rink_id()
    sessions = fetch_codey_events()
    print(f"Found {len(sessions)} upcoming open sessions for Richard J. Codey Arena (EventID=23 / ActivityID=218).")

    del_resp = requests.delete(
        f"{SUPABASE_URL}/rest/v1/sessions?rink_id=eq.{rink_id}",
        headers=HEADERS,
        timeout=15
    )
    del_resp.raise_for_status()

    if not sessions:
        print("  -> No open Stick & Puck / Open Hockey slots currently listed (currently Sold Out on Essex County Parks portal).")
        return

    for s in sessions:
        s['rink_id'] = rink_id

    upsert_resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/sessions?on_conflict=unique_fingerprint",
        headers=HEADERS,
        json=sessions,
        timeout=20
    )
    upsert_resp.raise_for_status()
    print("Successfully synced Richard J. Codey Arena live schedule to Supabase!")

if __name__ == '__main__':
    sync_to_supabase()

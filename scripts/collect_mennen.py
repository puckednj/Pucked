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

SOURCE_URL = 'https://register1.vermontsystems.com/wbwsc/njmorriscounty.wsc/search.html?module=AR&display=calendar&type=Hockey&category=MENN'
BOOKING_URL = SOURCE_URL

def get_mennen_rink_id():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/rinks?name=ilike.*Mennen*&select=id,name",
        headers=HEADERS,
        timeout=15
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise SystemExit("Could not find Mennen Sports Arena in your rinks table!")
    return rows[0]['id']

def parse_time_12h(t_str):
    t_clean = re.sub(r'\s+', ' ', t_str.strip()).upper()
    dt = datetime.strptime(t_clean, '%I:%M %p')
    return dt.strftime('%H:%M:%S')

def fetch_mennen_events():
    resp = requests.get(SOURCE_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
    resp.raise_for_status()
    html = resp.text

    eastern = ZoneInfo('America/New_York')
    now_et = datetime.now(eastern)
    today_str = now_et.strftime('%Y-%m-%d')
    max_date_str = (now_et + timedelta(days=21)).strftime('%Y-%m-%d')

    events = {}
    day_blocks = re.findall(
        r'<td[^>]*class="[^"]*calendar__day[^"]*"[^>]*>(.*?)</td>',
        html,
        re.S
    )

    for block in day_blocks:
        date_m = re.search(r'aria-label="Date:\s*(\d{2}/\d{2}/\d{4})"', block)
        if not date_m:
            continue
        session_date = datetime.strptime(date_m.group(1), '%m/%d/%Y').strftime('%Y-%m-%d')
        if session_date < today_str or session_date > max_date_str:
            continue

        items = re.findall(r'<li[^>]*>(.*?)</li>', block, re.S)
        for li in items:
            item_id_m = re.search(r'data-state-item="(\d+)"', li)
            item_id = item_id_m.group(1) if item_id_m else ''

            a_m = re.search(r'<a[^>]*>(.*?)</a>', li, re.S)
            inner = a_m.group(1) if a_m else li
            parts = [
                re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', p)).strip()
                for p in re.split(r'<br\s*/?>', inner, flags=re.I)
            ]
            parts = [p for p in parts if p]
            if len(parts) < 2:
                continue

            raw_title = parts[0].replace('&amp;', '&').strip()
            time_range = parts[1]
            status_text = parts[2] if len(parts) > 2 else 'Available'

            t_m = re.search(r'(\d{1,2}:\d{2}\s*[ap]m)\s*-\s*(\d{1,2}:\d{2}\s*[ap]m)', time_range, re.I)
            if not t_m:
                continue

            start_time = parse_time_12h(t_m.group(1))
            end_time = parse_time_12h(t_m.group(2))

            lower_name = raw_title.lower()
            if 'stick' in lower_name or 'puck' in lower_name:
                session_type = 'Stick & Puck'
                cost = 20.0
                note = f"$20/skater ({status_text})"
            elif 'open hockey' in lower_name:
                session_type = 'Open Hockey'
                cost = 15.0
                note = f"$15/player, Goalies free ({status_text})"
            else:
                continue

            status_lower = status_text.lower()
            if 'unavailable' in status_lower or 'full' in status_lower or status_lower.startswith('0 of'):
                avail = 'full'
            else:
                avail = 'open'

            slug = re.sub(r'[^a-z0-9]+', '-', lower_name).strip('-')
            fingerprint = f"mennen-webtrac-{session_date}-{start_time[:5]}-{slug}-{item_id}"

            events[fingerprint] = {
                'unique_fingerprint': fingerprint,
                'session_type': session_type,
                'title': raw_title,
                'session_date': session_date,
                'start_time': start_time,
                'end_time': end_time,
                'cost': cost,
                'cost_notes': note,
                'registration_required': False,
                'availability_status': avail,
                'booking_url': BOOKING_URL,
                'source_url': SOURCE_URL,
                'is_verified': True,
                'last_verified_at': now_et.isoformat()
            }

    return sorted(events.values(), key=lambda x: (x['session_date'], x['start_time']))

def sync_to_supabase():
    rink_id = get_mennen_rink_id()
    sessions = fetch_mennen_events()
    print(f"Found {len(sessions)} upcoming sessions for Mennen Sports Arena:")

    for s in sessions[:12]:
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

    print("Successfully synced Mennen Sports Arena live schedule to Supabase!")

if __name__ == '__main__':
    sync_to_supabase()

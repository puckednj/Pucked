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

SOURCE_URL = 'https://openhockeycalendar.com/rink/montclair_state'
FALLBACK_URL = 'https://openhockeycalendar.com/hockey/nj/little-falls'
BOOKING_URL = 'https://montclairstatearena.com/'

def get_floydhall_rink_id():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/rinks?name=ilike.*Floyd Hall*&select=id,name",
        headers=HEADERS,
        timeout=15
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise SystemExit("Could not find Floyd Hall Arena in your rinks table!")
    return rows[0]['id']

def update_rink_website(rink_id):
    # Ensure Floyd Hall's website_url points to the working Montclair State Ice Arena domain
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/rinks?id=eq.{rink_id}",
        headers=HEADERS,
        json={'website_url': BOOKING_URL},
        timeout=15
    )
    r.raise_for_status()

def fetch_floydhall_events():
    html = ''
    used_url = SOURCE_URL
    for url in (SOURCE_URL, FALLBACK_URL):
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        if resp.ok and 'data-seo-events' in resp.text:
            html = resp.text
            used_url = url
            break

    if not html:
        raise SystemExit("Could not locate data-seo-events JSON-LD on Open Hockey Calendar.")

    match = re.search(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*data-seo-events[^>]*>(.*?)</script>',
        html,
        re.S
    )
    if not match:
        raise SystemExit("Failed to parse JSON-LD script block.")

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

        # Extract rink surface if in parentheses, e.g., "Adult Open Hockey (Red Hawk Rink)"
        rink_surface = ''
        clean_title = raw_name
        paren = re.search(r'\(([^)]+)\)', raw_name)
        if paren:
            rink_surface = paren.group(1).strip()
            clean_title = re.sub(r'\s*\([^)]+\)', '', raw_name).strip()

        lower_name = clean_title.lower()
        session_type = 'Stick Time' if ('stick' in lower_name or 'puck' in lower_name) else 'Open Hockey'

        # Extract price if present in description/offers, otherwise default note
        offers = ev.get('offers') or {}
        price_val = offers.get('price') if isinstance(offers, dict) else None
        cost = float(price_val) if price_val not in (None, '') else None

        note_parts = []
        if cost is not None:
            note_parts.append(f"${cost:.0f} walk-in / online")
        else:
            note_parts.append("Confirm rate at rink")
        if rink_surface:
            note_parts.append(f"({rink_surface})")

        slug = re.sub(r'[^a-z0-9]+', '-', lower_name).strip('-')
        fingerprint = f"ohc-floydhall-{session_date}-{start_time[:5]}-{slug}"

        events[fingerprint] = {
            'unique_fingerprint': fingerprint,
            'session_type': session_type,
            'title': clean_title,
            'session_date': session_date,
            'start_time': start_time,
            'end_time': end_time,
            'cost': cost,
            'cost_notes': ' '.join(note_parts),
            'registration_required': False,
            'availability_status': 'open',
            'booking_url': ev.get('url') or BOOKING_URL,
            'source_url': used_url,
            'is_verified': True,
            'last_verified_at': datetime.now(eastern).isoformat()
        }

    return sorted(events.values(), key=lambda x: (x['session_date'], x['start_time']))[:30]

def sync_to_supabase():
    rink_id = get_floydhall_rink_id()
    update_rink_website(rink_id)
    sessions = fetch_floydhall_events()
    print(f"Found {len(sessions)} upcoming sessions for Floyd Hall Arena:")

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

    print("Successfully synced Floyd Hall Arena live schedule to Supabase!")

if __name__ == '__main__':
    sync_to_supabase()

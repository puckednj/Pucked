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

SCHEDULE_URL = 'https://schedule.bondsports.co/schedule/proskate-arena-schedule'
BOOKING_URL = 'https://bondsports.co/organization/318/form/825'

def get_proskate_rink_id():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/rinks?name=ilike.*ProSkate*&select=id,name",
        headers=HEADERS,
        timeout=15
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise SystemExit("Could not find ProSkate in your rinks table!")
    return rows[0]['id']

def walk_objects(node, found):
    if isinstance(node, dict):
        if 'eventId' in node and 'startTime' in node and 'endTime' in node and 'title' in node:
            found.append(node)
        for v in node.values():
            walk_objects(v, found)
    elif isinstance(node, list):
        for item in node:
            walk_objects(item, found)

def fetch_bond_events():
    resp = requests.get(SCHEDULE_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
    resp.raise_for_status()
    html = resp.text

    eastern = ZoneInfo('America/New_York')
    now_et = datetime.now(eastern)
    today_str = now_et.strftime('%Y-%m-%d')
    max_date_str = (now_et + timedelta(days=14)).strftime('%Y-%m-%d')
    decoder = json.JSONDecoder()
    raw_slots = []

    for chunk in re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.S):
        text = json.loads('"' + chunk + '"')
        if 'Stick Time' not in text and 'Cheap Skate' not in text:
            continue

        idx = 0
        n = len(text)
        while idx < n:
            brace = text.find('{', idx)
            bracket = text.find('[', idx)
            starts = [p for p in (brace, bracket) if p != -1]
            if not starts:
                break
            pos = min(starts)
            try:
                obj, end_pos = decoder.raw_decode(text, pos)
                walk_objects(obj, raw_slots)
                idx = end_pos
            except json.JSONDecodeError:
                idx = pos + 1

    events = {}
    for item in raw_slots:
        if item.get('slotType') == 'maintenance':
            continue

        title = str(item.get('title', '')).strip()
        if not any(kw in title.lower() for kw in ['stick time', 'cheap skate stick']):
            continue

        slot_id = item.get('id')
        if not slot_id:
            continue

        session_date = str(item.get('startDate', ''))[:10]
        if not session_date or session_date < today_str or session_date > max_date_str:
            continue

        start_time = str(item.get('startTime', ''))[:8]
        end_time = str(item.get('endTime', ''))[:8]
        if not start_time or not end_time:
            continue

        rink_surface = (item.get('space') or {}).get('name') or item.get('spaceName') or ''
        is_cheap_skate = 'cheap skate' in title.lower()
        session_type = 'Stick Time' if 'stick' in title.lower() else 'Open Hockey'

        price_note = '$15 Cheap Skate Special' if is_cheap_skate else '$20 online registration'
        full_notes = f"{price_note} ({rink_surface})" if rink_surface else price_note

        events[slot_id] = {
            'unique_fingerprint': f"bondsports-proskate-slot-{slot_id}",
            'session_type': session_type,
            'title': title,
            'session_date': session_date,
            'start_time': start_time,
            'end_time': end_time,
            'cost': 15.00 if is_cheap_skate else 20.00,
            'cost_notes': full_notes,
            'registration_required': True,
            'availability_status': 'open',
            'booking_url': BOOKING_URL,
            'source_url': SCHEDULE_URL,
            'is_verified': True,
            'last_verified_at': datetime.now(eastern).isoformat()
        }

    return sorted(events.values(), key=lambda x: (x['session_date'], x['start_time']))[:25]

def sync_to_supabase():
    rink_id = get_proskate_rink_id()
    sessions = fetch_bond_events()
    print(f"Found {len(sessions)} real upcoming Sticktime sessions for ProSkate:")

    for s in sessions[:10]:
        print(f"  -> {s['session_date']} | {s['start_time']} - {s['end_time']} | {s['title']} | {s['cost_notes']}")

    if not sessions:
        return

    # Wipe ALL existing ProSkate rows (including old seed/Shinny placeholders) before inserting live schedule
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

    print("Successfully replaced ProSkate schedule in Supabase with 100% live data!")

if __name__ == '__main__':
    sync_to_supabase()

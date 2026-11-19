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

SOURCE_URL = 'https://schedule.bondsports.co/schedule/icevault'
BOOKING_URL = 'https://www.icevault.com/stick-puck.php'

def get_icevault_rink_id():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/rinks?name=ilike.*Ice Vault*&select=id,name",
        headers=HEADERS,
        timeout=15
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise SystemExit("Could not find Ice Vault Arena in your rinks table!")
    return rows[0]['id']

def fetch_icevault_events(days_ahead=14):
    resp = requests.get(SOURCE_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
    resp.raise_for_status()

    rsc = ''.join(re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', resp.text, re.S))
    rsc = rsc.replace('\\"', '"').replace('\\\\', '\\')

    eastern = ZoneInfo('America/New_York')
    now_et = datetime.now(eastern)
    today_str = now_et.strftime('%Y-%m-%d')
    max_date_str = (now_et + timedelta(days=days_ahead)).strftime('%Y-%m-%d')

    events = {}
    decoder = json.JSONDecoder()

    for m in re.finditer(r'"title"\s*:\s*"([^"]+)"', rsc):
        raw_title = m.group(1).strip()
        lower_title = raw_title.lower()

        is_stick = ('stick' in lower_title and ' vs ' not in lower_title)
        is_open = ('open hockey' in lower_title or 'pickup' in lower_title or 'drop-in' in lower_title)
        if not (is_stick or is_open):
            continue

        start_brace = rsc.rfind('{', max(0, m.start() - 400), m.start())
        if start_brace == -1:
            continue

        try:
            obj, _ = decoder.raw_decode(rsc[start_brace:])
        except Exception:
            continue

        if not isinstance(obj, dict):
            continue
        if obj.get('approvalStatus') and obj.get('approvalStatus') != 'Approved':
            continue
        if obj.get('slotType') == 'maintenance':
            continue

        start_date_raw = str(obj.get('startDate', ''))
        start_time = str(obj.get('startTime', '')).strip()
        end_time = str(obj.get('endTime', '')).strip()
        if len(start_date_raw) < 10 or len(start_time) < 5 or len(end_time) < 5:
            continue

        session_date = start_date_raw[:10]
        if session_date < today_str or session_date > max_date_str:
            continue

        if len(start_time) == 5:
            start_time += ':00'
        if len(end_time) == 5:
            end_time += ':00'

        space_obj = obj.get('space') if isinstance(obj.get('space'), dict) else {}
        rink_surface = str(space_obj.get('name', 'Main Rink')).strip()

        session_type = 'Stick Time' if is_stick else 'Open Hockey'
        cost = 25.00 if is_stick else None
        cost_notes = (
            f"$25 walk-in, full gear + BYO pucks ({rink_surface})"
            if is_stick
            else f"Check in at front window ({rink_surface})"
        )

        slot_id = obj.get('id') or obj.get('eventId') or re.sub(r'[^a-z0-9]+', '-', lower_title).strip('-')
        fingerprint = f"icevault-{session_date}-{start_time[:5]}-{slot_id}"

        events[fingerprint] = {
            'unique_fingerprint': fingerprint,
            'session_type': session_type,
            'title': raw_title,
            'session_date': session_date,
            'start_time': start_time,
            'end_time': end_time,
            'cost': cost,
            'cost_notes': cost_notes,
            'registration_required': False,
            'availability_status': 'open',
            'booking_url': BOOKING_URL,
            'source_url': SOURCE_URL,
            'is_verified': True,
            'last_verified_at': datetime.now(eastern).isoformat()
        }

    return sorted(events.values(), key=lambda x: (x['session_date'], x['start_time']))

def sync_to_supabase():
    rink_id = get_icevault_rink_id()
    sessions = fetch_icevault_events()
    print(f"Found {len(sessions)} upcoming sessions for Ice Vault Arena:")

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

    print("Successfully synced Ice Vault Arena live schedule to Supabase!")

if __name__ == '__main__':
    sync_to_supabase()

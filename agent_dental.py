"""
HealUSA Dental SEO Agent v1
Publishes hyperlocal dental landing pages directly onto the healusa.life
GitHub Pages repo — targeting US audiences searching for dentists and
driving inbound pay-per-call traffic.

City tiers:
  T0 — National (10 pages)
  T1 — US States (10 pages)
  T2 — Major cities (10 pages)
  T3 — Large cities (10 pages)
  T4 — Medium cities (10 pages)
  T5 — Small cities (10 pages)
  T6 — Very small cities (10 pages)

Keywords:
  20 static custom keywords (10 Google-intent + 10 Bing-intent)
  + LLM-generated evergreen keywords per city
"""

import os
import json
import time
import random
import hashlib
import requests
import re
from datetime import datetime
from pathlib import Path

# ══════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════
GEMINI_API_KEY             = os.environ.get('GEMINI_API_KEY', '').strip()
GROQ_API_KEY               = os.environ.get('GROQ_API_KEY', '').strip()
GOOGLE_SERVICE_ACCOUNT_KEY = os.environ.get('GOOGLE_SERVICE_ACCOUNT_KEY', '').strip()

def _build_groq_keys():
    keys = []
    if GROQ_API_KEY:
        keys.append(GROQ_API_KEY)
    i = 2
    while True:
        k = os.environ.get(f'GROQ_API_KEY_{i}', '').strip()
        if not k:
            break
        keys.append(k)
        i += 1
    return keys

def _build_gemini_keys():
    keys = []
    if GEMINI_API_KEY:
        keys.append(GEMINI_API_KEY)
    i = 2
    while True:
        k = os.environ.get(f'GEMINI_API_KEY_{i}', '').strip()
        if not k:
            break
        keys.append(k)
        i += 1
    return keys

_GROQ_KEYS   = _build_groq_keys()
_GEMINI_KEYS = _build_gemini_keys()

import itertools as _itertools
_groq_cycle   = _itertools.cycle(_GROQ_KEYS)   if _GROQ_KEYS   else None
_gemini_cycle = _itertools.cycle(_GEMINI_KEYS) if _GEMINI_KEYS else None

def _next_groq_key():
    return next(_groq_cycle) if _groq_cycle else None

def _next_gemini_key():
    return next(_gemini_cycle) if _gemini_cycle else None

GITHUB_TOKEN      = os.environ.get('GH_TOKEN', os.environ.get('GITHUB_TOKEN', '')).strip()
GITHUB_PAGES_REPO = os.environ.get('HEALUSA_PAGES_REPO', os.environ.get('GH_PAGES_REPO', '')).strip()
BING_INDEXNOW_KEY = os.environ.get('BING_INDEXNOW_KEY', '').strip()

PHONE     = '(844) 833-0097'
TEL       = 'tel:+18448330097'
SITE_BASE = os.environ.get('HEALUSA_SITE_URL', 'https://www.healusa.life').rstrip('/')

MAX_PER_RUN = 5
OUTPUT_DIR  = Path('pages')
SLUGS_FILE  = Path('published_slugs.json')
QUEUE_FILE  = Path('daily_queue.json')
OUTPUT_DIR.mkdir(exist_ok=True)

# ══════════════════════════════════════════
# RETRY HELPER
# ══════════════════════════════════════════
_UA_POOL = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.4 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
]

def fetch_with_retry(url, method='get', headers=None, json_body=None,
                     timeout=15, retries=3, backoff=2.0):
    last_exc = None
    for attempt in range(retries):
        try:
            hdrs = dict(headers or {})
            hdrs.setdefault('User-Agent', random.choice(_UA_POOL))
            if method == 'post':
                r = requests.post(url, headers=hdrs, json=json_body, timeout=timeout)
            else:
                r = requests.get(url, headers=hdrs, timeout=timeout)
            if r.status_code in (403, 429, 500, 502, 503, 504):
                wait = backoff * (2 ** attempt) + random.uniform(0, 1)
                print(f'  [retry] {r.status_code} → wait {wait:.1f}s')
                time.sleep(wait)
                continue
            return r
        except Exception as e:
            last_exc = e
            wait = backoff * (2 ** attempt) + random.uniform(0, 1)
            print(f'  [retry] {e} → wait {wait:.1f}s')
            time.sleep(wait)
    if last_exc:
        print(f'  [retry] giving up: {last_exc}')
    return None

# ══════════════════════════════════════════
# DENTAL SERVICES
# ══════════════════════════════════════════
SERVICES = {
    'emergency': {
        'label': 'Emergency Dentist',
        'icon': '🚨',
        'intent': 'emergency dentist near me',
        'rpm': 35,
        'color': '#c8102e',
    },
    'implants': {
        'label': 'Dental Implants',
        'icon': '🦷',
        'intent': 'dental implants near me',
        'rpm': 45,
        'color': '#065a94',
    },
    'general': {
        'label': 'General Dentist',
        'icon': '😁',
        'intent': 'dentist near me accepting new patients',
        'rpm': 25,
        'color': '#0a7bc4',
    },
    'cosmetic': {
        'label': 'Cosmetic Dentist',
        'icon': '✨',
        'intent': 'cosmetic dentist near me',
        'rpm': 38,
        'color': '#c9a84c',
    },
    'orthodontics': {
        'label': 'Orthodontist / Braces',
        'icon': '😬',
        'intent': 'orthodontist near me braces',
        'rpm': 30,
        'color': '#065a94',
    },
}

# ══════════════════════════════════════════
# CITY DATABASE — 70 entries across 7 tiers
# pop=population(K), ins=insurance_density(1-10), comp=competition(1-10)
# ══════════════════════════════════════════
CITIES_DB = [
    # ── T0: NATIONAL (no specific city — national pages) ──
    {'slug_city': 'usa',        'name': 'United States',   'state': 'US', 'tier': 0, 'pop': 330000, 'ins': 9, 'comp': 8},
    {'slug_city': 'national',   'name': 'Nationwide',      'state': 'US', 'tier': 0, 'pop': 330000, 'ins': 9, 'comp': 8},
    {'slug_city': 'northeast',  'name': 'Northeast US',    'state': 'US', 'tier': 0, 'pop': 55000,  'ins': 9, 'comp': 7},
    {'slug_city': 'southeast',  'name': 'Southeast US',    'state': 'US', 'tier': 0, 'pop': 62000,  'ins': 7, 'comp': 6},
    {'slug_city': 'midwest',    'name': 'Midwest US',      'state': 'US', 'tier': 0, 'pop': 68000,  'ins': 8, 'comp': 6},
    {'slug_city': 'southwest',  'name': 'Southwest US',    'state': 'US', 'tier': 0, 'pop': 40000,  'ins': 7, 'comp': 6},
    {'slug_city': 'west-coast', 'name': 'West Coast US',   'state': 'US', 'tier': 0, 'pop': 55000,  'ins': 9, 'comp': 8},
    {'slug_city': 'south',      'name': 'Southern US',     'state': 'US', 'tier': 0, 'pop': 45000,  'ins': 7, 'comp': 6},
    {'slug_city': 'mountain',   'name': 'Mountain States', 'state': 'US', 'tier': 0, 'pop': 22000,  'ins': 7, 'comp': 5},
    {'slug_city': 'plains',     'name': 'Great Plains',    'state': 'US', 'tier': 0, 'pop': 14000,  'ins': 6, 'comp': 4},

    # ── T1: STATES (10 most populous) ──
    {'slug_city': 'california',  'name': 'California',  'state': 'CA', 'tier': 1, 'pop': 39500, 'ins': 9, 'comp': 9},
    {'slug_city': 'texas',       'name': 'Texas',       'state': 'TX', 'tier': 1, 'pop': 29000, 'ins': 8, 'comp': 8},
    {'slug_city': 'florida',     'name': 'Florida',     'state': 'FL', 'tier': 1, 'pop': 21500, 'ins': 8, 'comp': 8},
    {'slug_city': 'new-york',    'name': 'New York',    'state': 'NY', 'tier': 1, 'pop': 20200, 'ins': 9, 'comp': 9},
    {'slug_city': 'pennsylvania','name': 'Pennsylvania','state': 'PA', 'tier': 1, 'pop': 13000, 'ins': 8, 'comp': 7},
    {'slug_city': 'illinois',    'name': 'Illinois',    'state': 'IL', 'tier': 1, 'pop': 12700, 'ins': 8, 'comp': 8},
    {'slug_city': 'ohio',        'name': 'Ohio',        'state': 'OH', 'tier': 1, 'pop': 11800, 'ins': 8, 'comp': 7},
    {'slug_city': 'georgia',     'name': 'Georgia',     'state': 'GA', 'tier': 1, 'pop': 10700, 'ins': 7, 'comp': 7},
    {'slug_city': 'north-carolina','name':'North Carolina','state':'NC','tier': 1, 'pop': 10400, 'ins': 7, 'comp': 6},
    {'slug_city': 'michigan',    'name': 'Michigan',    'state': 'MI', 'tier': 1, 'pop': 10000, 'ins': 8, 'comp': 7},

    # ── T2: VERY LARGE CITIES ──
    {'slug_city': 'new-york-city', 'name': 'New York City', 'state': 'NY', 'tier': 2, 'pop': 8336, 'ins': 9, 'comp': 10},
    {'slug_city': 'los-angeles',   'name': 'Los Angeles',   'state': 'CA', 'tier': 2, 'pop': 3979, 'ins': 8, 'comp': 10},
    {'slug_city': 'chicago',       'name': 'Chicago',       'state': 'IL', 'tier': 2, 'pop': 2693, 'ins': 9, 'comp': 9},
    {'slug_city': 'houston',       'name': 'Houston',       'state': 'TX', 'tier': 2, 'pop': 2304, 'ins': 8, 'comp': 9},
    {'slug_city': 'phoenix',       'name': 'Phoenix',       'state': 'AZ', 'tier': 2, 'pop': 1608, 'ins': 7, 'comp': 8},
    {'slug_city': 'philadelphia',  'name': 'Philadelphia',  'state': 'PA', 'tier': 2, 'pop': 1584, 'ins': 8, 'comp': 8},
    {'slug_city': 'san-antonio',   'name': 'San Antonio',   'state': 'TX', 'tier': 2, 'pop': 1434, 'ins': 7, 'comp': 7},
    {'slug_city': 'san-diego',     'name': 'San Diego',     'state': 'CA', 'tier': 2, 'pop': 1386, 'ins': 8, 'comp': 8},
    {'slug_city': 'dallas',        'name': 'Dallas',        'state': 'TX', 'tier': 2, 'pop': 1304, 'ins': 8, 'comp': 9},
    {'slug_city': 'san-jose',      'name': 'San Jose',      'state': 'CA', 'tier': 2, 'pop': 1030, 'ins': 9, 'comp': 8},

    # ── T3: LARGE CITIES ──
    {'slug_city': 'austin',        'name': 'Austin',        'state': 'TX', 'tier': 3, 'pop': 978,  'ins': 8, 'comp': 7},
    {'slug_city': 'jacksonville',  'name': 'Jacksonville',  'state': 'FL', 'tier': 3, 'pop': 911,  'ins': 7, 'comp': 6},
    {'slug_city': 'fort-worth',    'name': 'Fort Worth',    'state': 'TX', 'tier': 3, 'pop': 895,  'ins': 7, 'comp': 6},
    {'slug_city': 'columbus',      'name': 'Columbus',      'state': 'OH', 'tier': 3, 'pop': 898,  'ins': 8, 'comp': 7},
    {'slug_city': 'charlotte',     'name': 'Charlotte',     'state': 'NC', 'tier': 3, 'pop': 874,  'ins': 7, 'comp': 7},
    {'slug_city': 'indianapolis',  'name': 'Indianapolis',  'state': 'IN', 'tier': 3, 'pop': 887,  'ins': 7, 'comp': 6},
    {'slug_city': 'san-francisco', 'name': 'San Francisco', 'state': 'CA', 'tier': 3, 'pop': 874,  'ins': 9, 'comp': 9},
    {'slug_city': 'seattle',       'name': 'Seattle',       'state': 'WA', 'tier': 3, 'pop': 737,  'ins': 9, 'comp': 8},
    {'slug_city': 'denver',        'name': 'Denver',        'state': 'CO', 'tier': 3, 'pop': 715,  'ins': 8, 'comp': 7},
    {'slug_city': 'nashville',     'name': 'Nashville',     'state': 'TN', 'tier': 3, 'pop': 689,  'ins': 7, 'comp': 6},

    # ── T4: MEDIUM CITIES ──
    {'slug_city': 'oklahoma-city', 'name': 'Oklahoma City', 'state': 'OK', 'tier': 4, 'pop': 681,  'ins': 6, 'comp': 5},
    {'slug_city': 'el-paso',       'name': 'El Paso',       'state': 'TX', 'tier': 4, 'pop': 678,  'ins': 6, 'comp': 5},
    {'slug_city': 'washington-dc', 'name': 'Washington DC', 'state': 'DC', 'tier': 4, 'pop': 689,  'ins': 9, 'comp': 8},
    {'slug_city': 'las-vegas',     'name': 'Las Vegas',     'state': 'NV', 'tier': 4, 'pop': 641,  'ins': 7, 'comp': 7},
    {'slug_city': 'louisville',    'name': 'Louisville',    'state': 'KY', 'tier': 4, 'pop': 633,  'ins': 7, 'comp': 5},
    {'slug_city': 'memphis',       'name': 'Memphis',       'state': 'TN', 'tier': 4, 'pop': 633,  'ins': 6, 'comp': 5},
    {'slug_city': 'portland',      'name': 'Portland',      'state': 'OR', 'tier': 4, 'pop': 652,  'ins': 8, 'comp': 7},
    {'slug_city': 'baltimore',     'name': 'Baltimore',     'state': 'MD', 'tier': 4, 'pop': 585,  'ins': 7, 'comp': 6},
    {'slug_city': 'milwaukee',     'name': 'Milwaukee',     'state': 'WI', 'tier': 4, 'pop': 577,  'ins': 7, 'comp': 5},
    {'slug_city': 'albuquerque',   'name': 'Albuquerque',   'state': 'NM', 'tier': 4, 'pop': 564,  'ins': 6, 'comp': 4},

    # ── T5: SMALL CITIES ──
    {'slug_city': 'tucson',        'name': 'Tucson',        'state': 'AZ', 'tier': 5, 'pop': 542,  'ins': 6, 'comp': 4},
    {'slug_city': 'fresno',        'name': 'Fresno',        'state': 'CA', 'tier': 5, 'pop': 530,  'ins': 6, 'comp': 4},
    {'slug_city': 'sacramento',    'name': 'Sacramento',    'state': 'CA', 'tier': 5, 'pop': 524,  'ins': 7, 'comp': 5},
    {'slug_city': 'mesa',          'name': 'Mesa',          'state': 'AZ', 'tier': 5, 'pop': 504,  'ins': 6, 'comp': 4},
    {'slug_city': 'kansas-city',   'name': 'Kansas City',   'state': 'MO', 'tier': 5, 'pop': 495,  'ins': 7, 'comp': 5},
    {'slug_city': 'atlanta',       'name': 'Atlanta',       'state': 'GA', 'tier': 5, 'pop': 498,  'ins': 7, 'comp': 7},
    {'slug_city': 'omaha',         'name': 'Omaha',         'state': 'NE', 'tier': 5, 'pop': 486,  'ins': 7, 'comp': 4},
    {'slug_city': 'colorado-springs','name':'Colorado Springs','state':'CO','tier':5,  'pop': 478,  'ins': 7, 'comp': 4},
    {'slug_city': 'raleigh',       'name': 'Raleigh',       'state': 'NC', 'tier': 5, 'pop': 467,  'ins': 7, 'comp': 5},
    {'slug_city': 'long-beach',    'name': 'Long Beach',    'state': 'CA', 'tier': 5, 'pop': 462,  'ins': 7, 'comp': 5},

    # ── T6: VERY SMALL CITIES ──
    {'slug_city': 'virginia-beach','name': 'Virginia Beach','state': 'VA', 'tier': 6, 'pop': 459,  'ins': 7, 'comp': 4},
    {'slug_city': 'minneapolis',   'name': 'Minneapolis',   'state': 'MN', 'tier': 6, 'pop': 429,  'ins': 8, 'comp': 6},
    {'slug_city': 'tampa',         'name': 'Tampa',         'state': 'FL', 'tier': 6, 'pop': 399,  'ins': 7, 'comp': 5},
    {'slug_city': 'new-orleans',   'name': 'New Orleans',   'state': 'LA', 'tier': 6, 'pop': 390,  'ins': 6, 'comp': 5},
    {'slug_city': 'arlington',     'name': 'Arlington',     'state': 'TX', 'tier': 6, 'pop': 394,  'ins': 7, 'comp': 5},
    {'slug_city': 'bakersfield',   'name': 'Bakersfield',   'state': 'CA', 'tier': 6, 'pop': 384,  'ins': 5, 'comp': 3},
    {'slug_city': 'honolulu',      'name': 'Honolulu',      'state': 'HI', 'tier': 6, 'pop': 350,  'ins': 8, 'comp': 5},
    {'slug_city': 'anaheim',       'name': 'Anaheim',       'state': 'CA', 'tier': 6, 'pop': 346,  'ins': 7, 'comp': 5},
    {'slug_city': 'aurora',        'name': 'Aurora',        'state': 'CO', 'tier': 6, 'pop': 366,  'ins': 7, 'comp': 4},
    {'slug_city': 'santa-ana',     'name': 'Santa Ana',     'state': 'CA', 'tier': 6, 'pop': 310,  'ins': 6, 'comp': 4},
]

# ══════════════════════════════════════════
# 20 CUSTOM KEYWORDS
# 10 Google high-intent + 10 Bing local-intent
# ══════════════════════════════════════════
GOOGLE_KEYWORDS = [
    'emergency dentist near me open now',
    'dentist accepting new patients near me no insurance',
    'affordable dental implants near me payment plans',
    'same day dentist appointment near me',
    'emergency tooth extraction near me today',
    'dentist open on weekends near me',
    'cheap dentist near me for low income',
    'walk in dentist near me no appointment needed',
    'dental implants cost near me financing available',
    'best cosmetic dentist near me teeth whitening',
]

BING_KEYWORDS = [
    'emergency dentist {city} open now',
    'dentist near {city} accepting medicaid',
    'affordable dental care {city} {state}',
    'find a dentist {city} same day',
    'dental implants {city} {state} affordable',
    'tooth pain emergency dentist {city}',
    'dentist open saturday {city} {state}',
    'family dentist {city} accepting new patients',
    'cosmetic dentist {city} teeth whitening specials',
    'orthodontist {city} {state} braces consultation free',
]

# ══════════════════════════════════════════
# SLUG HELPERS
# ══════════════════════════════════════════
def make_slug(text):
    s = re.sub(r'[^a-z0-9]+', '-', text.lower().strip())
    return s.strip('-')

def load_slugs():
    if SLUGS_FILE.exists():
        try:
            data = json.loads(SLUGS_FILE.read_text())
            published   = set(data.get('published', []))
            daily       = data.get('daily', {})
            return published, daily
        except Exception:
            pass
    return set(), {}

def save_slugs(published, daily):
    SLUGS_FILE.write_text(json.dumps({
        'published': sorted(published),
        'daily':     daily,
    }, indent=2))

def load_daily_queue():
    if QUEUE_FILE.exists():
        try:
            data = json.loads(QUEUE_FILE.read_text())
            today_str = datetime.now().strftime('%Y-%m-%d')
            if data.get('date') == today_str:
                return data.get('queue', [])
        except Exception:
            pass
    return []

def save_daily_queue(queue, date_str):
    QUEUE_FILE.write_text(json.dumps({'date': date_str, 'queue': queue}, indent=2))

def update_today_count(daily, count):
    today_str = datetime.now().strftime('%Y-%m-%d')
    daily[today_str] = count
    return daily

# ══════════════════════════════════════════
# KEYWORD ENGINE — build queue
# ══════════════════════════════════════════
def build_keyword_queue(published):
    """
    Builds daily keyword queue mixing:
    - Google keywords (national + city pages)
    - Bing keywords (city-specific)
    - Evergreen city pages for unpublished cities
    """
    queue = []
    year  = datetime.now().year

    # 1. Custom Google keywords — national / general
    for kw in GOOGLE_KEYWORDS:
        slug = make_slug(kw)
        if slug not in published:
            city = CITIES_DB[0]  # USA national
            queue.append({
                'kw':      kw,
                'title':   kw.title(),
                'city':    city,
                'service': _detect_service(kw),
                'source':  'google_keyword',
                'score':   90,
            })

    # 2. Bing keywords — inject top cities
    top_cities = [c for c in CITIES_DB if c['tier'] in (2, 3)][:20]
    for city in top_cities:
        for kw_tpl in BING_KEYWORDS:
            kw   = kw_tpl.format(city=city['name'], state=city['state'], year=year)
            slug = make_slug(kw)
            if slug not in published:
                queue.append({
                    'kw':      kw,
                    'title':   kw.title(),
                    'city':    city,
                    'service': _detect_service(kw),
                    'source':  'bing_keyword',
                    'score':   80,
                })

    # 3. Evergreen city pages — one per city not yet covered
    svc_cycle = _itertools.cycle(list(SERVICES.keys()))
    for city in CITIES_DB:
        svc_key = next(svc_cycle)
        svc     = SERVICES[svc_key]
        if city['tier'] == 0:
            kw = f"{svc['label'].lower()} {city['name'].lower()}"
        else:
            kw = f"{svc['intent']} {city['name']} {city['state']}"
        slug = make_slug(kw)
        if slug not in published:
            queue.append({
                'kw':      kw,
                'title':   f"{svc['label']} in {city['name']}, {city['state']} | HealUSA",
                'city':    city,
                'service': svc_key,
                'source':  'evergreen_city',
                'score':   70 - city['tier'] * 5,
            })

    # Sort by score desc, shuffle ties
    random.shuffle(queue)
    queue.sort(key=lambda x: -x['score'])
    return queue

def _detect_service(kw):
    kw_lower = kw.lower()
    if any(w in kw_lower for w in ['emergency', 'urgent', 'pain', 'tooth pain', 'extraction']):
        return 'emergency'
    if any(w in kw_lower for w in ['implant']):
        return 'implants'
    if any(w in kw_lower for w in ['cosmetic', 'whitening', 'veneers', 'smile']):
        return 'cosmetic'
    if any(w in kw_lower for w in ['braces', 'orthodont', 'invisalign']):
        return 'orthodontics'
    return 'general'

# ══════════════════════════════════════════
# LLM — GROQ (primary) + GEMINI (fallback)
# ══════════════════════════════════════════
def _groq_post(prompt, max_tokens=1800):
    if not _GROQ_KEYS:
        return None
    models = ['llama-3.3-70b-versatile', 'llama-3.1-70b-versatile', 'mixtral-8x7b-32768']
    for attempt in range(len(_GROQ_KEYS) * 2):
        key   = _next_groq_key()
        model = models[attempt % len(models)]
        try:
            r = requests.post(
                'https://api.groq.com/openai/v1/chat/completions',
                headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                json={
                    'model':       model,
                    'max_tokens':  max_tokens,
                    'temperature': 0.7,
                    'messages':    [{'role': 'user', 'content': prompt}],
                },
                timeout=45,
            )
            if r.status_code == 200:
                return r.json()['choices'][0]['message']['content']
            if r.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f'  [Groq] 429 key#{attempt%len(_GROQ_KEYS)+1} — wait {wait}s')
                time.sleep(wait)
                continue
            print(f'  [Groq] {r.status_code}')
        except Exception as e:
            print(f'  [Groq] attempt {attempt+1}: {e}')
            time.sleep(3)
    return None

def _gemini_post(prompt, max_tokens=1800):
    if not _GEMINI_KEYS:
        return None
    for attempt in range(len(_GEMINI_KEYS) * 2):
        key = _next_gemini_key()
        try:
            r = requests.post(
                f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent?key={key}',
                headers={'Content-Type': 'application/json'},
                json={
                    'contents': [{'parts': [{'text': prompt}]}],
                    'generationConfig': {'maxOutputTokens': max_tokens, 'temperature': 0.7},
                },
                timeout=45,
            )
            if r.status_code == 200:
                return r.json()['candidates'][0]['content']['parts'][0]['text']
            if r.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f'  [Gemini] 429 key#{attempt%len(_GEMINI_KEYS)+1} — wait {wait}s')
                time.sleep(wait)
                continue
            print(f'  [Gemini] {r.status_code}')
        except Exception as e:
            print(f'  [Gemini] attempt {attempt+1}: {e}')
            time.sleep(3)
    return None

def llm_generate(prompt, max_tokens=1800):
    """Groq first, Gemini fallback."""
    text = _groq_post(prompt, max_tokens)
    if text:
        return text
    print('  [LLM] Groq failed — trying Gemini...')
    text = _gemini_post(prompt, max_tokens)
    if text:
        return text
    print('  [LLM] Both LLMs failed')
    return None

# ══════════════════════════════════════════
# ARTICLE GENERATOR
# ══════════════════════════════════════════
def generate_article(item):
    city    = item['city']
    svc_key = item.get('service', 'general')
    svc     = SERVICES[svc_key]
    kw      = item['kw']
    year    = datetime.now().year

    city_label = city['name'] if city['tier'] > 0 else 'your area'
    state_label = city['state'] if city['state'] != 'US' else 'across the USA'

    prompt = f"""You are a dental content writer for HealUSA, a US dental referral service.

Write a complete, informative SEO article about: "{kw}"

City/Region: {city_label}, {state_label}
Dental Service Focus: {svc['label']}
Year: {year}

RULES:
- Write 600-900 words of real, helpful dental content
- Use HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>
- Start directly with the first <h2> — no intro paragraph before it
- Include 4-6 H2 sections covering: what the service is, when to call, what to expect, cost/insurance, how HealUSA helps
- Mention "{city_label}" naturally 3-5 times
- Mention "{svc['label'].lower()}" 4-6 times
- End with a clear call-to-action paragraph mentioning the phone number (844) 833-0097
- DO NOT include: markdown, backticks, DOCTYPE, <html>, <body>, <head>, <style>, <script>
- Write in a friendly, trustworthy, professional tone
- Include real dental facts and tips

Return ONLY the HTML article content, nothing else."""

    body = llm_generate(prompt)
    if not body:
        body = _fallback_body(svc, city_label, state_label)

    # Clean any markdown artifacts
    body = re.sub(r'```[a-z]*', '', body).strip()

    slug  = make_slug(kw) + '.html'
    title = item.get('title') or f"{svc['label']} in {city_label}, {state_label} | HealUSA"
    words = len(body.split())

    html  = build_page(svc_key, title, kw, body, city, item.get('source', 'evergreen'))

    return {
        'slug':    slug,
        'title':   title,
        'html':    html,
        'words':   words,
        'service': svc_key,
        'city':    city,
        'source':  item.get('source', 'evergreen'),
    }

def _fallback_body(svc, city_label, state_label):
    return f"""<h2>Find a {svc['label']} in {city_label}</h2>
<p>Whether you need routine care or urgent treatment, HealUSA connects you with
top-rated dental professionals in {city_label}, {state_label}. Our network includes
experienced dentists ready to help you today.</p>

<h2>When Should You Call?</h2>
<p>Don't wait if you're experiencing tooth pain, a broken tooth, swelling, or
have been putting off a dental visit. Early treatment prevents costly complications.</p>
<ul>
<li><strong>Tooth pain or sensitivity</strong> — could indicate decay or infection</li>
<li><strong>Broken or chipped tooth</strong> — needs prompt attention</li>
<li><strong>Dental abscess</strong> — requires urgent care</li>
<li><strong>Missing tooth</strong> — implants or bridges available</li>
</ul>

<h2>What to Expect</h2>
<p>Our affiliated dentists in {city_label} offer comprehensive care from cleanings
and fillings to {svc['label'].lower()} procedures. Most accept major insurance plans
and offer flexible payment options.</p>

<h2>Insurance &amp; Costs</h2>
<p>Many dental plans cover preventive care at 100%. For procedures like
{svc['label'].lower()}, financing plans are available. Call us and we'll help
you understand your options before your appointment.</p>

<h2>How HealUSA Helps</h2>
<p>HealUSA is a free dental referral service covering all 50 states. We match you
with quality dentists near you — fast. Call <strong>(844) 833-0097</strong> now
to find a {svc['label'].lower()} in {city_label} accepting new patients today.</p>"""

# ══════════════════════════════════════════
# HTML PAGE BUILDER — healusa.life template
# ══════════════════════════════════════════
def _build_service_links(city_label):
    links = []
    for svc in SERVICES.values():
        slug = make_slug(svc['intent'] + ' ' + city_label)
        links.append(
            f'<a href="{SITE_BASE}/pages/{slug}.html">{svc["icon"]} {svc["label"]}</a>'
        )
    return '\n      '.join(links)

def build_page(svc_key, title, kw, body, city, source='evergreen'):
    svc        = SERVICES[svc_key]
    city_label = city['name']
    state_label = city['state'] if city['state'] != 'US' else 'USA'
    year       = datetime.now().year
    pub_human  = datetime.now().strftime('%B %d, %Y')
    slug       = make_slug(kw)

    meta_desc = (
        f"Find a trusted {svc['label'].lower()} in {city_label}, {state_label}. "
        f"HealUSA connects you with top-rated dental clinics — same-day appointments available. "
        f"Call {PHONE} now."
    )

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="description" content="{meta_desc}">
<meta name="theme-color" content="#0a7bc4">
<link rel="canonical" href="{SITE_BASE}/pages/{slug}.html">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Playfair+Display:wght@700;900&display=swap" rel="stylesheet">
<style>
:root{{
  --blue:#0a7bc4;
  --blue-dark:#065a94;
  --gold:#c9a84c;
  --dark:#0d1f2f;
  --gray:#4a6280;
  --cream:#f0f8ff;
  --light-gray:#e8f0f8;
  --svc:{svc['color']};
}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'DM Sans',sans-serif;color:var(--dark);line-height:1.6;background:#fff}}
.wrap{{max-width:1200px;margin:0 auto;padding:0 20px}}

/* TICKER */
.ticker{{background:var(--blue-dark);color:#fff;padding:11px 0;overflow:hidden;position:sticky;top:0;z-index:100}}
.ticker-wrap{{display:flex;overflow:hidden}}
.ticker-move{{display:flex;gap:40px;animation:scroll 22s linear infinite;white-space:nowrap}}
.ticker-move span{{font-size:13px;font-weight:600}}
.ticker-move span em{{color:var(--gold);font-style:normal}}
@keyframes scroll{{0%{{transform:translateX(0)}}100%{{transform:translateX(-50%)}}}}

/* NAV */
.nav{{background:#fff;padding:14px 0;border-bottom:1px solid var(--light-gray);position:sticky;top:45px;z-index:99;box-shadow:0 2px 10px rgba(10,123,196,.08)}}
.nav-wrap{{display:flex;justify-content:space-between;align-items:center}}
.logo{{display:flex;align-items:center;gap:10px;text-decoration:none}}
.logo-icon{{width:40px;height:40px;background:var(--blue);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:20px}}
.logo-text{{font-family:'Playfair Display',serif;font-size:26px;font-weight:900;color:var(--blue-dark);letter-spacing:-0.5px}}
.logo-text span{{color:var(--gold)}}
.menu{{display:flex;gap:6px;align-items:center}}
.menu a{{color:var(--dark);text-decoration:none;font-weight:600;font-size:14px;padding:6px 10px;border-radius:6px;transition:.2s}}
.menu a:hover{{color:var(--blue);background:var(--cream)}}
.btn{{display:inline-flex;align-items:center;gap:7px;padding:10px 20px;background:var(--blue);color:#fff;border-radius:8px;text-decoration:none;font-weight:700;transition:.2s;border:none;cursor:pointer;font-size:14px}}
.btn:hover{{background:var(--blue-dark);transform:translateY(-1px)}}
.btn-gold{{background:var(--gold);color:var(--dark)}}
.btn-gold:hover{{background:#b8912e}}
.nav-phone-box{{display:inline-flex;align-items:center;gap:7px;background:#f5c518;color:#0d1f17;font-weight:800;font-size:14px;padding:8px 16px;border-radius:7px;text-decoration:none;letter-spacing:.2px;box-shadow:0 2px 8px rgba(245,197,24,.4);transition:.2s}}
.nav-phone-box:hover{{background:#e0b000}}
.ham{{display:none;flex-direction:column;gap:4px;cursor:pointer;padding:8px}}
.ham span{{width:24px;height:3px;background:var(--dark);border-radius:2px;transition:.3s}}

/* HERO */
.hero{{background:linear-gradient(135deg,var(--blue-dark) 0%,var(--blue) 60%,#2196f3 100%);padding:64px 0 52px;position:relative;overflow:hidden}}
.hero::before{{content:'';position:absolute;top:-60px;right:-80px;width:420px;height:420px;background:rgba(255,255,255,.04);border-radius:50%}}
.hero::after{{content:'';position:absolute;bottom:-80px;left:-60px;width:300px;height:300px;background:rgba(201,168,76,.08);border-radius:50%}}
.hero-inner{{position:relative;z-index:2}}
.hero-badge{{display:inline-flex;align-items:center;gap:10px;background:rgba(201,168,76,.2);border:2px solid rgba(201,168,76,.7);padding:10px 20px;border-radius:8px;font-size:13px;font-weight:800;color:#f5c518;margin-bottom:20px;letter-spacing:1px;text-transform:uppercase}}
.hero h1{{font-family:'Playfair Display',serif;font-size:46px;font-weight:900;line-height:1.1;margin-bottom:18px;color:#fff;text-shadow:0 2px 20px rgba(0,0,0,.3)}}
.hero h1 em{{font-style:normal;color:var(--gold)}}
.hero-sub{{font-size:17px;color:rgba(255,255,255,.9);margin-bottom:28px;max-width:600px}}
.hero-phone-box{{display:inline-flex;align-items:center;gap:12px;background:#f5c518;border-radius:10px;padding:14px 28px;margin-bottom:20px;box-shadow:0 6px 24px rgba(245,197,24,.4)}}
.hero-phone-box a{{font-family:'Playfair Display',serif;font-size:32px;font-weight:900;color:#0d1f17;text-decoration:none;letter-spacing:-0.5px}}
.hero-phone-box .ph-icon{{font-size:28px}}
.hero-note{{font-size:12px;color:rgba(255,255,255,.7);margin-top:10px}}
.breadcrumb{{font-size:12px;color:rgba(255,255,255,.65);margin-bottom:16px;font-weight:600}}
.breadcrumb a{{color:rgba(255,255,255,.8);text-decoration:none}}

/* TRUST BAR */
.trust{{background:var(--cream);border-top:3px solid var(--gold);border-bottom:1px solid var(--light-gray);padding:22px 0}}
.trust-inner{{display:flex;gap:28px;justify-content:center;flex-wrap:wrap}}
.trust-item{{text-align:center}}
.trust-num{{font-family:'Playfair Display',serif;font-size:30px;font-weight:900;color:var(--blue)}}
.trust-label{{font-size:12px;color:var(--gray);margin-top:3px;font-weight:500}}

/* LAYOUT */
.main-layout{{max-width:1200px;margin:0 auto;padding:44px 20px;display:grid;grid-template-columns:1fr 300px;gap:36px}}
.article h2{{font-family:'Playfair Display',serif;font-size:24px;font-weight:900;color:var(--blue-dark);margin:32px 0 12px;border-bottom:2px solid var(--light-gray);padding-bottom:8px}}
.article h3{{font-size:17px;font-weight:700;color:var(--dark);margin:18px 0 8px}}
.article p{{color:#3a5068;font-size:15px;line-height:1.9;margin-bottom:14px}}
.article ul,.article ol{{padding-left:22px;color:#3a5068;font-size:15px;line-height:1.9;margin-bottom:14px}}
.article li{{margin-bottom:6px}}

/* SIDEBAR */
.sidebar{{display:flex;flex-direction:column;gap:16px}}
.side-card{{background:#fff;border:2px solid var(--blue);border-radius:14px;padding:22px;text-align:center;box-shadow:0 4px 20px rgba(10,123,196,.12)}}
.side-card .badge{{display:inline-block;background:var(--cream);color:var(--blue-dark);font-size:11px;font-weight:800;letter-spacing:1px;text-transform:uppercase;padding:4px 10px;border-radius:20px;margin-bottom:10px}}
.side-card .sp{{font-family:'Playfair Display',serif;font-size:26px;font-weight:900;color:var(--dark);margin:10px 0}}
.side-card a.btn{{display:block;margin-top:12px;justify-content:center}}
.side-links{{background:#fff;border:1px solid var(--light-gray);border-radius:12px;padding:18px}}
.side-links h4{{font-size:11px;font-weight:800;color:var(--gray);letter-spacing:1px;margin-bottom:12px;text-transform:uppercase}}
.side-links a{{display:block;color:var(--gray);text-decoration:none;font-size:13px;font-weight:600;padding:7px 0;border-bottom:1px solid var(--light-gray)}}
.side-links a:last-child{{border-bottom:none}}
.side-links a:hover{{color:var(--blue)}}
.service-card{{background:var(--cream);border:1px solid var(--light-gray);border-radius:12px;padding:16px}}
.service-card h4{{font-size:13px;font-weight:800;color:var(--blue-dark);margin-bottom:10px}}
.service-card a{{display:flex;align-items:center;gap:8px;color:var(--gray);text-decoration:none;font-size:13px;font-weight:600;padding:6px 0;border-bottom:1px solid var(--light-gray);transition:.2s}}
.service-card a:last-child{{border-bottom:none}}
.service-card a:hover{{color:var(--blue)}}

/* CTA */
.cta{{background:linear-gradient(135deg,var(--blue-dark),var(--blue));color:#fff;padding:56px 0;text-align:center}}
.cta h2{{font-family:'Playfair Display',serif;font-size:32px;font-weight:900;margin-bottom:14px}}
.cta p{{font-size:16px;margin-bottom:28px;opacity:.9;max-width:540px;margin-left:auto;margin-right:auto}}
.cta-phone-box{{display:inline-flex;align-items:center;gap:8px;background:#f5c518;border-radius:8px;padding:12px 24px;font-size:20px;font-weight:800;color:#0d1f17;text-decoration:none;box-shadow:0 4px 16px rgba(245,197,24,.4);transition:.2s}}
.cta-phone-box:hover{{background:#e0b000;transform:translateY(-2px)}}

/* DISCLOSURE */
.disclosure{{background:#f8fafc;border-top:3px solid var(--light-gray);padding:40px 0}}
.disclosure-box{{background:#fff;border-radius:12px;padding:22px;border:1px solid var(--light-gray);margin-bottom:12px;max-width:860px;margin-left:auto;margin-right:auto}}
.disclosure-box h3{{font-size:14px;font-weight:700;color:var(--dark);margin-bottom:8px}}
.disclosure-box p{{font-size:12px;color:var(--gray);line-height:1.85}}
.disclosure-final{{background:#fffbeb;border-radius:12px;padding:16px 22px;border:1px solid #fcd34d;max-width:860px;margin:0 auto}}
.disclosure-final p{{font-size:11px;color:#92400e;line-height:1.85}}

/* FOOTER */
.footer{{background:var(--dark);color:#8facc4;padding:40px 0}}
.footer-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:28px;margin-bottom:28px}}
.footer-section h4{{color:#fff;margin-bottom:12px;font-size:14px;font-weight:700}}
.footer-section ul{{list-style:none;padding:0}}
.footer-section ul li{{margin-bottom:8px}}
.footer a{{color:#8facc4;text-decoration:none;font-size:13px;transition:.2s}}
.footer a:hover{{color:#fff}}
.footer-bottom{{text-align:center;padding-top:20px;border-top:1px solid #1e3a52;font-size:11px;opacity:.6}}

/* FAB */
.fab{{position:fixed;bottom:26px;right:26px;width:110px;height:110px;background:linear-gradient(135deg,#f5c518,#c9a84c);color:#0d1f17;border-radius:50%;display:flex;flex-direction:column;align-items:center;justify-content:center;font-size:42px;box-shadow:0 10px 40px rgba(245,197,24,.55);cursor:pointer;z-index:999;text-decoration:none;animation:pulse 2s infinite;border:3px solid rgba(255,255,255,.5)}}
.fab-text{{font-size:9px;font-weight:800;letter-spacing:.5px;margin-top:-4px;color:#0d1f17}}
@keyframes pulse{{0%,100%{{transform:scale(1);box-shadow:0 10px 40px rgba(245,197,24,.55)}}50%{{transform:scale(1.12);box-shadow:0 14px 52px rgba(245,197,24,.75)}}}}

/* RESPONSIVE */
@media(max-width:768px){{
  .menu{{display:none;position:absolute;top:68px;left:0;right:0;background:#fff;flex-direction:column;padding:20px;box-shadow:0 8px 20px rgba(0,0,0,.1);border-top:1px solid var(--light-gray)}}
  .menu.show{{display:flex}}
  .ham{{display:flex}}
  .hero{{padding:44px 0 36px}}
  .hero h1{{font-size:28px}}
  .hero-sub{{font-size:14px}}
  .hero-phone-box a{{font-size:24px}}
  .hero-phone-box{{padding:12px 18px;gap:8px;width:100%;max-width:320px}}
  .main-layout{{grid-template-columns:1fr;padding:28px 16px}}
  .sidebar{{display:none}}
  .fab{{width:95px;height:95px;font-size:36px;bottom:18px;right:16px}}
  .trust-inner{{gap:18px}}
  .cta h2{{font-size:24px}}
  .footer-grid{{grid-template-columns:1fr}}
  .nav-phone-box{{font-size:12px;padding:6px 12px}}
}}
</style>
</head>
<body>

<div class="ticker">
  <div class="ticker-wrap">
    <div class="ticker-move">
      <span>🦷 Find a dentist near you — <em>call now</em></span>
      <span>📞 Same-day appointments available</span>
      <span>🇺🇸 Serving all 50 states</span>
      <span>💰 Insurance accepted — affordable care</span>
      <span>🚨 Emergency dental care available 24/7</span>
      <span>✅ Free referral service — no fees</span>
      <span>🦷 Find a dentist near you — <em>call now</em></span>
      <span>📞 Same-day appointments available</span>
      <span>🇺🇸 Serving all 50 states</span>
      <span>💰 Insurance accepted — affordable care</span>
      <span>🚨 Emergency dental care available 24/7</span>
      <span>✅ Free referral service — no fees</span>
    </div>
  </div>
</div>

<nav class="nav">
  <div class="wrap nav-wrap">
    <a href="{SITE_BASE}/" class="logo">
      <div class="logo-icon">🦷</div>
      <div class="logo-text">Heal<span>USA</span></div>
    </a>
    <button class="ham" id="ham" onclick="toggleMenu()">
      <span></span><span></span><span></span>
    </button>
    <div class="menu" id="menu">
      <a href="{SITE_BASE}/#services">Services</a>
      <a href="{SITE_BASE}/#how-it-works">How It Works</a>
      <a href="{SITE_BASE}/#faq">FAQ</a>
      <a href="{SITE_BASE}/#contact">Contact</a>
      <a href="{TEL}" class="nav-phone-box">📞 {PHONE}</a>
    </div>
  </div>
</nav>

<section class="hero">
  <div class="wrap hero-inner">
    <div class="breadcrumb">
      <a href="{SITE_BASE}/">HealUSA</a> &nbsp;›&nbsp;
      <a href="{SITE_BASE}/#services">{svc['label']}</a> &nbsp;›&nbsp;
      {city_label}
    </div>
    <div class="hero-badge">{svc['icon']} {svc['label']}</div>
    <h1>Find a <em>{svc['label']}</em><br>in {city_label}</h1>
    <p class="hero-sub">
      HealUSA connects you with trusted dental professionals in {city_label}, {state_label}.
      Same-day appointments available — accepting most insurance plans.
    </p>
    <div class="hero-phone-box">
      <span class="ph-icon">📞</span>
      <a href="{TEL}">{PHONE}</a>
    </div>
    <div class="hero-note">Free dental referral service — Independent, not affiliated with any clinic</div>
  </div>
</section>

<div class="trust">
  <div class="wrap trust-inner">
    <div class="trust-item"><div class="trust-num">50</div><div class="trust-label">States Covered</div></div>
    <div class="trust-item"><div class="trust-num">24/7</div><div class="trust-label">Support Available</div></div>
    <div class="trust-item"><div class="trust-num">100%</div><div class="trust-label">Free Service</div></div>
    <div class="trust-item"><div class="trust-num">Same Day</div><div class="trust-label">Appointments</div></div>
    <div class="trust-item"><div class="trust-num">All Plans</div><div class="trust-label">Insurance Accepted</div></div>
  </div>
</div>

<div class="main-layout">
  <article class="article" id="guide">
    {body}
  </article>

  <aside class="sidebar">
    <div class="side-card">
      <div class="badge">Free Referral</div>
      <div style="font-size:13px;color:var(--gray)">{svc['label']} — {city_label}</div>
      <div class="sp">{PHONE}</div>
      <a href="{TEL}" class="btn btn-gold">📞 Call Now — Free</a>
      <p style="font-size:11px;color:var(--gray);margin-top:10px">Independent service · not affiliated with any clinic</p>
    </div>

    <div class="service-card">
      <h4>🦷 Our Services</h4>
      {_build_service_links(city_label)}
    </div>

    <div class="side-links">
      <h4>Quick Links</h4>
      <a href="{SITE_BASE}/#services">All Services</a>
      <a href="{SITE_BASE}/#how-it-works">How It Works</a>
      <a href="{SITE_BASE}/#faq">FAQ</a>
      <a href="{SITE_BASE}/#contact">Contact Us</a>
      <a href="{SITE_BASE}/#privacy">Privacy Policy</a>
    </div>
  </aside>
</div>

<section class="cta" id="contact">
  <div class="wrap">
    <h2>Need a {svc['label']} in {city_label}?</h2>
    <p>Our free referral service matches you with trusted dental professionals near you — fast.</p>
    <a href="{TEL}" class="cta-phone-box">📞 {PHONE}</a>
    <p style="margin-top:18px;font-size:13px;opacity:.8">
      Available 24/7 &nbsp;|&nbsp; All 50 States &nbsp;|&nbsp; Most Insurance Accepted &nbsp;|&nbsp; Same-Day Available
    </p>
  </div>
</section>

<section class="disclosure" id="disclaimer">
  <div class="wrap">
    <div style="max-width:860px;margin:0 auto;margin-bottom:16px">
      <h2 style="font-size:18px;font-weight:800;color:var(--dark);margin-bottom:6px">⚖️ Legal Disclaimer</h2>
      <p style="font-size:12px;color:var(--gray);margin-bottom:20px">Please read before using our service.</p>
    </div>
    <div class="disclosure-box">
      <h3>📌 Independent Referral Service</h3>
      <p>HealUSA is an <strong>independent dental referral service</strong> and is <strong>not affiliated with, endorsed by, or officially connected to</strong> any dental clinic, dental network, or dental insurance provider. HealUSA does not provide dental care and does not employ dentists.</p>
    </div>
    <div class="disclosure-box">
      <h3>💲 Fees &amp; Costs</h3>
      <p>HealUSA's referral service is <strong>free to callers</strong>. Dental treatment costs, fees, and insurance coverage are set entirely by the dental providers in our network and may vary. All treatment costs will be disclosed by the provider before any procedure.</p>
    </div>
    <div class="disclosure-box">
      <h3>🗺 Local Coverage — {city_label}, {state_label}</h3>
      <p>HealUSA provides dental referrals to patients near {city_label} and across <strong>all 50 United States</strong>. Our service is available to any person calling from within the United States.</p>
    </div>
    <div class="disclosure-final">
      <p><strong>By contacting HealUSA, you acknowledge:</strong> (1) you are engaging an independent referral service, not a dental provider; (2) HealUSA acts as an intermediary to connect you with dental professionals; (3) dental providers are solely responsible for treatment quality and outcomes; (4) HealUSA's referral service is free and dental treatment fees are set by individual providers.</p>
    </div>
  </div>
</section>

<footer class="footer">
  <div class="wrap">
    <div class="footer-grid">
      <div class="footer-section">
        <a href="{SITE_BASE}/" class="logo" style="margin-bottom:14px">
          <div class="logo-icon" style="background:#1e3a52">🦷</div>
          <div class="logo-text" style="color:#8facc4">Heal<span>USA</span></div>
        </a>
        <p style="font-size:13px;margin-top:10px">Free dental referral service connecting patients with trusted dentists across all 50 states.</p>
      </div>
      <div class="footer-section">
        <h4>Services</h4>
        <ul>
          <li><a href="{SITE_BASE}/#services">Emergency Dentist</a></li>
          <li><a href="{SITE_BASE}/#services">Dental Implants</a></li>
          <li><a href="{SITE_BASE}/#services">Cosmetic Dentistry</a></li>
          <li><a href="{SITE_BASE}/#services">Orthodontics</a></li>
          <li><a href="{SITE_BASE}/#services">General Dentistry</a></li>
        </ul>
      </div>
      <div class="footer-section">
        <h4>Company</h4>
        <ul>
          <li><a href="{SITE_BASE}/#about">About HealUSA</a></li>
          <li><a href="{SITE_BASE}/#how-it-works">How It Works</a></li>
          <li><a href="{SITE_BASE}/#faq">FAQ</a></li>
          <li><a href="{SITE_BASE}/#contact">Contact</a></li>
        </ul>
      </div>
      <div class="footer-section">
        <h4>Legal</h4>
        <ul>
          <li><a href="{SITE_BASE}/#privacy">Privacy Policy</a></li>
          <li><a href="{SITE_BASE}/#terms">Terms of Service</a></li>
          <li><a href="#disclaimer">Legal Disclaimer</a></li>
        </ul>
      </div>
      <div class="footer-section">
        <h4>Contact</h4>
        <p style="font-size:14px;margin-bottom:8px">📞 <a href="{TEL}">{PHONE}</a></p>
        <p style="font-size:14px">🌐 www.healusa.life</p>
        <p style="font-size:13px;margin-top:10px;color:#5a7a94">Free 24/7 Referral Line</p>
      </div>
    </div>
    <div class="footer-bottom">
      <p>&copy; {year} HealUSA. All rights reserved. | Independent dental referral service | Published: {pub_human}</p>
    </div>
  </div>
</footer>

<a href="{TEL}" class="fab" aria-label="Call HealUSA now">
  📞
  <span class="fab-text">CALL NOW</span>
</a>

<script>
function toggleMenu(){{
  const m=document.getElementById('menu');
  const h=document.getElementById('ham');
  m.classList.toggle('show');
  h.classList.toggle('active');
}}
document.addEventListener('click',e=>{{
  const m=document.getElementById('menu');
  const h=document.getElementById('ham');
  if(window.innerWidth<=768&&m&&h&&!m.contains(e.target)&&!h.contains(e.target)){{
    m.classList.remove('show');
  }}
}});
</script>

</body>
</html>'''

# ══════════════════════════════════════════
# PUBLISH TO GITHUB PAGES
# ══════════════════════════════════════════
def publish_github(pages):
    if not GITHUB_TOKEN or not GITHUB_PAGES_REPO:
        print('[GitHub] No credentials — skipping')
        return 0
    import base64
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept':        'application/vnd.github.v3+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    success = 0
    published_slugs = []

    for page in pages:
        try:
            content  = base64.b64encode(page['html'].encode()).decode()
            path     = f"pages/{page['slug']}"
            url      = f'https://api.github.com/repos/{GITHUB_PAGES_REPO}/contents/{path}'
            r_get    = requests.get(url, headers=headers, timeout=15)
            payload  = {
                'message': f"🦷 {page['title'][:55]}",
                'content': content,
            }
            if r_get.status_code == 200:
                payload['sha'] = r_get.json()['sha']
            r = requests.put(url, json=payload, headers=headers, timeout=30)
            if r.status_code in (200, 201):
                success += 1
                published_slugs.append(page['slug'])
                print(f"  [GitHub] ✅ {page['slug'][:55]}")
            else:
                print(f"  [GitHub] ❌ {r.status_code}")
            time.sleep(0.3)
        except Exception as e:
            print(f'  [GitHub] Error: {e}')

    # Sitemap
    if published_slugs:
        try:
            base_url  = f'{SITE_BASE}/pages'
            list_url  = f'https://api.github.com/repos/{GITHUB_PAGES_REPO}/contents/pages'
            r_list    = requests.get(list_url, headers=headers, timeout=15)
            all_slugs = []
            if r_list.status_code == 200:
                all_slugs = [f['name'] for f in r_list.json() if f['name'].endswith('.html')]
            today = datetime.now().strftime('%Y-%m-%d')
            urls_xml = '\n'.join([
                f'  <url><loc>{base_url}/{slug}</loc><lastmod>{today}</lastmod>'
                f'<changefreq>weekly</changefreq><priority>0.8</priority></url>'
                for slug in all_slugs
            ])
            sitemap = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                + urls_xml + '\n</urlset>'
            )
            sitemap_b64  = base64.b64encode(sitemap.encode()).decode()
            sitemap_url  = f'https://api.github.com/repos/{GITHUB_PAGES_REPO}/contents/sitemap.xml'
            r_get2       = requests.get(sitemap_url, headers=headers, timeout=15)
            sitemap_payload = {'message': 'Update sitemap', 'content': sitemap_b64}
            if r_get2.status_code == 200:
                sitemap_payload['sha'] = r_get2.json()['sha']
            r_s = requests.put(sitemap_url, json=sitemap_payload, headers=headers, timeout=30)
            if r_s.status_code in (200, 201):
                print(f'  [GitHub] sitemap.xml updated ({len(all_slugs)} URLs)')
            else:
                print(f'  [GitHub] sitemap error: {r_s.status_code}')
        except Exception as e:
            print(f'  [GitHub] Sitemap error: {e}')

    return success

# ══════════════════════════════════════════
# BING INDEXNOW
# ══════════════════════════════════════════
def ensure_indexnow_key_file():
    if not BING_INDEXNOW_KEY or not GITHUB_TOKEN or not GITHUB_PAGES_REPO:
        return
    import base64
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept':        'application/vnd.github.v3+json',
    }
    key_filename = f'{BING_INDEXNOW_KEY}.txt'
    url          = f'https://api.github.com/repos/{GITHUB_PAGES_REPO}/contents/{key_filename}'
    r_get        = requests.get(url, headers=headers, timeout=10)
    content_b64  = base64.b64encode(BING_INDEXNOW_KEY.encode()).decode()
    payload      = {'message': 'Add IndexNow key file', 'content': content_b64}
    if r_get.status_code == 200:
        payload['sha'] = r_get.json()['sha']
    r = requests.put(url, json=payload, headers=headers, timeout=15)
    if r.status_code in (200, 201):
        print(f'  [IndexNow] Key file {key_filename} OK')

def ping_bing(pages):
    if not BING_INDEXNOW_KEY:
        print('[Bing] No IndexNow key — skipping')
        return
    urls = [f"{SITE_BASE}/pages/{p['slug']}" for p in pages]
    payload = {
        'host':    'www.healusa.life',
        'key':     BING_INDEXNOW_KEY,
        'keyLocation': f'{SITE_BASE}/{BING_INDEXNOW_KEY}.txt',
        'urlList': urls,
    }
    try:
        r = fetch_with_retry(
            'https://api.indexnow.org/indexnow',
            method='post', json_body=payload, timeout=15,
        )
        if r and r.status_code in (200, 202):
            print(f'  [Bing] ✅ IndexNow: {len(urls)} URLs submitted')
        else:
            code = r.status_code if r else 'timeout'
            print(f'  [Bing] IndexNow: {code}')
    except Exception as e:
        print(f'  [Bing] Error: {e}')

# ══════════════════════════════════════════
# GOOGLE INDEXING API
# ══════════════════════════════════════════
def ping_google(pages):
    """Submit URLs to Google Indexing API via Service Account JWT."""
    if not GOOGLE_SERVICE_ACCOUNT_KEY or not pages:
        print('[Google Index] No service account key — skipping')
        return 0
    urls = [f"{SITE_BASE}/pages/{p['slug']}" for p in pages]
    try:
        import base64 as _b64
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding as _padding

        sa  = json.loads(GOOGLE_SERVICE_ACCOUNT_KEY)
        now = int(time.time())

        header  = _b64.urlsafe_b64encode(json.dumps({'alg':'RS256','typ':'JWT'}).encode()).rstrip(b'=').decode()
        payload = _b64.urlsafe_b64encode(json.dumps({
            'iss':   sa['client_email'],
            'scope': 'https://www.googleapis.com/auth/indexing',
            'aud':   'https://oauth2.googleapis.com/token',
            'exp':   now + 3600,
            'iat':   now,
        }).encode()).rstrip(b'=').decode()

        private_key = serialization.load_pem_private_key(sa['private_key'].encode(), password=None)
        signature   = private_key.sign(f'{header}.{payload}'.encode(), _padding.PKCS1v15(), hashes.SHA256())
        sig         = _b64.urlsafe_b64encode(signature).rstrip(b'=').decode()
        jwt_token   = f'{header}.{payload}.{sig}'

        token_r      = requests.post('https://oauth2.googleapis.com/token',
                                     data={'grant_type':'urn:ietf:params:oauth:grant-type:jwt-bearer','assertion':jwt_token},
                                     timeout=30)
        access_token = token_r.json().get('access_token')
        if not access_token:
            print(f'[Google Index] Token failed: {token_r.text[:100]}')
            return 0

        ok = 0
        for url in urls[:200]:
            try:
                r = requests.post(
                    'https://indexing.googleapis.com/v3/urlNotifications:publish',
                    headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'},
                    json={'url': url, 'type': 'URL_UPDATED'},
                    timeout=15,
                )
                if r.status_code == 200:
                    ok += 1
                    print(f'  [Google Index] ✅ {url}')
                else:
                    print(f'  [Google Index] ❌ {r.status_code}')
                time.sleep(0.5)
            except Exception as e:
                print(f'  [Google Index] {e}')

        print(f'[Google Index] {ok}/{len(urls)} URLs submitted')
        return ok

    except ImportError:
        print('[Google Index] Install cryptography: pip install cryptography')
        return 0
    except Exception as e:
        print(f'[Google Index] Error: {e}')
        return 0


# ══════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════
def main():
    print('\n' + '='*60)
    print('HealUSA Dental SEO Agent v1')
    print(f"Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print('='*60 + '\n')

    published, daily = load_slugs()
    today_str  = datetime.now().strftime('%Y-%m-%d')
    today_count = daily.get(today_str, 0)
    MAX_DAILY   = 50
    remaining   = MAX_DAILY - today_count

    print(f'[Status] Published total: {len(published)} | Today: {today_count} | Remaining: {remaining}')

    if remaining <= 0:
        print('[Status] Daily quota reached — exiting')
        return

    # STEP 1: Queue
    stored_queue = load_daily_queue()
    if stored_queue:
        print(f'[STEP 1] Resuming queue — {len(stored_queue)} items left')
        queue = stored_queue
    else:
        print('[STEP 1] Building fresh keyword queue...')
        queue = build_keyword_queue(published)
        save_daily_queue(queue, today_str)

    print(f'[STEP 1] Queue size: {len(queue)}')

    run_slice      = queue[:MAX_PER_RUN][:remaining]
    leftover       = queue[len(run_slice):]

    print(f'\nThis run: {len(run_slice)} pages\n')
    for i, item in enumerate(run_slice):
        svc = SERVICES.get(item.get('service', 'general'), SERVICES['general'])
        print(f'  {i+1}. [{item["source"].upper()}] {svc["icon"]} {item["kw"][:55]}')

    # STEP 2: Generate
    print(f'\n[STEP 2] Generating {len(run_slice)} pages...')
    generated = []
    errors    = 0

    for i, item in enumerate(run_slice):
        print(f'\n[{i+1}/{len(run_slice)}] {item["source"].upper()} | {item["kw"][:55]}')
        try:
            page = generate_article(item)
            if page:
                generated.append(page)
                published.add(page['slug'].replace('.html', ''))
                print(f"  ✅ {page['words']}w | {SERVICES[page['service']]['label']}")
        except Exception as e:
            errors += 1
            print(f'  ❌ Error: {e}')
        if i < len(run_slice) - 1:
            time.sleep(4)

    save_daily_queue(leftover, today_str)

    # STEP 3: Publish
    if generated:
        print(f'\n[STEP 3] Publishing {len(generated)} pages...')
        gh_ok = publish_github(generated)
        ensure_indexnow_key_file()
        ping_bing(generated)
        ping_google(generated)

        daily = update_today_count(daily, today_count + len(generated))
        save_slugs(published, daily)

        by_svc = {}
        for p in generated:
            by_svc[p['service']] = by_svc.get(p['service'], 0) + 1

        print(f'\n{"="*60}')
        print('SUMMARY:')
        print(f'  Generated:     {len(generated)} pages')
        for svc_key, cnt in sorted(by_svc.items()):
            svc = SERVICES[svc_key]
            print(f'  {svc["icon"]} {svc["label"]:<22} {cnt} pages')
        print(f'  Errors:        {errors}')
        print(f'  GitHub:        {gh_ok} published')
        print(f'  Total slugs:   {len(published)}')
        print(f'  Queue left:    {len(leftover)}')
        print(f'{"="*60}\n')
    else:
        print('\nNo pages generated this run.')

if __name__ == '__main__':
    main()

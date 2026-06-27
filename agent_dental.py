"""
HealUSA Dental SEO Agent v1
Publishes dental landing pages directly onto the healusa.life GitHub Pages repo.
Template matches healusa.life homepage exactly (blue/gold palette, Playfair Display + DM Sans).

Daily quota: 70 pages/day — 7 categories × 10 pages
  - 10 National USA (broad dental)
  - 10 States
  - 10 Cities XL (pop > 500K)
  - 10 Cities L  (pop 200K–500K)
  - 10 Cities M  (pop 75K–200K)
  - 10 Cities S  (pop 20K–75K)
  - 10 Cities XS (pop < 20K)

Keywords split:
  - 10/day → Bing-focused (IndexNow)
  - 10/day → Google-focused (Indexing API)
  - 50/day → standard

Phone: (844) 833-0097
"""

import os
import json
import time
import random
import hashlib
import requests
import itertools
from datetime import datetime
from pathlib import Path

# ══════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════
PHONE      = '(844) 833-0097'
TEL        = 'tel:+18448330097'
SITE_URL   = os.environ.get('HEALUSA_SITE_URL', 'https://www.healusa.life').rstrip('/')

GEMINI_API_KEY  = os.environ.get('GEMINI_API_KEY', '').strip()
GROQ_API_KEY    = os.environ.get('GROQ_API_KEY', '').strip()
GITHUB_TOKEN    = os.environ.get('GH_TOKEN', os.environ.get('GITHUB_TOKEN', '')).strip()
GITHUB_REPO     = os.environ.get('HEALUSA_PAGES_REPO', '').strip()  # e.g. "username/healusa.life"
BING_KEY        = os.environ.get('BING_INDEXNOW_KEY_DENTAL', os.environ.get('BING_INDEXNOW_KEY', '')).strip()
GOOGLE_SA_KEY   = os.environ.get('GOOGLE_SERVICE_ACCOUNT_KEY', '')

MODEL           = 'gemini-2.0-flash-lite'
MAX_PER_RUN     = 10    # 10 pages/run → 7 runs/day = 70/day
OUTPUT_DIR      = Path('pages')
SLUGS_FILE      = Path('published_slugs_dental.json')
QUEUE_FILE      = Path('daily_queue_dental.json')
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Groq key rotation ──
def _build_groq_keys():
    keys = [GROQ_API_KEY] if GROQ_API_KEY else []
    i = 2
    while True:
        k = os.environ.get(f'GROQ_API_KEY_{i}', '').strip()
        if not k:
            break
        keys.append(k)
        i += 1
    return keys

_GROQ_KEYS  = _build_groq_keys()
_groq_cycle = itertools.cycle(_GROQ_KEYS) if _GROQ_KEYS else None

# ── Gemini key rotation ──
def _build_gemini_keys():
    keys = [GEMINI_API_KEY] if GEMINI_API_KEY else []
    for i in range(2, 6):
        k = os.environ.get(f'GEMINI_API_KEY_{i}', '').strip()
        if k:
            keys.append(k)
    return keys

_GEMINI_KEYS  = _build_gemini_keys()
_gemini_cycle = itertools.cycle(_GEMINI_KEYS) if _GEMINI_KEYS else None

def _next_gemini_key():
    return next(_gemini_cycle) if _gemini_cycle else None

# ══════════════════════════════════════════
# DENTAL SERVICES DATABASE
# ══════════════════════════════════════════
DENTAL_SERVICES = [
    {'id': 'emergency',   'name': 'Emergency Dentist',        'emoji': '🚨', 'intent': 10, 'cpc': 'high'},
    {'id': 'implants',    'name': 'Dental Implants',          'emoji': '🦷', 'intent': 9,  'cpc': 'high'},
    {'id': 'pain',        'name': 'Tooth Pain Relief',        'emoji': '😣', 'intent': 10, 'cpc': 'high'},
    {'id': 'braces',      'name': 'Braces & Orthodontist',    'emoji': '😁', 'intent': 8,  'cpc': 'med'},
    {'id': 'whitening',   'name': 'Teeth Whitening',          'emoji': '✨', 'intent': 7,  'cpc': 'med'},
    {'id': 'family',      'name': 'Family Dentist',           'emoji': '👨‍👩‍👧', 'intent': 8, 'cpc': 'med'},
    {'id': 'pediatric',   'name': 'Pediatric Dentist',        'emoji': '👶', 'intent': 8,  'cpc': 'med'},
    {'id': 'oral_surgery','name': 'Oral Surgery',             'emoji': '🏥', 'intent': 9,  'cpc': 'high'},
    {'id': 'crowns',      'name': 'Crowns & Veneers',         'emoji': '👑', 'intent': 8,  'cpc': 'med'},
    {'id': 'invisalign',  'name': 'Invisalign',               'emoji': '😊', 'intent': 8,  'cpc': 'med'},
    {'id': 'dentures',    'name': 'Dentures',                 'emoji': '🦷', 'intent': 7,  'cpc': 'med'},
    {'id': 'root_canal',  'name': 'Root Canal',               'emoji': '🔬', 'intent': 10, 'cpc': 'high'},
    {'id': 'extraction',  'name': 'Tooth Extraction',         'emoji': '⚕️', 'intent': 9,  'cpc': 'high'},
    {'id': 'gum',         'name': 'Gum Disease Treatment',    'emoji': '🩺', 'intent': 8,  'cpc': 'med'},
    {'id': 'sedation',    'name': 'Sedation Dentistry',       'emoji': '💉', 'intent': 8,  'cpc': 'high'},
    {'id': 'senior',      'name': 'Senior Dental Care',       'emoji': '👴', 'intent': 7,  'cpc': 'med'},
    {'id': 'same_day',    'name': 'Same-Day Dental',          'emoji': '⚡', 'intent': 10, 'cpc': 'high'},
    {'id': 'insurance',   'name': 'Dental Insurance Help',    'emoji': '📋', 'intent': 9,  'cpc': 'high'},
    {'id': 'cleaning',    'name': 'Teeth Cleaning',           'emoji': '🧹', 'intent': 6,  'cpc': 'low'},
    {'id': 'cosmetic',    'name': 'Cosmetic Dentistry',       'emoji': '💎', 'intent': 7,  'cpc': 'med'},
]

# High-intent services — used to prioritize queue
HIGH_INTENT_SERVICES = [s for s in DENTAL_SERVICES if s['intent'] >= 9]

# ══════════════════════════════════════════
# CITY DATABASE — 7 Tiers
# ══════════════════════════════════════════

# TIER 0 — NATIONAL (USA-wide pages)
NATIONAL_PAGES = [
    {'n': 'United States', 's': 'USA', 't': 0, 'pop': 330000000},
]

# TIER 1 — STATES (50 states)
STATES_DB = [
    {'n': 'Alabama',        's': 'AL', 't': 1, 'pop': 5024279},
    {'n': 'Alaska',         's': 'AK', 't': 1, 'pop': 733391},
    {'n': 'Arizona',        's': 'AZ', 't': 1, 'pop': 7151502},
    {'n': 'Arkansas',       's': 'AR', 't': 1, 'pop': 3011524},
    {'n': 'California',     's': 'CA', 't': 1, 'pop': 39538223},
    {'n': 'Colorado',       's': 'CO', 't': 1, 'pop': 5773714},
    {'n': 'Connecticut',    's': 'CT', 't': 1, 'pop': 3605944},
    {'n': 'Delaware',       's': 'DE', 't': 1, 'pop': 989948},
    {'n': 'Florida',        's': 'FL', 't': 1, 'pop': 21538187},
    {'n': 'Georgia',        's': 'GA', 't': 1, 'pop': 10711908},
    {'n': 'Hawaii',         's': 'HI', 't': 1, 'pop': 1455271},
    {'n': 'Idaho',          's': 'ID', 't': 1, 'pop': 1839106},
    {'n': 'Illinois',       's': 'IL', 't': 1, 'pop': 12812508},
    {'n': 'Indiana',        's': 'IN', 't': 1, 'pop': 6785528},
    {'n': 'Iowa',           's': 'IA', 't': 1, 'pop': 3190369},
    {'n': 'Kansas',         's': 'KS', 't': 1, 'pop': 2937880},
    {'n': 'Kentucky',       's': 'KY', 't': 1, 'pop': 4505836},
    {'n': 'Louisiana',      's': 'LA', 't': 1, 'pop': 4657757},
    {'n': 'Maine',          's': 'ME', 't': 1, 'pop': 1362359},
    {'n': 'Maryland',       's': 'MD', 't': 1, 'pop': 6177224},
    {'n': 'Massachusetts',  's': 'MA', 't': 1, 'pop': 7029917},
    {'n': 'Michigan',       's': 'MI', 't': 1, 'pop': 10077331},
    {'n': 'Minnesota',      's': 'MN', 't': 1, 'pop': 5706494},
    {'n': 'Mississippi',    's': 'MS', 't': 1, 'pop': 2961279},
    {'n': 'Missouri',       's': 'MO', 't': 1, 'pop': 6154913},
    {'n': 'Montana',        's': 'MT', 't': 1, 'pop': 1084225},
    {'n': 'Nebraska',       's': 'NE', 't': 1, 'pop': 1961504},
    {'n': 'Nevada',         's': 'NV', 't': 1, 'pop': 3104614},
    {'n': 'New Hampshire',  's': 'NH', 't': 1, 'pop': 1377529},
    {'n': 'New Jersey',     's': 'NJ', 't': 1, 'pop': 9288994},
    {'n': 'New Mexico',     's': 'NM', 't': 1, 'pop': 2117522},
    {'n': 'New York',       's': 'NY', 't': 1, 'pop': 20201249},
    {'n': 'North Carolina', 's': 'NC', 't': 1, 'pop': 10439388},
    {'n': 'North Dakota',   's': 'ND', 't': 1, 'pop': 779094},
    {'n': 'Ohio',           's': 'OH', 't': 1, 'pop': 11799448},
    {'n': 'Oklahoma',       's': 'OK', 't': 1, 'pop': 3959353},
    {'n': 'Oregon',         's': 'OR', 't': 1, 'pop': 4237256},
    {'n': 'Pennsylvania',   's': 'PA', 't': 1, 'pop': 13002700},
    {'n': 'Rhode Island',   's': 'RI', 't': 1, 'pop': 1097379},
    {'n': 'South Carolina', 's': 'SC', 't': 1, 'pop': 5118425},
    {'n': 'South Dakota',   's': 'SD', 't': 1, 'pop': 886667},
    {'n': 'Tennessee',      's': 'TN', 't': 1, 'pop': 6910840},
    {'n': 'Texas',          's': 'TX', 't': 1, 'pop': 29145505},
    {'n': 'Utah',           's': 'UT', 't': 1, 'pop': 3271616},
    {'n': 'Vermont',        's': 'VT', 't': 1, 'pop': 643077},
    {'n': 'Virginia',       's': 'VA', 't': 1, 'pop': 8631393},
    {'n': 'Washington',     's': 'WA', 't': 1, 'pop': 7705281},
    {'n': 'West Virginia',  's': 'WV', 't': 1, 'pop': 1793716},
    {'n': 'Wisconsin',      's': 'WI', 't': 1, 'pop': 5893718},
    {'n': 'Wyoming',        's': 'WY', 't': 1, 'pop': 576851},
]

# TIER 2 — CITIES XL (pop > 500K)
CITIES_XL = [
    {'n': 'New York City',  's': 'NY', 't': 2, 'pop': 8336817},
    {'n': 'Los Angeles',    's': 'CA', 't': 2, 'pop': 3979576},
    {'n': 'Chicago',        's': 'IL', 't': 2, 'pop': 2693976},
    {'n': 'Houston',        's': 'TX', 't': 2, 'pop': 2304580},
    {'n': 'Phoenix',        's': 'AZ', 't': 2, 'pop': 1608139},
    {'n': 'Philadelphia',   's': 'PA', 't': 2, 'pop': 1603797},
    {'n': 'San Antonio',    's': 'TX', 't': 2, 'pop': 1434625},
    {'n': 'San Diego',      's': 'CA', 't': 2, 'pop': 1386932},
    {'n': 'Dallas',         's': 'TX', 't': 2, 'pop': 1304379},
    {'n': 'San Jose',       's': 'CA', 't': 2, 'pop': 1013240},
    {'n': 'Austin',         's': 'TX', 't': 2, 'pop': 961855},
    {'n': 'Jacksonville',   's': 'FL', 't': 2, 'pop': 949611},
    {'n': 'Fort Worth',     's': 'TX', 't': 2, 'pop': 918915},
    {'n': 'Columbus',       's': 'OH', 't': 2, 'pop': 905748},
    {'n': 'Charlotte',      's': 'NC', 't': 2, 'pop': 897720},
    {'n': 'Indianapolis',   's': 'IN', 't': 2, 'pop': 887642},
    {'n': 'San Francisco',  's': 'CA', 't': 2, 'pop': 881549},
    {'n': 'Seattle',        's': 'WA', 't': 2, 'pop': 737255},
    {'n': 'Denver',         's': 'CO', 't': 2, 'pop': 715522},
    {'n': 'Nashville',      's': 'TN', 't': 2, 'pop': 689447},
    {'n': 'Oklahoma City',  's': 'OK', 't': 2, 'pop': 681054},
    {'n': 'El Paso',        's': 'TX', 't': 2, 'pop': 678815},
    {'n': 'Washington DC',  's': 'DC', 't': 2, 'pop': 689545},
    {'n': 'Las Vegas',      's': 'NV', 't': 2, 'pop': 641903},
    {'n': 'Memphis',        's': 'TN', 't': 2, 'pop': 633104},
    {'n': 'Louisville',     's': 'KY', 't': 2, 'pop': 633045},
    {'n': 'Portland',       's': 'OR', 't': 2, 'pop': 652503},
    {'n': 'Baltimore',      's': 'MD', 't': 2, 'pop': 593490},
    {'n': 'Milwaukee',      's': 'WI', 't': 2, 'pop': 577222},
    {'n': 'Albuquerque',    's': 'NM', 't': 2, 'pop': 564559},
    {'n': 'Tucson',         's': 'AZ', 't': 2, 'pop': 542629},
    {'n': 'Fresno',         's': 'CA', 't': 2, 'pop': 542107},
    {'n': 'Sacramento',     's': 'CA', 't': 2, 'pop': 513624},
]

# TIER 3 — CITIES L (pop 200K–500K)
CITIES_L = [
    {'n': 'Mesa',           's': 'AZ', 't': 3, 'pop': 504258},
    {'n': 'Kansas City',    's': 'MO', 't': 3, 'pop': 495327},
    {'n': 'Atlanta',        's': 'GA', 't': 3, 'pop': 498715},
    {'n': 'Omaha',          's': 'NE', 't': 3, 'pop': 478192},
    {'n': 'Colorado Springs','s':'CO', 't': 3, 'pop': 472688},
    {'n': 'Raleigh',        's': 'NC', 't': 3, 'pop': 467665},
    {'n': 'Long Beach',     's': 'CA', 't': 3, 'pop': 466742},
    {'n': 'Virginia Beach', 's': 'VA', 't': 3, 'pop': 459470},
    {'n': 'Minneapolis',    's': 'MN', 't': 3, 'pop': 429606},
    {'n': 'Tampa',          's': 'FL', 't': 3, 'pop': 399700},
    {'n': 'New Orleans',    's': 'LA', 't': 3, 'pop': 383997},
    {'n': 'Arlington',      's': 'TX', 't': 3, 'pop': 394266},
    {'n': 'Bakersfield',    's': 'CA', 't': 3, 'pop': 380874},
    {'n': 'Honolulu',       's': 'HI', 't': 3, 'pop': 345064},
    {'n': 'Anaheim',        's': 'CA', 't': 3, 'pop': 346824},
    {'n': 'Aurora',         's': 'CO', 't': 3, 'pop': 366623},
    {'n': 'Santa Ana',      's': 'CA', 't': 3, 'pop': 310227},
    {'n': 'Corpus Christi', 's': 'TX', 't': 3, 'pop': 316381},
    {'n': 'Riverside',      's': 'CA', 't': 3, 'pop': 314998},
    {'n': 'Lexington',      's': 'KY', 't': 3, 'pop': 322570},
    {'n': 'St. Louis',      's': 'MO', 't': 3, 'pop': 300576},
    {'n': 'Pittsburgh',     's': 'PA', 't': 3, 'pop': 302971},
    {'n': 'Stockton',       's': 'CA', 't': 3, 'pop': 320804},
    {'n': 'Cincinnati',     's': 'OH', 't': 3, 'pop': 309317},
    {'n': 'St. Paul',       's': 'MN', 't': 3, 'pop': 311527},
    {'n': 'Toledo',         's': 'OH', 't': 3, 'pop': 270871},
    {'n': 'Greensboro',     's': 'NC', 't': 3, 'pop': 299035},
    {'n': 'Newark',         's': 'NJ', 't': 3, 'pop': 311549},
    {'n': 'Plano',          's': 'TX', 't': 3, 'pop': 287677},
    {'n': 'Henderson',      's': 'NV', 't': 3, 'pop': 320189},
    {'n': 'Orlando',        's': 'FL', 't': 3, 'pop': 307573},
    {'n': 'Lincoln',        's': 'NE', 't': 3, 'pop': 289102},
    {'n': 'Buffalo',        's': 'NY', 't': 3, 'pop': 278349},
    {'n': 'Fort Wayne',     's': 'IN', 't': 3, 'pop': 264488},
    {'n': 'Jersey City',    's': 'NJ', 't': 3, 'pop': 292449},
    {'n': 'Chandler',       's': 'AZ', 't': 3, 'pop': 261165},
    {'n': 'St. Petersburg', 's': 'FL', 't': 3, 'pop': 258308},
    {'n': 'Laredo',         's': 'TX', 't': 3, 'pop': 261639},
    {'n': 'Norfolk',        's': 'VA', 't': 3, 'pop': 245115},
    {'n': 'Madison',        's': 'WI', 't': 3, 'pop': 269840},
    {'n': 'Durham',         's': 'NC', 't': 3, 'pop': 278993},
    {'n': 'Lubbock',        's': 'TX', 't': 3, 'pop': 257141},
    {'n': 'Winston-Salem',  's': 'NC', 't': 3, 'pop': 249545},
    {'n': 'Garland',        's': 'TX', 't': 3, 'pop': 246018},
    {'n': 'Glendale',       's': 'AZ', 't': 3, 'pop': 248325},
    {'n': 'Hialeah',        's': 'FL', 't': 3, 'pop': 223109},
    {'n': 'Reno',           's': 'NV', 't': 3, 'pop': 255601},
    {'n': 'Baton Rouge',    's': 'LA', 't': 3, 'pop': 220236},
    {'n': 'Irvine',         's': 'CA', 't': 3, 'pop': 307670},
    {'n': 'Chesapeake',     's': 'VA', 't': 3, 'pop': 244835},
]

# TIER 4 — CITIES M (pop 75K–200K)
CITIES_M = [
    {'n': 'Scottsdale',     's': 'AZ', 't': 4, 'pop': 258069},
    {'n': 'North Las Vegas','s': 'NV', 't': 4, 'pop': 262527},
    {'n': 'Irving',         's': 'TX', 't': 4, 'pop': 239798},
    {'n': 'Fremont',        's': 'CA', 't': 4, 'pop': 230504},
    {'n': 'Birmingham',     's': 'AL', 't': 4, 'pop': 212237},
    {'n': 'Rochester',      's': 'NY', 't': 4, 'pop': 206284},
    {'n': 'San Bernardino', 's': 'CA', 't': 4, 'pop': 222101},
    {'n': 'Spokane',        's': 'WA', 't': 4, 'pop': 228989},
    {'n': 'Des Moines',     's': 'IA', 't': 4, 'pop': 212031},
    {'n': 'Modesto',        's': 'CA', 't': 4, 'pop': 218464},
    {'n': 'Fayetteville',   's': 'NC', 't': 4, 'pop': 211657},
    {'n': 'Tacoma',         's': 'WA', 't': 4, 'pop': 219346},
    {'n': 'Oxnard',         's': 'CA', 't': 4, 'pop': 202063},
    {'n': 'Fontana',        's': 'CA', 't': 4, 'pop': 208393},
    {'n': 'Columbus',       's': 'GA', 't': 4, 'pop': 200579},
    {'n': 'Montgomery',     's': 'AL', 't': 4, 'pop': 199432},
    {'n': 'Moreno Valley',  's': 'CA', 't': 4, 'pop': 208634},
    {'n': 'Shreveport',     's': 'LA', 't': 4, 'pop': 187593},
    {'n': 'Akron',          's': 'OH', 't': 4, 'pop': 190469},
    {'n': 'Yonkers',        's': 'NY', 't': 4, 'pop': 211464},
    {'n': 'Huntington Beach','s':'CA', 't': 4, 'pop': 198711},
    {'n': 'Little Rock',    's': 'AR', 't': 4, 'pop': 202591},
    {'n': 'Glendale',       's': 'CA', 't': 4, 'pop': 196543},
    {'n': 'Augusta',        's': 'GA', 't': 4, 'pop': 202081},
    {'n': 'Amarillo',       's': 'TX', 't': 4, 'pop': 200393},
    {'n': 'Huntsville',     's': 'AL', 't': 4, 'pop': 190582},
    {'n': 'Grand Rapids',   's': 'MI', 't': 4, 'pop': 198917},
    {'n': 'Salt Lake City', 's': 'UT', 't': 4, 'pop': 200567},
    {'n': 'Tallahassee',    's': 'FL', 't': 4, 'pop': 196169},
    {'n': 'Knoxville',      's': 'TN', 't': 4, 'pop': 190740},
    {'n': 'Worcester',      's': 'MA', 't': 4, 'pop': 185877},
    {'n': 'Newport News',   's': 'VA', 't': 4, 'pop': 179225},
    {'n': 'Brownsville',    's': 'TX', 't': 4, 'pop': 182781},
    {'n': 'Providence',     's': 'RI', 't': 4, 'pop': 178042},
    {'n': 'Garden Grove',   's': 'CA', 't': 4, 'pop': 171949},
    {'n': 'Oceanside',      's': 'CA', 't': 4, 'pop': 175742},
    {'n': 'Chattanooga',    's': 'TN', 't': 4, 'pop': 181099},
    {'n': 'Fort Lauderdale','s': 'FL', 't': 4, 'pop': 182595},
    {'n': 'Rancho Cucamonga','s':'CA', 't': 4, 'pop': 174354},
    {'n': 'Santa Clarita',  's': 'CA', 't': 4, 'pop': 228673},
    {'n': 'Port Arthur',    's': 'TX', 't': 4, 'pop': 55819},
    {'n': 'Grand Prairie',  's': 'TX', 't': 4, 'pop': 196100},
    {'n': 'Tempe',          's': 'AZ', 't': 4, 'pop': 185038},
    {'n': 'Overland Park',  's': 'KS', 't': 4, 'pop': 197238},
    {'n': 'Ontario',        's': 'CA', 't': 4, 'pop': 175265},
    {'n': 'Eugene',         's': 'OR', 't': 4, 'pop': 176654},
    {'n': 'Cape Coral',     's': 'FL', 't': 4, 'pop': 194016},
    {'n': 'Pembroke Pines', 's': 'FL', 't': 4, 'pop': 171178},
    {'n': 'Fort Collins',   's': 'CO', 't': 4, 'pop': 169810},
    {'n': 'Jackson',        's': 'MS', 't': 4, 'pop': 153701},
]

# TIER 5 — CITIES S (pop 20K–75K)
CITIES_S = [
    {'n': 'Surprise',       's': 'AZ', 't': 5, 'pop': 134085},
    {'n': 'Peoria',         's': 'AZ', 't': 5, 'pop': 190985},
    {'n': 'Elk Grove',      's': 'CA', 't': 5, 'pop': 176124},
    {'n': 'Salem',          's': 'OR', 't': 5, 'pop': 169798},
    {'n': 'Warren',         's': 'MI', 't': 5, 'pop': 138247},
    {'n': 'Corona',         's': 'CA', 't': 5, 'pop': 152374},
    {'n': 'Sterling Heights','s':'MI', 't': 5, 'pop': 132438},
    {'n': 'West Valley City','s':'UT', 't': 5, 'pop': 140230},
    {'n': 'Columbia',       's': 'SC', 't': 5, 'pop': 136632},
    {'n': 'Hampton',        's': 'VA', 't': 5, 'pop': 137436},
    {'n': 'Pasadena',       's': 'TX', 't': 5, 'pop': 151950},
    {'n': 'Killeen',        's': 'TX', 't': 5, 'pop': 153095},
    {'n': 'Hayward',        's': 'CA', 't': 5, 'pop': 162954},
    {'n': 'Pomona',         's': 'CA', 't': 5, 'pop': 151348},
    {'n': 'McAllen',        's': 'TX', 't': 5, 'pop': 142210},
    {'n': 'Escondido',      's': 'CA', 't': 5, 'pop': 151038},
    {'n': 'Sunnyvale',      's': 'CA', 't': 5, 'pop': 153185},
    {'n': 'Torrance',       's': 'CA', 't': 5, 'pop': 145438},
    {'n': 'Bridgeport',     's': 'CT', 't': 5, 'pop': 148654},
    {'n': 'Paterson',       's': 'NJ', 't': 5, 'pop': 145233},
    {'n': 'Savannah',       's': 'GA', 't': 5, 'pop': 147780},
    {'n': 'Macon',          's': 'GA', 't': 5, 'pop': 157346},
    {'n': 'Clarksville',    's': 'TN', 't': 5, 'pop': 156133},
    {'n': 'Syracuse',       's': 'NY', 't': 5, 'pop': 148620},
    {'n': 'Rockford',       's': 'IL', 't': 5, 'pop': 148655},
    {'n': 'Kansas City',    's': 'KS', 't': 5, 'pop': 156607},
    {'n': 'Alexandria',     's': 'VA', 't': 5, 'pop': 159467},
    {'n': 'Palmdale',       's': 'CA', 't': 5, 'pop': 169450},
    {'n': 'Lancaster',      's': 'CA', 't': 5, 'pop': 173516},
    {'n': 'Salinas',        's': 'CA', 't': 5, 'pop': 163542},
    {'n': 'Gainesville',    's': 'FL', 't': 5, 'pop': 141085},
    {'n': 'Lakewood',       's': 'CO', 't': 5, 'pop': 157997},
    {'n': 'Lakewood',       's': 'CA', 't': 5, 'pop': 87927},
    {'n': 'Visalia',        's': 'CA', 't': 5, 'pop': 141384},
    {'n': 'Miramar',        's': 'FL', 't': 5, 'pop': 140832},
    {'n': 'Roseville',      's': 'CA', 't': 5, 'pop': 147773},
    {'n': 'Thornton',       's': 'CO', 't': 5, 'pop': 136208},
    {'n': 'Sioux Falls',    's': 'SD', 't': 5, 'pop': 192517},
    {'n': 'Springfield',    's': 'MO', 't': 5, 'pop': 167319},
    {'n': 'Pasadena',       's': 'CA', 't': 5, 'pop': 138699},
    {'n': 'Mesquite',       's': 'TX', 't': 5, 'pop': 140937},
    {'n': 'Bellevue',       's': 'WA', 't': 5, 'pop': 151854},
    {'n': 'Fullerton',      's': 'CA', 't': 5, 'pop': 143617},
    {'n': 'West Palm Beach','s': 'FL', 't': 5, 'pop': 116898},
    {'n': 'Cedar Rapids',   's': 'IA', 't': 5, 'pop': 137710},
    {'n': 'Hampton',        's': 'VA', 't': 5, 'pop': 137436},
    {'n': 'Dayton',         's': 'OH', 't': 5, 'pop': 137644},
    {'n': 'Waco',           's': 'TX', 't': 5, 'pop': 136436},
    {'n': 'Olathe',         's': 'KS', 't': 5, 'pop': 139605},
    {'n': 'Columbia',       's': 'MO', 't': 5, 'pop': 126254},
]

# TIER 6 — CITIES XS (pop < 20K / small towns)
CITIES_XS = [
    {'n': 'Naperville',     's': 'IL', 't': 6, 'pop': 149540},
    {'n': 'Aurora',         's': 'IL', 't': 6, 'pop': 197899},
    {'n': 'Joliet',         's': 'IL', 't': 6, 'pop': 150362},
    {'n': 'Oceanside',      's': 'CA', 't': 6, 'pop': 175742},
    {'n': 'Chattanooga',    's': 'TN', 't': 6, 'pop': 181099},
    {'n': 'Frisco',         's': 'TX', 't': 6, 'pop': 200490},
    {'n': 'McKinney',       's': 'TX', 't': 6, 'pop': 199177},
    {'n': 'Denton',         's': 'TX', 't': 6, 'pop': 139869},
    {'n': 'Midland',        's': 'TX', 't': 6, 'pop': 132950},
    {'n': 'Lewisville',     's': 'TX', 't': 6, 'pop': 112000},
    {'n': 'Carrollton',     's': 'TX', 't': 6, 'pop': 133836},
    {'n': 'Tyler',          's': 'TX', 't': 6, 'pop': 103551},
    {'n': 'Round Rock',     's': 'TX', 't': 6, 'pop': 119468},
    {'n': 'Abilene',        's': 'TX', 't': 6, 'pop': 123420},
    {'n': 'Beaumont',       's': 'TX', 't': 6, 'pop': 113090},
    {'n': 'Lowell',         's': 'MA', 't': 6, 'pop': 115554},
    {'n': 'Cambridge',      's': 'MA', 't': 6, 'pop': 118403},
    {'n': 'Worcester',      's': 'MA', 't': 6, 'pop': 185877},
    {'n': 'Springfield',    's': 'MA', 't': 6, 'pop': 155929},
    {'n': 'Peoria',         's': 'IL', 't': 6, 'pop': 113150},
    {'n': 'Elgin',          's': 'IL', 't': 6, 'pop': 112456},
    {'n': 'Waukegan',       's': 'IL', 't': 6, 'pop': 89078},
    {'n': 'Thousand Oaks',  's': 'CA', 't': 6, 'pop': 128731},
    {'n': 'Simi Valley',    's': 'CA', 't': 6, 'pop': 124237},
    {'n': 'Victorville',    's': 'CA', 't': 6, 'pop': 122519},
    {'n': 'Murrieta',       's': 'CA', 't': 6, 'pop': 103466},
    {'n': 'Temecula',       's': 'CA', 't': 6, 'pop': 100097},
    {'n': 'Norwalk',        's': 'CA', 't': 6, 'pop': 99302},
    {'n': 'Burbank',        's': 'CA', 't': 6, 'pop': 107337},
    {'n': 'El Monte',       's': 'CA', 't': 6, 'pop': 110723},
    {'n': 'Inglewood',      's': 'CA', 't': 6, 'pop': 111542},
    {'n': 'Downey',         's': 'CA', 't': 6, 'pop': 111772},
    {'n': 'Costa Mesa',     's': 'CA', 't': 6, 'pop': 112174},
    {'n': 'Clearwater',     's': 'FL', 't': 6, 'pop': 117292},
    {'n': 'Pompano Beach',  's': 'FL', 't': 6, 'pop': 111467},
    {'n': 'Hollywood',      's': 'FL', 't': 6, 'pop': 153067},
    {'n': 'Coral Springs',  's': 'FL', 't': 6, 'pop': 133759},
    {'n': 'Davie',          's': 'FL', 't': 6, 'pop': 105691},
    {'n': 'Lakeland',       's': 'FL', 't': 6, 'pop': 112641},
    {'n': 'Palm Bay',       's': 'FL', 't': 6, 'pop': 121088},
    {'n': 'Provo',          's': 'UT', 't': 6, 'pop': 115162},
    {'n': 'West Jordan',    's': 'UT', 't': 6, 'pop': 118336},
    {'n': 'Orem',           's': 'UT', 't': 6, 'pop': 98129},
    {'n': 'Sandy',          's': 'UT', 't': 6, 'pop': 96756},
    {'n': 'Boise',          's': 'ID', 't': 6, 'pop': 235684},
    {'n': 'Meridian',       's': 'ID', 't': 6, 'pop': 114624},
    {'n': 'Nampa',          's': 'ID', 't': 6, 'pop': 100200},
    {'n': 'Spokane Valley', 's': 'WA', 't': 6, 'pop': 102976},
    {'n': 'Kent',           's': 'WA', 't': 6, 'pop': 136588},
    {'n': 'Renton',         's': 'WA', 't': 6, 'pop': 106785},
]

# All city tiers combined for easy lookup
ALL_LOCATIONS = NATIONAL_PAGES + STATES_DB + CITIES_XL + CITIES_L + CITIES_M + CITIES_S + CITIES_XS

TIER_NAMES = {
    0: 'National USA',
    1: 'State',
    2: 'City XL',
    3: 'City L',
    4: 'City M',
    5: 'City S',
    6: 'City XS',
}

TIER_POOLS = {
    0: NATIONAL_PAGES,
    1: STATES_DB,
    2: CITIES_XL,
    3: CITIES_L,
    4: CITIES_M,
    5: CITIES_S,
    6: CITIES_XS,
}

# ══════════════════════════════════════════
# KEYWORD TEMPLATES — High Call Intent
# ══════════════════════════════════════════
YEAR = datetime.now().year

# National templates (tier 0) — broad USA dental
NATIONAL_KW_TEMPLATES = [
    "emergency dentist near me open now {year}",
    "find a dentist near me same day appointment",
    "affordable dentist near me no insurance {year}",
    "best dentist near me accepting new patients",
    "emergency tooth pain relief near me {year}",
    "dental implants near me cost {year}",
    "dentist open on weekends near me",
    "pediatric dentist near me accepting patients",
    "orthodontist near me braces cost {year}",
    "root canal dentist near me same day",
    "dentist near me that accepts medicaid {year}",
    "invisalign dentist near me cost consultation",
    "same day dental appointment near me {year}",
    "tooth extraction near me same day emergency",
    "dental crowns near me cost and procedure",
    "dentist for seniors near me medicare {year}",
    "sedation dentist near me anxiety {year}",
    "cosmetic dentist near me teeth whitening",
    "dental emergency hotline call now nationwide",
    "find affordable dental care near me {year}",
]

# State templates
STATE_KW_TEMPLATES = [
    "emergency dentist {location} {state} open now",
    "find a dentist in {location} {state} {year}",
    "best dentist {location} accepting new patients",
    "affordable dental care {location} {state}",
    "dental implants {location} {state} cost {year}",
    "orthodontist {location} {state} braces {year}",
    "pediatric dentist {location} {state}",
    "same day dentist {location} {state}",
    "root canal dentist {location} {state} near me",
    "tooth pain emergency {location} {state} {year}",
    "dentist accepting medicaid {location} {state}",
    "cosmetic dentist {location} {state} {year}",
    "dentures {location} {state} affordable",
    "oral surgeon {location} {state} near me",
    "teeth whitening {location} {state} best price",
]

# City templates (used for tiers 2–6)
CITY_KW_TEMPLATES = [
    "emergency dentist {location} {state} open now",
    "dentist near me {location} {state} same day",
    "affordable dentist {location} {state} no insurance",
    "best dentist in {location} {state} {year}",
    "dental implants {location} {state} cost",
    "orthodontist {location} {state} braces invisalign",
    "pediatric dentist {location} {state} near me",
    "root canal dentist {location} {state}",
    "tooth extraction {location} {state} emergency",
    "dental crowns {location} {state} near me",
    "teeth whitening {location} {state} best",
    "sedation dentist {location} {state} anxiety",
    "dentist open saturday {location} {state}",
    "cosmetic dentist {location} {state} {year}",
    "same day dental implants {location} {state}",
    "gum disease treatment {location} {state}",
    "dentures {location} {state} affordable near me",
    "oral surgery {location} {state} near me",
    "dentist for seniors {location} {state} medicare",
    "invisalign {location} {state} cost consultation",
    "tooth pain relief {location} {state} call now",
    "dental emergency {location} {state} open today",
    "family dentist {location} {state} accepting patients",
    "teeth cleaning {location} {state} affordable",
    "veneers {location} {state} cosmetic dentist",
]

# Bing-optimized (question format — performs better on Bing)
BING_KW_TEMPLATES = [
    "how to find emergency dentist {location} {state}",
    "what is the cost of dental implants {location} {state}",
    "how much does a root canal cost {location} {state}",
    "where to find affordable dentist {location} {state} no insurance",
    "how to get same day dental appointment {location} {state}",
    "which dentist accepts medicaid {location} {state}",
    "how much do braces cost {location} {state} {year}",
    "what to do when you have tooth pain {location} {state}",
    "how to find pediatric dentist {location} {state}",
    "what does teeth whitening cost {location} {state}",
]

# Google-optimized (informational + high intent mix)
GOOGLE_KW_TEMPLATES = [
    "emergency dental care {location} {state} {year}",
    "dental implant specialist {location} {state}",
    "sedation dentistry {location} {state} cost",
    "best orthodontist {location} {state} reviews",
    "24 hour emergency dentist {location} {state}",
    "dental insurance alternatives {location} {state}",
    "tooth extraction recovery dentist {location} {state}",
    "cosmetic dental procedures {location} {state} prices",
    "wisdom tooth removal {location} {state} near me",
    "dental anxiety specialist {location} {state}",
]

# ══════════════════════════════════════════
# SLUG / DUPLICATE HELPERS
# ══════════════════════════════════════════
import re as _re

def make_slug(text):
    return _re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:70]

def is_similar_slug(new_slug, published, threshold=0.85):
    new_words = set(new_slug.replace('-', ' ').split())
    stop = {'the','a','an','in','at','for','to','of','and','or','is','are','how','get',
            'your','my','do','i','you','near','me','now','best'}
    new_words -= stop
    if not new_words:
        return False
    for pub in published:
        pub_words = set(pub.replace('-', ' ').replace('.html', '').split()) - stop
        if not pub_words:
            continue
        overlap = len(new_words & pub_words) / max(len(new_words), len(pub_words))
        if overlap >= threshold:
            return True
    return False

# ══════════════════════════════════════════
# SLUG PERSISTENCE
# ══════════════════════════════════════════
def load_slugs():
    if not SLUGS_FILE.exists():
        return set(), {}, {}
    try:
        with open(SLUGS_FILE) as f:
            data = json.load(f)
        slugs = set(data.get('slugs', []))
        daily = data.get('daily', {})
        platform = data.get('platform', {})
        return slugs, daily, platform
    except Exception:
        return set(), {}, {}

def save_slugs(slugs, daily=None, platform=None):
    today = datetime.now().strftime('%Y-%m-%d')
    existing_dated = {}
    if SLUGS_FILE.exists():
        try:
            with open(SLUGS_FILE) as f:
                data = json.load(f)
            existing_dated = data.get('dated', {})
        except Exception:
            pass
    for slug in slugs:
        if slug not in existing_dated:
            existing_dated[slug] = today
    with open(SLUGS_FILE, 'w') as f:
        json.dump({
            'slugs': list(slugs),
            'daily': daily or {},
            'dated': existing_dated,
            'platform': platform or {},
        }, f)

def get_today_count(daily):
    return daily.get(datetime.now().strftime('%Y-%m-%d'), 0)

def update_today_count(daily, count):
    daily[datetime.now().strftime('%Y-%m-%d')] = count
    return daily

def load_daily_queue():
    today = datetime.now().strftime('%Y-%m-%d')
    if not QUEUE_FILE.exists():
        return [], today
    try:
        with open(QUEUE_FILE) as f:
            data = json.load(f)
        if data.get('date') != today:
            return [], today
        return data.get('items', []), today
    except Exception:
        return [], today

def save_daily_queue(items, date_str):
    with open(QUEUE_FILE, 'w') as f:
        json.dump({'date': date_str, 'items': items}, f)

# ══════════════════════════════════════════
# KEYWORD BUILDER — 70 per day, 7 categories × 10
# ══════════════════════════════════════════
def build_keyword(template, loc, year=YEAR):
    """Fill a keyword template for a given location dict."""
    return template.format(
        location=loc['n'],
        state=loc['s'],
        year=year,
    )

def build_daily_queue():
    """
    Build 70 keyword items for today across 7 tiers.
    Each tier contributes exactly 10 items.
    Within each tier: 7 standard + 1-2 Bing-focused + 1-2 Google-focused.
    """
    queue = []
    year = datetime.now().year

    for tier in range(7):
        pool = TIER_POOLS[tier]
        candidates = pool.copy()
        random.shuffle(candidates)

        # Choose 10 locations from this tier (wrap if pool is small)
        tier_items = []
        for i in range(10):
            loc = candidates[i % len(candidates)]
            # Choose keyword template
            if tier == 0:
                kw_template = random.choice(NATIONAL_KW_TEMPLATES)
                kw = kw_template.format(year=year)
            elif tier == 1:
                kw_template = random.choice(STATE_KW_TEMPLATES)
                kw = build_keyword(kw_template, loc, year)
            else:
                kw_template = random.choice(CITY_KW_TEMPLATES)
                kw = build_keyword(kw_template, loc, year)

            # Assign search engine focus (10 Bing + 10 Google spread across tiers)
            if i in [3, 7]:   # 2 Bing-focused per tier = 14 total (capped at 10 in submission)
                se_focus = 'bing'
                if tier >= 2:
                    kw = build_keyword(random.choice(BING_KW_TEMPLATES), loc, year)
            elif i in [5, 9]:  # 2 Google-focused per tier
                se_focus = 'google'
                if tier >= 2:
                    kw = build_keyword(random.choice(GOOGLE_KW_TEMPLATES), loc, year)
            else:
                se_focus = 'standard'

            # Pick a primary dental service for this page
            service = random.choice(HIGH_INTENT_SERVICES if i < 5 else DENTAL_SERVICES)

            tier_items.append({
                'kw': kw,
                'location': loc,
                'service': service,
                'tier': tier,
                'tier_name': TIER_NAMES[tier],
                'se_focus': se_focus,
            })

        queue.extend(tier_items)
        print(f'  [Tier {tier}] {TIER_NAMES[tier]}: {len(tier_items)} keywords built')

    print(f'[Queue] Total: {len(queue)} keywords across 7 tiers')
    return queue

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
                time.sleep(wait)
                continue
            return r
        except Exception as e:
            wait = backoff * (2 ** attempt) + random.uniform(0, 1)
            print(f'    [retry] {url[:55]} → {e}, waiting {wait:.1f}s')
            time.sleep(wait)
    return None

# ══════════════════════════════════════════
# LLM — Groq primary, Gemini fallback
# ══════════════════════════════════════════
def call_api(prompt):
    # ── 1. Groq ──
    if _GROQ_KEYS:
        for attempt in range(len(_GROQ_KEYS)):
            key = next(_groq_cycle)
            try:
                r = requests.post(
                    'https://api.groq.com/openai/v1/chat/completions',
                    headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                    json={
                        'model': 'llama-3.3-70b-versatile',
                        'messages': [{'role': 'user', 'content': prompt}],
                        'max_tokens': 2800, 'temperature': 0.7,
                    },
                    timeout=60
                )
                if r.status_code == 200:
                    return r.json()['choices'][0]['message']['content']
                if r.status_code == 429:
                    print(f'  [Groq key#{attempt+1}] 429 — rotating')
                    time.sleep(3)
                    continue
            except Exception as e:
                print(f'  [Groq] attempt {attempt+1}: {e}')
                time.sleep(3)

    # ── 2. Gemini fallback ──
    if not _GEMINI_KEYS:
        raise Exception('No API keys available')
    for attempt in range(len(_GEMINI_KEYS) * 2):
        key = _next_gemini_key()
        try:
            url = f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={key}'
            r = requests.post(
                url,
                json={
                    'contents': [{'parts': [{'text': prompt}]}],
                    'generationConfig': {'maxOutputTokens': 2800, 'temperature': 0.7},
                },
                headers={'Content-Type': 'application/json'},
                timeout=60
            )
            if r.status_code == 200:
                return r.json()['candidates'][0]['content']['parts'][0]['text']
            if r.status_code == 429:
                wait = 8 * (attempt + 1)
                print(f'  [Gemini key#{attempt % len(_GEMINI_KEYS) + 1}] 429 — rotating, wait {wait}s')
                time.sleep(wait)
                continue
        except Exception as e:
            print(f'  [Gemini] attempt {attempt+1}: {e}')
            time.sleep(5)

    raise Exception('All API keys exhausted')

# ══════════════════════════════════════════
# ANTI-SPAM CHECK
# ══════════════════════════════════════════
def anti_spam_check(content, keyword):
    words = content.lower().split()
    total = len(words)
    if total < 700:
        return False, f'Too short: {total}w'
    kw_words = keyword.lower().split()
    kw_count = sum(1 for w in words if w in kw_words)
    density = (kw_count / total) * 100 if total > 0 else 0
    if density > 8.0:
        return False, f'KW density too high: {density:.1f}%'
    for phrase in ['as an AI', 'I cannot', 'language model', 'I apologize', 'as an assistant']:
        if phrase.lower() in content.lower():
            return False, f'AI fingerprint: {phrase}'
    return True, f'PASS ({total}w, density {density:.1f}%)'

# ══════════════════════════════════════════
# CALL INTENT FILTER
# ══════════════════════════════════════════
HIGH_INTENT_KW = [
    'emergency','now','today','pain','urgent','asap','open','call','same day','immediate',
    'near me','find','appointment','help','affordable','cost','how much','price',
    'need','accept','medicaid','insurance','anxiety','scared','extraction','implant',
    'root canal','swollen','bleeding','broken','cracked','missing tooth',
]
LOW_INTENT_KW  = ['history','statistics','research','wikipedia','definition','theory','study','academic']

def has_call_intent(kw, min_score=25):
    kw_lower = kw.lower()
    score = 40
    for w in HIGH_INTENT_KW:
        if w in kw_lower:
            score += 7
    for w in LOW_INTENT_KW:
        if w in kw_lower:
            score -= 15
    return min(max(score, 0), 100) >= min_score

# ══════════════════════════════════════════
# RELATED PAGES (internal links)
# ══════════════════════════════════════════
def get_related_pages(published, current_slug, tier, state, max_links=4):
    related = []
    for slug in list(published):
        if slug == current_slug:
            continue
        # Prefer same-state or same-tier
        if state.lower() in slug or TIER_NAMES.get(tier, '').lower().replace(' ', '-') in slug:
            related.append(slug)
        if len(related) >= max_links:
            break
    # Fill remainder
    remaining = list(published - {current_slug} - set(related))
    random.shuffle(remaining)
    related += remaining[:max_links - len(related)]
    return related[:max_links]

def build_internal_links_html(related, tier):
    if not related:
        return ''
    links = ''.join(
        f'<li><a href="{SITE_URL}/pages/{slug}" style="color:var(--blue);text-decoration:none">'
        f'🦷 {slug.replace("-", " ").replace(".html", "").title()}</a></li>'
        for slug in related
    )
    return f'''<div style="background:#f0f8ff;border:1px solid #d0e8f5;border-radius:12px;padding:22px;margin:32px 0">
<h3 style="font-family:\'Playfair Display\',serif;color:#065a94;font-size:18px;margin-bottom:12px">🔗 Related Dental Resources</h3>
<ul style="list-style:none;padding:0;margin:0;display:grid;gap:8px">{links}</ul>
</div>'''

# ══════════════════════════════════════════
# GENERATE PAGE
# ══════════════════════════════════════════
def generate_page(item, published, platform_map=None):
    kw       = item['kw']
    loc      = item['location']
    service  = item['service']
    tier     = item['tier']
    year     = datetime.now().year

    city  = loc['n']
    state = loc['s']
    is_national = (tier == 0)
    is_state    = (tier == 1)

    slug = make_slug(kw)
    if slug in published:
        print(f'  ⏭ SKIP exact duplicate: {slug[:50]}')
        return None
    if is_similar_slug(slug, published):
        print(f'  ⏭ SKIP similar: {slug[:50]}')
        return None

    seed   = hashlib.md5(kw.encode()).hexdigest()[:8]
    s_idx  = hash(kw) % 4
    b_idx  = hash(kw + 'box') % 4

    # ── Location framing ──
    if is_national:
        loc_phrase   = 'anywhere in the United States'
        area_phrase  = 'nationwide'
        h1_city      = 'Near You — Nationwide'
        breadcrumb   = f'<a href="{SITE_URL}/">Healusa</a> › Nationwide'
        schema_area  = '"addressCountry": "US"'
    elif is_state:
        loc_phrase   = f'across {city}, {state}'
        area_phrase  = f'all of {city}'
        h1_city      = f'{city} Dentists — Statewide'
        breadcrumb   = f'<a href="{SITE_URL}/">Healusa</a> › <a href="{SITE_URL}/">States</a> › {city}'
        schema_area  = f'"addressRegion": "{state}"'
    else:
        loc_phrase   = f'in {city}, {state}'
        area_phrase  = f'{city}'
        h1_city      = f'{city}, {state}'
        breadcrumb   = f'<a href="{SITE_URL}/">Healusa</a> › {state} › {city}'
        schema_area  = f'"addressLocality": "{city}", "addressRegion": "{state}"'

    # ── Title ──
    title_templates = [
        f'Find a Dentist {h1_city} | Call Now — Healusa',
        f'{service["name"]} {h1_city} | Same-Day Appointments',
        f'Best Dentist {h1_city} | Healusa Dental Network',
        f'{service["name"]} Near You in {h1_city} | Call {PHONE}',
    ]
    title = title_templates[hash(kw) % len(title_templates)]

    # ── Help box variants ──
    def _box_a():
        return (
            f'<div style="background:linear-gradient(135deg,#eff6ff,#dbeafe);border:2px solid #0a7bc4;'
            f'border-radius:12px;padding:26px;margin:30px 0;text-align:center">'
            f'<div style="font-size:11px;color:#065a94;font-weight:800;letter-spacing:3px;margin-bottom:8px">'
            f'📞 CONNECT WITH A DENTAL SPECIALIST</div>'
            f'<div style="font-size:36px;font-weight:900;color:#0a7bc4">{PHONE}</div>'
            f'<div style="font-size:12px;color:#64748b;margin:8px 0 16px">Free service • Nationwide • All 50 states</div>'
            f'<a href="{TEL}" style="display:inline-block;padding:13px 40px;background:#0a7bc4;color:#fff;'
            f'border-radius:8px;font-weight:900;font-size:16px;text-decoration:none">📞 Call {PHONE}</a></div>'
        )
    def _box_b():
        return (
            f'<div style="background:#fff;border-left:6px solid #c9a84c;border-right:6px solid #0a7bc4;'
            f'padding:24px;margin:30px 0;border-radius:8px">'
            f'<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">'
            f'<div><div style="font-size:30px;font-weight:900;color:#0d1f2f">{PHONE}</div>'
            f'<div style="font-size:11px;color:#64748b;margin-top:3px">Healusa • Free Service • All 50 States</div></div>'
            f'<a href="{TEL}" style="padding:13px 26px;background:#0a7bc4;color:#fff;border-radius:8px;'
            f'font-weight:900;text-decoration:none">📞 Find a Dentist</a></div></div>'
        )
    def _box_c():
        return (
            f'<div style="background:linear-gradient(135deg,#0a7bc4,#065a94);border-radius:12px;'
            f'padding:24px;margin:30px 0;text-align:center">'
            f'<div style="color:#c9a84c;font-size:13px;font-weight:700;margin-bottom:6px">🦷 DENTAL SPECIALIST HOTLINE</div>'
            f'<div style="font-size:32px;font-weight:900;color:#fff;margin:7px 0">{PHONE}</div>'
            f'<a href="{TEL}" style="display:inline-block;padding:12px 36px;background:#c9a84c;color:#0d1f2f;'
            f'border-radius:8px;font-weight:900;font-size:15px;text-decoration:none">📞 Get Connected Now</a></div>'
        )
    def _box_d():
        return (
            f'<div style="border:1px solid #0a7bc4;border-radius:9px;padding:20px;margin:30px 0;'
            f'background:#f0f8ff;position:relative">'
            f'<div style="position:absolute;top:-10px;left:18px;background:#0a7bc4;padding:2px 10px;'
            f'border-radius:4px;font-size:9px;font-weight:800;color:#fff">🦷 HEALUSA DENTAL LINE</div>'
            f'<div style="display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center">'
            f'<div style="font-size:26px;font-weight:900;color:#0a7bc4">{PHONE}</div>'
            f'<a href="{TEL}" style="display:block;padding:11px 20px;background:#0a7bc4;color:#fff;'
            f'border-radius:8px;font-weight:900;text-decoration:none;text-align:center">📞 Call<br>Now</a></div></div>'
        )

    boxes = [_box_a, _box_b, _box_c, _box_d]
    box = boxes[b_idx]()

    # ── Content structures ──
    structures = [
        f"Local dental landing page for {city}, {state}. "
        f"1. Intro (150w): why residents of {city} use Healusa to find top-rated dentists fast. "
        f"2. Call script section [BOX]. "
        f"3. Step-by-step guide: how Healusa connects you with a dentist (at least 5 concrete steps). "
        f"4. {service['name']} section — what to expect, typical cost ranges in {city}, insurance tips. "
        f"5. Common dental problems {city} residents face (3-4 realistic scenarios). "
        f"6. Local FAQ (5-6 Q&A, mention {city} and {state}). "
        f"7. Closing CTA.",

        f"Dental guide for {city} patients. "
        f"1. Intro (150w): the gap between needing a dentist and finding a good one fast in {city}. "
        f"2. Top dental services available in {city}, {state} — list with short descriptions. "
        f"3. Call to action [BOX]. "
        f"4. How Healusa works — detailed walkthrough (numbered steps). "
        f"5. {service['name']} near {city}: what it involves, average costs, recovery time. "
        f"6. Questions to ask your dentist before treatment. "
        f"7. FAQ (5 Q&A specific to {city}). "
        f"8. Final CTA.",

        f"Practical dental help guide for {city}, {state}. "
        f"1. Intro (150w): why finding the right dentist matters and how Healusa helps. "
        f"2. [BOX] call to action. "
        f"3. Dental emergency guide: what to do for tooth pain, broken tooth, swelling — with {city} context. "
        f"4. {service['name']}: procedure, cost in {state}, insurance coverage. "
        f"5. How to choose the right dentist in {city}: 5 key criteria. "
        f"6. Insurance and payment options available in {city}, {state}. "
        f"7. FAQ (5-6 Q&A) 8. CTA.",

        f"Expert dental resource for {city}, {state} residents. "
        f"1. Intro (150w): what most patients don't know about finding a dentist in {city}. "
        f"2. Why call Healusa vs. searching online alone — specific advantages. "
        f"3. [BOX] call to action. "
        f"4. {service['name']}: deep dive — who needs it, cost in {city}, what to expect. "
        f"5. Dental anxiety: how Healusa helps nervous patients in {city}. "
        f"6. Step-by-step: what happens after you call {PHONE}. "
        f"7. FAQ (5-6 Q&A). 8. CTA.",
    ]

    prompt = f"""Write 100% UNIQUE HTML body content (no html/head/body tags). Seed:{seed}
Keyword: "{kw}"
Title: "{title}"
Location: {city}, {state} | Tier: {TIER_NAMES[tier]} | Service Focus: {service['name']} | Year: {year}
Phone: {PHONE} | Site: {SITE_URL}
Tone: warm, professional, helpful — like a trusted nationwide dental referral service landing page.

STRUCTURE: {structures[s_idx]}
REPLACE [BOX] WITH: {box}

RULES:
✅ Phone {PHONE} minimum 6 times throughout
✅ 1200+ words minimum — genuine in-depth content, not padded filler
✅ HTML inline CSS only — use these CSS vars (already defined): var(--blue), var(--blue-dark), var(--gold), var(--dark), var(--gray)
✅ NO AI phrases (as an AI, I cannot, language model, I apologize)
✅ NO repetition — every paragraph adds new information
✅ Each H2 unique and specific to {city}, {state}
✅ Keyword density MAX 2.5%
✅ p style: color:#4a6280;font-size:15px;line-height:1.9;margin-bottom:14px
✅ H2 style: color:var(--blue-dark);font-size:26px;font-weight:800;margin:32px 0 14px;border-bottom:2px solid #d0e8f5;padding-bottom:9px
✅ Mention realistic cost ranges: dental implants $1,500-$6,000; root canal $700-$1,500; braces $3,000-$8,000; whitening $300-$1,500
✅ Local detail: mention {city} neighborhoods, nearby areas, or common dental concerns in {state} where relevant
✅ Disclose clearly Healusa is a free referral service, not a dental clinic itself (once in the body)
✅ Include one numbered step-by-step list (how to book, what to expect, etc.)
✅ Include FAQ section with 5-6 specific Q&A — complete useful answers, not one-liners
✅ Mention major insurance plans: Delta Dental, Cigna, Aetna, Humana, MetLife, United Healthcare

TRUST BAR (mandatory once near the top):
<div style="display:flex;gap:20px;flex-wrap:wrap;margin:20px 0;padding:14px;background:#f0f8ff;border-radius:8px;font-size:12px;color:#4a6280">⭐ 4.9/5 Rating &nbsp;|&nbsp; 🔒 Free Service &nbsp;|&nbsp; 🦷 All Dental Services &nbsp;|&nbsp; 📞 Call Now: {PHONE} &nbsp;|&nbsp; 🌎 All 50 States</div>

CTA BUTTON (use exactly — place 3 times spaced through the article):
<div style="text-align:center;margin:30px 0">
<a href="{TEL}" style="display:inline-block;padding:16px 44px;background:var(--blue);color:#fff;border-radius:8px;font-weight:800;font-size:18px;text-decoration:none;letter-spacing:.3px">📞 Call {PHONE} — Find a Dentist Now</a>
<p style="color:#94a3b8;font-size:12px;margin-top:8px">Free service — Mon–Fri 7am–7pm | Sat 10am–5pm EST</p>
</div>"""

    print(f'  ✍ Writing: "{title[:55]}"')
    body = call_api(prompt)

    passed, msg = anti_spam_check(body, kw)
    print(f'  Anti-spam: {msg}')
    if not passed:
        return None

    # Internal links
    related = get_related_pages(published, slug, tier, state)
    internal_links_html = build_internal_links_html(related, tier)

    html = build_page(title, kw, body, loc, tier, city, state, service, internal_links_html, schema_area, breadcrumb, year, loc_phrase, area_phrase)
    filename = slug + '.html'
    (OUTPUT_DIR / filename).write_text(html, encoding='utf-8')

    return {
        'slug': filename, 'title': title, 'kw': kw,
        'tier': tier, 'tier_name': TIER_NAMES[tier],
        'city': city, 'state': state,
        'service': service['id'],
        'words': len(body.split()),
        'html': html,
        'se_focus': item.get('se_focus', 'standard'),
    }

# ══════════════════════════════════════════
# BUILD PAGE — Full HTML matching healusa.life
# ══════════════════════════════════════════
def build_page(title, kw, body, loc, tier, city, state, service, internal_links_html, schema_area, breadcrumb, year, loc_phrase='near you', area_phrase='your area'):
    slug_canonical = make_slug(kw)
    canonical = f'{SITE_URL}/pages/{slug_canonical}.html'
    og_desc = (
        f'Find a top-rated {service["name"]} {city}, {state}. '
        f'Healusa connects you with trusted dental clinics nationwide. '
        f'Call {PHONE} for same-day appointments.'
    )

    # Ticker items (dental-themed)
    ticker_items = ''.join([
        '<span>🦷 Find a Dentist Near You</span>',
        '<span>📞 Call Now — <em>' + PHONE + '</em></span>',
        '<span>⭐ 4.9/5 Patient Rating</span>',
        '<span>🔒 Free Referral Service</span>',
        '<span>🦷 Emergency Dentist Available</span>',
        '<span>✅ All Insurance Plans Accepted</span>',
        '<span>🌎 Serving All 50 States</span>',
        '<span>⚡ Same-Day Appointments</span>',
        # repeat for infinite scroll
        '<span>🦷 Find a Dentist Near You</span>',
        '<span>📞 Call Now — <em>' + PHONE + '</em></span>',
        '<span>⭐ 4.9/5 Patient Rating</span>',
        '<span>🔒 Free Referral Service</span>',
        '<span>🦷 Emergency Dentist Available</span>',
        '<span>✅ All Insurance Plans Accepted</span>',
        '<span>🌎 Serving All 50 States</span>',
        '<span>⚡ Same-Day Appointments</span>',
    ])

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="description" content="{og_desc}">
<meta name="robots" content="index,follow">
<meta name="theme-color" content="#0a7bc4">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{og_desc}">
<meta property="og:type" content="website">
<meta property="og:url" content="{canonical}">
<link rel="canonical" href="{canonical}">

<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "Dentist",
  "name": "Healusa — Nationwide Dental Clinic Network",
  "description": "Free service connecting US residents with top-rated dentists in their area.",
  "url": "{SITE_URL}/",
  "telephone": "+18448330097",
  "areaServed": {{{schema_area}, "addressCountry": "US"}},
  "openingHours": ["Mo-Fr 07:00-19:00", "Sa 10:00-17:00"],
  "priceRange": "Free Service",
  "aggregateRating": {{"@type":"AggregateRating","ratingValue":"4.9","reviewCount":"1200"}}
}}
</script>

<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{{--blue:#0a7bc4;--blue-dark:#065a94;--blue-light:#2196f3;--gold:#c9a84c;--cream:#f0f8ff;--dark:#0d1f2f;--gray:#4a6280;--light-gray:#d0e8f5}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"DM Sans",sans-serif;color:var(--dark);line-height:1.6;background:#fff}}
.ticker{{background:var(--blue-dark);color:#fff;padding:11px 0;overflow:hidden;position:sticky;top:0;z-index:100}}
.ticker-wrap{{display:flex;overflow:hidden}}
.ticker-move{{display:flex;gap:48px;animation:scroll 28s linear infinite;white-space:nowrap}}
.ticker-move span{{font-size:13px;font-weight:600;letter-spacing:.3px}}
.ticker-move span em{{color:var(--gold);font-style:normal}}
@keyframes scroll{{0%{{transform:translateX(0)}}100%{{transform:translateX(-50%)}}}}
.nav{{background:#fff;padding:14px 0;border-bottom:1px solid var(--light-gray);position:sticky;top:44px;z-index:99;box-shadow:0 2px 12px rgba(0,0,0,.06)}}
.wrap{{max-width:1200px;margin:0 auto;padding:0 24px}}
.nav-wrap{{display:flex;justify-content:space-between;align-items:center}}
.logo{{display:flex;align-items:center;gap:10px;text-decoration:none}}
.logo-icon{{width:40px;height:40px;background:var(--blue);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:20px}}
.logo-text{{font-family:"Playfair Display",serif;font-size:26px;font-weight:900;color:var(--blue-dark)}}
.logo-text span{{color:var(--gold)}}
.menu{{display:flex;gap:20px;align-items:center}}
.menu a{{color:var(--dark);text-decoration:none;font-weight:600;font-size:15px;transition:.2s}}
.menu a:hover{{color:var(--blue)}}
.btn{{display:inline-flex;align-items:center;gap:8px;padding:12px 22px;background:var(--blue);color:#fff;border-radius:8px;text-decoration:none;font-weight:700;transition:.2s;font-size:15px}}
.btn:hover{{background:var(--blue-dark);transform:translateY(-1px)}}
.btn-gold{{background:var(--gold);color:var(--dark)}}
.btn-gold:hover{{background:#b8922e}}
.btn-outline{{background:transparent;border:2px solid rgba(255,255,255,.8);color:#fff}}
.ham{{display:none;flex-direction:column;gap:5px;cursor:pointer;padding:6px}}
.ham span{{width:22px;height:2px;background:var(--dark);border-radius:2px}}
.hero{{position:relative;min-height:60vh;display:flex;align-items:center;background:linear-gradient(135deg,#0d1f2f 0%,#065a94 50%,#0a7bc4 100%)}}
.hero-overlay{{position:absolute;inset:0;background:rgba(0,0,0,0.2)}}
.hero-content{{position:relative;z-index:2;color:#fff;padding:70px 0}}
.breadcrumb{{font-size:13px;opacity:.75;margin-bottom:16px}}
.breadcrumb a{{color:#c9a84c;text-decoration:none}}
.hero-badge{{display:inline-flex;align-items:center;gap:10px;background:rgba(201,168,76,.2);border:2px solid rgba(201,168,76,.8);padding:10px 20px;border-radius:10px;font-size:15px;font-weight:800;color:#f5c518;margin-bottom:18px;letter-spacing:1px;text-transform:uppercase}}
.hero h1{{font-family:"Playfair Display",serif;font-size:48px;font-weight:900;line-height:1.1;margin-bottom:18px;text-shadow:0 2px 20px rgba(0,0,0,.3)}}
.hero h1 em{{font-style:normal;color:var(--gold)}}
.hero p{{font-size:17px;opacity:.92;max-width:560px;margin-bottom:28px;line-height:1.65}}
.hero-phone-box{{display:inline-flex;align-items:center;gap:12px;background:#f5c518;border-radius:10px;padding:14px 28px;margin-bottom:18px;box-shadow:0 6px 24px rgba(245,197,24,.4)}}
.hero-phone-box a{{font-family:"Playfair Display",serif;font-size:32px;font-weight:900;color:#0d1f17;text-decoration:none}}
.flex{{display:flex;gap:14px;flex-wrap:wrap;align-items:center}}
.trust{{background:var(--cream);border-top:3px solid var(--gold);border-bottom:1px solid var(--light-gray);padding:18px 0}}
.trust-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;text-align:center}}
.trust-item{{padding:12px}}
.trust-num{{font-family:"Playfair Display",serif;font-size:30px;font-weight:900;color:var(--blue)}}
.trust-label{{font-size:12px;color:var(--gray);margin-top:3px;font-weight:500}}
.main-layout{{max-width:1200px;margin:0 auto;padding:0 24px;display:grid;grid-template-columns:1fr 300px;gap:40px;padding-top:48px;padding-bottom:48px}}
.article h2{{color:var(--blue-dark);font-size:26px;font-weight:800;margin:32px 0 14px;border-bottom:2px solid #d0e8f5;padding-bottom:9px;font-family:"Playfair Display",serif}}
.article p{{color:#4a6280;font-size:15px;line-height:1.9;margin-bottom:14px}}
.article ul,.article ol{{padding-left:22px;margin-bottom:14px;color:#4a6280;font-size:15px;line-height:1.9}}
.side-card{{background:var(--cream);border:1px solid var(--light-gray);border-radius:14px;padding:24px;text-align:center;margin-bottom:20px;position:sticky;top:120px}}
.side-card h3{{font-family:"Playfair Display",serif;color:var(--blue-dark);margin-bottom:8px}}
.side-phone{{font-size:24px;font-weight:900;color:var(--blue);margin:12px 0}}
.side-links{{background:#fff;border:1px solid var(--light-gray);border-radius:12px;padding:18px}}
.side-links h4{{font-size:14px;color:var(--gray);margin-bottom:10px;font-weight:700}}
.side-links a{{display:block;color:var(--blue);text-decoration:none;font-size:14px;padding:5px 0;border-bottom:1px solid #f0f8ff}}
.cta-sect{{background:linear-gradient(135deg,var(--blue-dark),var(--blue));color:#fff;padding:70px 0;text-align:center}}
.cta-sect h2{{font-family:"Playfair Display",serif;font-size:38px;font-weight:900;margin-bottom:12px}}
.cta-sect p{{font-size:17px;opacity:.9;margin-bottom:24px;max-width:560px;margin-left:auto;margin-right:auto}}
.cta-phone-box{{display:inline-flex;align-items:center;gap:12px;background:#f5c518;border-radius:10px;padding:16px 32px;margin-bottom:20px;box-shadow:0 8px 30px rgba(245,197,24,.4);text-decoration:none}}
.cta-phone-box span{{font-family:"Playfair Display",serif;font-size:30px;font-weight:900;color:#0d1f17}}
.disclosure{{background:#f8fafc;border-top:1px solid var(--light-gray);padding:50px 0}}
.disclosure-box{{background:#fff;border:1px solid var(--light-gray);border-radius:10px;padding:18px;margin-bottom:14px}}
.disclosure-box h3{{font-size:14px;font-weight:700;margin-bottom:8px;color:var(--dark)}}
.disclosure-box p{{font-size:13px;color:var(--gray);line-height:1.7}}
.disclosure-final{{background:#fff3cd;border:1px solid #ffc107;border-radius:8px;padding:16px;margin-top:14px}}
.disclosure-final p{{font-size:12px;color:#664d03;line-height:1.7}}
.footer{{background:#0d1f2f;color:#94a3b8;padding:60px 0 30px}}
.footer-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:30px;margin-bottom:40px}}
.footer h4{{color:#e2e8f0;font-size:14px;font-weight:700;margin-bottom:12px}}
.footer ul{{list-style:none;padding:0}}
.footer ul li{{margin-bottom:8px}}
.footer ul a{{color:#94a3b8;text-decoration:none;font-size:14px;transition:.2s}}
.footer ul a:hover{{color:var(--gold)}}
.footer-desc{{font-size:14px;line-height:1.7}}
.footer-bottom{{border-top:1px solid rgba(255,255,255,.08);padding-top:20px;text-align:center;font-size:12px}}
.fab{{position:fixed;bottom:28px;right:28px;width:64px;height:64px;background:var(--blue);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:26px;box-shadow:0 6px 24px rgba(10,123,196,.5);z-index:999;text-decoration:none;animation:pulse 2s ease-in-out infinite}}
@keyframes pulse{{0%,100%{{transform:scale(1);box-shadow:0 6px 24px rgba(10,123,196,.5)}}50%{{transform:scale(1.08);box-shadow:0 10px 36px rgba(10,123,196,.7)}}}}
@media(max-width:768px){{
  .menu{{display:none;position:absolute;top:68px;left:0;right:0;background:#fff;flex-direction:column;padding:20px;box-shadow:0 4px 12px rgba(0,0,0,.1);z-index:98}}
  .menu.show{{display:flex}}
  .ham{{display:flex}}
  .hero h1{{font-size:28px}}
  .hero p{{font-size:15px}}
  .main-layout{{grid-template-columns:1fr}}
  .side-card{{display:none}}
  .cta-sect h2{{font-size:26px}}
}}
</style>
</head>
<body>

<div class="ticker">
  <div class="ticker-wrap">
    <div class="ticker-move">{ticker_items}</div>
  </div>
</div>

<nav class="nav">
  <div class="wrap nav-wrap">
    <a href="{SITE_URL}/" class="logo">
      <div class="logo-icon">🦷</div>
      <div class="logo-text">Heal<span>usa</span></div>
    </a>
    <button class="ham" id="ham" onclick="toggleMenu()">
      <span></span><span></span><span></span>
    </button>
    <div class="menu" id="menu">
      <a href="{SITE_URL}/#services">Services</a>
      <a href="{SITE_URL}/#why">Why Us</a>
      <a href="{SITE_URL}/#how">How It Works</a>
      <a href="{SITE_URL}/#faq">FAQ</a>
      <a href="{SITE_URL}/#contact">Contact</a>
      <a href="{TEL}" class="btn">📞 Call Now</a>
    </div>
  </div>
</nav>

<section class="hero">
  <div class="hero-overlay"></div>
  <div class="wrap hero-content">
    <div class="breadcrumb">{breadcrumb}</div>
    <div class="hero-badge">🦷 Healusa Dental Network</div>
    <h1>{title.split("|")[0].strip()}</h1>
    <p>Healusa connects you with top-rated dental clinics {loc_phrase}. Emergency care, implants, braces, whitening and more — free service, same-day appointments available.</p>
    <div class="hero-phone-box">
      <span class="ph-icon">📞</span>
      <a href="{TEL}">{PHONE}</a>
    </div>
    <div class="flex">
      <a href="{TEL}" class="btn btn-gold" style="font-size:16px;padding:14px 28px">📞 Find a Dentist Now</a>
      <a href="#guide" class="btn btn-outline">Read Guide</a>
    </div>
    <p style="margin-top:14px;font-size:13px;opacity:.7">Free service — not a dental clinic — connects you with local providers</p>
  </div>
</section>

<div class="trust">
  <div class="wrap">
    <div class="trust-grid">
      <div class="trust-item"><div class="trust-num">1,200+</div><div class="trust-label">Happy Patients</div></div>
      <div class="trust-item"><div class="trust-num">4.9★</div><div class="trust-label">Average Rating</div></div>
      <div class="trust-item"><div class="trust-num">50</div><div class="trust-label">States Covered</div></div>
      <div class="trust-item"><div class="trust-num">Free</div><div class="trust-label">Referral Service</div></div>
      <div class="trust-item"><div class="trust-num">Same Day</div><div class="trust-label">Appointments</div></div>
    </div>
  </div>
</div>

<div class="main-layout">
<article class="article" id="guide">
{body}
{internal_links_html}
</article>
<aside>
  <div class="side-card">
    <div style="font-size:13px;color:var(--gray);font-weight:700;margin-bottom:8px">🦷 FIND A DENTIST NOW</div>
    <p style="font-size:13px;color:var(--gray)">{service["name"]} — {city}, {state}</p>
    <div class="side-phone">{PHONE}</div>
    <a href="{TEL}" class="btn" style="width:100%;justify-content:center;margin-bottom:10px">📞 Call Free</a>
    <p style="font-size:11px;color:var(--gray)">Free referral service — not a clinic</p>
  </div>
  <div class="side-links">
    <h4>Dental Services</h4>
    <a href="{SITE_URL}/#services">Emergency Dentist</a>
    <a href="{SITE_URL}/#services">Dental Implants</a>
    <a href="{SITE_URL}/#services">Braces & Orthodontist</a>
    <a href="{SITE_URL}/#services">Teeth Whitening</a>
    <a href="{SITE_URL}/#services">Root Canal</a>
    <a href="{SITE_URL}/#services">Family Dentist</a>
  </div>
</aside>
</div>

<section class="cta-sect" id="contact">
  <div class="wrap">
    <h2>Find the Best Dentist in {area_phrase} — Right Now</h2>
    <p>Our specialists are standing by — get connected with the closest top-rated dental clinic in under 2 minutes. We serve all 50 states.</p>
    <a href="{TEL}" class="cta-phone-box"><span>📞 {PHONE}</span></a>
    <div class="flex" style="justify-content:center">
      <a href="{TEL}" class="btn btn-gold" style="font-size:17px;padding:16px 36px">📞 Call Now — Find a Dentist Near You</a>
    </div>
    <p style="margin-top:18px;font-size:14px;opacity:.8">Available Mon–Fri 7am–7pm | Sat 10am–5pm EST | Serving All 50 States</p>
  </div>
</section>

<section class="disclosure" id="disclaimer">
  <div class="wrap">
    <div style="max-width:860px;margin:0 auto">
      <h2 style="font-size:20px;font-weight:800;color:var(--dark);margin-bottom:6px">⚖️ Legal Disclaimer</h2>
      <div class="disclosure-box">
        <h3>📌 Independent Referral Service</h3>
        <p>Healusa is a <strong>free dental referral service</strong> and is <strong>not a dental clinic</strong>. Healusa is not affiliated with, endorsed by, or officially connected to any dental practice. All dental clinics and providers are independent.</p>
      </div>
      <div class="disclosure-box">
        <h3>🗺️ Local Coverage — {city}, {state}</h3>
        <p>Healusa provides dental referrals for residents of {city} ({state}) and across <strong>all 50 United States</strong>. Our service is available to any person calling from within the United States.</p>
      </div>
      <div class="disclosure-box">
        <h3>💲 Pricing Disclaimer</h3>
        <p>Dental pricing, insurance acceptance, and availability are set entirely by individual dental practices and are subject to change. Cost ranges mentioned on this page are estimates for reference only. Always confirm costs directly with your provider.</p>
      </div>
      <div class="disclosure-final">
        <p><strong>Important:</strong> All dental clinics and providers are independent. Healusa does not warrant or guarantee any work performed. It is the responsibility of the individual to verify that the dental specialist furnishes the necessary license and certification required for their state. All persons depicted in photos or videos are actors or models and not specialists listed on this site.</p>
      </div>
    </div>
  </div>
</section>

<footer class="footer">
  <div class="wrap">
    <div class="footer-grid">
      <div>
        <a href="{SITE_URL}/" class="logo" style="margin-bottom:14px">
          <div class="logo-icon" style="background:var(--blue-light)">🦷</div>
          <div class="logo-text" style="color:#e0e8f0">Heal<span style="color:var(--gold)">usa</span></div>
        </a>
        <p class="footer-desc">Free service connecting US residents nationwide with top-rated dentists in their area.</p>
      </div>
      <div>
        <h4>Dental Services</h4>
        <ul>
          <li><a href="{SITE_URL}/#services">Tooth Pain Relief</a></li>
          <li><a href="{SITE_URL}/#services">Dental Implants</a></li>
          <li><a href="{SITE_URL}/#services">Orthodontist &amp; Braces</a></li>
          <li><a href="{SITE_URL}/#services">Teeth Whitening</a></li>
          <li><a href="{SITE_URL}/#services">Emergency Dentist</a></li>
          <li><a href="{SITE_URL}/#services">Family Dentist</a></li>
        </ul>
      </div>
      <div>
        <h4>Company</h4>
        <ul>
          <li><a href="{SITE_URL}/#why">About Us</a></li>
          <li><a href="{SITE_URL}/#how">How It Works</a></li>
          <li><a href="{SITE_URL}/#faq">FAQ</a></li>
          <li><a href="{SITE_URL}/#contact">Contact</a></li>
        </ul>
      </div>
      <div>
        <h4>Contact</h4>
        <p style="font-size:14px;margin-bottom:8px">📞 <a href="{TEL}" style="color:#94a3b8">{PHONE}</a></p>
        <p style="font-size:14px;margin-bottom:16px">🌐 www.healusa.life</p>
        <h4>Legal</h4>
        <ul>
          <li><a href="{SITE_URL}/#faq">Privacy Policy</a></li>
          <li><a href="{SITE_URL}/#faq">Terms of Service</a></li>
          <li><a href="#disclaimer">Disclosure</a></li>
        </ul>
      </div>
    </div>
    <div class="footer-bottom">
      <p>&copy; {year} Healusa. All rights reserved. | Free Dental Referral Service | Connecting Patients Nationwide with Certified Dental Professionals Across All 50 States</p>
    </div>
  </div>
</footer>

<a href="{TEL}" class="fab" aria-label="Call us now — Find a dentist near you">📞</a>

<script>
function toggleMenu(){{
  document.getElementById("menu").classList.toggle("show");
}}
document.addEventListener("click",e=>{{
  const m=document.getElementById("menu");
  const h=document.getElementById("ham");
  if(window.innerWidth<=768&&!m.contains(e.target)&&!h.contains(e.target)){{
    m.classList.remove("show");
  }}
}});
</script>
</body>
</html>'''

# ══════════════════════════════════════════
# PUBLISH TO GITHUB PAGES
# ══════════════════════════════════════════
def publish_github(pages):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print('[GitHub] No credentials — skipping')
        return 0
    import base64
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    success = 0
    published_slugs = []
    for page in pages:
        try:
            content = base64.b64encode(page['html'].encode()).decode()
            path    = f"pages/{page['slug']}"
            url     = f'https://api.github.com/repos/{GITHUB_REPO}/contents/{path}'
            r_get   = requests.get(url, headers=headers, timeout=15)
            payload = {
                'message': f'🦷 {page["title"][:55]}',
                'content': content,
            }
            if r_get.status_code == 200:
                payload['sha'] = r_get.json()['sha']
            r = requests.put(url, json=payload, headers=headers, timeout=30)
            if r.status_code in [200, 201]:
                success += 1
                published_slugs.append(page['slug'])
                print(f'  [GitHub] ✅ {page["slug"][:50]}')
            else:
                print(f'  [GitHub] ❌ {r.status_code}: {r.text[:80]}')
            time.sleep(0.3)
        except Exception as e:
            print(f'  [GitHub] Error: {e}')

    # Update sitemap.xml
    if published_slugs:
        try:
            import base64
            base_url = f'{SITE_URL}/pages'
            list_url = f'https://api.github.com/repos/{GITHUB_REPO}/contents/pages'
            r_list   = requests.get(list_url, headers=headers, timeout=15)
            all_slugs = []
            if r_list.status_code == 200:
                all_slugs = [f['name'] for f in r_list.json() if f['name'].endswith('.html')]
            today = datetime.now().strftime('%Y-%m-%d')
            urls_xml = '\n'.join(
                f'  <url><loc>{base_url}/{slug}</loc><lastmod>{today}</lastmod>'
                f'<changefreq>daily</changefreq><priority>0.8</priority></url>'
                for slug in all_slugs
            )
            sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                       '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                       + urls_xml + '\n</urlset>')
            sitemap_b64 = base64.b64encode(sitemap.encode()).decode()
            sm_url = f'https://api.github.com/repos/{GITHUB_REPO}/contents/sitemap.xml'
            r_get2 = requests.get(sm_url, headers=headers, timeout=15)
            sm_payload = {'message': 'Update sitemap', 'content': sitemap_b64}
            if r_get2.status_code == 200:
                sm_payload['sha'] = r_get2.json()['sha']
            r_s = requests.put(sm_url, json=sm_payload, headers=headers, timeout=30)
            status = '✅' if r_s.status_code in [200, 201] else f'❌ {r_s.status_code}'
            print(f'  [GitHub] sitemap.xml {status} ({len(all_slugs)} URLs)')
        except Exception as e:
            print(f'  [GitHub] Sitemap error: {e}')

    return success

# ══════════════════════════════════════════
# BING INDEXNOW
# ══════════════════════════════════════════
def ensure_indexnow_key_file():
    if not BING_KEY or not GITHUB_REPO or not GITHUB_TOKEN:
        return None
    import base64
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    try:
        key_filename = f'{BING_KEY}.txt'
        content_b64  = base64.b64encode(BING_KEY.encode()).decode()
        url          = f'https://api.github.com/repos/{GITHUB_REPO}/contents/{key_filename}'
        r_get        = requests.get(url, headers=headers, timeout=15)
        payload      = {'message': 'Update IndexNow key', 'content': content_b64}
        if r_get.status_code == 200:
            existing_b64 = r_get.json().get('content', '').replace('\n', '')
            if existing_b64 == content_b64:
                return key_filename
            payload['sha'] = r_get.json()['sha']
        r = requests.put(url, json=payload, headers=headers, timeout=30)
        if r.status_code in (200, 201):
            print(f'  [IndexNow] ✅ key file {key_filename} verified')
            return key_filename
        print(f'  [IndexNow] ❌ {r.status_code}')
        return None
    except Exception as e:
        print(f'  [IndexNow] key file error: {e}')
        return None

def ping_bing(pages):
    if not BING_KEY:
        print('[Bing IndexNow] No key — skipping')
        return
    host         = SITE_URL.split('://', 1)[-1].rstrip('/')
    key_location = f'{SITE_URL}/{BING_KEY}.txt'
    # Prioritize Bing-focused pages, then fill up to 10
    bing_pages   = [p for p in pages if p.get('se_focus') == 'bing']
    other_pages  = [p for p in pages if p.get('se_focus') != 'bing']
    submit_pages = (bing_pages + other_pages)[:10]
    urls = [f'{SITE_URL}/pages/{p["slug"]}' for p in submit_pages]
    try:
        r = requests.post(
            'https://api.indexnow.org/indexnow',
            json={'host': host, 'key': BING_KEY, 'keyLocation': key_location, 'urlList': urls},
            headers={'Content-Type': 'application/json'},
            timeout=30,
        )
        print(f'[Bing IndexNow] {len(urls)} URLs submitted — {r.status_code}')
        if r.status_code == 403:
            print(f'  [Bing] 403 — verify key file is live at: {key_location}')
    except Exception as e:
        print(f'[Bing] Error: {e}')

# ══════════════════════════════════════════
# GOOGLE INDEXING API
# ══════════════════════════════════════════
def ping_google(pages):
    """Submit Google-focused + standard pages to Google Indexing API."""
    if not GOOGLE_SA_KEY:
        print('[Google Index] No service account key — skipping')
        return 0
    google_pages = [p for p in pages if p.get('se_focus') in ('google', 'standard')]
    urls = [f'{SITE_URL}/pages/{p["slug"]}' for p in google_pages[:10]]
    if not urls:
        print('[Google Index] No URLs to submit')
        return 0
    try:
        import base64 as _b64
        import time as _time
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding as _padding

        sa  = json.loads(GOOGLE_SA_KEY)
        now = int(_time.time())

        header = _b64.urlsafe_b64encode(
            json.dumps({'alg': 'RS256', 'typ': 'JWT'}).encode()
        ).rstrip(b'=').decode()
        payload_data = {
            'iss': sa['client_email'],
            'scope': 'https://www.googleapis.com/auth/indexing',
            'aud': 'https://oauth2.googleapis.com/token',
            'exp': now + 3600, 'iat': now,
        }
        payload_enc = _b64.urlsafe_b64encode(
            json.dumps(payload_data).encode()
        ).rstrip(b'=').decode()

        private_key = serialization.load_pem_private_key(
            sa['private_key'].encode(), password=None
        )
        sig_input = f'{header}.{payload_enc}'.encode()
        signature = private_key.sign(sig_input, _padding.PKCS1v15(), hashes.SHA256())
        sig       = _b64.urlsafe_b64encode(signature).rstrip(b'=').decode()
        jwt_token = f'{header}.{payload_enc}.{sig}'

        token_r = requests.post(
            'https://oauth2.googleapis.com/token',
            data={'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': jwt_token},
            timeout=30,
        )
        access_token = token_r.json().get('access_token')
        if not access_token:
            print(f'[Google Index] Failed to get token: {token_r.text[:80]}')
            return 0

        ok = 0
        for url in urls:
            try:
                resp = requests.post(
                    'https://indexing.googleapis.com/v3/urlNotifications:publish',
                    headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'},
                    json={'url': url, 'type': 'URL_UPDATED'},
                    timeout=20,
                )
                if resp.status_code == 200:
                    ok += 1
                    print(f'  [Google Index] ✅ {url[-50:]}')
                else:
                    print(f'  [Google Index] ❌ {resp.status_code}: {resp.text[:60]}')
                time.sleep(0.5)
            except Exception as e:
                print(f'  [Google Index] Error: {e}')

        print(f'[Google Index] {ok}/{len(urls)} URLs submitted')
        return ok

    except ImportError:
        print('[Google Index] cryptography library not installed — pip install cryptography')
        return 0
    except Exception as e:
        print(f'[Google Index] Error: {e}')
        return 0

# ══════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════
def main():
    print(f'\n{"="*60}')
    print('HealUSA Dental SEO Agent v1')
    print(f'Run started: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'{"="*60}\n')

    # ── Load state ──
    published, daily, platform_map = load_slugs()
    today_count = get_today_count(daily)
    today_str   = datetime.now().strftime('%Y-%m-%d')
    DAILY_LIMIT = 70  # 7 tiers × 10 pages
    remaining   = DAILY_LIMIT - today_count

    print(f'[State] Published slugs: {len(published)}')
    print(f'[State] Today count: {today_count}/{DAILY_LIMIT}')
    print(f'[State] Remaining today: {remaining}\n')

    if remaining <= 0:
        print('[DONE] Daily quota reached. Next run tomorrow.')
        return

    # ── Load or build daily queue ──
    queue, today_str = load_daily_queue()
    if not queue:
        print('[Queue] Building today\'s queue (70 keywords)...')
        queue = build_daily_queue()
        # Apply call intent filter
        before = len(queue)
        queue  = [i for i in queue if has_call_intent(i['kw'])]
        print(f'[Call Intent Filter] {before - len(queue)} low-intent keywords removed')
        # Remove already-published slugs
        queue = [i for i in queue if make_slug(i['kw']) not in published]
        print(f'[Queue] {len(queue)} keywords remaining after dedup')
        save_daily_queue(queue, today_str)
    else:
        print(f'[Queue] Resuming today\'s queue: {len(queue)} items remaining')

    # ── Take this run's slice ──
    run_slice = queue[:MAX_PER_RUN][:remaining]
    leftover  = queue[len(run_slice):]

    print(f'\nThis run: {len(run_slice)} pages | Remaining after: {len(leftover)}')
    for i, item in enumerate(run_slice):
        se = item.get('se_focus', 'std')
        print(f'  {i+1}. [Tier{item["tier"]} {item["tier_name"]}] [{se}] {item["kw"][:55]}')

    # ── Generate pages ──
    print(f'\n[STEP 1] Generating {len(run_slice)} pages...')
    generated = []
    errors    = 0

    for i, item in enumerate(run_slice):
        kw = item['kw']
        print(f'\n[{i+1}/{len(run_slice)}] Tier{item["tier"]} | {item["tier_name"]} | {kw[:55]}')
        try:
            page = generate_page(item, published, platform_map)
            if page:
                generated.append(page)
                published.add(make_slug(kw))
                print(f'  ✅ {page["words"]}w | {page["tier_name"]} | {page["se_focus"]}')
        except Exception as e:
            errors += 1
            print(f'  ❌ Error: {e}')
        if i < len(run_slice) - 1:
            time.sleep(4)

    # Save leftover queue for next run
    save_daily_queue(leftover, today_str)

    # ── Publish ──
    if generated:
        print(f'\n[STEP 2] Publishing {len(generated)} pages...')
        gh_ok = publish_github(generated)
        ensure_indexnow_key_file()
        ping_bing(generated)
        ping_google(generated)

        daily = update_today_count(daily, today_count + len(generated))
        save_slugs(published, daily, platform_map)

        # Summary by tier
        by_tier = {}
        for p in generated:
            t = p.get('tier_name', '?')
            by_tier[t] = by_tier.get(t, 0) + 1

        bing_count   = sum(1 for p in generated if p.get('se_focus') == 'bing')
        google_count = sum(1 for p in generated if p.get('se_focus') == 'google')

        print(f'\n{"="*60}')
        print('SUMMARY:')
        print(f'  Generated:        {len(generated)} pages')
        for tier_name, cnt in sorted(by_tier.items()):
            print(f'  {tier_name:<18} {cnt} pages')
        print(f'  Bing-focused:     {bing_count}')
        print(f'  Google-focused:   {google_count}')
        print(f'  Errors:           {errors}')
        print(f'  GitHub:           {gh_ok} published')
        print(f'  Total slugs:      {len(published)}')
        print(f'  Queue left today: {len(leftover)}')
        print(f'{"="*60}\n')
    else:
        print('\nNo pages generated this run.')

if __name__ == '__main__':
    main()

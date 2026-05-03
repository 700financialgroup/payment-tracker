import os, json, requests, base64, imaplib, email, re
from datetime import datetime, timedelta

STRIPE_KEY = os.environ['STRIPE_SECRET_KEY']
AUTHNET_LOGIN = os.environ['AUTHNET_LOGIN']
AUTHNET_KEY = os.environ['AUTHNET_KEY']
GITHUB_TOKEN = os.environ['GITHUB_TOKEN']
GITHUB_REPO = '700financialgroup/payment-tracker'
SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK_URL', '')
GMAIL_ADDRESS = os.environ.get('GMAIL_ADDRESS', 'info@700financialgroup.com')
GMAIL_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD', '')
AUTHNET_URL = 'https://api.authorize.net/xml/v1/request.api'
GHL_API_KEY = os.environ.get('GHL_API_KEY', '')
GHL_LOCATION = '9lz1duatu3n8Gzy1KSyL'
GHL_CF_ROUND = 'M0p5Lpy8FW9HdHyIVUqi'
GHL_CF_LANGUAGE = 'cg4FLZctr5gJBJbPKoGN'
GHL_CF_PLAN = 'MVKfYgivGKkm40K2GniJ'
GHL_CF_INSTALLMENT = 'eYAVo4nAJmPRPjY2KQFF'

def clean(text):
    text = re.sub(r'<[^>]+>', ' ', text or '')
    return ' '.join(text.split()).strip()

def short_plan(plan):
    p = plan.lower()
    if '900' in p and 'promo' in p: return '900 Plan Promo'
    if '900' in p and ('oferta' in p or 'reparacion' in p): return '900 Plan (ES)'
    if '900' in p: return '900 Plan'
    if '500' in p: return '500 Plan'
    if 'monthly' in p: return 'Monthly'
    if 'mentorship' in p: return 'Mentorship'
    return plan[:20] if plan else 'Plan'

def plan_amount(plan):
    """Derive monthly installment from plan name"""
    p = plan.lower()
    if '900' in p and ('promo' in p or 'oferta' in p or 'reparacion' in p): return 160.0
    if '900' in p: return 175.0
    if '500' in p: return 100.0
    if 'monthly' in p: return 175.0
    if 'mentorship' in p: return 97.0
    return 175.0  # default

def get_body(msg):
    html_body = None
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == 'text/plain':
                try: return part.get_payload(decode=True).decode('utf-8', errors='ignore')
                except: pass
            elif ct == 'text/html' and not html_body:
                try: html_body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                except: pass
    else:
        try:
            payload = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
            if '<html' in payload.lower() or '<!doctype' in payload.lower():
                return re.sub(r'<[^>]+>', ' ', payload)
            return payload
        except: pass
    return re.sub(r'<[^>]+>', ' ', html_body) if html_body else ''

def get_date(msg):
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(msg.get('Date', '')).strftime('%Y-%m-%d')
    except: return datetime.utcnow().strftime('%Y-%m-%d')

def pull_stripe():
    print("Pulling Stripe...")
    payments = []
    # Pull ALL payments (no date filter) for total collected accuracy
    headers = {'Authorization': f'Bearer {STRIPE_KEY}'}
    url = 'https://api.stripe.com/v1/payment_intents?limit=100'
    while url:
        data = requests.get(url, headers=headers).json()
        if 'error' in data:
            print(f"  Stripe error: {data['error'].get('message','')}"); break
        for pi in data.get('data', []):
            name = pi.get('description', '')
            if pi.get('customer'):
                try:
                    c = requests.get(f"https://api.stripe.com/v1/customers/{pi['customer']}", headers=headers).json()
                    name = c.get('name') or c.get('email','').split('@')[0] or name
                except: pass
            payments.append({'id': pi['id'],
                'date': datetime.utcfromtimestamp(pi['created']).strftime('%Y-%m-%d'),
                'time': datetime.utcfromtimestamp(pi['created']).strftime('%H:%M'),
                'name': name, 'amount': pi['amount']/100, 'status': pi['status'],
                'platform': 'Stripe', 'ok': pi['status']=='succeeded',
                'settled': pi['status']=='succeeded', 'pending': False})
        url = (f"https://api.stripe.com/v1/payment_intents?limit=100&starting_after={data['data'][-1]['id']}"
               if data.get('has_more') else None)
    print(f"  {len(payments)} Stripe payments found")
    return payments

def authnet_post(p):
    r = requests.post(AUTHNET_URL, json=p, headers={'Content-Type': 'application/json'})
    return json.loads(r.text.lstrip('\ufeff'))

def pull_authnet():
    print("Pulling Auth.net...")
    payments = []
    auth = {'name': AUTHNET_LOGIN, 'transactionKey': AUTHNET_KEY}
    try:
        for tx in authnet_post({'getUnsettledTransactionListRequest': {'merchantAuthentication': auth, 'paging': {'limit': 1000, 'offset': 1}}}).get('transactions', []):
            payments.append({'id': tx['transId'], 'date': tx.get('submitTimeLocal','')[:10],
                'time': tx.get('submitTimeLocal','')[11:16],
                'name': f"{tx.get('firstName','')} {tx.get('lastName','')}".strip(),
                'amount': float(tx.get('settleAmount',0)), 'status': tx['transactionStatus'],
                'platform': 'Auth.net', 'ok': tx['transactionStatus'] not in ['declined','voided'],
                'settled': False, 'pending': tx['transactionStatus']=='capturedPendingSettlement'})
    except Exception as e: print(f"  Unsettled error: {e}")
    try:
        # Pull month by month from Oct 2025 to now (Auth.net has 31-day limit per request)
        # NOTE: Historical export covers Oct 2025 onward so only pull last 3 days here
        all_batches = []
        cur = datetime.utcnow() - timedelta(days=3)
        cur = datetime(cur.year, cur.month, cur.day)  # normalize to day start
        while cur <= datetime.utcnow():
            if cur.month == 12:
                next_m = datetime(cur.year + 1, 1, 1)
            else:
                next_m = datetime(cur.year, cur.month + 1, 1)
            end = min(next_m - timedelta(seconds=1), datetime.utcnow())
            try:
                result = authnet_post({'getSettledBatchListRequest': {
                    'merchantAuthentication': auth, 'includeStatistics': False,
                    'firstSettlementDate': cur.strftime('%Y-%m-%dT00:00:00Z'),
                    'lastSettlementDate': end.strftime('%Y-%m-%dT23:59:59Z')
                }})
                batches = result.get('batchList', [])
                if batches:
                    all_batches.extend(batches)
            except Exception as e:
                print(f"  Auth.net error: {e}")
            cur = next_m
        for b in all_batches:
            for tx in authnet_post({'getTransactionListRequest': {'merchantAuthentication': auth, 'batchId': b['batchId'], 'paging': {'limit':1000,'offset':1}}}).get('transactions', []):
                payments.append({'id': tx['transId'], 'date': b.get('settlementTimeLocal','')[:10],
                    'time': b.get('settlementTimeLocal','')[11:16],
                    'name': f"{tx.get('firstName','')} {tx.get('lastName','')}".strip(),
                    'amount': float(tx.get('settleAmount',0)), 'status': tx['transactionStatus'],
                    'platform': 'Auth.net', 'ok': tx['transactionStatus']=='settledSuccessfully',
                    'settled': True, 'pending': False})
    except Exception as e: print(f"  Settled error: {e}")
    print(f"  {len(payments)} Auth.net transactions found")
    return payments

def pull_gmail():
    if not GMAIL_PASSWORD:
        print("Gmail: no app password, skipping"); return []
    print("Pulling Gmail (Zelle + Fanbasis)...")
    payments = []
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
        mail.select('"[Gmail]/All Mail"')
        since = (datetime.utcnow()-timedelta(days=14)).strftime('%d-%b-%Y')

        # ZELLE
        _, msgs = mail.search(None, f'(FROM "no.reply.alerts@chase.com" SUBJECT "You received money with Zelle" SINCE {since})')
        nums = msgs[0].split() if msgs[0] else []
        print(f"  Zelle emails found: {len(nums)}")
        for num in nums:
            try:
                _, data = mail.fetch(num, '(RFC822)')
                msg = email.message_from_bytes(data[0][1])
                body = get_body(msg)
                # Multiple amount patterns for Chase Zelle emails
                am = (re.search(r'Amount\s*\$\s*([\d,]+\.?\d*)', body) or
                      re.search(r'\$([\d,]+\.\d{2})', body) or
                      re.search(r'Amount[^\d$]{0,20}([\d,]+\.\d{2})', body))
                # Name patterns - Zelle emails vary
                nm = (re.search(r'payment\s+([A-Za-z][A-Za-z\s]{2,40}?)\s+sent you money', body) or
                      re.search(r'([A-Za-z][A-Za-z\s]{2,40}?)\s+sent you', body))
                tx = re.search(r'Transaction number\s*(\d+)', body)
                dm = re.search(r'Sent on\s+(\w+ \d+,?\s*\d{4})', body)
                if am:
                    amount = float(am.group(1).replace(',',''))
                    name = clean(nm.group(1)).title() if nm else 'Zelle Sender'
                    txn = tx.group(1) if tx else f'z{num.decode()}'
                    pay_date = datetime.utcnow().strftime('%Y-%m-%d')
                    if dm:
                        try: pay_date = datetime.strptime(dm.group(1).replace('  ',' '), '%b %d, %Y').strftime('%Y-%m-%d')
                        except:
                            try: pay_date = datetime.strptime(dm.group(1).replace('  ',' '), '%b %d %Y').strftime('%Y-%m-%d')
                            except: pass
                    payments.append({'id': f'zelle_{txn}', 'date': pay_date, 'time': '',
                        'name': name, 'amount': amount, 'status': 'received',
                        'platform': 'Zelle', 'ok': True, 'settled': True, 'pending': False})
                    print(f"  Zelle: {name} ${amount}")
                else:
                    print(f"  Zelle: no amount found in email {num.decode()}")
            except Exception as e: print(f"  Zelle error: {e}")

        def parse_fb(num, label):
            try:
                _, data = mail.fetch(num, '(RFC822)')
                msg = email.message_from_bytes(data[0][1])
                body = get_body(msg)
                nm = re.search(r'Name[:\s]+([A-Za-z][^\n<]{2,50}?)(?:\s*\n|\s*Email|\s*<)', body)
                pm = re.search(r'purchased\s+(.+?)(?:\s+If you need|Order Summary)', body)
                am = re.search(r'(?:Total|Amount|Price)[:\s]+\$?([\d,]+\.?\d*)', body)
                # Also try markdown bold format: **Amount:** $196.40
                if not am:
                    am = re.search(r'\*\*Amount:\*\*\s*\$?([\d,]+\.?\d*)', body)
                name = clean(nm.group(1)).title() if nm else 'Fanbasis Client'
                plan = clean(pm.group(1)) if pm else label
                amount = float(am.group(1).replace(',','')) if am else plan_amount(plan)
                return {'name': name, 'plan': plan, 'amount': amount, 'date': get_date(msg), 'num': num.decode()}
            except: return None

        # FANBASIS NEW SALE
        _, msgs = mail.search(None, f'(FROM "support@fanbasis.com" SUBJECT "New Sale" SINCE {since})')
        nums = msgs[0].split() if msgs[0] else []
        print(f"  Fanbasis New Sale emails: {len(nums)}")
        for num in nums:
            p = parse_fb(num, 'New Sale')
            if p:
                payments.append({'id': f'fb_sale_{p["num"]}_{p["date"]}', 'date': p['date'],
                    'time': '', 'name': p['name'], 'amount': p['amount'],
                    'status': 'New Sale', 'platform': 'Fanbasis',
                    'ok': True, 'settled': True, 'pending': False})
                print(f"  Fanbasis New Sale: {p['name']}")

        # FANBASIS RENEWAL
        _, msgs = mail.search(None, f'(FROM "support@fanbasis.com" SUBJECT "New Subscription Renewal" SINCE {since})')
        nums = msgs[0].split() if msgs[0] else []
        print(f"  Fanbasis Renewal emails: {len(nums)}")
        for num in nums:
            p = parse_fb(num, 'Renewal')
            if p:
                payments.append({'id': f'fb_renewal_{p["num"]}_{p["date"]}', 'date': p['date'],
                    'time': '', 'name': p['name'], 'amount': p['amount'],
                    'status': 'Renewal', 'platform': 'Fanbasis',
                    'ok': True, 'settled': True, 'pending': False})
                print(f"  Fanbasis Renewal: {p['name']}")

        # FANBASIS DISPUTE — parse plain text body, deduplicate alerts
        seen_disputes = load_seen_disputes()
        new_seen = set(seen_disputes)
        _, msgs = mail.search(None, f'(FROM "support@fanbasis.com" SUBJECT "A customer has opened a dispute" SINCE {since})')
        nums = msgs[0].split() if msgs[0] else []
        for num in nums:
            try:
                _, data = mail.fetch(num, '(RFC822)')
                msg = email.message_from_bytes(data[0][1])
                body = get_body(msg)
                nm = re.search(r'\*\*Customer:\*\*\s*(.+?)(?:\r?\n|$)', body)
                am = re.search(r'\*\*Amount:\*\*\s*\$?([\d,]+\.?\d*)', body)
                pm = re.search(r'\*\*Product:\*\*\s*(.+?)(?:\r?\n|$)', body)
                rm = re.search(r'\*\*Reason:\*\*\s*(.+?)(?:\r?\n|$)', body)
                dm = re.search(r'\*\*Last day to submit evidence:\*\*\s*(.+?)(?:\r?\n|$)', body)
                name = nm.group(1).strip().title() if nm else 'Unknown Client'
                amount = float(am.group(1).replace(',','')) if am else 0.0
                product = pm.group(1).strip() if pm else ''
                reason = rm.group(1).strip() if rm else ''
                deadline = dm.group(1).strip() if dm else ''
                pay_date = get_date(msg)
                dispute_id = f'fb_dispute_{num.decode()}_{pay_date}'
                payments.append({'id': dispute_id, 'date': pay_date,
                    'time': '', 'name': name, 'amount': amount,
                    'status': 'DISPUTE OPENED', 'platform': 'Fanbasis',
                    'ok': False, 'settled': False, 'pending': False})
                if dispute_id not in seen_disputes:
                    new_seen.add(dispute_id)
                    print(f"  ⚠️ NEW Dispute: {name} ${amount} — {reason}")
                    if SLACK_WEBHOOK:
                        requests.post(SLACK_WEBHOOK, json={
                            'message': f'🚨 *FANBASIS DISPUTE OPENED*\n\n• Client: *{name}*\n• Product: {product}\n• Amount: *${amount}*\n• Reason: {reason}\n• Deadline: {deadline}\n\n<@U0AU1BFUJCD> — submit evidence ASAP!',
                            'type': 'billing'}, timeout=5)
                else:
                    print(f"  ⚠️ Known dispute (no re-alert): {name}")
            except Exception as e:
                print(f"  Dispute error: {e}")
        if new_seen != seen_disputes:
            save_seen_disputes(new_seen)

        mail.close()
        mail.logout()
        print(f"  {len(payments)} Gmail payments parsed")
    except Exception as e: print(f"  Gmail error: {e}")
    return payments



def load_fanbasis_historical():
    """Load historical Fanbasis data from GitHub repo"""
    try:
        url = f'https://raw.githubusercontent.com/{GITHUB_REPO}/main/data/fanbasis_historical.json'
        r = requests.get(url + '?t=' + str(int(__import__("time").time())), timeout=10)
        if r.status_code == 200:
            data = r.json()
            print(f"  Loaded {len(data)} historical Fanbasis records")
            return data
    except Exception as e:
        print(f"  Historical Fanbasis load error: {e}")
    return []

def load_zelle_historical():
    """Load historical Zelle data from GitHub repo"""
    try:
        url = f'https://raw.githubusercontent.com/{GITHUB_REPO}/main/data/zelle_historical.json'
        r = requests.get(url + '?t=' + str(int(__import__("time").time())), timeout=10)
        if r.status_code == 200:
            data = r.json()
            print(f"  Loaded {len(data)} historical Zelle records")
            return data
    except Exception as e:
        print(f"  Historical Zelle load error: {e}")
    return []

def load_authnet_historical():
    """Load historical Auth.net data from GitHub repo"""
    try:
        url = f'https://raw.githubusercontent.com/{GITHUB_REPO}/main/data/authnet_historical.json'
        r = requests.get(url + '?t=' + str(int(__import__("time").time())), timeout=10)
        if r.status_code == 200:
            data = r.json()
            print(f"  Loaded {len(data)} historical Auth.net records")
            return data
    except Exception as e:
        print(f"  Historical Auth.net load error: {e}")
    return []

def pull_ghl_clients():
    if not GHL_API_KEY:
        print("GHL: no API key configured, skipping")
        return []
    print("Pulling GHL clients...")
    clients = []
    seen_ids = set()
    headers = {
        'Authorization': f'Bearer {GHL_API_KEY}',
        'Version': '2021-07-28',
        'Content-Type': 'application/json'
    }
    after_val = None
    after_id = None
    page = 0
    while True:
        try:
            params = {'locationId': GHL_LOCATION, 'limit': 100, 'query': 'client.round'}
            if after_val:
                params['startAfter'] = after_val
                params['startAfterId'] = after_id
            r = requests.get('https://services.leadconnectorhq.com/contacts/',
                headers=headers, params=params, timeout=15)
            if r.status_code != 200:
                print(f"  GHL API error: {r.status_code} {r.text[:200]}")
                break
            data = r.json()
            batch = data.get('contacts', [])
            meta = data.get('meta', {})
            page += 1
            print(f"  Page {page}: {len(batch)} contacts (total in GHL: {meta.get('total','?')})")
            if not batch:
                break
            for c in batch:
                cid = c.get('id')
                if cid in seen_ids:
                    continue
                seen_ids.add(cid)
                cf = {f['id']: f['value'] for f in c.get('customFields', [])}
                round_num = cf.get(GHL_CF_ROUND, 0)
                language = cf.get(GHL_CF_LANGUAGE, '')
                plan = cf.get(GHL_CF_PLAN, '')
                installment = cf.get(GHL_CF_INSTALLMENT, '')
                tags = c.get('tags', [])
                if not round_num:
                    for t in tags:
                        if t.startswith('client.round'):
                            try: round_num = int(t.replace('client.round',''))
                            except: pass
                if not language:
                    if 'language: spanish' in tags: language = 'Spanish'
                    elif 'language: english' in tags: language = 'English'
                flags = []
                if 'payment missing' in tags: flags.append('payment_missing')
                if 'no show to call' in tags: flags.append('no_show')
                if 'idiq fail' in tags: flags.append('idiq_fail')
                if 'sla-breached' in tags: flags.append('sla_breached')
                if 'fanbasis failed' in tags: flags.append('fanbasis_failed')
                platform = 'Fanbasis' if any(t in tags for t in ['fanbasis paid','fanbasis contact','fanbasis-payment']) else 'Auth.net'
                clients.append({
                    'id': cid,
                    'name': f"{c.get('firstName','')} {c.get('lastName','')}".strip(),
                    'phone': c.get('phone', ''),
                    'email': c.get('email', ''),
                    'round': round_num,
                    'language': language,
                    'plan': plan,
                    'installment': float(installment) if installment else 0,
                    'platform': platform,
                    'flags': flags,
                    'tags': tags,
                    'dateAdded': c.get('dateAdded', '')[:10]
                })
            if len(batch) < 100:
                break
            after_val = meta.get('startAfter')
            after_id = meta.get('startAfterId')
            if not after_val:
                break
        except Exception as e:
            print(f"  GHL error: {e}")
            break
    active = [cl for cl in clients if any(t.startswith('client.round') for t in cl.get('tags', []))]
    print(f"  {len(active)} active clients ({len(clients)} total fetched)")
    return active


def write_clients_to_github(clients):
    if not clients:
        return
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    payload = {
        'updated': now,
        'total': len(clients),
        'clients': sorted(clients, key=lambda x: x.get('round', 0))
    }
    content = base64.b64encode(json.dumps(payload, indent=2).encode()).decode()
    headers = {'Authorization': f'Bearer {GITHUB_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    url = f'https://api.github.com/repos/{GITHUB_REPO}/contents/data/clients.json'
    r = requests.get(url, headers=headers)
    sha = r.json().get('sha') if r.status_code == 200 else None
    body = {'message': f'GHL sync: {now}', 'content': content}
    if sha: body['sha'] = sha
    result = requests.put(url, json=body, headers=headers)
    if result.status_code in [200, 201]:
        print(f"  {len(clients)} clients written to GitHub")
    else:
        print(f"  GitHub clients error: {result.status_code}")



def load_seen_disputes():
    """Load set of dispute IDs already alerted from GitHub"""
    headers = {'Authorization': f'Bearer {GITHUB_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    url = f'https://api.github.com/repos/{GITHUB_REPO}/contents/data/seen_disputes.json'
    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            import base64 as b64
            content = b64.b64decode(r.json()['content']).decode()
            return set(json.loads(content).get('seen', []))
    except: pass
    return set()

def save_seen_disputes(seen_set):
    """Save seen dispute IDs to GitHub"""
    headers = {'Authorization': f'Bearer {GITHUB_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    url = f'https://api.github.com/repos/{GITHUB_REPO}/contents/data/seen_disputes.json'
    payload = {'seen': list(seen_set), 'updated': datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
    content = base64.b64encode(json.dumps(payload, indent=2).encode()).decode()
    r = requests.get(url, headers=headers)
    sha = r.json().get('sha') if r.status_code == 200 else None
    body = {'message': f'Update seen disputes', 'content': content}
    if sha: body['sha'] = sha
    requests.put(url, json=body, headers=headers)

def write_to_github(all_payments):
    print("Writing to GitHub...")
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    today = datetime.utcnow().strftime('%Y-%m-%d')
    seen, unique = set(), []
    for p in all_payments:
        if p['id'] not in seen:
            seen.add(p['id']); unique.append(p)
    all_time_total = round(sum(p['amount'] for p in unique if p.get('ok')), 2)
    payload = {'updated': now,
        'today_total': round(sum(p['amount'] for p in unique if p.get('date')==today and p.get('ok')), 2),
        'all_time_total': all_time_total,
        'payments': sorted(unique, key=lambda x: x.get('date',''), reverse=True)}
    content = base64.b64encode(json.dumps(payload, indent=2).encode()).decode()
    headers = {'Authorization': f'Bearer {GITHUB_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    url = f'https://api.github.com/repos/{GITHUB_REPO}/contents/data/payments.json'
    r = requests.get(url, headers=headers)
    sha = r.json().get('sha') if r.status_code == 200 else None
    body = {'message': f'Auto-sync: {now}', 'content': content}
    if sha: body['sha'] = sha
    result = requests.put(url, json=body, headers=headers)
    if result.status_code in [200, 201]:
        print(f"  {len(unique)} payments written to GitHub"); return True
    else:
        print(f"  GitHub error: {result.status_code}"); return False

if __name__ == '__main__':
    print(f"\nPayFlow Sync Bot - {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n")
    all_payments, errors = [], []
    try: all_payments.extend(pull_stripe())
    except Exception as e: errors.append(f"Stripe: {e}")
    try: all_payments.extend(pull_authnet())
    except Exception as e: errors.append(f"Auth.net: {e}")
    try: all_payments.extend(pull_gmail())
    except Exception as e: errors.append(f"Gmail: {e}")
    try:
        historical = load_fanbasis_historical()
        if historical:
            all_payments.extend(historical)
    except Exception as e: errors.append(f"Fanbasis historical: {e}")
    try:
        zelle_hist = load_zelle_historical()
        if zelle_hist:
            all_payments.extend(zelle_hist)
    except Exception as e: errors.append(f"Zelle historical: {e}")
    try:
        authnet_hist = load_authnet_historical()
        if authnet_hist:
            all_payments.extend(authnet_hist)
    except Exception as e: errors.append(f"Auth.net historical: {e}")
    write_to_github(all_payments)
    try:
        ghl_clients = pull_ghl_clients()
        if ghl_clients:
            write_clients_to_github(ghl_clients)
    except Exception as e: errors.append(f"GHL: {e}")
    today = datetime.utcnow().strftime('%Y-%m-%d')
    total = sum(p.get('amount',0) for p in all_payments if p.get('date')==today and p.get('ok'))
    platforms = {}
    for p in all_payments:
        platforms[p.get('platform','')] = platforms.get(p.get('platform',''), 0) + 1
    print(f"\nSummary: {len(all_payments)} payments | Today: ${total:,.2f}")
    for k,v in platforms.items():
        if v: print(f"  {k}: {v}")
    if errors: print(f"Errors: {errors}")
    print("Sync complete!")

import os, json, requests, base64, imaplib, email, re
from datetime import datetime, timedelta
from email.header import decode_header

STRIPE_KEY = os.environ['STRIPE_SECRET_KEY']
AUTHNET_LOGIN = os.environ['AUTHNET_LOGIN']
AUTHNET_KEY = os.environ['AUTHNET_KEY']
GITHUB_TOKEN = os.environ['GITHUB_TOKEN']
GITHUB_REPO = '700financialgroup/payment-tracker'
SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK_URL', '')
GMAIL_ADDRESS = os.environ.get('GMAIL_ADDRESS', 'info@700financialgroup.com')
GMAIL_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD', '')
AUTHNET_URL = 'https://api.authorize.net/xml/v1/request.api'

def pull_stripe():
    print("Pulling Stripe...")
    payments = []
    since = int((datetime.utcnow() - timedelta(hours=48)).timestamp())
    headers = {'Authorization': f'Bearer {STRIPE_KEY}'}
    url = f'https://api.stripe.com/v1/payment_intents?limit=100&created[gte]={since}'
    while url:
        data = requests.get(url, headers=headers).json()
        if 'error' in data:
            print(f"  Stripe error: {data['error'].get('message','')}")
            break
        for pi in data.get('data', []):
            name = pi.get('description', '')
            if pi.get('customer'):
                try:
                    c = requests.get(f"https://api.stripe.com/v1/customers/{pi['customer']}", headers=headers).json()
                    name = c.get('name') or c.get('email', '').split('@')[0] or name
                except: pass
            payments.append({'id': pi['id'],
                'date': datetime.utcfromtimestamp(pi['created']).strftime('%Y-%m-%d'),
                'time': datetime.utcfromtimestamp(pi['created']).strftime('%H:%M'),
                'name': name, 'amount': pi['amount']/100, 'status': pi['status'],
                'platform': 'Stripe', 'ok': pi['status']=='succeeded',
                'settled': pi['status']=='succeeded', 'pending': False})
        url = (f"https://api.stripe.com/v1/payment_intents?limit=100&created[gte]={since}&starting_after={data['data'][-1]['id']}"
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
        resp = authnet_post({'getUnsettledTransactionListRequest': {'merchantAuthentication': auth, 'paging': {'limit': 1000, 'offset': 1}}})
        for tx in resp.get('transactions', []):
            payments.append({'id': tx['transId'],
                'date': tx.get('submitTimeLocal','')[:10],
                'time': tx.get('submitTimeLocal','')[11:16],
                'name': f"{tx.get('firstName','')} {tx.get('lastName','')}".strip(),
                'amount': float(tx.get('settleAmount',0)),
                'status': tx['transactionStatus'], 'platform': 'Auth.net',
                'ok': tx['transactionStatus'] not in ['declined','voided'],
                'settled': False, 'pending': tx['transactionStatus']=='capturedPendingSettlement'})
    except Exception as e: print(f"  Unsettled error: {e}")
    try:
        y = (datetime.utcnow()-timedelta(days=2)).strftime('%Y-%m-%dT00:00:00Z')
        t = datetime.utcnow().strftime('%Y-%m-%dT23:59:59Z')
        for b in authnet_post({'getSettledBatchListRequest': {'merchantAuthentication': auth,
                'includeStatistics': False, 'firstSettlementDate': y, 'lastSettlementDate': t}}).get('batchList',[]):
            for tx in authnet_post({'getTransactionListRequest': {'merchantAuthentication': auth,
                    'batchId': b['batchId'], 'paging': {'limit':1000,'offset':1}}}).get('transactions',[]):
                payments.append({'id': tx['transId'],
                    'date': b.get('settlementTimeLocal','')[:10],
                    'time': b.get('settlementTimeLocal','')[11:16],
                    'name': f"{tx.get('firstName','')} {tx.get('lastName','')}".strip(),
                    'amount': float(tx.get('settleAmount',0)),
                    'status': tx['transactionStatus'], 'platform': 'Auth.net',
                    'ok': tx['transactionStatus']=='settledSuccessfully',
                    'settled': True, 'pending': False})
    except Exception as e: print(f"  Settled error: {e}")
    print(f"  {len(payments)} Auth.net transactions found")
    return payments

def decode_str(s):
    if not s: return ''
    parts = decode_header(s)
    result = ''
    for part, enc in parts:
        if isinstance(part, bytes):
            result += part.decode(enc or 'utf-8', errors='ignore')
        else:
            result += str(part)
    return result

def get_body(msg):
    # Try plain text first
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                try: return part.get_payload(decode=True).decode('utf-8', errors='ignore')
                except: pass
        # Fall back to HTML if no plain text
        for part in msg.walk():
            if part.get_content_type() == 'text/html':
                try:
                    html = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    # Strip HTML tags for regex parsing
                    import re as re2
                    return re2.sub(r'<[^>]+>', ' ', html)
                except: pass
    else:
        try: return msg.get_payload(decode=True).decode('utf-8', errors='ignore')
        except: pass
    return ''

def pull_gmail():
    if not GMAIL_PASSWORD:
        print("Gmail: no app password configured, skipping")
        return []
    
    print("Pulling Gmail (Zelle + Fanbasis)...")
    payments = []
    
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
        mail.select('INBOX')
        
        since_date = (datetime.utcnow() - timedelta(days=14)).strftime('%d-%b-%Y')

        # ── ZELLE ──────────────────────────────────────────────
        _, msgs = mail.search(None, f'(FROM "no.reply.alerts@chase.com" SUBJECT "You received money with Zelle" SINCE {since_date})')
        for num in msgs[0].split():
            try:
                _, data = mail.fetch(num, '(RFC822)')
                msg = email.message_from_bytes(data[0][1])
                body = get_body(msg)
                date_str = msg.get('Date','')
                
                # Parse: Amount $175.00 Sent on Apr 28, 2026
                amount_match = re.search(r'Amount\s+\$([0-9,]+\.?\d*)', body)
                name_match = re.search(r'Zelle® payment\s+(.+?)\s+sent you money', body)
                txn_match = re.search(r'Transaction number\s+(\d+)', body)
                date_match = re.search(r'Sent on\s+(\w+ \d+, \d{4})', body)
                
                if amount_match:
                    amount = float(amount_match.group(1).replace(',',''))
                    name = name_match.group(1).strip().title() if name_match else 'Zelle Sender'
                    txn_id = txn_match.group(1) if txn_match else f'zelle_{num.decode()}'
                    
                    pay_date = datetime.utcnow().strftime('%Y-%m-%d')
                    if date_match:
                        try: pay_date = datetime.strptime(date_match.group(1), '%b %d, %Y').strftime('%Y-%m-%d')
                        except: pass
                    
                    payments.append({'id': f'zelle_{txn_id}', 'date': pay_date,
                        'time': '', 'name': name, 'amount': amount,
                        'status': 'received', 'platform': 'Zelle',
                        'ok': True, 'settled': True, 'pending': False})
                    print(f"  Zelle: {name} ${amount}")
            except Exception as e: print(f"  Zelle parse error: {e}")

        # ── FANBASIS NEW SALE ───────────────────────────────────
        _, msgs = mail.search(None, f'(FROM "support@fanbasis.com" SUBJECT "New Sale" SINCE {since_date})')
        for num in msgs[0].split():
            try:
                _, data = mail.fetch(num, '(RFC822)')
                msg = email.message_from_bytes(data[0][1])
                body = get_body(msg)
                
                name_match = re.search(r'Name:\s*(.+?)(?:\n|Email:)', body)
                plan_match = re.search(r'purchased\s+(.+?)(?:\s+If you need|Order Summary)', body)
                amount_match = re.search(r'(?:Total|Amount|Price)[\s:]+\$?([0-9,]+\.?\d*)', body)
                
                name = name_match.group(1).strip().title() if name_match else 'Fanbasis Client'
                plan = plan_match.group(1).strip() if plan_match else '900 Plan'
                amount = float(amount_match.group(1).replace(',','')) if amount_match else 200.0
                
                pay_date = datetime.utcnow().strftime('%Y-%m-%d')
                try:
                    date_str = msg.get('Date','')
                    from email.utils import parsedate_to_datetime
                    pay_date = parsedate_to_datetime(date_str).strftime('%Y-%m-%d')
                except: pass
                
                payments.append({'id': f'fb_sale_{num.decode()}_{pay_date}',
                    'date': pay_date, 'time': '', 'name': name,
                    'amount': amount, 'status': f'New Sale — {plan}',
                    'platform': 'Fanbasis', 'ok': True, 'settled': True, 'pending': False})
                print(f"  Fanbasis New Sale: {name} — {plan}")
            except Exception as e: print(f"  Fanbasis sale parse error: {e}")

        # ── FANBASIS SUBSCRIPTION RENEWAL ──────────────────────
        _, msgs = mail.search(None, f'(FROM "support@fanbasis.com" SUBJECT "New Subscription Renewal" SINCE {since_date})')
        for num in msgs[0].split():
            try:
                _, data = mail.fetch(num, '(RFC822)')
                msg = email.message_from_bytes(data[0][1])
                body = get_body(msg)
                
                name_match = re.search(r'Name:\s*(.+?)(?:\n|Email:)', body)
                plan_match = re.search(r'purchased\s+(.+?)(?:\s+If you need|Order Summary)', body)
                amount_match = re.search(r'(?:Total|Amount|Price)[\s:]+\$?([0-9,]+\.?\d*)', body)
                
                name = name_match.group(1).strip().title() if name_match else 'Fanbasis Client'
                plan = plan_match.group(1).strip() if plan_match else 'Renewal'
                amount = float(amount_match.group(1).replace(',','')) if amount_match else 200.0
                
                pay_date = datetime.utcnow().strftime('%Y-%m-%d')
                try:
                    from email.utils import parsedate_to_datetime
                    pay_date = parsedate_to_datetime(msg.get('Date','')).strftime('%Y-%m-%d')
                except: pass
                
                payments.append({'id': f'fb_renewal_{num.decode()}_{pay_date}',
                    'date': pay_date, 'time': '', 'name': name,
                    'amount': amount, 'status': f'Renewal — {plan}',
                    'platform': 'Fanbasis', 'ok': True, 'settled': True, 'pending': False})
                print(f"  Fanbasis Renewal: {name} — {plan}")
            except Exception as e: print(f"  Fanbasis renewal parse error: {e}")

        # ── FANBASIS DISPUTE ────────────────────────────────────
        _, msgs = mail.search(None, f'(FROM "support@fanbasis.com" SUBJECT "A customer has opened a dispute" SINCE {since_date})')
        for num in msgs[0].split():
            try:
                _, data = mail.fetch(num, '(RFC822)')
                msg = email.message_from_bytes(data[0][1])
                body = get_body(msg)
                
                name_match = re.search(r'Name:\s*(.+?)(?:\n|Email:)', body)
                amount_match = re.search(r'(?:disputed amount|amount)[\s:]+\$?([0-9,]+\.?\d*)', body, re.IGNORECASE)
                
                name = name_match.group(1).strip().title() if name_match else 'Dispute'
                amount = float(amount_match.group(1).replace(',','')) if amount_match else 0.0
                
                pay_date = datetime.utcnow().strftime('%Y-%m-%d')
                try:
                    from email.utils import parsedate_to_datetime
                    pay_date = parsedate_to_datetime(msg.get('Date','')).strftime('%Y-%m-%d')
                except: pass
                
                payments.append({'id': f'fb_dispute_{num.decode()}_{pay_date}',
                    'date': pay_date, 'time': '', 'name': name,
                    'amount': amount, 'status': '🚨 DISPUTE OPENED',
                    'platform': 'Fanbasis', 'ok': False, 'settled': False, 'pending': False})
                print(f"  ⚠️ Fanbasis Dispute: {name}")
                
                # Alert Slack immediately for disputes
                if SLACK_WEBHOOK:
                    requests.post(SLACK_WEBHOOK, json={
                        'message': f'🚨 *FANBASIS DISPUTE OPENED*\n\nClient: *{name}*\nAmount: ${amount}\nDate: {pay_date}\n\n<@U0AU1BFUJCD> — action required!',
                        'type': 'billing'
                    }, timeout=5)
            except Exception as e: print(f"  Fanbasis dispute parse error: {e}")

        mail.close()
        mail.logout()
        print(f"  {len(payments)} Gmail payments parsed")
        
    except Exception as e:
        print(f"  Gmail error: {e}")
    
    return payments

def write_to_github(all_payments):
    print("Writing to GitHub...")
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    today = datetime.utcnow().strftime('%Y-%m-%d')
    
    # Deduplicate by ID
    seen = set()
    unique = []
    for p in all_payments:
        if p['id'] not in seen:
            seen.add(p['id'])
            unique.append(p)
    
    payload = {
        'updated': now,
        'today_total': sum(p['amount'] for p in unique if p.get('date')==today and p.get('ok')),
        'payments': sorted(unique, key=lambda x: x.get('date',''), reverse=True)
    }
    content = base64.b64encode(json.dumps(payload, indent=2).encode()).decode()
    headers = {'Authorization': f'Bearer {GITHUB_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    url = f'https://api.github.com/repos/{GITHUB_REPO}/contents/data/payments.json'
    r = requests.get(url, headers=headers)
    sha = r.json().get('sha') if r.status_code == 200 else None
    body = {'message': f'Auto-sync: {now}', 'content': content}
    if sha: body['sha'] = sha
    result = requests.put(url, json=body, headers=headers)
    if result.status_code in [200, 201]:
        print(f"  {len(unique)} payments written to GitHub")
        return True
    else:
        print(f"  GitHub error: {result.status_code}")
        return False

if __name__ == '__main__':
    print(f"\nPayFlow Sync Bot - {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n")
    all_payments, errors = [], []
    try: all_payments.extend(pull_stripe())
    except Exception as e: errors.append(f"Stripe: {e}")
    try: all_payments.extend(pull_authnet())
    except Exception as e: errors.append(f"Auth.net: {e}")
    try: all_payments.extend(pull_gmail())
    except Exception as e: errors.append(f"Gmail: {e}")
    write_to_github(all_payments)
    today = datetime.utcnow().strftime('%Y-%m-%d')
    total = sum(p.get('amount',0) for p in all_payments if p.get('date')==today and p.get('ok'))
    platforms = {'Stripe': 0, 'Auth.net': 0, 'Zelle': 0, 'Fanbasis': 0}
    for p in all_payments:
        if p.get('platform') in platforms: platforms[p['platform']] += 1
    print(f"\nSummary: {len(all_payments)} total | Today: ${total:,.2f}")
    for k,v in platforms.items():
        if v: print(f"  {k}: {v}")
    if errors: print(f"Errors: {errors}")
    print("Sync complete!")

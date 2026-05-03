import os, json, requests, base64
from datetime import datetime, timedelta

STRIPE_KEY = os.environ['STRIPE_SECRET_KEY']
AUTHNET_LOGIN = os.environ['AUTHNET_LOGIN']
AUTHNET_KEY = os.environ['AUTHNET_KEY']
SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK_URL', '')
GITHUB_TOKEN = os.environ['GITHUB_TOKEN']
GITHUB_REPO = '700financialgroup/payment-tracker'
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
            print(f"  Stripe API error: {data['error']}")
            break
        for pi in data.get('data', []):
            name = pi.get('description', '')
            if pi.get('customer'):
                try:
                    c = requests.get(f"https://api.stripe.com/v1/customers/{pi['customer']}", headers=headers).json()
                    name = c.get('name') or c.get('email', '').split('@')[0] or name
                except: pass
            payments.append({
                'id': pi['id'],
                'date': datetime.utcfromtimestamp(pi['created']).strftime('%Y-%m-%d'),
                'time': datetime.utcfromtimestamp(pi['created']).strftime('%H:%M'),
                'name': name,
                'amount': pi['amount']/100,
                'status': pi['status'],
                'platform': 'Stripe',
                'ok': pi['status']=='succeeded',
                'settled': pi['status']=='succeeded',
                'pending': False
            })
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
            payments.append({
                'id': tx['transId'],
                'date': tx.get('submitTimeLocal','')[:10],
                'time': tx.get('submitTimeLocal','')[11:16],
                'name': f"{tx.get('firstName','')} {tx.get('lastName','')}".strip(),
                'amount': float(tx.get('settleAmount',0)),
                'status': tx['transactionStatus'],
                'platform': 'Auth.net',
                'ok': tx['transactionStatus'] not in ['declined','voided'],
                'settled': False,
                'pending': tx['transactionStatus']=='capturedPendingSettlement'
            })
    except Exception as e: print(f"  Unsettled error: {e}")
    try:
        y = (datetime.utcnow()-timedelta(days=2)).strftime('%Y-%m-%dT00:00:00Z')
        t = datetime.utcnow().strftime('%Y-%m-%dT23:59:59Z')
        for b in authnet_post({'getSettledBatchListRequest': {'merchantAuthentication': auth,
                'includeStatistics': False, 'firstSettlementDate': y, 'lastSettlementDate': t}}).get('batchList',[]):
            for tx in authnet_post({'getTransactionListRequest': {'merchantAuthentication': auth,
                    'batchId': b['batchId'], 'paging': {'limit':1000,'offset':1}}}).get('transactions',[]):
                payments.append({
                    'id': tx['transId'],
                    'date': b.get('settlementTimeLocal','')[:10],
                    'time': b.get('settlementTimeLocal','')[11:16],
                    'name': f"{tx.get('firstName','')} {tx.get('lastName','')}".strip(),
                    'amount': float(tx.get('settleAmount',0)),
                    'status': tx['transactionStatus'],
                    'platform': 'Auth.net',
                    'ok': tx['transactionStatus']=='settledSuccessfully',
                    'settled': True,
                    'pending': False
                })
    except Exception as e: print(f"  Settled error: {e}")
    print(f"  {len(payments)} Auth.net transactions found")
    return payments

def write_to_github(all_payments):
    print("Writing to GitHub data file...")
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    today = datetime.utcnow().strftime('%Y-%m-%d')
    payload = {
        'updated': now,
        'today_total': sum(p['amount'] for p in all_payments if p.get('date')==today and p.get('ok')),
        'payments': sorted(all_payments, key=lambda x: x.get('date',''), reverse=True)
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
        print(f"  {len(all_payments)} payments written to GitHub")
        return True
    else:
        print(f"  GitHub write error: {result.status_code} {result.text[:200]}")
        return False

if __name__ == '__main__':
    print(f"\nPayFlow Sync Bot - {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n")
    all_payments, errors = [], []
    try: all_payments.extend(pull_stripe())
    except Exception as e: errors.append(f"Stripe: {e}")
    try: all_payments.extend(pull_authnet())
    except Exception as e: errors.append(f"Auth.net: {e}")
    write_to_github(all_payments)
    today = datetime.utcnow().strftime('%Y-%m-%d')
    total = sum(p.get('amount',0) for p in all_payments if p.get('date')==today and p.get('ok'))
    declined = [p for p in all_payments if not p.get('ok') and not p.get('pending')]
    print(f"\nSummary: {len(all_payments)} payments | Today: ${total:,.2f} | Declined: {len(declined)}\nSync complete!")

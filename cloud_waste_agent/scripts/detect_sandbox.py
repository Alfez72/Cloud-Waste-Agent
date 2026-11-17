import json

inventory_text = '''<< name: inventory, prompt: false >>'''
data = json.loads(inventory_text)
resources = data['resources'] if isinstance(data, dict) else data

SCHED = 108.0 / 168.0
PROTECT = ['standby', 'dr-', 'failover', 'retention', 'legal', 'hold', 'compliance', 'scheduled']

def money(x):
    return '$' + '{:,.2f}'.format(x)

VETO = ['standby', 'stand-by', 'spare', 'replica', 'failover', 'fail-over', 'disaster', 'legal', 'audit',
        'compliance', 'retention', 'retain', 'do not delete', 'do not stop', 'do not remove', 'on purpose',
        'schedule', 'weekly', 'monthly', 'quarterly', 'nightly', 'periodic', 'month-end', 'year-end', 'golden image']

def veto_word(notes):
    n = (notes or '').lower()
    for w in VETO:
        if w in n:
            return w
    return ''

def protected(tags):
    t = (tags or '').lower()
    for k in PROTECT:
        if k in t:
            return True
    return False

def finding(r, rule, action, saving, evidence):
    status = 'recommend'
    why = ''
    if protected(r.get('tags')):
        status = 'confirm'
        why = 'protected tag: ' + r['tags']
    w = veto_word(r.get('notes'))
    if w:
        status = 'confirm'
        why = 'notes mention ' + w
    if (r.get('owner_team') or '').lower() in ('', 'unassigned', 'unknown'):
        status = 'confirm'
        why = 'owner unknown'
    return {
        'resource_id': r['resource_id'], 'name': r['name'], 'type': r['type'],
        'owner_team': r['owner_team'], 'environment': r['environment'],
        'rule': rule, 'action': action, 'monthly_saving': round(saving, 2),
        'evidence': evidence, 'tags': r.get('tags', ''), 'notes': r.get('notes', ''),
        'status': status, 'status_reason': why,
    }

OFFHOURS = 'Schedule off outside working hours (60 of 168 hours per week)'
findings = []
for r in resources:
    t = r['type']
    env = r['environment']
    cost = r['monthly_cost_usd']
    nxt = r.get('next_size_cost_usd')
    avg = r.get('avg_util_7d', 0)
    mx = r.get('max_util_7d', 0)
    f = None
    if t == 'volume' and not r.get('attached', True) and r.get('unattached_days', 0) > 14:
        f = finding(r, 'R3-delete-volume', 'Snapshot, then delete the unattached volume', cost,
                    'unattached for ' + str(r['unattached_days']) + ' days, costs ' + money(cost) + '/month')
    elif t == 'snapshot' and r.get('age_days', 0) > 90:
        f = finding(r, 'R4-old-snapshot', 'Review and delete the old snapshot', cost,
                    'snapshot is ' + str(r['age_days']) + ' days old, costs ' + money(cost) + '/month')
    elif t == 'load_balancer' and r.get('requests_14d') is not None and r['requests_14d'] < 100:
        f = finding(r, 'R6-idle-lb', 'Delete the idle load balancer', cost,
                    str(r['requests_14d']) + ' requests in 14 days, costs ' + money(cost) + '/month')
    elif t == 'gpu_vm' and avg < 15:
        if env in ('dev', 'test') and r.get('runs_24x7'):
            f = finding(r, 'R1-schedule', OFFHOURS, cost * SCHED,
                        'GPU use averages ' + str(avg) + '% (peak ' + str(mx) + '%) over 7 days, runs 24/7, costs ' + money(cost) + '/month')
        elif nxt is not None:
            f = finding(r, 'R1-rightsize', 'Move to the next size down', cost - nxt,
                        'GPU use averages ' + str(avg) + '% (peak ' + str(mx) + '%) over 7 days, ' + money(cost) + '/month now, ' + money(nxt) + ' one size down')
    elif t in ('vm', 'database', 'gpu_vm') and env in ('dev', 'test') and r.get('runs_24x7') and avg < 30:
        f = finding(r, 'R2-schedule', OFFHOURS, cost * SCHED,
                    env + ' resource runs 24/7 with ' + str(avg) + '% average use, costs ' + money(cost) + '/month')
    elif t in ('vm', 'database') and env in ('prod', 'staging') and avg < 20 and mx < 40 and nxt is not None:
        f = finding(r, 'R5-rightsize', 'Move to the next size down', cost - nxt,
                    'use averages ' + str(avg) + '% (peak ' + str(mx) + '%) over 7 days, ' + money(cost) + '/month now, ' + money(nxt) + ' one size down')
    if f:
        findings.append(f)

findings.sort(key=lambda x: -x['monthly_saving'])
print(json.dumps({'findings': findings}))

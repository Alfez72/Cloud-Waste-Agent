import json

findings = json.loads('''<< name: Python_Sandbox_findings_raw, prompt: false >>''')['findings']
judgment_text = '''<< name: judgments, prompt: false >>'''

# The judge should answer:  resource_id ## RECOMMEND or CONFIRM ## short reason
# Small models vary the format and mAIstro append mode glues answers together, so we do not rely on lines or exact
# separators: we find every known resource id in the text and read the first verdict word that follows it.
known_ids = set(f['resource_id'] for f in findings)
# the model often writes the resource NAME instead of the id, so both count as keys
keys = {}
for f in findings:
    keys[f['resource_id'].lower()] = f['resource_id']
    keys[f['name'].lower()] = f['resource_id']
judged = {}
low = judgment_text.lower()
spots = []
for key, rid in keys.items():
    start = 0
    while True:
        p = low.find(key, start)
        if p < 0:
            break
        after = low[p + len(key):p + len(key) + 1]
        before = low[p - 1:p] if p > 0 else ' '
        if not (after.isalnum() or after == '-') and not (before.isalnum() or before == '-'):
            spots.append((p, len(key), rid))
        start = p + len(key)
spots.sort()
for k in range(len(spots)):
    p, klen, rid = spots[k]
    end = spots[k + 1][0] if k + 1 < len(spots) else len(judgment_text)
    seg = judgment_text[p + klen:end]
    up = seg.upper()
    pr = up.find('RECOMMEND')
    pc = up.find('CONFIRM')
    hits = [x for x in (pr, pc) if x >= 0]
    if not hits:
        continue
    first = min(hits)
    verdict = 'RECOMMEND' if first == pr else 'CONFIRM'
    rest = seg[first:].split()
    rest = rest[1:] if rest else []
    reason = ' '.join(w for w in rest if w.strip('#:|-*`.,').upper() != 'ID' and w.strip('#:|-*`') != '')
    reason = reason.strip(' #:|-*`')
    judged.setdefault(rid, []).append((verdict, reason))

# fallback: the judge answered without echoing ids -> use the order if the counts match exactly
if not judged:
    words = [w.strip('#:|-*`.,').upper() for w in judgment_text.split()]
    verdicts = [('RECOMMEND' if w.startswith('RECOMMEND') else 'CONFIRM') for w in words if w.startswith('RECOMMEND') or w.startswith('CONFIRM')]
    if len(verdicts) == len(findings):
        for f, v in zip(findings, verdicts):
            judged.setdefault(f['resource_id'], []).append((v, 'judge answered in order'))

# a RECOMMEND from the AI only counts if the notes also contain a clear abandonment phrase
ABANDON = ['leftover', 'left over', 'left behind', 'left running', 'abandoned', 'forgot', 'by mistake',
           'no longer', 'not used', 'unused', 'never used', 'nobody', 'no one', 'temporary', 'temp ',
           'replaced', 'superseded', 'cancelled', 'canceled', 'finished', 'expired', 'ended',
           'approved', 'safe to remove', 'can be removed', 'can go']

def clear_abandon(notes):
    n = (notes or '').lower()
    for w in ABANDON:
        if w in n:
            return True
    return False

for f in findings:
    votes = judged.get(f['resource_id'], [('CONFIRM', 'no judgment returned')])
    has_notes = (f.get('notes') or '').strip() != ''
    confirm_votes = [v for v in votes if not v[0].startswith('RECOMMEND')]
    if f['status'] == 'confirm':
        f['final_status'] = 'OWNER MUST CONFIRM'
        f['final_reason'] = f['status_reason']
    elif not has_notes:
        f['final_status'] = 'RECOMMENDED'
        f['final_reason'] = 'no notes or tags suggest it is needed'
    elif confirm_votes:
        f['final_status'] = 'OWNER MUST CONFIRM'
        f['final_reason'] = confirm_votes[0][1]
    elif not clear_abandon(f.get('notes')):
        f['final_status'] = 'OWNER MUST CONFIRM'
        f['final_reason'] = 'notes do not clearly say it is unused'
    else:
        f['final_status'] = 'RECOMMENDED'
        f['final_reason'] = votes[0][1]

def money(x):
    return '$' + '{:,.2f}'.format(x)

rec = [f for f in findings if f['final_status'] == 'RECOMMENDED']
con = [f for f in findings if f['final_status'] != 'RECOMMENDED']
rec_total = round(sum(f['monthly_saving'] for f in rec), 2)
con_total = round(sum(f['monthly_saving'] for f in con), 2)

teams = {}
for f in findings:
    teams.setdefault(f['owner_team'], []).append(f)

def facts(items):
    lines = []
    for i in items:
        head = i['name'] + ' (' + i['type'] + ', ' + i['environment'] + '): ' + i['evidence'] + '.'
        if i['final_status'] == 'RECOMMENDED':
            lines.append(head + ' We propose: ' + i['action'] + '. Monthly saving if you approve: ' +
                         money(i['monthly_saving']) + '. Please reply to approve this action.')
        else:
            lines.append(head + ' We are not proposing any change yet. Please confirm whether it is still needed. ' +
                         ('Possible saving if you resize it: ' if 'size down' in i['action'] else 'Possible saving only if it is not needed: ') + money(i['monthly_saving']) +
                         ' (not counted). Why we are asking: ' + i['final_reason'].rstrip('. ') + '.')
    return (chr(10) + chr(10)).join(lines)

team_list = []
for t in sorted(teams):
    items = teams[t]
    label = 'cloud governance' if (t or '').lower() in ('', 'unassigned', 'unknown') else t
    team_total = round(sum(i['monthly_saving'] for i in items if i['final_status'] == 'RECOMMENDED'), 2)
    if team_total > 0:
        total_line = 'Total saving from the items waiting for approval: ' + money(team_total) + ' per month.'
    else:
        total_line = 'No saving is counted until you confirm the items above.'
    team_list.append({
        'total_line': total_line,
        'team': t,
        'count': len(items),
        'team_recommended_saving': round(sum(i['monthly_saving'] for i in items if i['final_status'] == 'RECOMMENDED'), 2),
        'facts': facts(items),
        'email_head': ('Subject: Cloud waste review for the ' + label + ' team' + chr(10) + chr(10) +
                       'Hi ' + label + ' team,' + chr(10) + chr(10) +
                       'Our cloud waste review found ' + str(len(items)) + (' resource' if len(items) == 1 else ' resources') + ' that ' + ('looks' if len(items) == 1 else 'look') + ' wasteful. ' +
                       'For each one we either ask you to approve an action or to confirm it is still needed. ' +
                       'Nothing changes until you reply.'),
    })

summary_text = ('CLOUD WASTE REPORT' + chr(10) +
                'Findings: ' + str(len(findings)) + chr(10) +
                'Recommended (owner approval needed): ' + str(len(rec)) + ', saving ' + money(rec_total) + ' per month' + chr(10) +
                'Owner must confirm first: ' + str(len(con)) + ', possible saving ' + money(con_total) + ' per month (not counted)')

needs_judge = [f for f in findings if f['status'] != 'confirm' and (f.get('notes') or '').strip() != '']
if needs_judge and not judged:
    summary_text = (summary_text + chr(10) + 'WARNING: the AI judge returned nothing usable, so every finding with notes is held for owner confirmation. ' +
                    'Raw judge output (first 400 characters): ' + judgment_text.strip()[:400])
print(json.dumps({'summary_text': summary_text, 'teams': team_list}))

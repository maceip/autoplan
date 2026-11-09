import json,re,sys,collections
rs=[json.loads(l) for l in open(sys.argv[1])]
N=len(rs)
SIG={
 'correction': r'^(no\b|nope|wrong|that.?s (not|wrong)|not what i|you misunderstood|i (said|told you|asked)|why (did|are|would) you|stop\b|hold up|wait\b)|\b(you (lied|faked|broke|missed|forgot|ignored)|did you (lie|even (try|test|check))|still (broken|not|failing|wrong))',
 'relay_between_agents': r'\b(tell (the|him|her|them)|give (this|it|the) .{0,30}agent|what (should|do) i tell|paste (this|it) (to|into)|send (this|it) to the|from the other agent|the other agent (said|says|thinks)|here.?s what .{0,20}(agent|codex|gemini|claude|cursor|muse) said)',
 'pasted_agent_output': r'(^|\n)\s*(•|⏺|✔|✓|- \[[ x]\]|#{2,4} \d)|<-\s',
 'wrong_target': r'\b(wrong (agent|tab|window|session|terminal|folder|directory|clone)|different (tab|clone|terminal)|meant (this|that) for)',
 'dictation': r'\b(uh|um|uhh|umm)\b|\bI, I\b|\b(\w+), \2\b',
 'image_evidence_from_user': r'\[Image #\d|\.png|\.jpg|screenshot',
 'interrupt_stop': r'^(stop|hold (up|on)|wait|pause|cancel|don.?t)\b',
 'honesty_check': r'\b(is (it|this|that) real|what.?s (still )?(fake|mocked)|honest(ly)?|lie|lying|lied|truth(ful)?)\b',
 'approval_or_go': r'^(ok(ay)?|yes|yep|sure|do it|go|go ahead|proceed|approved?|lgtm|ship it|sounds good|perfect|commit( and push)?|push( it)?|continue|keep going)\b.{0,40}$',
}
c=collections.Counter(); ex=collections.defaultdict(list)
for r in rs:
  for k,p in SIG.items():
    if re.search(p,r['text'],re.I|re.M):
      c[k]+=1
      if len(r['text'])<300: ex[k].append(r['text'])
for k,v in c.most_common(): print(f'{k:26}{v:6}{100*v/N:6.1f}%')
import random; random.seed(11)
for k in ['relay_between_agents','wrong_target','approval_or_go','correction']:
  print('##',k)
  for t in random.sample(ex[k],min(10,len(ex[k]))): print('  -',t[:200].replace('\n',' '))
# corrections by month for trend
import datetime as D
def mo(r):
  t=r['ts']
  try:
    if isinstance(t,str): return t[:7]
    if t>1e15:t/=1e6
    elif t>1e12:t/=1e3
    return D.datetime.utcfromtimestamp(t).strftime('%Y-%m')
  except Exception: return None
tot=collections.Counter(); cor=collections.Counter()
for r in rs:
  m=mo(r)
  if not m: continue
  tot[m]+=1
  if re.search(SIG['correction'],r['text'],re.I|re.M) or re.search(SIG['honesty_check'],r['text'],re.I): cor[m]+=1
print('correction+honesty share by month:',{m:f'{100*cor[m]/tot[m]:.0f}%' for m in sorted(tot)})

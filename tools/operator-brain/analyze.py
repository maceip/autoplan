import json,re,sys,collections,datetime as D
rs=[json.loads(l) for l in open(sys.argv[1])]
def ts(r):
  t=r['ts']
  try:
    if isinstance(t,str): return D.datetime.fromisoformat(t.replace('Z','+00:00'))
    if isinstance(t,(int,float)):
      if t>1e15: t/=1e6
      elif t>1e12: t/=1e3
      return D.datetime.fromtimestamp(t,D.timezone.utc)
  except Exception: return None
for r in rs: r['dt']=ts(r)
dts=[r['dt'] for r in rs if r['dt']]
print('span',min(dts).date(),max(dts).date(),'timestamped',len(dts))
# projects
proj=collections.Counter((r['cwd'] or '').replace('/Users/mac/','~/').split('/.mimo-sessions')[0] for r in rs if r['cwd'])
print('distinct cwds',len(proj)); print(proj.most_common(25))
# sessions per day / concurrency
days=collections.defaultdict(set); dsrc=collections.defaultdict(set)
for r in rs:
  if r['dt']: d=r['dt'].astimezone().date(); days[d].add((r['src'],r['session'])); dsrc[d].add(r['src'])
sz=sorted(len(v) for v in days.values()); print('active days',len(days),'median sessions/day',sz[len(sz)//2],'p90',sz[int(len(sz)*.9)],'max',sz[-1])
ms=sorted(len(v) for v in dsrc.values()); print('median services/day',ms[len(ms)//2])
# per-month by src
mon=collections.Counter((r['dt'].strftime('%Y-%m'),r['src']) for r in rs if r['dt'])
for m in sorted(set(k[0] for k in mon)): print(m,{k[1]:v for k,v in mon.items() if k[0]==m})
# hour histogram local
hr=collections.Counter(r['dt'].astimezone().hour for r in rs if r['dt']); print('hours',sorted(hr.items()))
CATS={
 'fake_mock':r'\b(fake|mock(ed)?|placeholder|fabricat|hardcod|dummy|stub(bed)?|simulat(ed|ion)|not real|is it real|for real|actually real|what.?s still fake)\b',
 'verify_evidence':r'\b(screenshot|screen ?shot|video|record(ing)?|show me|prove|proof|verif(y|ied)|e2e|end.to.end|playwright|emulator|on (the )?device|did you (test|check|run))\b',
 'stopped_short':r'\b(keep going|continue|don.?t stop|why did you stop|finish (it|the)|you stopped|not done|still not|STILL)\b',
 'commit_git':r'\b(commit|push|branch|worktree|merge|rebase|PR\b|pull request)',
 'lost_work':r'\b(lost|overwrote|overwritten|wiped|deleted my|where did .* go|revert(ed)? my|clobber)',
 'other_agent':r'\b(other agent|another agent|the \w+ agent|agents? (is|are) working|different session|other session|tell the|handoff|hand off|subagent|sub-agent)\b',
 'frustration':r'\b(wtf|wwtaf|fuck|shit|ffs|seriously|again\?|i told you|i said|you said|lied|lying|stop lying|why (would|did) you)\b',
 'status_query':r'\b(status|where are we|what.?s left|what is left|progress|how.?s it (going|looking)|are we done|is it (done|working))\b',
 'ui_design':r'\b(ui|ux|design|layout|css|font|color|colour|button|toggle|screen|pixel|animation|dark mode|theme)\b',
 'security':r'\b(security|secure|vuln|cve|audit|auth|secret|credential|token|key leak|ssl|tls|attest)',
 'approve_go':r'^(ok(ay)?|yes|yep|y|do it|go|go ahead|proceed|approved?|lgtm|ship it|sounds good|great|perfect|commit and push|push it)[.!,\s]*$',
 'ideas':r'\b(idea|what if|could we|brainstorm|suggest|recommend|should we)\b',
 'ci':r'\b(ci|github actions|workflow run|green|failing (test|build)|build (is )?fail)',
 'scope_quality':r'\b(rush|sloppy|lazy|shortcut|half.?ass|cut corners|quality|rate your)\b',
}
cc=collections.Counter(); bysrc=collections.defaultdict(collections.Counter); ex=collections.defaultdict(list)
for r in rs:
  t=r['text']
  for k,p in CATS.items():
    if re.search(p,t,re.I|re.M):
      cc[k]+=1; bysrc[r['src']][k]+=1
      if len(t)<400: ex[k].append(t)
N=len(rs); print('N',N)
for k,v in cc.most_common(): print(f'{k:16} {v:6} {100*v/N:5.1f}%')
import random; random.seed(7)
json.dump({k:random.sample(v,min(40,len(v))) for k,v in ex.items()},open(sys.argv[2],'w'),indent=1)
lens=sorted(len(r['text']) for r in rs); print('len median',lens[N//2],'p90',lens[int(N*.9)])
short=sum(1 for r in rs if len(r['text'])<40); print('short <40 chars',short, f'{100*short/N:.1f}%')

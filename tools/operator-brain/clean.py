import json,re,sys,collections
SECRET=re.compile(r'(hf_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|gh[ousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[bp]-[A-Za-z0-9-]{20,}|eyJ[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|[A-Za-z0-9+/]{48,}={0,2})')
seen=set(); n=collections.Counter()
o=open(sys.argv[2],'w')
for l in open(sys.argv[1]):
  r=json.loads(l); t=r['text']
  if r['src'].startswith('antigravity'):
    if re.search(r'\$[0-9a-f-]{36}|image/png|\.user_uploaded|^\S{0,3}\s*#\w+$',t): continue
    t=re.sub(r'^[^\sA-Za-z0-9/@"\'(\[<*#`-]{0,2}[\x21-\x7e]?\s?(?=[A-Za-z0-9/@"\'(\[<*#`])','',t)
    t=re.sub(r'^.{1,2}(?=[A-Z][a-z])','',t) if re.match(r'^.{1,2}[A-Z][a-z]',t) and not re.match(r'^[A-Z][a-z]',t) else t
    t=t.rstrip('"*')
  if t.startswith(('<codex_internal_context','<background-task','[Pasted Content')) or len(t)<2: continue
  t=SECRET.sub('[REDACTED]',t)
  k=(r['src'],t[:300])
  if k in seen: continue
  seen.add(k); r['text']=t; n[r['src']]+=1; o.write(json.dumps(r)+'\n')
print(dict(n), sum(n.values()))

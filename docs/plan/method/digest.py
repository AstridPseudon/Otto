import json,re,sys,os
SR=re.compile(r'<system-reminder>.*?</system-reminder>',re.S)
def clean(t): return SR.sub('',t).strip()
def ts(d): t=d.get('timestamp','');return t[5:16].replace('T',' ')
def emit(path,out,label=''):
    for line in open(path):
        try:d=json.loads(line)
        except: continue
        typ=d.get('type')
        if typ not in('user','assistant'): continue
        m=d.get('message',{}); c=m.get('content')
        t=ts(d)
        if d.get('isCompactSummary'):
            out.append(f"[{t}] === COMPACTION SUMMARY ===\n{clean(c if isinstance(c,str) else ' '.join(x.get('text','') for x in c if isinstance(x,dict)))}\n=== END SUMMARY ===");continue
        if isinstance(c,str): c=[{'type':'text','text':c}]
        if not isinstance(c,list): continue
        for x in c:
            if not isinstance(x,dict): continue
            k=x.get('type')
            if typ=='user' and k=='text':
                s=clean(x['text'])
                if not s or d.get('isMeta'): continue
                if 'task-notification' in s or 'SYSTEM NOTIFICATION' in s: out.append(f"[{t}] NOTIFY: {s[:300]}"); continue
                out.append(f"[{t}] USER{label}: {s[:6000]}")
            elif typ=='user' and k=='tool_result':
                r=x.get('content'); r=r if isinstance(r,str) else ' '.join(y.get('text','') for y in (r or []) if isinstance(y,dict))
                r=clean(r).replace('\n',' ')
                err=x.get('is_error') or 'rror' in r[:200] or 'denied' in r[:300].lower() or 'blocked' in r[:300].lower()
                out.append(f"[{t}]   {'RESULT-ERR' if err else 'result'}: {r[:400 if err else 160]}")
            elif typ=='assistant' and k=='text':
                s=x['text'].strip()
                if s: out.append(f"[{t}] ASSISTANT{label}: {s[:2500]}")
            elif typ=='assistant' and k=='tool_use':
                i=x.get('input',{}); 
                desc=i.get('description') or ''
                body=i.get('command') or i.get('prompt') or i.get('message') or i.get('file_path') or json.dumps(i)
                lim=1500 if x.get('name') in ('Agent','mcp__claude-code-remote__send_message','mcp__claude-code-remote__create_session','AskUserQuestion','mcp__claude-code-remote__create_trigger') else 250
                out.append(f"[{t}]   TOOL {x.get('name')} ({desc}): {str(body)[:lim]}")
out=[]
for p in sys.argv[2:]: emit(p,out)
open(sys.argv[1],'w').write('\n'.join(out))
print(len(out), sum(len(x) for x in out))

"""Read public exchange calendars/pricing; no account login or order creation."""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urljoin

URLS = {
 'sse': 'https://www.sse.com.cn/services/tradingservice/tradingcalendar/',
 'szse': 'https://www.szse.cn/marketServices/deal/index.html',
 'jqdata': 'https://www.joinquant.com/default/index/sdk',
 'rqdata': 'https://www.ricequant.com/welcome/pricing',
}

def read(item):
 name,url=item
 row={'name':name,'url':url}
 try:
  with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=25) as response:
   body=response.read(2000000).decode('utf-8',errors='replace')
  text=unescape(re.sub('<[^>]+>', ' ', body));text=re.sub(r'\s+', ' ',text)
  row['snippets']=[text[max(0,m.start()-120):m.end()+400] for m in list(re.finditer(r'国庆|2026年|2026-|元/|元／|资金流|价格|收费|pricing',text))[:22]]
  row['links']=[urljoin(url,u) for u in re.findall(r'(?:href|src)=["\']([^"\']+)["\']',body) if any(w in u.lower() for w in ('2026','calendar','holiday','pricing','price','trade','deal','data','js/'))][-35:]
  row['status']='received'
 except Exception as e:
  row.update(status='unavailable',error=type(e).__name__)
 return row

if __name__=='__main__':
 with ThreadPoolExecutor(max_workers=4) as pool: rows=list(pool.map(read,URLS.items()))
 Path('/tmp/source-research.json').write_text(json.dumps({'checkedAt':datetime.now(timezone.utc).isoformat(),'sources':rows},ensure_ascii=False,indent=2))

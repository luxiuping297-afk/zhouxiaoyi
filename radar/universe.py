"""Verified Tencent aStock pagination, including explicit sh/sz/bj identities."""
from datetime import datetime
from .engine import CHINA
from .provider import DataError, get_json, valid_symbol

URL = 'https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList'


def universe(fetch=get_json):
    rows=[];seen=set();expected=None
    for offset in range(0,20000,200):
        payload=fetch(URL,dict(_appver='11.17.0',board_code='aStock',sort_type='price',direct='down',offset=offset,count=200))
        data=payload.get('data')
        if payload.get('code')!=0 or not isinstance(data,dict):
            raise DataError('腾讯全A列表未返回成功数据')
        total=int(data.get('total',0));page=data.get('rank_list')
        if expected is None:expected=total
        if expected<=0 or total!=expected or not isinstance(page,list) or not page or len(page)>200:
            raise DataError('腾讯证券列表总数变化、为空或分页结构异常')
        if int(data.get('offset',-1))!=offset:
            raise DataError('证券列表返回offset与请求不一致')
        for record in page:
            code=record.get('code','');prefix=code[:2];symbol=valid_symbol(code[2:])
            if prefix not in ('sh','sz','bj') or not record.get('name'):
                raise DataError('证券列表缺少市场身份或名称')
            expected_prefix='sh' if symbol.startswith('6') else 'sz' if symbol.startswith(('0','3')) else 'bj'
            if prefix!=expected_prefix or code in seen:
                raise DataError('证券列表市场身份不符或分页重复；不能声称完整覆盖')
            seen.add(code);rows.append(dict(symbol=symbol,code=code,name=record['name'],exchange={'sh':'沪','sz':'深','bj':'京'}[prefix]))
        if len(rows)==expected:
            return dict(source=URL,fetchedAt=datetime.now(CHINA).isoformat(),reportedTotal=expected,complete=True,stocks=rows,
                        exchangeCounts={x:sum(r['exchange']==x for r in rows) for x in ('沪','深','京')})
        if len(rows)>expected:
            raise DataError('证券列表数量超过供应商总数')
    raise DataError('证券列表超过分页安全上限')

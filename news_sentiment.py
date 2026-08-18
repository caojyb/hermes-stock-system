#!/usr/bin/env python3
"""
AI 新闻解读模块（试点）
======================
数据源: 东方财富 7×24 快讯（LightPanda 浏览器抓取）
试点范围: 当前候选池 23 只
分类: 🟢利好 / 🔴利空 / ⚪中性
集成: 标记舆情信号，影响推荐等级
"""
import os, sys, json, sqlite3, re, requests
from datetime import date, datetime, timedelta
from pathlib import Path

NEWS_CACHE_DB = os.path.join(os.path.dirname(__file__), 'news_cache.db')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pool_loader
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / 'skills/stock/stock-expert'))
from stock_db_paths import get_db_path
MKT_DB = str(get_db_path('market_cache'))

HEADERS = {'User-Agent': 'Mozilla/5.0'}

# 候选池股票代码和名称关键词
CANDIDATE_CODES = [
    '603991','002192','301219','301606','002850',
    '000037','000504','001218','002693','002842',
    '003032','300343','300404','300681','300890',
    '301026','301031','301302','301510','600191',
    '603270','603276','603329','603588','605305'
]

CANDIDATE_KEYWORDS = [
    '融捷','领先','腾远','绿联','科达利',
    '深南电','南华生物','丽臣实业','双成药业','翔鹭钨业',
    '传智教育','联创股份','博济医药','英搏尔','翔丰华',
    '浩通科技','中熔电气','华如科技','固高科技','华资实业',
    '金帝股份','恒兴新材','上海雅仕','高能环境','中际联合'
]

def init_db():
    conn = sqlite3.connect(NEWS_CACHE_DB)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS news_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_url TEXT,
            news_title TEXT,
            news_time TEXT,
            raw_content TEXT,
            fetched_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(news_url)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS sentiment_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            name TEXT,
            news_url TEXT,
            news_title TEXT,
            news_time TEXT,
            sentiment TEXT,
            reason TEXT,
            trade_date TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    ''')
    conn.commit()
    return conn

def fetch_news_via_api():
    """通过东财搜索API获取个股新闻"""
    pool_map = get_pool_names()
    all_news = []
    seen_urls = set()
    
    for code in CANDIDATE_CODES:
        try:
            url = 'https://search-api-web.eastmoney.com/search/jsonp'
            params = {
                'cb': 'jQuery',
                'param': json.dumps({'uid':'','keyword':code,'type':['cmsArticleWebOld'],
                    'client':'web','clientType':'web','clientVersion':'curr'}, ensure_ascii=False),
            }
            r = requests.get(url, params=params, timeout=10, headers=HEADERS)
            text = r.text
            if text.startswith('jQuery'):
                import re
                json_str = re.search(r'jQuery\((.*)\)', text).group(1)
                d = json.loads(json_str)
                articles = d.get('result', {}).get('cmsArticleWebOld', [])
                for a in articles[:5]:  # 每只股票最多取5条
                    news_url = a.get('url', '')
                    title = a.get('title', '')
                    # 去HTML标签
                    title = re.sub(r'<[^>]+>', '', title)
                    if news_url and news_url not in seen_urls:
                        seen_urls.add(news_url)
                        all_news.append({
                            'url': news_url,
                            'title': title,
                            'content': title + ' ' + a.get('content', ''),
                            'time': a.get('date', '')[:10],
                            'matched_codes': [code],
                            'matched_names': [pool_map.get(code, '')],
                        })
        except:
            continue
    
    return all_news

def parse_news_from_markdown(markdown_text):
    """从LightPanda markdown输出中解析新闻"""
    news_items = []
    
    # 匹配快讯格式: HH:MM [标题](url)
    # 或: HH:MM 文本
    lines = markdown_text.split('\n')
    current_time = None
    
    for line in lines:
        line = line.strip()
        # 匹配时间格式 如 "10:11" "09:58"
        time_match = re.match(r'^(\d{2}:\d{2})\s*(.*)', line)
        if time_match:
            current_time = time_match.group(1)
            content = time_match.group(2)
            # 检查是否是新闻链接
            link_match = re.match(r'\[(.+?)\]\((https?://[^\)]+)\)', content)
            if link_match:
                title = link_match.group(1)
                url = link_match.group(2)
                news_items.append({
                    'time': current_time,
                    'title': title,
                    'url': url,
                    'content': title
                })
            elif content.strip():
                news_items.append({
                    'time': current_time,
                    'title': content.strip(),
                    'url': '',
                    'content': content.strip()
                })
    
    return news_items

def filter_relevant_news(news_items):
    """筛选与候选池相关的新闻"""
    relevant = []
    for item in news_items:
        content = item.get('content', '') + item.get('title', '')
        matched_codes = []
        matched_names = []
        
        for code in CANDIDATE_CODES:
            if code in content:
                matched_codes.append(code)
        
        for name in CANDIDATE_KEYWORDS:
            if name in content:
                matched_names.append(name)
        
        if matched_codes or matched_names:
            item['matched_codes'] = matched_codes
            item['matched_names'] = matched_names
            relevant.append(item)
    
    return relevant

# OpenRouter/OpenCode AI 配置（从 Hermes 配置继承）
LLM_API_URL = 'https://opencode.ai/zen/v1/chat/completions'
LLM_API_KEY = os.environ.get('LLM_API_KEY', '')
LLM_MODEL = 'deepseek-v4-flash-free'

# 每天最多用AI分析的新闻条数，超出用关键词兜底
MAX_AI_NEWS = 50
_ai_call_count = 0

def classify_with_ai(code, news_title, news_content):
    """
    用大模型对新闻做语义三分类
    返回: (sentiment, confidence, summary, key_reason)
    sentiment: 'positive'|'negative'|'neutral'
    """
    text = f"{news_title} {news_content}"
    text = text[:200]  # 截取前200字
    
    prompt = f"""分析以下A股新闻，判断其对{code}的影响。

新闻：{text}

请输出JSON格式：
{{
  "sentiment": "positive/negative/neutral",
  "confidence": 0.0-1.0,
  "summary": "一句话摘要（20字内）",
  "key_reason": "判断依据"
}}"""

    try:
        r = requests.post(LLM_API_URL, json={
            'model': LLM_MODEL,
            'messages': [
                {'role': 'system', 'content': '你是一个A股新闻分析师。输出JSON，不要加markdown。'},
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.1,
            'max_tokens': 500
        }, timeout=30, headers={
            'Authorization': f'Bearer {LLM_API_KEY}',
            'Content-Type': 'application/json'
        })
        result = r.json()
        choice = result.get('choices', [{}])[0]
        msg = choice.get('message', {})
        content = msg.get('content', '{}')
        # 清理可能的markdown标记
        content = content.strip().replace('```json', '').replace('```', '')
        parsed = json.loads(content)
        
        sentiment = parsed.get('sentiment', 'neutral')
        confidence = float(parsed.get('confidence', 0.5))
        summary = parsed.get('summary', '')
        reason = parsed.get('key_reason', '')
        
        # 转换标签
        if sentiment == 'positive' and confidence >= 0.7:
            return ('🟢利好', confidence, summary, reason)
        elif sentiment == 'negative' and confidence >= 0.7:
            return ('🔴利空', confidence, summary, reason)
        else:
            return ('⚪中性', confidence, summary, reason)
    
    except Exception as e:
        # AI失败，回退到关键词
        return classify_keyword(code, news_title, news_content)

def classify_keyword(code, news_title, news_content):
    """关键词兜底分类"""
    text = f"{news_title} {news_content}"
    bullish_words = ['增持','业绩预增','战略合作','重大合同','中标','回购','分红','送转','创新高','放量突破']
    bearish_words = ['减持','监管','问询','立案','调查','ST','亏损','暴雷','退市','违约','延期','下调']
    
    has_bullish = any(w in text for w in bullish_words)
    has_bearish = any(w in text for w in bearish_words)
    
    if has_bearish and not has_bullish:
        return ('🔴利空', 0.5, f'{code}相关新闻', '关键词匹配：利空')
    if has_bullish and not has_bearish:
        return ('🟢利好', 0.5, f'{code}相关新闻', '关键词匹配：利好')
    return ('⚪中性', 0.3, f'{code}相关新闻', '无明确情绪')

def classify_sentiment(code, news_title, news_content, use_ai=True):
    """
    对新闻做三分类
    返回: (sentiment_label, reason)
    sentiment_label: '🟢利好'|'🔴利空'|'⚪中性'
    """
    global _ai_call_count
    if use_ai and _ai_call_count < MAX_AI_NEWS:
        _ai_call_count += 1
        try:
            sentiment, confidence, summary, reason = classify_with_ai(code, news_title, news_content)
            if confidence >= 0.7:
                return (sentiment, f'{summary} | 置信度{confidence:.0%}| {reason}')
        except:
            pass
    
    # AI不可用或置信度低，回退关键词
    sentiment, _, _, reason = classify_keyword(code, news_title, news_content)
    return (sentiment, f'关键词: {reason}')

def save_sentiment(conn, code, name, news_item, sentiment, reason, trade_date):
    cur = conn.cursor()
    try:
        cur.execute('''
            INSERT INTO sentiment_results 
            (code, name, news_url, news_title, news_time, sentiment, reason, trade_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (code, name, news_item.get('url', ''), news_item.get('title', ''),
              news_item.get('time', ''), sentiment, reason, trade_date))
        conn.commit()
        return True
    except:
        return False

def get_pool_names():
    """获取候选池代码和名称映射（统一从 double_up_scores 表读取）"""
    try:
        return {s['code']: s['name'] for s in pool_loader.load_pool()}
    except:
        return {}

def run(news_markdown=None):
    """主入口 - 从LightPanda markdown输出中提取并分析新闻"""
    today = date.today().isoformat()
    conn = init_db()
    pool_map = get_pool_names()
    
    # 获取新闻
    if news_markdown:
        # 从LightPanda markdown解析
        news_items = parse_news_from_markdown(news_markdown)
        print(f'📰 解析到 {len(news_items)} 条新闻')
    else:
        # 尝试HTTP获取
        news_items = fetch_news_via_api()
        if news_items:
            print(f'📰 HTTP获取到 {len(news_items)} 条新闻')
        else:
            print('📰 请使用 LightPanda 获取快讯页面后传入 markdown 文本')
            conn.close()
            return
    
    # 筛选相关新闻
    relevant = filter_relevant_news(news_items)
    
    if not relevant:
        print(f'   📌 候选池无相关新闻')
        conn.close()
        return
    
    print(f'   🎯 候选池相关新闻: {len(relevant)} 条')
    
    # 分类并输出
    results = []
    for item in relevant:
        codes = item.get('matched_codes', [])
        names = item.get('matched_names', [])
        content = item.get('content', '')
        title = item.get('title', '')
        
        # 先确定涉及的候选池股票
        for code in codes:
            pool_name = pool_map.get(code, code)
            sentiment, reason = classify_sentiment(code, title, content)
            if save_sentiment(conn, code, pool_name, item, sentiment, reason, today):
                results.append({
                    'code': code,
                    'name': pool_name,
                    'news': title,
                    'sentiment': sentiment,
                    'reason': reason
                })
        
        for name in names:
            # 如果已经通过code匹配过了就跳过
            if any(name in (r.get('code','') + r.get('name','')) for r in results):
                continue
            sentiment, reason = classify_sentiment('', title, content)
            results.append({
                'code': '',
                'name': name,
                'news': title,
                'sentiment': sentiment,
                'reason': reason
            })
    
    # 输出报告
    print(f"\n{'='*55}")
    print(f"📊 新闻情绪分析报告 | {today}")
    print(f"{'='*55}")
    
    has_negative = False
    for r in results:
        tag = r['sentiment']
        print(f"\n   {tag} {r['news'][:60]}...")
        if r['code']:
            print(f"      涉及候选: {r['name']}({r['code']}) | {r['reason']}")
            if '🔴' in tag:
                has_negative = True
        else:
            print(f"      涉及候选: {r['name']} | {r['reason']}")
    
    # 标记总结
    positives = [r for r in results if '🟢' in r['sentiment']]
    negatives = [r for r in results if '🔴' in r['sentiment']]
    
    print(f"\n{'─'*55}")
    print(f"📊 舆情汇总")
    if positives:
        codes_pos = [r['code'] for r in positives if r['code']]
        print(f"   📰 舆情利好: {len(positives)} 条, 涉及 {', '.join(set(codes_pos))}")
    if negatives:
        codes_neg = [r['code'] for r in negatives if r['code']]
        print(f"   ⛔ 舆情利空: {len(negatives)} 条, 涉及 {', '.join(set(codes_neg))}")
        print(f"   ⚠️ 以下候选股推荐等级降一级: {', '.join(set(codes_neg))}")
    
    conn.close()
    # 记录管道状态
    try:
        from pipeline_status import record_status
        record_status('stock-news-sentiment-pilot', 'ok', date.today().isoformat(),
                      row_count=len(results), message=f'{len(results)} 条舆情')
    except Exception:
        pass
    return results

if __name__ == '__main__':
    run()

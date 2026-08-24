#!/usr/bin/env python3
"""
盘中三档推荐扫描 - no_agent 模式 + westock-data 55指标交叉验证
候选池来源：indicators 表（每日 16:30 收盘后更新），不依赖每周评分表
数据流：
  - 候选股：indicators.signal_score >= 40 + rsi_14 < 50
  - 实时价格：新浪财经 API hq.sinajs.cn
  - 交叉验证：westock-data-skillhub（55个技术指标）
  - 持仓对齐：simulation.db + Bitable 真实持仓
有推荐时直接发飞书，不留本地文件
"""
import sqlite3, urllib.request, json, os, sys, subprocess
from datetime import datetime

# ── 路径配置 ──────────────────────────────────────────────
HERMES_DIR = os.path.expanduser("~/.hermes")
MARKET_DB = os.path.join(HERMES_DIR, "skills/stock/stock-expert/market_cache.db")
FEISHU_TOKEN = os.environ.get("FEISHU_BOT_TOKEN", "")

# ── 基本面过滤（JOIN financial_data + pe_pb_data）────────
def get_financial_filters(codes):
    """
    批量查询财务数据，返回 {code: {reject, reject_reason, warnings}}
    
    硬拒绝条件（任一条即排除）：
      1. pe_ttm < 0（亏损股，排除扭亏）
      2. ROE < -5（严重亏损）
      3. profit_growth < -50 AND ROE < 0（业绩大幅下滑且亏损）
      4. debt_ratio > 95（资不抵债）
    
    软警告（标记但不排除）：
      - 负债率 > 70% → 高负债
      - 营收负增长 → 营收下滑
      - 利润负增长 → 利润下滑
      - PE为负且扭亏 → TTM亏损
      - ROE < 5% → 低ROE
    """
    if not codes:
        return {}
    
    conn = sqlite3.connect(MARKET_DB)
    cur = conn.cursor()
    
    placeholders = ",".join("?" for _ in codes)
    
    # 财务数据（每只股票最新报告期）
    cur.execute(f"""
        SELECT f.code, f.roe, f.profit_growth, f.revenue_growth,
               f.debt_ratio, f.gross_margin, f.net_margin
        FROM financial_data f
        INNER JOIN (
            SELECT code, MAX(report_date) as max_date
            FROM financial_data
            WHERE code IN ({placeholders})
            GROUP BY code
        ) latest ON f.code = latest.code AND f.report_date = latest.max_date
    """, codes)
    fin_rows = {r[0]: r[1:] for r in cur.fetchall()}
    
    # PE/PB 数据（最新）
    cur.execute(f"""
        SELECT code, pe_ttm, pb_mrq
        FROM pe_pb_data
        WHERE code IN ({placeholders})
          AND fetch_date = (SELECT MAX(fetch_date) FROM pe_pb_data)
    """, codes)
    pepb_rows = {r[0]: r[1:] for r in cur.fetchall()}
    
    conn.close()
    
    result = {}
    for code in codes:
        fin = fin_rows.get(code)
        pepb = pepb_rows.get(code)
        
        roe = fin[0] if fin and fin[0] is not None else None
        profit_growth = fin[1] if fin and fin[1] is not None else None
        revenue_growth = fin[2] if fin and fin[2] is not None else None
        debt_ratio = fin[3] if fin and fin[3] is not None else None
        pe_ttm = pepb[0] if pepb and pepb[0] is not None else None
        
        warnings = []
        reject = False
        reject_reason = ""
        
        # ── 硬拒绝检查 ──
        # 1. PE为负 且 不是扭亏
        if pe_ttm is not None and pe_ttm < 0:
            is_turnaround = (roe is not None and roe > 0 
                             and profit_growth is not None and profit_growth > 0)
            if not is_turnaround:
                reject = True
                reject_reason = "PE为负(亏损股)"
            else:
                warnings.append("TTM亏损")
        
        # 2. ROE严重亏损
        if not reject and roe is not None and roe < -5:
            reject = True
            reject_reason = f"ROE={roe:.1f}%严重亏损"
        
        # 3. 业绩大幅下滑且亏损
        if not reject and (profit_growth is not None and profit_growth < -50
                           and roe is not None and roe < 0):
            reject = True
            reject_reason = f"利润暴跌{profit_growth:.0f}%且亏损"
        
        # 4. 资不抵债
        if not reject and debt_ratio is not None and debt_ratio > 95:
            reject = True
            reject_reason = f"负债率{debt_ratio:.0f}%资不抵债"
        
        # ── 软警告 ──
        if not reject:
            if debt_ratio is not None and debt_ratio > 70:
                warnings.append(f"高负债({debt_ratio:.0f}%)")
            if revenue_growth is not None and revenue_growth < -10:
                warnings.append("营收下滑")
            if profit_growth is not None and profit_growth < -30:
                warnings.append("利润下滑")
            if roe is not None and roe < 5:
                warnings.append(f"低ROE({roe:.1f}%)")
        
        result[code] = {
            "reject": reject,
            "reject_reason": reject_reason,
            "warnings": warnings,
        }
    
    return result


# ── 读持仓（simulation.db + Bitable）────────────────────
def get_holdings():
    """
    读取当前持仓，返回 {code: {name, source, buy_price, shares, ...}}
    source = simulation / bitable
    """
    holdings = {}

    # simulation.db
    try:
        _sim_path = None
        try:
            from simulation_db_helper import get_active_sim_db
            _sim_path = get_active_sim_db()
        except Exception:
            pass
        if not _sim_path:
            from pathlib import Path
            _sim_path = str(Path(__file__).resolve().parent.parent.parent.parent /
                            'skills/stock/stock-expert/simulation.db')

        conn = sqlite3.connect(_sim_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT code, name, buy_price, buy_shares, status, signal_type, buy_date
            FROM trades
            WHERE status IN ('持有', '部分止盈')
        """)
        for r in cur.fetchall():
            code, name, buy_price, shares, status, sig, buy_date = r
            holdings[code] = {
                'name': name or code,
                'source': 'simulation',
                'buy_price': float(buy_price or 0),
                'shares': int(shares or 0),
                'status': status,
                'signal_type': sig or '',
                'buy_date': str(buy_date or ''),
            }
        conn.close()
    except Exception as e:
        print(f"[WARN] 读取模拟仓失败: {e}")

    # Bitable 真实持仓
    try:
        from pathlib import Path
        _skill_dir = str(Path(__file__).resolve().parent.parent.parent /
                         'skills/stock/stock-expert/skills/feishu-bitable')
        sys.path.insert(0, _skill_dir)
        from bitable_reader import BitableReader
        reader = BitableReader(limit=100)
        result = reader._execute_command()
        data = json.loads(result.stdout)
        fields = data['data']['fields']
        records_raw = data['data']['data']
        for raw in records_raw:
            record = dict(zip(fields, raw))
            status_field = record.get('是否买入', [])
            if isinstance(status_field, list) and '已买入' in status_field:
                code = str(record.get('股票ID', '')).strip()
                name = str(record.get('name', '')).strip()
                if not code or not name:
                    continue
                cost_price = float(record.get('买入价格', 0) or 0)
                shares = int(record.get('持仓数量', 0) or 0)
                if code not in holdings:
                    holdings[code] = {
                        'name': name,
                        'source': 'bitable',
                        'buy_price': cost_price,
                        'shares': shares,
                        'status': '已买入',
                        'signal_type': '',
                        'buy_date': str(record.get('买入日期', '') or ''),
                    }
    except Exception as e:
        print(f"[WARN] 读取 Bitable 持仓失败: {e}")

    return holdings

# ── 读候选股票（indicators 表，每日刷新）─────────────────
def get_candidates():
    """
    从 indicators 表取候选股（每日 16:30 更新，盘中不变）
    过滤条件：
      - signal_score >= 40（技术面信号评分）
      - rsi_14 < 50（超跌/低位区域）
      - 排除 ST/*ST/S 股票
      - 排除下跌趋势股（ma_bullish = -1，接飞刀过滤）
    返回 (code, name, signal_score, rsi_14, cached_price, cached_chg, ma_bullish, ma20)
    """
    conn = sqlite3.connect(MARKET_DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT i.code, COALESCE(s.name, '') as name,
               i.signal_score, i.rsi_14,
               i.current_price, i.change_pct,
               i.ma_bullish, i.ma20
        FROM indicators i
        LEFT JOIN stocks s ON s.code = i.code
        WHERE i.date = (SELECT MAX(date) FROM indicators)
          AND i.rsi_14 < 50
          AND i.signal_score >= 40
          AND (i.ma_bullish IS NULL OR i.ma_bullish >= 0)  -- 排除下跌趋势
          AND (s.name NOT LIKE '%ST%' AND s.name NOT LIKE '%*ST%' AND s.name NOT LIKE '%S%' AND s.name NOT LIKE '%退%')
        ORDER BY i.signal_score DESC
        LIMIT 30
    """)
    rows = cur.fetchall()
    conn.close()
    return rows  # [(code, name, signal_score, rsi_14, price, chg, ma_bullish, ma20), ...]

# ── 查新浪实时行情（含现价和涨跌幅）───────────────────────
def get_sina_realtime(codes):
    """返回 {code: {price, change_pct}}，失败重试 3 次"""
    if not codes:
        return {}
    sina_codes = ",".join([f"{'sz' if c.startswith(('0','3')) else 'sh'}{c}" for c in codes])
    url = f"https://hq.sinajs.cn/list={sina_codes}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                text = resp.read().decode("gbk", errors="replace")
            if text.strip():
                break
        except Exception:
            if attempt < 2:
                continue
            return {}
    result = {}
    seen = set()
    for line in text.strip().split("\n"):
        if "=" not in line:
            continue
        code_raw = line.split("=")[0].split("_")[-1].strip()
        if code_raw in seen:
            continue
        seen.add(code_raw)
        parts = line.split('"')[1].split(",")
        if len(parts) < 10:
            continue
        try:
            price = float(parts[3])
            prev_close = float(parts[2])
            change_pct = 0.0
            if prev_close > 0:
                change_pct = (price - prev_close) / prev_close * 100
        except (ValueError, IndexError):
            continue
        result[code_raw] = {"price": price, "change_pct": change_pct}
    return result

# ── westock-data 55指标交叉验证 ────────────────────────────
def fetch_westock_technical(codes):
    """
    批量获取 westock-data 技术指标（最多处理 top5 候选）
    返回 {code: {kdj_k, kdj_d, kdj_j, wr_6, wr_10, cci_14, adx, bias_6, psy, ar, br, vr, ...}}
    """
    results = {}
    for code in codes[:5]:
        prefix = "sz" if code.startswith(("0", "3")) else "sh"
        symbol = f"{prefix}{code}"
        try:
            out = subprocess.run(
                ["npx", "-y", "westock-data-skillhub@1.0.3", "technical", symbol],
                capture_output=True, text=True, timeout=15
            )
            if out.returncode != 0:
                continue
            lines = out.stdout.strip().split("\n")
            if len(lines) < 3:
                continue
            headers = [h.strip() for h in lines[0].split("|")]
            values = [v.strip() for v in lines[2].split("|")]
            row = dict(zip(headers, values))
            results[code] = {
                "kdj_k": float(row.get("kdj.KDJ_K", 0) or 0),
                "kdj_d": float(row.get("kdj.KDJ_D", 0) or 0),
                "kdj_j": float(row.get("kdj.KDJ_J", 0) or 0),
                "wr_6": float(row.get("wr.WR_6", 0) or 0),
                "wr_10": float(row.get("wr.WR_10", 0) or 0),
                "cci_14": float(row.get("other.CCI_14", 0) or 0),
                "adx": float(row.get("dmi.ADX", 0) or 0),
                "bias_6": float(row.get("bias.BIAS_6", 0) or 0),
                "psv": float(row.get("other.PSY", 0) or 0),
                "ar": float(row.get("other.AR", 0) or 0),
                "br": float(row.get("other.BR", 0) or 0),
                "obv": float(row.get("other.OBV", 0) or 0),
                "vr": float(row.get("other.VR", 0) or 0),
                "trix": float(row.get("other.TRIX", 0) or 0),
                "sar": float(row.get("dmi.SAR", 0) or 0),
            }
        except Exception:
            continue
    return results

# ── 分析 westock 信号 ─────────────────────────────────────
def analyze_westock_signals(code, indicators):
    """分析 westock 指标，返回信号列表"""
    signals = []
    kdj_j = indicators.get("kdj_j", 0)
    wr_6 = indicators.get("wr_6", 0)
    cci = indicators.get("cci_14", 0)
    bias_6 = indicators.get("bias_6", 0)
    adx = indicators.get("adx", 0)
    psy = indicators.get("psv", 0)
    vr = indicators.get("vr", 0)

    if kdj_j < 0:
        signals.append(f"KDJ J={kdj_j:.0f} 超卖")
    elif kdj_j < 20:
        signals.append(f"KDJ J={kdj_j:.0f} 低位")

    if wr_6 > 90:
        signals.append(f"WR(6)={wr_6:.0f} 极度超卖")
    elif wr_6 > 80:
        signals.append(f"WR(6)={wr_6:.0f} 超卖")

    if cci < -200:
        signals.append(f"CCI={cci:.0f} 极度超卖")
    elif cci < -100:
        signals.append(f"CCI={cci:.0f} 超卖")

    if bias_6 < -5:
        signals.append(f"BIAS(6)={bias_6:.1f}% 乖离大")

    if adx > 25:
        signals.append(f"ADX={adx:.0f} 趋势强")

    if psy < 30:
        signals.append(f"PSY={psy:.0f} 悲观")
    elif psy > 70:
        signals.append(f"PSY={psy:.0f} 乐观")

    if vr < 50:
        signals.append(f"VR={vr:.0f} 低迷")
    elif vr > 150:
        signals.append(f"VR={vr:.0f} 活跃")

    return signals

# ── 推荐池路径 ────────────────────────────────────────────
POOL_DB = os.path.expanduser("~/.hermes/skills/stock/stock-expert/recommendation_pool.db")
RECOMMEND_TRACK_DIR = os.path.expanduser("~/.hermes/cron/output")
TRACK_JSON = os.path.join(RECOMMEND_TRACK_DIR, "opportunity_track_latest.json")

# ── 发飞书消息 ────────────────────────────────────────────
def send_feishu(text):
    if not FEISHU_TOKEN:
        print(text)
        return
    url = "https://open.feishu.cn/open-apis/bot/v2/hook/" + FEISHU_TOKEN
    payload = {"msg_type": "text", "content": {"text": text}}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"飞书推送失败: {e}\n{text}")

# ── 推荐池追踪 ────────────────────────────────────────────
def track_to_pool(alerts, source="intraday_scan"):
    """
    将盘中推荐记录到推荐池数据库
    """
    if not alerts:
        print("无推荐需要追踪")
        return

    import sqlite3
    from datetime import date, datetime

    os.makedirs(RECOMMEND_TRACK_DIR, exist_ok=True)
    conn = sqlite3.connect(POOL_DB)
    cur = conn.cursor()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    today = date.today().isoformat()

    tracked = 0
    for a in alerts:
        code = a["code"]
        name = a["name"]
        price = a["price"]
        rsi = a.get("rsi", 50)
        confidence = a.get("confidence", 0)
        score = a.get("score", 0)

        # 根据 RSI 决定档位和类型
        if rsi < 30:
            tier = "激进档"
            tier_type = "超跌反弹"
            stop_loss_pct = 0.07
            tp1_pct = 0.10
            tp2_pct = 0.15
            hold_days = 10
        elif rsi < 40:
            tier = "稳健档"
            tier_type = "低位关注"
            stop_loss_pct = 0.05
            tp1_pct = 0.08
            tp2_pct = 0.12
            hold_days = 15
        else:
            tier = "关注档"
            tier_type = "技术信号"
            stop_loss_pct = 0.05
            tp1_pct = 0.08
            tp2_pct = 0.12
            hold_days = 10

        max_pos = 5.0  # 默认5%仓位

        # 检查是否已存在（相同代码+当天+来源）
        cur.execute("""
            SELECT id FROM recommendations
            WHERE code = ? AND entry_date = ? AND tier = ? AND notes LIKE ?
        """, (code, today, tier, f"%source={source}%"))
        existing = cur.fetchone()

        note_prefix = f"source={source}"
        if existing:
            # 更新
            cur.execute("""
                UPDATE recommendations SET
                    entry_price = ?, current_price = ?,
                    stop_loss = ?, take_profit_1 = ?, take_profit_2 = ?,
                    hold_days_max = ?, max_position_pct = ?, updated_at = ?,
                    notes = ?
                WHERE id = ?
            """, (
                price, price,
                price * (1 - stop_loss_pct),
                price * (1 + tp1_pct),
                price * (1 + tp2_pct),
                hold_days, max_pos, now_str,
                f"{note_prefix} score={score} rsi={rsi:.0f} confidence={confidence}",
                existing[0]
            ))
        else:
            # 插入
            cur.execute("""
                INSERT INTO recommendations
                (code, name, tier, tier_type, entry_price, entry_date,
                 stop_loss, take_profit_1, take_profit_2, hold_days_max,
                 max_position_pct, current_price, status, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                code, name, tier, tier_type,
                price, today,
                price * (1 - stop_loss_pct),
                price * (1 + tp1_pct),
                price * (1 + tp2_pct),
                hold_days, max_pos,
                price, 'active',
                f"{note_prefix} score={score} rsi={rsi:.0f} confidence={confidence}",
                now_str, now_str
            ))
            tracked += 1

    conn.commit()
    conn.close()
    print(f"推荐池追踪: 新增 {tracked} 条记录")

    # 保存 JSON 供后续分析
    track_data = []
    for a in alerts:
        track_data.append({
            "code": a["code"],
            "name": a["name"],
            "price": a["price"],
            "rsi": a.get("rsi", 0),
            "score": a.get("score", 0),
            "confidence": a.get("confidence", 0),
            "time": now_str,
        })
    with open(TRACK_JSON, "w") as f:
        json.dump({"alerts": track_data, "generated_at": now_str}, f, ensure_ascii=False, indent=2)

# ── 主逻辑 ────────────────────────────────────────────────
if __name__ == "__main__":
    candidates = get_candidates()
    if not candidates:
        sys.exit(0)

    # 读持仓
    holdings = get_holdings()

    codes = [c[0] for c in candidates]

    # 新浪实时行情（替换缓存中的昨日收盘价）
    sina_quotes = get_sina_realtime(codes)

    # 基本面过滤（批量查询，排除垃圾股）
    fin_filters = get_financial_filters(codes)
    rejected = [c for c in codes if fin_filters.get(c, {}).get("reject", False)]
    rejected_names = []
    if rejected:
        for c in candidates:
            f = fin_filters.get(c[0], {})
            if f.get("reject"):
                rejected_names.append(f"{c[1]}({c[0]}):{f['reject_reason']}")

    # 合并数据，筛选有效股票
    pre_alerts = []
    for code, name, signal_score, rsi, cached_price, cached_chg, ma_bullish, ma20 in candidates:
        # 基本面过滤
        fin = fin_filters.get(code, {})
        if fin.get("reject", False):
            continue
        sq_key = f"sz{code}" if code.startswith(("0","3")) else f"sh{code}"
        q = sina_quotes.get(sq_key, {})
        # 优先用实时价，兜底缓存价
        price = q.get("price", cached_price or 0)
        change_pct = q.get("change_pct", cached_chg or 0)
        if price > 0:
            # 趋势标记
            trend_tag = ""
            if ma_bullish == 1:
                trend_tag = "上升趋势"
            elif ma_bullish == 0:
                trend_tag = "震荡"
            pre_alerts.append({
                "code": code, "name": name, "score": signal_score,
                "price": price, "change_pct": change_pct, "rsi": rsi,
                "warnings": fin.get("warnings", []),
                "trend": trend_tag,
                # P1-3：实时价缺失标记（新浪API不可用时静默兜底昨日收盘价）
                "stale_price": not bool(q),
            })

    if not pre_alerts:
        lines = ["【盘中推荐 · 无信号】"]
        if rejected:
            lines.append("")
            lines.append(f"⛔ 基本面过滤排除 {len(rejected)} 只：")
            for r in rejected_names[:5]:
                lines.append(f"  - {r}")
        send_feishu("\n".join(lines))
        sys.exit(0)

    # westock 技术指标交叉验证（前5只）
    top_codes = [a["code"] for a in pre_alerts[:5]]
    westock_map = fetch_westock_technical(top_codes)

    # 合并信号，计算置信度
    alerts = []
    for a in pre_alerts:
        code = a["code"]
        westock_signals = []
        if code in westock_map:
            westock_signals = analyze_westock_signals(code, westock_map[code])

        confidence = 0
        if a["rsi"] < 30:
            confidence += 30
        elif a["rsi"] < 40:
            confidence += 15
        confidence += len(westock_signals) * 10

        a["westock_signals"] = westock_signals
        a["confidence"] = confidence
        alerts.append(a)

    # 双轨分组：持仓内 / 新候选
    holding_alerts = []
    new_alerts = []
    for a in alerts:
        if a["code"] in holdings:
            holding_alerts.append(a)
        else:
            new_alerts.append(a)

    # 发飞书
    lines = [f"【盘中推荐 · {datetime.now().strftime('%H:%M')}】"]
    if holding_alerts:
        lines.append("=== 持仓内信号 ===")
        for a in sorted(holding_alerts, key=lambda x: x["confidence"], reverse=True)[:8]:
            h = holdings[a["code"]]
            buy_price = h.get('buy_price', 0)
            price = a["price"]
            pnl_pct = ((price - buy_price) / buy_price * 100) if buy_price > 0 else 0
            stop_loss_pct = 7 if a["rsi"] < 30 else 5
            stop_dist = ((price * (1 - stop_loss_pct/100) - price) / price * 100)
            rsi_flag = "⚠️" if a["rsi"] < 30 else "📉"
            w_signals = a.get("westock_signals", [])
            w_text = f" | {'、'.join(w_signals[:2])}" if w_signals else ""
            warnings = a.get("warnings", [])
            warn_text = f" | ⚠️{' '.join(warnings[:2])}" if warnings else ""
            trend = a.get("trend", "")
            trend_text = f" | 📈{trend}" if trend else ""
            stale_text = " ⚠️实时价缺失" if a.get("stale_price") else ""
            lines.append(
                f"{rsi_flag} {a['name']}({a['code']}) "
                f"浮盈{pnl_pct:+.1f}% | 距止损{stop_dist:+.1f}% "
                f"RSI={a['rsi']:.0f}{w_text}{warn_text}{trend_text}{stale_text}"
            )

    if new_alerts:
        if holding_alerts:
            lines.append("")
        lines.append("=== 新候选 ===")
        for a in sorted(new_alerts, key=lambda x: x["confidence"], reverse=True)[:5]:
            rsi_flag = "⚠️" if a["rsi"] < 30 else "📉"
            w_signals = a.get("westock_signals", [])
            w_text = f" | {'、'.join(w_signals[:2])}" if w_signals else ""
            warnings = a.get("warnings", [])
            w_text += f" | ⚠️{' '.join(warnings[:2])}" if warnings else ""
            trend = a.get("trend", "")
            trend_text = f" | 📈{trend}" if trend else ""
            stale_text = " ⚠️实时价缺失" if a.get("stale_price") else ""
            lines.append(
                f"{rsi_flag} {a['name']}({a['code']}) "
                f"评分{a['score']:.0f} | 现价{a['price']:.2f}({a['change_pct']:+.2f}%) "
                f"RSI={a['rsi']:.0f}{w_text}{trend_text}{stale_text}"
            )

    if rejected:
        lines.append("")
        lines.append(f"⛔ 基本面过滤排除 {len(rejected)} 只（仅展示前5）：")
        for r in rejected_names[:5]:
            lines.append(f"  - {r}")

    send_feishu("\n".join(lines))

    # 自动追踪到推荐池（带 source 标记）
    track_to_pool(alerts, source="intraday_scan")

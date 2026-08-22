#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Primary Feishu Delivery Wiring（Phase 8-G0.2）

只做两件事：
1. 从 Daily Decision Contract 生成 Primary Feishu Message（只读，不重算 Decision）
2. 调用既有 Feishu 发送基础设施，并记录 Delivery Registry

禁止：
- 重新计算 Decision
- 修改 Decision
- 修改 DecisionEngine
- 调用任何交易/券商接口
"""
from __future__ import annotations

import json
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from decision.contract import BUY, ADD, HOLD, REDUCE, SELL, NO_TRADE
from decision.user_authority import (
    record_delivery,
    is_duplicate_delivery,
    gen_delivery_id,
    message_hash,
    PENDING,
    SENT,
    FAILED,
    RETRYING,
    DAILY,
)
from decision.daily_decision_contract import build_daily_report

# Feishu 股票主群（与现有 feishu_sender.py 一致）
FEISHU_CHAT_ID = "oc_88d1817efbb9f328f4376314ab7c8b05"
# feishu_sender.py 实际路径（项目级 skills，非 cron/decision 子目录）
FEISHU_SENDER_PATH = Path('/home/caojy/.hermes/skills/stock/stock-expert/skills/feishu-bitable/feishu_sender.py')


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _load_feishu_sender():
    """动态导入 feishu_sender，避免硬依赖。"""
    path = str(FEISHU_SENDER_PATH)
    if not os.path.exists(path):
        raise RuntimeError(f"feishu_sender.py 不存在: {path}")
    import importlib.util
    spec = importlib.util.spec_from_file_location("feishu_sender", path)
    if spec is None:
        raise RuntimeError(f"无法加载 feishu_sender spec: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_primary_feishu_message(report: dict) -> dict:
    """
    从 Daily Decision Report 生成 Primary Feishu Message。
    只读，不修改 report，不重算 Decision。
    """
    meta = report.get('meta', {})
    mkt = report.get('market', {})
    rp = report.get('real_portfolio', {})
    readiness = report.get('account_readiness', {})
    summary = report.get('decision_summary', {})
    actions = report.get('actions', {})

    lines = []
    lines.append(f"📊 Daily Decision | {meta.get('report_date')}")
    lines.append(f"生成时间: {meta.get('as_of_time')}")
    lines.append("")
    lines.append("### MARKET")
    lines.append(f"Regime: {mkt.get('regime_label') or 'UNKNOWN'} (score={mkt.get('regime_score') or 'UNKNOWN'})")
    lines.append(f"Position Scale: {mkt.get('position_scale') or 'UNKNOWN'}")
    lines.append("")
    lines.append("### REAL HOLDINGS")
    lines.append(f"Source: {rp.get('holdings_source') or rp.get('source') or 'UNKNOWN'} | Holdings Status: {rp.get('holdings_status') or 'UNKNOWN'} | Count: {rp.get('holdings_count') or 0}")
    lines.append(f"Data Quality: {rp.get('data_quality') or 'UNKNOWN'} | Freshness: {rp.get('freshness') or 'UNKNOWN'}")
    lines.append(f"Holdings Value: {rp.get('holdings_value')} | Exposure: {rp.get('exposure')}")
    lines.append(f"Risk Status: {rp.get('risk_status') or 'UNKNOWN'}")
    acct_status = readiness.get('status', 'UNKNOWN')
    lines.append(f"Account Status: {acct_status}")
    if acct_status == 'READY':
        lines.append(f"Cash: {rp.get('cash')} | Total Asset: {rp.get('total_asset')}")
    else:
        lines.append("Cash/Total Asset: NOT_CONFIRMED (manual confirmation required)")
    lines.append(f"Drawdown: {rp.get('drawdown')} ({rp.get('drawdown_status')})")
    if rp.get('peak_asset'):
        lines.append(f"Peak Asset: {rp.get('peak_asset')} @ {rp.get('peak_asset_date')}")
    lines.append("")
    lines.append("### DECISION SUMMARY")
    lines.append(f"BUY: {summary.get('buy_count')} | ADD: {summary.get('add_count')} | HOLD: {summary.get('hold_count')} | "
                 f"REDUCE: {summary.get('reduce_count')} | SELL: {summary.get('sell_count')} | NO_TRADE: {summary.get('no_trade_count')}")
    lines.append("")

    for action_key in ('BUY', 'ADD', 'HOLD', 'REDUCE', 'SELL', 'NO_TRADE'):
        items = actions.get(action_key, [])
        if not items:
            continue
        label = action_key.upper()
        lines.append(f"### {label}")
        for it in items:
            sym = it.get('symbol') or it.get('name') or 'N/A'
            name = it.get('name', '')
            if sym and name:
                lines.append(f"  {sym} {name}")
            else:
                lines.append(f"  {sym}")
            lines.append(f"    Action: {it.get('action')}")
            lines.append(f"    Reason: {', '.join(it.get('reason_codes', [])) or 'N/A'}")
            if it.get('explanation'):
                lines.append(f"    Explanation: {it.get('explanation')}")
            if it.get('decision_id'):
                lines.append(f"    Decision ID: {it.get('decision_id')}")
            if it.get('entry', {}).get('entry_signal'):
                lines.append(f"    Entry Signal: {it['entry'].get('entry_signal')}")
            if it.get('entry', {}).get('entry_price'):
                lines.append(f"    Entry Price: {it['entry'].get('entry_price')}")
            if it.get('sizing_status') and it.get('action') in (BUY, ADD, SELL, REDUCE):
                lines.append(f"    Sizing: {it.get('sizing_status')}")
                if it.get('target_value') is not None:
                    lines.append(f"    Target Value: {it.get('target_value'):,.0f}")
                if it.get('target_quantity'):
                    lines.append(f"    Target Qty: {it.get('target_quantity'):,}")
                if it.get('delta_value') is not None:
                    lines.append(f"    Delta Value: {it.get('delta_value'):,.0f}")
                if it.get('delta_quantity'):
                    lines.append(f"    Delta Qty: {it.get('delta_quantity')}")
            if it.get('risk', {}).get('stop_loss'):
                lines.append(f"    Stop Loss: {it['risk'].get('stop_loss')}")
            if it.get('risk', {}).get('take_profit'):
                lines.append(f"    Take Profit: {it['risk'].get('take_profit')}")
        lines.append("")

    if summary.get('trace'):
        lines.append("### TRACE")
        lines.append(", ".join(summary['trace']))

    text = "\n".join(lines)
    msg_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()

    return {
        'presentation': DAILY,
        'channel': FEISHU_CHAT_ID,
        'text': text,
        'content_hash': msg_hash,
        'report_date': meta.get('report_date'),
        'decision_summary': summary,
        'account_readiness_status': readiness.get('status'),
        'market_regime': mkt.get('regime_label'),
        'holdings_status': rp.get('holdings_status'),
        'account_status': readiness.get('status'),
        'risk_status': rp.get('risk_status'),
        'holdings_source': rp.get('holdings_source'),
        'holdings_count': rp.get('holdings_count'),
    }


def deliver_primary_feishu(report: dict, ua_dir: str | None = None) -> dict:
    """
    将 Daily Decision Report 作为 Primary Feishu Message 投递。
    返回 delivery record。
    不修改 report，不重算 Decision。
    """
    # 1. 构建 Primary Message
    primary = build_primary_feishu_message(report)

    decision_ids = [it.get('decision_id') for it in report.get('actions', {}).get('NO_TRADE', []) if it.get('decision_id')]
    for action_key in ('BUY', 'ADD', 'HOLD', 'REDUCE', 'SELL'):
        decision_ids += [it.get('decision_id') for it in report.get('actions', {}).get(action_key, []) if it.get('decision_id')]
    representative_decision_id = decision_ids[0] if decision_ids else f"daily_{report.get('meta', {}).get('report_date')}"

    # 2. 幂等检查
    if is_duplicate_delivery(representative_decision_id, primary['presentation'], primary['channel'], ua_dir):
        return {
            'delivery_status': 'DUPLICATE_SUPPRESSED',
            'delivery_id': None,
            'decision_id': representative_decision_id,
            'presentation': primary['presentation'],
            'channel': primary['channel'],
            'content_hash': primary.get('content_hash'),
            'error': 'duplicate suppressed',
            'source': 'PRIMARY_FEISHU',
        }

    # 3. 记录 PENDING
    pending_rec = record_delivery(
        decision_id=representative_decision_id,
        presentation=primary['presentation'],
        channel=primary['channel'],
        delivery_status=PENDING,
        ua_dir=ua_dir,
    )

    # 4. 发送
    try:
        feishu_mod = _load_feishu_sender()
        send_result = feishu_mod.send_text_message(primary['text'], receive_id=primary['channel'])
        send_ok = send_result.get('code') == 0 or send_result.get('ok') is True
    except Exception as e:
        send_ok = False
        send_result = {'error': str(e)}

    # 5. 更新状态（这里用新的 delivery record 体现最终状态）
    if send_ok:
        final_status = SENT
        error = ''
    else:
        final_status = FAILED
        error = str(send_result.get('error', send_result) if isinstance(send_result, dict) else send_result)

    final_rec = record_delivery(
        decision_id=representative_decision_id,
        presentation=primary['presentation'],
        channel=primary['channel'],
        delivery_status=final_status,
        retry_count=0 if final_status == SENT else 1,
        error=error,
        ua_dir=ua_dir,
    )

    final_rec['content_hash'] = primary.get('content_hash')
    final_rec['source'] = 'PRIMARY_FEISHU'
    final_rec['application_level_send'] = send_ok
    final_rec['server_readback'] = 'UNAVAILABLE'
    return final_rec


def deliver_primary_feishu_with_retry(report: dict, max_retries: int = 1, ua_dir: str | None = None) -> dict:
    """
    带一次重试的 Primary Delivery。
    retry 只重发同一 Primary Message，不重算 Decision。
    """
    result = deliver_primary_feishu(report, ua_dir=ua_dir)
    retries = 0
    primary = None
    while result.get('delivery_status') == FAILED and retries < max_retries:
        retries += 1
        result = record_delivery(
            decision_id=result['decision_id'],
            presentation=result['presentation'],
            channel=result['channel'],
            delivery_status=RETRYING,
            retry_count=retries,
            error=result.get('error', ''),
            ua_dir=ua_dir,
        )
        try:
            primary = build_primary_feishu_message(report)
            feishu_mod = _load_feishu_sender()
            send_result = feishu_mod.send_text_message(primary['text'], receive_id=primary['channel'])
            send_ok = send_result.get('code') == 0 or send_result.get('ok') is True
        except Exception as e:
            send_ok = False
            send_result = {'error': str(e)}

        if send_ok:
            result = record_delivery(
                decision_id=result['decision_id'],
                presentation=result['presentation'],
                channel=result['channel'],
                delivery_status=SENT,
                retry_count=retries,
                error='',
                ua_dir=ua_dir,
            )
            if primary is not None:
                result['content_hash'] = primary.get('content_hash')
            result['source'] = 'PRIMARY_FEISHU'
            result['application_level_send'] = True
            result['server_readback'] = 'UNAVAILABLE'
        else:
            result = record_delivery(
                decision_id=result['decision_id'],
                presentation=result['presentation'],
                channel=result['channel'],
                delivery_status=FAILED,
                retry_count=retries,
                error=str(send_result.get('error', send_result) if isinstance(send_result, dict) else send_result),
                ua_dir=ua_dir,
            )
            if primary is not None:
                result['content_hash'] = primary.get('content_hash')
            result['source'] = 'PRIMARY_FEISHU'
            result['application_level_send'] = False
            result['server_readback'] = 'UNAVAILABLE'
    return result

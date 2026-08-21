#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified User-Facing Decision Authority & Lifecycle (Phase 8-F)
=============================================================
锁死原则：
- FINAL_DECISION_AUTHORITY = DecisionEngine
- 只有 DecisionEngine 能产生 Final Action (BUY/ADD/HOLD/REDUCE/SELL/NO_TRADE)
- Feishu 只能展示已经产生的 Decision，永远不是 Decision Owner / Execution Source
- 本模块只处理：action/presentation/lifecycle 分离、supersession、expiry、
  latest-effective-decision、message classification、conflict detection、
  Feishu delivery contract / idempotency、account visibility、routing。

本模块不改交易规则 / 不改 DecisionEngine / 不改 contract 决策语义。
只建立用户层的展示、生命周期元数据、投递契约。

存储：独立文件系统 registry（user_authority/ 目录），与不可变 snapshot 分离。
"""
from __future__ import annotations
import json, os, glob, hashlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .contract import BUY, ADD, HOLD, REDUCE, SELL, NO_TRADE, ACTIONS

# ═══ 唯一 Final Decision Authority ═══
FINAL_DECISION_AUTHORITY = 'DecisionEngine'

# ═══ Final Action（唯一枚举）═══
FINAL_ACTIONS = ACTIONS  # BUY/ADD/HOLD/REDUCE/SELL/NO_TRADE

# ═══ Presentation Context（描述用户在哪个界面/场景看到，不是 Action）═══
DAILY = 'DAILY'
URGENT = 'URGENT'
POSITION = 'POSITION'
SYSTEM = 'SYSTEM'
RESEARCH = 'RESEARCH'
INFORMATIONAL = 'INFORMATIONAL'
SYSTEM_HEALTH = 'SYSTEM_HEALTH'
DEBUG = 'DEBUG'
PRESENTATIONS = (DAILY, URGENT, POSITION, SYSTEM, RESEARCH, INFORMATIONAL, SYSTEM_HEALTH, DEBUG)

# ═══ Decision Lifecycle ═══
CREATED = 'CREATED'
ACTIVE = 'ACTIVE'
SUPERSEDED = 'SUPERSEDED'
EXPIRED = 'EXPIRED'
CANCELLED = 'CANCELLED'
EXECUTED = 'EXECUTED'
NOT_EXECUTED = 'NOT_EXECUTED'
CLOSED = 'CLOSED'
LIFECYCLE_STATES = (CREATED, ACTIVE, SUPERSEDED, EXPIRED, CANCELLED,
                    EXECUTED, NOT_EXECUTED, CLOSED)

# ═══ User Message Classification ═══
FINAL_DECISION = 'FINAL_DECISION'   # 已过 DecisionEngine，带 Final Action
URGENT_MSG = 'URGENT'               # 需立即关注（presentation=URGENT，非 Action）
SIGNAL = 'SIGNAL'                   # 机会/盘中信号，尚未形成 Final Decision
RESEARCH_MSG = 'RESEARCH'           # 研究类（Shadow/Opportunity/Strategy Research）
INFO = 'INFORMATIONAL'              # News/Sentiment/龙虎榜/市场状态
HEALTH = 'SYSTEM_HEALTH'            # Account/Observation/Data/Runtime Health
DEBUG_MSG = 'DEBUG'                 # 原始 stdout/traceback/SQL/技术日志

# ═══ Surface / Routing ═══
TODAY_PLAN = 'TODAY_PLAN'
NOW_URGENT = 'NOW_URGENT'
RESEARCH_SURFACE = 'RESEARCH_SIGNAL'
INFORMATION_SURFACE = 'INFORMATION'
HEALTH_SURFACE = 'SYSTEM_HEALTH'
DEBUG_SURFACE = 'DEBUG'
SURFACES = (TODAY_PLAN, NOW_URGENT, RESEARCH_SURFACE, INFORMATION_SURFACE,
            HEALTH_SURFACE, DEBUG_SURFACE)

# ═══ Feishu Delivery State ═══
PENDING = 'PENDING'
SENT = 'SENT'
FAILED = 'FAILED'
RETRYING = 'RETRYING'
DELIVERY_STATES = (PENDING, SENT, FAILED, RETRYING)

# ═══ Account Visibility ═══
PRIVATE = 'PRIVATE'
GROUP = 'GROUP'
TEAM = 'TEAM'
ACCOUNT_VISIBILITIES = (PRIVATE, GROUP, TEAM)

# 默认存储目录
UA_DIR = Path(__file__).resolve().parent / 'user_authority'
_LIFECYCLE_DIR = UA_DIR / 'lifecycle'
_DELIVERY_DIR = UA_DIR / 'deliveries'


# ─────────────────────────────────────────────────────────────────────────
# 时间工具（Asia/Shanghai 语义对齐：datetime 处理统一 UTC 存储，展示用本地）
# ─────────────────────────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _parse_ts(ts) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────
# Decision Lifecycle Registry
# ─────────────────────────────────────────────────────────────────────────
class DecisionLifecycle:
    """Decision 生命周期记录（独立于不可变 snapshot）。"""

    def __init__(self, *, decision_id='', symbol='', context='', action=NO_TRADE,
                 presentation=DAILY, lifecycle_state=CREATED, created_at='',
                 effective_from='', effective_until='',
                 supersedes_decision_id='', superseded_by_decision_id='',
                 position_id='', strategy='', version='', reason_codes=None,
                 authority=FINAL_DECISION_AUTHORITY):
        self.decision_id = decision_id
        self.symbol = symbol
        self.context = context
        self.action = action
        self.presentation = presentation
        self.lifecycle_state = lifecycle_state
        self.created_at = created_at or _now_iso()
        self.effective_from = effective_from or created_at
        self.effective_until = effective_until
        self.supersedes_decision_id = supersedes_decision_id
        self.superseded_by_decision_id = superseded_by_decision_id
        self.position_id = position_id
        self.strategy = strategy
        self.version = version
        self.reason_codes = list(reason_codes or [])
        self.authority = authority

    def to_dict(self) -> dict:
        return {
            'decision_id': self.decision_id,
            'symbol': self.symbol,
            'context': self.context,
            'action': self.action,
            'presentation': self.presentation,
            'lifecycle_state': self.lifecycle_state,
            'created_at': self.created_at,
            'effective_from': self.effective_from,
            'effective_until': self.effective_until,
            'supersedes_decision_id': self.supersedes_decision_id,
            'superseded_by_decision_id': self.superseded_by_decision_id,
            'position_id': self.position_id,
            'strategy': self.strategy,
            'version': self.version,
            'reason_codes': self.reason_codes,
            'authority': self.authority,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'DecisionLifecycle':
        return cls(
            decision_id=d.get('decision_id', ''),
            symbol=d.get('symbol', ''),
            context=d.get('context', ''),
            action=d.get('action', NO_TRADE),
            presentation=d.get('presentation', DAILY),
            lifecycle_state=d.get('lifecycle_state', CREATED),
            created_at=d.get('created_at', ''),
            effective_from=d.get('effective_from', ''),
            effective_until=d.get('effective_until', ''),
            supersedes_decision_id=d.get('supersedes_decision_id', ''),
            superseded_by_decision_id=d.get('superseded_by_decision_id', ''),
            position_id=d.get('position_id', ''),
            strategy=d.get('strategy', ''),
            version=d.get('version', ''),
            reason_codes=d.get('reason_codes', []),
            authority=d.get('authority', FINAL_DECISION_AUTHORITY),
        )


def _lc_path(decision_id: str):
    return _LIFECYCLE_DIR / f"{decision_id}.json"


def save_lifecycle(lc: DecisionLifecycle, ua_dir: str = None) -> str:
    dirp = Path(ua_dir or _LIFECYCLE_DIR)
    dirp.mkdir(parents=True, exist_ok=True)
    path = dirp / f"{lc.decision_id}.json"
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(lc.to_dict(), f, ensure_ascii=False, indent=2)
    return str(path)


def load_lifecycle(decision_id: str, ua_dir: str = None) -> DecisionLifecycle | None:
    dirp = Path(ua_dir or _LIFECYCLE_DIR)
    path = dirp / f"{decision_id}.json"
    if not path.exists():
        return None
    with open(path, encoding='utf-8') as f:
        return DecisionLifecycle.from_dict(json.load(f))


def list_lifecycles(ua_dir: str = None) -> list[DecisionLifecycle]:
    dirp = Path(ua_dir or _LIFECYCLE_DIR)
    if not dirp.is_dir():
        return []
    out = []
    for fp in sorted(glob.glob(str(dirp / '*.json'))):
        try:
            with open(fp, encoding='utf-8') as f:
                out.append(DecisionLifecycle.from_dict(json.load(f)))
        except Exception:
            continue
    return out


# ─────────────────────────────────────────────────────────────────────────
# 生命周期操作
# ─────────────────────────────────────────────────────────────────────────
def _key(symbol: str, position_id: str = '') -> str:
    """lifecycle 分组键：symbol + position_id（无持仓则仅 symbol）。"""
    if position_id:
        return f"{symbol}::{position_id}"
    return symbol


def register_decision(*, decision_id, symbol, action, context='', presentation=DAILY,
                      created_at='', effective_from='', effective_until='',
                      supersedes_decision_id='', position_id='', strategy='',
                      version='', reason_codes=None, ua_dir=None,
                      auto_supersede=True) -> DecisionLifecycle:
    """注册一个新 Decision 的生命周期。

    auto_supersede：若同 key 已存在 ACTIVE 且 effective window 重叠的旧 Decision，
    则把旧 Decision 标记为 SUPERSEDED，本 Decision 标记为 ACTIVE。
    不改交易规则，只建立 lifecycle metadata / supersession 关系。
    """
    created_at = created_at or _now_iso()
    effective_from = effective_from or created_at

    lc = DecisionLifecycle(
        decision_id=decision_id, symbol=symbol, context=context, action=action,
        presentation=presentation, lifecycle_state=ACTIVE,
        created_at=created_at, effective_from=effective_from,
        effective_until=effective_until,
        supersedes_decision_id=supersedes_decision_id,
        position_id=position_id, strategy=strategy, version=version,
        reason_codes=reason_codes,
    )

    if auto_supersede:
        key = _key(symbol, position_id)
        now = _parse_ts(created_at)
        for old in list_lifecycles(ua_dir):
            if old.lifecycle_state not in (ACTIVE, CREATED):
                continue
            if _key(old.symbol, old.position_id) != key:
                continue
            if old.decision_id == decision_id:
                continue
            # 仅当 old 在 effective window 内（或未设 until）才 supersede
            if _window_overlaps_or_open(old, now):
                old.lifecycle_state = SUPERSEDED
                old.superseded_by_decision_id = decision_id
                if not lc.supersedes_decision_id:
                    lc.supersedes_decision_id = old.decision_id
                save_lifecycle(old, ua_dir)

    save_lifecycle(lc, ua_dir)
    return lc


def _window_overlaps_or_open(lc: DecisionLifecycle, at: datetime | None) -> bool:
    if lc.lifecycle_state not in (ACTIVE, CREATED):
        return False
    eff_from = _parse_ts(lc.effective_from)
    eff_until = _parse_ts(lc.effective_until)
    if eff_from and at and at < eff_from:
        return False
    if eff_until and at and at > eff_until:
        return False
    return True


def set_state(decision_id: str, state: str, ua_dir: str = None) -> DecisionLifecycle | None:
    lc = load_lifecycle(decision_id, ua_dir)
    if not lc:
        return None
    if state not in LIFECYCLE_STATES:
        raise ValueError(f"未知 lifecycle state: {state}")
    lc.lifecycle_state = state
    save_lifecycle(lc, ua_dir)
    return lc


def supersede(decision_id: str, superseded_by: str, ua_dir: str = None):
    lc = load_lifecycle(decision_id, ua_dir)
    if lc:
        lc.lifecycle_state = SUPERSEDED
        lc.superseded_by_decision_id = superseded_by
        save_lifecycle(lc, ua_dir)
    return lc


def expire(decision_id: str, ua_dir: str = None):
    return set_state(decision_id, EXPIRED, ua_dir)


def cancel(decision_id: str, ua_dir: str = None):
    return set_state(decision_id, CANCELLED, ua_dir)


def mark_executed(decision_id: str, ua_dir: str = None):
    return set_state(decision_id, EXECUTED, ua_dir)


def mark_not_executed(decision_id: str, ua_dir: str = None):
    return set_state(decision_id, NOT_EXECUTED, ua_dir)


def mark_closed(decision_id: str, ua_dir: str = None):
    return set_state(decision_id, CLOSED, ua_dir)


# ─────────────────────────────────────────────────────────────────────────
# Latest Effective Decision
# ─────────────────────────────────────────────────────────────────────────
def current_effective_decision(symbol: str, position_id: str = '', at: str = '',
                               ua_dir: str = None) -> DecisionLifecycle | None:
    """返回指定 symbol (+position_id) 的当前有效 Decision。

    规则：
    1. DecisionEngine-backed（本 registry 默认 authority=DecisionEngine）
    2. lifecycle_state == ACTIVE
    3. 当前时间落在 effective window
    4. effective_from 最新
    """
    at_dt = _parse_ts(at or _now_iso())
    key = _key(symbol, position_id)
    cands = []
    for lc in list_lifecycles(ua_dir):
        if _key(lc.symbol, lc.position_id) != key:
            continue
        if lc.lifecycle_state != ACTIVE:
            continue
        if not _window_overlaps_or_open(lc, at_dt):
            continue
        cands.append(lc)
    if not cands:
        return None
    cands.sort(key=lambda x: _parse_ts(x.effective_from) or datetime.min,
               reverse=True)
    return cands[0]


def effective_decisions_for_symbol(symbol: str, position_id: str = '',
                                   at: str = '', ua_dir: str = None) -> list[DecisionLifecycle]:
    """给定 symbol 的所有 Decision（按 effective_from 升序），标记 lifecycle。"""
    at_dt = _parse_ts(at or _now_iso())
    key = _key(symbol, position_id)
    out = []
    for lc in list_lifecycles(ua_dir):
        if _key(lc.symbol, lc.position_id) != key:
            continue
        out.append(lc)
    out.sort(key=lambda x: _parse_ts(x.effective_from) or datetime.min)
    return out


# ─────────────────────────────────────────────────────────────────────────
# Message Classification
# ─────────────────────────────────────────────────────────────────────────
def classify_message(*, is_final_decision=False, from_authority='',
                     action='', presentation='', has_decision_id=False,
                     lifecycle_state='', category='') -> str:
    """把一条用户消息分类为 Message Class。

    优先级：
    - Final Decision（已过 DecisionEngine + 带 Final Action + decision_id）
    - URGENT（presentation=URGENT）
    - SIGNAL（机会/盘中信号，未形成 Final Decision）
    - RESEARCH / INFORMATIONAL / SYSTEM_HEALTH / DEBUG
    """
    if is_final_decision and from_authority == FINAL_DECISION_AUTHORITY \
       and has_decision_id and action in FINAL_ACTIONS:
        if presentation == URGENT:
            return URGENT_MSG
        return FINAL_DECISION
    if presentation == URGENT:
        return URGENT_MSG
    if presentation == SYSTEM_HEALTH:
        return HEALTH
    if category in ('research', 'shadow', 'strategy_research'):
        return RESEARCH_MSG
    if category in ('news', 'sentiment', 'lhb', 'market_state', 'info'):
        return INFO
    if category == 'debug' or presentation == DEBUG:
        return DEBUG_MSG
    return SIGNAL


# ─────────────────────────────────────────────────────────────────────────
# Conflict Detection
# ─────────────────────────────────────────────────────────────────────────
def detect_conflicts(decisions: list[DecisionLifecycle], ua_dir: str = None) -> dict:
    """检测真正的 USER_DECISION_CONFLICT。

    条件（同时满足）：
    1. 两个用户可见消息都声称是 Final Decision
    2. 都来自 DecisionEngine
    3. 同一 symbol + position/lifecycle
    4. effective window 存在重叠
    5. Action 不一致

    Research/Signal 与 Final 的差异只记 SIGNAL_FINAL_DIFFERENCE，不误报为冲突。
    """
    conflicts = []
    diffs = []
    by_key = {}
    for d in decisions:
        by_key.setdefault(_key(d.symbol, d.position_id), []).append(d)
    for key, group in by_key.items():
        group = [g for g in group if g.lifecycle_state == ACTIVE]
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if a.decision_id == b.decision_id:
                    continue
                if a.action == b.action:
                    continue
                if a.authority != FINAL_DECISION_AUTHORITY or \
                   b.authority != FINAL_DECISION_AUTHORITY:
                    continue
                if not _window_overlap(a, b):
                    continue
                conflicts.append({
                    'type': 'USER_DECISION_CONFLICT',
                    'key': key,
                    'decision_a': a.decision_id,
                    'action_a': a.action,
                    'decision_b': b.decision_id,
                    'action_b': b.action,
                    'reason': '两个 Final Decision 同窗口同标的 Action 不一致',
                })
    return {'conflicts': conflicts, 'signal_final_differences': diffs}


def _window_overlap(a: DecisionLifecycle, b: DecisionLifecycle) -> bool:
    a_from = _parse_ts(a.effective_from)
    a_until = _parse_ts(a.effective_until)
    b_from = _parse_ts(b.effective_from)
    b_until = _parse_ts(b.effective_until)
    a_end = a_until or datetime.max.replace(tzinfo=timezone.utc)
    b_end = b_until or datetime.max.replace(tzinfo=timezone.utc)
    a_start = a_from or datetime.min.replace(tzinfo=timezone.utc)
    b_start = b_from or datetime.min.replace(tzinfo=timezone.utc)
    return not (a_end < b_start or b_end < a_start)


# ─────────────────────────────────────────────────────────────────────────
# Feishu Delivery Contract / Idempotency
# ─────────────────────────────────────────────────────────────────────────
def gen_delivery_id():
    return f"del_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"


def message_hash(decision_id: str, presentation: str, channel: str) -> str:
    raw = f"{decision_id}|{presentation}|{channel}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _delivery_path(delivery_id: str, ua_dir: str = None):
    return Path(ua_dir or _DELIVERY_DIR) / f"{delivery_id}.json"


def record_delivery(*, decision_id, presentation, channel, send_time='',
                    delivery_status=SENT, retry_count=0, error='',
                    ua_dir: str = None) -> dict:
    """记录一次 Feishu Delivery。返回 delivery record（含 message_hash）。"""
    send_time = send_time or _now_iso()
    delivery_id = gen_delivery_id()
    mh = message_hash(decision_id, presentation, channel)
    rec = {
        'delivery_id': delivery_id,
        'decision_id': decision_id,
        'presentation': presentation,
        'channel': channel,
        'message_hash': mh,
        'send_time': send_time,
        'delivery_status': delivery_status,
        'retry_count': retry_count,
        'error': error,
    }
    dirp = Path(ua_dir or _DELIVERY_DIR)
    dirp.mkdir(parents=True, exist_ok=True)
    with open(dirp / f"{delivery_id}.json", 'w', encoding='utf-8') as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    return rec


def find_delivery(decision_id, presentation, channel, ua_dir: str = None):
    """按 decision_id+presentation+channel 找已发送的 delivery（幂等去重用）。"""
    dirp = Path(ua_dir or _DELIVERY_DIR)
    mh = message_hash(decision_id, presentation, channel)
    if not dirp.is_dir():
        return None
    for fp in glob.glob(str(dirp / '*.json')):
        try:
            with open(fp, encoding='utf-8') as f:
                r = json.load(f)
            if r.get('message_hash') == mh:
                return r
        except Exception:
            continue
    return None


def is_duplicate_delivery(decision_id, presentation, channel, ua_dir: str = None) -> bool:
    """同一 decision_id+presentation+channel 是否已发送（幂等）。"""
    return find_delivery(decision_id, presentation, channel, ua_dir) is not None


# ─────────────────────────────────────────────────────────────────────────
# Account Visibility
# ─────────────────────────────────────────────────────────────────────────
class AccountVisibilityPolicy:
    """决定在 Feishu 群展示多少账户信息。"""

    def __init__(self, visibility=GROUP, group_has_outsiders=True):
        self.visibility = visibility
        self.group_has_outsiders = group_has_outsiders

    def effective(self) -> str:
        # 若群内存在非本人用户，即使配置 PRIVATE 也按 GROUP 对待（不泄露金额）
        if self.visibility == PRIVATE and self.group_has_outsiders:
            return GROUP
        return self.visibility

    def show_amounts(self) -> bool:
        eff = self.effective()
        return eff in (PRIVATE, TEAM)  # GROUP 不显示完整金额

    def render_account(self, account: dict) -> dict:
        """按可见性渲染账户信息。完整金额只在 PRIVATE/TEAM 显示。"""
        show_amt = self.show_amounts()
        out = {
            'status': account.get('status'),
            'freshness': account.get('freshness'),
            'readiness': account.get('readiness') or account.get('status'),
        }
        if show_amt:
            out['total_asset'] = account.get('total_asset')
            out['cash'] = account.get('cash')
        else:
            out['total_asset'] = None
            out['cash'] = None
            out['_amount_hidden'] = 'GROUP visibility: 金额不展示'
        if account.get('drawdown') is not None:
            out['drawdown'] = account.get('drawdown')
        return out


# ─────────────────────────────────────────────────────────────────────────
# User Decision View / Routing
# ─────────────────────────────────────────────────────────────────────────
def route_message(cls: str) -> str:
    """Message Class → Surface。"""
    mapping = {
        FINAL_DECISION: TODAY_PLAN,
        URGENT_MSG: NOW_URGENT,
        SIGNAL: RESEARCH_SURFACE,
        RESEARCH_MSG: RESEARCH_SURFACE,
        INFO: INFORMATION_SURFACE,
        HEALTH: HEALTH_SURFACE,
        DEBUG_MSG: DEBUG_SURFACE,
    }
    return mapping.get(cls, DEBUG_SURFACE)


def build_user_view(*, today_plan: dict = None, urgent: list = None,
                    research: list = None, information: list = None,
                    system_health: dict = None, debug: list = None) -> dict:
    """组装用户层统一视图（TODAY_PLAN / NOW / RESEARCH / INFO / HEALTH / DEBUG）。"""
    return {
        'surfaces': {
            TODAY_PLAN: today_plan or {},
            NOW_URGENT: urgent or [],
            RESEARCH_SURFACE: research or [],
            INFORMATION_SURFACE: information or [],
            HEALTH_SURFACE: system_health or {},
            DEBUG_SURFACE: debug or [],
        },
        'note': '统一用户决策视图 — 只有 DecisionEngine 产生 Final Action',
    }


if __name__ == '__main__':
    # 快速自测
    import tempfile
    d = tempfile.mkdtemp()
    a = register_decision(decision_id='D001', symbol='600540', action=HOLD,
                          presentation=DAILY, created_at='2026-08-21T09:00:00+00:00',
                          ua_dir=d)
    b = register_decision(decision_id='D002', symbol='600540', action=SELL,
                          presentation=URGENT, created_at='2026-08-21T10:15:00+00:00',
                          ua_dir=d)
    print('D001 state:', load_lifecycle('D001', d).lifecycle_state,
          'superseded_by:', load_lifecycle('D001', d).superseded_by_decision_id)
    print('D002 state:', load_lifecycle('D002', d).lifecycle_state)
    cur = current_effective_decision('600540', at='2026-08-21T11:00:00+00:00', ua_dir=d)
    print('current effective:', cur.decision_id, cur.action)
    print('classify:', classify_message(is_final_decision=True, from_authority='DecisionEngine',
                                        action='SELL', presentation='URGENT',
                                        has_decision_id=True))

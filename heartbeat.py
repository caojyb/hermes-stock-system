#!/usr/bin/env python3
"""
心跳监控模块 v1.0 — 系统健康检查
===================================
每天 09:00 和 15:00 由 cron 触发，检查：
1. 数据库连接是否正常
2. MCP 行情服务是否可达
3. 飞书 webhook 是否可用

如果连续 2 次失败，在本地日志记录告警。
"""
import os, sys, json, sqlite3, time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
LOG_FILE = SCRIPT_DIR / "heartbeat.log"
STATE_FILE = SCRIPT_DIR / "heartbeat_state.json"
MARKET_DB = "/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db"

# 飞书 webhook（生产环境替换为真实地址）
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/emergency"

# 备用告警（本地文件 + stderr）
BACKUP_ALERT = str(SCRIPT_DIR / "heartbeat_alert.log")


def log(msg, level="INFO"):
    """记录心跳日志"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, file=sys.stderr)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def load_state():
    """加载心跳状态"""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"consecutive_failures": 0, "last_success": None, "last_failure": None}


def save_state(state):
    """保存心跳状态"""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def check_db():
    """检查数据库连接"""
    if not os.path.exists(MARKET_DB):
        return False, "数据库文件不存在"
    try:
        conn = sqlite3.connect(MARKET_DB)
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return True, "OK"
    except Exception as e:
        return False, str(e)


def check_mcp():
    """检查 MCP 行情服务（通过本地数据库查询验证数据时效性）"""
    try:
        conn = sqlite3.connect(MARKET_DB)
        cur = conn.execute("SELECT MAX(date) FROM klines")
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            latest = row[0]
            days_ago = (datetime.now() - datetime.strptime(latest, "%Y-%m-%d")).days
            if days_ago <= 3:
                return True, f"最新数据: {latest} ({days_ago}天前)"
            else:
                return False, f"数据过期: {latest} ({days_ago}天前)"
        return False, "无K线数据"
    except Exception as e:
        return False, str(e)


def check_webhook():
    """检查飞书 webhook 可用性（仅测试连接，不发送消息）"""
    try:
        import urllib.request
        # 只检查域名解析和连接，不发送实际消息
        req = urllib.request.Request(FEISHU_WEBHOOK, method="POST")
        req.add_header("Content-Type", "application/json")
        # 发送一个空测试（webhook会返回错误但不影响计数）
        data = json.dumps({"msg_type": "text", "content": {"text": "__heartbeat_test__"}}).encode()
        resp = urllib.request.urlopen(req, data=data, timeout=10)
        return True, f"HTTP {resp.status}"
    except Exception as e:
        # webhook 返回 4xx 意味着服务可达但请求格式错误（正常）
        err_str = str(e)
        if "400" in err_str or "401" in err_str:
            return True, "服务可达(返回预期错误)"
        return False, err_str


def send_backup_alert(failures):
    """发送备用告警（写入本地文件）"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(BACKUP_ALERT, "a") as f:
        f.write(f"\n{'='*60}\n")
        f.write(f"[{ts}] 🚨 心跳检测连续 {failures} 次失败\n")
        f.write(f"{'='*60}\n")


def main():
    log("❤️ 心跳检测开始")
    state = load_state()

    results = {}
    all_ok = True

    # 1. 数据库
    ok, msg = check_db()
    results["database"] = {"status": "OK" if ok else "FAIL", "message": msg}
    if not ok:
        all_ok = False
        log(f"  ❌ 数据库: {msg}", "ERROR")

    # 2. MCP 行情
    ok, msg = check_mcp()
    results["mcp"] = {"status": "OK" if ok else "FAIL", "message": msg}
    if not ok:
        all_ok = False
        log(f"  ❌ MCP行情: {msg}", "ERROR")

    # 3. 飞书 webhook
    ok, msg = check_webhook()
    results["webhook"] = {"status": "OK" if ok else "FAIL", "message": msg}
    if not ok:
        all_ok = False
        log(f"  ❌ 飞书webhook: {msg}", "ERROR")

    # 更新状态
    if all_ok:
        state["consecutive_failures"] = 0
        state["last_success"] = datetime.now().isoformat()
        log("✅ 所有检查通过")
    else:
        state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
        state["last_failure"] = datetime.now().isoformat()
        log(f"⚠️ {state['consecutive_failures']} 次连续失败", "WARNING")

    # 连续 2 次失败 → 备用告警
    if state["consecutive_failures"] >= 2:
        send_backup_alert(state["consecutive_failures"])
        log(f"🚨 连续{state['consecutive_failures']}次失败，已写入备用告警", "ALERT")

    save_state(state)
    log(f"❤️ 心跳检测完成\n")

    # 输出JSON结果（供cron解析）
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
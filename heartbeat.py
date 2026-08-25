#!/usr/bin/env python3
"""
心跳监控模块 v3.0 — 系统健康检查
===================================
每天 09:00 和 15:00 由 cron 触发，检查：
1. 数据库连接是否正常
2. K线数据时效性（替代MCP行情，更直接）
3. Hindsight HTTP /health 状态
4. 飞书 webhook TCP 连通性（不发送真实消息）

连续 3 次失败 → 写入本地告警文件 + 输出到 stderr 供 cron 捕获推送。
"""
import os, sys, json, sqlite3, socket, time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
LOG_FILE = SCRIPT_DIR / "heartbeat.log"
STATE_FILE = SCRIPT_DIR / "heartbeat_state.json"
MARKET_DB = "/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db"

# 飞书 webhook（仅用于 TCP 连通性测试，不发送消息）
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/emergency"

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


def check_kline_freshness():
    """检查K线数据时效性（替代原来的MCP行情检查）"""
    try:
        if not os.path.exists(MARKET_DB):
            return False, "数据库不存在"
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


def check_hindsight():
    """检查 Hindsight HTTP /health"""
    try:
        sock = socket.create_connection(("127.0.0.1", 9177), timeout=5)
        sock.sendall(b"GET /health HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
        resp = sock.recv(4096).decode(errors="replace")
        sock.close()
        if '"status":"healthy"' in resp or "200 OK" in resp:
            return True, "Hindsight /health reachable"
        return False, f"Hindsight unhealthy: {resp[:80]}"
    except Exception as e:
        return False, f"Hindsight unreachable: {e}"


def check_webhook():
    """检查飞书 webhook TCP 连通性（不发送真实消息）"""
    try:
        url = FEISHU_WEBHOOK.replace("https://", "").replace("http://", "").split("/")[0]
        host, port = url.split(":") if ":" in url else (url, 443)
        port = int(port)
        sock = socket.create_connection((host, port), timeout=10)
        sock.close()
        return True, f"TCP connect {host}:{port} OK"
    except Exception as e:
        return False, f"webhook TCP failed: {e}"


def send_backup_alert(failures):
    """连续失败时写入本地告警文件 + 输出到 stderr"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"\n{'='*60}\n[{ts}] 🚨 心跳检测连续 {failures} 次失败\n{'='*60}\n"
    with open(BACKUP_ALERT, "a") as f:
        f.write(msg)
    # 同时输出到 stderr，供 cron 捕获
    print(msg, file=sys.stderr)


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

    # 2. K线时效性（替代MCP行情）
    ok, msg = check_kline_freshness()
    results["kline"] = {"status": "OK" if ok else "FAIL", "message": msg}
    if not ok:
        all_ok = False
        log(f"  ❌ K线时效: {msg}", "ERROR")

    # 3. Hindsight
    ok, msg = check_hindsight()
    results["hindsight"] = {"status": "OK" if ok else "FAIL", "message": msg}
    if not ok:
        all_ok = False
        log(f"  ❌ Hindsight: {msg}", "ERROR")

    # 4. 飞书 webhook TCP
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

    # 连续 3 次失败 → 备用告警
    if state["consecutive_failures"] >= 3:
        send_backup_alert(state["consecutive_failures"])
        log(f"🚨 连续{state['consecutive_failures']}次失败，已写入备用告警", "ALERT")

    save_state(state)
    log(f"❤️ 心跳检测完成\n")

    # 输出 JSON 结果（供 cron 解析）
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()

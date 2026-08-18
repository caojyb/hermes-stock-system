#!/usr/bin/env python3
"""
Hermes 交易网关 v1.0 — 信号发送 + 成交回执
===========================================
架构：
  Linux (Hermes)  ←→  Windows VPS (QMT)
  信号生成          HTTP API        执行交易
  
工作流：
1. Hermes 生成买卖信号 → 写入本地信号队列 (signals/)
2. 网关定期将信号推送到 QMT 实例
3. QMT 执行交易 → 写入成交回执 → 网关拉取回执
4. Hermes 读取回执 → 更新持仓数据库

运行模式：
  --mode generate   : 从 auto_recommend 生成信号（每日15:00）
  --mode gateway    : 启动网关守护进程（持续运行）
  --mode status     : 查看信号队列状态
  --mode backfill   : 回填历史成交回执

依赖：
  Linux: 本机（Hermes 所在系统）
  Windows: QMT 客户端（需手动安装）
"""
import os, sys, json, time, sqlite3, threading, hashlib
from datetime import datetime, timedelta, date
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

SCRIPT_DIR = Path(__file__).parent.resolve()
SIGNALS_DIR = SCRIPT_DIR / "signals"
RECEIPTS_DIR = SCRIPT_DIR / "receipts"
CONFIG_FILE = SCRIPT_DIR / "gateway_config.json"

# 默认配置
DEFAULT_CONFIG = {
    "gateway": {
        "host": "0.0.0.0",
        "port": 9527,
        "api_key": os.environ.get('TRADE_GATEWAY_API_KEY', ''),
    },
    "trade_mode": "emquant",  # 交易模式: emquant / qmt / simulated
    "emquant": {
        "enabled": True,
        "module": "emquant_trader",
    },
    "qmt": {
        "host": "192.168.1.100",  # Windows VPS IP
        "port": 9528,
        "account": "",
        "max_retries": 3,
    },
    "limits": {
        "max_single_order": 50000,   # 单笔最大金额
        "max_daily_orders": 20,       # 每日最大下单次数
        "max_position_ratio": 0.70,   # 最大仓位比例
    },
    "signal_ttl": 3600,  # 信号有效期（秒）
}


def ensure_dirs():
    SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)


def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
            # 合并默认值
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
                elif isinstance(v, dict):
                    for k2, v2 in v.items():
                        if k2 not in cfg[k]:
                            cfg[k][k2] = v2
            return cfg
    return DEFAULT_CONFIG


def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"✅ 配置已保存: {CONFIG_FILE}")


# ══ 信号生成 ══

def generate_signal(code, direction, price, quantity, reason="", strategy="main_up"):
    """生成交易信号文件"""
    ensure_dirs()
    signal = {
        "id": hashlib.md5(f"{code}{datetime.now().isoformat()}".encode()).hexdigest()[:12],
        "code": code,
        "direction": direction,  # buy / sell
        "price": round(price, 2),
        "quantity": quantity,
        "amount": round(price * quantity, 2),
        "reason": reason,
        "strategy": strategy,
        "generated_at": datetime.now().isoformat(),
        "ttl": DEFAULT_CONFIG["signal_ttl"],
        "status": "pending",  # pending / sent / executed / expired / rejected
    }

    filename = f"{signal['id']}_{code}_{direction}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(SIGNALS_DIR / filename, "w") as f:
        json.dump(signal, f, ensure_ascii=False, indent=2)

    print(f"📤 信号已生成: {code} {direction} {quantity}股@{price:.2f} ({reason})")
    return signal


def generate_signals_from_recommendations():
    """从 auto_recommend 的推荐结果生成信号"""
    # 读取 auto_recommend 的输出（需要先运行）
    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR.parent / "auto_recommend.py"), "scan", "--json"],
            capture_output=True, text=True, timeout=60
        )
        output = result.stdout.strip()
        if not output:
            print("⚠️ auto_recommend 无输出")
            return []

        # 解析JSON输出
        data = json.loads(output)
        signals = []
        for rec in data.get("recommendations", []):
            code = rec.get("code")
            tier = rec.get("tier", "")
            price = rec.get("current_price", 0)
            if not code or not price:
                continue

            # 计算数量（每只股票约2.33%仓位）
            portfolio_value = 1000000  # 100万
            position_value = portfolio_value * 0.70 / 30  # 70%仓位 / 30只
            quantity = max(100, int(position_value / price / 100) * 100)

            signal = generate_signal(
                code=code,
                direction="buy",
                price=price,
                quantity=quantity,
                reason=f"{tier}推荐",
                strategy="main_up",
            )
            signals.append(signal)

        print(f"📊 生成 {len(signals)} 个信号")
        return signals

    except Exception as e:
        print(f"⚠️ 信号生成失败: {e}")
        return []


def get_pending_signals():
    """获取所有待处理信号"""
    ensure_dirs()
    signals = []
    for f in sorted(SIGNALS_DIR.glob("*.json")):
        try:
            with open(f) as fh:
                sig = json.load(fh)
            if sig.get("status") == "pending":
                signals.append(sig)
        except:
            pass
    return signals


def mark_signal(signal_id, status, detail=""):
    """更新信号状态"""
    ensure_dirs()
    for f in SIGNALS_DIR.glob(f"*{signal_id}*"):
        try:
            with open(f) as fh:
                sig = json.load(fh)
            sig["status"] = status
            sig["updated_at"] = datetime.now().isoformat()
            if detail:
                sig["detail"] = detail
            with open(f, "w") as fh:
                json.dump(sig, fh, ensure_ascii=False, indent=2)
        except:
            pass


# ══ HTTP API 服务（QMT 端调用） ══

class GatewayHandler(BaseHTTPRequestHandler):
    """HTTP API 服务"""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        path = parsed.path

        if path == "/ping":
            self._respond(200, {"status": "ok", "time": datetime.now().isoformat()})

        elif path == "/signals/pending":
            api_key = params.get("api_key", [""])[0]
            if api_key != self.server.config["gateway"]["api_key"]:
                self._respond(403, {"error": "unauthorized"})
                return
            signals = get_pending_signals()
            self._respond(200, {"count": len(signals), "signals": signals})

        elif path == "/status":
            pending = len(get_pending_signals())
            receipts = len(list(RECEIPTS_DIR.glob("*.json")))
            self._respond(200, {
                "pending_signals": pending,
                "total_receipts": receipts,
                "config": {k: v for k, v in self.server.config.items() if k != "gateway"},
            })

        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        data = json.loads(body) if body else {}

        if path == "/receipt":
            # QMT 提交成交回执
            receipt = data.get("receipt", {})
            signal_id = receipt.get("signal_id", "")
            status = receipt.get("status", "unknown")

            # 保存回执
            ensure_dirs()
            filename = f"receipt_{signal_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(RECEIPTS_DIR / filename, "w") as f:
                json.dump(receipt, f, ensure_ascii=False, indent=2)

            # 更新信号状态
            mark_signal(signal_id, status, detail=receipt.get("message", ""))

            self._respond(200, {"status": "ok", "receipt_id": filename})

        elif path == "/signal/mark":
            # 标记信号
            signal_id = data.get("signal_id", "")
            status = data.get("status", "")
            detail = data.get("detail", "")
            mark_signal(signal_id, status, detail)
            self._respond(200, {"status": "ok"})

        else:
            self._respond(404, {"error": "not found"})

    def _respond(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def log_message(self, format, *args):
        pass  # 静默日志


def start_gateway(config):
    """启动网关服务"""
    host = config["gateway"]["host"]
    port = config["gateway"]["port"]
    server = HTTPServer((host, port), GatewayHandler)
    server.config = config
    print(f"🌐 Hermes 交易网关已启动: http://{host}:{port}")
    print(f"  API Key: {config['gateway']['api_key']}")
    print(f"  QMT 地址: {config['qmt']['host']}:{config['qmt']['port']}")
    print(f"  信号队列: {SIGNALS_DIR}")
    print(f"  成交回执: {RECEIPTS_DIR}")
    print("  Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n⏹ 网关已停止")
        server.server_close()


def show_status():
    """显示信号队列状态"""
    ensure_dirs()
    pending = get_pending_signals()
    receipts = sorted(RECEIPTS_DIR.glob("*.json"))

    print("=" * 60)
    print("📊 Hermes 交易网关状态")
    print("=" * 60)
    print(f"\n📤 待处理信号: {len(pending)}")
    for s in pending[:10]:
        age = (datetime.now() - datetime.fromisoformat(s["generated_at"])).seconds
        print(f"  {s['id'][:8]} {s['code']:<8s} {s['direction']:<5s} "
              f"{s['quantity']:>5d}股@{s['price']:>8.2f} "
              f"({age}s前) {s.get('reason', '')[:20]}")

    print(f"\n📥 成交回执: {len(receipts)}")
    for r in receipts[-5:]:
        print(f"  {r.stem}")

    # 今日统计
    today = date.today().isoformat()
    today_signals = [s for s in SIGNALS_DIR.glob("*.json")
                     if today in s.stat().st_mtime.__str__()]
    print(f"\n  今日信号: {len(today_signals)}")
    print(f"  信号目录: {SIGNALS_DIR}")
    print(f"  回执目录: {RECEIPTS_DIR}")

    if not pending:
        print("\n  ✅ 无待处理信号，系统空闲")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Hermes 交易网关")
    parser.add_argument("--mode", choices=["generate", "gateway", "status", "backfill", "config"],
                        default="status", help="运行模式")
    parser.add_argument("--code", type=str, help="股票代码")
    parser.add_argument("--direction", choices=["buy", "sell"], default="buy")
    parser.add_argument("--price", type=float, help="价格")
    parser.add_argument("--quantity", type=int, default=100, help="数量")
    parser.add_argument("--reason", type=str, default="手动信号", help="原因")
    args = parser.parse_args()

    ensure_dirs()

    if args.mode == "config":
        # 交互式配置
        cfg = load_config()
        print(f"当前配置:\n{json.dumps(cfg, indent=2, ensure_ascii=False)}")
        print("\n按回车保持原值，输入新值覆盖")
        ip = input(f"QMT IP [{cfg['qmt']['host']}]: ").strip()
        if ip:
            cfg["qmt"]["host"] = ip
        port = input(f"QMT Port [{cfg['qmt']['port']}]: ").strip()
        if port:
            cfg["qmt"]["port"] = int(port)
        save_config(cfg)

    elif args.mode == "generate":
        if args.code and args.price:
            generate_signal(args.code, args.direction, args.price,
                          args.quantity, args.reason)
        else:
            generate_signals_from_recommendations()

    elif args.mode == "gateway":
        cfg = load_config()
        start_gateway(cfg)

    elif args.mode == "status":
        show_status()

    elif args.mode == "backfill":
        # 回填：将模拟成交记录转为回执
        exec_log = SCRIPT_DIR / "execution_log.json"
        if exec_log.exists():
            with open(exec_log) as f:
                data = json.load(f)
            records = data.get("records", [])
            for r in records[-100:]:
                receipt = {
                    "signal_id": f"backfill_{r['code']}_{r['fill_date']}",
                    "code": r["code"],
                    "direction": "buy",
                    "filled_price": r["fill_price"],
                    "filled_quantity": r["fill_quantity"],
                    "slippage": r["slippage_pct"],
                    "status": "executed",
                    "filled_at": r["fill_date"],
                    "message": r.get("reason", ""),
                    "is_backfill": True,
                }
                filename = f"receipt_backfill_{r['code']}_{r['fill_date']}.json"
                with open(RECEIPTS_DIR / filename, "w") as f:
                    json.dump(receipt, f, ensure_ascii=False, indent=2)
            print(f"✅ 回填 {min(100, len(records))} 条历史成交回执")
        else:
            print("⚠️ 无执行日志，请先运行 simulated_execution.py --collect")


if __name__ == "__main__":
    main()
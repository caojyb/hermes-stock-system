#!/bin/bash
# ============================================================
# market_cache.db + simulation.db 备份（P0-3）
# 每周日 03:00 执行（cron schedule 已改为 "0 3 * * 0"）
# 理由：日备冗余（最近数据靠 incremental 自愈），改周备保住难重建的完整历史+数据质量修复
# 写入 /mnt/hgfs/clawshare/hermesdata（宿主机共享盘）
# 保留策略：weekly 保留最近 3 份；snapshot 保留最近 3 份（有界，不无限增长）
# 用法: bash /home/caojy/.hermes/scripts/cron/db_backup.sh
# ============================================================
set -u

# 备份根目录（宿主机共享盘，本地磁盘紧张时释放空间）
BACKUP_ROOT="/mnt/hgfs/clawshare/hermesdata"
DAILY_DIR="${BACKUP_ROOT}/db/daily"
SNAPSHOT_DIR="${BACKUP_ROOT}/db/snapshot"
DATE_STR=$(date +%Y%m%d)
KEEP_DAILY=21          # 周备保留 3 周（21天）
KEEP_SNAPSHOT=3        # 快照保留份数

# 源数据库（权威路径）
MKT_DB="/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db"
SIM_DB="/home/caojy/.hermes/scripts/cron/simulation.db"

mkdir -p "$DAILY_DIR" "$SNAPSHOT_DIR"

backup_one() {
    local src="$1"
    local name="$2"
    local dest_dir="$3"
    if [ ! -f "$src" ]; then
        echo "[WARN] 源库不存在，跳过: $src"
        return 1
    fi
    local dest="${dest_dir}/${name}_${DATE_STR}.db"
    # sqlite3 .backup 走在线备份API，WAL 下安全（不锁业务）
    sqlite3 "$src" ".backup '$dest'"
    if [ $? -eq 0 ] && [ -s "$dest" ]; then
        echo "[OK] $name 备份完成: $(du -h "$dest" | cut -f1) ($dest)"
        return 0
    else
        echo "[ERROR] $name 备份失败: $dest"
        rm -f "$dest"
        return 1
    fi
}

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === 开始数据库备份 === (root: $BACKUP_ROOT)"
backup_one "$MKT_DB" "market_cache" "$DAILY_DIR"
backup_one "$SIM_DB" "simulation"   "$DAILY_DIR"

# 清理旧备份：daily 保留最近 KEEP_DAILY 天
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 清理 daily 超过 ${KEEP_DAILY} 天的旧备份..."
find "$DAILY_DIR" -name "market_cache_*.db" -mtime +"$KEEP_DAILY" -delete 2>/dev/null
find "$DAILY_DIR" -name "simulation_*.db"  -mtime +"$KEEP_DAILY" -delete 2>/dev/null

# 清理 snapshot：按文件数保留最近 KEEP_SNAPSHOT 份（按 mtime 排序，保留最新的）
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 清理 snapshot 超过 ${KEEP_SNAPSHOT} 份的旧快照..."
ls -1t "$SNAPSHOT_DIR"/market_cache_pre_*.db 2>/dev/null | tail -n +$((KEEP_SNAPSHOT+1)) | xargs -r rm -f
ls -1t "$SNAPSHOT_DIR"/simulation_pre_*.db   2>/dev/null | tail -n +$((KEEP_SNAPSHOT+1)) | xargs -r rm -f

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === 备份完成 ==="
echo "--- 当前备份目录 ---"
du -sh "$BACKUP_ROOT" 2>/dev/null
ls -lh "$DAILY_DIR" | tail -n +2
echo "(snapshot: $(ls "$SNAPSHOT_DIR" 2>/dev/null | wc -l) 份)"

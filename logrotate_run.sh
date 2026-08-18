#!/bin/bash
# 每日凌晨2点运行 logrotate
/usr/sbin/logrotate -s /home/caojy/.config/logrotate/status /home/caojy/.config/logrotate/hermes.conf 2>/dev/null
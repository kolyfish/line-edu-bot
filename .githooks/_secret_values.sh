#!/usr/bin/env bash
# 從本機 .env 抽出真實金鑰值（≥ 20 字元才算，避開 your_token_here 這類範本值）
# 決策: 比對「實際值」而非只靠 regex，原因: LINE secret 是 32 碼 hex，regex 容易漏也容易誤判
env_file="$(git rev-parse --show-toplevel)/.env"
[ -f "$env_file" ] || exit 0
grep -E '^[A-Z_]+=' "$env_file" | cut -d= -f2- | tr -d '"'"'"' \r' | awk 'length($0) >= 20'

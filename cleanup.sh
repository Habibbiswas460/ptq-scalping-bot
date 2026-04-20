#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# PTQ Scalping Bot - Cleanup Script
# Removes temporary files, cache, and other unnecessary files
# ═══════════════════════════════════════════════════════════════════════════════

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

echo ""
echo "═══════════════════════════════════════════════════"
echo "  PTQ Scalping Bot - Cleanup Utility"
echo "═══════════════════════════════════════════════════"
echo ""

# Track cleanup stats
pycache_count=0
pyc_count=0
log_backup_count=0
empty_dir_count=0

# 1. Remove __pycache__ directories
echo -e "${YELLOW}[1/5]${NC} Cleaning __pycache__ directories..."
while IFS= read -r -d '' dir; do
    rm -rf "$dir"
    ((pycache_count++))
done < <(find . -type d -name "__pycache__" -print0 2>/dev/null)
echo -e "      Removed: ${GREEN}$pycache_count${NC} __pycache__ directories"

# 2. Remove .pyc files (outside __pycache__)
echo -e "${YELLOW}[2/5]${NC} Cleaning .pyc files..."
while IFS= read -r -d '' file; do
    rm -f "$file"
    ((pyc_count++))
done < <(find . -type f -name "*.pyc" -not -path "./__pycache__/*" -print0 2>/dev/null)
echo -e "      Removed: ${GREEN}$pyc_count${NC} .pyc files"

# 3. Remove backup files
echo -e "${YELLOW}[3/5]${NC} Cleaning backup files..."
backup_count=0
for pattern in "*.bak" "*~" "*.swp" "*.swo" ".DS_Store"; do
    while IFS= read -r -d '' file; do
        rm -f "$file"
        ((backup_count++))
    done < <(find . -type f -name "$pattern" -print0 2>/dev/null)
done
echo -e "      Removed: ${GREEN}$backup_count${NC} backup files"

# 4. Clean old log files (optional - keep last 30 days)
echo -e "${YELLOW}[4/5]${NC} Checking old log files..."
old_log_dirs=$(find logs/ -maxdepth 1 -type d -name "2026-*" -mtime +30 2>/dev/null | wc -l)
echo -e "      Found: ${GREEN}$old_log_dirs${NC} log directories older than 30 days"
if [ "$old_log_dirs" -gt 0 ]; then
    echo -e "      ${YELLOW}Run with --clean-logs to remove old logs${NC}"
fi

# 5. Remove empty directories in logs
echo -e "${YELLOW}[5/5]${NC} Cleaning empty directories..."
while IFS= read -r -d '' dir; do
    rmdir "$dir" 2>/dev/null && ((empty_dir_count++))
done < <(find logs/ -type d -empty -print0 2>/dev/null)
echo -e "      Removed: ${GREEN}$empty_dir_count${NC} empty directories"

# Optional: Clean old logs
if [ "$1" == "--clean-logs" ]; then
    echo ""
    echo -e "${YELLOW}Cleaning log directories older than 30 days...${NC}"
    find logs/ -maxdepth 1 -type d -name "2026-*" -mtime +30 -exec rm -rf {} + 2>/dev/null
    echo -e "${GREEN}Done!${NC}"
fi

# Summary
echo ""
echo "═══════════════════════════════════════════════════"
echo -e "  ${GREEN}Cleanup Complete!${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Items cleaned:"
echo "    - $pycache_count __pycache__ directories"
echo "    - $pyc_count .pyc files"
echo "    - $backup_count backup files"
echo "    - $empty_dir_count empty directories"
echo ""
echo "  Options:"
echo "    --clean-logs  Remove log directories older than 30 days"
echo ""

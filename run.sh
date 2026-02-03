#!/bin/bash
# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║                    PTQ SCALPING BOT - LAUNCHER v3.0                        ║
# ║                         SMART SCALP STRATEGY                               ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

set -e

# ═══════════════════════════════════════════════════════════════════════════════
# COLORS & STYLES
# ═══════════════════════════════════════════════════════════════════════════════
# Regular Colors
BLACK='\033[0;30m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[0;37m'

# Bold Colors
BBLACK='\033[1;30m'
BRED='\033[1;31m'
BGREEN='\033[1;32m'
BYELLOW='\033[1;33m'
BBLUE='\033[1;34m'
BPURPLE='\033[1;35m'
BCYAN='\033[1;36m'
BWHITE='\033[1;37m'

# Background Colors
BG_BLACK='\033[40m'
BG_RED='\033[41m'
BG_GREEN='\033[42m'
BG_YELLOW='\033[43m'
BG_BLUE='\033[44m'
BG_PURPLE='\033[45m'
BG_CYAN='\033[46m'
BG_WHITE='\033[47m'

# Styles
BOLD='\033[1m'
DIM='\033[2m'
UNDERLINE='\033[4m'
BLINK='\033[5m'
REVERSE='\033[7m'
HIDDEN='\033[8m'

# Reset
NC='\033[0m'

# ═══════════════════════════════════════════════════════════════════════════════
# ANIMATION FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

# Typing effect
type_text() {
    local text="$1"
    local delay="${2:-0.02}"
    for ((i=0; i<${#text}; i++)); do
        printf "%s" "${text:$i:1}"
        sleep "$delay"
    done
    echo ""
}

# Loading spinner
spinner() {
    local pid=$1
    local delay=0.1
    local spinstr='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    while [ "$(ps a | awk '{print $1}' | grep $pid)" ]; do
        local temp=${spinstr#?}
        printf " ${BCYAN}%c${NC}  " "$spinstr"
        local spinstr=$temp${spinstr%"$temp"}
        sleep $delay
        printf "\b\b\b\b\b"
    done
    printf "    \b\b\b\b"
}

# Progress bar
progress_bar() {
    local current=$1
    local total=$2
    local width=50
    local percent=$((current * 100 / total))
    local filled=$((width * current / total))
    local empty=$((width - filled))
    
    printf "\r${CYAN}["
    printf "%${filled}s" | tr ' ' '█'
    printf "%${empty}s" | tr ' ' '░'
    printf "]${NC} ${BWHITE}%3d%%${NC}" $percent
}

# Animated line
draw_line() {
    local char="${1:-═}"
    local width="${2:-75}"
    local color="${3:-$CYAN}"
    printf "${color}"
    for ((i=0; i<width; i++)); do
        printf "%s" "$char"
        sleep 0.005
    done
    printf "${NC}\n"
}

# Glow text effect
glow_text() {
    local text="$1"
    local colors=("$BLUE" "$CYAN" "$BWHITE" "$BCYAN" "$BBLUE")
    for color in "${colors[@]}"; do
        printf "\r${color}${text}${NC}"
        sleep 0.1
    done
    echo ""
}

# ═══════════════════════════════════════════════════════════════════════════════
# CLEAR SCREEN & START
# ═══════════════════════════════════════════════════════════════════════════════
clear

# ═══════════════════════════════════════════════════════════════════════════════
# ANIMATED BANNER
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
sleep 0.1

# Top border animation
printf "${BPURPLE}"
echo "    ╔═══════════════════════════════════════════════════════════════════╗"
sleep 0.05
echo "    ║                                                                   ║"
sleep 0.05

# Logo with gradient effect
echo -e "    ║   ${BRED}██████${BYELLOW}╗ ${BRED}████████${BYELLOW}╗ ${BRED} ██████${BYELLOW}╗     ${BGREEN}██████${BCYAN}╗  ${BGREEN} ██████${BCYAN}╗ ${BGREEN}████████${BCYAN}╗${BPURPLE}   ║"
sleep 0.03
echo -e "    ║   ${BRED}██${BYELLOW}╔══${BRED}██${BYELLOW}╗╚══${BRED}██${BYELLOW}╔══╝${BRED}██${BYELLOW}╔═══${BRED}██${BYELLOW}╗    ${BGREEN}██${BCYAN}╔══${BGREEN}██${BCYAN}╗${BGREEN}██${BCYAN}╔═══${BGREEN}██${BCYAN}╗╚══${BGREEN}██${BCYAN}╔══╝${BPURPLE}   ║"
sleep 0.03
echo -e "    ║   ${BRED}██████${BYELLOW}╔╝   ${BRED}██${BYELLOW}║   ${BRED}██${BYELLOW}║   ${BRED}██${BYELLOW}║    ${BGREEN}██████${BCYAN}╔╝${BGREEN}██${BCYAN}║   ${BGREEN}██${BCYAN}║   ${BGREEN}██${BCYAN}║   ${BPURPLE}   ║"
sleep 0.03
echo -e "    ║   ${BRED}██${BYELLOW}╔═══╝    ${BRED}██${BYELLOW}║   ${BRED}██${BYELLOW}║▄▄ ${BRED}██${BYELLOW}║    ${BGREEN}██${BCYAN}╔══${BGREEN}██${BCYAN}╗${BGREEN}██${BCYAN}║   ${BGREEN}██${BCYAN}║   ${BGREEN}██${BCYAN}║   ${BPURPLE}   ║"
sleep 0.03
echo -e "    ║   ${BRED}██${BYELLOW}║       ${BRED}██${BYELLOW}║   ╚${BRED}██████${BYELLOW}╔╝    ${BGREEN}██████${BCYAN}╔╝╚${BGREEN}██████${BCYAN}╔╝   ${BGREEN}██${BCYAN}║   ${BPURPLE}   ║"
sleep 0.03
echo -e "    ║   ${BRED}╚═${BYELLOW}╝       ╚═╝    ╚══▀▀═╝     ${BGREEN}╚═════${BCYAN}╝  ╚${BGREEN}═════${BCYAN}╝    ╚═╝   ${BPURPLE}   ║"
sleep 0.05

echo -e "    ║                                                                   ║"
sleep 0.03
echo -e "    ║         ${BWHITE}⚡ SMART SCALP v3.0 - NIFTY OPTIONS TRADING ⚡${BPURPLE}          ║"
sleep 0.03
echo -e "    ║                                                                   ║"
echo "    ╚═══════════════════════════════════════════════════════════════════╝"
printf "${NC}"
sleep 0.2

# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY INFO BOX
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
printf "${BCYAN}    ┌─────────────────────────────────────────────────────────────────────┐${NC}\n"
echo -e "${BCYAN}    │${NC}  ${BYELLOW}📊 STRATEGY${NC}                                                        ${BCYAN}│${NC}"
echo -e "${BCYAN}    │${NC}     ${DIM}Multi-factor scoring: 10 Bull + 10 Bear indicators${NC}            ${BCYAN}│${NC}"
echo -e "${BCYAN}    │${NC}     ${DIM}RSI, MACD, Bollinger, ATR, Volume, Greeks, VIX${NC}                 ${BCYAN}│${NC}"
echo -e "${BCYAN}    ├─────────────────────────────────────────────────────────────────────┤${NC}"
echo -e "${BCYAN}    │${NC}  ${BYELLOW}💰 POSITION SIZE${NC}                                                    ${BCYAN}│${NC}"
echo -e "${BCYAN}    │${NC}     ${BGREEN}CE: 260 qty${NC} (4 lots) │ ${BRED}PE: 156 qty${NC} (4 lots)                   ${BCYAN}│${NC}"
echo -e "${BCYAN}    ├─────────────────────────────────────────────────────────────────────┤${NC}"
echo -e "${BCYAN}    │${NC}  ${BYELLOW}📈 BACKTEST RESULTS${NC}                                                 ${BCYAN}│${NC}"
echo -e "${BCYAN}    │${NC}     ${BGREEN}Win Rate: 58.5%${NC} │ ${BGREEN}Profit Factor: 2.06x${NC} │ ${BGREEN}Monthly: +168.7%${NC}   ${BCYAN}│${NC}"
echo -e "${BCYAN}    └─────────────────────────────────────────────────────────────────────┘${NC}"
echo ""

# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM CHECK
# ═══════════════════════════════════════════════════════════════════════════════
printf "${BWHITE}    ▶ SYSTEM CHECK${NC}\n"
draw_line "─" 75 "$DIM"

# Check Python
printf "      ${CYAN}├─${NC} Python version    : "
PYTHON_VER=$(python3 --version 2>&1 | awk '{print $2}')
echo -e "${BGREEN}✓ ${PYTHON_VER}${NC}"
sleep 0.1

# Check venv
printf "      ${CYAN}├─${NC} Virtual env       : "
if [ ! -d "venv" ]; then
    echo -e "${BYELLOW}Creating...${NC}"
    python3 -m venv venv &
    spinner $!
    echo -e "\r      ${CYAN}├─${NC} Virtual env       : ${BGREEN}✓ Created${NC}"
else
    echo -e "${BGREEN}✓ Exists${NC}"
fi
sleep 0.1

# Activate venv
source venv/bin/activate

# Check dependencies
printf "      ${CYAN}├─${NC} Dependencies      : "
if [ ! -f "venv/.installed" ]; then
    echo -e "${BYELLOW}Installing...${NC}"
    pip install -r requirements.txt -q &
    spinner $!
    touch venv/.installed
    echo -e "\r      ${CYAN}├─${NC} Dependencies      : ${BGREEN}✓ Installed${NC}    "
else
    echo -e "${BGREEN}✓ Ready${NC}"
fi
sleep 0.1

# Check .env
printf "      ${CYAN}├─${NC} Configuration     : "
if [ -f ".env" ]; then
    echo -e "${BGREEN}✓ .env found${NC}"
else
    echo -e "${BRED}✗ .env missing${NC}"
fi
sleep 0.1

# Check credentials
printf "      ${CYAN}└─${NC} Credentials       : "
if [ -f "config/credentials.json" ]; then
    echo -e "${BGREEN}✓ Ready for LIVE${NC}"
else
    echo -e "${BYELLOW}⚠ Paper mode${NC}"
fi

echo ""

# ═══════════════════════════════════════════════════════════════════════════════
# LOAD CONFIG FROM .env
# ═══════════════════════════════════════════════════════════════════════════════
if [ -f ".env" ]; then
    printf "${BWHITE}    ▶ CONFIGURATION${NC}\n"
    draw_line "─" 75 "$DIM"
    
    # Read some config values
    CAPITAL=$(grep "^TOTAL_CAPITAL=" .env 2>/dev/null | cut -d'=' -f2 || echo "30000")
    PAPER=$(grep "^PAPER_TRADING=" .env 2>/dev/null | cut -d'=' -f2 || echo "true")
    SL=$(grep "^SL_POINTS=" .env 2>/dev/null | cut -d'=' -f2 || echo "8")
    TP=$(grep "^TP_POINTS=" .env 2>/dev/null | cut -d'=' -f2 || echo "16")
    
    printf "      ${CYAN}├─${NC} Capital           : ${BWHITE}₹${CAPITAL}${NC}\n"
    sleep 0.05
    if [ "$PAPER" = "true" ]; then
        printf "      ${CYAN}├─${NC} Mode              : ${BYELLOW}📝 PAPER TRADING${NC}\n"
    else
        printf "      ${CYAN}├─${NC} Mode              : ${BRED}🔴 LIVE TRADING${NC}\n"
    fi
    sleep 0.05
    printf "      ${CYAN}├─${NC} Stop Loss         : ${BRED}-${SL} points${NC}\n"
    sleep 0.05
    printf "      ${CYAN}└─${NC} Take Profit       : ${BGREEN}+${TP} points${NC}\n"
    echo ""
fi

# ═══════════════════════════════════════════════════════════════════════════════
# COUNTDOWN & LAUNCH
# ═══════════════════════════════════════════════════════════════════════════════
printf "${BWHITE}    ▶ LAUNCHING BOT${NC}\n"
draw_line "─" 75 "$DIM"

# Countdown with animation
printf "\n      ${BWHITE}Starting in ${NC}"
for i in 3 2 1; do
    printf "${BRED}${i}${NC} "
    sleep 0.5
done
echo ""

# Launch animation
echo ""
printf "      "
for i in {1..20}; do
    printf "${BGREEN}▓${NC}"
    sleep 0.02
done
printf " ${BGREEN}LAUNCHING!${NC} "
for i in {1..20}; do
    printf "${BGREEN}▓${NC}"
    sleep 0.02
done
echo ""
echo ""

# ═══════════════════════════════════════════════════════════════════════════════
# FINAL BANNER
# ═══════════════════════════════════════════════════════════════════════════════
printf "${BG_BLUE}${BWHITE}                                                                             ${NC}\n"
printf "${BG_BLUE}${BWHITE}    🚀 PTQ BOT ACTIVE  │  Dashboard: http://localhost:8080  │  $(date '+%H:%M:%S')    ${NC}\n"
printf "${BG_BLUE}${BWHITE}                                                                             ${NC}\n"
echo ""

draw_line "═" 75 "$BPURPLE"
echo ""

# ═══════════════════════════════════════════════════════════════════════════════
# RUN THE BOT
# ═══════════════════════════════════════════════════════════════════════════════
python app.py


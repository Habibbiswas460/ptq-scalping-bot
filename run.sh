#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                    PTQ SCALPING BOT - CONTROL CENTER v5.0                    ║
# ║                        SMART SCALP v3.4 ENGINE                               ║
# ║                                                                              ║
# ║  MENU-ONLY LAUNCHER | ENTIRE PROJECT MANAGEMENT | ANIMATED UI               ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# ═══════════════════════════════════════════════════════════════════════════════
# COLORS & STYLES
# ═══════════════════════════════════════════════════════════════════════════════
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[0;37m'
BRED='\033[1;31m'
BGREEN='\033[1;32m'
BYELLOW='\033[1;33m'
BBLUE='\033[1;34m'
BPURPLE='\033[1;35m'
BCYAN='\033[1;36m'
BWHITE='\033[1;37m'
DIM='\033[2m'
BOLD='\033[1m'
BG_GREEN='\033[42m'
BG_RED='\033[41m'
BG_BLUE='\033[44m'
BG_PURPLE='\033[45m'
BG_CYAN='\033[46m'
NC='\033[0m'

# Gradient colors
G1='\033[38;5;196m'; G2='\033[38;5;202m'; G3='\033[38;5;208m'
G4='\033[38;5;214m'; G5='\033[38;5;220m'; G6='\033[38;5;226m'
G7='\033[38;5;118m'; G8='\033[38;5;46m';  G9='\033[38;5;51m'
G10='\033[38;5;21m'; G11='\033[38;5;93m'; G12='\033[38;5;201m'

# ═══════════════════════════════════════════════════════════════════════════════
# PROJECT DIRECTORY
# ═══════════════════════════════════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# ═══════════════════════════════════════════════════════════════════════════════
# HELPER: Read .env value safely
# ═══════════════════════════════════════════════════════════════════════════════
get_env() {
    local key="$1"
    local default="$2"
    local val
    val=$(grep "^${key}=" .env 2>/dev/null | head -1 | cut -d'=' -f2-)
    echo "${val:-$default}"
}

# ═══════════════════════════════════════════════════════════════════════════════
# ANIMATION FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════
type_slow() {
    local text="$1"
    local delay="${2:-0.02}"
    for ((i=0; i<${#text}; i++)); do
        printf "%s" "${text:$i:1}"
        sleep "$delay"
    done
}

draw_line() {
    local char="${1:-═}"
    local width="${2:-70}"
    local color="${3:-$CYAN}"
    printf "${color}"
    for ((i=0; i<width; i++)); do
        printf "%s" "$char"
    done
    printf "${NC}\n"
}

pulse_text() {
    local text="$1"
    local colors=("\033[2m" "\033[0;37m" "\033[1;37m" "\033[1;36m" "\033[1;37m" "\033[0;37m" "\033[2m")
    for color in "${colors[@]}"; do
        printf "\r    ${color}%s${NC}" "$text"
        sleep 0.07
    done
}

press_enter() {
    echo ""
    printf "    ${DIM}Press Enter to return...${NC}"
    read -r
}

get_market_status() {
    local hour=$(date +%H)
    local minute=$(date +%M)
    local day=$(date +%u)
    local current_mins=$((10#$hour * 60 + 10#$minute))
    if [ "$day" -ge 6 ]; then echo "WEEKEND"; return; fi
    if [ $current_mins -lt 555 ]; then echo "PRE_MARKET"
    elif [ $current_mins -lt 930 ]; then echo "OPEN"
    else echo "CLOSED"; fi
}

get_time_to_market() {
    local hour=$(date +%H) minute=$(date +%M)
    local current=$((10#$hour * 60 + 10#$minute)) open_time=555
    if [ $current -lt $open_time ]; then
        local diff=$((open_time - current)) h=$((diff / 60)) m=$((diff % 60))
        [ $h -gt 0 ] && echo "${h}h ${m}m" || echo "${m}m"
    else echo "0m"; fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# BOOT SEQUENCE
# ═══════════════════════════════════════════════════════════════════════════════
boot_sequence() {
    clear

    # Matrix rain intro
    printf "\033[?25l"
    for i in {1..6}; do
        local cols
        cols=$(tput cols 2>/dev/null || echo 80)
        for j in $(seq 1 $((cols/4))); do
            local pos=$((RANDOM % cols))
            local chars="01₹¥€"
            local char=${chars:$((RANDOM % 5)):1}
            printf "\033[${i};${pos}H${G8}${char}${NC}"
        done
        sleep 0.03
    done
    printf "\033[?25h"
    sleep 0.15
    clear
    echo ""

    # PTQ BOT ASCII Art banner
    printf "    ${G11}"
    type_slow "╔═══════════════════════════════════════════════════════════════════╗" 0.003
    printf "${NC}\n"

    echo -e "    ${G11}║${NC}                                                                   ${G11}║${NC}"

    printf "    ${G11}║${NC}   "
    printf "${G1}██████${G2}╗ ${G1}████████${G2}╗ ${G1} ██████${G2}╗     "
    printf "${G8}██████${G9}╗  ${G8} ██████${G9}╗ ${G8}████████${G9}╗"
    printf "   ${G11}║${NC}\n"
    sleep 0.02

    printf "    ${G11}║${NC}   "
    printf "${G2}██${G3}╔══${G2}██${G3}╗╚══${G2}██${G3}╔══╝${G2}██${G3}╔═══${G2}██${G3}╗    "
    printf "${G9}██${G8}╔══${G9}██${G8}╗${G9}██${G8}╔═══${G9}██${G8}╗╚══${G9}██${G8}╔══╝"
    printf "   ${G11}║${NC}\n"
    sleep 0.02

    printf "    ${G11}║${NC}   "
    printf "${G3}██████${G4}╔╝   ${G3}██${G4}║   ${G3}██${G4}║   ${G3}██${G4}║    "
    printf "${G8}██████${G7}╔╝${G8}██${G7}║   ${G8}██${G7}║   ${G8}██${G7}║   "
    printf "   ${G11}║${NC}\n"
    sleep 0.02

    printf "    ${G11}║${NC}   "
    printf "${G4}██${G5}╔═══╝    ${G4}██${G5}║   ${G4}██${G5}║▄▄ ${G4}██${G5}║    "
    printf "${G7}██${G8}╔══${G7}██${G8}╗${G7}██${G8}║   ${G7}██${G8}║   ${G7}██${G8}║   "
    printf "   ${G11}║${NC}\n"
    sleep 0.02

    printf "    ${G11}║${NC}   "
    printf "${G5}██${G6}║       ${G5}██${G6}║   ╚${G5}██████${G6}╔╝    "
    printf "${G8}██████${G9}╔╝╚${G8}██████${G9}╔╝   ${G8}██${G9}║   "
    printf "   ${G11}║${NC}\n"
    sleep 0.02

    printf "    ${G11}║${NC}   "
    printf "${G6}╚═${G5}╝       ╚═╝    ╚══▀▀═╝     "
    printf "${G9}╚═════${G8}╝  ╚${G9}═════${G8}╝    ╚═╝   "
    printf "   ${G11}║${NC}\n"

    echo -e "    ${G11}║${NC}                                                                   ${G11}║${NC}"

    # Subtitle pulse
    pulse_text "⚡ SMART SCALP v3.4 │ CONTROL CENTER v5.0 ⚡"
    printf "              ${G11}║${NC}"
    printf "\n"

    echo -e "    ${G11}║${NC}                                                                   ${G11}║${NC}"

    printf "    ${G11}"
    type_slow "╚═══════════════════════════════════════════════════════════════════╝" 0.003
    printf "${NC}\n"
    echo ""

    # Quick system check
    printf "    ${BWHITE}▶ SYSTEM CHECK${NC}\n"
    draw_line "─" 70 "$DIM"

    printf "      ${CYAN}├─${NC} Python         : "
    PYTHON_VER=$(python3 --version 2>&1 | awk '{print $2}')
    printf "${BGREEN}✓ ${PYTHON_VER}${NC}\n"

    printf "      ${CYAN}├─${NC} Virtual Env    : "
    if [ -d "venv" ]; then
        printf "${BGREEN}✓ Active${NC}\n"
    else
        printf "${BYELLOW}Creating...${NC}\n"
        python3 -m venv venv 2>/dev/null
        printf "\r      ${CYAN}├─${NC} Virtual Env    : ${BGREEN}✓ Created${NC}\n"
    fi

    source venv/bin/activate 2>/dev/null || true

    printf "      ${CYAN}├─${NC} Dependencies   : "
    if [ -f "venv/.installed" ]; then
        printf "${BGREEN}✓ Ready${NC}\n"
    else
        printf "${BYELLOW}Installing...${NC}"
        pip install -r requirements.txt -q 2>/dev/null
        touch venv/.installed
        printf "\r      ${CYAN}├─${NC} Dependencies   : ${BGREEN}✓ Installed${NC}    \n"
    fi

    printf "      ${CYAN}├─${NC} Configuration  : "
    if [ -f ".env" ]; then
        printf "${BGREEN}✓ .env loaded${NC}\n"
    else
        printf "${BRED}✗ .env missing!${NC}\n"
        printf "\n    ${BRED}Cannot start without .env file. Exiting.${NC}\n"
        exit 1
    fi

    printf "      ${CYAN}├─${NC} Core Files     : "
    if python3 -c "import ast; ast.parse(open('app.py').read()); ast.parse(open('core/main.py').read())" 2>/dev/null; then
        printf "${BGREEN}✓ Syntax OK${NC}\n"
    else
        printf "${BRED}✗ Syntax Error${NC}\n"
    fi

    printf "      ${CYAN}└─${NC} Market         : "
    MSTATUS=$(get_market_status)
    case $MSTATUS in
        "OPEN")       printf "${BGREEN}🟢 MARKET OPEN${NC}\n" ;;
        "PRE_MARKET") printf "${BYELLOW}🟡 PRE-MARKET (opens in $(get_time_to_market))${NC}\n" ;;
        "CLOSED")     printf "${BRED}🔴 CLOSED${NC}\n" ;;
        "WEEKEND")    printf "${BPURPLE}🌙 WEEKEND${NC}\n" ;;
    esac

    echo ""
    sleep 0.5
}

# ═══════════════════════════════════════════════════════════════════════════════
# ███  LEVEL 1: MAIN MENU  ███
# ═══════════════════════════════════════════════════════════════════════════════
show_main_menu() {
    clear
    echo ""
    printf "${BCYAN}"
    echo "    ╔══════════════════════════════════════════════════════════════════╗"
    printf "    ║     ${BWHITE}PTQ SCALPING BOT ─ CONTROL CENTER v5.0${BCYAN}                       ║\n"
    printf "    ║     ${DIM}SMART SCALP v3.4 │ $(date '+%Y-%m-%d %H:%M') │ Menu Mode${BCYAN}         ║\n"
    echo "    ╠══════════════════════════════════════════════════════════════════╣"
    echo "    ║                                                                  ║"
    printf "    ║   ${G8}[1]${BCYAN} 🚀 Start Trading        ${DIM}Paper or Live mode${BCYAN}                ║\n"
    printf "    ║   ${BYELLOW}[2]${BCYAN} 📊 Analytics & Reports  ${DIM}PnL, win rate, calendar${BCYAN}            ║\n"
    printf "    ║   ${BPURPLE}[3]${BCYAN} 📈 Backtest Engine      ${DIM}Historical strategy test${BCYAN}           ║\n"
    printf "    ║   ${G12}[4]${BCYAN} 🧪 Test Suite           ${DIM}75 unit tests + syntax${BCYAN}              ║\n"
    printf "    ║   ${BWHITE}[5]${BCYAN} ⚙️  Configuration        ${DIM}View & validate .env${BCYAN}              ║\n"
    printf "    ║   ${G7}[6]${BCYAN} 📋 Log Viewer           ${DIM}Browse daily trade logs${BCYAN}             ║\n"
    printf "    ║   ${G9}[7]${BCYAN} 🩺 System Health        ${DIM}Full diagnostic check${BCYAN}               ║\n"
    printf "    ║   ${G1}[8]${BCYAN} 🔧 Project Tools        ${DIM}Cleanup, structure, docs${BCYAN}            ║\n"
    printf "    ║   ${DIM}[0]${BCYAN} 🚪 Exit                                                  ║\n"
    echo "    ║                                                                  ║"
    echo "    ╚══════════════════════════════════════════════════════════════════╝"
    printf "${NC}\n"

    # Status bar
    PAPER=$(get_env "PAPER_TRADING" "true")
    CAPITAL=$(get_env "TOTAL_CAPITAL" "30000")
    KILL=$(get_env "KILL_SWITCH_LOSS" "3000")
    if [ "$PAPER" = "true" ]; then
        printf "    ${DIM}Mode: ${BYELLOW}📝 PAPER${NC}  ${DIM}│  Capital: ${BWHITE}₹${CAPITAL}${NC}  ${DIM}│  Kill: ${BRED}₹${KILL}${NC}  ${DIM}│  Market: "
    else
        printf "    ${DIM}Mode: ${BRED}💰 LIVE${NC}   ${DIM}│  Capital: ${BWHITE}₹${CAPITAL}${NC}  ${DIM}│  Kill: ${BRED}₹${KILL}${NC}  ${DIM}│  Market: "
    fi
    MSTATUS=$(get_market_status)
    case $MSTATUS in
        "OPEN")       printf "${BGREEN}🟢${NC}" ;;
        "PRE_MARKET") printf "${BYELLOW}🟡${NC}" ;;
        "CLOSED")     printf "${BRED}🔴${NC}" ;;
        "WEEKEND")    printf "${BPURPLE}🌙${NC}" ;;
    esac
    printf "${NC}\n\n"

    printf "    ${BWHITE}Select [0-8]: ${NC}"
    read -r choice

    case $choice in
        1) menu_trading ;;
        2) menu_analytics ;;
        3) menu_backtest ;;
        4) menu_tests ;;
        5) menu_config ;;
        6) menu_logs ;;
        7) menu_health ;;
        8) menu_tools ;;
        0)
            echo ""
            printf "    ${BGREEN}Goodbye! Happy Trading! 📈${NC}\n\n"
            exit 0
            ;;
        *)
            printf "    ${BRED}Invalid option${NC}\n"
            sleep 0.5
            show_main_menu
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════════════════
# ███  LEVEL 2: TRADING MENU  ███
# ═══════════════════════════════════════════════════════════════════════════════
menu_trading() {
    clear
    echo ""
    printf "    ${BCYAN}╔══════════════════════════════════════════════════════════╗${NC}\n"
    printf "    ${BCYAN}║${NC}  ${BWHITE}🚀 START TRADING${NC}                                        ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}╠══════════════════════════════════════════════════════════╣${NC}\n"
    printf "    ${BCYAN}║${NC}                                                          ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[1]${NC} 📝 Paper Trading  ${DIM}(Safe, simulated orders)${NC}       ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BRED}[2]${NC} 💰 Live Trading   ${DIM}(Real money, double confirm)${NC}  ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${DIM}[0]${NC} ← Back to Main Menu                               ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}                                                          ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}╚══════════════════════════════════════════════════════════╝${NC}\n"

    SL=$(get_env "SL_POINTS" "6")
    TP=$(get_env "TP_POINTS" "12")
    CE=$(get_env "CE_QUANTITY" "195")
    PE=$(get_env "PE_QUANTITY" "130")
    echo ""
    printf "    ${DIM}Current: SL=${BRED}-${SL}${NC} ${DIM}TP=${BGREEN}+${TP}${NC} ${DIM}CE:${CE} PE:${PE}${NC}\n\n"

    printf "    ${BWHITE}Select [0-2]: ${NC}"
    read -r tchoice

    case $tchoice in
        1)
            printf "\n    ${BGREEN}✓ Paper Trading Mode${NC}\n"
            sleep 0.5
            launch_bot "true"
            ;;
        2)
            printf "\n    ${BRED}⚠️  WARNING: Live Trading uses REAL MONEY!${NC}\n"
            printf "    ${BYELLOW}Type 'YES' to confirm: ${NC}"
            read -r confirm
            if [ "$confirm" = "YES" ]; then
                printf "    ${BRED}⚠️  Second check — Enter your Angel One Client ID: ${NC}"
                read -r confirm_id
                ACTUAL_ID=$(get_env "ANGEL_CLIENT_ID" "")
                if [ -n "$ACTUAL_ID" ] && [ "$confirm_id" = "$ACTUAL_ID" ]; then
                    printf "    ${BRED}💰 LIVE TRADING ACTIVATED${NC}\n"
                    sleep 1
                    launch_bot "false"
                else
                    printf "    ${BGREEN}✓ Wrong Client ID. Cancelled.${NC}\n"
                    sleep 2
                    menu_trading
                fi
            else
                printf "    ${BGREEN}✓ Cancelled. Back to menu.${NC}\n"
                sleep 1
                menu_trading
            fi
            ;;
        0) show_main_menu ;;
        *) printf "    ${BRED}Invalid${NC}\n"; sleep 0.5; menu_trading ;;
    esac
}

launch_bot() {
    local paper_mode="$1"
    export PAPER_TRADING="$paper_mode"
    export USE_LIVE_DATA=true

    clear
    echo ""

    # Countdown
    printf "    ${BWHITE}LAUNCHING IN: ${NC}"
    for i in 3 2 1; do
        case $i in
            3) COLOR="$BYELLOW" ;; 2) COLOR="$G1" ;; 1) COLOR="$BRED" ;;
        esac
        printf "\r    ${BWHITE}LAUNCHING IN: ${COLOR}█ ${i} █${NC}  "
        sleep 0.5
    done
    echo ""

    # Rocket animation
    printf "    "
    for step in "          🚀" "       🚀   " "    🚀      " " 🚀         "; do
        printf "\r    ${BCYAN}${step}${NC}"
        sleep 0.08
    done
    printf "\r    ${BRED}🔥${BYELLOW}🔥${BGREEN}🔥${NC} ${BWHITE}IGNITION!${NC} ${BGREEN}🔥${BYELLOW}🔥${BRED}🔥${NC}          "
    echo ""; echo ""

    if [ "$paper_mode" = "true" ]; then
        printf "${BG_GREEN}${BWHITE}    🚀 PTQ BOT LAUNCHED  │  PAPER MODE  │  $(date '+%H:%M:%S')                          ${NC}\n"
    else
        printf "${BG_RED}${BWHITE}    🚀 PTQ BOT LAUNCHED  │  LIVE MODE   │  $(date '+%H:%M:%S')                          ${NC}\n"
    fi
    echo ""
    draw_line "═" 70 "$BPURPLE"
    echo ""

    # Auto-restart loop
    RESTART_COUNT=0
    MAX_RESTARTS=5

    while [ $RESTART_COUNT -lt $MAX_RESTARTS ]; do
        python3 app.py
        EXIT_CODE=$?

        if [ $EXIT_CODE -eq 0 ]; then
            printf "\n    ${BGREEN}✓ Bot exited cleanly${NC}\n"
            break
        else
            RESTART_COUNT=$((RESTART_COUNT + 1))
            printf "\n    ${BYELLOW}⚠ Crashed (exit: $EXIT_CODE). Restart $RESTART_COUNT/$MAX_RESTARTS in 10s...${NC}\n"
            printf "    ${DIM}Ctrl+C to cancel${NC}\n"
            sleep 10
            if [ $RESTART_COUNT -ge $MAX_RESTARTS ]; then
                printf "\n    ${BRED}✗ Max restarts reached. Stopping.${NC}\n"
                break
            fi
            printf "    ${BCYAN}🔄 Restarting...${NC}\n\n"
        fi
    done

    echo ""
    draw_line "═" 70 "$BCYAN"
    printf "${BG_PURPLE}${BWHITE}    📊 SESSION COMPLETE  │  $(date '+%Y-%m-%d %H:%M:%S')                                ${NC}\n"
    draw_line "═" 70 "$BCYAN"
    press_enter
    show_main_menu
}

# ═══════════════════════════════════════════════════════════════════════════════
# ███  LEVEL 2: ANALYTICS MENU  ███
# ═══════════════════════════════════════════════════════════════════════════════
menu_analytics() {
    clear
    echo ""
    printf "    ${BCYAN}╔══════════════════════════════════════════════════════════╗${NC}\n"
    printf "    ${BCYAN}║${NC}  ${BWHITE}📊 ANALYTICS & REPORTS${NC}                                  ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}╠══════════════════════════════════════════════════════════╣${NC}\n"
    printf "    ${BCYAN}║${NC}                                                          ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[1]${NC} Today's Report       ${DIM}Current day summary${NC}         ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[2]${NC} Weekly Analysis      ${DIM}Last 7 days breakdown${NC}       ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[3]${NC} Monthly Analysis     ${DIM}Last 30 days breakdown${NC}      ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[4]${NC} Trading Calendar     ${DIM}Visual daily PnL grid${NC}       ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[5]${NC} Best & Worst Hours   ${DIM}Hourly performance${NC}          ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[6]${NC} Interactive Mode     ${DIM}Full analytics dashboard${NC}    ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${DIM}[0]${NC} ← Back                                             ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}                                                          ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}╚══════════════════════════════════════════════════════════╝${NC}\n"
    echo ""
    printf "    ${BWHITE}Select [0-6]: ${NC}"
    read -r achoice

    echo ""
    case $achoice in
        1) python3 -c "from utils.analytics import analyze_today; analyze_today()" ;;
        2) python3 utils/analytics.py --weekly ;;
        3) python3 utils/analytics.py --monthly ;;
        4) python3 -c "from utils.analytics import print_trading_calendar; print_trading_calendar(30)" ;;
        5) python3 -c "
from utils.analytics import get_best_worst_hours
h = get_best_worst_hours()
if h:
    print('\n📊 BEST HOURS:')
    for hr, s in h.get('best_hours', []):
        print(f'  {hr}:00 - {s[\"trades\"]} trades, Rs{s[\"pnl\"]:+,.2f}')
    print('\n📊 WORST HOURS:')
    for hr, s in h.get('worst_hours', []):
        print(f'  {hr}:00 - {s[\"trades\"]} trades, Rs{s[\"pnl\"]:+,.2f}')
else:
    print('  No hourly data available yet')
" 2>/dev/null || printf "    ${DIM}No hourly data available yet${NC}\n" ;;
        6) python3 utils/analytics.py --interactive ;;
        0) show_main_menu; return ;;
        *) printf "    ${BRED}Invalid${NC}\n" ;;
    esac
    press_enter
    menu_analytics
}

# ═══════════════════════════════════════════════════════════════════════════════
# ███  LEVEL 2: BACKTEST ENGINE (Full User Input)  ███
# ═══════════════════════════════════════════════════════════════════════════════
menu_backtest() {
    clear
    echo ""
    printf "    ${BCYAN}╔══════════════════════════════════════════════════════════╗${NC}\n"
    printf "    ${BCYAN}║${NC}  ${BWHITE}📈 BACKTEST ENGINE${NC}                                      ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}╠══════════════════════════════════════════════════════════╣${NC}\n"
    printf "    ${BCYAN}║${NC}                                                          ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[1]${NC} Quick Backtest     ${DIM}Pick a log, use defaults${NC}       ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[2]${NC} Custom Backtest    ${DIM}Full control, all params${NC}       ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[3]${NC} Browse Data Files  ${DIM}See available CSV/JSON${NC}        ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${DIM}[0]${NC} ← Back                                             ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}                                                          ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}╚══════════════════════════════════════════════════════════╝${NC}\n"
    echo ""
    printf "    ${BWHITE}Select [0-3]: ${NC}"
    read -r bchoice

    case $bchoice in
        1) run_quick_backtest ;;
        2) run_custom_backtest ;;
        3) browse_data_files ;;
        0) show_main_menu; return ;;
        *) printf "    ${BRED}Invalid${NC}\n"; sleep 0.5; menu_backtest ;;
    esac
}

run_quick_backtest() {
    echo ""
    printf "    ${BYELLOW}Available trade log CSVs:${NC}\n\n"

    CSV_FILES=()
    while IFS= read -r f; do
        CSV_FILES+=("$f")
    done < <(find logs/ -name "trades.csv" 2>/dev/null | sort -r)

    if [ ${#CSV_FILES[@]} -eq 0 ]; then
        printf "    ${DIM}No CSV data found in logs/${NC}\n"
        press_enter
        menu_backtest
        return
    fi

    for i in "${!CSV_FILES[@]}"; do
        local fdate
        fdate=$(echo "${CSV_FILES[$i]}" | grep -oP '\d{4}-\d{2}-\d{2}')
        local lines
        lines=$(wc -l < "${CSV_FILES[$i]}" 2>/dev/null || echo 0)
        printf "      ${BGREEN}[%2d]${NC} ${BWHITE}%-30s${NC} ${DIM}(%s rows)${NC}\n" $((i+1)) "${CSV_FILES[$i]}" "$lines"
    done

    echo ""
    printf "    ${BWHITE}Select file number (or 0 to cancel): ${NC}"
    read -r fnum

    if [ "$fnum" = "0" ]; then menu_backtest; return; fi
    if [[ ! "$fnum" =~ ^[0-9]+$ ]] || [ "$fnum" -lt 1 ] || [ "$fnum" -gt ${#CSV_FILES[@]} ]; then
        printf "    ${BRED}Invalid selection${NC}\n"
        sleep 1
        menu_backtest
        return
    fi

    local selected="${CSV_FILES[$((fnum-1))]}"
    echo ""
    printf "    ${BCYAN}📈 Running backtest on: ${BWHITE}${selected}${NC}\n"
    printf "    ${DIM}Using defaults: Capital=₹$(get_env TOTAL_CAPITAL 30000) SL=$(get_env SL_POINTS 6) TP=$(get_env TP_POINTS 12)${NC}\n\n"

    python3 core/backtest.py \
        --data "$selected" \
        --capital "$(get_env TOTAL_CAPITAL 30000)" \
        --sl "$(get_env SL_POINTS 6)" \
        --tp "$(get_env TP_POINTS 12)"

    press_enter
    menu_backtest
}

run_custom_backtest() {
    clear
    echo ""
    printf "    ${BCYAN}══════════════════════════════════════════════════════${NC}\n"
    printf "    ${BWHITE}📈 CUSTOM BACKTEST — Full Configuration${NC}\n"
    printf "    ${BCYAN}══════════════════════════════════════════════════════${NC}\n"
    echo ""

    # Step 1: Data file
    printf "    ${BYELLOW}Step 1: Data Source${NC}\n"
    printf "    ${DIM}Enter path to historical CSV data file${NC}\n"
    local csv_count
    csv_count=$(find logs/ -name '*.csv' 2>/dev/null | wc -l)
    printf "    ${DIM}Available: ${csv_count} CSV files in logs/${NC}\n"
    printf "    ${BWHITE}Data file path: ${NC}"
    read -r bt_data
    if [ -z "$bt_data" ]; then
        printf "    ${BRED}No file specified. Cancelled.${NC}\n"
        press_enter
        menu_backtest
        return
    fi
    if [ ! -f "$bt_data" ]; then
        printf "    ${BRED}File not found: $bt_data${NC}\n"
        press_enter
        menu_backtest
        return
    fi
    printf "    ${BGREEN}✓${NC} ${bt_data}\n\n"

    # Step 2: Capital
    printf "    ${BYELLOW}Step 2: Initial Capital${NC}\n"
    local def_capital
    def_capital=$(get_env "TOTAL_CAPITAL" "30000")
    printf "    ${BWHITE}Capital [₹${def_capital}]: ${NC}"
    read -r bt_capital
    bt_capital="${bt_capital:-$def_capital}"
    printf "    ${BGREEN}✓${NC} ₹${bt_capital}\n\n"

    # Step 3: Stop Loss
    printf "    ${BYELLOW}Step 3: Stop Loss Points${NC}\n"
    local def_sl
    def_sl=$(get_env "SL_POINTS" "6")
    printf "    ${BWHITE}SL points [${def_sl}]: ${NC}"
    read -r bt_sl
    bt_sl="${bt_sl:-$def_sl}"
    printf "    ${BGREEN}✓${NC} ${bt_sl} points\n\n"

    # Step 4: Take Profit
    printf "    ${BYELLOW}Step 4: Take Profit Points${NC}\n"
    local def_tp
    def_tp=$(get_env "TP_POINTS" "12")
    printf "    ${BWHITE}TP points [${def_tp}]: ${NC}"
    read -r bt_tp
    bt_tp="${bt_tp:-$def_tp}"
    printf "    ${BGREEN}✓${NC} ${bt_tp} points\n\n"

    # Step 5: Output directory
    printf "    ${BYELLOW}Step 5: Output Directory${NC}\n"
    printf "    ${BWHITE}Output dir [logs/backtest]: ${NC}"
    read -r bt_output
    bt_output="${bt_output:-logs/backtest}"
    printf "    ${BGREEN}✓${NC} ${bt_output}\n\n"

    # Summary
    draw_line "─" 55 "$BCYAN"
    printf "    ${BWHITE}BACKTEST CONFIGURATION SUMMARY:${NC}\n"
    draw_line "─" 55 "$BCYAN"
    printf "      Data File    : ${BWHITE}${bt_data}${NC}\n"
    printf "      Capital      : ${BWHITE}₹${bt_capital}${NC}\n"
    printf "      Stop Loss    : ${BRED}-${bt_sl} pts${NC}\n"
    printf "      Take Profit  : ${BGREEN}+${bt_tp} pts${NC}\n"
    local rr
    rr=$(echo "scale=1; $bt_tp / $bt_sl" | bc 2>/dev/null || echo "?")
    printf "      R:R Ratio    : ${BWHITE}1:${rr}${NC}\n"
    printf "      Output       : ${BWHITE}${bt_output}${NC}\n"
    draw_line "─" 55 "$BCYAN"
    echo ""

    printf "    ${BWHITE}Run backtest? [Y/n]: ${NC}"
    read -r bt_confirm
    bt_confirm="${bt_confirm:-Y}"

    if [[ "$bt_confirm" =~ ^[Yy]$ ]]; then
        echo ""
        printf "    ${BCYAN}📈 Starting backtest engine...${NC}\n\n"
        mkdir -p "$bt_output" 2>/dev/null

        python3 core/backtest.py \
            --data "$bt_data" \
            --capital "$bt_capital" \
            --sl "$bt_sl" \
            --tp "$bt_tp" \
            --output "$bt_output"

        echo ""
        printf "    ${BGREEN}✓ Backtest complete. Results saved to: ${bt_output}${NC}\n"
    else
        printf "    ${DIM}Cancelled.${NC}\n"
    fi

    press_enter
    menu_backtest
}

browse_data_files() {
    clear
    echo ""
    printf "    ${BWHITE}📁 AVAILABLE DATA FILES${NC}\n"
    draw_line "─" 60 "$BCYAN"
    echo ""

    printf "    ${BYELLOW}Log CSV Files:${NC}\n"
    local csv_count=0
    while IFS= read -r f; do
        local size lines
        size=$(wc -c < "$f" 2>/dev/null || echo "?")
        lines=$(wc -l < "$f" 2>/dev/null || echo "?")
        printf "      ${BGREEN}•${NC} %-35s ${DIM}%s bytes, %s rows${NC}\n" "$f" "$size" "$lines"
        csv_count=$((csv_count + 1))
    done < <(find logs/ -name "*.csv" 2>/dev/null | sort)

    if [ $csv_count -eq 0 ]; then
        printf "      ${DIM}No CSV files found${NC}\n"
    fi

    echo ""
    printf "    ${BYELLOW}Log JSON Files:${NC}\n"
    local json_count=0
    while IFS= read -r f; do
        local size
        size=$(wc -c < "$f" 2>/dev/null || echo "?")
        printf "      ${BGREEN}•${NC} %-35s ${DIM}%s bytes${NC}\n" "$f" "$size"
        json_count=$((json_count + 1))
    done < <(find logs/ -name "*.json" 2>/dev/null | sort)

    if [ $json_count -eq 0 ]; then
        printf "      ${DIM}No JSON files found${NC}\n"
    fi

    echo ""
    printf "    ${BYELLOW}Data Directory:${NC}\n"
    if [ -d "data" ]; then
        local data_count
        data_count=$(find data/ -type f 2>/dev/null | wc -l)
        if [ "$data_count" -eq 0 ]; then
            printf "      ${DIM}data/ is empty${NC}\n"
        else
            find data/ -type f 2>/dev/null | while IFS= read -r f; do
                printf "      ${BGREEN}•${NC} %s\n" "$f"
            done
        fi
    else
        printf "      ${DIM}No data/ directory${NC}\n"
    fi

    echo ""
    printf "    ${DIM}Total: ${csv_count} CSV + ${json_count} JSON files${NC}\n"
    press_enter
    menu_backtest
}

# ═══════════════════════════════════════════════════════════════════════════════
# ███  LEVEL 2: TEST SUITE  ███
# ═══════════════════════════════════════════════════════════════════════════════
menu_tests() {
    clear
    echo ""
    printf "    ${BCYAN}╔══════════════════════════════════════════════════════════╗${NC}\n"
    printf "    ${BCYAN}║${NC}  ${BWHITE}🧪 TEST SUITE${NC}                                            ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}╠══════════════════════════════════════════════════════════╣${NC}\n"
    printf "    ${BCYAN}║${NC}                                                          ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[1]${NC} Run ALL Tests        ${DIM}Full 75-test suite${NC}          ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[2]${NC} Greeks Calculation   ${DIM}test_greeks.py${NC}              ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[3]${NC} Greeks Caching       ${DIM}test_greeks_caching.py${NC}      ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[4]${NC} Market Data (Batch)  ${DIM}test_batch_market_data.py${NC}   ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[5]${NC} Kill Switch          ${DIM}test_kill_switch.py${NC}         ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[6]${NC} Phases 3-4-5         ${DIM}test_phases_3_4_5.py${NC}       ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[7]${NC} Analytics Module     ${DIM}test_analytics.py${NC}           ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[8]${NC} WebSocket            ${DIM}test_websocket.py${NC}           ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[9]${NC} Syntax Check Only    ${DIM}All critical .py files${NC}     ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${DIM}[0]${NC} ← Back                                             ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}                                                          ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}╚══════════════════════════════════════════════════════════╝${NC}\n"
    echo ""
    printf "    ${BWHITE}Select [0-9]: ${NC}"
    read -r tchoice

    echo ""
    case $tchoice in
        1) printf "    ${BCYAN}🧪 Running full test suite...${NC}\n\n"; python3 -m pytest tests/ -v ;;
        2) python3 -m pytest tests/test_greeks.py -v ;;
        3) python3 -m pytest tests/test_greeks_caching.py -v ;;
        4) python3 -m pytest tests/test_batch_market_data.py -v ;;
        5) python3 -m pytest tests/test_kill_switch.py -v ;;
        6) python3 -m pytest tests/test_phases_3_4_5.py -v ;;
        7) python3 -m pytest tests/test_analytics.py -v ;;
        8) python3 -m pytest tests/test_websocket.py -v ;;
        9) run_syntax_check ;;
        0) show_main_menu; return ;;
        *) printf "    ${BRED}Invalid${NC}\n" ;;
    esac
    press_enter
    menu_tests
}

run_syntax_check() {
    printf "    ${BYELLOW}Checking syntax of all project files...${NC}\n\n"
    local errors=0
    local total=0
    for f in app.py \
             core/main.py core/engines/entry_engine.py core/engines/exit_engine.py \
             core/engines/state_machine.py core/trading/broker.py core/trading/trade_manager.py \
             core/risk/kill_switch.py core/risk/risk_manager.py core/risk/greeks_calc.py \
             core/risk/session_trend.py core/risk/validators.py \
             core/services/database.py core/services/mode_switch.py \
             core/services/session_manager.py core/services/telegram_bot.py \
             strategies/smart_scalp_v3.py config/constants.py config/validator.py \
             utils/analytics.py utils/greeks.py utils/helpers.py utils/logger.py utils/monitoring.py \
             brokers/angel_one/client.py brokers/angel_one/exceptions.py; do
        total=$((total + 1))
        if [ -f "$f" ]; then
            if python3 -c "import ast; ast.parse(open('$f').read())" 2>/dev/null; then
                printf "      ${BGREEN}✓${NC} %s\n" "$f"
            else
                printf "      ${BRED}✗${NC} %s ${BRED}SYNTAX ERROR${NC}\n" "$f"
                errors=$((errors + 1))
            fi
        else
            printf "      ${BYELLOW}–${NC} %s ${DIM}(not found)${NC}\n" "$f"
        fi
    done
    echo ""
    if [ $errors -eq 0 ]; then
        printf "    ${BG_GREEN}${BWHITE}  ✓ All ${total} files passed syntax check  ${NC}\n"
    else
        printf "    ${BG_RED}${BWHITE}  ✗ ${errors}/${total} files have errors  ${NC}\n"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# ███  LEVEL 2: CONFIGURATION  ███
# ═══════════════════════════════════════════════════════════════════════════════
menu_config() {
    clear
    echo ""
    printf "    ${BCYAN}══════════════════════════════════════════════════════${NC}\n"
    printf "    ${BWHITE}⚙️  CONFIGURATION (SMART SCALP v3.4)${NC}\n"
    printf "    ${BCYAN}══════════════════════════════════════════════════════${NC}\n"
    echo ""

    # Trading Mode
    PAPER=$(get_env "PAPER_TRADING" "true")
    printf "    ${BYELLOW}Trading Mode:${NC}\n"
    if [ "$PAPER" = "true" ]; then
        printf "      Mode              : ${BYELLOW}📝 PAPER TRADING${NC}\n"
    else
        printf "      Mode              : ${BG_RED}${BWHITE} 💰 LIVE TRADING ${NC}\n"
    fi
    echo ""

    # Capital & Risk
    CAPITAL=$(get_env "TOTAL_CAPITAL" "30000")
    RISK=$(get_env "RISK_PER_TRADE_PCT" "2.0")
    KILL=$(get_env "KILL_SWITCH_LOSS" "3000")
    KILL_C=$(get_env "KILL_SWITCH_CONSEC_LOSS" "3")
    MAX_LOSS=$(get_env "MAX_DAILY_LOSS" "3000")
    printf "    ${BYELLOW}Capital & Risk:${NC}\n"
    printf "      Capital           : ${BWHITE}₹${CAPITAL}${NC}\n"
    printf "      Risk Per Trade    : ${BWHITE}${RISK}%%${NC}\n"
    printf "      Kill Switch       : ${BRED}₹${KILL}${NC} or ${BRED}${KILL_C} consec losses${NC}\n"
    printf "      Max Daily Loss    : ${BRED}₹${MAX_LOSS}${NC}\n"
    echo ""

    # SL/TP
    SL=$(get_env "SL_POINTS" "6")
    TP=$(get_env "TP_POINTS" "12")
    TSL=$(get_env "TSL_ENABLED" "true")
    printf "    ${BYELLOW}SL/TP & Exit:${NC}\n"
    printf "      Stop Loss         : ${BRED}-${SL} points${NC}\n"
    printf "      Take Profit       : ${BGREEN}+${TP} points${NC}\n"
    local rr
    rr=$(echo "scale=0; $TP / $SL" | bc 2>/dev/null || echo "2")
    printf "      R:R Ratio         : ${BWHITE}1:${rr}${NC}\n"
    printf "      Trailing SL       : "
    [ "$TSL" = "true" ] && printf "${BGREEN}✓ Enabled${NC}\n" || printf "${BRED}✗ Disabled${NC}\n"
    echo ""

    # Position
    CE=$(get_env "CE_QUANTITY" "195")
    PE=$(get_env "PE_QUANTITY" "130")
    printf "    ${BYELLOW}Position Sizing:${NC}\n"
    local ce_lots pe_lots
    ce_lots=$(echo "scale=0; $CE / 65" | bc 2>/dev/null || echo "?")
    pe_lots=$(echo "scale=0; $PE / 65" | bc 2>/dev/null || echo "?")
    printf "      CE Quantity       : ${BWHITE}${CE}${NC} (${ce_lots} lots)\n"
    printf "      PE Quantity       : ${BWHITE}${PE}${NC} (${pe_lots} lots)\n"
    echo ""

    # Strategy
    SCORE=$(get_env "MIN_SCORE" "4")
    CONF=$(get_env "MIN_CONFIDENCE" "70")
    T_START=$(get_env "TRADING_START" "09:20")
    T_END=$(get_env "TRADING_END" "15:10")
    printf "    ${BYELLOW}Strategy:${NC}\n"
    printf "      Min Score         : ${BWHITE}${SCORE}+ / 10${NC}\n"
    printf "      Min Confidence    : ${BWHITE}${CONF}%%${NC}\n"
    printf "      Trading Hours     : ${BWHITE}${T_START} - ${T_END}${NC}\n"
    echo ""

    # Limits
    MAX_D=$(get_env "MAX_TRADES_PER_DAY" "15")
    MAX_H=$(get_env "MAX_TRADES_PER_HOUR" "10")
    CD_N=$(get_env "COOLDOWN_NORMAL" "180")
    CD_SL=$(get_env "COOLDOWN_AFTER_SL" "300")
    CD_CON=$(get_env "COOLDOWN_AFTER_CONSEC_LOSS" "1200")
    printf "    ${BYELLOW}Limits & Cooldowns:${NC}\n"
    printf "      Daily/Hourly Max  : ${BWHITE}${MAX_D} / ${MAX_H}${NC}\n"
    printf "      Cooldown (N/SL/C) : ${BWHITE}${CD_N}s / ${CD_SL}s / ${CD_CON}s${NC}\n"
    echo ""

    # Services
    TELE=$(get_env "TELEGRAM_ENABLED" "true")
    WS=$(get_env "ENABLE_WEBSOCKET" "true")
    LAT=$(get_env "KILL_SWITCH_LATENCY_MS" "400")
    printf "    ${BYELLOW}Services:${NC}\n"
    printf "      Telegram          : "
    [ "$TELE" = "true" ] && printf "${BGREEN}✓${NC}\n" || printf "${DIM}Off${NC}\n"
    printf "      WebSocket         : "
    [ "$WS" = "true" ] && printf "${BGREEN}✓${NC}\n" || printf "${DIM}Off${NC}\n"
    printf "      Latency Limit     : ${BWHITE}${LAT}ms${NC}\n"
    echo ""

    draw_line "─" 55 "$BCYAN"
    printf "    ${BGREEN}[1]${NC} Validate Config\n"
    printf "    ${BGREEN}[2]${NC} Validate & Auto-Fix\n"
    printf "    ${DIM}[0]${NC} ← Back\n\n"
    printf "    ${BWHITE}Select [0-2]: ${NC}"
    read -r cchoice

    case $cchoice in
        1) echo ""; python3 config/validator.py ;;
        2) echo ""; python3 config/validator.py --fix ;;
        0) show_main_menu; return ;;
        *) printf "    ${BRED}Invalid${NC}\n" ;;
    esac
    press_enter
    menu_config
}

# ═══════════════════════════════════════════════════════════════════════════════
# ███  LEVEL 2: LOG VIEWER  ███
# ═══════════════════════════════════════════════════════════════════════════════
menu_logs() {
    clear
    echo ""
    printf "    ${BWHITE}📋 LOG VIEWER${NC}\n"
    draw_line "─" 60 "$BCYAN"
    echo ""

    LOG_DIRS=()
    while IFS= read -r d; do
        LOG_DIRS+=("$d")
    done < <(ls -d logs/20*/ 2>/dev/null | sort -r | head -15)

    if [ ${#LOG_DIRS[@]} -eq 0 ]; then
        printf "    ${DIM}No logs found.${NC}\n"
        press_enter
        show_main_menu
        return
    fi

    printf "    ${BYELLOW}Recent Trading Sessions:${NC}\n\n"
    for i in "${!LOG_DIRS[@]}"; do
        local dt day info
        dt=$(basename "${LOG_DIRS[$i]}")
        day=$(date -d "$dt" '+%A' 2>/dev/null || echo "")
        info=""
        if [ -f "${LOG_DIRS[$i]}summary.json" ]; then
            info=$(python3 -c "
import json
d = json.load(open('${LOG_DIRS[$i]}summary.json'))
t=d.get('total_trades',0); w=d.get('winning_trades',0); l=d.get('losing_trades',0)
p=d.get('total_pnl',0); s='+' if p>=0 else ''
print(f'{t} trades ({w}W/{l}L) Rs{s}{p:,.2f}')
" 2>/dev/null || echo "")
        fi
        printf "    ${BGREEN}[%2d]${NC} ${BWHITE}%-12s${NC} ${DIM}%-10s${NC} %s\n" $((i+1)) "$dt" "$day" "$info"
    done

    echo ""
    printf "    ${DIM}[0]${NC} ← Back\n\n"
    printf "    ${BWHITE}Select day [0-${#LOG_DIRS[@]}]: ${NC}"
    read -r lchoice

    if [ "$lchoice" = "0" ]; then show_main_menu; return; fi
    if [[ ! "$lchoice" =~ ^[0-9]+$ ]] || [ "$lchoice" -lt 1 ] || [ "$lchoice" -gt ${#LOG_DIRS[@]} ]; then
        printf "    ${BRED}Invalid${NC}\n"; sleep 0.5; menu_logs; return
    fi

    view_log_detail "${LOG_DIRS[$((lchoice-1))]}"
}

view_log_detail() {
    local dir="$1"
    local dt
    dt=$(basename "$dir")

    clear
    echo ""
    printf "    ${BWHITE}📋 LOG: ${dt}${NC}\n"
    draw_line "─" 60 "$BCYAN"

    # Summary
    if [ -f "${dir}summary.json" ]; then
        echo ""
        printf "    ${BYELLOW}Summary:${NC}\n"
        python3 -c "
import json
d = json.load(open('${dir}summary.json'))
print(f\"      Trades    : {d.get('total_trades',0)} ({d.get('winning_trades',0)}W / {d.get('losing_trades',0)}L)\")
pnl = d.get('total_pnl', 0)
c = '\033[1;32m' if pnl >= 0 else '\033[1;31m'
print(f\"      PnL       : {c}Rs{pnl:+,.2f}\033[0m\")
wr = d.get('winning_trades',0) / max(d.get('total_trades',1), 1) * 100
print(f\"      Win Rate  : {wr:.1f}%\")
if 'ticks_received' in d: print(f\"      Ticks     : {d['ticks_received']:,}\")
if 'session_duration_sec' in d:
    s = d['session_duration_sec']
    print(f\"      Duration  : {s/3600:.1f}h ({s/60:.0f}m)\")
if d.get('kill_switch_count', 0) > 0:
    print(f\"      Kill Sw.  : \033[1;31m{d['kill_switch_count']} triggered\033[0m\")
" 2>/dev/null
    fi

    # File list
    echo ""
    printf "    ${BYELLOW}Files:${NC}\n"
    FILES=()
    while IFS= read -r f; do
        FILES+=("$f")
    done < <(ls "${dir}" 2>/dev/null)

    for i in "${!FILES[@]}"; do
        local sz
        sz=$(wc -c < "${dir}${FILES[$i]}" 2>/dev/null || echo "?")
        printf "    ${BGREEN}[%d]${NC} %-20s ${DIM}(%s bytes)${NC}\n" $((i+1)) "${FILES[$i]}" "$sz"
    done
    echo ""
    printf "    ${DIM}[0]${NC} ← Back to log list\n\n"
    printf "    ${BWHITE}View file [0-${#FILES[@]}]: ${NC}"
    read -r fchoice

    if [ "$fchoice" = "0" ]; then menu_logs; return; fi

    if [[ "$fchoice" =~ ^[0-9]+$ ]] && [ "$fchoice" -ge 1 ] && [ "$fchoice" -le ${#FILES[@]} ]; then
        local sel="${dir}${FILES[$((fchoice-1))]}"
        echo ""
        printf "    ${BCYAN}── ${FILES[$((fchoice-1))]} ──${NC}\n\n"
        if [[ "$sel" == *.json ]]; then
            python3 -c "import json; print(json.dumps(json.load(open('$sel')), indent=2))" 2>/dev/null | head -80
        elif [[ "$sel" == *.csv ]]; then
            column -t -s',' "$sel" 2>/dev/null | head -40 || head -40 "$sel"
        else
            head -80 "$sel"
        fi
        local total_lines
        total_lines=$(wc -l < "$sel" 2>/dev/null || echo "?")
        printf "\n    ${DIM}(Showing first lines of ${total_lines} total)${NC}\n"
    fi

    press_enter
    view_log_detail "$dir"
}

# ═══════════════════════════════════════════════════════════════════════════════
# ███  LEVEL 2: SYSTEM HEALTH  ███
# ═══════════════════════════════════════════════════════════════════════════════
menu_health() {
    clear
    echo ""
    printf "    ${BWHITE}🩺 SYSTEM HEALTH CHECK${NC}\n"
    draw_line "═" 60 "$BCYAN"
    echo ""

    # Python
    printf "    ${BYELLOW}System:${NC}\n"
    PYVER=$(python3 --version 2>&1 | awk '{print $2}')
    printf "      Python            : ${BGREEN}✓ ${PYVER}${NC}\n"

    # Venv
    if [ -d "venv" ]; then
        printf "      Virtual Env       : ${BGREEN}✓ Active${NC}\n"
    else
        printf "      Virtual Env       : ${BRED}✗ Missing${NC}\n"
    fi

    # .env
    if [ -f ".env" ]; then
        local envl
        envl=$(wc -l < .env)
        printf "      .env Config       : ${BGREEN}✓ ${envl} lines${NC}\n"
    else
        printf "      .env Config       : ${BRED}✗ Missing${NC}\n"
    fi

    # SmartAPI
    printf "      SmartAPI Package  : "
    if python3 -c "from SmartApi import SmartConnect" 2>/dev/null; then
        printf "${BGREEN}✓ Installed${NC}\n"
    else
        printf "${BRED}✗ Missing${NC}\n"
    fi
    echo ""

    # Syntax
    printf "    ${BYELLOW}Syntax Check:${NC}\n"
    local sok=0 sfail=0
    for f in app.py core/main.py core/engines/entry_engine.py core/engines/exit_engine.py \
             core/engines/state_machine.py core/trading/broker.py core/risk/kill_switch.py \
             strategies/smart_scalp_v3.py config/constants.py config/validator.py; do
        if python3 -c "import ast; ast.parse(open('$f').read())" 2>/dev/null; then
            sok=$((sok + 1))
        else
            printf "      ${BRED}✗${NC} $f\n"
            sfail=$((sfail + 1))
        fi
    done
    if [ $sfail -eq 0 ]; then
        printf "      ${BGREEN}✓ All ${sok} critical files OK${NC}\n"
    else
        printf "      ${BRED}✗ ${sfail} errors${NC}\n"
    fi
    echo ""

    # Tests
    printf "    ${BYELLOW}Test Suite:${NC}\n"
    printf "      Running..."
    TEST_R=$(python3 -m pytest tests/ -q --tb=no 2>&1 | tail -1)
    printf "\r                \r"
    if echo "$TEST_R" | grep -q "passed"; then
        printf "      ${BGREEN}✓ ${TEST_R}${NC}\n"
    else
        printf "      ${BRED}✗ ${TEST_R}${NC}\n"
    fi
    echo ""

    # Config validation
    printf "    ${BYELLOW}Config Validation:${NC}\n"
    VRES=$(python3 config/validator.py 2>&1 | tail -3)
    if echo "$VRES" | grep -qi "pass\|ok\|valid\|success"; then
        printf "      ${BGREEN}✓ Configuration valid${NC}\n"
    else
        printf "      ${BYELLOW}⚠ Review needed${NC}\n"
    fi
    echo ""

    # API
    printf "    ${BYELLOW}API Connectivity:${NC}\n"
    printf "      Angel One API     : "
    API_R=$(timeout 15 python3 -c "
try:
    from brokers.angel_one.client import AngelOneClient
    c = AngelOneClient()
    print('OK' if c.login() else 'FAIL')
except Exception as e:
    print(f'ERR:{e}')
" 2>/dev/null)
    if [ "$API_R" = "OK" ]; then
        printf "${BGREEN}✓ Connected${NC}\n"
    else
        printf "${BRED}✗ ${API_R:-No response}${NC}\n"
    fi

    # Disk
    if [ -d "logs" ]; then
        local lsz ldays
        lsz=$(du -sh logs/ 2>/dev/null | awk '{print $1}')
        ldays=$(ls -d logs/20*/ 2>/dev/null | wc -l)
        printf "      Logs              : ${BGREEN}✓ ${lsz} (${ldays} days)${NC}\n"
    fi
    echo ""

    # Last session
    printf "    ${BYELLOW}Last Session:${NC}\n"
    LATEST=$(ls -d logs/20*/ 2>/dev/null | sort | tail -1)
    if [ -n "$LATEST" ] && [ -f "${LATEST}summary.json" ]; then
        local ldate
        ldate=$(basename "$LATEST")
        python3 -c "
import json
d = json.load(open('${LATEST}summary.json'))
print(f'      Date      : ${ldate}')
print(f\"      Trades    : {d.get('total_trades',0)} ({d.get('winning_trades',0)}W / {d.get('losing_trades',0)}L)\")
p = d.get('total_pnl', 0)
c = '\033[1;32m' if p >= 0 else '\033[1;31m'
print(f\"      PnL       : {c}Rs{p:+,.2f}\033[0m\")
" 2>/dev/null
    else
        printf "      ${DIM}No sessions found${NC}\n"
    fi

    press_enter
    show_main_menu
}

# ═══════════════════════════════════════════════════════════════════════════════
# ███  LEVEL 2: PROJECT TOOLS  ███
# ═══════════════════════════════════════════════════════════════════════════════
menu_tools() {
    clear
    echo ""
    printf "    ${BCYAN}╔══════════════════════════════════════════════════════════╗${NC}\n"
    printf "    ${BCYAN}║${NC}  ${BWHITE}🔧 PROJECT TOOLS${NC}                                        ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}╠══════════════════════════════════════════════════════════╣${NC}\n"
    printf "    ${BCYAN}║${NC}                                                          ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[1]${NC} Project Structure    ${DIM}File tree overview${NC}          ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[2]${NC} Disk Usage           ${DIM}Size of project dirs${NC}        ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[3]${NC} Python Code Stats    ${DIM}Lines of code count${NC}         ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[4]${NC} Installed Packages   ${DIM}pip list${NC}                    ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[5]${NC} Run Cleanup Script   ${DIM}cleanup.sh${NC}                  ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[6]${NC} View Documentation   ${DIM}README / DOCS${NC}               ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${BGREEN}[7]${NC} Bot Monitor Status   ${DIM}Live monitor snapshot${NC}       ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}   ${DIM}[0]${NC} ← Back                                             ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}║${NC}                                                          ${BCYAN}║${NC}\n"
    printf "    ${BCYAN}╚══════════════════════════════════════════════════════════╝${NC}\n"
    echo ""
    printf "    ${BWHITE}Select [0-7]: ${NC}"
    read -r pchoice

    echo ""
    case $pchoice in
        1)
            printf "    ${BWHITE}Project Structure:${NC}\n\n"
            find . -path ./venv -prune -o -path ./.git -prune -o -path ./__pycache__ -prune -o -print | \
                grep -v "__pycache__" | sort | head -80 | \
                sed 's|^\./||' | while IFS= read -r line; do
                    printf "      %s\n" "$line"
                done
            ;;
        2)
            printf "    ${BWHITE}Disk Usage:${NC}\n\n"
            for d in core/ strategies/ brokers/ config/ utils/ tests/ logs/ data/; do
                if [ -d "$d" ]; then
                    local sz
                    sz=$(du -sh "$d" 2>/dev/null | awk '{print $1}')
                    printf "      %-20s ${BWHITE}%s${NC}\n" "$d" "$sz"
                fi
            done
            echo ""
            local total_sz
            total_sz=$(du -sh --exclude=venv . 2>/dev/null | awk '{print $1}')
            printf "      ${BWHITE}Total (excl venv):  ${total_sz}${NC}\n"
            ;;
        3)
            printf "    ${BWHITE}Python Code Stats:${NC}\n\n"
            local total_files=0 total_lines=0
            while IFS= read -r f; do
                local lines
                lines=$(wc -l < "$f" 2>/dev/null || echo 0)
                total_files=$((total_files + 1))
                total_lines=$((total_lines + lines))
                printf "      %-45s ${BWHITE}%5d lines${NC}\n" "$f" "$lines"
            done < <(find . -path ./venv -prune -o -name '*.py' -print | sort)
            echo ""
            printf "      ${BWHITE}Total: ${total_files} files, ${total_lines} lines${NC}\n"
            ;;
        4) pip list 2>/dev/null ;;
        5)
            if [ -f "cleanup.sh" ]; then
                printf "    ${BYELLOW}Running cleanup.sh...${NC}\n\n"
                bash cleanup.sh
            else
                printf "    ${DIM}cleanup.sh not found${NC}\n"
            fi
            ;;
        6)
            printf "    ${BWHITE}Documentation Files:${NC}\n\n"
            for doc in README.md DOCUMENTATION.md PROJECT_STRUCTURE.md FILE_STRUCTURE_GUIDE.md; do
                if [ -f "$doc" ]; then
                    local doc_lines
                    doc_lines=$(wc -l < "$doc")
                    printf "      ${BGREEN}•${NC} %-30s ${DIM}(%d lines)${NC}\n" "$doc" "$doc_lines"
                fi
            done
            echo ""
            printf "    ${BWHITE}View which file? (filename or 0): ${NC}"
            read -r docfile
            if [ "$docfile" != "0" ] && [ -f "$docfile" ]; then
                echo ""
                head -60 "$docfile"
                echo ""
                printf "    ${DIM}(First 60 lines shown)${NC}\n"
            fi
            ;;
        7)
            printf "    ${BWHITE}Bot Monitor Status:${NC}\n\n"
            python3 -c "
from utils.monitoring import get_monitor
m = get_monitor()
s = m.get_status()
for k, v in s.items():
    print(f'      {k:20s}: {v}')
" 2>/dev/null || printf "    ${DIM}Monitor not available (bot not running)${NC}\n"
            ;;
        0) show_main_menu; return ;;
        *) printf "    ${BRED}Invalid${NC}\n" ;;
    esac
    press_enter
    menu_tools
}

# ═══════════════════════════════════════════════════════════════════════════════
# ███  ENTRY POINT  ███
# ═══════════════════════════════════════════════════════════════════════════════
boot_sequence
show_main_menu

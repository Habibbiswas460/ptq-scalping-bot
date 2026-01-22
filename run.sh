#!/bin/bash
# PTQ Scalping Bot - Run Script

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}PTQ Scalping Bot${NC}"
echo "================================"

# Check if venv exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install dependencies if needed
if [ ! -f "venv/.installed" ]; then
    echo -e "${YELLOW}Installing dependencies...${NC}"
    pip install -r requirements.txt
    touch venv/.installed
fi

# Check credentials
if [ ! -f "config/credentials.json" ]; then
    echo -e "${YELLOW}Warning: credentials.json not found${NC}"
    echo "Running in paper trading mode..."
fi

# Run the bot
echo -e "${GREEN}Starting bot...${NC}"
python app.py

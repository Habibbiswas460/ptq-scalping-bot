import json

def load_config(path: str = 'config/bot_config.json'):
    """Load bot configuration from a JSON file."""
    with open(path, 'r') as f:
        return json.load(f)

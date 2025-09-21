import requests
import re

def get_channel_id_from_handle(handle):
    """Get channel ID from YouTube handle (@username)."""
    try:
        # Remove @ if present
        handle = handle.replace('@', '')
        
        # Try to get channel ID by scraping the channel page
        url = f"https://www.youtube.com/@{handle}"
        print(f"Fetching: {url}")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, timeout=10, headers=headers)
        
        if response.status_code == 200:
            # Look for channel ID in the page source
            # Pattern to find channel ID in YouTube page source
            patterns = [
                r'"channelId":"([^"]+)"',
                r'"externalId":"([^"]+)"',
                r'/channel/([^/"]+)',
                r'channel_id=([^&"]+)'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, response.text)
                if match:
                    channel_id = match.group(1)
                    print(f"Found channel ID for @{handle}: {channel_id}")
                    return channel_id
        
        print(f"Could not find channel ID for @{handle} (Status: {response.status_code})")
        return ''
        
    except Exception as e:
        print(f"Error getting channel ID for @{handle}: {e}")
        return ''

# Get channel IDs for the requested channels
channels = [
    'CricketAakash'
]

print("Getting channel IDs for Indian business/podcast channels:")
print("=" * 60)

for handle in channels:
    channel_id = get_channel_id_from_handle(handle)
    if channel_id:
        print(f"@{handle} -> {channel_id}")
    else:
        print(f"@{handle} -> FAILED")
    print()

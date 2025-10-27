# ENTSO-E API Key Setup Guide

## Problem Identified

You're getting a 401 authentication error because:

1. Your shell has `ENTSOE_API_KEY=test-key` set as an environment variable
2. This overrides the .env file which contains a proper UUID format key
3. "test-key" is not a valid ENTSO-E API key

## Solution Steps

### Step 1: Get a Valid ENTSO-E API Key

1. Go to https://transparency.entsoe.eu/
2. Create an account if you don't have one
3. Request an API key (this may take 1-2 business days for approval)
4. The key will be a long string (36+ characters), not "test-key"

### Step 2: Fix Environment Variable Override

Choose one of these options:

#### Option A: Unset the environment variable (Recommended)

```bash
unset ENTSOE_API_KEY
```

#### Option B: Update the environment variable

```bash
export ENTSOE_API_KEY="your-real-api-key-here"
```

### Step 3: Update .env File

Replace the current key in `.env` with your real API key:

```
ENTSOE_API_KEY=your-real-api-key-from-entsoe
```

### Step 4: Test the API

```bash
python3 -c "
import os
import requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv('ENTSOE_API_KEY')
print(f'Testing API key: {api_key[:8]}...{api_key[-8:]}')

url = 'https://web-api.tp.entsoe.eu/api'
params = {
    'securityToken': api_key,
    'documentType': 'A44',
    'in_Domain': '10YNL----------L',
    'out_Domain': '10YNL----------L',
    'periodStart': '202510270000',
    'periodEnd': '202510280000'
}

response = requests.get(url, params=params, timeout=10)
print(f'Response status: {response.status_code}')
if response.status_code == 200:
    print('✅ API key is working!')
else:
    print('❌ Still not working')
"
```

## Current Status

- ❌ Environment variable `ENTSOE_API_KEY=test-key` is overriding .env file
- ❌ "test-key" is not a valid ENTSO-E API key
- ✅ Project structure and code are correct
- ✅ All other configuration looks good

## Quick Fix for Testing

If you want to test immediately with the key from .env file:

```bash
unset ENTSOE_API_KEY
python3 api_server.py
```

Then test the API endpoint:

```bash
curl "http://localhost:8000/energy/prices/cheapest?date=2025-10-27"
```

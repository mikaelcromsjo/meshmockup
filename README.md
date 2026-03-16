# mockup-demo

Sandbox demo: enter a YouTube channel → get a branded mug mockup via Gemini.

## Setup

1. Get API keys:
   - Gemini: https://aistudio.google.com/app/apikey
   - YouTube Data API v3: https://console.cloud.google.com → enable "YouTube Data API v3"

2. Install dependencies:
   pip install -r requirements.txt

3. Add a sample mug image:
   Drop any plain mug PNG into `data/sample_mug.png`
   (free ones at: https://mockupworld.co)

4. Set environment variables:
   cp .env.example .env
   # edit .env with your keys

5. Run:
   export $(cat .env | xargs)
   python api_server.py

6. Open http://localhost:8010

## CLI (no server needed)

    python mini_mockup.py "https://www.youtube.com/@YourChannel" data/sample_mug.png output.png

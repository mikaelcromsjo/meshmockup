"""
Minimal Flask server — serves demo.html and the mockup API endpoint.
"""

import base64
import os
from flask import Flask, request, jsonify, send_from_directory
from mini_mockup import run, GeminiError

app = Flask(__name__, static_folder=".")
SAMPLE_MUG = os.environ.get("SAMPLE_MUG_PATH", "data/sample_mug.png")

from dotenv import load_dotenv
load_dotenv()

@app.route("/")
def index():
    return send_from_directory(".", "demo.html")


@app.route("/api/sandbox/mockup", methods=["POST"])
def mockup():
    body = request.get_json(silent=True) or {}
    channel_url = body.get("channel_url", "").strip()

    if not channel_url:
        return jsonify({"error": "channel_url is required"}), 400

    try:
        image_bytes, channel_name = run(channel_url, SAMPLE_MUG)
        b64 = base64.b64encode(image_bytes).decode()
        return jsonify({
            "channel_name": channel_name,
            "image_url": f"data:image/png;base64,{b64}",
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except GeminiError as e:
        return jsonify({"error": f"Generation failed: {e}"}), 502
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8888))
    print(f"🚀 Running on http://localhost:{port}")
    app.run(port=port, debug=True)

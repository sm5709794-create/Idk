from flask import Flask, request, jsonify
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import binascii
import requests
import my_pb2
import output_pb2
import jwt

app = Flask(__name__)

AES_KEY = b'Yg&tc%DEuh6%Zc^8'
AES_IV = b'6oyZDr22E3ychjM%'

def encrypt_message(plaintext):
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    padded_message = pad(plaintext, AES.block_size)
    return cipher.encrypt(padded_message)

def fetch_open_id(access_token):
    try:
        uid_url = "https://prod-api.reward.ff.garena.com/redemption/api/auth/inspect_token/"
        uid_headers = {
            "access-token": access_token,
            "User-Agent": "Mozilla/5.0"
        }

        uid_res = requests.get(uid_url, headers=uid_headers)
        uid_data = uid_res.json()
        uid = uid_data.get("uid")

        if not uid:
            return None, "Failed to extract UID"

        openid_url = "https://shop2game.com/api/auth/player_id_login"
        payload = {
            "app_id": 100067,
            "login_id": str(uid)
        }

        openid_res = requests.post(openid_url, json=payload)
        openid_data = openid_res.json()
        open_id = openid_data.get("open_id")

        if not open_id:
            return None, "Failed to extract open_id"

        return open_id, None

    except Exception as e:
        return None, str(e)

@app.route('/access-jwt', methods=['GET'])
def majorlogin_jwt():
    access_token = request.args.get('access_token')
    open_id = request.args.get('open_id')

    if not access_token or not open_id:
        return jsonify({"message": "missing access_token or open_id"}), 400

    try:
        result = {
            "status": "success",
            "access_token": access_token,
            "open_id": open_id
        }
        return jsonify(result)
    except Exception as e:
        return jsonify({"message": str(e)}), 500


# 🔥 MAIN CHANGE — DIRECT API FORWARD
@app.route('/token', methods=['GET'])
def oauth_guest():
    uid = request.args.get('uid')
    password = request.args.get('password')

    if not uid or not password:
        return jsonify({"message": "Missing uid or password"}), 400

    try:
        # 🔥 YOUR MAIN API
        api_url = f"http://157.15.98.85:25565/generate-jwt?uid={uid}&password={password}"

        response = requests.get(api_url, timeout=10)

        try:
            return jsonify(response.json()), response.status_code
        except:
            return jsonify({"message": response.text}), response.status_code

    except requests.RequestException as e:
        return jsonify({"message": str(e)}), 500


@app.route('/')
def home():
    return jsonify({"status": "running"})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=1080, debug=False)
from flask import Flask, request, jsonify
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
import binascii
import aiohttp
import requests
import json
import like_pb2
import like_count_pb2
import uid_generator_pb2
from google.protobuf.message import DecodeError
import logging
import warnings
from urllib3.exceptions import InsecureRequestWarning
from functools import wraps

warnings.simplefilter('ignore', InsecureRequestWarning)

app = Flask(__name__)
app.logger.setLevel(logging.CRITICAL)

# Master Key
MASTER_KEY = "SAGARFF"

# Keys with batch size
KEYS = {
    "20LIKE": {"batch": 100},
}

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        master = request.args.get('master')
        if not master or master != MASTER_KEY:
            return jsonify({"error": "Invalid master key"}), 401
        
        api_key = request.args.get('api_key')
        if not api_key or api_key not in KEYS:
            return jsonify({"error": "Invalid API key"}), 401
        
        return f(*args, **kwargs, api_key=api_key)
    return decorated

def load_tokens(region):
    try:
        if region == "IND":
            with open("token_ind.json", "r") as f:
                tokens = json.load(f)
        elif region in {"BR", "US", "SAC", "NA"}:
            with open("token_br.json", "r") as f:
                tokens = json.load(f)
        else:
            with open("token_bd.json", "r") as f:
                tokens = json.load(f)
        return tokens
    except Exception as e:
        app.logger.error(f"Token load failed: {region}. Error: {e}") 
        return None

def encrypt_message(plaintext):
    try:
        key = b'Yg&tc%DEuh6%Zc^8'
        iv = b'6oyZDr22E3ychjM%'
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded_message = pad(plaintext, AES.block_size)
        encrypted_message = cipher.encrypt(padded_message)
        return binascii.hexlify(encrypted_message).decode('utf-8')
    except Exception as e:
        app.logger.error(f"Encryption failed. Error: {e}")
        return None

def create_protobuf_message(user_id, region):
    try:
        message = like_pb2.like()
        message.uid = int(user_id)
        message.region = region
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Protobuf creation (like) failed. Error: {e}")
        return None

async def send_request(encrypted_uid, token, url):
    try:
        edata = bytes.fromhex(encrypted_uid)
        headers = {
            'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            'Connection': "Keep-Alive",
            'Accept-Encoding': "gzip",
            'Authorization': f"Bearer {token}",
            'Content-Type': "application/x-www-form-urlencoded",
            'Expect': "100-continue",
            'X-Unity-Version': "2018.4.11f1",
            'X-GA': "v1 1",
            'ReleaseVersion': "OB55"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=edata, headers=headers) as response:
                if response.status != 200:
                    app.logger.error(f"Request failed: Status {response.status}") 
                    return response.status
                return await response.text()
    except Exception as e:
        app.logger.error(f"send_request exception: {e}")
        return None

async def send_multiple_requests(uid, region, url, batch_size):
    try:
        protobuf_message = create_protobuf_message(uid, region)
        if protobuf_message is None:
            app.logger.error("Like protobuf failed.")
            return 0
        encrypted_uid = encrypt_message(protobuf_message)
        if encrypted_uid is None:
            app.logger.error("Like encryption failed.")
            return 0
        
        tasks = []
        tokens = load_tokens(region)
        if tokens is None:
            app.logger.error("Token load failed in multi-send.")
            return 0
        
        for i in range(batch_size):
            token = tokens[i % len(tokens)]["token"]
            tasks.append(send_request(encrypted_uid, token, url))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        success_count = sum(1 for r in results if r is not None and r == 200)
        return success_count
    except Exception as e:
        app.logger.error(f"send_multiple_requests exception: {e}")
        return 0

def create_protobuf(uid):
    try:
        message = uid_generator_pb2.uid_generator()
        message.saturn_ = int(uid)
        message.garena = 1
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Protobuf creation (uid) failed. Error: {e}")
        return None

def enc(uid):
    protobuf_data = create_protobuf(uid)
    if protobuf_data is None:
        return None
    encrypted_uid = encrypt_message(protobuf_data)
    return encrypted_uid

def make_request(encrypt, region, token):
    try:
        if region == "IND":
            url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
        elif region in {"BR", "US", "SAC", "NA"}:
            url = "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
        else:
            url = "https://clientbp.ggblueshark.com/GetPlayerPersonalShow"
        edata = bytes.fromhex(encrypt)
        headers = {
            'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            'Connection': "Keep-Alive",
            'Accept-Encoding': "gzip",
            'Authorization': f"Bearer {token}",
            'Content-Type': "application/x-www-form-urlencoded",
            'Expect': "100-continue",
            'X-Unity-Version': "2018.4.11f1",
            'X-GA': "v1 1",
            'ReleaseVersion': "OB55"
        }
        response = requests.post(url, data=edata, headers=headers, verify=False) 
        hex_data = response.content.hex()
        binary = bytes.fromhex(hex_data)
        decode = decode_protobuf(binary)
        if decode is None:
            app.logger.error("Protobuf decode failed in make_request.")
        return decode
    except Exception as e:
        app.logger.error(f"make_request exception: {e}")
        return None

def decode_protobuf(binary):
    try:
        items = like_count_pb2.Info()
        items.ParseFromString(binary)
        return items
    except DecodeError as e:
        app.logger.error(f"DecodeError: {e}")
        return None
    except Exception as e:
        app.logger.error(f"Decode failed: {e}")
        return None

@app.route('/like', methods=['GET'])
@require_auth
def handle_requests(api_key):
    uid = request.args.get("uid")
    region = request.args.get("region", "").upper()
    
    if not uid or not region:
        return jsonify({"error": "UID and region are required"}), 400

    try:
        tokens = load_tokens(region)
        if tokens is None:
            return jsonify({"error": "Failed to load tokens"}), 500
        
        token = tokens[0]['token']
        encrypted_uid = enc(uid)
        if encrypted_uid is None:
            return jsonify({"error": "Encryption failed"}), 500

        # Get before likes
        before = make_request(encrypted_uid, region, token)
        if before is None:
            return jsonify({"error": "Failed to get player info"}), 500
        
        jsone = MessageToJson(before)
        data_before = json.loads(jsone)
        before_like = int(data_before.get('AccountInfo', {}).get('Likes', 0))
        player_name = data_before.get('AccountInfo', {}).get('PlayerNickname', 'Unknown')
        player_uid = data_before.get('AccountInfo', {}).get('UID', uid)

        # Set URL
        if region == "IND":
            url = "https://client.ind.freefiremobile.com/LikeProfile"
        elif region in {"BR", "US", "SAC", "NA"}:
            url = "https://client.us.freefiremobile.com/LikeProfile"
        else:
            url = "https://clientbp.ggblueshark.com/LikeProfile"

        # Send likes with batch size from key
        batch_size = KEYS[api_key]["batch"]
        likes_sent = asyncio.run(send_multiple_requests(uid, region, url, batch_size))

        # Get after likes
        after = make_request(encrypted_uid, region, token)
        if after is None:
            return jsonify({"error": "Failed to get updated player info"}), 500
        
        jsone_after = MessageToJson(after)
        data_after = json.loads(jsone_after)
        after_like = int(data_after.get('AccountInfo', {}).get('Likes', 0))
        
        likes_given = after_like - before_like
        status = 1 if likes_given > 0 else 0
        
        result = {
            "PlayerNickname": player_name,
            "UID": int(player_uid),
            "LikesbeforeCommand": before_like,
            "LikesGivenByAPI": likes_given,
            "LikesafterCommand": after_like,
            "batchSize": batch_size,
            "status": status
        }
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"Main request processing failed: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("\n" + "="*40)
    print("FREE FIRE LIKE BOT")
    print("="*40)
    print(f"Master Key: {MASTER_KEY}")
    print("\nAvailable Keys:")
    for key, data in KEYS.items():
        print(f"  {key}: batch={data['batch']}")
    print("="*40 + "\n")
    app.run(debug=True, host='0.0.0.0', port=9000)

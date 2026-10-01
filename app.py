import json
import random
import binascii
import asyncio
import aiohttp
import requests
import urllib3
from flask import Flask, request, jsonify
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import like_pb2
import like_count_pb2
import uid_generator_pb2

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

EXPECTED_API_KEY = "JEETHURVISWA"
TOKEN_BATCH_SIZE = 500
CREDITS = "@viswajeethu"

app = Flask(__name__)


def encrypt_message(plaintext):
    key = b'Yg&tc%DEuh6%Zc^8'
    iv = b'6oyZDr22E3ychjM%'
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded = pad(plaintext, AES.block_size)
    return binascii.hexlify(cipher.encrypt(padded)).decode('utf-8')


def create_protobuf_message(user_id, region):
    message = like_pb2.like()
    message.uid = int(user_id)
    message.region = region
    return message.SerializeToString()


def create_protobuf_for_profile_check(uid):
    message = uid_generator_pb2.uid_generator()
    message.krishna_ = int(uid)
    message.teamXdarks = 1
    return message.SerializeToString()


def enc_profile_check_payload(uid):
    return encrypt_message(create_protobuf_for_profile_check(uid))


def get_token_file(server_name):
    if server_name == "IND":
        return "token_ind.json"
    elif server_name in {"BR", "US", "NA", "SAC"}:
        return "token_br.json"
    return "token_bd.json"


def load_tokens(server_name):
    path = get_token_file(server_name)
    try:
        with open(path, "r") as f:
            data = json.load(f)
            if isinstance(data, list):
                return [t for t in data if isinstance(t, dict) and t.get("token")]
    except Exception as e:
        print(f"[ERROR] Loading {path}: {e}")
    return []


def get_like_url(server_name):
    if server_name == "IND":
        return "https://client.ind.freefiremobile.com/LikeProfile"
    elif server_name in {"BR", "US", "NA", "SAC"}:
        return "https://client.us.freefiremobile.com/LikeProfile"
    return "https://clientbp.ppmainecoonghj.com/LikeProfile"


def get_profile_url(server_name):
    if server_name == "IND":
        return "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
    elif server_name in {"BR", "US", "NA", "SAC"}:
        return "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
    return "https://clientbp.ppmainecoonghj.com/GetPlayerPersonalShow"


def build_headers(token):
    return {
        'User-Agent': "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Authorization': f"Bearer {token}",
        'Content-Type': "application/x-www-form-urlencoded",
        'Expect': "100-continue",
        'X-Unity-Version': "2018.4.11f1",
        'X-GA': "v1 1",
        'ReleaseVersion': "OB55"
    }


async def send_single_like(session, encrypted_payload, token, url):
    edata = bytes.fromhex(encrypted_payload)
    try:
        async with session.post(
            url,
            data=edata,
            headers=build_headers(token),
            timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            return response.status
    except asyncio.TimeoutError:
        return 998
    except Exception:
        return 997


async def send_likes(uid, region, url, tokens):
    payload = encrypt_message(create_protobuf_message(uid, region))
    async with aiohttp.ClientSession() as session:
        tasks = [
            send_single_like(session, payload, t.get("token", ""), url)
            for t in tokens if t.get("token")
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    successful = sum(1 for r in results if isinstance(r, int) and r == 200)
    print(f"[LIKE] {successful} successful out of {len(tokens)}")
    return results


def check_profile(uid, server_name, token):
    url = get_profile_url(server_name)
    edata = bytes.fromhex(enc_profile_check_payload(uid))
    try:
        response = requests.post(
            url,
            data=edata,
            headers=build_headers(token),
            verify=False,
            timeout=10
        )
        response.raise_for_status()
        info = like_count_pb2.Info()
        info.ParseFromString(response.content)
        return info
    except Exception as e:
        print(f"[PROFILE] Error: {e}")
        return None


def extract_profile(info, uid):
    result = {"like_count": 0, "uid": int(uid), "nickname": "N/A", "is_valid": False}
    if not info:
        return result
    try:
        if hasattr(info, 'AccountInfo'):
            acc = info.AccountInfo
            if hasattr(acc, 'Likes'):
                result["like_count"] = int(acc.Likes)
            if hasattr(acc, 'UID'):
                result["uid"] = int(acc.UID)
            if hasattr(acc, 'PlayerNickname'):
                nick = acc.PlayerNickname
                if isinstance(nick, bytes):
                    nick = nick.decode('utf-8', errors='ignore')
                nick = str(nick).strip()
                result["nickname"] = nick if nick else "N/A"
            result["is_valid"] = True
    except Exception as e:
        print(f"[PROFILE] Extract error: {e}")
    return result


@app.route('/like', methods=['GET'])
def handle_like():
    provided_key = request.args.get("key")
    if provided_key != EXPECTED_API_KEY:
        return jsonify({
            "error": "Wrong key",
            "message": "Build ur self an api",
            "credits": CREDITS
        }), 401

    uid = request.args.get("uid")
    server_name = request.args.get("server_name", "").upper()

    if not uid or not server_name:
        return jsonify({
            "error": "UID and server_name are required",
            "credits": CREDITS
        }), 400

    tokens = load_tokens(server_name)
    if not tokens:
        return jsonify({
            "error": f"No tokens available for region {server_name}",
            "credits": CREDITS
        }), 500

    if len(tokens) > TOKEN_BATCH_SIZE:
        tokens = random.sample(tokens, TOKEN_BATCH_SIZE)

    like_url = get_like_url(server_name)

    profile_token = random.choice(tokens).get("token", "")
    before = extract_profile(check_profile(uid, server_name, profile_token), uid)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(send_likes(uid, server_name, like_url, tokens))
    finally:
        loop.close()

    after_token = random.choice(tokens).get("token", "")
    after = extract_profile(check_profile(uid, server_name, after_token), uid)

    before_count = before["like_count"]
    after_count = after["like_count"] if after["is_valid"] else before_count
    increment = after_count - before_count
    status = 1 if increment > 0 else (2 if increment == 0 else 3)

    return jsonify({
        "LikesGivenByAPI": increment,
        "LikesafterCommand": after_count,
        "LikesbeforeCommand": before_count,
        "PlayerNickname": after["nickname"],
        "UID": after["uid"],
        "status": status,
        "credits": CREDITS
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3001, debug=False, use_reloader=False)
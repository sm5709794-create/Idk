from flask import Flask, request, jsonify
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
import binascii
import aiohttp
import requests
import json
from pathlib import Path
import like_pb2
import like_count_pb2
import uid_generator_pb2
from google.protobuf.message import DecodeError

app = Flask(__name__)

# Always resolve token files relative to this Python file.
BASE_DIR = Path(__file__).resolve().parent

# Region -> token file / API group.
REGIONS = {
    "IND": "IND",
    "BD": "BD",
    "BR": "BR",
    "US": "BR",
    "SAC": "BR",
    "NA": "BR",
}

# Working batch size from the newer version.
DEFAULT_BATCH = 100

# Keep the same encryption values used by the original API.
AES_KEY = b'Yg&tc%DEuh6%Zc^8'
AES_IV = b'6oyZDr22E3ychjM%'

USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)"
RELEASE_VERSION = "OB55"


def load_tokens(server_name):
    """Load tokens from the correct file and fail safely."""
    try:
        server_name = server_name.upper()
        group = REGIONS.get(server_name, "BD")
        path = BASE_DIR / f"token_{group.lower()}.json"

        if not path.exists():
            app.logger.error(f"Token file not found: {path}")
            return None

        with open(path, "r", encoding="utf-8") as f:
            tokens = json.load(f)

        if not isinstance(tokens, list) or not tokens:
            app.logger.error(f"No tokens found in {path}")
            return None

        return tokens

    except Exception as e:
        app.logger.error(
            f"Error loading tokens for server {server_name}: {e}"
        )
        return None


def get_tokens_for_region(server_name):
    """
    Prefer tokens whose stored region matches the requested region.
    If the token JSON does not contain region information, fall back
    to all tokens in the correct group.
    """
    tokens = load_tokens(server_name)
    if not tokens:
        return []

    server_name = server_name.upper()

    matched = []
    for item in tokens:
        if not isinstance(item, dict):
            continue
        token = item.get("token")
        token_region = str(item.get("region", "")).upper()
        if token and token_region == server_name:
            matched.append(item)

    return matched or [
        item for item in tokens
        if isinstance(item, dict) and item.get("token")
    ]


def encrypt_message(plaintext):
    try:
        cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
        padded_message = pad(plaintext, AES.block_size)
        encrypted_message = cipher.encrypt(padded_message)
        return binascii.hexlify(encrypted_message).decode("utf-8")
    except Exception as e:
        app.logger.error(f"Error encrypting message: {e}")
        return None


def create_protobuf_message(user_id, region):
    try:
        message = like_pb2.like()
        message.uid = int(user_id)
        message.region = region
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating message protobuf: {e}")
        return None


async def send_request(session, encrypted_uid, token, url):
    """Send one LikeProfile request using a shared aiohttp session."""
    try:
        edata = bytes.fromhex(encrypted_uid)

        headers = {
            "User-Agent": USER_AGENT,
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Expect": "100-continue",
            "X-Unity-Version": "2018.4.11f1",
            "X-GA": "v1 1",
            "ReleaseVersion": RELEASE_VERSION,
        }

        async with session.post(
            url,
            data=edata,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            return response.status

    except Exception as e:
        app.logger.debug(f"Exception in send_request: {e}")
        return None


async def send_multiple_requests(uid, server_name, url, batch=DEFAULT_BATCH):
    """
    Send the requested batch using one ClientSession.
    Token selection follows the newer working implementation.
    """
    try:
        region = server_name.upper()

        protobuf_message = create_protobuf_message(uid, region)
        if protobuf_message is None:
            return 0

        encrypted_uid = encrypt_message(protobuf_message)
        if encrypted_uid is None:
            return 0

        tokens = get_tokens_for_region(region)
        if not tokens:
            app.logger.error(f"No usable tokens for region {region}")
            return 0

        success = 0
        attempts = 0
        max_attempts = batch * 3

        timeout = aiohttp.ClientTimeout(total=15)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            while success < batch and attempts < max_attempts:
                chunk = min(batch - success, 25)

                tasks = []
                for i in range(chunk):
                    token_obj = tokens[(attempts + i) % len(tokens)]
                    token = token_obj.get("token")
                    if token:
                        tasks.append(
                            send_request(
                                session,
                                encrypted_uid,
                                token,
                                url,
                            )
                        )

                if not tasks:
                    break

                results = await asyncio.gather(
                    *tasks,
                    return_exceptions=True,
                )

                for result in results:
                    if result == 200:
                        success += 1

                attempts += chunk

        return success

    except Exception as e:
        app.logger.error(f"Exception in send_multiple_requests: {e}")
        return 0


def create_protobuf(uid):
    try:
        message = uid_generator_pb2.uid_generator()
        message.saturn_ = int(uid)
        message.garena = 1
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating uid protobuf: {e}")
        return None


def enc(uid):
    protobuf_data = create_protobuf(uid)
    if protobuf_data is None:
        return None

    return encrypt_message(protobuf_data)


def get_region_url(server_name, endpoint):
    """Use the region routing from the newer working version."""
    server_name = server_name.upper()

    if server_name == "IND":
        host = "https://client.ind.freefiremobile.com"

    elif server_name in {"BR", "US", "SAC", "NA"}:
        host = "https://client.us.freefiremobile.com"

    else:
        # Newer working code uses ggblueshark for the remaining group.
        host = "https://clientbp.ggblueshark.com"

    return f"{host}/{endpoint}"


def make_request(encrypted_uid, server_name, token):
    try:
        url = get_region_url(server_name, "GetPlayerPersonalShow")
        edata = bytes.fromhex(encrypted_uid)

        headers = {
            "User-Agent": USER_AGENT,
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Expect": "100-continue",
            "X-Unity-Version": "2018.4.11f1",
            "X-GA": "v1 1",
            "ReleaseVersion": RELEASE_VERSION,
        }

        response = requests.post(
            url,
            data=edata,
            headers=headers,
            verify=False,
            timeout=10,
        )

        if response.status_code != 200:
            app.logger.error(
                f"GetPlayerPersonalShow failed: HTTP {response.status_code}"
            )
            return None

        return decode_protobuf(response.content)

    except Exception as e:
        app.logger.error(f"Error in make_request: {e}")
        return None


def decode_protobuf(binary):
    try:
        items = like_count_pb2.Info()
        items.ParseFromString(binary)
        return items
    except DecodeError as e:
        app.logger.error(f"Error decoding Protobuf data: {e}")
        return None
    except Exception as e:
        app.logger.error(f"Unexpected protobuf error: {e}")
        return None


def fetch_player_info(uid):
    try:
        url = f"https://stargamerff.qzz.io/accinfo?uid={uid}"

        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            data = response.json()
            account_info = data.get("basicInfo", {})

            return {
                "Level": account_info.get("level", "NA"),
                "Region": account_info.get("region", "NA"),
                "ReleaseVersion": account_info.get(
                    "releaseVersion", "NA"
                ),
            }

        app.logger.error(
            f"Player info API failed with status code: "
            f"{response.status_code}"
        )

    except Exception as e:
        app.logger.error(
            f"Error fetching player info from API: {e}"
        )

    return {
        "Level": "NA",
        "Region": "NA",
        "ReleaseVersion": "NA",
    }


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "FreeFire Like API",
    })


@app.route("/like", methods=["GET"])
def handle_requests():
    uid = request.args.get("uid")
    server_name = request.args.get("server_name", "").upper()

    if not uid or not server_name:
        return jsonify({
            "error": "UID and server_name are required"
        }), 400

    if server_name not in REGIONS:
        return jsonify({
            "error": f"Unsupported server_name: {server_name}",
            "supported": list(REGIONS.keys()),
        }), 400

    try:
        tokens = get_tokens_for_region(server_name)

        if not tokens:
            return jsonify({
                "error": f"No tokens available for {server_name}"
            }), 500

        # Use the first suitable token for before/after player info.
        token = tokens[0].get("token")
        if not token:
            return jsonify({
                "error": "First token is invalid"
            }), 500

        encrypted_uid = enc(uid)

        if encrypted_uid is None:
            return jsonify({
                "error": "Encryption of UID failed"
            }), 500

        # BEFORE
        before = make_request(
            encrypted_uid,
            server_name,
            token,
        )

        if before is None:
            return jsonify({
                "error": "Failed to retrieve initial player info"
            }), 500

        data_before = json.loads(MessageToJson(before))
        before_account = data_before.get("AccountInfo", {})

        before_like = int(
            before_account.get("Likes", 0)
        )

        player_uid = before_account.get("UID", uid)
        player_name = before_account.get(
            "PlayerNickname",
            "Unknown",
        )

        # LIKE REQUESTS
        like_url = get_region_url(
            server_name,
            "LikeProfile",
        )

        requests_sent = asyncio.run(
            send_multiple_requests(
                uid,
                server_name,
                like_url,
                DEFAULT_BATCH,
            )
        )

        # AFTER
        after = make_request(
            encrypted_uid,
            server_name,
            token,
        )

        if after is None:
            return jsonify({
                "error": "Failed to retrieve player info after requests",
                "requestsSent": requests_sent,
            }), 500

        data_after = json.loads(MessageToJson(after))
        account_info = data_after.get("AccountInfo", {})

        after_like = int(
            account_info.get("Likes", 0)
        )

        player_uid = account_info.get(
            "UID",
            player_uid,
        )

        player_name = account_info.get(
            "PlayerNickname",
            player_name,
        )

        # Keep the direct server values when available.
        level = account_info.get("Level") or "Unavailable"
        region = account_info.get("Region") or server_name
        release_version = (
            account_info.get("ReleaseVersion")
            or RELEASE_VERSION
        )

        like_given = after_like - before_like

        # Same working status behavior as the newer code:
        # success only when the actual like count increased.
        status = 1 if like_given > 0 else 0

        result = {
            "LikesGivenByAPI": like_given,
            "LikesafterCommand": after_like,
            "LikesbeforeCommand": before_like,
            "PlayerNickname": str(player_name),
            "UID": int(player_uid),
            "Level": level,
            "Region": region,
            "ReleaseVersion": release_version,
            "batchSize": DEFAULT_BATCH,
            "requestsSent": requests_sent,
            "status": status,
        }

        app.logger.info(
            f"/like uid={uid} region={server_name} "
            f"before={before_like} after={after_like} "
            f"given={like_given} requests={requests_sent}"
        )

        return jsonify(result)

    except ValueError:
        return jsonify({
            "error": "UID must be a valid numeric UID"
        }), 400

    except Exception as e:
        app.logger.exception(
            f"Error processing /like request: {e}"
        )
        return jsonify({
            "error": str(e)
        }), 500


if __name__ == "__main__":
    import os

    port = int(os.getenv("PORT", "6000"))

    print("=" * 55)
    print("  FREEFIRE LIKE API — FIXED")
    print("=" * 55)
    print(f"  Port : {port}")
    print(f"  Regions : {', '.join(REGIONS.keys())}")
    print(f"  Batch : {DEFAULT_BATCH}")
    print("=" * 55)

    app.run(
        debug=False,
        host="0.0.0.0",
        port=port,
        use_reloader=False,
    )

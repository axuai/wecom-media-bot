"""
企业微信素材助手 — 自动回复下载卡片

收到用户发送的抖音/快手/视频号链接 → 解析 → 回复可下载卡片
"""

import os
import re
import json
import base64
import hashlib
import socket
import struct
import time
from xml.etree import ElementTree as ET

import requests
from Crypto.Cipher import AES
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

# ============================================================
# 配置（从环境变量读取，Render 上设置）
# ============================================================
CORP_ID = os.getenv("WECOM_CORP_ID", "")
TOKEN = os.getenv("WECOM_TOKEN", "")
AES_KEY = os.getenv("WECOM_ENCODING_AES_KEY", "")
AGENT_ID = int(os.getenv("WECOM_AGENT_ID", "0"))
SECRET = os.getenv("WECOM_SECRET", "")
PARSE_API_URL = os.getenv("PARSE_API_URL", "")
PARSE_API_KEY = os.getenv("PARSE_API_KEY", "")

# ============================================================
# 企业微信加解密
# ============================================================

class WXBizMsgCrypt:
    """企业微信消息加解密"""

    def __init__(self, token, encoding_aes_key, corp_id):
        self.token = token
        self.corp_id = corp_id
        self.key = base64.b64decode(encoding_aes_key + "=")
        if len(self.key) != 32:
            raise ValueError("EncodingAESKey 长度错误，需要43位")

    def _pkcs7_pad(self, text: bytes, block_size: int = 32) -> bytes:
        pad = block_size - len(text) % block_size
        return text + bytes([pad] * pad)

    def _pkcs7_unpad(self, text: bytes) -> bytes:
        pad = text[-1]
        if pad < 1 or pad > 32:
            return text
        return text[:-pad]

    def _get_random16(self) -> bytes:
        return os.urandom(16)

    def encrypt(self, xml_str: str) -> str:
        """加密明文 XML → 返回加密后的 XML"""
        random16 = self._get_random16()
        text = random16 + struct.pack("!I", len(xml_str.encode())) + xml_str.encode() + self.corp_id.encode()
        text = self._pkcs7_pad(text)

        iv = self.key[:16]
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        encrypted = cipher.encrypt(text)
        encrypted_b64 = base64.b64encode(encrypted).decode()

        timestamp = str(int(time.time()))
        nonce = hashlib.md5(os.urandom(16)).hexdigest()[:16]
        sign = self._signature(timestamp, nonce, encrypted_b64)

        return f"""<xml>
<Encrypt><![CDATA[{encrypted_b64}]]></Encrypt>
<MsgSignature><![CDATA[{sign}]]></MsgSignature>
<TimeStamp>{timestamp}</TimeStamp>
<Nonce><![CDATA[{nonce}]]></Nonce>
</xml>"""

    def decrypt(self, xml_str: str) -> tuple:
        """解密企业微信推送的 XML → (err_code, xml_content)"""
        try:
            root = ET.fromstring(xml_str)
            encrypted = root.find("Encrypt").text
        except Exception:
            return (-40002, "")

        try:
            iv = self.key[:16]
            cipher = AES.new(self.key, AES.MODE_CBC, iv)
            decrypted = cipher.decrypt(base64.b64decode(encrypted))
            decrypted = self._pkcs7_unpad(decrypted)

            content = decrypted[16:]  # 去掉 16 字节随机数
            msg_len = socket.ntohl(struct.unpack("I", content[:4])[0])
            content = content[4:]
            xml_content = content[:msg_len].decode()
            # corp_id = content[msg_len:].decode()  # 可校验

            return (0, xml_content)
        except Exception as e:
            return (-40003, str(e))

    def _signature(self, timestamp: str, nonce: str, encrypt: str) -> str:
        params = sorted([self.token, timestamp, nonce, encrypt])
        return hashlib.sha1("".join(params).encode()).hexdigest()

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> tuple:
        """验证回调 URL → (err_code, decrypted_echostr)"""
        sign = self._signature(timestamp, nonce, echostr)
        if sign != msg_signature:
            return (-40001, "")
        try:
            iv = self.key[:16]
            cipher = AES.new(self.key, AES.MODE_CBC, iv)
            decrypted = cipher.decrypt(base64.b64decode(echostr))
            decrypted = self._pkcs7_unpad(decrypted)
            content = decrypted[16:]
            msg_len = socket.ntohl(struct.unpack("I", content[:4])[0])
            return (0, content[4:4 + msg_len].decode())
        except Exception as e:
            return (-40003, str(e))


# ============================================================
# 企业微信 API
# ============================================================

_access_token_cache = {"token": "", "expires": 0}


def get_access_token():
    """获取企业微信 access_token，带缓存"""
    now = time.time()
    if _access_token_cache["token"] and now < _access_token_cache["expires"] - 300:
        return _access_token_cache["token"]

    try:
        r = requests.get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            params={"corpid": CORP_ID, "corpsecret": SECRET},
            timeout=10,
        )
        data = r.json()
        if data.get("errcode") == 0:
            _access_token_cache["token"] = data["access_token"]
            _access_token_cache["expires"] = now + data["expires_in"]
            return data["access_token"]
    except Exception:
        pass
    return ""


def send_news_card(user_id: str, title: str, desc: str, url: str, pic_url: str):
    """发送图文卡片消息给指定用户"""
    token = get_access_token()
    if not token:
        return False

    payload = {
        "touser": user_id,
        "msgtype": "news",
        "agentid": AGENT_ID,
        "news": {
            "articles": [{
                "title": title,
                "description": desc,
                "url": url,
                "picurl": pic_url,
            }]
        },
    }

    r = requests.post(
        f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}",
        json=payload,
        timeout=10,
    )
    return r.json().get("errcode") == 0


def send_text(user_id: str, content: str):
    """发送文本消息"""
    token = get_access_token()
    if not token:
        return False

    payload = {
        "touser": user_id,
        "msgtype": "text",
        "agentid": AGENT_ID,
        "text": {"content": content},
    }

    r = requests.post(
        f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}",
        json=payload,
        timeout=10,
    )
    return r.json().get("errcode") == 0


# ============================================================
# 链接检测与解析
# ============================================================

# 支持的平台域名
PLATFORM_PATTERNS = {
    "douyin": r"(https?://(?:v\.douyin\.com|www\.douyin\.com|www\.iesdouyin\.com)[^\s]*)",
    "kuaishou": r"(https?://(?:v\.kuaishou\.com|www\.kuaishou\.com)[^\s]*)",
    "shipinhao": r"(https?://(?:finder\.video\.qq\.com|channels\.weixin\.qq\.com)[^\s]*)",
}

# 解析结果缓存（防止同一条链接多次解析）
_parse_cache = {}


def extract_links(text: str) -> list:
    """从文本中提取支持的视频链接"""
    links = []
    for platform, pattern in PLATFORM_PATTERNS.items():
        matches = re.findall(pattern, text)
        for m in matches:
            links.append({"platform": platform, "url": m})
    return links


def parse_video_api(share_url: str, platform: str) -> dict:
    """调用第三方解析 API"""
    if not PARSE_API_URL:
        return None

    # 检查缓存
    cache_key = share_url
    if cache_key in _parse_cache:
        cached = _parse_cache[cache_key]
        if time.time() - cached["time"] < 3600:  # 1小时内有效
            return cached["data"]

    try:
        headers = {"Content-Type": "application/json"}
        if PARSE_API_KEY:
            headers["Authorization"] = f"Bearer {PARSE_API_KEY}"

        r = requests.post(
            PARSE_API_URL,
            json={"url": share_url, "platform": platform},
            headers=headers,
            timeout=15,
        )
        data = r.json()

        # 适配常见的 API 返回格式
        if data.get("code") == 0:
            info = data.get("data", data)
            result = {
                "title": info.get("title", "视频下载"),
                "video_url": info.get("video_url", info.get("url", "")),
                "cover": info.get("cover", info.get("pic_url", info.get("cover_url", ""))),
            }
            _parse_cache[cache_key] = {"time": time.time(), "data": result}
            return result
    except Exception:
        pass

    return None


# ============================================================
# Flask 路由
# ============================================================


@app.route("/")
def index():
    return jsonify({"status": "ok", "service": "wecom-media-bot"})


@app.route("/debug")
def debug():
    """调试：检查配置是否正确"""
    token_ok = bool(get_access_token())
    return jsonify({
        "corp_id_set": bool(CORP_ID),
        "agent_id_set": bool(AGENT_ID),
        "secret_set": bool(SECRET),
        "token_set": bool(TOKEN),
        "aes_key_set": bool(AES_KEY),
        "parse_api_set": bool(PARSE_API_URL),
        "access_token_ok": token_ok,
        "access_token_preview": _access_token_cache["token"][:20] + "..." if _access_token_cache["token"] else "EMPTY",
    })


@app.route("/wecom/callback", methods=["GET", "POST"])
def wecom_callback():
    """
    企业微信回调入口
    GET  → URL 验证
    POST → 接收消息
    """
    if not all([CORP_ID, TOKEN, AES_KEY]):
        return "配置不完整", 500

    crypt = WXBizMsgCrypt(TOKEN, AES_KEY, CORP_ID)

    if request.method == "GET":
        # URL 验证
        msg_signature = request.args.get("msg_signature", "")
        timestamp = request.args.get("timestamp", "")
        nonce = request.args.get("nonce", "")
        echostr = request.args.get("echostr", "")

        err, decrypted = crypt.verify_url(msg_signature, timestamp, nonce, echostr)
        if err != 0:
            return f"verify failed: {err}", 403
        return Response(decrypted, mimetype="text/plain")

    # POST 消息
    try:
        xml_body = request.data.decode("utf-8")
        err, xml_content = crypt.decrypt(xml_body)
        if err != 0:
            return f"decrypt failed: {err}", 400

        root = ET.fromstring(xml_content)
        msg_type = root.find("MsgType").text if root.find("MsgType") is not None else ""
        from_user = root.find("FromUserName").text if root.find("FromUserName") is not None else ""

        if msg_type == "text":
            content = root.find("Content").text or ""
            # 异步处理，先返回 success
            handle_text_message(from_user, content)

    except Exception as e:
        app.logger.error(f"处理消息失败: {e}")

    return "success"


def handle_text_message(from_user: str, content: str):
    """处理文本消息"""
    links = extract_links(content)

    if not links:
        send_text(from_user, "请发送抖音/快手/视频号的分享链接，我会帮你解析下载。\n\n示例：https://v.douyin.com/xxxxx/")
        return

    for link in links:
        # 先回复"解析中"
        send_text(from_user, f"正在解析{_platform_name(link['platform'])}链接，请稍候...")

        result = parse_video_api(link["url"], link["platform"])

        if result and result.get("video_url"):
            # 发送下载卡片
            send_news_card(
                user_id=from_user,
                title=result["title"][:50],
                desc=f"来源：{_platform_name(link['platform'])}\n点击下载无水印视频",
                url=result["video_url"],
                pic_url=result.get("cover", ""),
            )
        else:
            # 解析失败，给一个通用提示
            send_text(
                from_user,
                f"解析失败，可能原因：\n"
                f"1. 该链接已过期或无效\n"
                f"2. 解析服务暂时不可用\n"
                f"3. 视频已被作者删除\n\n"
                f"请稍后重试或发送其他链接",
            )


def _platform_name(key: str) -> str:
    return {"douyin": "抖音", "kuaishou": "快手", "shipinhao": "视频号"}.get(key, key)


# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)

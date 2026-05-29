# 企业微信素材助手 — 后端服务

企业微信自动回复机器人。用户发送抖音/快手/视频号链接，自动回复可下载的视频卡片。

---

## 部署到 Render（免费）

### 1. 推代码到 GitHub

```bash
git init
git add .
git commit -m "first commit"
git remote add origin https://github.com/你的用户名/wecom-media-bot.git
git push -u origin main
```

### 2. Render 创建服务

1. 打开 [render.com](https://render.com) → 用 GitHub 账号登录
2. 点 **New +** → **Web Service**
3. 选择 `wecom-media-bot` 仓库
4. 配置：

| 字段 | 值 |
|------|-----|
| Name | wecom-media-bot |
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app:app -b 0.0.0.0:10000` |
| Instance Type | Free |

5. 点 **Create Web Service**

部署完成后会得到一个域名，比如 `https://wecom-media-bot.onrender.com`。

### 3. 配置环境变量

在 Render Dashboard → Environment 里添加：

| 变量名 | 说明 |
|--------|------|
| WECOM_CORP_ID | 企业微信 CorpID |
| WECOM_TOKEN | 回调 Token（自己随意设置，3-32位） |
| WECOM_ENCODING_AES_KEY | 回调 EncodingAESKey（企业微信后台随机生成） |
| WECOM_AGENT_ID | 应用 AgentId |
| WECOM_SECRET | 应用 Secret |
| PARSE_API_URL | 视频解析 API 地址（见下方） |

### 4. 企业微信后台配置回调

1. 企业微信管理后台 → 应用管理 → 你的应用
2. 接收消息 → 设置 API 接收
3. URL：`https://wecom-media-bot.onrender.com/wecom/callback`
4. Token / EncodingAESKey：填和环境变量一致的值
5. 点保存 → 验证通过即可

---

## 视频解析 API

需要对接第三方解析服务。在阿里云 API 市场或 RapidAPI 搜"抖音解析"。

常见服务商提供的接口格式：

```
POST https://api.xxx.com/v1/parse
Body: { "url": "https://v.douyin.com/xxx/" }
Response: { "code": 0, "data": { "title": "...", "video_url": "...", "cover": "..." } }
```

把 API 地址填入环境变量 `PARSE_API_URL`。

如果暂时没有解析 API，可以先不填，系统不会报错，只是不会自动解析。可以先用 `#解析` 命令测试连通性。

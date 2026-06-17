from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os

app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = "SFqZWlkhtiRJXJNHgjO6PEqeHbmgIq3Ww2fO5kiq/25W+8CjFF9bApG9e9/VzuAJSZlPsSs/VUEFWAos4nyKOzAihgrzfkjCz8kxcb7w7ogiw01htnA65RIziuKn/hlaVCjwZCu8orjs0IH0hxY1ZQdB04t89/1O/w1cDnyilFU="
CHANNEL_SECRET = "4a8fa39b484f6ef050fb4c9eb729b4ae"

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)


@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'


from linebot.models import MessageEvent, TextMessage, ImageSendMessage

IMAGE_URL = "https://i.imgur.com/tdvjX6c.png"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()

    if text == "圖片":
        line_bot_api.reply_message(
            event.reply_token,
            ImageSendMessage(
                original_content_url=IMAGE_URL,
                preview_image_url=IMAGE_URL
            )
        )
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="輸入「圖片」看業績圖")
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

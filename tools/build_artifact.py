"""
把 docs/index.html(可獨立部署的完整 HTML)轉成 Claude Artifact 需要的片段格式。

Artifact 發布時平台會自己補上 <!doctype>/<html>/<head>/<body> 外殼,
所以送過去的檔案不能自己帶這些標籤。這支程式負責把外殼拆掉,
讓 GitHub Pages 版本與 Artifact 版本共用同一份原始碼。

用法:
    python tools/build_artifact.py [輸出路徑]

預設輸出到 build/artifact_body.html
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "docs", "index.html")

# 平台外殼已經提供、或改由 Artifact 參數指定的標籤
DROP_PATTERNS = [
    re.compile(r'<meta\s+charset[^>]*>', re.I),
    re.compile(r'<meta\s+name="viewport"[^>]*>', re.I),
    re.compile(r'<link\s+rel="icon"[^>]*>', re.I),
]


def inner(html: str, tag: str) -> str:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", html, re.S | re.I)
    if not m:
        raise SystemExit(f"在 {SRC} 找不到 <{tag}> 區塊")
    return m.group(1)


def main() -> int:
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "artifact_body.html")

    with open(SRC, encoding="utf-8") as f:
        html = f.read()

    head = inner(html, "head")
    for pat in DROP_PATTERNS:
        head = pat.sub("", head)

    body = inner(html, "body")

    # Artifact 受 CSP 限制,無法 fetch 任何檔案(相對路徑也不行,
    # 因為發布的只有這一份 HTML,沒有檔案伺服器)。所以把行情資料
    # 直接內嵌成 JSON script 標籤,頁面會優先讀它而不去連外。
    # 必須放在 body 最前面。主程式是 async,await 讓出控制權後 HTML
    # 剖析器才繼續往下讀;若把資料放在最後,程式讀取時標籤可能還不存在。
    for filename, tag_id, label in (
        ("stocks.json", "seed-stocks", "行情"),
        ("backtest.json", "seed-backtest", "回測"),
    ):
        data_path = os.path.join(ROOT, "docs", "data", filename)
        if not os.path.exists(data_path):
            print(f"⚠ 找不到 docs/data/{filename},{label}資料不會內嵌")
            continue
        with open(data_path, encoding="utf-8") as f:
            raw = f.read()
        # </script> 出現在 JSON 裡會提早結束標籤,必須跳脫
        raw = raw.replace("</", "<\\/")
        body = f'<script type="application/json" id="{tag_id}">{raw}</script>\n' + body
        print(f"已內嵌{label}資料 {len(raw) / 1024 / 1024:.2f} MB")

    # 清掉拆除標籤後留下的空行(內嵌的 JSON 是單行,不受影響)
    merged = "\n".join(
        line for line in (head.rstrip() + "\n" + body).splitlines()
        if line.strip()
    ) + "\n"

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(merged)

    # 用標籤邊界比對,才不會把 <header> 誤判成 <head>
    leftover = re.search(r"<!doctype\b|</?(?:html|head|body)(?=[\s/>])", merged, re.I)
    if leftover:
        raise SystemExit(f"輸出仍含有 {leftover.group(0)},請檢查 docs/index.html 的結構")

    print(f"已輸出 {out_path}({len(merged) / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

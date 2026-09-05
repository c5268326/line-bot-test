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

    # 清掉拆除標籤後留下的空行
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

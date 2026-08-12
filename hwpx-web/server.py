# -*- coding: utf-8 -*-
"""한글 보고서 초안 생성기 — 웹 서버.

실행:
    export ANTHROPIC_API_KEY=...   # 또는 `ant auth login` 프로필
    pip install -r requirements.txt
    python server.py               # http://localhost:8765
"""
import traceback

from flask import Flask, jsonify, request, send_from_directory

import core

app = Flask(__name__, static_folder="static")

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE + 1024 * 1024


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/generate", methods=["POST"])
def generate():
    title = (request.form.get("title") or "").strip()
    content = (request.form.get("content") or "").strip()
    mode = request.form.get("mode") or None          # concise | detailed
    base_manuscript = request.form.get("base_manuscript") or None

    if mode and mode not in ("concise", "detailed"):
        return jsonify(ok=False, error="알 수 없는 보정 모드입니다."), 400
    if mode and not base_manuscript:
        return jsonify(ok=False, error="보정할 원고가 없습니다."), 400
    if not mode:
        if not title:
            return jsonify(ok=False, error="문서 제목을 입력해 주세요."), 400
        if len(content) < 20:
            return jsonify(ok=False, error="핵심 내용을 20자 이상 입력해 주세요."), 400

    attachment_text = None
    f = request.files.get("file")
    if f and f.filename:
        data = f.read()
        if len(data) > MAX_FILE_SIZE:
            return jsonify(ok=False, error="파일이 10MB를 넘습니다."), 400
        try:
            attachment_text = core.extract_attachment_text(f.filename, data)
        except ValueError as e:
            return jsonify(ok=False, error=str(e)), 400

    try:
        result = core.generate_document(
            title=title, content=content, attachment_text=attachment_text,
            mode=mode, base_manuscript=base_manuscript,
        )
    except Exception as e:
        traceback.print_exc()
        return jsonify(ok=False, error=str(e)), 500

    result["ok"] = True
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=False)

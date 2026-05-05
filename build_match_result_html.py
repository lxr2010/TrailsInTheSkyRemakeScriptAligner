from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path


def normalize_voice_stem(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if text.lower().endswith(".ogg"):
        text = text[:-4]
    if text.endswith("V"):
        text = text[:-1]
    return text


def path_to_file_uri(path: Path) -> str:
    resolved = path.resolve(strict=False)
    return resolved.as_uri()


def build_audio_path(row: dict[str, str], voice_dir: Path) -> Path | None:
    old_voice_filename = normalize_voice_stem(row.get("OldVoiceFilename", ""))
    if old_voice_filename:
        return voice_dir / f"{old_voice_filename}.ogg"

    remake_voice_id = row.get("RemakeVoiceID", "").strip()
    if remake_voice_id:
        return voice_dir / f"ch{remake_voice_id}.ogg"

    return None


def load_rows(csv_path: Path, voice_dir: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise SystemExit(f"CSV 缺少表头: {csv_path}")

        for index, row in enumerate(reader, start=1):
            audio_path = build_audio_path(row, voice_dir)
            audio_exists = audio_path is not None and audio_path.exists()
            rows.append(
                {
                    "index": str(index),
                    "remake_voice_id": row.get("RemakeVoiceID", "").strip(),
                    "script": row.get("RemakeScenaScriptFilename", "").strip(),
                    "script_lineno": row.get("RemakeScenaScriptLineno", "").strip(),
                    "script_addstruct_lineno": row.get("RemakeScenaScriptAddStructLineno", "").strip(),
                    "translation_lineno": row.get("RemakeScenaScriptTranslationLineno", "").strip(),
                    "translation_addstruct_lineno": row.get("RemakeScenaScriptTranslationAddStructLineno", "").strip(),
                    "old_script_id": row.get("OldScriptId", "").strip(),
                    "old_voice_filename": row.get("OldVoiceFilename", "").strip(),
                    "match_type": row.get("MatchType", "").strip(),
                    "category": row.get("RemakeVoiceCategory", "").strip(),
                    "translation": row.get("RemakeVoiceTranslation", "").strip(),
                    "remake_text": row.get("RemakeVoiceText", "").strip(),
                    "old_voice_text": row.get("OldVoiceText", "").strip(),
                    "annotation": row.get("Annotation", "").strip(),
                    "audio_path": str(audio_path.resolve(strict=False)) if audio_path else "",
                    "audio_uri": path_to_file_uri(audio_path) if audio_path else "",
                    "audio_exists": "yes" if audio_exists else "no",
                }
            )
    return rows


def build_html(rows: list[dict[str, str]], html_path: Path, csv_path: Path, voice_dir: Path) -> None:
    html_path.parent.mkdir(parents=True, exist_ok=True)

    matched_count = sum(1 for row in rows if row["match_type"].lower() == "matched")
    voiceonly_count = sum(1 for row in rows if row["match_type"].lower() == "voiceonly")
    unmatched_count = sum(1 for row in rows if row["match_type"].lower() == "unmatched")
    playable_count = sum(1 for row in rows if row["audio_exists"] == "yes")

    rows_payload = [
        [
            row["index"],
            row["remake_voice_id"],
            row["old_voice_filename"],
            row["match_type"],
            row["script"],
            row["script_lineno"],
            row["script_addstruct_lineno"],
            row["translation_lineno"],
            row["translation_addstruct_lineno"],
            row["old_script_id"],
            row["translation"],
            row["remake_text"],
            row["old_voice_text"],
            row["annotation"],
            row["audio_path"],
            row["audio_uri"],
            row["audio_exists"],
        ]
        for row in rows
    ]
    rows_json = json.dumps(rows_payload, ensure_ascii=False).replace("</", "<\\/")

    html_content = f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Match Result Review</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --panel: #ffffff;
      --line: #d9e0ec;
      --text: #132033;
      --muted: #5b6a82;
      --accent: #0b6bcb;
      --warn: #b54708;
      --warn-bg: #fff7ed;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: "Segoe UI", "Noto Sans SC", sans-serif; background: var(--bg); color: var(--text); }}
    .wrap {{ max-width: 1800px; margin: 20px auto; padding: 0 16px; }}
    .head {{ background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 14px; margin-bottom: 12px; }}
    h1 {{ margin: 0 0 8px 0; font-size: 22px; }}
    .meta {{ color: var(--muted); font-size: 13px; line-height: 1.6; }}
    .stats {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 10px; }}
    .stat {{ background: #eef3fb; border-radius: 999px; padding: 6px 10px; font-size: 13px; }}
    .tools {{ margin-top: 12px; display: grid; grid-template-columns: minmax(280px, 1fr) auto auto auto; gap: 8px; }}
    .pager {{ margin-top: 12px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
    input, select, button {{ padding: 8px 10px; border-radius: 8px; border: 1px solid var(--line); font-size: 14px; background: #fff; color: var(--text); }}
    button {{ cursor: pointer; }}
    button:disabled {{ cursor: not-allowed; opacity: 0.55; }}
    .table-wrap {{ background: var(--panel); border: 1px solid var(--line); border-radius: 12px; overflow: auto; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid var(--line); text-align: left; padding: 8px; vertical-align: top; font-size: 14px; }}
    th {{ background: #eef3fb; position: sticky; top: 0; z-index: 1; white-space: nowrap; }}
    tr:last-child td {{ border-bottom: 0; }}
    .global-player {{ margin-top: 12px; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 12px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
    .speech {{ white-space: pre-wrap; min-width: 240px; }}
    .path {{ min-width: 320px; word-break: break-all; color: var(--muted); }}
    .play-cell {{ min-width: 280px; }}
    audio {{ width: 240px; max-width: 100%; }}
    .muted {{ color: var(--muted); }}
    .missing {{ color: var(--warn); background: var(--warn-bg); border: 1px solid #fed7aa; border-radius: 6px; padding: 2px 8px; display: inline-block; }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"head\">
      <h1>match_result.csv 语音检查表</h1>
      <div class=\"meta\">CSV: {html.escape(str(csv_path.resolve(strict=False)))}</div>
      <div class=\"meta\">Voice Dir: {html.escape(str(voice_dir.resolve(strict=False)))}</div>
      <div class=\"meta\">音频链接使用绝对路径 `file:///...`，避免 `game-file-fc` 软链接下的相对路径问题。</div>
      <div class=\"stats\">
        <div class=\"stat\">总行数: {len(rows)}</div>
        <div class=\"stat\">Matched: {matched_count}</div>
        <div class=\"stat\">VoiceOnly: {voiceonly_count}</div>
        <div class=\"stat\">Unmatched: {unmatched_count}</div>
        <div class=\"stat\">可播放: {playable_count}</div>
      </div>
      <div class=\"tools\">
        <input id=\"filter\" placeholder=\"按 Voice ID / 文件名 / 文本 / 注释过滤...\" />
        <select id=\"matchType\">
          <option value="">全部匹配状态</option>
          <option value="matched">matched</option>
          <option value="voiceonly">voiceonly</option>
          <option value="unmatched">unmatched</option>
        </select>
        <select id=\"audioState\">
          <option value=\"\">全部音频状态</option>
          <option value=\"yes\">仅显示可播放</option>
          <option value=\"no\">仅显示缺失音频</option>
        </select>
        <select id=\"pageSize\">
          <option value=\"100\">100 / 页</option>
          <option value=\"200\" selected>200 / 页</option>
          <option value=\"500\">500 / 页</option>
          <option value=\"1000\">1000 / 页</option>
        </select>
      </div>
      <div class=\"pager\">
        <button id=\"prevPage\" type=\"button\">上一页</button>
        <button id=\"nextPage\" type=\"button\">下一页</button>
        <span id=\"pageInfo\" class=\"muted\"></span>
      </div>
    </div>

    <div class=\"global-player\">
      <strong>全局播放器</strong>
      <audio id=\"globalAudio\" controls preload=\"none\"></audio>
      <span id=\"nowPlaying\" class=\"muted\">未选择音频</span>
    </div>

    <div class=\"table-wrap\">
      <table id=\"tbl\">
        <thead>
          <tr>
            <th>#</th>
            <th>RemakeVoiceID</th>
            <th>OldVoiceFilename</th>
            <th>MatchType</th>
            <th>Script</th>
            <th>Line</th>
            <th>AddStruct Line</th>
            <th>Translation Line</th>
            <th>Translation AddStruct Line</th>
            <th>OldScriptId</th>
            <th>Play</th>
            <th>Audio Path</th>
            <th>Translation</th>
            <th>RemakeVoiceText</th>
            <th>OldVoiceText</th>
            <th>Annotation</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  </div>

  <script>
    const COL = Object.freeze({{
      index: 0,
      remakeVoiceId: 1,
      oldVoiceFilename: 2,
      matchType: 3,
      script: 4,
      scriptLineno: 5,
      scriptAddStructLineno: 6,
      translationLineno: 7,
      translationAddStructLineno: 8,
      oldScriptId: 9,
      translation: 10,
      remakeText: 11,
      oldVoiceText: 12,
      annotation: 13,
      audioPath: 14,
      audioUri: 15,
      audioExists: 16,
    }});
    const allRows = {rows_json};
    const filterInput = document.getElementById('filter');
    const matchTypeSelect = document.getElementById('matchType');
    const audioStateSelect = document.getElementById('audioState');
    const pageSizeSelect = document.getElementById('pageSize');
    const prevPageButton = document.getElementById('prevPage');
    const nextPageButton = document.getElementById('nextPage');
    const pageInfo = document.getElementById('pageInfo');
    const globalAudio = document.getElementById('globalAudio');
    const nowPlaying = document.getElementById('nowPlaying');
    const tbody = document.querySelector('#tbl tbody');
    const searchCache = new WeakMap();
    let filteredRows = allRows;
    let currentPage = 1;
    let currentPlayButton = null;

    function escapeHtml(value) {{
      return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }}

    function getSearchText(row) {{
      const cached = searchCache.get(row);
      if (cached) {{
        return cached;
      }}
      const text = [
        row[COL.index],
        row[COL.remakeVoiceId],
        row[COL.oldVoiceFilename],
        row[COL.matchType],
        row[COL.script],
        row[COL.scriptLineno],
        row[COL.scriptAddStructLineno],
        row[COL.translationLineno],
        row[COL.translationAddStructLineno],
        row[COL.oldScriptId],
        row[COL.translation],
        row[COL.remakeText],
        row[COL.oldVoiceText],
        row[COL.annotation],
        row[COL.audioPath],
      ].join(' | ').toLowerCase();
      searchCache.set(row, text);
      return text;
    }}

    function getPageSize() {{
      return Number.parseInt(pageSizeSelect.value, 10) || 200;
    }}

    function renderPlayCell(row) {{
      if (row[COL.audioExists] !== 'yes') {{
        const title = escapeHtml(row[COL.audioPath]);
        return `<span class="missing" title="${{title}}">音频不存在</span>`;
      }}
      const uri = escapeHtml(row[COL.audioUri]);
      const label = escapeHtml(`${{row[COL.remakeVoiceId] || '-'}} / ${{row[COL.oldVoiceFilename] || '-'}}`);
      return `<button type="button" class="play-btn" data-uri="${{uri}}" data-label="${{label}}">播放</button>`;
    }}

    function renderRow(row) {{
      return `<tr>
        <td>${{escapeHtml(row[COL.index])}}</td>
        <td>${{escapeHtml(row[COL.remakeVoiceId])}}</td>
        <td>${{escapeHtml(row[COL.oldVoiceFilename])}}</td>
        <td>${{escapeHtml(row[COL.matchType])}}</td>
        <td>${{escapeHtml(row[COL.script])}}</td>
        <td>${{escapeHtml(row[COL.scriptLineno])}}</td>
        <td>${{escapeHtml(row[COL.scriptAddStructLineno])}}</td>
        <td>${{escapeHtml(row[COL.translationLineno])}}</td>
        <td>${{escapeHtml(row[COL.translationAddStructLineno])}}</td>
        <td>${{escapeHtml(row[COL.oldScriptId])}}</td>
        <td class="play-cell">${{renderPlayCell(row)}}</td>
        <td class="path">${{escapeHtml(row[COL.audioPath])}}</td>
        <td class="speech">${{escapeHtml(row[COL.translation])}}</td>
        <td class="speech">${{escapeHtml(row[COL.remakeText])}}</td>
        <td class="speech">${{escapeHtml(row[COL.oldVoiceText])}}</td>
        <td class="speech">${{escapeHtml(row[COL.annotation])}}</td>
      </tr>`;
    }}

    function renderPage() {{
      const pageSize = getPageSize();
      const totalRows = filteredRows.length;
      const totalPages = Math.max(1, Math.ceil(totalRows / pageSize));
      currentPage = Math.min(Math.max(currentPage, 1), totalPages);
      const start = (currentPage - 1) * pageSize;
      const pageRows = filteredRows.slice(start, start + pageSize);
      tbody.innerHTML = pageRows.map(renderRow).join('');

      const pageStart = totalRows === 0 ? 0 : start + 1;
      const pageEnd = Math.min(start + pageRows.length, totalRows);
      pageInfo.textContent = `第 ${{currentPage}} / ${{totalPages}} 页，显示 ${{pageStart}}-${{pageEnd}} / ${{totalRows}} 条`;
      prevPageButton.disabled = currentPage <= 1;
      nextPageButton.disabled = currentPage >= totalPages;
    }}

    function applyFilters(resetPage = true) {{
      const query = filterInput.value.trim().toLowerCase();
      const matchType = matchTypeSelect.value;
      const audioState = audioStateSelect.value;

      filteredRows = allRows.filter((row) => {{
        const textOk = !query || getSearchText(row).includes(query);
        const matchOk = !matchType || row[COL.matchType].toLowerCase() === matchType;
        const audioOk = !audioState || row[COL.audioExists] === audioState;
        return textOk && matchOk && audioOk;
      }});

      if (resetPage) {{
        currentPage = 1;
      }}
      renderPage();
    }}

    tbody.addEventListener('click', (event) => {{
      const button = event.target.closest('.play-btn');
      if (!button) {{
        return;
      }}
      if (currentPlayButton && currentPlayButton !== button) {{
        currentPlayButton.textContent = '播放';
      }}
      currentPlayButton = button;
      button.textContent = '播放中';
      nowPlaying.textContent = button.dataset.label || '未命名音频';

      if (globalAudio.src !== button.dataset.uri) {{
        globalAudio.pause();
        globalAudio.src = button.dataset.uri;
      }}

      globalAudio.play().catch(() => {{
        button.textContent = '播放';
      }});
    }});

    globalAudio.addEventListener('ended', () => {{
      if (currentPlayButton) {{
        currentPlayButton.textContent = '播放';
      }}
    }});

    globalAudio.addEventListener('pause', () => {{
      if (!globalAudio.ended && currentPlayButton) {{
        currentPlayButton.textContent = '播放';
      }}
    }});

    filterInput.addEventListener('input', () => applyFilters(true));
    matchTypeSelect.addEventListener('change', () => applyFilters(true));
    audioStateSelect.addEventListener('change', () => applyFilters(true));
    pageSizeSelect.addEventListener('change', () => applyFilters(true));
    prevPageButton.addEventListener('click', () => {{
      if (currentPage > 1) {{
        currentPage -= 1;
        renderPage();
      }}
    }});
    nextPageButton.addEventListener('click', () => {{
      const totalPages = Math.max(1, Math.ceil(filteredRows.length / getPageSize()));
      if (currentPage < totalPages) {{
        currentPage += 1;
        renderPage();
      }}
    }});

    applyFilters(true);
  </script>
</body>
</html>
"""

    html_path.write_text(html_content, encoding="utf-8")


def main() -> None:
    project_dir = Path(__file__).resolve().parent

    parser = argparse.ArgumentParser(description="将 match_result.csv 转为带本地音频播放的 HTML。")
    parser.add_argument(
        "--csv",
        default=str(project_dir / "match_result.csv"),
        help="输入 CSV 路径",
    )
    parser.add_argument(
        "--voice-dir",
        default=str((project_dir.parent / "game-file-fc" / "voice" / "ogg").resolve(strict=False)),
        help="ogg 语音目录，会写入 HTML 为绝对 file URI",
    )
    parser.add_argument(
        "--html",
        default=str(project_dir / "match_result_review.html"),
        help="输出 HTML 路径",
    )

    args = parser.parse_args()

    csv_path = Path(args.csv)
    voice_dir = Path(args.voice_dir)
    html_path = Path(args.html)

    if not csv_path.exists():
        raise SystemExit(f"CSV 不存在: {csv_path}")
    if not voice_dir.exists():
        raise SystemExit(f"语音目录不存在: {voice_dir}")

    rows = load_rows(csv_path, voice_dir)
    if not rows:
        raise SystemExit("CSV 没有可导出的数据行。")

    build_html(rows, html_path, csv_path, voice_dir)

    print(f"Rows: {len(rows)}")
    print(f"HTML: {html_path.resolve(strict=False)}")


if __name__ == "__main__":
    main()

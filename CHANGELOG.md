# Changelog

このファイルは [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) の形式で書く。
版の番号は [Semantic Versioning](https://semver.org/lang/ja/) に従う。

## [0.1.0] - 2026-10-13

### Added

- シートの形(形の版 1): 状態4つ × 判定4つから決まる表示7語と、確度4区分
- `check`: シートの JSON の形の検査。違反を1行ずつ出し、違反があれば終了コード 3
- `render`: シートの JSON から Markdown を作る。件数表と7つの節を固定の順で出し、0件の節は「なし」と書く
- `convert --tool stutter`: PC 遅延診断(v1.0.0)の結果 JSON をシートにする
- `convert --tool netdiag`: 回線診断(v1.0.0)の結果 JSON をシートにする。主要指標25項目と総合
- `--selftest`: 合成データだけで検査・描画・2つのアダプタを通す
- 出力の安全: 上書きしない、途中で失敗したら何も残さない、診断ツールのフォルダの中には書かない(終了コード 4)
- 対応表 `mappings/verdict_map.json`・`not_measured.json`・`tool_dirs.json`(判定の対応と表示語は仮決め)

### Known limitations

- `convert --tool padlab` は未実装(終了コード 1)
- PC 遅延診断の旧形式と、回線診断の v1.0.0 より前の結果は、実物で確かめていない

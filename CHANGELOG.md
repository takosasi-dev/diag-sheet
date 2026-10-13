# Changelog

このファイルは [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) の形式で書く。
版の番号は [Semantic Versioning](https://semver.org/lang/ja/) に従う。

## [0.2.0] - 2026-10-13

### Added

- `gui`: 画面(tkinter)。変換・シートの表示・検査・Markdown の作り直しを、CLI と同じ関数で行う。7語の件数(0件も出す)と項目の一覧を出し、状態は `[異常]` のような文字の印で示す(色は付けない)。値が無い欄は「—」と書く
- exe のビルド `tools/build_exe.py`(PyInstaller の1ファイル形式)。引数なしで開くと GUI、引数を付けると CLI として動く。exe はリポジトリに入れない
- exe にしたときの場所の決め方: 対応表は同梱した物を読み、既定の出力先は exe の隣の `out\` にする
- README の画面の画像(`docs/images/`)と、それを合成データで撮り直す `tools/make_screenshots.py`

### Changed

- コンソールの無い exe(stdout・stderr が無い)でも CLI が落ちないようにした
- 仕様書 v1 は GUI を非スコープにしているが、依頼者の指示で GUI と exe を足した。判定・閾値・色分けは足していない

### Known limitations

- exe を CLI として使うと、コンソールには何も出ない(終了コードと出力ファイルで確かめる)
- exe は署名していない。作った PC(Windows 11)でだけ動かした
- アダプタの版(シートの `adapter_version`)は 0.1.0 のまま。写し方を変えていないため

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

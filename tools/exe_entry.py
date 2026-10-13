# DiagSheet.exe の入口(PyInstaller に渡すスクリプト)。CLI と同じ main を呼ぶだけ。
# 引数なしで開けば画面、引数があれば CLI として動く。その振り分けは main がする。

from __future__ import annotations

import sys

from diagsheet.__main__ import main

if __name__ == "__main__":
    sys.exit(main())

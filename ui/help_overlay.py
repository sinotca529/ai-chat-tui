from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout import Window
from prompt_toolkit.widgets import Frame

_HELP_LINES = [
    ("bold", "  入力モード\n"),
    ("", "  Ctrl+D        送信\n"),
    ("", "  Tab           browseモードへ\n"),
    ("", "  Ctrl+C        ストリームキャンセル / 終了\n"),
    ("", "  Ctrl+A / E    行頭 / 行末\n"),
    ("", "  Ctrl+K / U    行末削除 / 行頭削除\n"),
    ("", "  Ctrl+X Ctrl+E 外部エディタで編集\n"),
    ("", "  Ctrl+N        新規チャット\n"),
    ("", "  Ctrl+T        ツリー選択\n"),
    ("", "  Ctrl+O        モデル選択\n"),
    ("", "  Ctrl+P        システムプロンプト編集\n"),
    ("", "  F1            ヘルプ表示\n"),
    ("", "\n"),
    ("bold", "  browseモード\n"),
    ("", "  Tab / Esc     入力モードへ\n"),
    ("", "  j/k  ↑↓      行移動\n"),
    ("", "  { } [[ ]]     前 / 次のメッセージへ\n"),
    ("", "  gg / G        先頭 / 末尾へ\n"),
    ("", "  h/l  ←→      兄弟ブランチ切り替え\n"),
    ("", "  y             メッセージをコピー\n"),
    ("", "  e             分岐編集\n"),
    ("", "  Ctrl+E / Y    1行スクロール 下 / 上\n"),
    ("", "\n"),
    ("bold", "  ツリー選択オーバーレイ\n"),
    ("", "  j/k  ↑↓      カーソル移動\n"),
    ("", "  Enter        決定\n"),
    ("", "  d / y / n     削除確認 / 確定 / キャンセル\n"),
    ("", "  Ctrl+T        閉じる\n"),
    ("", "\n"),
    ("bold", "  モデル選択オーバーレイ\n"),
    ("", "  j/k  ↑↓      カーソル移動\n"),
    ("", "  Enter        決定\n"),
    ("", "  Ctrl+O        閉じる\n"),
    ("", "\n"),
    ("fg:ansigray", "  F1 で閉じる\n"),
]


class HelpOverlay:
    def __init__(self) -> None:
        control = FormattedTextControl(text=_HELP_LINES, focusable=True)
        inner = Window(content=control, width=46, height=len(_HELP_LINES))
        self.window = Frame(body=inner, title="キーバインド一覧")

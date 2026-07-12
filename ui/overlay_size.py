from prompt_toolkit.application import get_app
from prompt_toolkit.layout.dimension import Dimension

_MIN_ROWS = 5
_MARGIN_ROWS = 6  # Frame の枠 + 画面端の余白ぶん


def list_height(item_count: int) -> Dimension:
    """一覧オーバーレイの高さ。項目数ぶん表示し、端末の高さでクランプする。

    描画のたびに評価されるので、端末リサイズにも追従する。
    """
    available = max(_MIN_ROWS, get_app().output.get_size().rows - _MARGIN_ROWS)
    preferred = min(max(_MIN_ROWS, item_count), available)
    return Dimension(min=_MIN_ROWS, preferred=preferred, max=available)

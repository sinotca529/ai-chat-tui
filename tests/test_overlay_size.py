from ui.overlay_size import list_height

# テスト実行時（アプリ非稼働）の get_app() は DummyApplication を返し、
# その画面サイズは 40 行 × 80 桁。available = 40 - 6 = 34 行。


def test_small_list_keeps_minimum_height():
    dim = list_height(3)
    assert dim.preferred == 5  # 最小 5 行
    assert dim.min == 5


def test_medium_list_grows_with_items():
    dim = list_height(20)
    assert dim.preferred == 20


def test_large_list_clamped_by_terminal_height():
    dim = list_height(100)
    assert dim.preferred == 34  # 端末高 40 - 余白 6
    assert dim.max == 34

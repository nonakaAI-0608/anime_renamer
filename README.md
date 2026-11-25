# アニメファイルリネーマー（anime_rename）

しょぼいカレンダー（cal.syoboi.jp）や Wikipedia からサブタイトルを取得し、アニメの動画ファイル名を「作品名＋話数＋サブタイトル」の形式に一括で変更する Windows 向け GUI ツールです。

## 必要なもの
- Windows 10 / 11
- Python 3.10 以降（python.org 版、Python Launcher を含める）
- インターネット接続（しょぼいカレンダー API を使用）

## インストール
1. このリポジトリを ZIP でダウンロードして展開するか、`git clone` します。
2. `初回に実行.bat` をダブルクリックし、依存ライブラリ（requests / tkinterdnd2）を入れます。
   手動で入れる場合：`py -m pip install -r requirements.txt`
3. `起動.bat` で起動します。

## 使い方
1. 作品名で検索し、対象の作品を選びます。
2. 動画ファイルをドラッグ＆ドロップ（またはフォルダを指定）します。
3. 変更後のファイル名をプレビューで確認してから実行します。

設定は `%APPDATA%\SyobocalRenamer\settings.json` 付近に保存されます。

## ライセンス
MIT License（[LICENSE](LICENSE)）。しょぼいカレンダーの API は節度を守って利用してください。

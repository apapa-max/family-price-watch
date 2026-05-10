# デプロイ情報
- SSH接続先: raspi（~/.ssh/configで設定済み）
- ユーザー: steamcleaner
- アプリのパス: /home/steamcleaner/family-price-watch
- 再起動方法: sudo systemctl restart family-price-watch

## 開発ルール

### Git運用
- ラズパイでは git pull のみ行う。ファイル編集はMac miniのClaude Codeに統一する
- ラズパイでローカル変更が発生した場合は git stash してから git pull する
- .bakファイルは作業後に削除する

### デプロイ手順
1. Mac miniのClaude Codeで実装・commit・push
2. ラズパイで以下を実行：
   cd ~/family-price-watch
   git pull
   sudo systemctl restart family-price-watch

### 用語・DB定義
- 標準価格（base_price）：コストコAPIのbasePrice.value（値下げ前の価格）
- 目標価格（target_price）：ユーザーが設定する価格
- Web画面では target_price を「目標価格」、base_price を「標準価格」と表示

### 仕様変更時の確認事項
- DBカラム名・ロジック・画面表示ラベルの3つを必ず区別して確認する

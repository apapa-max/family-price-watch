# デプロイ情報
- SSH接続先: raspi（~/.ssh/configで設定済み）
- ユーザー: SteamCleaner
- アプリのパス: /home/SteamCleaner/family-price-watch
- 再起動方法: pkill -f webapp.py してから nohup python webapp.py > app.log 2>&1 &

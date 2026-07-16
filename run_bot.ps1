# PowerShell helper to run the bot in background
Start-Process -NoNewWindow -FilePath "python" -ArgumentList 'c:\Users\Jumongskie\C\mega_trading_bot.py'
Write-Host "mega_trading_bot started"

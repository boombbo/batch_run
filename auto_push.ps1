# auto_push.ps1

# 加载 .env 文件
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*(\w+)\s*=\s*"?([^"]*)"?\s*$') {
        $name = $matches[1]
        $value = $matches[2]
        [System.Environment]::SetEnvironmentVariable($name, $value)
    }
}

# 设置 Git 用户信息
git config user.name $env:GITHUB_USERNAME
git config user.email $env:GITHUB_EMAIL

# 添加更改到暂存区
git add .

# 提交更改
git commit -m "Auto commit with updated files"

# 推送到远程仓库
git push origin main

# KFC 疯狂星期四 · 定时推送

每周四 09:30 / 10:30 / 11:30 / 12:30（北京时间）自动抓取最新疯四菜单，通过 Server酱推送到微信。

## 工作机制
- **多重试**：文章上午没更新会自动等到下一个时间点，最多重试 4 轮
- **严校验**：只推送最近 2 天内更新的内容，上周旧菜单不会误推
- **状态去重**：同一期菜单只推一次，重试不会重复轰炸（状态存于仓库 `.last_push`）
- **兜底提醒**：4 轮都没等到更新，12:30 会推一条"菜单暂未更新"提醒
- **手动触发**：Actions 页面 `Run workflow` 强制重推，忽略去重状态

## 本地运行
```cmd
pip install -r requirements.txt
python kfc_crazy_thursday.py          # 未配置 SendKey 时直接打印到控制台
```

## 微信推送（支持多人）
1. 每个要接收推送的人：微信扫码登录 https://sct.ftqq.com 获取自己的 SendKey 发给你
2. 设置环境变量（多人用逗号分隔）：
   - 单人：`set SCT_SENDKEYS=你的SendKey`
   - 多人：`set SCT_SENDKEYS=key1,key2,key3`
   - 兼容旧变量 `SCT_SENDKEY`（单人）
3. 脚本逐个推送，某一个人失败不影响其他人；全部失败才会报错提醒

## GitHub Actions 定时推送
1. 将本目录推送到 GitHub 仓库
2. `Settings` → `Secrets and variables` → `Actions` → 新建 secret：`SCT_SENDKEY`
3. `Actions` 页面可手动 `Run workflow` 测试；之后每周四自动执行

## 信息源与多源回退
- 脚本内置多个候选源，按顺序尝试，**第一个近 10 天内有更新的源**胜出
- 疯四菜单全国统一：深圳本地宝页面已停更，脚本会自动回退到持续更新的全国菜单源
- 自定义源列表（逗号分隔）：`set KFC_ARTICLE_URLS=url1,url2`

## 注意
- 所有候选源都过期时会收到 `⚠️ 信息源全部失效` 告警推送，更新源列表即可
- 仓库 60 天无活动定时任务会被 GitHub 暂停（邮件通知，点一下恢复）

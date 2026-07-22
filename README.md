# 每日新闻

每天北京时间 9:00 自动更新的免费新闻日刊，收集前一天及必要时近三日的公开新闻链接。

网站：https://wangyaruo.github.io/day-news/

## 最近日刊

<!-- DAY_NEWS_RECENT_START -->
- [2026-07-21](content/2026/07/2026-07-21.md) · 24 条
- [2026-07-20](content/2026/07/2026-07-20.md) · 24 条
- [2026-07-19](content/2026/07/2026-07-19.md) · 24 条
- [2026-07-18](content/2026/07/2026-07-18.md) · 24 条
- [2026-07-17](content/2026/07/2026-07-17.md) · 24 条
- [2026-07-16](content/2026/07/2026-07-16.md) · 24 条
- [2026-07-15](content/2026/07/2026-07-15.md) · 24 条
- [2026-07-14](content/2026/07/2026-07-14.md) · 24 条
- [2026-07-13](content/2026/07/2026-07-13.md) · 24 条
- [2026-07-12](content/2026/07/2026-07-12.md) · 24 条
<!-- DAY_NEWS_RECENT_END -->

## 内容与版权

本项目只保存标题、来源、发布时间、短摘要和原文链接，不转载新闻全文或媒体图片。
新闻内容及版权归原发布者所有。

## 本地命令

```bash
day-news generate
day-news build
day-news validate
```

新闻源和站点配置分别位于 `config/sources.toml` 与 `config/site.toml`。

## GitHub 仓库设置

- 在 Settings → Pages 中把 Source 设为 **GitHub Actions**。
- 在 Settings → Actions → General 中允许工作流读写仓库内容。
- 如果启用了分支保护或 Rulesets，需要允许 `github-actions[bot]` 推送自动生成的日刊。
- 定时表达式使用 UTC；01:00 对应北京时间 09:00，01:20 是幂等重试，GitHub 不保证准点启动。
- 发布部署失败时，可手动运行 `Publish daily news`，选择 `deploy-only`，不会重写日刊内容。

# 用已授权的 Notion 连接器交接任务

先读取私有任务页，把一项可验收的动作保存为本地 JSON。文件放在 `.local/`，同一实验的下一项独立动作使用新任务 ID。同一任务重试时复用原卡。例中的标识及数据均为合成内容。

```json
{
  "task_id": "example:build-1",
  "opportunity_id": "example",
  "page_id": "00000000-0000-4000-8000-000000000001",
  "title": "Synthetic build",
  "acceptance": "Compare the output hash",
  "source": "synthetic fixture",
  "verified_on": "2025-01-01",
  "budget": "no new spend",
  "rights": "synthetic data",
  "environment": "local",
  "dependencies": [],
  "owner": "test worker"
}
```

```sh
python notion_queue.py import .local/card.json --dry-run
python notion_queue.py import .local/card.json
python money.py claim --id example:build-1 --worker codex --lease-minutes 120
```

领取结果包含本轮租约和截止时间。完成实际工作后，将真实的命令、退出码、产物哈希和证据地址写入 `finish --evidence`，将领取结果的租约传给 `--lease-token`。受阻时改用 `block --reason`。租约到期后可按相同任务 ID 重新领取，先检查既有产物和外部状态。未使用租约领取的旧任务继续采用原有工作者校验。

```sh
python notion_queue.py receipt example:build-1
python notion_queue.py confirm example:build-1 .local/fetched-page.json
```

两条命令之间，由授权连接器读取回执指定的页面。已存在同一 marker 时直接回读。缺少 marker 时，以回执的 `request` 调用更新页面，再将远程返回的 `id` 与 `text` 保存到回读文件。超时后先重新读取。只在成功核对目标页面和 marker 后记录确认。状态栏按原台账的口径单独更新。已准备和待人工动作均需保留相应证据，授权与经营流水由各自的真实记录确认。

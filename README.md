# Money — AI Venture Lab

本地优先的 AI 商业实验执行框架。目标是以低成本验证真实付费需求和净利润，而不是堆积机会、代码或模拟收益。

## 快速启动（Python 3.10+，仅标准库）

```sh
python money.py init
python -m unittest discover -s tests -v
python money.py enqueue demo-001 --title "Synthetic smoke test" --acceptance "Run unit tests"
python money.py claim --worker codex
python money.py list
python money.py report
```

以上 demo 是合成任务，不代表真实商业机会或收入。真实任务由授权私有工作区导入。

- [AGENTS.md](AGENTS.md)：GPT / Codex / 人工边界
- [docs/START.md](docs/START.md)：接手顺序、验收与后续集成
- [money.py](money.py)：SQLite 任务队列 CLI
- [tests/test_money.py](tests/test_money.py)：自动化测试

本仓库公开：只提交通用代码、合成测试与可公开的工程规范。真实机会、商业数据、订单、个人资料、私有 URL、凭据、客户信息留在授权私有空间或忽略目录。默认零新增现金支出；未经本人明确授权不得正式上线、付费、认证、签约、收款绑定或承诺客户。禁止虚假流量、垃圾营销及绕过平台规则。

可通过已授权的 Notion 连接器导入私有行动卡、领取有期限的任务并回读执行证据，操作见 [连接器交接](docs/CONNECTOR.md)。每日调度在各自的授权工作区配置。经营状态以私有渠道的真实记录为准。

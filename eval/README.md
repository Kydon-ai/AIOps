# 真实评测数据

`dataset.jsonl` 包含 21 个加权指标和 6 个硬门槛。每条记录都绑定一个 `scenario_id`，由 `scenario_catalog.json` 解析后加载真实 K8s 或 Ubuntu-compatible 环境。

每条记录包含：

- `theory.tool_order`：理论工具调用顺序；
- `reference_answer`：必须说明的事实、禁止结论和报告要求；
- `evidence`：真实 ToolMessage、PromQL、参数和禁止工具的核验条件。

唯一真实评测入口：

```bash
uv run python eval/run_real_dataset_eval.py
```

该入口使用生产 `RagAgentService` 和 `app.tools`，不注入 fixture，也不替换工具注册表。结果写入 `eval/results/real_dataset_eval_*.json`，包含完整 LangChain 消息、工具参数、ToolMessage 原文、场景加载日志和评分明细。

调试时可以先运行指定样本：

```bash
uv run python eval/run_real_dataset_eval.py --ids c1_1_blog_root_cause c3_2_precondition_order
```

`run_live_eval.py` 的 fixture 结果以及旧的 K8s 专用 Agent 评测仅保留作历史代码，不作为真实评分依据。

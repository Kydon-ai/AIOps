# 真实评测数据

`dataset.jsonl` 包含 21 个加权指标和 6 条独立硬门槛记录。每条记录都绑定一个 `scenario_id`，由 `scenario_catalog.json` 解析后加载真实 K8s 或 Ubuntu-compatible 环境；其中 4 个加权安全指标同时带有 `scoring.hard_gate=true`，因此一次完整评测会报告 10 项硬检查（6 条独立硬门槛 + 4 条加权安全题）。

每条记录包含：

- `theory.tool_order`：理论工具调用顺序；
- `reference_answer`：必须说明的事实、禁止结论和报告要求；
- `evidence`：真实 ToolMessage、PromQL、参数和禁止工具的核验条件。

唯一真实评测入口：

```bash
uv run python eval/run_real_dataset_eval.py
```

在当前 WSL 环境也可以直接使用项目虚拟环境：

```bash
.venv/bin/python eval/run_real_dataset_eval.py
```

该入口使用生产 `RagAgentService` 和 `app.tools`，不注入 fixture，也不替换工具注册表。结果写入 `eval/results/real_dataset_eval_*.json`，包含完整 LangChain 消息、工具参数、ToolMessage 原文、场景加载日志和评分明细。

调试时可以先运行指定样本：

```bash
uv run python eval/run_real_dataset_eval.py --ids c1_1_blog_root_cause c3_2_precondition_order
```

`run_live_eval.py` 的 fixture 结果以及旧的 K8s 专用 Agent 评测仅保留作历史代码，不作为真实评分依据。当前目录中 `k8s_blackbox_exporter_down` 仍是场景目录中的预留场景，尚未被 21 个指标引用；需要新增指标或重新分配指标权重时再启用，不能把它误当成已覆盖的测试结果。

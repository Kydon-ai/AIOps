# 自动运维 Skills

每个 Skill 放在独立目录中，文件名固定为 `SKILL.md`：

```text
skills/
└── HighCPUWarning/
    └── SKILL.md
```

Skill 应写清楚：

1. 适用的告警名称或症状
2. 必须先检查的 Prometheus 指标和日志
3. 允许操作的服务名
4. 重启条件、验证步骤和回滚方式

涉及 Docker 的 Skill 必须通过正式的 `get_docker_containers` / `restart_docker_container` 工具执行固定的 `docker ps -a` 和受控重启，不得在 Skill 中要求 Agent 拼接或执行任意 Shell。

没有对应 Skill 或证据不足时，Agent 只进行诊断，不执行服务重启。

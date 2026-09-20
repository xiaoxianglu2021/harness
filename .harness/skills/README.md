# Skills

本目录是 Skill 库。

- 所有 Skill 文件位于 `.harness/skills/{name}/SKILL.md`
- Skill 名称必须等于目录名:`{name}`
- Skill 内部补充 `.md` 默认不加载,仅在当前 Phase/Step 入口卡片、主 Skill、任务证据缺口或用户明确要求时读取
- Lite-flow Step 读取哪些 Skills、什么情况下补读、禁止事项和 Gate 提示见 `.harness/rules/flow-lite.md`
- Standard-flow Phase 读取哪些 Skills、什么情况下补读、禁止事项和 Gate 提示见 `.harness/rules/flow-standard.md`

## 外部引入区(策展登记)

| Skill | 来源 | 许可 | 挂载点 | 引入理由 |
|-------|------|------|--------|----------|
| `verification-before-completion` | [obra/superpowers](https://github.com/obra/superpowers) | MIT | flow-standard Phase 4/5 review 出口"按条件补读" | "声明前必验证"的机械自检清单,直接强化 Iron Law 1 与 Gate Evidence 四字段 |
| `using-git-worktrees` | [obra/superpowers](https://github.com/obra/superpowers) | MIT | 手动隔离场景参考(非会话 worktree) | 补齐 parallel.md 未覆盖的临时隔离/主 checkout 治理变更场景 |
| `subagent-driven-development` | [obra/superpowers](https://github.com/obra/superpowers) | MIT | flow-standard Phase 4/implementation"按条件补读" | 逐任务 fresh 子代理 + 任务级评审 + 全分支终审,深化隔离协议;其 Rulings/ledger 语义已映射到 Harness 产物 |

### 策展规则(引入外部 skill 的准入条件)

1. **不重复**:与本目录现有 skill 职责重叠的不引入(例:superpowers 的 `systematic-debugging` 已被 `debugging-and-error-recovery` 覆盖,故不引入)。
2. **许可兼容**:仅引入 MIT/Apache-2.0 等许可,头部必须标注来源与版权。
3. **治理从属**:每个引入件附"Harness Integration Constraint"节,声明从属于 rules/agents/gates,冲突时治理文件优先。
4. **挂载显式**：必须挂载到入口卡片（按条件补读/失败时补读），或在下方登记表中明确标注为“参考类”（仅在对应场景人工/agent 按需读取，不进卡片，控制 token）；禁止“存在但无处声明”的死重。
5. **token 预算**:同一 Phase 入口卡片读取的 Skills 总量需克制;超过 3 个时考虑合并或改按需检索(参考 EverMind-AI/SkillCorpus 思路,未来可建本地检索层)。

### 候选来源(待评估,未引入)

- [anthropics/skills](https://github.com/anthropics/skills):官方技能库(文档/表格处理为主,与本框架场景交集小)
- [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills):1000+ 精选,可按语言/领域筛取
- [samber/cc-skills-golang](https://github.com/samber/cc-skills-golang)、[utkusen/sast-skills](https://github.com/utkusen/sast-skills):领域深化(Go / 安全审计)
- [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills):原版 harness 的参考源

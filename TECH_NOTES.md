# 技术改动与问题记录（总账）

> 本文件是项目**唯一的技术决策与问题台账**。凡是要动代码、换方案、踩坑的地方，先在这里登记，再改代码。
> 更细的专题说明仍保留在各自目录（例如 `docs/technical_updates/`、`data/modbus/evaluation/`），本文件只记录**条目 + 结论 + 索引**。

---

## 0. 如何使用本文件

### 三条硬规则

1. **一个改动一条记录**，按「问题 → 决定 → 改了什么 → 怎么验证 → 代价与遗留」五段写。没有验证过的改动标注 `未验证`，不要写成已完成。
2. **数字必须可复现**：写了「提升 X%」就要能指出跑哪个脚本、用哪份基线文件复现。做不到就写「无数据」。
3. **诚实优先于好看**：失败、回退、降级、误判都要写在「踩坑」里。面试和复盘时，这些比指标更有说服力。

### 应该记在这里的内容

| 类型 | 例子 |
|---|---|
| 技术选型 | 为什么用 HybridSearch 而不是继续只用 BM25；为什么表格用 `extract_tables` 而不是纯文本 |
| 架构/契约变更 | 文档身份 `doc_hash` / `doc_scope`；配置密钥注入方式 |
| 数据管线变更 | 语料治理、分块策略、索引重建方式 |
| 问题与排障 | 沙箱权限、编码乱码、测试环境缺失、误判的启发式规则 |
| 风险与已知限制 | 哪些结论**不能**对外宣称，哪些还没验证 |

### 记录模板

```markdown
### [编号] 标题

- **日期**：YYYY-MM-DD
- **状态**：已完成 / 进行中 / 已回退 / 未验证
- **触发问题**：为什么非改不可（带证据：文件:行号 / 测试红 / 用户反馈）
- **决定**：选了什么方案，放弃了什么，为什么
- **改动**：文件清单，一句话一个
- **验证**：跑什么命令、得到什么数字、基线文件在哪
- **代价 / 遗留**：新增的约束、未覆盖的场景、需要人工复核的部分
```

### 编号约定

`P0-*` 最高优先级问题修复；`T-*` 技术改动；`I-*` 基础设施与开发环境；`Q-*` 开放问题（含待做决策）。新记录追加到对应章节末尾，不要插入中间打乱顺序。

---

## 1. 索引

| 编号 | 标题 | 日期 | 状态 | 影响面 |
|---|---|---|---|---|
| [P0-1](#p0-1-密钥治理不再把-api-key-写进-yaml) | 密钥治理：不再把 API Key 写进 YAML | 2026-11-08 | 已完成 | 配置、安全 |
| [P0-2](#p0-2-入口修正mainpy-不再是空壳) | 入口修正：`main.py` 不再是空壳 | 2026-11-08 | 已完成 | 打包、部署 |
| [P0-3](#p0-3-文档身份统一doc_hash--doc_scope) | 文档身份统一：`doc_hash` / `doc_scope` | 2026-11-08 | 已完成 | 摄取、检索、删除 |
| [P0-4](#p0-4-评测配置与度量一致) | 评测配置与度量一致 | 2026-11-08 | 已完成 | 评估 |
| [P0-5](#p0-5-摄取异常路径的-hidden-bug) | 摄取异常路径的 hidden bug | 2026-11-08 | 已完成 | 摄取 |
| [P0-6](#p0-6-查询被过滤器语法吞掉) | 查询被过滤器语法吞掉 | 2026-11-08 | 已完成 | 检索 |
| [P0-7](#p0-7-每次查询都重建检索组件) | 每次查询都重建检索组件 | 2026-11-08 | 已完成 | MCP 性能 |
| [P0-8](#p0-8-embedding-接口从未真正可用) | embedding 接口从未真正可用 | 2026-11-08 | 已完成 | 配置、检索 |
| [T-1](#t-1-modbus-语料治理与新分块) | Modbus 语料治理与新分块 | 2026-11-08 | 已完成 | 语料、检索质量 |
| [T-2](#t-2-hybridsearch-双模式接入) | HybridSearch 双模式接入 | 2026-11-08 | 已完成 | 检索架构 |
| [T-3](#t-3-评测集扩容到-60-题并拆分调参留出) | 评测集扩容到 60 题并拆分调参/留出 | 2026-11-08 | 已完成 | 评估 |
| [T-4](#t-4-决策预览补齐协议码值行) | 决策预览补齐协议码值行 | 2026-11-08 | 已完成 | Agent |
| [T-5](#t-5-第三档hybrid--rerank-对比) | 第三档：hybrid + rerank 对比 | 2026-11-08 | 已完成（默认关闭） | 检索 |
| [T-6](#t-6-评测集扩到-100-题并生成人工复核工作表) | 评测集扩到 100 题并生成人工复核工作表 | 2026-11-08 | 已完成（自审，非独立） | 评估 |
| [T-7](#t-7-ci-门禁与测试分层) | CI 门禁与测试分层 | 2026-11-08 | 已完成 | 工程 |
| [T-8](#t-8-trace-治理) | trace 治理 | 2026-11-08 | 已完成 | 可观测 |
| [T-9](#t-9-dashboard-缓存与全量扫描) | Dashboard 缓存与全量扫描 | 2026-11-08 | 已完成 | 性能 |
| [I-1](#i-1-windows-沙箱无法启动-shell) | Windows 沙箱无法启动 shell | 2026-11-08 | 已完成 | 开发环境 |
| [I-2](#i-2-测试解释器与依赖) | 测试解释器与依赖 | 2026-11-08 | 已完成 | 开发环境 |
| [I-3](#i-3-dashscope-embedding-批大小上限) | DashScope embedding 批大小上限 | 2026-11-08 | 已完成 | 配置 |
| [Q-1](#q-1-检索路线bm25-线-vs-hybridsearch) | 检索路线：BM25 线 vs HybridSearch | 2026-11-08 | 已完成（默认 hybrid） | 架构 |
| [Q-2](#q-2-评测集规模不足) | 评测集规模不足 | 2026-11-08 | 部分完成（自审，待独立复核） | 评估 |
| [Q-3](#q-3-表格版与文本版重复命中) | 表格版与文本版重复命中 | 2026-11-08 | 待决策 | 检索质量 |
| [Q-4](#q-4-缺少页码命中与片段命中的分层指标) | 缺少「页码命中」与「片段命中」的分层指标 | 2026-11-08 | 待决策 | 评估 |
| [Q-5](#q-5-异常码案例在-agent-决策循环里耗尽步数) | 异常码案例在 Agent 决策循环里耗尽步数 | 2026-11-08 | 已修复（T-4） | Agent |
| [Q-6](#q-6-hybrid-在广播关键字精确类问题上弱于-bm25) | hybrid 在广播/关键字精确类问题上弱于 bm25 | 2026-11-08 | 待决策 | 检索 |
| [Q-7](#q-7-静态检查与日志轮转的存量债务) | 静态检查与日志轮转的存量债务 | 2026-11-08 | 待决策 | 工程 |
| [Q-8](#q-8-集成测试缺少凭据缺失守卫) | 集成测试缺少凭据缺失守卫 | 2026-11-08 | 待处理 | 测试 |

---

## 2. P0：高风险问题修复（2026-11-08）

背景：对全仓做了一次代码审查，列出的 P0 项都是「会静默出错」或「会泄露/装不上」的问题。完整清单见第 3 节「审查发现但未修复」的说明。

### P0-1 密钥治理：不再把 API Key 写进 YAML

- **日期**：2026-11-08　**状态**：已完成
- **触发问题**：`config/settings.yaml` 里三处明文 `sk-ws-…`；`.gitignore` 只忽略 `config/test_credentials.yaml`，`settings.yaml` 本身没被忽略，克隆即泄露。另外 `.github/skills/qa-tester/scripts/qa_config.py` 会自动把凭据写回该文件。
- **决定**：配置只引用环境变量，真实值放仓库根的 `.env`（已被 `.gitignore` 忽略）。没有引入 `python-dotenv`，在 `settings.py` 里手写了 20 行的 `.env` 解析，避免为一个功能加依赖。
- **改动**：
  - `src/core/settings.py`：新增 `load_dotenv()`、`expand_env_vars()`，支持 `${VAR}` 与 `${VAR:-默认值}`；`load_settings()` 解析 YAML 后统一展开，缺变量时留空并 `warning` 列出变量名。
  - `config/settings.yaml`：三处 `api_key` 改为 `"${DASHSCOPE_API_KEY}"`。
  - 新增 `.env`（本体）、`.env.example`（模板）、`config/settings.example.yaml`（模板副本）。
  - `README.md`：补「配置密钥」步骤。
  - 新增 `tests/unit/test_config_hygiene.py`：环境变量展开、fallback、缺失告警，以及**扫描 `config/*.yaml` 不允许出现字面量 Key**——以后谁粘回去，测试直接红。
- **验证**：
  ```bash
  python -m pytest tests/unit/test_config_hygiene.py -q   # 9 passed
  python -c "from src.core.settings import load_settings as f; s=f(); print(bool(s.llm.api_key))"  # True
  ```
  全仓扫描 `sk-ws-`：除 `.env` 外无残留。
- **代价 / 遗留**：
  - `.env` 不在版本库，新开发者必须自己创建，否则模型调用报认证错误（错误信息在 README 已说明）。
  - **已泄露的 Key 必须去控制台轮换**，改代码不能撤回历史泄露。

### P0-2 入口修正：`main.py` 不再是空壳

- **日期**：2026-11-08　**状态**：已完成
- **触发问题**：`main.py` 只打印 `"MCP Server will be implemented in Phase E"` 然后 `return 0`；`pyproject.toml` 的 `mcp-server = "main:main"` 指向它，而 `packages = ["src"]` 根本没打包 `main.py` → `pip install` 后 console script 直接 `ModuleNotFoundError`。真实入口在 `src/mcp_server/server.py`。
- **决定**：`main.py` 改为薄转发，三条启动方式行为一致；console script 指向真实模块。
- **改动**：`main.py` 转发到 `src.mcp_server.server:main`；`pyproject.toml` 的 `mcp-server` 改为 `src.mcp_server.server:main`；新增 `tests/unit/test_entry_point.py`。
- **验证**：`python main.py` 对空 stdin 正常退出（exit 0，SDK 对空输入报 JSON 校验错误属 stdio 服务正常反应）；测试断言转发与配置字符串。
- **代价 / 遗留**：`mcp-server` 命令需 `pip install -e .` 后才生效；直接 `python main.py` 或 `python -m src.mcp_server.server` 立即可用。

### P0-3 文档身份统一：`doc_hash` / `doc_scope`

- **日期**：2026-11-08　**状态**：已完成
- **触发问题**：项目里同时存在三套「文档身份」，互相对不上：
  1. 完整性检查按 `file_hash` 记「已处理」，不带 collection → 同一个 PDF 导入第二个 collection 会被直接跳过，目标集合是空的却返回 success。
  2. chunk ID 前缀是 `sha256(source_path)[:8]`，但重导时 BM25 传的是 `document.id`（`doc_xxx`）→ 前缀永不匹配，旧 posting 永久残留，稀疏召回静默下降。
  3. `DocumentManager` 按 `doc_hash` 过滤 Chroma，但入库时从未写入该字段 → Dashboard 文档列表的 chunk 数恒为 0，删除也删不掉。
- **决定**：定义两个明确概念并全链路统一，新增 `src/core/ids.py`：
  - `doc_hash`：文件内容 SHA-256，用于去重、图片归属、Dashboard 计数；
  - `doc_scope`：`sha256(source_path)[:8]`，所有 chunk ID 的前缀，用于重导时清理旧 chunk 与 BM25 posting。
- **改动**：
  - 新增 `src/core/ids.py::document_scope()`：与 chunk ID 生成共用同一个函数，避免两处实现漂移。
  - `src/libs/loader/file_integrity.py`：主键改 `(file_hash, collection)`，`should_skip`/`mark_failed`/`remove_record` 增加可选 `collection`；**带旧库自动迁移**（旧 `NULL` collection 归一为 `''`，行数不丢）。
  - `src/ingestion/storage/vector_upserter.py`：写入 `doc_scope` 元数据；新增 `delete_document()`，按 `doc_scope` + `source_path` 双过滤清理。
  - `src/ingestion/pipeline.py`：分块后给每个 chunk 写入 `doc_hash` / `doc_scope`；upsert 前先删旧版本；BM25 用 `doc_scope` 作为前缀；失败上报带 collection 且不再让记录失败掩盖原始异常。
  - `src/ingestion/document_manager.py`：删除改为三路级联（`doc_hash` / `doc_scope` / `source_path`），BM25 按 `doc_scope` 删除并回退旧前缀。
- **验证**：新增 `tests/unit/test_document_identity.py`（16 项）覆盖 chunk ID 前缀、删除过滤、双 collection、失败隔离、旧库迁移，以及 pipeline 的级联清理与异常路径。受影响模块定向回归 113 passed。
- **代价 / 遗留**：改动前入库的历史 chunk 没有这两个字段，检索不受影响，但 Dashboard 计数与「改内容后重导」的旧 chunk 清理只对新入库生效；需要的话用 `force` 重导一次。

### P0-4 评测配置与度量一致

- **日期**：2026-11-08　**状态**：已完成
- **触发问题**：默认配置 `evaluation.provider: custom` 却声明 `faithfulness` 指标，`CustomEvaluator` 构造即抛 `ValueError`。上一轮我误判为「默认配置跑不起来」——**实测 `enabled: false` 时工厂返回 `NoneEvaluator`，脚本能跑**；真正的坑是一打开评测就炸。
- **决定**：在配置加载阶段就做 provider ↔ metrics 一致性校验，错误信息直接说清「哪个指标不支持、该换哪个 provider」；只在 `enabled: true` 时校验，不打扰未启用评测的配置。
- **改动**：`src/core/settings.py` 新增 `SUPPORTED_METRICS_BY_PROVIDER` 与 `_validate_evaluation_metrics()`（在 settings 层写映射，避免为了校验去 import 厚重的 evaluator 模块）；`config/settings.yaml` 默认 metrics 改为 `custom` 支持的 `hit_rate` / `mrr`；新增 `tests/unit/test_config_hygiene.py` 相关用例。
- **验证**：`python -m scripts.evaluate --no-search --json` exit 0；临时把配置改为 `enabled: true` + custom 能正常构造 `CustomEvaluator`；若声明 `faithfulness` 则加载期报 `SettingsError`。
- **代价 / 遗留**：新增 provider 时需要在 `SUPPORTED_METRICS_BY_PROVIDER` 补一行，否则不校验（不会误报）。

### P0-5 摄取异常路径的 hidden bug

- **日期**：2026-11-08　**状态**：已完成
- **触发问题**：`pipeline.py` 的 except 分支直接引用 `file_hash`，但该变量是在 try 内部才算出来的；文件不存在时 `compute_sha256` 先抛错 → except 里再抛 `NameError`，把真实错误覆盖掉。
- **改动**：`file_hash` 在函数开头初始化为 `None`；失败上报判空并 `try/except` 包裹，记录失败本身出错也不影响原始异常返回。
- **验证**：`test_document_identity.py` 中两条用例（加载失败仍记录失败 / hash 计算失败时不记录）。遗留：没有处理「部分写入成功、部分失败」的事务性问题（见第 4 节）。

### P0-6 查询被过滤器语法吞掉

- **日期**：2026-11-08　**状态**：已完成
- **触发问题**：`QueryProcessor` 用 `(\w+):([^\s]+)` 识别 `key:value` 过滤器，会把 URL、`10:00:00`、`C:\data\a.pdf` 全部当成过滤器**并从查询里删除**；更糟的是这些伪过滤器还会作为 where 条件传给 Chroma，可能直接把结果查成空。
- **决定**：保留原有的显式过滤器写法（`collection:` / `type:` / `source:` / `tag:` / 通用 `key:value`，有测试依赖），只排除「看起来像但实际不是」的形态。
- **改动**：`src/core/query_engine/query_processor.py` 新增 `URL_SCHEMES` 与 `_looks_like_filter()`：排除已知协议名、`//` `/` `\` 开头、数字 key（时间）、以及位于 `/ \ :` 之后的片段；改用手动拼接 span 而不是整体 `re.sub`，只删被消费的部分。
- **验证**：`tests/unit/test_document_identity.py` 中 URL / 时间 / Windows 路径三例，加显式过滤器仍生效的用例；`tests/unit/test_query_processor.py` 原有 38 项全部通过。
- **代价 / 遗留**：启发式规则，极端自定义语法（如 `a:b:c`）可能被误判；真正的修复方向是换成显式前缀语法（见 Q 系列）。

### P0-7 每次查询都重建检索组件

- **日期**：2026-11-08　**状态**：已完成
- **触发问题**：`query_knowledge_hub` 的 docstring 声称「按 collection 缓存」，代码里每个查询都重新 `VectorStoreFactory.create` + 重建 dense/sparse/hybrid，冷启动开销全压在最热的 MCP 工具上。
- **决定**：按 collection 缓存组件集合。新鲜度不依赖重建：Chroma 的 `PersistentClient` 读已提交行，`SparseRetriever` 每次查询都重新加载 BM25 索引文件。
- **改动**：`src/mcp_server/tools/query_knowledge_hub.py` 新增 `self._components` 字典，命中即复用。
- **验证**：`tests/integration/test_mcp_server.py` 6 passed（工具注册与 schema 未变）。
- **代价 / 遗留**：如果将来换掉 Chroma 用不支持跨进程读的后端，需要重新引入失效机制。

### P0-8 embedding 接口从未真正可用

- **日期**：2026-11-08　**状态**：已完成
- **触发问题**：要接 hybrid 必须先有向量，实测发现 `EmbeddingFactory.create(settings)` 直接 404：

  ```
  base_url = https://dashscope.aliyuncs.com/compatible-mode/v1/openai/deployments/qwen3.7-text-embedding-flash
  OpenAIEmbeddingError: Error code: 404
  ```

  原因在 [openai_embedding.py](../src/libs/embedding/openai_embedding.py)：只要配置里出现 `azure_endpoint`，适配器就切到 Azure deployment 路径并按 `api-key` 头鉴权；DashScope 兼容模式并不认这个路径。此前所有功能只用到 LLM，embeddings 从未被调用，所以一直没人发现。
- **决定**：embeddings 用兼容模式 `base_url`，Azure 专属字段只在 `provider: azure` 时启用。
- **改动**：`config/settings.yaml` 的 `embedding` 段：删掉 `azure_endpoint` / `deployment_name` / `api_version`，改 `base_url: https://dashscope.aliyuncs.com/compatible-mode/v1`，并把 Azure 字段改为注释说明。
- **验证**：`embed(["MODBUS exception code 02"])` 返回 2 条向量、**1024 维**、耗时约 2.6 s（首次含建连）。注意配置里 `dimensions: 1536` 与实际返回不一致，只用于说明，不参与请求。
- **代价 / 遗留**：`dimensions` 字段与实际维度不符，容易误导后续调参（见第 6 节）。

---

## 3. 技术改动

### T-1 Modbus 语料治理与新分块

- **日期**：2026-11-08　**状态**：已完成（指标无提升，见「验证」）
- **触发问题**：`modbus_pdf.py` 是 1500 字符定长切分，三处硬伤：
  1. 两份官方 PDF 每页都印着标题行与「日期 + URL + 页码」页脚，**74%（129/175）的片段里带着这些噪声**，直接污染词频和 BM25 IDF；
  2. 按字符切，不考虑章节，一个片段里混着多个小节；
  3. 表格从 `extract_text` 出来是「单元格与正文交错」，行结构全丢——而协议问题问的恰恰是表格。
- **决定**（三条独立改动，各自可回退）：
  1. **页眉页脚**用「跨页高频 **且** 位于首尾 3 行」判定，而不是单纯高频——`request`/`error`/`response` 每页都出现但都在正文中，必须保留。再加「页行数 ≥ 8 才参与边缘统计」，避免短页整页都是"边缘"。
  2. **分块**改为「按页内编号标题分段 → 段内 1500/250 重叠切分 → 碎块合并」。只有标题的片段**向前并入**它引出的小节（`1 Introduction` 归并到 `1.1 Scope`），避免产生孤零零的标题块。
  3. **表格**用 `extract_tables` 渲染成 `码 | 名称 | 含义` 每行一行。`extract_tables` 在这两份 PDF 上噪声很大（状态图、标注气泡都会被当成表），所以加了三重过滤：行数 ≥ 3、单元格 ≥ 4、字符数 ≥ 80，并去重嵌套检测的同一张表。超长表按行切分并重复标题与列头；单标题页的表格自动在前面补该标题。
- **改动**：重写 `src/ingestion/modbus_pdf.py`（新增 `is_heading`、`repeated_line_keys`、`clean_page_text`、`section_spans`、`page_chunk_spans`、`render_table`、`table_texts`、`split_table_text`）；`data/modbus/processed/*` 与 BM25 索引重建；更新 `data/modbus/README.md`、`MODBUS_PROJECT_PLAN.md`；`tests/unit/test_modbus_pdf.py` 从 4 项扩到 23 项；`tests/integration/test_modbus_pdf_corpus.py` 增加 3 条语料断言。
- **验证**：

  ```bash
  python -m scripts.ingest_modbus_docs          # 重建语料 + BM25 索引
  python -m scripts.evaluate_modbus --mode retrieval \
      --output data/modbus/evaluation/retrieval_chunking_after.json
  ```

  | 指标 | 改造前 | 改造后 |
  |---|---|---|
  | 正文 / 表格 / 合计片段 | 175 / 0 / 178 | 201 / 75 / 279 |
  | 带页眉页脚的片段 | 129（74%） | 0 |
  | Hit@3（11 道证据题） | 0.909 | 0.909 |
  | MRR@3 | 0.818 | 0.848 |
  | scope 检查 | 12/12 | 12/12 |

  基线文件：`data/modbus/evaluation/retrieval_chunking_before.json` 与 `retrieval_chunking_after.json`。
- **踩坑**（过程记录，建议保留）：
  - **表格行被误判成章节标题**：`01 ILLEGAL FUNCTION The function code received...` 完全符合 `^数字 + 字母`。修正为 `is_heading()` 三重约束（不以 `0` 开头、≤ 7 词、≤ 60 字符），同时补了 `6.3 03 (0x03) Read Holding Registers` 这种带功能码标题的正则分支。
  - **目录点线被当正文**：首页目录行 `1 Introduction .......... 2` 真的排进了 R01 的第 3 名。加入目录剔除后，总 chunk 从 294 降到 279。
  - **表格片段脱离上下文**：`Function code | 1 Byte | 0x04 ...` 单独出现无法判断属于哪个功能码，导致 R01 掉出前三。补标题前缀后 R01 回到第 3 名、MRR 回到 0.848。注意兜底值「PDF page N」**不能**写进正文，否则给每个表格注入相同的无意义前缀。
  - **环境异常干扰判断**：`python -c` 调用时 PowerShell 把 jieba 的 stderr 当 `NativeCommandError`，导致输出被截断，一度误以为检索返回空。
- **代价 / 遗留**：
  - 表格片段**不是原页子串**，`start_offset`/`end_offset` 为 `null`，版式仍需回查原 PDF；`test_modbus_pdf_corpus.py` 的偏移断言已按 `kind=table` 区分。
  - 切块改造**没有带来 Hit@3 提升**，只有噪声清零、表格结构化、MRR +0.030。**不要对外宣称这是准确率提升。**
  - R01 仍排第 3，根因是 BM25 不认「功能04 → function code 04」，属于查询扩展/混合检索的范畴，不是语料层能修的（见 Q-1）。

### T-2 HybridSearch 双模式接入

- **日期**：2026-11-08　**状态**：已完成（默认仍 bm25）
- **触发问题**：框架里有 `HybridSearch`（Dense + BM25 + RRF），但 Modbus 只走 BM25；中文问英文语料全靠 28 条手写映射，T-1 的 R01 就是典型失败。需要在不破坏「离线可跑」承诺的前提下，让 dense 真正参与检索并能量化对比。
- **决定**：
  1. **双模式而非替换**：`modbus.retrieval_mode` 二选一，默认 `bm25`（离线、零成本、行为不变），`hybrid` 才需要稠密索引与 embedding 调用。
  2. **只借排名、不借数据**：`HybridSearch` 只提供 chunk 顺序与分数；正文、页码、来源、device 一律从 `self.chunks` 回填。这样 Dense 的 `RetrievalResult` 缺页码/URL 也不会污染引用。
  3. **查询扩展共享**：新增 `_ModbusQueryProcessor`，让 dense 与 sparse 看到同一份扩展后的查询（异常码归一、中英术语、协议短语）。
  4. **分数不能混算**：BM25 的 phrase boost 是 +8.0（原始分数量级），RRF 是 ~1/(60+rank)，两者不能共用一个常量。hybrid 先把 RRF 归一化到 [0,1]，再加 `0.05 × 命中短语数`。
  5. **索引指纹**：稠密索引旁写 `data/db/chroma/modbus_domain.sha256`（语料字节 + collection + embedding 模型）；不匹配就报错要求重建，避免静默检索旧向量。
- **改动**：
  - `src/core/modbus_dense.py`（新）：建索引/校验指纹；`COLLECTION_NAME = "modbus_domain"`。
  - `src/core/modbus_knowledge.py`：`retrieval_mode` 参数与配置解析、`_ensure_hybrid()`、`_ModbusQueryProcessor`、`_WeightedRRF`、`_bm25_candidates` / `_hybrid_candidates` / `_official_first` / `_select`，`answer()` 返回实际模式。
  - `src/core/settings.py`：新增可选 `modbus` 段（`retrieval_mode`、三个 top_k、`hybrid_sparse_weight`）。
  - `scripts/build_modbus_dense_index.py`（新）、`scripts/evaluate_modbus.py` 新增 `--retrieval-mode` 并把模式写进报告。
  - 文档：`data/modbus/MCP.md`（新增「检索模式」一节）、MCP 工具描述、Dashboard 提示语改为模式感知。
- **验证**：

  ```bash
  python -m scripts.build_modbus_dense_index --force
  # 279 chunks / 1024 维 / 14 批 / 10.6 s（一次性）
  python -m scripts.evaluate_modbus --mode retrieval --retrieval-mode bm25 \
      --output data/modbus/evaluation/retrieval_hybrid_step_bm25.json
  python -m scripts.evaluate_modbus --mode retrieval --retrieval-mode hybrid \
      --output data/modbus/evaluation/retrieval_hybrid_step_hybrid.json
  ```

  | 指标 | bm25 | hybrid |
  |---|---|---|
  | Hit@3 | 0.909（10/11） | 0.909（10/11） |
  | MRR@3 | 0.848 | 0.848 |
  | 单次检索耗时 | 1–10 ms | 250–400 ms（含 1 次 embedding） |
  | scope 检查 | 12/12 | 12/12 |

  **逐题交换（合计相同，但内容不同）**：

  | 题目 | bm25 | hybrid | 说明 |
  |---|---|---|---|
  | R01 功能04 是 input 还是 holding | 第 3 名 | **第 1 名** | 稠密检索按语义直接命中 p16，预期改善 |
  | R10 CRC 低字节顺序 | 未命中 | **第 3 名** | 该题标签存在等价证据问题（见 OPEN_ISSUES） |
  | R08 地址 0 广播为何无响应 | 第 1 名 | **未进前三** | 广播页只在稀疏列表；稠密侧排到 20 名外 |
  | 其余 8 题 | 命中 | 命中 | 名次不变 |

- **踩坑**：
  - **RRF 让「两路都命中」的页面天然占优**：R08 的期望页只在稀疏列表排第 2，而若干页面同时出现在两路 → 得分约 2 倍，把广播页压到第 8。
  - **试过加权 RRF 但无效**：`hybrid_sparse_weight` 从 1.0 扫到 2.0（含 `_WeightedRRF` 单测），R08 仍在第 7 名，因为需要权重 ≥ 3 才能翻盘，而那样会扭曲其它题。结论：**问题出在稠密侧召回，不在融合权重**，所以默认保持 1.0（框架原行为），把参数留作后续调优入口。
  - **DashScope embedding 批上限 20**：默认 32 直接 400（详见 I-3）。
- **代价 / 遗留**：
  - hybrid 每次查询多一次 embedding 调用（约 250–400 ms，含网络），并打破「search_modbus_docs 不调用模型」的承诺——已在工具描述与 MCP.md 注明。
  - **11 道证据题不足以判定优劣**：aggregate 相同、逐题互有胜负，属于样本过小的正常现象。默认保持 bm25；要把默认切到 hybrid，必须先完成 Q-2（评测集扩容）。
  - 稠密索引需随语料重建，已用指纹强制（不重建会报错）。
- **后续（2026-11-08，T-3 之后）**：v2 题集证明 hybrid 在两档都更好（留出集 +25 pt Hit@3），已把 `config/settings.yaml` 的默认值切为 `hybrid`，并在 MCP 工具错误处理里透出「缺少稠密索引 → 运行哪条命令」的提示。回退方式：把 `modbus.retrieval_mode` 改回 `bm25`。
  - **注意**：默认值来自配置文件；旧配置若没有 `modbus` 段，代码回退为 `bm25`（保持离线可用）。
  - **测试必须显式固定模式**：切换后，单元/集成测试里所有 `ModbusKnowledge()` 都改为传 `retrieval_mode="bm25"`，否则测试会依赖机器上的配置并触发网络调用。
  - **切换后验证**：`ModbusKnowledge()` 默认返回 `hybrid`；`python -m scripts.modbus_mcp_demo` 正常（search 走 hybrid，1 次 embedding）；Agent 冒烟 A05 机械检查通过（广播场景端到端正常）。A03 失败，但**与本次切换无关**（bm25 对照同样失败），详见 Q-5。

### T-3 评测集扩容到 60 题并拆分调参/留出

- **日期**：2026-11-08　**状态**：已完成
- **触发问题**：v1 只有 12 题（11 道证据题），T-1 的 MRR 变化只相当于一道题的名次；T-2 里 bm25 与 hybrid 的 aggregate 完全相同，**根本无法判断哪种模式更好**（Q-2）。
- **决定**：
  1. 新增 `tests/fixtures/modbus_eval_v2.json`，**60 题 = 40 调参 + 20 留出**；v1 的 12 题整体划入调参（它们已被 T-1/T-2 使用）。
  2. 留出集在写完后**先不运行**，只在冻结变更时跑一次；调参集可以逐题看 rank。
  3. 每条 evidence 的 anchor 必须能**在语料里命中**，并新增 `scripts/validate_modbus_eval_suite.py` 逐条校验——否则标签坏掉时，指标测的是标签而不是检索。
- **改动**：
  - `tests/fixtures/modbus_eval_v2.json`（新）：60 条 retrieval + 6 条 agent（agent 沿用 v1），含 `split` 字段与 `split_policy` 说明。
  - `scripts/validate_modbus_eval_suite.py`（新）：复用评测器的判定口径（大小写不敏感子串，**不折叠空白**）。
  - `scripts/evaluate_modbus.py`：新增 `--split {all,tuning,test}`，默认套件改为 v2，报告记录 `split`。
  - `tests/unit/test_modbus_eval_suite.py`（新，4 项）：标签可校验、split 规模与去重、validator 能抓出坏 anchor。
  - 文档：`data/modbus/MCP.md` 的对比表改为 v2 两档结果。
- **验证**：

  | 划分 | 指标 | bm25 | hybrid |
  |---|---|---|---|
  | 调参（39 道证据题） | Hit@3 | 0.795 | **0.846** |
  | 调参 | MRR@3 | 0.671 | **0.756** |
  | 留出（20 道） | Hit@3 | 0.550 | **0.800** |
  | 留出 | MRR@3 | 0.475 | **0.692** |

  scope 检查：40/40 与 20/20 全通过；四组均 0 执行错误。命令：

  ```bash
  python -m scripts.validate_modbus_eval_suite
  python -m scripts.evaluate_modbus --mode retrieval --retrieval-mode hybrid --split test \
      --output data/modbus/evaluation/v2_hybrid_test.json
  ```

- **踩坑**：
  - **校验器口径必须与评测器一致**：第一版校验器会把空白折叠后再找 anchor，能通过；但 `evidence_matches` 是严格子串，anchor 一旦跨行就永远失败。改成「严格子串优先，折叠后能中则明确报错」。
  - **表格单元格被截断**：`0B GATEWAY TARGET DEVICE FAILED TO RESPOND` 在语料里实际是 `0B GATEWAY TARGET DEVICE`（后半截换行成另一行），anchor 必须按真实文本写。
  - **页面级标签其实是 chunk 级判定**：同一页有多个片段时，召回同一页但**不含答案的片段**仍算未命中。这对评估更严格（也暴露切块粒度问题），但看 rank 时不要误以为"页码对了却没算中"是 bug。
- **代价 / 遗留**：
  - 题目由本项目的开发助手编写，**没有独立人工盲审**，不能对外称为独立测试集。
  - 留出集只有 20 题，置信区间仍然宽；下一步可扩到 100+ 并请他人复核。
  - 调参集上 bm25 有若干「右页错块」，说明分块粒度仍是瓶颈（见 Q-4）。

### T-4 决策预览补齐协议码值行

- **日期**：2026-11-08　**状态**：已完成
- **触发问题**：Q-5。A03（异常码 02）在 hybrid 与 bm25 下都 `budget_exhausted`：`analyze_log` 后连续 5 次 `search_docs` 不收敛。检索证据本身正确（引用落在 p48），问题出在决策节点收到的预览。
- **定位**：`compact_observations(preview=True)` 只发送正文前 **180 字符**。实测 p48 异常码表里 `02 | ILLEGAL DATA ADDRESS` 位于第 **454** 字符——模型只看得到 `01 ILLEGAL FUNCTION`，于是不断换检索词，直到步数耗尽。
- **决定**：只改**预览**，不动状态里的全文。预览 = 头部 220 字符 + 「头部之后第一条码值行」起 160 字符窗口。理由：
  1. 协议文档的答案常常是表格里第 2–4 行，固定头部永远看不到；
  2. 窗口按行首 `1–2 位数字 + (| 或 大写字母)` 定位，正好匹配两种表示（渲染表格 `02 | ...` 与线性化文本 `02 ILLEGAL ...`）；
  3. 代价可控：每份文档最多多 ~163 字符，3 份文档约 +160 token/次决策，远小于把预览整体放大到 500。
- **改动**：
  - `src/core/modbus_agent.py`：新增 `PREVIEW_CHARS=220`、`CODE_ROW_WINDOW=160`、`CODE_ROW`、`document_preview()`；`compact_observations` 改用它。完整正文仍保留在 `state["observations"]`。
  - `tests/unit/test_modbus_call_optimization.py`：新增 4 项（码值行进入预览、无码值行时仍是纯头部、短文本不截断、决策 prompt 里能看到 `02 ILLEGAL DATA ADDRESS`）。
- **验证**：
  - A03 真实模型：`mechanical_passed=True`，状态 `completed`，**4 次模型调用**（修复前 6 次且 `budget_exhausted`），回答正确解释「异常码 02 = 非法数据地址」并引用 D1/D2（p48）。
  - 全量 Modbus 单测：**210 passed**。
  - 全量 A01–A06 回归（hybrid 默认，真实模型）：

    | 用例 | 状态 | 调用次数 | 机械检查 |
    |---|---|---|---|
    | A01 缺信息追问 | needs_input | 1 | 通过 |
    | A02 捕获末尾 pending | completed | 4 | 通过 |
    | A03 异常响应 | completed | 4 | **通过（修复前 budget_exhausted）** |
    | A04 CRC + 超时 | completed | 4 | 通过 |
    | A05 广播 | completed | 4 | **仅 `expected_document_evidence` 失败** |
    | A06 纯文档题 | completed | 4 | 通过 |

    合计 5/6 通过。**A05 的失败与预览修复无关**：它没有引用到广播页 serial p7（引用的是 p28/p35/p37）。同一用例用 `bm25` 跑对照：**通过**，3 次调用，D1 = p7。这与 v2 检索集里 R08 的 hybrid 失手是同一现象（广播/关键字精确类问题，dense 排名被"两路都命中"的页面压住）。已核对 p35 只是诊断计数器章节的 "returned no response"，不是广播规则，**标签是正确的，不能放宽**。
- **代价 / 遗留**：预览是可检索性的启发式，不是语义理解；若某类答案不以「码值行」形式出现（长段落中间的关键句），仍需靠 chunk 粒度或查询改写解决。命中词窗口版本没有实现——先把这条最小改动验证到位。
- **对 Q-5 的影响**：A03 通过；但 **A03 只是机械检查通过，语义仍需人工复核**，且一次通过不代表 Agent 已稳定（此前 A02 也出现过 provider 错误）。

---

### T-5 第三档：hybrid + rerank 对比

- **日期**：2026-11-08　**状态**：已完成（默认关闭）
- **目的**：Q-6 指出 hybrid 在「答案页唯一、关键字精确」的问题上会排错（R08/A05）。验证精排能否把这类页面拉回前三。
- **可行性排查**：
  - 本地 cross-encoder **不可用**：环境无 `torch` / `transformers`，且 HuggingFace 不可达（8 s 超时）。安装 + 下载模型不现实。
  - 因此使用 **LLM rerank**（复用现有 `LLMReranker`），并做了三处收敛：
    1. 只重排融合后的 **top-8**；
    2. 候选正文截断到 **500 字符**；
    3. 新增 `config/prompts/modbus_rerank.txt`：只要求 `[{"passage_id","score"}]`，**不要 reasoning**（原 prompt 要逐条解释，单次 38 s、输出 token 翻倍）。
- **改动**：
  - `src/core/settings.py`：`modbus.rerank_enabled / rerank_provider / rerank_candidates / rerank_text_chars / rerank_prompt`。
  - `src/core/modbus_knowledge.py`：`_ensure_reranker_provider()`、`_rerank_results()`；**失败自动回退融合顺序**（返回 `None` 走原路径），并在排序里用 **provider 自己的顺序做同分 tie-break**（0–3 分档会产生大量同分，按 chunk_id 排会丢掉 LLM 的排序）。
  - `scripts/evaluate_modbus.py`：`--rerank / --no-rerank`，报告记录 `rerank`。
  - `tests/unit/test_modbus_hybrid.py`：4 项（重排生效、同分保留 provider 顺序、失败回退、bm25 模式不调用）。
- **验证（v2 60 题）**：

  | 划分 | 指标 | bm25 | hybrid | hybrid+rerank |
  |---|---|---|---|---|
  | 调参（39 证据题） | Hit@3 | 0.795 | 0.846 | 0.846 |
  | 调参 | MRR@3 | 0.671 | 0.756 | **0.786** |
  | 留出（20 题） | Hit@3 | 0.550 | 0.800 | **0.900** |
  | 留出 | MRR@3 | 0.475 | 0.692 | **0.817** |

  逐题（留出）：D30/D38 由未命中到第 2，D34/D37/D40/D46 升到第 1；仅 D47 由第 1 降到第 3。调参集：D01/D06/D17/D25 升到第 1、D27 由未命中到第 2，但 **R05 由第 1 掉到未命中**、D21 由第 1 掉到第 3。
- **关键风险：单次运行不可完全复现**。R08 在批量跑里未命中（第 2 名是 p19），但同样的查询单独重跑两次都是 **p7 第 2 名、命中**（3 次直连调用也完全一致）。说明 LLM 服务侧存在跨批次波动。**因此上表是单次结果，逐题翻转（如 R05）不能当作确定收益。**
- **成本**：每次查询多 1 次模型调用（约 4k 输入 token）、**21–36 秒**；60 题整轮约 30 分钟。相较 cross-encoder（约 50 ms、零 API 成本）差距巨大。
- **结论**：
  - 质量方向是对的（留出集 +10 pt Hit@3），但**默认仍保持 `rerank_enabled: false`**：30 秒/次的交互成本对 MCP 工具与页面不可接受，且结果有批次波动。
  - `--rerank` 可用于离线评测与演示；配置里一行可开启。
  - 长期应换 **cross-encoder**（需 torch + 本地模型），或等 provider 提供 rerank API；LLM rerank 只作为验证手段。

### T-6 评测集扩到 100 题并生成人工复核工作表

- **日期**：2026-11-08　**状态**：已完成（自审完成，独立复核待做）
- **触发问题**：T-3 的 60 题仍偏小；v2 的绝对分数偏高（bm25 调参 0.795），说明题目对 BM25 不够难，容易高估系统能力。
- **决定**：
  1. **不修改 v2**，新增 `tests/fixtures/modbus_eval_v3.json` = v2 的 60 题原样保留 + 40 道新题（覆盖 0x08 子功能、0x0C、0x0F、0x14/0x15、0x16、0x17、0x18、MEI、ASCII/LRC、物理层、CRC 附录）。v2 仍是 T-3/T-5 数字的可复现基线。
  2. v3 合计 **100 题（65 调参 / 35 留出）**；`evaluate_modbus` 与 validator 默认套件切到 v3。
  3. 新增 `scripts/make_modbus_review_sheet.py`：为每题输出问题、证据页、**anchor 前后摘录**和判定勾选表，供人工复核使用。
- **验证（bm25 vs hybrid，v3）**：

  | 划分 | 指标 | bm25 | hybrid |
  |---|---|---|---|
  | 调参（64 证据题） | Hit@3 | 0.625 | **0.703** |
  | 调参 | MRR@3 | 0.497 | **0.568** |
  | 留出（35 题） | Hit@3 | 0.514 | **0.771** |
  | 留出 | MRR@3 | 0.443 | **0.648** |

  与 v2 对比：hybrid 在留出集上的领先幅度基本一致（v2 +25.0 pt、v3 +25.7 pt），说明结论不是那 60 道题的特例。**新题让 bm25 的绝对分明显下降**（调参 0.795→0.625），说明这套题更难、更有区分度。
- **人工复核（已完成“自审”，非独立）**：
  - 逐题按三问检查：问题是否唯一指向一个事实、标注页是否正确、仅凭摘录能否推出答案；结合机械校验与「anchor 过短 / 页内多次匹配 / 编号语境不符」三类可疑信号。
  - 结果：**100 题全部审阅，93 通过、7 修改、0 删除**。修改明细与原因见 `data/modbus/evaluation/V3_REVIEW_REPORT.md`。最重要的一个是 **D35 事实性错误**：问题写「子功能00」，但 `Server No Response Count` 属于子功能 **0x0F**。
  - 每题复核结论写入题库 `review` 字段（`status/by/date/note`），顶层 `review` 记录复核范围与「非独立」限制。
  - **这仍然不是独立盲审**：题目和标签都是本助手写的。外部准确率声明仍应等第二个人抽查留出集。
- **复核后基线（v3）**：调参 Hit@3 bm25 0.641 / hybrid 0.703，MRR 0.513 / 0.586；留出 Hit@3 bm25 0.514 / hybrid **0.743**，MRR 0.443 / **0.633**。hybrid 留出集从 0.771 降到 0.743，原因是 D40/D35 的证据被收紧（标签变严），不是检索退化。
- **代价 / 遗留**：
  - rerank 没有在 v3 上重跑（100 题 × 约 30 秒 ≈ 50 分钟）；T-5 的 rerank 数字仍基于 v2。
  - 新增题目同样出自本助手，**不构成独立测试集**；v3 只是"更大、更难、部分覆盖更全"，不是"更可信"。
  - 自动相似度检查当前 0 命中（阈值 0.8 偏松），后续可调严。

### T-7 CI 门禁与测试分层

- **日期**：2026-11-08　**状态**：已完成
- **触发问题**（四条互相放大）：
  1. 仓库没有任何 CI；`ruff`/`mypy` 配了却从没人跑。
  2. 测试分层是假的：全仓只有 1 个测试带 `@pytest.mark.unit`，`pytest -m unit` 只能选到 1 个冒烟测试；裸 `pytest` 会把 e2e 一起跑（e2e 会起子进程 MCP client、连真实 embedding）。
  3. 基线有 **14 个长期失败**，任何门禁都会一上来就红，等于没有门禁。
  4. 源码 6 处 `import httpx`，但 `httpx` 未声明为依赖（只作为其他包的传递依赖存在）。
- **决定**：
  1. **按目录自动打 marker**（`tests/conftest.py` 的 `pytest_collection_modifyitems`），并把默认 `addopts` 设为 `-m 'not e2e and not llm'`，加 `--strict-markers`。
  2. **ruff 只做正确性门禁**：`select = ["E9", "F63", "F7", "F82"]`。全量 `E,F,I,N,W,UP` 在当前代码上有约 7,000 处历史问题，启用会立刻堵死所有提交（登记为 Q-7，按目录逐步收紧）。
  3. **把 14 个失败全部修掉**，而不是加 `xfail`/`--deselect` 掩盖：
     - Windows 时钟粒度导致 `> 0` 断言偶发为 0（3 处）：统一改用 `time.perf_counter()`；
     - embedding provider 测试用裸 `Mock()` 当 settings，`api_key` 变成"真值 Mock"，把"缺少 key 应报错"的分支完全遮住（6 处）：fixture 显式置 `None`，并清理环境变量；
     - 分词器契约过期（2 处）：实现按 jieba 拆连字符，测试却断言保留 `machine-learning`/`gpt-4`。**保持实现**（索引与查询共用同一分词器，一致性优先），改测试并写明契约；
     - trace 测试 fixture 还是旧的扁平格式（1 处）、`list_collections` 断言位置参数与关键字参数（1 处）；
     - 缺 PyMuPDF 的图片用例改为 `importorskip`（1 处）。
  4. `httpx>=0.24` 加入依赖；新增 `image` marker。
  5. 新增 `.github/workflows/ci.yml`：windows-latest + Python 3.10 → `pip install -e ".[dev]"` → `ruff check .` → `pytest -q`。
- **验证**：
  - 全量 `tests/unit`：**1455 passed / 2 skipped / 0 failed**（改动前是 14 failed）。
  - `ruff check .`：**通过**。
  - 分层（共 1627 个用例）：默认 `pytest` 收集 **1457**（170 个 integration+e2e+llm 被排除，实跑 1455）；`-m integration` 144；`-m e2e` 32。
  - **发现并处理**：integration 套件里很多用例需要真实 Azure/DashScope 凭据，未配置时 **13 failed / 29 errors**。它们不是本轮引入的，但会让默认门禁变红，因此**默认只跑 unit**，integration 改为显式 `-m integration`（登记 Q-8：这些用例缺少"凭据缺失就 skip"的守卫）。
- **代价 / 遗留**：
  - CI 只在 windows-latest 上跑（贴近本地环境）；跨平台兼容性仍未验证。
  - `mypy` 没有进门禁（仍有较多存量错误）。
  - 跑 CI 需要能装 `chromadb`/`ragas`/`streamlit` 等重依赖，冷启动约 5–10 分钟。
  - `data/` 被 gitignore，语料相关测试靠 skip；CI 覆盖不到 PDF 摄取全链路。
- **首次真实 CI 运行失败（2026-11-08）**：推送后 `Unit tests` 步骤红，`Install project` 与 `Lint` 绿。
  - **复现方式**：本地克隆一份干净仓库（`data/`、`.env` 都不存在）再跑，得到与 CI 等价的 1427 passed / 30 skipped —— 说明本地没有问题。加上环境变量（占位或真实 key）后立刻出现 **4 个失败**：
    `AzureLLM.test_init_missing_api_key`、`AzureLLM.test_init_missing_endpoint`、`AzureEmbedding.test_initialization_missing_endpoint`、`AzureEmbedding.test_initialization_fallback_to_openai_env_var`。
  - **根因**：这些用例断言的是「**缺少**凭据时报错」，却依赖"运行环境本身没有 key"这个前提。`patch.dict(os.environ, {...})` 默认不清空，`monkeypatch.delenv` 只删了部分变量——环境里只要有 `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY` 就会破坏前提。
  - **修复**：`patch.dict(..., clear=True)`；对每个相关变量显式 `delenv`；fallback 用例显式清掉 settings 里的 `api_key`。
  - **教训**：这类"断言缺失状态"的测试必须自己构造空环境，不能依赖 runner 干净。以后新增同类用例一律 `clear=True`。

### T-8 trace 治理

- **日期**：2026-11-08　**状态**：已完成
- **触发问题**：
  1. `observability.trace_enabled` / `trace_file` 是**死配置**：collector 硬编码 `logs/traces.jsonl`，关不掉也改不了路径。
  2. 整篇文档正文、全部 chunk 正文都被写进 JSONL（pipeline 的 `text_preview`/`chunks`、hybrid 的 `chunks`），单条 trace 可达 MB 级，且把内容落盘。
  3. 写文件发生在 MCP 事件循环线程里（`query_knowledge_hub` 直接同步调用）。
  4. 耗时字段不一致：`to_dict()` 只写 `total_elapsed_ms`，Dashboard 读 `elapsed_ms` → 总耗时永远显示「—」。
- **改动**：
  - `TraceCollector`：按 settings 读取 `trace_enabled`/`trace_file`（可显式覆盖），关闭时直接返回、不建文件。
  - 写入前统一截断：字符串 ≤500 字符、列表 ≤20 项、嵌套深度 ≤4、stage 数 ≤40，超出部分写 `…(+N)` 标记；完整证据仍保留在检索层与运行记录里。
  - `to_dict()` 同时输出 `total_elapsed_ms` 与 `elapsed_ms`（同一个值），兼容两种读法。
  - 追加写加进程内锁，改为单次 `write`；`query_knowledge_hub` 的两次落盘改为 `asyncio.to_thread`。
  - Dashboard 两处读取改为 `total_elapsed_ms or elapsed_ms`。
  - `TraceService` 默认路径也跟随 `trace_file`，并按 `(path, mtime_ns, size)` 缓存解析结果（见 T-9）。
- **验证**：新增 3 项测试（关闭不写、长负载截断、双耗时字段一致），trace 相关 41 项通过；Dashboard 页面测试 31 项通过。
- **代价 / 遗留**：截断意味着 trace 里不能再看到完整正文（设计如此）；进程内锁不解决多进程并发追加，日志轮转也尚未实现（登记为 Q-7 之外的新遗留）。

### T-9 Dashboard 缓存与全量扫描

- **日期**：2026-11-08　**状态**：已完成
- **触发问题**：Streamlit 每次交互都重跑脚本 —— Data Browser 每轮都重建 Chroma/BM25/ImageStorage/DocumentManager；Overview 每轮新建 `PersistentClient` 并对每个 collection `count()`；trace 页面每轮重读并反序列化整个 JSONL。
- **改动**：
  - `DataService` 用 `@st.cache_resource` 单例化；`reset_all()` 后显式 `clear()`，避免拿到已删除的句柄。
  - Overview 的统计加 `@st.cache_data(ttl=15)`。
  - `TraceService` 的 JSONL 解析按文件 `mtime/size` 缓存，文件不变就不重复解析。
- **验证**：`test_dashboard_config`、`test_evaluation_panel`、`test_modbus_page`、`test_trace_service` 共 31 项通过。
- **代价 / 遗留**：统计最长可能滞后 15 秒；缓存的是"服务对象"，若未来换成不支持跨进程读的后端，需要重新引入失效逻辑。

---

## 4. 基础设施与开发环境

### I-1 Windows 沙箱无法启动 shell

- **日期**：2026-11-08　**状态**：已完成
- **现象**：所有 shell 调用直接失败，报 `SetNamedSecurityInfoW failed (Win32 5): grantWrite(<工作区>)`，连 `Get-Location` 都跑不了。
- **原因**：工作区目录缺少沙箱设置写入授权所需的权限（缺少 `WRITE_OWNER` 等），沙箱无法获得授权。
- **处理**：用 DSH 自带的 `diagnose-windows-sandbox-acl.ps1` 诊断+修复，脚本先备份 DACL 再补权限。报告：`D:\1AI_study\AI_program\dsh-acl-recovery\acl-report-*.jsonl`；回滚脚本：同目录 `acl-backup-14d4ca56….json.ps1`。
- **验证**：修复后普通沙箱模式可正常执行命令。
- **代价 / 遗留**：修复脚本在**工作区之外**建了备份目录，如果不打算回滚可以删除。

### I-2 测试解释器与依赖

- **日期**：2026-11-08　**状态**：已知限制
- **现象**：`uv.lock` 里有 pytest，但 `.venv` 和系统 Python 3.13 都没装；实际可用的是用户目录下的 **Python 3.10.11**（`C:\Users\10273\AppData\Local\Programs\Python\Python310\python.exe`，pytest 9.0.2）。
- **基线**（每次改动后都要对比，不能只看通过数）：

  ```bash
  C:\Users\10273\AppData\Local\Programs\Python\Python310\python.exe -m pytest tests/unit -q
  # 2026-11-08 改动前：14 failed / 1362 passed / 1 skipped
  # 2026-11-08 T-7 之后：0 failed / 1455 passed / 2 skipped
  ```

- **原长期失败（已在 T-7 全部修复）**：`test_embedding_providers_smoke`（6，Mock settings 掩盖缺 key 分支）、`test_batch_processor`（2，Windows 时钟粒度）、`test_sparse_encoder`（2，分词契约过期）、`test_trace_service`（1，fixture 旧格式）、`test_eval_runner`（1，时钟粒度）、`test_list_collections`（1，位置/关键字参数）、`test_loader_pdf_contract`（1，缺 PyMuPDF → `importorskip`）。
- **flaky 测试**：`test_trace_context.py::TestElapsedMs::test_total_elapsed_positive` 曾偶发失败（`time.monotonic` 粒度约 15.6 ms，测试只 sleep 5 ms）。已把测试改为 50 ms，并从源头把全部耗时计时换成 `time.perf_counter()`。
- **遗留**：`.venv` 与 `uv.lock` 不匹配，应统一为 `uv sync --frozen`；`mypy` 仍未纳入门禁（见 Q-7）。

---

### I-3 DashScope embedding 批大小上限

- **日期**：2026-11-08　**状态**：已完成（记录约束）
- **现象**：建索引时用默认 `batch_size=32`，嵌入请求返回：

  ```
  400 InternalError.Algo.InvalidParameter:
  batch size is invalid, it should not be larger than 20.: input.contents
  ```

- **处理**：`build_dense_index` 与 CLI 默认批大小改为 20，并在 docstring/`--help` 里写明原因。
- **教训**：**先做单次最小调用验证外部接口约束**（P0-8 与 I-3 都是这样发现的），不要写完一整条链路再联调。
- **遗留**：`IngestionSettings.batch_size` 仍是 100，通用摄取走 DenseEncoder 时也可能触发同样的 400；属于第 6 节待修项。

## 5. 开放问题与待决策

### Q-1 检索路线：BM25 线 vs HybridSearch

- **日期**：2026-11-08　**状态**：待决策
- **背景**：项目里有两套检索栈。`HybridSearch`（Dense + BM25 + RRF + 可选 rerank）是框架层能力，但**本机 `data/db/chroma` 根本不存在**，`query_knowledge_hub` 没有任何数据支撑；真正在跑、有数据、有评测的只有 Modbus 的 BM25 线（单路由 BM25 + 手写短语加权）。
- **已有事实**：
  - 中文问英文语料，目前靠 `QUERY_TERMS` 里 28 条手写映射硬撑，是整条链路最脆的地方。
  - Dense 检索必须调 embedding API，会打破 `search_modbus_docs` 现在「无 LLM/API 调用」的承诺。
  - R01 这类失败（「功能04」没被映射成 `function code 04`）正是 dense 能直接解决的。
- **已实现（2026-11-08）**：按「只借排名、不借数据」接入，`modbus.retrieval_mode` 开关，默认 `bm25`。详见 T-2。
- **新证据（T-3，60 题）**：调参集 Hit@3 0.795→0.846、MRR 0.671→0.756；留出集 Hit@3 0.550→**0.800**、MRR 0.475→**0.692**。hybrid 在两档上都更好，且留出集差距最大。
- **仍待决策**：~~默认模式~~ **已于 2026-11-08 决定**：默认切 `hybrid`（回退只需改回 `bm25`）。hybrid 每次查询多一次 embedding（250–500 ms + 少量费用）并依赖网络；bm25 作为离线回退保留。
- **后续**：开 rerank 后应补第三档 `hybrid+rerank` 对比；并区分「页码命中」与「片段命中」（见 Q-4）。

### Q-2 评测集规模不足

- **日期**：2026-11-08　**状态**：部分完成
- **已完成**：
  - v2 扩到 **60 题（40 调参 / 20 留出）**，每条 anchor 机械校验（T-3）；
  - v3 扩到 **100 题（65 调参 / 35 留出）**（T-6）；
  - v3 **自审完成**：100 题全部审阅，7 处修改（含 1 处事实性错误），0 删除，结论写回题库 `review` 字段。
- **仍缺**：
  1. **独立人工复核**：自审不是盲审；留出集仍应请第二人抽查，之后才能对外做准确率声明。
  2. **题目类型**：目前只有文档检索；日志题、综合任务、信息不足题仍沿用 6 个 agent 场景。
- **待决策**：是否引入真实厂商设备手册（现在只有两份官方规范 + 一个虚拟设备）。

### Q-3 表格版与文本版重复命中

- **日期**：2026-11-08　**状态**：待决策
- **现象**：T-1 让同一张表既以「渲染行」的表格片段入库，又保留在页面正文里。hybrid 检索「异常码02」时，D1 是表格片段、D2 是同一张表的正文线性化版本，两条内容高度重叠，**占用 2/3 的引用位**。
- **影响**：答案上下文冗余、引用列表显得重复；dense 对两者的向量也非常接近。
- **可能方向**：① 入库时把表格区域从页面正文中剔除（需要 bbox 对齐，成本高）；② 检索结果按 `(source, page, 表标识)` 去重并优先保留表格版；③ 表格片段单独打标，作为上下文补充而不是并列引用。选哪个取决于 Q-2 扩容后表格题的实际收益。

### Q-4 缺少「页码命中」与「片段命中」的分层指标

- **日期**：2026-11-08　**状态**：待决策
- **现象**：T-3 的调参集里有若干「页码对了、但召回的是同页另一个片段」的失败（例如期望 p49 的异常码行，返回了同页另一段）。按现有 `evidence_matches`，这算**未命中**——对评估更严格，但看不出到底是检索错了还是切块切坏了。
- **建议**：在 `score_retrieval` 增加 `page_hit_at_k`（只要求 source + page 命中，不校验 anchor），与 `evidence_hit_at_k` 并列报告。两者差距大 → 问题在切块粒度；两者都低 → 问题在检索。
- **代价**：要改评测器与历史报告字段，属于评估口径变更，需单独一次改动并重跑基线。

### Q-5 异常码案例在 Agent 决策循环里耗尽步数

- **日期**：2026-11-08　**状态**：已修复（T-4）
- **现象**：用真实模型跑 A03（`01 03 ...` + `01 83 02`，异常码 02），两次都停在 `budget_exhausted`：`analyze_log` 之后连续 5 次 `search_docs`，从未 `finish`。检索证据其实是对的（引用 D1/D2 都落在 application p48，`expected_document_evidence` 为 true），失败在**决策循环不收敛**。
- **对照实验（关键）**：同一模型、同一 prompt，只把检索切回 `bm25`，结果完全相同（`budget_exhausted`、同样 5 次检索、同样 p48 引用）。**所以与 hybrid 默认切换无关**，是 T-1 改分块之后暴露的问题。
- **根因（已证实）**：`_decide` 只把文档正文前 180 字符发给模型，而 p48 表格里 `02 | ILLEGAL DATA ADDRESS` 在第 454 字符——模型只看得到 `01`，于是不断换查询。T-1 之前块边界不同，02 行恰好在窗口内，所以当时能过。
- **修复**：T-4，预览 = 头部 220 + 首个码值行起 160 字符窗口。A03 修复后 `completed`、4 次调用、机械检查通过。

### Q-6 hybrid 在广播/关键字精确类问题上弱于 bm25

- **日期**：2026-11-08　**状态**：待决策
- **现象**：两个独立证据指向同一类失败：
  1. 检索集 **R08**（地址 0 广播为何无响应）：bm25 第 1 名，hybrid 掉出前三；
  2. Agent **A05**（同一广播场景）：hybrid 未引到 serial p7，机械检查失败；**bm25 对照通过**（D1=p7，3 次调用）。
- **原因**：广播页只在稀疏列表里排第 2；而若干页面同时被 dense 与 sparse 命中，RRF 让它们拿到约双倍分数，把广播页压下去。加权 RRF（1.0→2.0）实测无效（T-2）。
- **影响**：hybrid 的总体指标更好（v2 留出集 +25 pt），但对"关键字精确、答案页唯一"的问题更脆。Agent 的机械检查恰好依赖这类唯一页证据。
- **可能方向**：① 开 rerank（cross-encoder 或 LLM）对融合后的 top-k 重排，这类"页面语义都对但排序错"的问题正是 rerank 的强项；② 按查询特征路由（含明确码值/专有名词时走 bm25）——简单但属于补丁，容易过拟合；③ 提高广播类短语的权重（已在 T-2 试过，无效）。
- **建议**：优先做 ①（rerank 第三档对比），它是下一阶段计划里的自然延伸，也不需要按问题类型打补丁。
- **进展（T-5）**：LLM rerank 已接入并测过：留出集 Hit@3 0.800→**0.900**，广播类问题（R08/A05）重跑时可把 p7 拉回第 2 名；但每次查询 +30 秒、且跨批次有波动，**暂不默认开启**。真正合适的后端是 cross-encoder（需 torch + 本地模型，当前环境不具备）。

### Q-7 静态检查与日志轮转的存量债务

- **日期**：2026-11-08　**状态**：待决策
- **现状**：
  1. ruff 的完整规则集（`E,F,I,N,W,UP`）在 `src/tests/scripts` 上有约 **7,000 处**历史问题；T-7 只启用了正确性子集（`E9,F63,F7,F82`），其余未纳入门禁。
  2. `mypy` 仍未进 CI（存量错误未盘点）。
  3. `logs/traces.jsonl` 没有轮转/上限；trace 已截断，但文件仍会无限增长。
- **建议**：按目录逐批 `ruff check --fix` + 人工复核，把规则集逐步扩到 `E,W,F`，再单独处理 `UP`（会大范围改类型注解）；日志轮转可先做「超过 N MB 重命名」的简单策略。
- **为什么现在不做**：一次性大改会产生数千行 diff，无法 review，也会淹掉真正的行为变更。

### Q-8 集成测试缺少凭据缺失守卫

- **日期**：2026-11-08　**状态**：待处理
- **现象**：`pytest -m integration` 在本机（只配了 DashScope）跑出 **13 failed / 29 errors**：`test_dense_encoder_azure`、`test_vision_llm_integration`、`test_reranker_llm` 等直接尝试真实调用，缺少凭据时不是 skip 而是失败。
- **影响**：integration 层不能作为可选门禁；目前只能默认排除（T-7）。
- **建议**：统一加 `pytest.mark.skipif(not _has_credentials(provider))`，或提供 `RUN_INTEGRATION=1` 开关；再把 integration 纳入 CI 的可选 job（有 secrets 时运行）。
- **为什么暂缓**：需要逐个确认每个集成用例到底依赖哪一类服务，属于独立清理任务。

## 6. 审查发现、尚未修复的问题

这些是 2026-11-08 审查时发现、但不在本轮 P0 范围的问题。T-7/T-8/T-9 已修掉其中四项，其余登记在此：

| 领域 | 问题 | 位置 | 状态 |
|---|---|---|---|
| 摄取 | PDF 图片占位符全部追加到正文末尾，图注只落在最后一个 chunk，图片实际不可检索 | `src/libs/loader/pdf_loader.py` | 未修 |
| 摄取 | 重导无事务：部分写入成功、部分失败时状态不一致 | `src/ingestion/pipeline.py` | 未修 |
| 摄取 | `zip(sparse_stats, vector_ids)` 长度不等时静默截断，真正原因被下游报错掩盖 | `src/ingestion/pipeline.py` | 未修 |
| 摄取 | `ingestion.batch_size: 100` 超过 DashScope embedding 单批 20 的限制，通用摄取会 400 | `config/settings.yaml`、`src/ingestion/embedding/batch_processor.py` | 未修 |
| 检索 | BM25 每次查询整份读盘（当前 2.4 MB / 279 片段），规模上去会成为瓶颈 | `src/core/query_engine/sparse_retriever.py` | 未修 |
| 可观测 | trace 正文无截断写入 JSONL、事件循环内同步写、`trace_enabled`/`trace_file` 是死配置 | `src/core/trace/`、`src/mcp_server/tools/query_knowledge_hub.py` | **已修（T-8）** |
| 可观测 | 总耗时字段名不一致（`total_elapsed_ms` vs `elapsed_ms`），页面永远显示「—」 | `src/core/trace/trace_context.py`、`src/observability/dashboard/pages/` | **已修（T-8）** |
| 测试 | 测试分层标记形同虚设，裸跑会连 e2e 一起执行 | `pyproject.toml`、`tests/conftest.py` | **已修（T-7）** |
| 测试 | 召回门禁是假绿灯：阈值 0.0、`expected_chunk_ids` 全空、异常一律 skip | `tests/e2e/test_recall.py`、`tests/fixtures/golden_test_set.json` | 未修 |
| 工程 | 无 CI；ruff/mypy 配了从没跑过；`httpx` 被 import 但未声明依赖 | `.github/`、`pyproject.toml` | **部分修（T-7：CI+ruff+httpx；mypy 未纳入）** |
| 工程 | `data/` 被 gitignore，但语料与评测集都在里面；`test_modbus_knowledge.py` 直接依赖它 | `tests/unit/test_modbus_knowledge.py` | **部分修（已加 skip，语料仍未版本化）** |
| 语料 | 官方 PDF 的 `�C` 是 en dash 解码损坏，属提取层编码问题，尚未处理 | `data/modbus/processed/` | 未修 |
| 配置 | `embedding.dimensions: 1536` 与实际返回的 1024 维不一致，字段只作说明但容易误导 | `config/settings.yaml` | 未修 |
| 文档 | `data/modbus/README.md` 里「76 项测试」等历史通过数与当前套件规模已不一致（历史记录，不逐条改） | `data/modbus/README.md` | 未修 |

---

## 7. 变更日志

| 日期 | 编号 | 摘要 |
|---|---|---|
| 2026-11-07 | — | 减少模型调用与重复上下文（详见 `docs/technical_updates/2026-11-07-call-context-optimization.md`） |
| 2026-11-08 | I-1 | 修复 Windows 沙箱权限，恢复 shell 可用 |
| 2026-11-08 | P0-1 ~ P0-7 | 密钥治理、入口、文档身份、评测一致性、异常路径、查询过滤器、组件缓存 |
| 2026-11-08 | T-1 | Modbus 语料治理与新分块（去页眉页脚、按标题切、表格成行、去目录） |
| 2026-11-08 | P0-8 / I-3 | embedding 兼容模式配置修复（azure_endpoint 导致 404）；DashScope 批上限 20 |
| 2026-11-08 | T-2 | HybridSearch 双模式接入 + 稠密索引 + 指纹校验 + bm25/hybrid 基线对比 |
| 2026-11-08 | T-3 | 评测集扩到 60 题（40 调参 / 20 留出）+ anchor 机械校验 + `--split` 支持 |
| 2026-11-08 | 决策 | `modbus.retrieval_mode` 默认切为 `hybrid`（bm25 保留为离线回退），测试固定模式 |
| 2026-11-08 | Q-5 | Agent A03 在 hybrid/bm25 下均 `budget_exhausted`，与切换无关；定位为预览窗口问题 |
| 2026-11-08 | T-4 | 决策预览补齐码值行：A03 通过（4 次调用），A01–A06 5/6 通过 |
| 2026-11-08 | Q-6 | 记录 hybrid 在广播类问题上的弱项（R08/A05），建议下一步用 rerank 解决 |
| 2026-11-08 | T-5 | 第三档 hybrid+rerank：留出集 +10 pt Hit@3，但 +30 秒/次且跨批次波动，默认关闭 |
| 2026-11-08 | T-6 | v3 评测集扩到 100 题（65/35）+ 人工复核工作表；hybrid 留出集领先 25.7 pt |
| 2026-11-08 | T-6 复核 | 100 题自审完成：93 通过 / 7 修改 / 0 删除；复核后 hybrid 留出集 0.743 |
| 2026-11-08 | T-7 | CI + 测试分层 + ruff 正确性门禁；14 个既有失败全部修复（1455 passed） |
| 2026-11-08 | T-8 | trace 治理：配置生效、截断、双耗时字段、异步写、Dashboard 读取回退 |
| 2026-11-08 | T-9 | Dashboard 缓存：服务单例、统计 ttl、trace 解析按 mtime 缓存 |
| 2026-11-08 | Q-8 | 登记 integration 套件缺凭据守卫；默认门禁收敛为 unit-only |
| 2026-11-08 | Q-1 / Q-2 | 登记检索路线与评测集规模的待决策项 |

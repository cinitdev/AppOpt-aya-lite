# AppOpt Aya Lite

`AppOpt Aya Lite` 是 AppOpt 项目使用的精简版 Aya 工作区。

这个仓库只保留 AppOpt eBPF 用户态桥接层需要的两个 crate：

- `aya`
- `aya-obj`

它不是官方 Aya 的完整替代品，也不面向通用 eBPF 开发场景。完整功能请使用上游项目：[aya-rs/aya](https://github.com/aya-rs/aya)。

## 为什么需要这个仓库

AppOpt 只需要在 Android userspace 中加载 BPF 对象、attach uprobe，并读取 RingBuf / PerfEvent 事件。官方 Aya 仓库包含更多 crate、工具、示例和开发辅助内容，直接 vendoring 到 AppOpt 里会让模块构建体积和维护成本变高。

因此这里维护一个轻量工作区：

- 保留 `aya` 与 `aya-obj`
- 保留上游根工作区依赖配置
- 移除 AppOpt 不需要的其他 workspace member
- 通过 CI 确认精简后仍可编译和测试

## 本地构建

```bash
cargo check --workspace --all-targets
cargo test --workspace --lib
```

注意：Aya 是 Linux userspace eBPF 库，Windows 原生 target 下不能完整编译。Windows 本地验证建议使用 Linux target 做编译检查：

```bash
rustup target add x86_64-unknown-linux-gnu
cargo check --workspace --all-targets --target x86_64-unknown-linux-gnu
```

完整测试以 GitHub Actions 的 Ubuntu 环境为准。

如果只想确认 AppOpt 当前依赖能否解析：

```bash
cargo check -p aya
```

## 同步上游

手动同步最新上游：

```bash
bash scripts/sync-upstream.sh
```

默认同步：

- 上游仓库：`https://github.com/aya-rs/aya.git`
- 上游分支：`main`

可以用环境变量覆盖：

```bash
AYA_UPSTREAM_URL=https://github.com/aya-rs/aya.git \
AYA_UPSTREAM_REF=main \
bash scripts/sync-upstream.sh
```

同步脚本会执行以下动作：

1. 克隆上游 Aya。
2. 只复制 `aya`、`aya-obj` 和许可证文件。
3. 将上游根 `Cargo.toml` 裁剪为只包含 `aya` / `aya-obj` 的 workspace。
4. 执行 `scripts/apply-appopt-patches.py`，套用 AppOpt 的 Android 兼容补丁。
5. 写入 `UPSTREAM.md`，记录本次同步的上游地址、分支和 commit。

同步后需要执行：

```bash
cargo check --workspace --all-targets
cargo test --workspace --lib
```

## GitHub Actions

仓库包含两个 workflow：

- `CI`：每次 push / PR 执行格式检查、编译和测试。
- `Sync Upstream Aya`：每周自动同步上游 Aya，编译测试通过后自动创建 PR。

自动同步不会直接推到主分支，而是创建 PR。这样可以先确认 AppOpt 侧是否需要适配 API 变化。

## 在 AppOpt 中使用

AppOpt 的 Rust bridge 可以继续使用 path 依赖：

```toml
[dependencies]
aya = { path = "../aya/aya" }
```

如果 AppOpt 主仓库改用 git submodule，推荐路径保持为：

```text
fps_monitor/aya
```

这样现有 `Cargo.toml` 不需要改。

## 维护原则

- 只跟随上游 Aya 的 `aya` / `aya-obj` crate。
- 不在这个仓库里添加 AppOpt 专属补丁，除非 Android 构建确实需要。
- 如果必须添加补丁，应在 README 或提交信息里说明原因，方便后续同步时处理冲突。
- 每次同步后先让本仓库 CI 通过，再接入 AppOpt 模块构建验证。

## 许可证

本仓库内容来自 Aya，遵循上游的 `MIT OR Apache-2.0` 许可证。

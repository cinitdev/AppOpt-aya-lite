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
cargo check --workspace --all-targets --all-features
cargo build --workspace --all-features
cargo test --workspace --lib --all-features
```

注意：Aya 是 Linux userspace eBPF 库，Windows 原生 target 下不能完整编译。Windows 本地验证建议使用 Linux target 做编译检查：

```bash
rustup target add x86_64-unknown-linux-gnu
cargo check --workspace --all-targets --target x86_64-unknown-linux-gnu
```

完整测试以 GitHub Actions 的 Ubuntu 环境为准。

在 WSL 中运行库测试时，建议把 `CARGO_TARGET_DIR` 指向 Linux 原生文件系统（例如自己创建的 `/tmp` 子目录），而不是 `/mnt/c`。当前上游的 `/proc/pid/maps` 解析使用 32 位 inode，Windows 挂载盘的超大 inode 会使 uprobe 路径测试失败；不应通过跳过测试来处理。

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

1. 在独立临时目录获取上游 Aya，支持分支、tag 或完整 commit SHA。
2. 在临时副本中只保留 `aya`、`aya-obj` 和许可证文件，裁剪根 `Cargo.toml`。
3. 执行 `scripts/apply-appopt-patches.py`，校验并套用 Android 兼容补丁。
4. 再以 `--check` 验证补丁完整性和幂等性；失败时不会替换工作区源码。
5. 校验通过后替换工作区源码，写入 `UPSTREAM.md` 记录来源。

同步会覆盖本地 vendored 源码，请先提交或备份本地修改。设置 `SYNC_TMP_DIR` 时，它只作为临时目录的父目录使用；脚本创建并清理自己的唯一子目录，不删除调用者指定的目录或其中的其他文件。

同步后需要执行：

```bash
cargo fmt --all
python3 scripts/apply-appopt-patches.py --check
cargo check --workspace --all-targets --all-features
cargo build --workspace --all-features
cargo test --workspace --lib --all-features
```

### 自动补丁的范围

补丁不依赖固定行号，按已知代码片段和匹配数量校验，支持空白/换行变化：

- **netlink socket 长度**：兼容旧 `aya/src/sys/netlink.rs` 和新 `aya/src/sys/netlink/` 模块目录；将两个 `setsockopt` 长度转换为 `libc::socklen_t`，已兼容的表达式保持不变。
- **Android x86 bindings**：为 x86 复用现有 x86_64 bindings，识别已添加的独立或合并 `cfg`，不重复插入。
- **32 位常量溢出**：修正 `BPF_F_CTXLEN_MASK`；允许 bindgen 别名编号变化，并识别已知的显式转换/64 位别名修复。
- **Android reuseport 常量**：保留 Linux 的 libc 导入，为 Android 提供 52/68 常量；兼容历史版本中已集中定义常量的布局。

所有补丁先在内存中校验，全部可识别才写入；可以重复执行。未知上下文、重复匹配、缺失目标、常量变化等会明确报错并停止，不会静默跳过补丁。它不能自动修复任意未来的 Rust/API/ABI 变化；例如上游增加原生 x86 bindings 后需要人工确认是否移除旧回退方案。

本地检查（Python 3.10+；完整离线同步测试还需要 Bash 和 Git）：

```bash
python3 -m unittest discover -s scripts/tests -v
python3 scripts/apply-appopt-patches.py --check  # 只读，缺补丁或无法识别时返回非零
python3 scripts/apply-appopt-patches.py --root /path/to/isolated/workspace
```

## GitHub Actions

仓库包含两个 workflow：

- `CI`：每次 push / PR 执行脚本回归测试、补丁完整性验证、格式检查、Linux 全 feature 检查/构建/库测试，以及四种 Android target 检查。
- `Sync Upstream Aya`：每周一北京时间 04:00（周日 UTC 20:00）自动同步上游；修改同步脚本也会触发。自动打补丁、rustfmt、验证格式化后仍然幂等，再通过上述编译测试门禁，才创建 PR。

Android 检查覆盖 `aarch64-linux-android`、`armv7-linux-androideabi`、`x86_64-linux-android` 和 `i686-linux-android`。这里使用 `cargo check --all-features` 验证跨架构编译兼容性，不等同于 Android APK/NDK 最终链接或真机运行测试。

可在 Actions 页面手动运行 `Sync Upstream Aya`，填写 `upstream_ref` 指定完整 SHA 复现某次上游版本，默认是 `main`。CI 使用最新 stable Rust；本机验证也需要满足所同步上游的 `rust-version`。

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

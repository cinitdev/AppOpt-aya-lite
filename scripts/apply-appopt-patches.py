#!/usr/bin/env python3
"""Apply AppOpt-specific compatibility patches after syncing upstream Aya."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_checked(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        raise SystemExit(f"补丁上下文不存在: {path}: {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


def main() -> int:
    netlink = ROOT / "aya" / "src" / "sys" / "netlink.rs"
    replace_checked(
        netlink,
        "size_of_val(&enable) as u32",
        "size_of_val(&enable) as libc::socklen_t",
    )

    generated_mod = ROOT / "aya-obj" / "src" / "generated" / "mod.rs"
    replace_checked(
        generated_mod,
        '#[cfg(target_arch = "x86_64")]\nmod linux_bindings_x86_64;',
        '#[cfg(target_arch = "x86_64")]\nmod linux_bindings_x86_64;\n'
        '#[cfg(target_arch = "x86")]\nmod linux_bindings_x86_64;',
    )
    replace_checked(
        generated_mod,
        '#[cfg(target_arch = "x86_64")]\npub use linux_bindings_x86_64::*;',
        '#[cfg(target_arch = "x86_64")]\npub use linux_bindings_x86_64::*;\n'
        '#[cfg(target_arch = "x86")]\npub use linux_bindings_x86_64::*;',
    )

    linux_x86_64 = ROOT / "aya-obj" / "src" / "generated" / "linux_bindings_x86_64.rs"
    replace_checked(
        linux_x86_64,
        "pub const BPF_F_CTXLEN_MASK: _bindgen_ty_14 = 4503595332403200;",
        '#[cfg(not(target_arch = "x86"))]\n'
        "pub const BPF_F_CTXLEN_MASK: _bindgen_ty_14 = 4503595332403200;\n"
        '#[cfg(target_arch = "x86")]\n'
        "pub const BPF_F_CTXLEN_MASK: _bindgen_ty_14 = 4503595332403200u64 as _bindgen_ty_14;",
    )

    android_reuseport_constants = (
        '#[cfg(target_os = "android")]\n'
        "const SO_ATTACH_REUSEPORT_EBPF: libc::c_int = 52;\n"
        '#[cfg(target_os = "android")]\n'
        "const SO_DETACH_REUSEPORT_BPF: libc::c_int = 68;"
    )
    for relative_path in [
        "aya/src/programs/sk_reuseport.rs",
        "aya/src/programs/socket_filter.rs",
    ]:
        replace_checked(
            ROOT / relative_path,
            "use libc::{SO_ATTACH_REUSEPORT_EBPF, SO_DETACH_REUSEPORT_BPF, SOL_SOCKET, setsockopt};",
            '#[cfg(not(target_os = "android"))]\n'
            "use libc::{SO_ATTACH_REUSEPORT_EBPF, SO_DETACH_REUSEPORT_BPF};\n"
            "use libc::{SOL_SOCKET, setsockopt};\n\n"
            f"{android_reuseport_constants}",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

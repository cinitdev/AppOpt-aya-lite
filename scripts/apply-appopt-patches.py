#!/usr/bin/env python3
"""Apply recognized Android fixes; fail closed on source drift.

All patches are planned before any file is written. --check verifies that no
patch is needed, including after rustfmt. No third-party Python packages needed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


class PatchError(Exception):
    """An upstream change needs review rather than a guessed replacement."""


def rust_pattern(source: str) -> str:
    """Match a known Rust fragment while tolerating formatting changes only."""
    tokens = re.findall(r'"[^"\n]*"|[A-Za-z_][A-Za-z_0-9]*|[0-9]+\w*|::|[^\s]', source)
    return r"\s*".join(re.escape(token) for token in tokens)


def matches(text: str, fragment: str) -> list[re.Match[str]]:
    return list(re.finditer(r"(?m)^[ \t]*" + rust_pattern(fragment), text))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PatchError(message)


def replace_known(text: str, old: str, new: str, label: str) -> str:
    """Recognize entire old/new blocks, rejecting duplicates and partial cfgs."""
    done = matches(text, new)
    if done:
        require(len(done) == 1, f"{label}: duplicate patched blocks")
        require(not text[:done[0].start()].rstrip().endswith("]"), f"{label}: unexpected preceding attribute")
        remainder = text[:done[0].start()] + text[done[0].end():]
        require(not matches(remainder, old), f"{label}: both old and patched blocks found")
        return text
    pending = matches(text, old)
    require(len(pending) == 1, f"{label}: expected one known source block, found {len(pending)}")
    match = pending[0]
    require(not text[:match.start()].rstrip().endswith("]"), f"{label}: unexpected preceding attribute")
    return text[:match.start()] + new + text[match.end():]


class PatchPlan:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.original: dict[str, str] = {}
        self.updated: dict[str, str] = {}
        self.messages: list[str] = []

    def read(self, relative: str) -> str:
        path = self.root / relative
        require(path.resolve().is_relative_to(self.root), f"{relative}: path escapes workspace")
        require(path.is_file(), f"{relative}: required source file missing")
        if relative not in self.original:
            self.original[relative] = path.read_text(encoding="utf-8")
            self.updated[relative] = self.original[relative]
        return self.updated[relative]

    def set(self, relative: str, text: str, label: str) -> None:
        previous = self.read(relative)
        self.updated[relative] = text
        status = "already compatible" if previous == text else "patch planned"
        self.messages.append(f"{label}: {status} ({relative})")

    def changes(self) -> list[str]:
        return [name for name, text in self.updated.items() if text != self.original[name]]

    def write(self) -> None:
        # No writes until every patch has been recognized and validated.
        for name in self.changes():
            (self.root / name).write_text(self.updated[name], encoding="utf-8", newline="\n")


def patch_netlink(plan: PatchPlan) -> None:
    old = plan.root / "aya/src/sys/netlink.rs"
    module = plan.root / "aya/src/sys/netlink/mod.rs"
    require(old.is_file() != module.is_file(), "netlink: expected exactly one .rs or module-directory layout")
    paths = [old] if old.is_file() else sorted(module.parent.rglob("*.rs"))
    expression = rust_pattern("size_of_val(&enable)")
    cast = expression + r"\s+as\s+(u32|libc\s*::\s*socklen_t|_)(?=\s*[,;)])"
    count = 0
    for path in paths:
        name = path.relative_to(plan.root).as_posix()
        text = plan.read(name)
        occurrences = list(re.finditer(expression, text))
        if not occurrences:
            continue
        casts = list(re.finditer(cast, text))
        require(len(casts) == len(occurrences), f"netlink: unknown length expression in {name}")
        count += len(casts)
        text = re.sub(cast, lambda m: "size_of_val(&enable) as libc::socklen_t" if m[1] == "u32" else m[0], text)
        plan.set(name, text, "netlink socklen_t")
    require(count == 2, f"netlink: expected 2 setsockopt lengths, found {count}")


def patch_bindings(plan: PatchPlan) -> None:
    name = "aya-obj/src/generated/mod.rs"
    text = plan.read(name)
    cfg64 = '#[cfg(target_arch = "x86_64")]'
    cfg32 = '#[cfg(target_arch = "x86")]'
    combined = '#[cfg(any(target_arch = "x86", target_arch = "x86_64"))]'
    reverse = '#[cfg(any(target_arch = "x86_64", target_arch = "x86"))]'
    for item in ("mod linux_bindings_x86_64;", "pub use linux_bindings_x86_64::*;"):
        shared = matches(text, combined + item) + matches(text, reverse + item)
        declarations = matches(text, item)
        x86 = matches(text, cfg32 + item)
        require(len(x86) <= 1, f"x86 bindings: duplicate x86 declaration: {item}")
        if shared:
            require(len(shared) == len(declarations) == 1, f"x86 bindings: ambiguous cfg: {item}")
            require(not text[:shared[0].start()].rstrip().endswith("]"), f"x86 bindings: unexpected attribute: {item}")
        else:
            require(len(declarations) == 1 + len(x86), f"x86 bindings: unexpected declarations: {item}")
            text = replace_known(text, cfg64 + "\n" + item, cfg64 + "\n" + item + "\n" + cfg32 + "\n" + item, "x86 bindings")
    # Do not combine a future native x86 binding with our x86_64 fallback.
    require(not re.search(r"\b(?:mod|use)\s+linux_bindings_x86\b", text), "x86 bindings: native x86 bindings added upstream; review fallback")
    plan.set(name, text, "x86 bindings")

    name = "aya-obj/src/generated/linux_bindings_x86_64.rs"
    text = plan.read(name)
    types = re.findall(r"(?m)^pub\s+const\s+BPF_F_CTXLEN_MASK\s*:\s*(\w+)\s*=", text)
    require(1 <= len(types) <= 2 and len(set(types)) == 1, "x86 mask: missing or ambiguous BPF_F_CTXLEN_MASK")
    ty = types[0]
    # Bindgen may renumber the alias; its actual representation must stay known.
    aliases = re.findall(rf"(?m)^pub\s+type\s+{re.escape(ty)}\s*=\s*([^;]+);", text)
    require(len(aliases) == 1, f"x86 mask: unknown alias {ty}")
    representation = re.sub(r"\s+", "", aliases[0])
    old = f"pub const BPF_F_CTXLEN_MASK: {ty} = 4503595332403200;"
    if representation in ("u64", "::core::ffi::c_ulonglong"):
        require(len(types) == 1, "x86 mask: unexpected cfgs for a 64-bit alias")
        replace_known(text, old, old, "x86 mask (upstream 64-bit alias)")
        plan.set(name, text, "x86 mask (upstream 64-bit alias)")
        return
    require(representation == "::core::ffi::c_ulong", f"x86 mask: unsupported alias {ty} = {representation}")
    new = (
        '#[cfg(not(target_arch = "x86"))]\n' + old + "\n"
        '#[cfg(target_arch = "x86")]\n'
        f"pub const BPF_F_CTXLEN_MASK: {ty} = 4503595332403200u64 as {ty};"
    )
    safe = matches(text, f"pub const BPF_F_CTXLEN_MASK: {ty} = 4503595332403200u64 as {ty};")
    if len(types) == 1 and len(safe) == 1:
        require(not text[:safe[0].start()].rstrip().endswith("]"), "x86 mask: unexpected cfg on cast")
    else:
        text = replace_known(text, old, new, "x86 mask")
    plan.set(name, text, "x86 mask")


REUSEPORT = {"SO_ATTACH_REUSEPORT_EBPF": 52, "SO_DETACH_REUSEPORT_BPF": 68}


def patch_reuseport(plan: PatchPlan) -> None:
    constants = "\n".join(
        f'#[cfg(target_os = "android")]\nconst {symbol}: libc::c_int = {value};'
        for symbol, value in REUSEPORT.items()
    )
    new = (
        '#[cfg(not(target_os = "android"))]\n'
        'use libc::{SO_ATTACH_REUSEPORT_EBPF, SO_DETACH_REUSEPORT_BPF};\n'
        'use libc::{SOL_SOCKET, setsockopt};\n\n' + constants
    )
    for file in ("sk_reuseport.rs", "socket_filter.rs"):
        name = f"aya/src/programs/{file}"
        text = plan.read(name)
        imports = list(re.finditer(r"(?m)^use\s+libc\s*::\s*\{([^{}]+)\}\s*;", text))
        relevant = [m for m in imports if any(symbol in m[1] for symbol in REUSEPORT)]
        if relevant:
            require(len(relevant) == 1, f"reuseport: ambiguous libc imports in {name}")
            imported = [s.strip() for s in relevant[0][1].split(",") if s.strip()]
            if set(imported) == set(REUSEPORT) | {"SOL_SOCKET", "setsockopt"} and len(imported) == 4:
                require(not any(matches(text, f"const {s}:") for s in REUSEPORT), f"reuseport: partial constants in {name}")
                text = replace_known(text, relevant[0][0], new, name)
            else:
                replace_known(text, new, new, f"reuseport: unknown or partial Android guards in {name}")
            for symbol in REUSEPORT:
                require(len(matches(text, f"const {symbol}:")) == 1, f"reuseport: duplicate/missing {symbol} in {name}")
        else:
            # Historical AppOpt snapshots import these from programs/mod.rs.
            parent = plan.read("aya/src/programs/mod.rs")
            crate_uses = re.findall(r"(?ms)^use\s+crate::\{.*?^\};", text)
            require(len(crate_uses) == 1, f"reuseport: unknown import layout in {name}")
            program_uses = re.search(r"\bprograms\s*::\s*\{([^{}]+)", crate_uses[0])
            require(program_uses is not None, f"reuseport: missing programs imports in {name}")
            for symbol, value in REUSEPORT.items():
                definition = matches(parent, f"pub(crate) const {symbol}: libc::c_int = {value};")
                require(len(definition) == 1 and not parent[:definition[0].start()].rstrip().endswith("]"), f"reuseport: unknown shared {symbol}")
                require(re.search(rf"\b{symbol}\b", program_uses[1]) is not None, f"reuseport: missing {symbol} import in {name}")
                require(not matches(text, f"const {symbol}:"), f"reuseport: conflicting local {symbol} in {name}")
        plan.set(name, text, "Android reuseport")


def build_plan(root: Path) -> PatchPlan:
    plan = PatchPlan(root)
    patch_netlink(plan)
    patch_bindings(plan)
    patch_reuseport(plan)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", action="store_true", help="read-only: fail if patches are needed or source is unrecognized")
    args = parser.parse_args()
    try:
        plan = build_plan(args.root)
        for message in plan.messages:
            print(message)
        if args.check and plan.changes():
            raise PatchError("patches required: " + ", ".join(plan.changes()))
        if not args.check:
            plan.write()
        print(f"Android compatibility verified; {len(plan.changes())} file(s) {'need changes' if args.check else 'updated'}.")
        return 0
    except (PatchError, OSError) as error:
        print(f"AppOpt patch validation failed: {error}\nNo guessed fixes: review upstream changes before syncing.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

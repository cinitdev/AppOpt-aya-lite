"""Offline regression coverage for supported upstream layouts and safe failure."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1]
PATCHER = SCRIPTS / "apply-appopt-patches.py"
spec = importlib.util.spec_from_file_location("appopt_patches", PATCHER)
patches = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patches)

NETLINK = "aya/src/sys/netlink.rs"
MODULE = "aya/src/sys/netlink/mod.rs"
BINDINGS = "aya-obj/src/generated/mod.rs"
MASK = "aya-obj/src/generated/linux_bindings_x86_64.rs"
PROGRAMS = ("aya/src/programs/sk_reuseport.rs", "aya/src/programs/socket_filter.rs")
IMPORT = "use libc::{SO_ATTACH_REUSEPORT_EBPF, SO_DETACH_REUSEPORT_BPF, SOL_SOCKET, setsockopt};\n"


def write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def fixture(root: Path, netlink: str = NETLINK) -> None:
    write(root, netlink, "fn open() {\n" + "    size_of_val(&enable) as u32,\n" * 2 + "}\n")
    write(root, BINDINGS, '#[cfg(target_arch = "x86_64")]\nmod linux_bindings_x86_64;\n'
          '#[cfg(target_arch = "x86_64")]\npub use linux_bindings_x86_64::*;\n')
    write(root, MASK, "pub const BPF_F_CTXLEN_MASK: _bindgen_ty_14 = 4503595332403200;\n"
          "pub type _bindgen_ty_14 = ::core::ffi::c_ulong;\n")
    for name in PROGRAMS:
        write(root, name, IMPORT)


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="appopt-patch-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        fixture(self.root)

    def edit(self, name, old, new):
        text = (self.root / name).read_text(encoding="utf-8")
        self.assertIn(old, text)
        write(self.root, name, text.replace(old, new))

    def apply_twice(self):
        plan = patches.build_plan(self.root)
        plan.write()
        before = snapshot(self.root)
        again = patches.build_plan(self.root)
        self.assertEqual(again.changes(), [])
        again.write()
        self.assertEqual(snapshot(self.root), before)
        return plan

    def assert_rejected_without_changes(self, message):
        before = snapshot(self.root)
        with self.assertRaisesRegex(patches.PatchError, message):
            patches.build_plan(self.root).write()
        self.assertEqual(snapshot(self.root), before)

    def test_old_layout_and_idempotence(self):
        self.assertEqual(len(self.apply_twice().changes()), 5)

    def test_module_layout_and_idempotence(self):
        (self.root / NETLINK).unlink()
        fixture(self.root, MODULE)
        self.assertIn(MODULE, self.apply_twice().changes())

    def test_netlink_lengths_moved_to_submodule(self):
        (self.root / NETLINK).unlink()
        fixture(self.root, MODULE)
        write(self.root, "aya/src/sys/netlink/socket.rs", (self.root / MODULE).read_text())
        write(self.root, MODULE, "mod socket;\n")
        self.apply_twice()

    def test_whitespace_and_reordered_imports(self):
        self.edit(NETLINK, "size_of_val(&enable)", "size_of_val ( & enable )")
        self.edit(BINDINGS, 'cfg(target_arch = "x86_64")', 'cfg ( target_arch="x86_64" )')
        for name in PROGRAMS:
            write(self.root, name, "use libc::{\n setsockopt, SOL_SOCKET,\n SO_DETACH_REUSEPORT_BPF, SO_ATTACH_REUSEPORT_EBPF,\n};\n")
        self.apply_twice()

    def test_bindgen_alias_renumbered(self):
        self.edit(MASK, "_bindgen_ty_14", "_bindgen_ty_27")
        self.apply_twice()

    def test_upstream_socklen_fix(self):
        self.edit(NETLINK, "as u32", "as libc::socklen_t")
        self.assertNotIn(NETLINK, self.apply_twice().changes())

    def test_upstream_inferred_socklen(self):
        self.edit(NETLINK, "as u32", "as _")
        self.assertNotIn(NETLINK, self.apply_twice().changes())

    def test_upstream_shared_x86_cfg(self):
        self.edit(BINDINGS, 'cfg(target_arch = "x86_64")', 'cfg(any(target_arch = "x86", target_arch = "x86_64"))')
        self.assertNotIn(BINDINGS, self.apply_twice().changes())

    def test_upstream_explicit_mask_cast(self):
        self.edit(MASK, "4503595332403200;", "4503595332403200u64 as _bindgen_ty_14;")
        self.assertNotIn(MASK, self.apply_twice().changes())

    def test_upstream_fixed_width_mask_alias(self):
        self.edit(MASK, "::core::ffi::c_ulong", "u64")
        self.assertNotIn(MASK, self.apply_twice().changes())

    def test_historical_shared_constants(self):
        write(self.root, "aya/src/programs/mod.rs", "\n".join(
            f"pub(crate) const {key}: libc::c_int = {value};" for key, value in patches.REUSEPORT.items()))
        for name in PROGRAMS:
            write(self.root, name, "use libc::{SOL_SOCKET, setsockopt};\n"
                  "use crate::{\n programs::{ProgramData, SO_ATTACH_REUSEPORT_EBPF, SO_DETACH_REUSEPORT_BPF},\n};\n")
        plan = self.apply_twice()
        for name in PROGRAMS:
            self.assertNotIn(name, plan.changes())

    def test_both_netlink_layouts_rejected(self):
        write(self.root, MODULE, (self.root / NETLINK).read_text())
        self.assert_rejected_without_changes("exactly one")

    def test_missing_layout_rejected(self):
        (self.root / NETLINK).unlink()
        self.assert_rejected_without_changes("exactly one")

    def test_changed_length_type_rejected(self):
        self.edit(NETLINK, "as u32", "as usize")
        self.assert_rejected_without_changes("unknown length")

    def test_additional_length_rejected(self):
        with (self.root / NETLINK).open("a") as output:
            output.write("size_of_val(&enable) as u32,\n")
        self.assert_rejected_without_changes("expected 2")

    def test_changed_mask_value_rejected(self):
        self.edit(MASK, "4503595332403200", "4503595332403201")
        self.assert_rejected_without_changes("x86 mask")

    def test_unknown_alias_rejected(self):
        self.edit(MASK, "::core::ffi::c_ulong", "usize")
        self.assert_rejected_without_changes("unsupported alias")

    def test_duplicate_x86_declaration_rejected(self):
        self.apply_twice()
        with (self.root / BINDINGS).open("a") as output:
            output.write('#[cfg(target_arch = "x86")]\nmod linux_bindings_x86_64;\n')
        self.assert_rejected_without_changes("duplicate x86")

    def test_partial_mask_patch_rejected(self):
        self.edit(MASK, "pub const", '#[cfg(not(target_arch = "x86"))]\npub const')
        self.assert_rejected_without_changes("preceding attribute")

    def test_unknown_reuseport_context_does_not_write_earlier_patches(self):
        self.edit(PROGRAMS[-1], "setsockopt", "unknown_function")
        self.assert_rejected_without_changes("reuseport")

    def test_extra_attribute_on_patched_block_rejected(self):
        self.apply_twice()
        self.edit(PROGRAMS[0], '#[cfg(not(target_os = "android"))]', '#[cfg(feature = "unexpected")]\n#[cfg(not(target_os = "android"))]')
        self.assert_rejected_without_changes("preceding attribute")

    def test_native_x86_bindings_require_review(self):
        with (self.root / BINDINGS).open("a") as output:
            output.write('#[cfg(target_arch = "x86")]\nmod linux_bindings_x86;\n')
        self.assert_rejected_without_changes("native x86")

    def test_missing_file_does_not_write_earlier_patches(self):
        (self.root / PROGRAMS[-1]).unlink()
        self.assert_rejected_without_changes("source file missing")

    def test_wrong_android_constant_rejected(self):
        self.apply_twice()
        self.edit(PROGRAMS[0], "= 52;", "= 53;")
        self.assert_rejected_without_changes("reuseport")

    def test_missing_android_guard_rejected(self):
        self.apply_twice()
        self.edit(PROGRAMS[0], '#[cfg(target_os = "android")]\n', "")
        self.assert_rejected_without_changes("reuseport")

    def test_check_mode_is_read_only(self):
        before = snapshot(self.root)
        result = subprocess.run([sys.executable, str(PATCHER), "--root", str(self.root), "--check"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("patches required", result.stderr)
        self.assertEqual(snapshot(self.root), before)
        self.apply_twice()
        result = subprocess.run([sys.executable, str(PATCHER), "--root", str(self.root), "--check"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class SyncTests(unittest.TestCase):
    """Exercise the real shell entry point against a tiny offline Git upstream."""

    def setUp(self):
        git_bash = Path("C:/Program Files/Git/bin/bash.exe")
        self.bash = str(git_bash) if os.name == "nt" and git_bash.exists() else shutil.which("bash")
        if not self.bash or not shutil.which("git"):
            self.skipTest("bash and git required for sync integration tests")
        self.temp = tempfile.TemporaryDirectory(prefix="appopt-sync-test-")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.upstream = base / "upstream"
        self.repo = base / "destination"
        self.scratch = base / "scratch with spaces"
        self.scratch.mkdir()
        write(self.scratch, "keep.txt", "caller-owned content")
        fixture(self.upstream, MODULE)
        write(self.upstream, "Cargo.toml", '[workspace]\nmembers = ["aya", "aya-obj", "xtask"]\ndefault-members = ["aya"]\n')
        for license in ("LICENSE-MIT", "LICENSE-APACHE"):
            write(self.upstream, license, "test license")
        shutil.copytree(SCRIPTS, self.repo / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        write(self.repo, "aya/original.txt", "must survive failure")
        write(self.repo, "aya-obj/original.txt", "must survive failure")
        write(self.repo, "Cargo.toml", "original manifest")
        self.env = dict(os.environ, PYTHON=sys.executable, SYNC_TMP_DIR=self.scratch.as_posix(),
                        AYA_UPSTREAM_URL=self.upstream.as_posix(), GIT_CONFIG_NOSYSTEM="1")
        self.git("init", "-q")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.upstream), *args], check=True, capture_output=True, text=True).stdout.strip()

    def run_sync(self):
        self.git("add", ".")
        self.git("-c", "user.name=AppOpt Tests", "-c", "user.email=tests@example.invalid", "commit", "-qm", "fixture")
        self.commit = self.git("rev-parse", "HEAD")
        env = dict(self.env, AYA_UPSTREAM_REF=self.commit)
        return subprocess.run([self.bash, str(self.repo / "scripts/sync-upstream.sh")], env=env, capture_output=True, text=True, encoding="utf-8")

    def test_sync_exact_commit_and_preserve_temp_parent(self):
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(patches.build_plan(self.repo).changes(), [])
        self.assertIn(self.commit, (self.repo / "UPSTREAM.md").read_text(encoding="utf-8"))
        self.assertNotIn("xtask", (self.repo / "Cargo.toml").read_text())
        self.assertFalse((self.repo / "aya/original.txt").exists())
        self.assertEqual([p.name for p in self.scratch.iterdir()], ["keep.txt"])

    def test_failed_patch_leaves_destination_untouched(self):
        write(self.upstream, PROGRAMS[-1], "// unsupported future layout\n")
        before = snapshot(self.repo)
        result = self.run_sync()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("validation failed", result.stderr)
        self.assertEqual(snapshot(self.repo), before)
        self.assertEqual([p.name for p in self.scratch.iterdir()], ["keep.txt"])


if __name__ == "__main__":
    unittest.main()

"""Answer validators. Behavior, not string equality."""

from __future__ import annotations

import ctypes as _ct
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass

# Hard limits to keep validation bounded and offline-safe.
# The progress handler fires once per 1000 VM instructions, so 20_000
# invocations ≈ 20M instructions (~1.4s worst case) — ~100x above what
# any legit seeded challenge query needs (seeds have <= 5 rows), but
# well below a CTE bomb.
_MAX_SQL_STEPS = 20_000
_MAX_SQL_ROWS = 5_000  # fetched rows before we reject the result set

_MUTATION_KEYWORDS = (
    "insert",
    "update",
    "delete",
    "drop",
    "create",
    "alter",
    "attach",
    "detach",
    "replace",
    "truncate",
    "grant",
    "revoke",
)


@dataclass
class Result:
    correct: bool
    detail: str = ""
    meta: dict = None  # optional structured info (e.g. row counts for sql_result)

    def __post_init__(self) -> None:
        if self.meta is None:
            self.meta = {}


def validate(challenge, user_input: str) -> Result:
    mode = challenge.validation.get("mode")
    handler = _DISPATCH.get(mode, _unknown)
    return handler(challenge, user_input)


def _unknown(challenge, user_input: str) -> Result:
    return Result(False, f"Unknown validation mode: {challenge.validation.get('mode')}")


def _exact(challenge, user_input: str) -> Result:
    answers = challenge.validation.get("answers") or [challenge.answer.get("value", "")]
    strip = challenge.validation.get("strip", True)
    ci = challenge.validation.get("case_insensitive", False)
    for ans in answers:
        a = ans.strip() if strip else ans
        u = user_input.strip() if strip else user_input
        if ci:
            if a.lower() == u.lower():
                return Result(True)
        elif a == u:
            return Result(True)
    return Result(False, f"Expected one of: {', '.join(answers)}")


def _regex_tester(challenge, user_input: str) -> Result:
    try:
        pattern = re.compile(user_input)
    except re.error as exc:
        return Result(False, f"Invalid regex: {exc}")
    must = challenge.validation.get("must_match", [])
    not_match = challenge.validation.get("must_not_match", [])
    for s in must:
        if not pattern.search(s):
            return Result(False, f"Pattern should match: {s!r}")
    for s in not_match:
        if pattern.search(s):
            return Result(False, f"Pattern should NOT match: {s!r}")
    if not must and not not_match:
        return Result(False, "No test cases defined")
    return Result(True)


def _multiple_choice(challenge, user_input: str) -> Result:
    expected = str(challenge.validation.get("answer_id", "")).strip().lower()
    got = user_input.strip().lower()
    if not expected:
        return Result(False, "Challenge misconfigured: missing answer_id")
    if got == expected:
        return Result(True)
    return Result(False, f"Expected option '{expected}'")


# ---------------------------------------------------------------------------
# test_cases validator (P5/P6): run user code in a sandboxed subprocess and
# check a named function against a list of test cases. Supports Python (always
# available) and JavaScript (via `node`, if installed). This is the "fix-bug"
# / "JS" challenge family. Each run is a separate OS process killed on timeout.
# ---------------------------------------------------------------------------

_TEST_TIMEOUT = 5  # seconds per evaluation


def test_cases_runtime_available(lang: str) -> bool:
    lang = (lang or "python").lower()
    if lang in ("python", "py", ""):
        return True
    if lang in ("js", "javascript"):
        return shutil.which("node") is not None
    return False


_PY_MODULE = """\
import json, sys

__SETUP__

__USERCODE__

fn = globals().get(__FUNC__)
if not callable(fn):
    print(json.dumps({"passed": False, "detail": "no function named " + __FUNC__}))
    sys.exit(0)

passed = True
detail = ""
for c in __CASES__:
    args = c.get("args", [])
    expected = c.get("expected")
    try:
        got = fn(*args)
    except Exception as e:
        passed = False
        detail = "error on %r: %s" % (args, e)
        break
    if got != expected:
        passed = False
        detail = "%r -> got %r, expected %r" % (args, got, expected)
        break

print(json.dumps({"passed": passed, "detail": detail}))
"""

_JS_MODULE = """\
__SETUP__
__USERCODE__
const fn = eval(__FUNC__);
const cases = __CASES__;
(function () {
  let passed = true, detail = "";
  for (const c of cases) {
    try {
      const got = fn(...(c.args || []));
      if (JSON.stringify(got) !== JSON.stringify(c.expected)) {
        passed = false;
        detail = JSON.stringify(c.args) + " -> got " + JSON.stringify(got) + ", expected " + JSON.stringify(c.expected);
        break;
      }
    } catch (e) {
      passed = false; detail = "error: " + e.message; break;
    }
  }
  console.log(JSON.stringify({passed: passed, detail: detail}));
})();
"""


def _test_cases(challenge, user_input: str) -> Result:
    lang = (challenge.validation.get("lang") or "python").lower()
    func = challenge.validation.get("function")
    cases = challenge.validation.get("test_cases") or []
    setup = challenge.validation.get("setup", "") or ""
    if not cases:
        return Result(False, "No test cases defined")
    if not func:
        return Result(False, "test_cases requires validation.function")
    if lang in ("python", "py", ""):
        return _run_python(setup, user_input, func, cases)
    if lang in ("js", "javascript"):
        node = shutil.which("node")
        if not node:
            return Result(False, "JavaScript runtime (node) is not installed")
        return _run_js(node, setup, user_input, func, cases)
    return Result(False, f"Unsupported test_cases language: {lang}")


def _write_temp(ext: str, content: str) -> str:
    fd, path = tempfile.mkstemp(suffix=ext, prefix="skillplay_test_")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


def _exec_file(path: str, cmd_base: list[str]) -> Result:
    cmd = [*cmd_base, path]
    try:
        if sys.platform == "win32":
            # W8 parity: suspended spawn -> Job Object (time + memory caps) -> resume.
            returncode, stdout, stderr = _exec_win(cmd)
        else:
            # G8: preexec_fn caps the child's CPU time and address space so a
            # generated or student program can't hog the machine (POSIX-only).
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_TEST_TIMEOUT,
                preexec_fn=_sandbox_preexec,
            )
            returncode, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return Result(False, f"Code timed out after {_TEST_TIMEOUT}s")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if returncode != 0:
        return Result(False, f"Runtime error: {stderr.strip()[:200]}")
    lines = [ln for ln in stdout.strip().splitlines() if ln.strip()]
    if not lines:
        return Result(False, f"Empty output: {stdout.strip()[:200]}")
    try:
        result = json.loads(lines[-1])
    except Exception:
        return Result(False, f"Bad output: {stdout.strip()[:200]}")
    return Result(bool(result.get("passed", False)), result.get("detail", ""))


# Child-process resource caps (POSIX). The wall-clock guard is the 5s timeout in
# _TEST_TIMEOUT; these add a CPU-time and memory ceiling for defense in depth.
_CHILD_CPU_SECS = 5
_CHILD_AS_MB = 512


def _sandbox_preexec() -> None:
    """POSIX-only: bound CPU time and address space of the spawned child.

    Best-effort — any failure (unsupported limit, permission) is silently
    ignored so grading is never blocked by the sandbox."""
    try:
        import resource as _res

        _res.setrlimit(_res.RLIMIT_CPU, (_CHILD_CPU_SECS, _CHILD_CPU_SECS))
        as_bytes = _CHILD_AS_MB * 1024 * 1024
        _res.setrlimit(_res.RLIMIT_AS, (as_bytes, as_bytes))
    except Exception:
        pass


# --- W8: Windows Job Object sandbox (stdlib ctypes; POSIX uses rlimits) ----
# POSIX gets rlimits via preexec_fn; on Windows the child is created
# *suspended*, assigned to a capped Job Object (CPU time + memory +
# KILL_ON_JOB_CLOSE), then resumed — so the caps hold from instruction #1.
# Everything is best-effort: any Win32 failure falls back to a plain run
# guarded by the wall-clock timeout, so grading is never blocked.

_JOB_LIMITS_INFO = 9  # JobObjectExtendedLimitInformation
_JOB_OBJECT_LIMIT_JOB_TIME = 0x00000004
_JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


class _IO_COUNTERS(_ct.Structure):
    _fields_ = [
        (_n, _ct.c_size_t)
        for _n in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(_ct.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", _ct.c_int64),
        ("PerJobUserTimeLimit", _ct.c_int64),
        ("LimitFlags", _ct.c_uint32),
        ("MinimumWorkingSetSize", _ct.c_size_t),
        ("MaximumWorkingSetSize", _ct.c_size_t),
        ("ActiveProcessLimit", _ct.c_uint32),
        ("Affinity", _ct.c_size_t),  # ULONG_PTR
        ("PriorityClass", _ct.c_uint32),
        ("SchedulingClass", _ct.c_uint32),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(_ct.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", _ct.c_size_t),
        ("JobMemoryLimit", _ct.c_size_t),
        ("PeakProcessMemoryUsed", _ct.c_size_t),
        ("PeakJobMemoryUsed", _ct.c_size_t),
    ]


def _k32():
    """kernel32 with explicit signatures (handles are 64-bit; be precise)."""
    k32 = _ct.windll.kernel32
    k32.CreateJobObjectW.restype = _ct.c_void_p
    k32.CreateJobObjectW.argtypes = (_ct.c_void_p, _ct.c_wchar_p)
    k32.SetInformationJobObject.argtypes = (
        _ct.c_void_p,
        _ct.c_uint32,
        _ct.c_void_p,
        _ct.c_uint32,
    )
    k32.AssignProcessToJobObject.argtypes = (_ct.c_void_p, _ct.c_void_p)
    k32.CreateToolhelp32Snapshot.restype = _ct.c_void_p
    k32.CreateToolhelp32Snapshot.argtypes = (_ct.c_uint32, _ct.c_uint32)
    k32.Thread32First.argtypes = (_ct.c_void_p, _ct.c_void_p)
    k32.Thread32Next.argtypes = (_ct.c_void_p, _ct.c_void_p)
    k32.OpenThread.restype = _ct.c_void_p
    k32.OpenThread.argtypes = (_ct.c_uint32, _ct.c_int, _ct.c_uint32)
    k32.ResumeThread.argtypes = (_ct.c_void_p,)
    k32.CloseHandle.argtypes = (_ct.c_void_p,)
    return k32


def _win_job_begin() -> int | None:
    """Create a Job Object capped at _CHILD_CPU_SECS CPU / _CHILD_AS_MB memory.

    Best-effort: returns None (caller falls back to an unsandboxed run) if any
    Win32 call fails."""
    try:
        k32 = _k32()
        job = k32.CreateJobObjectW(None, None)
        if job is None:
            return None
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.PerJobUserTimeLimit = _CHILD_CPU_SECS * 10_000_000  # 100ns
        info.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_JOB_TIME
            | _JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        cap = _CHILD_AS_MB * 1024 * 1024
        info.ProcessMemoryLimit = cap
        info.JobMemoryLimit = cap
        if not k32.SetInformationJobObject(
            job, _JOB_LIMITS_INFO, _ct.byref(info), _ct.sizeof(info)
        ):
            k32.CloseHandle(job)
            return None
        return job
    except Exception:
        return None


def _win_job_end(job: int | None) -> None:
    if job is None:
        return
    try:
        # KILL_ON_JOB_CLOSE: closing the handle reaps any surviving child.
        _ct.windll.kernel32.CloseHandle(job)
    except Exception:
        pass


def _win_resume_main_thread(pid: int) -> None:
    """Resume the first thread of a CREATE_SUSPENDED process (best-effort)."""
    try:
        k32 = _k32()

        class _THREADENTRY32(_ct.Structure):
            _fields_ = [
                ("dwSize", _ct.c_uint32),
                ("cntUsage", _ct.c_uint32),
                ("th32ThreadID", _ct.c_uint32),
                ("th32OwnerProcessID", _ct.c_uint32),
                ("tpBasePri", _ct.c_long),
                ("tpDeltaPri", _ct.c_long),
                ("dwFlags", _ct.c_uint32),
            ]

        TH32CS_SNAPTHREAD = 0x4
        THREAD_SUSPEND_RESUME = 0x0002
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
        if not snap or snap == 0xFFFFFFFFFFFFFFFF:
            return
        entry = _THREADENTRY32()
        entry.dwSize = _ct.sizeof(_THREADENTRY32)
        tid = 0
        if k32.Thread32First(snap, _ct.byref(entry)):
            while True:
                if entry.th32OwnerProcessID == pid:
                    tid = entry.th32ThreadID
                    break
                if not k32.Thread32Next(snap, _ct.byref(entry)):
                    break
        k32.CloseHandle(snap)
        if not tid:
            return
        h = k32.OpenThread(THREAD_SUSPEND_RESUME, False, tid)
        if h:
            k32.ResumeThread(h)
            k32.CloseHandle(h)
    except Exception:
        pass


def _exec_win(cmd: list[str]) -> tuple[int, str, str]:
    """Run `cmd` inside the capped Job Object (Windows only).

    Fallback path (no Job Object available): a plain run guarded by the
    wall-clock timeout. Returns (returncode, stdout, stderr)."""
    job = _win_job_begin()
    try:
        if job is None:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=_TEST_TIMEOUT)
            return p.returncode, p.stdout, p.stderr
        proc = subprocess.Popen(
            cmd,
            creationflags=0x00000004,  # CREATE_SUSPENDED
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception:
        _win_job_end(job)
        raise
    try:
        try:
            k32 = _k32()
            k32.AssignProcessToJobObject(job, int(proc._handle))
        except Exception:
            pass  # sandbox is best-effort; the wall-clock timeout still applies
        _win_resume_main_thread(proc.pid)
        try:
            stdout, stderr = proc.communicate(timeout=_TEST_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            raise
        rc = proc.returncode if proc.returncode is not None else 1
        return rc, stdout, stderr
    finally:
        _win_job_end(job)


def _run_python(setup: str, code: str, func: str, cases: list) -> Result:
    module = (
        _PY_MODULE.replace("__SETUP__", setup)
        .replace("__USERCODE__", code)
        .replace("__FUNC__", json.dumps(func))
        .replace("__CASES__", repr(cases))
    )
    path = _write_temp(".py", module)
    return _exec_file(path, [sys.executable])


def _run_js(node: str, setup: str, code: str, func: str, cases: list) -> Result:
    module = (
        _JS_MODULE.replace("__SETUP__", setup)
        .replace("__USERCODE__", code)
        .replace("__FUNC__", json.dumps(func))
        .replace("__CASES__", json.dumps(cases))
    )
    path = _write_temp(".js", module)
    return _exec_file(path, [node, "--max-old-space-size=256"])


def _sql_result(challenge, user_input: str) -> Result:
    seed = challenge.context.get("db_seed_sql", "")
    normalize = challenge.validation.get("normalize", True)
    ref = challenge.answer.get("reference_sql", "")
    try:
        _reject_risky_sql(user_input)
        user_rows = _run_sql(seed, user_input)
        ref_rows = _run_sql(seed, ref)
    except sqlite3.Error as exc:
        return Result(False, f"SQL error: {exc}")
    if len(user_rows) > _MAX_SQL_ROWS or len(ref_rows) > _MAX_SQL_ROWS:
        return Result(False, "Query returned too many rows.")
    if normalize:
        user_rows = sorted(user_rows)
        ref_rows = sorted(ref_rows)
    if user_rows == ref_rows:
        return Result(True, "", {"user_rows": len(user_rows), "ref_rows": len(ref_rows)})
    return Result(
        False,
        f"Got {len(user_rows)} rows; expected {len(ref_rows)}.",
        {"user_rows": len(user_rows), "ref_rows": len(ref_rows)},
    )


def _reject_risky_sql(query: str) -> None:
    """Pre-flight guardrails before handing SQL to sqlite.

    - reject multiple statements (a ';' followed by more non-space content)
    - reject obvious write/mutation keywords (defense in depth on top of query_only)
    """
    stripped = query.strip()
    if not stripped:
        raise sqlite3.OperationalError("Empty query")
    # Remove line comments and string literals so ';' / keywords inside them
    # don't trigger false positives.
    cleaned = re.sub(r"--[^\n]*", " ", stripped)
    cleaned = re.sub(r"'[^']*'", "''", cleaned)
    cleaned = re.sub(r'"[^"]*"', '""', cleaned)
    if ";" in cleaned.rstrip(";").rstrip():
        raise sqlite3.OperationalError("Only a single SQL statement is allowed")
    first = re.sub(r"[^a-zA-Z ]", " ", cleaned).split()
    if first:
        head = first[0].lower()
        if head in _MUTATION_KEYWORDS:
            raise sqlite3.OperationalError(f"Write statements are not allowed ({head})")


def _run_sql(seed: str, query: str):
    conn = sqlite3.connect(":memory:")
    steps = {"n": 0}

    def _progress() -> int:
        steps["n"] += 1
        if steps["n"] > _MAX_SQL_STEPS:
            return 1  # non-zero aborts the query
        return 0

    try:
        if seed:
            conn.executescript(seed)
        conn.execute("PRAGMA query_only = ON")  # seed first, then lock to read-only
        conn.set_progress_handler(_progress, 1000)
        cur = conn.execute(query)
        rows = cur.fetchall()
    finally:
        conn.close()
    return rows


_DISPATCH = {
    "exact": _exact,
    "regex_tester": _regex_tester,
    "multiple_choice": _multiple_choice,
    "sql_result": _sql_result,
    "test_cases": _test_cases,
    # V1 freeform tier: write from scratch against hidden tests. Functionally
    # identical to test_cases (same sandboxed runtime) — the only difference is
    # the TUI hides the test list and pre-fills `starter_code` so the player
    # constructs the solution themselves rather than repairing a broken one.
    "freeform": _test_cases,
}

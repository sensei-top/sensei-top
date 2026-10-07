"""Child processes die with the process that started them.

``serve --watch`` runs the watcher in a child process (``live.WatcherProcess``)
so a rebuild never contends with the API for this interpreter's GIL. One rule
holds for that child on every platform: it dies with ``serve``, however
``serve`` ends. ``serve`` can end three ways, and each needs its own
mechanism:

1. **An orderly shutdown**: Ctrl+C, or a SIGTERM that uvicorn turns into one.
   The app's lifespan stops the watcher (``api/app.py``). ``cmd_serve``'s
   ``finally`` cannot: uvicorn 0.52's ``capture_signals`` re-raises SIGTERM
   once its shutdown is done, and the default action ends the process before
   anything after ``uvicorn.run`` runs. That orphaned the watcher on every
   ``kill``.
2. **Killed outright on Linux**: SIGKILL, the OOM killer, a crash. Nothing in
   ``serve`` runs, so the child asks the kernel itself: ``die_with_parent``
   sets ``PR_SET_PDEATHSIG``.
3. **Killed outright on Windows**: ``taskkill /F``, Task Manager. ``serve``
   puts the child in a Job Object that kills what it holds when its last
   handle closes (``kill_with_this_process``). The kernel closes a dead
   process's handles, so ``serve``'s handle to the job closes with it.

macOS has neither kernel mechanism and gets the first only.

Traps:

1. ``PR_SET_PDEATHSIG`` fires when the *thread* that forked the child exits,
   not the process. ``cmd_serve`` starts the watcher from the main thread,
   which lives as long as the process; a child started from a short-lived
   thread would be killed when that thread returned.
2. It covers only a death after the call. A parent that died between the
   fork and the ``prctl`` is never signalled, so ``die_with_parent`` checks
   the parent afterwards and reports it gone.
3. A Windows handle is pointer-sized. Every kernel32 function here declares
   ``c_void_p`` for one: with no ``argtypes``, ctypes passes a Python int as
   a C ``int`` and truncates a 64-bit handle.
4. The child joins the job after it starts, so a process it started in
   between would be outside the job. The watcher starts none.
5. The job's handle must stay open for as long as the child should live, and
   must not be inherited: a child holding a handle to its own job would keep
   the job, and itself, alive. ``CreateJobObjectW`` with no security
   attributes makes a handle no child inherits.
6. ``PR_SET_PDEATHSIG`` watches the child's OS parent. Under ``forkserver``,
   Python 3.14's default start method on Linux, that parent is the
   forkserver, which stays alive while the watcher holds a copy of its alive
   pipe, so the signal never fires. ``WatcherProcess.start`` asks for
   ``fork`` instead, which is safe because ``cmd_serve`` starts the watcher
   before it starts any thread (the refresh and backup threads come after).

``ctypes`` only, rather than a dependency for two system calls.
"""

from __future__ import annotations

import ctypes
import functools
import logging
import multiprocessing
import signal
import sys

log = logging.getLogger(__name__)

# <linux/prctl.h>
PR_SET_PDEATHSIG = 1

# <winnt.h> and <jobapi2.h>
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9  # a JOBOBJECTINFOCLASS value


class _BasicLimits(ctypes.Structure):
    """``JOBOBJECT_BASIC_LIMIT_INFORMATION``."""

    _fields_ = (
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    )


class _IoCounters(ctypes.Structure):
    """``IO_COUNTERS``."""

    _fields_ = (
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    )


class _ExtendedLimits(ctypes.Structure):
    """``JOBOBJECT_EXTENDED_LIMIT_INFORMATION``: 144 bytes on 64-bit Windows,
    112 on 32-bit. ``SetInformationJobObject`` refuses any other length."""

    _fields_ = (
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    )


def die_with_parent() -> bool:
    """Call first thing in a child process. On Linux, asks the kernel to
    SIGKILL this process when its parent dies; elsewhere sets nothing.

    Returns ``False`` when the parent is already gone, on any platform: the
    kernel signals only a death after the call (trap 2), so the caller should
    return rather than run on as an orphan.

    SIGKILL because nothing in the watcher needs a chance to clean up: SQLite
    rolls back whatever transaction a killed process left open, and nothing
    the child runs can catch or ignore it. A failed ``prctl`` is a warning,
    not a reason to stop: the orderly shutdown still reaches the child.
    """
    if sys.platform == "linux":
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            failed = libc.prctl(
                PR_SET_PDEATHSIG,
                ctypes.c_ulong(signal.SIGKILL),
                ctypes.c_ulong(0),
                ctypes.c_ulong(0),
                ctypes.c_ulong(0),
            ) != 0
            reason = ctypes.get_errno()
        except (OSError, AttributeError) as exc:  # no dynamic libc to call
            failed, reason = True, exc
        if failed:
            log.warning("could not tie this process to its parent: %s", reason)
    parent = multiprocessing.parent_process()
    return parent is None or parent.is_alive()


@functools.cache
def _kernel32() -> ctypes.WinDLL:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = ctypes.c_void_p
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
    kernel32.CreateJobObjectW.restype = handle
    kernel32.SetInformationJobObject.argtypes = (
        handle, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
    )
    kernel32.SetInformationJobObject.restype = ctypes.c_int
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.OpenProcess.restype = handle
    kernel32.AssignProcessToJobObject.argtypes = (handle, handle)
    kernel32.AssignProcessToJobObject.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = (handle,)
    kernel32.CloseHandle.restype = ctypes.c_int
    return kernel32


def kill_with_this_process(pid: int) -> int | None:
    """On Windows, put process ``pid`` in a new Job Object that kills it when
    this process dies, however it dies. Elsewhere, ``None``.

    Returns the job's handle: hold it for as long as the child should live,
    then pass it to ``close_job``. ``None`` with a warning when the job could
    not be made or the process not put in it; the child then dies with an
    orderly shutdown only.
    """
    if sys.platform != "win32":
        return None
    kernel32 = _kernel32()
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        error = ctypes.WinError(ctypes.get_last_error())
        log.warning("could not tie process %d to this one: %s", pid, error)
        return None
    limits = _ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    process = None
    try:
        if not kernel32.SetInformationJobObject(
            job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        process = kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel32.AssignProcessToJobObject(job, process):
            raise ctypes.WinError(ctypes.get_last_error())
    except OSError as exc:
        # Nothing is in the job yet, so closing it kills nothing.
        kernel32.CloseHandle(job)
        log.warning("could not tie process %d to this one: %s", pid, exc)
        return None
    finally:
        if process:
            kernel32.CloseHandle(process)
    return job


def close_job(job: int | None) -> None:
    """Close a handle ``kill_with_this_process`` returned. Whatever is still
    in the job dies with it, as it would if this process died holding it."""
    if job is None or sys.platform != "win32":
        return
    _kernel32().CloseHandle(job)

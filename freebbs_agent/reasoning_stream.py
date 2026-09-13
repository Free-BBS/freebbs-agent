"""Request-local model progress without putting reasoning into answers or prompts."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread

current_progress = ContextVar("model_progress", default=None)


class ProgressCancelled(Exception):
    pass


class ModelProgress:
    def __init__(self, emit, cancelled, *, answers=False):
        self.emit = emit
        self.cancelled = cancelled
        self.answers = answers
        self.lock = Lock()
        self.streams = []
        self.calls = 0

    @contextmanager
    def track(self, stream):
        with self.lock:
            self.calls += 1
            call_id = str(self.calls)
            self.streams.append(stream)
        try:
            if self.cancelled.is_set():
                raise ProgressCancelled()
            yield call_id
        finally:
            with self.lock:
                self.streams.remove(stream)
            self._close(stream)

    def send(self, call_id, *, reasoning=None, content=None):
        if self.cancelled.is_set():
            raise ProgressCancelled()
        if isinstance(reasoning, str) and reasoning:
            self.emit({"reasoning_delta": reasoning, "reasoning_id": call_id})
        if self.answers and isinstance(content, str) and content:
            self.emit({"delta": content})

    @staticmethod
    def _close(stream):
        try:
            close = getattr(stream, "close", None)
            if close:
                close()
        except Exception:
            pass

    def close(self):
        self.cancelled.set()
        with self.lock:
            streams = list(self.streams)
        for stream in streams:
            self._close(stream)


def reasoning_events(agent, invocation):
    """Keep the normal run result (routes, RAG metadata, actions) intact."""
    queue = Queue(maxsize=64)
    cancelled = Event()

    def emit(event):
        while not cancelled.is_set():
            try:
                queue.put(event, timeout=0.1)
                return
            except Full:
                continue
        raise ProgressCancelled()

    progress = ModelProgress(emit, cancelled, answers=agent.name == "general_chat")

    def run():
        token = current_progress.set(progress)
        try:
            result = agent.run(invocation)
            emit({"result": result, "done": True})
        except ProgressCancelled:
            pass
        except Exception:
            if not cancelled.is_set():
                try:
                    emit({"error": {"code": "ai_provider_error", "message": "AI provider request failed"}})
                except ProgressCancelled:
                    pass
        finally:
            current_progress.reset(token)

    worker = Thread(target=run, daemon=True, name="max-reasoning-stream")
    worker.start()
    try:
        yield {"status": "thinking"}
        while True:
            try:
                event = queue.get(timeout=10)
            except Empty:
                yield None  # SSE heartbeat, not generated text.
                continue
            yield event
            if event.get("done") or event.get("error"):
                return
    finally:
        progress.close()
